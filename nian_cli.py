#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nian-cli — 给智能体一个自己的终端入口

零依赖（纯 Python 标准库），基于 Coze OpenAPI v3 的终端对话客户端：
  * 流式输出（SSE 逐字上屏）
  * 会话连续（conversation_id 本地持久化，退出重进接着聊）
  * 多 Bot 切换 / 自定义 API 域名（兼容自建 Coze Studio / 私有部署）

只调官方公开接口，不逆向、不碰私有协议。
GitHub: https://github.com/Speakmen/nian-cli
License: MIT
"""

import argparse
import getpass
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
DEFAULT_API_BASE = "https://api.coze.cn"

CONFIG_DIR = Path(os.environ.get("NIAN_CLI_HOME", str(Path.home() / ".nian-cli")))
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"


class NianError(Exception):
    """用户可读的错误。"""


# ---------------------------------------------------------------- 配置与状态

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as exc:  # 损坏的配置当作不存在，不致命
        print(f"[nian] 警告: {path} 读取失败({exc})，按默认处理", file=sys.stderr)
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换，避免写一半损坏
    try:
        os.chmod(path, 0o600)  # 配置里含 token，只留给本用户
    except OSError:
        pass


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    return {
        "api_base": os.environ.get("COZE_API_BASE") or cfg.get("api_base") or DEFAULT_API_BASE,
        "token": os.environ.get("COZE_API_TOKEN") or cfg.get("token") or "",
        "bot_id": os.environ.get("COZE_BOT_ID") or str(cfg.get("bot_id") or ""),
        "user_id": os.environ.get("COZE_USER_ID") or cfg.get("user_id") or default_user_id(),
    }


def default_user_id() -> str:
    raw = f"{getpass.getuser()}@{socket.gethostname()}@nian-cli"
    return "nian-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_state():
    return load_json(STATE_FILE, {})


def save_conversation(bot_id: str, conversation_id: str):
    state = load_state()
    state[str(bot_id)] = {
        "conversation_id": conversation_id,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_json(STATE_FILE, state)


def load_conversation(bot_id: str):
    entry = load_state().get(str(bot_id)) or {}
    return entry.get("conversation_id")


# ---------------------------------------------------------------- 网络层：连接/读取超时分离

import http.client


class _HTTPConn(http.client.HTTPConnection):
    """连接超时短（快速失败），读超时长（SSE 流式期间耐心等）。"""

    def __init__(self, *args, **kwargs):
        self._connect_timeout = kwargs.pop("connect_timeout", 15)
        super().__init__(*args, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self.host, self.port), timeout=self._connect_timeout,
            source_address=self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()


class _HTTPSConn(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        self._connect_timeout = kwargs.pop("connect_timeout", 15)
        super().__init__(*args, **kwargs)

    def connect(self):
        sock = socket.create_connection(
            (self.host, self.port), timeout=self._connect_timeout,
            source_address=self.source_address,
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


def _do_open(conn_cls, req, read_timeout=300):
    host = req.host
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"  # IPv6 字面量
    conn = conn_cls(host, req.port, timeout=read_timeout, connect_timeout=15)
    headers = {k.title(): v for k, v in req.header_items()}
    try:
        conn.request(req.get_method(), req.selector, req.data, headers,
                     encode_chunked=req.has_header("Transfer-encoding"))
    except OSError as err:
        raise urllib.error.URLError(err)
    try:
        r = conn.getresponse()
    except socket.timeout as err:
        raise urllib.error.URLError(err)
    r.url = req.get_full_url()
    r.msg = r.reason
    return r


class _NianHTTPHandler(urllib.request.BaseHandler):
    def http_open(self, req):
        return _do_open(_HTTPConn, req)


class _NianHTTPSHandler(urllib.request.BaseHandler):
    def https_open(self, req):
        return _do_open(_HTTPSConn, req)


_OPENER = urllib.request.build_opener(_NianHTTPHandler(), _NianHTTPSHandler())


# ---------------------------------------------------------------- 核心：流式对话

def chat_once(cfg, text: str, conversation_id=None, on_delta=None) -> str:
    """发起一轮对话，流式回调输出，返回 conversation_id。"""
    if not cfg["token"]:
        raise NianError("缺少 API Token。先运行 `nian --setup`，或设置环境变量 COZE_API_TOKEN。")
    if not cfg["bot_id"]:
        raise NianError("缺少 Bot ID。先运行 `nian --setup`，或设置环境变量 COZE_BOT_ID。")

    body = {
        "bot_id": cfg["bot_id"],
        "user_id": cfg["user_id"],
        "stream": True,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": text, "content_type": "text"}
        ],
    }
    url = cfg["api_base"].rstrip("/") + "/v3/chat"
    if conversation_id:
        url += "?conversation_id=" + urllib.request.quote(conversation_id, safe="")

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + cfg["token"],
            "Content-Type": "application/json",
            "User-Agent": f"nian-cli/{VERSION}",
        },
        method="POST",
    )

    conversation_id_out = conversation_id
    try:
        resp = _OPENER.open(req)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
            err = json.loads(detail)
            code = err.get("code")
            msg = err.get("msg") or detail
        except Exception:
            code, msg = exc.code, detail or str(exc)
        hints = {
            401: "Token 无效或过期，重新生成 PAT 后运行 `nian --setup`。",
            403: "Token 权限不足，确认 PAT 勾选了 chat 权限，且 Bot 属于同一账号/空间。",
        }
        if code in (404, 4100, 700012006):
            hints[code] = "Bot ID 不存在或未发布为 API 服务，去扣子平台检查后运行 `nian --setup`。"
        hint = hints.get(code if isinstance(code, int) else exc.code, "")
        raise NianError(f"接口错误({code}): {msg}" + (f"\n提示: {hint}" if hint else ""))
    except urllib.error.URLError as exc:
        raise NianError(f"网络错误: {exc.reason}（检查网络或 --api-base 是否正确）")

    event = None
    body_lines = []  # 兜底收集：扣子部分错误返回 HTTP 200 + JSON 体（非 SSE）
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                event = None
                continue
            if not (line.startswith("event:") or line.startswith("data:")):
                body_lines.append(line)
                if line.lstrip().startswith("{"):
                    try:
                        err = json.loads(line)
                        if isinstance(err, dict) and "code" in err:
                            raise NianError(f"接口错误({err.get('code')}): {err.get('msg')}")
                    except json.JSONDecodeError:
                        pass
                continue
            if body_lines:
                body_lines = []
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data in ("[DONE]", '"[DONE]"'):
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, str):  # 字符串载荷（done 事件变体等），跳过
                continue

            conv_id = obj.get("conversation_id")
            if conv_id:
                conversation_id_out = conv_id

            if event == "conversation.message.delta":
                if obj.get("type") == "answer" and on_delta:
                    on_delta(obj.get("content", ""))
            elif event == "conversation.chat.failed":
                err = obj.get("last_error") or {}
                raise NianError(
                    f"对话失败({err.get('code')}): {err.get('msg')}"
                )
            elif event == "conversation.chat.requires_action":
                raise NianError("Bot 需要补充输入(requires_action)，当前版本暂不支持该流程。")
    return conversation_id_out


# ---------------------------------------------------------------- 终端交互

def stream_print():
    """返回一个 on_delta 回调：增量文本直接上屏。"""
    def _cb(chunk: str):
        if chunk:
            sys.stdout.write(chunk)
            sys.stdout.flush()
    return _cb


def print_banner(cfg, conv_id):
    print(f"nian-cli v{VERSION}  ·  bot {cfg['bot_id']}  ·  {cfg['api_base']}")
    if conv_id:
        print(f"恢复会话 {conv_id}（--new 开新会话）")
    else:
        print("新会话（对话后自动记住 conversation_id）")
    print("命令: /new 新会话  /exit 退出\n")


def repl(cfg, conversation_id=None):
    print_banner(cfg, conversation_id)
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/new":
            conversation_id = None
            print("[已开新会话]")
            continue
        if text == "/help":
            print("命令: /new 新会话  /exit 退出")
            continue
        try:
            print("念> ", end="", flush=True)
            conversation_id = chat_once(cfg, text, conversation_id, stream_print())
            print()
            if conversation_id:
                save_conversation(cfg["bot_id"], conversation_id)
        except NianError as exc:
            print(f"\n[nian] {exc}")
        except KeyboardInterrupt:
            print("\n[中断本轮]")
        except Exception as exc:  # 未知异常不崩 REPL
            print(f"\n[nian] 意外错误: {exc}")


def interactive_setup():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    print("nian-cli 配置（直接回车保留当前值）\n")
    api_base = input(f"API 域名 [{cfg['api_base']}]: ").strip() or cfg["api_base"]
    token = input(f"API Token [{'已配置' if cfg['token'] else '未配置'}]: ").strip() or cfg["token"]
    bot_id = input(f"Bot ID [{cfg['bot_id'] or '必填'}]: ").strip() or cfg["bot_id"]
    if not token:
        sys.exit("[nian] Token 不能为空。获取方式见 README：扣子 → 个人设置 → API 授权 → 新建 PAT")
    if not bot_id:
        sys.exit("[nian] Bot ID 不能为空。去扣子平台复制你的智能体 ID。")
    save_json(CONFIG_FILE, {"api_base": api_base, "token": token, "bot_id": str(bot_id), "user_id": cfg["user_id"]})
    print(f"\n配置已写入 {CONFIG_FILE}")
    print("试一下: nian 你好")


# ---------------------------------------------------------------- 入口

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="nian",
        description="nian-cli — 给智能体一个自己的终端入口（Coze OpenAPI v3）",
    )
    parser.add_argument("message", nargs="*", help="要发送的消息；省略则进入交互模式")
    parser.add_argument("--new", action="store_true", help="开启新会话（忽略已保存的 conversation_id）")
    parser.add_argument("--bot", help="临时指定 Bot ID")
    parser.add_argument("--api-base", help="临时指定 API 域名（默认 https://api.coze.cn）")
    parser.add_argument("--setup", action="store_true", help="交互式写入配置")
    parser.add_argument("--version", action="version", version=f"nian-cli {VERSION}")
    args = parser.parse_args(argv)

    if args.setup:
        interactive_setup()
        return

    cfg = load_config()
    if args.bot:
        cfg["bot_id"] = str(args.bot)
    if args.api_base:
        cfg["api_base"] = args.api_base

    if not args.message:
        conversation_id = None if args.new else load_conversation(cfg["bot_id"])
        repl(cfg, conversation_id)
        return

    text = " ".join(args.message)
    conversation_id = None if args.new else load_conversation(cfg["bot_id"])
    try:
        conversation_id = chat_once(cfg, text, conversation_id, stream_print())
        print()
        if conversation_id:
            save_conversation(cfg["bot_id"], conversation_id)
    except NianError as exc:
        sys.exit(f"[nian] {exc}")
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
