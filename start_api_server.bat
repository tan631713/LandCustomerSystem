@echo off
setlocal
cd /d "%~dp0"
python start_api_server.py --check
if errorlevel 1 (
  echo.
  echo API 設定檢查失敗。
  pause
  exit /b 1
)
python start_api_server.py
