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
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo 設定未完成，請查看上方錯誤訊息。
) else (
  echo.
  echo PostgreSQL 專案資料庫設定完成，可以繼續啟動伺服器。
)
if /I not "%~1"=="--no-pause" pause >nul
endlocal & exit /b %EXIT_CODE%
