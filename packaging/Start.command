#!/bin/bash
# macOS：双击启动（若提示无法打开，在终端执行：chmod +x Start.command）
cd "$(dirname "$0")"
export PYTHONUTF8=1

if [[ -x "runtime/bin/python3" ]]; then
  exec "runtime/bin/python3" "scripts/launcher.py"
elif [[ -x "runtime/bin/python" ]]; then
  exec "runtime/bin/python" "scripts/launcher.py"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 "scripts/launcher.py"
else
  echo "未找到 Python。请使用维护者打好的 macOS 便携包，或先安装 Python 3.10+。"
  read -r -p "按回车键退出…"
  exit 1
fi
