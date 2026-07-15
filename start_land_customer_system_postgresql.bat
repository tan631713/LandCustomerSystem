@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 PostgreSQL 正式版
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "DESKTOP_EXE=%~dp0LandCustomerSystem\LandCustomerSystem.exe"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"
set "LAND_CUSTOMER_DESKTOP_BACKEND=postgresql"
set "LAND_CUSTOMER_API_URL=https://127.0.0.1:8732"
set "LAND_CUSTOMER_API_CA_CERT=%LocalAppData%\LandCustomerSystem\certificates\land-customer-local-ca.pem"

echo 正在檢查 PostgreSQL 與資料...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --check
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --check
)
if errorlevel 1 goto FAILED

start "土地資料系統 PostgreSQL HTTPS API" cmd /k call "%~dp0start_mobile_server_https.bat"
timeout /t 3 /nobreak >nul

if exist "%DESKTOP_EXE%" (
  "%DESKTOP_EXE%"
) else (
  "%PYTHON_EXE%" "%~dp0customer_ui_qt.py"
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo 桌面程式結束，錯誤代碼：%EXIT_CODE%
goto FINISH

:FAILED
set "EXIT_CODE=1"
echo PostgreSQL 正式版啟動前檢查失敗，請查看上方錯誤訊息。

:FINISH
echo.
echo 桌面程式已關閉。API 視窗可另外關閉。
echo 按任意鍵關閉這個視窗...
pause >nul
exit /b %EXIT_CODE%
