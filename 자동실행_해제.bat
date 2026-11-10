@echo off
rem Remove auto collect from Windows startup. ASCII-only on purpose.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python pc_sync.py --autorun-off
echo.
pause
