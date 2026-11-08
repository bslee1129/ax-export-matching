@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo  노트북을 켜면 일정 시간 뒤 공고 수집·업로드를 자동 실행하도록 등록
echo  (윈도 시작프로그램에 등록 — 관리자 권한 필요 없음, 하루 한 번만 실행)
echo ============================================================
set MIN=10
set /p MIN=노트북을 켠 뒤 몇 분 뒤에 실행할까요? [그냥 Enter = 10분]: 
echo %MIN%| findstr /r "^[0-9][0-9]*$" >nul || goto bad
if not exist data mkdir data
>"data\auto_wait_min.txt" echo %MIN%
if exist "data\auto_disabled.txt" del "data\auto_disabled.txt"
set "F=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AX_auto_collect.cmd"
>"%F%" echo @echo off
>>"%F%" echo chcp 65001 ^>nul
>>"%F%" echo start "AX 공고 자동수집" /min "%~dp0PC자동수집_시작.bat"
echo.
echo  [완료] 노트북을 켜면 %MIN%분 뒤에 자동으로 공고를 수집해 올립니다.
echo         작업 표시줄에 'AX 공고 자동수집' 창이 최소화되어 나타납니다.
echo         해제하려면 자동실행_해제.bat 을 실행하세요.
pause
exit /b 0

:bad
echo  숫자만 입력하세요. 예: 10
pause
exit /b 1
