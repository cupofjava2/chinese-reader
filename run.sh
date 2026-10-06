#!/bin/sh
# 啟動中文文字閱讀器
# 用法：./run.sh [port]
cd "$(dirname "$0")" || exit 1
PORT="${1:-5000}"

# 安裝依賴（含可選的 edge-tts 引擎；沒網絡時會略過，功能自動降級為 macOS 系統語音）
uv sync --extra edge --quiet 2>/dev/null || uv sync --quiet

echo "啟動中… http://127.0.0.1:$PORT"
uv run python app.py "$PORT"
