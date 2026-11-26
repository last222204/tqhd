@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 우산 T6

rem 프로그램 환경은 OneDrive 밖(사용자 폴더)에 둔다. 동기화로 느려지지 않게.
set "VENV=%USERPROFILE%\.venvs\umbrella_t6"
set "PY=%VENV%\Scripts\python.exe"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [오류] Python 이 설치되어 있지 않습니다.
  echo https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행해 주세요.
  echo 설치할 때 "Add python.exe to PATH" 에 꼭 체크하세요.
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo 처음 실행이라 준비 중입니다. 몇 분 걸릴 수 있어요...
  python -m venv "%VENV%"
  if errorlevel 1 goto fail
)

fc /b requirements.txt "%VENV%\req.stamp" >nul 2>nul
if errorlevel 1 (
  echo 필요한 프로그램을 설치하는 중입니다...
  "%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto fail
  copy /y requirements.txt "%VENV%\req.stamp" >nul
)

rem Streamlit 첫 실행 때 묻는 이메일 질문 건너뛰기
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo  ===============================================
echo   우산 T6 를 켭니다. 브라우저가 자동으로 열립니다.
echo   끄려면 이 창을 닫으세요.
echo  ===============================================
echo.
"%PY%" -X utf8 -m streamlit run app.py
pause
exit /b 0

:fail
echo.
echo [오류] 준비에 실패했습니다. 인터넷 연결을 확인하고 다시 실행해 주세요.
pause
exit /b 1
