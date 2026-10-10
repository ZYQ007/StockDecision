@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 买入时机
if exist "runtime\python.exe" (
  "runtime\python.exe" "scripts\launcher.py"
) else (
  python "scripts\launcher.py"
)
if errorlevel 1 (
  echo.
  echo 启动失败。请查看上方信息，或参阅 docs\安装与使用.md
  pause
)
