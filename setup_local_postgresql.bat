@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --setup-postgresql
) else (
  "%PYTHON_EXE%" setup_local_postgresql_gui.py
)
if errorlevel 1 (
  echo.
  echo 設定未完成，請查看上方錯誤訊息。
) else (
  echo.
  echo 設定完成，請回到 Codex。
)
pause >nul
endlocal
