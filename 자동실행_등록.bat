@echo off
rem Register auto collect at Windows startup (asks wait minutes). ASCII-only on purpose.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python pc_sync.py --autorun-set
echo.
pause
