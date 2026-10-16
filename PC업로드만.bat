@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo PC에서 이미 수집한 공고 데이터를 GitHub 웹페이지에 올립니다 (수집은 하지 않음)
python pc_sync.py --upload-only
if errorlevel 1 echo [!] 실패했습니다. 이 창의 내용을 캡처해 Claude 에게 보여 주세요.
echo.
pause
