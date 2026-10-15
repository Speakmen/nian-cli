#!/usr/bin/env bash
# nian-cli 一键安装：装到 /usr/local/bin/nian
set -euo pipefail

DEST="${NIAN_CLI_INSTALL_DIR:-/usr/local/bin}"
REPO="https://raw.githubusercontent.com/Speakmen/nian-cli/main"

TMP="$(mktemp /tmp/nian_cli.XXXXXX)"
trap 'rm -f "$TMP"' EXIT

curl -fsSL "$REPO/nian_cli.py" -o "$TMP"

if [ ! -w "$DEST" ]; then
  SUDO="sudo"
fi
$SUDO install -m 0755 "$TMP" "$DEST/nian"

echo "✓ installed: $DEST/nian"
echo "  下一步: nian --setup"
