@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 土地資料系統 公司筆電遠端桌面版
cd /d "%~dp0"

set "DESKTOP_EXE=%~dp0LandCustomerSystem\LandCustomerSystem.exe"
set "SERVER_IP_FILE=%~dp0home_server_ip.txt"
set "CA_CERT=%~dp0land-customer-local-ca.pem"
set "DIAGNOSTICS=%LocalAppData%\LandCustomerSystem\client-network-diagnostics.json"

echo ============================================================
echo 土地資料系統 - 公司筆電一鍵客戶端
echo ============================================================
echo.

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

set "HOME_SERVER_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$value=(Get-Content -LiteralPath $env:SERVER_IP_FILE -Raw).Trim(); if($value){$value}"`) do set "HOME_SERVER_IP=%%I"
if not defined HOME_SERVER_IP (
  echo home_server_ip.txt 內容為空白。
  goto FAILED
)

echo [1/3] 檢查 NetBird 安裝、登入與連線...
call "%~dp0setup_netbird_client.bat" --no-pause
if errorlevel 1 goto FAILED

echo.
echo [2/3] 驗證家中主機、HTTPS 憑證與 PostgreSQL API...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0company_client_preflight.ps1" -ServerIp "%HOME_SERVER_IP%" -DesktopExe "%DESKTOP_EXE%" -Port 8732 -DiagnosticsPath "%DIAGNOSTICS%"
if errorlevel 1 goto FAILED

set "LAND_CUSTOMER_DESKTOP_BACKEND=postgresql"
set "LAND_CUSTOMER_API_URL=https://%HOME_SERVER_IP%:8732"
set "LAND_CUSTOMER_API_CA_CERT=%CA_CERT%"

echo.
echo [3/3] 正在開啟完整桌面程式：https://%HOME_SERVER_IP%:8732
echo 公司筆電不會啟動 PostgreSQL，也不會建立第二份正式資料庫。
"%DESKTOP_EXE%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto FAILED_WITH_CODE
goto FINISH

:FAILED
set "EXIT_CODE=1"
:FAILED_WITH_CODE
echo.
echo 遠端桌面程式啟動失敗。
echo 請確認家中主機的 start_home_server_vpn.bat 視窗、NetBird 與網路都保持運作。
echo 可提供以下診斷檔協助排查：
echo %DIAGNOSTICS%

:FINISH
echo.
echo 按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
