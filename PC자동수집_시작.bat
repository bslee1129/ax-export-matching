@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem ── 노트북을 켠 뒤 일정 시간 기다렸다가 공고 수집·업로드 (윈도 시작프로그램에서 자동 실행)
rem    기다리는 시간(분)은 data\auto_wait_min.txt — 자동실행_등록.bat 으로 바꿀 수 있음
set WAIT_MIN=10
if exist "data\auto_wait_min.txt" set /p WAIT_MIN=<"data\auto_wait_min.txt"
set /a WAIT_SEC=%WAIT_MIN%*60
title AX 공고 자동수집 - %WAIT_MIN%분 뒤 시작
echo ============================================================
echo  노트북을 켠 뒤 %WAIT_MIN%분 기다렸다가 공고 수집·업로드를 시작합니다.
echo  - 지금 바로 시작: 아무 키나 누르기
echo  - 오늘은 건너뛰기: 이 창 닫기
echo ============================================================
timeout /t %WAIT_SEC%
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
set LAST=
if exist "data\auto_last_run.txt" set /p LAST=<"data\auto_last_run.txt"
if "%LAST%"=="%TODAY%" goto already
if not exist data mkdir data
>"data\auto_last_run.txt" echo %TODAY%
title AX 공고 자동수집 - 실행 중
call "%~dp0PC수집_업로드.bat"
exit /b 0

:already
echo.
echo  오늘 %TODAY% 은 이미 자동 수집을 했습니다. 하루 한 번만 자동 실행합니다.
echo  다시 수집하려면 PC수집_업로드.bat 을 직접 실행하세요.
timeout /t 20
exit /b 0
