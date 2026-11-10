@echo off
rem AX auto collect launcher (run from Windows Startup).
rem Keep this file ASCII-only: Korean text in .bat lines breaks cmd parsing. Messages come from pc_sync.py
setlocal
cd /d "%~dp0"
title AX auto collect
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python -m pip install -q -r requirements.txt >nul 2>nul
python pc_sync.py --auto
echo.
pause
