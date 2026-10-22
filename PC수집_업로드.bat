@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo  지원사업 공고 PC 수집 후 GitHub 웹페이지에 올리기
echo  (기업마당·KOTRA 는 해외 서버 접속을 막아 PC에서 수집)
echo ============================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python 이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치하세요.
  pause
  exit /b 1
)
echo [준비] 필요한 프로그램 확인
python -m pip install -q -r requirements.txt
if not defined AX_SOURCES set AX_SOURCES=jexport,jbexport,at,kotra,bizinfo
python pc_sync.py --sources %AX_SOURCES% %*
if errorlevel 1 (
  echo.
  echo [!] 실패했습니다. 이 창의 내용을 캡처해 Claude 에게 보여 주세요.
)
echo.
pause
