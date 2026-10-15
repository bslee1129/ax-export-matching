@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo  지원사업 공고 PC 수집 후 GitHub 웹페이지에 올리기
echo  (기업마당·KOTRA 는 해외 서버 접속을 막아 PC에서 수집)
echo ============================================================

where git >nul 2>nul
if errorlevel 1 (
  echo [!] Git 이 설치되어 있지 않습니다.
  echo     https://git-scm.com/download/win 에서 설치 후 다시 실행하세요. 설치 옵션은 기본값 그대로 두면 됩니다.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python 이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치하세요.
  pause
  exit /b 1
)

if not exist ".git" (
  echo [준비] 이 폴더를 GitHub 저장소와 연결합니다. 처음 한 번만 실행됩니다.
  git init -q
  git remote add origin https://github.com/bslee1129/ax-export-matching.git
  git fetch -q origin main || goto :fail
  git reset -q --hard origin/main || goto :fail
  git branch -M main
  git branch -q -u origin/main
)
git config user.name "bslee1129"
git config user.email "bslee1129@users.noreply.github.com"

if not defined AX_SOURCES set AX_SOURCES=jexport,at,kotra,bizinfo

echo [1/4] GitHub 최신 데이터 받기
git pull -q --rebase origin main || goto :fail

echo [2/4] 필요한 프로그램 확인
python -m pip install -q -r requirements.txt

echo [3/4] 공고 수집 (기업마당·KOTRA·aT·수출e음) — 처음에는 10~20분 걸릴 수 있습니다
python ax_collect.py --insecure --sources %AX_SOURCES%
python export_static.py || goto :fail

echo [4/4] GitHub 에 올리기 (처음 한 번은 GitHub 로그인 창이 뜹니다)
git add data/ax_notices.db docs/data
git diff --cached --quiet && (echo     변경 없음 — 올릴 내용이 없습니다. & goto :done)
git commit -q -m "PC 수집 공고 데이터 갱신 %date% %time:~0,5%"
git pull -q --rebase origin main || goto :fail
git push -q origin main || goto :fail
echo.
echo  완료! 1~2분 뒤 웹페이지에 반영됩니다: https://bslee1129.github.io/ax-export-matching/

:done
echo.
pause
exit /b 0

:fail
echo.
echo [!] 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
echo     같은 오류가 반복되면 이 창의 내용을 캡처해 Claude 에게 보여 주세요.
pause
exit /b 1
