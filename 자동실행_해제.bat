@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "F=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AX_auto_collect.cmd"
if exist "%F%" del "%F%"
if not exist data mkdir data
>"data\auto_disabled.txt" echo 사용자가 자동 실행을 해제함
echo  [완료] 노트북을 켤 때 자동 수집하지 않습니다. 다시 켜려면 자동실행_등록.bat 을 실행하세요.
pause
