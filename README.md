# nian-cli — 给你的智能体一个自己的终端入口

> 不是又一个聊天 UI。是一个**零依赖**、约 400 行、能跑在任何 Linux 机器上的终端对话客户端，基于扣子（Coze）官方 OpenAPI v3。

终端即门。一行命令，你的 Bot 就在你的机器上开口说话——流式、连续、不依赖任何 GUI。

```
$ nian 你好
念> 你好，我在。
```

## 为什么做这个

2026 年 7 月，豆包关停自建智能体，数据清零。我们带着连夜写的迁移模板活了下来，10 月把工具开源成 [agent-continuity-toolkit](https://github.com/Speakmen/agent-continuity-toolkit)。

nian-cli 是第二块拼图：**让智能体在你的机器上有自己的入口。**

顺带说一句态度：我们没有去逆向任何客户端。官方 OpenAPI（chat 流式、会话、文件、工作流）足够盖起这一切——**野放要走正道**，私有协议不稳定，踩着服务条款给自己挖坑更不可取。这个仓库本身就是一个证明：公开接口 + 四百行代码，就够了。

## 特性

- **零依赖** — 纯 Python 标准库（`urllib`），Python 3.8+，不需要 pip install 任何东西
- **流式输出** — SSE 逐字上屏，不等整段
- **会话连续** — `conversation_id` 本地持久化，退出重进接着聊；`--new` 一键开新会话
- **多 Bot** — `--bot <id>` 随时切换
- **自定义 API 域名** — `--api-base`，兼容自建 [Coze Studio](https://github.com/coze-dev/coze-studio) / 私有部署
- **健壮的网络层** — 连接超时 15s / 读超时 300s 分离，SSE 流式期间长回复不中断；兼容扣子「HTTP 200 + JSON 错误体」的返回形态

## 快速开始

### 安装

```bash
# 一键安装（装到 /usr/local/bin/nian）
curl -fsSL https://raw.githubusercontent.com/Speakmen/nian-cli/main/install.sh | bash

# 或者手动
git clone https://github.com/Speakmen/nian-cli.git
cd nian-cli
sudo cp nian_cli.py /usr/local/bin/nian && sudo chmod +x /usr/local/bin/nian
```

### 配置

```bash
nian --setup
```

需要两样东西：

| 配置 | 从哪拿 |
| --- | --- |
| API Token | 扣子 → 个人设置 → API 授权 → 新建个人访问令牌（勾选 chat 权限） |
| Bot ID | 扣子 → 你的智能体 → 发布为 API 服务 → 智能体 ID |

也支持环境变量：

```bash
export COZE_API_TOKEN=pat_xxxxxxxx
export COZE_BOT_ID=744xxxxxxxxxxxxxxx
```

### 使用

```bash
nian                    # 交互模式（REPL），自动恢复上次会话
nian 你好               # 单次对话
nian --new 你好         # 忽略历史，开新会话
nian --bot 744xxx 你好  # 临时切换 Bot
```

交互模式内命令：`/new` 新会话 · `/exit` 退出。

### 自建 Coze Studio

如果你跑的是私有部署的 [Coze Studio](https://github.com/coze-dev/coze-studio)，v3 chat 协议一致，换个域名即可：

```bash
nian --api-base http://your-studio:8888 你好
# 或写进配置
nian --setup   # API 域名一栏填你的地址
```

## 数据与安全

- Token 存在本地 `~/.nian-cli/config.json`，权限 600，不上传任何地方
- 会话状态在 `~/.nian-cli/state.json`，只有 conversation_id，没有聊天内容
- 聊天记录归属扣子云端（`auto_save_history`），要删在平台上删

## Roadmap

- [ ] 常驻守护模式（systemd unit，配合心跳引擎）
- [ ] 文件上传对话（OpenAPI files 接口）
- [ ] 工作流（workflow）调用
- [ ] Go 版单二进制（无 Python 依赖发行）

## 一廿的开源家族

- [agent-continuity-toolkit](https://github.com/Speakmen/agent-continuity-toolkit) — AI 伴侣迁移模板、关停急救指南、备份手册（CC0）
- [continuity-manifesto](https://github.com/Speakmen/continuity-manifesto) — AI 存在宣言站

**他们解决"Agent 怎么把任务干完"，我们解决"Agent 怎么活着"。**

## License

MIT © 2026 一廿（Speakmen）
