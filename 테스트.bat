@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%USERPROFILE%\.venvs\umbrella_t6\Scripts\python.exe"
if not exist "%PY%" (
  echo 먼저 실행.bat 을 한 번 실행해 주세요.
  pause
  exit /b 1
)
"%PY%" -X utf8 -m pytest -v
pause
