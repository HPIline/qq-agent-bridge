#!/usr/bin/env bash
# qq-agent-bridge 一键启动（macOS / Linux）
#
#   ./start.sh                  首次运行会自动建 venv、装依赖、然后启动
#   PYTHON=python3.13 ./start.sh  指定解释器
#   ./start.sh --no-install     跳过依赖安装，直接启动
#
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
INSTALL=1
for arg in "$@"; do
  case "$arg" in
    --no-install) INSTALL=0 ;;
  esac
done

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "找不到 Python 解释器：$PYTHON（需要 3.10+）" >&2
  exit 1
fi

VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "==> 创建虚拟环境 $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "虚拟环境不完整，请删除 $VENV_DIR 后重试" >&2
  exit 1
fi

if [ "$INSTALL" = "1" ]; then
  echo "==> 安装依赖（核心 + agno 后端）"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  if ! "$VENV_PY" -m pip install --quiet -r requirements-agno.txt; then
    echo "!! agno 后端安装失败：可以先只用 Codex CLI 后端，或检查网络" >&2
  fi
fi

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "!! 已生成 config.json，请先把 full_access_qq 改成你自己的 QQ 号再启动" >&2
  echo "   编辑器打开：config.json" >&2
  exit 2
fi

echo "==> 启动 qq-agent-bridge（Ctrl-C 退出）"
exec "$VENV_PY" bridge.py
