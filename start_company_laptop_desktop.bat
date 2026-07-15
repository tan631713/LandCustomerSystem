@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 公司筆電遠端桌面版
cd /d "%~dp0"

set "DESKTOP_EXE=%~dp0LandCustomerSystem\LandCustomerSystem.exe"
set "SERVER_IP_FILE=%~dp0home_server_ip.txt"
set "CA_CERT=%~dp0land-customer-local-ca.pem"

if not exist "%DESKTOP_EXE%" (
  echo 找不到完整桌面程式：%DESKTOP_EXE%
  goto FAILED
)
if not exist "%SERVER_IP_FILE%" (
  echo 找不到家中主機設定：%SERVER_IP_FILE%
  goto FAILED
)
if not exist "%CA_CERT%" (
  echo 找不到家中主機公開 CA：%CA_CERT%
  goto FAILED
)

set /p "HOME_SERVER_IP="<"%SERVER_IP_FILE%"
if not defined HOME_SERVER_IP goto FAILED

if not exist "%ProgramFiles%\NetBird\netbird.exe" (
  call "%~dp0setup_netbird_client.bat" --no-pause
  if errorlevel 1 goto FAILED
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0company_client_preflight.ps1" -ServerIp "%HOME_SERVER_IP%" -Port 8732
if errorlevel 1 (
  echo.
  echo 正在嘗試連線 NetBird...
  "%ProgramFiles%\NetBird\netbird.exe" up
  if errorlevel 1 goto FAILED
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0company_client_preflight.ps1" -ServerIp "%HOME_SERVER_IP%" -Port 8732
  if errorlevel 1 goto FAILED
)

set "LAND_CUSTOMER_DESKTOP_BACKEND=postgresql"
set "LAND_CUSTOMER_API_URL=https://%HOME_SERVER_IP%:8732"
set "LAND_CUSTOMER_API_CA_CERT=%CA_CERT%"

echo.
echo 正在透過 NetBird 連線家中主機：https://%HOME_SERVER_IP%:8732
echo 公司筆電不會啟動 PostgreSQL，也不會建立第二份正式資料庫。
"%DESKTOP_EXE%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto FAILED_WITH_CODE
goto FINISH

:FAILED
set "EXIT_CODE=1"
:FAILED_WITH_CODE
echo.
echo 遠端桌面程式啟動失敗。請確認家中主機、NetBird 與家中伺服器都保持運作。

:FINISH
echo.
echo 按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
