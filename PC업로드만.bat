@echo off
rem Upload the data already collected on this PC (no collecting). ASCII-only on purpose.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python pc_sync.py --upload-only
echo.
pause
