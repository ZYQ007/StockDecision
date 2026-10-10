#!/bin/bash
# .app 入口：打开 Terminal 运行启动器，便于看到日志与 Ctrl+C
ROOT="$(cd "$(dirname "$0")/../Resources" && pwd)"
osascript <<EOF
tell application "Terminal"
  activate
  do script "cd $(printf %q "$ROOT") && ./Start.command; exit"
end tell
EOF
