@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 NetBird iPhone HTTPS 伺服器
cd /d "%~dp0"

set "NETBIRD_EXE=%ProgramFiles%\NetBird\netbird.exe"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"
set "CERT_DIR=%LocalAppData%\LandCustomerSystem\certificates"
set "SERVER_CERT=%CERT_DIR%\land-customer-server-cert.pem"
set "SERVER_KEY=%CERT_DIR%\land-customer-server-key.pem"

if not exist "%NETBIRD_EXE%" (
  echo 找不到 NetBird，請先執行 setup_netbird_vpn.bat。
  goto FAILED
)

set "VPN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if not defined VPN_IP (
  echo NetBird 尚未連線，正在開啟登入頁...
  "%NETBIRD_EXE%" up
  if errorlevel 1 goto FAILED
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
)
if not defined VPN_IP goto FAILED

echo 正在建立包含 NetBird IP 的 HTTPS 憑證...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --setup-https --prefer-vpn
) else (
  "%PYTHON_EXE%" setup_local_https.py --prefer-vpn
)
if errorlevel 1 goto FAILED

echo 正在檢查 PostgreSQL...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --check
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --check
)
if errorlevel 1 (
  echo.
  echo PostgreSQL 檢查未通過。
  echo 請確認 PostgreSQL 服務正在執行；若已更換主機或 Windows 使用者，
  echo 請先執行 setup_local_postgresql.bat 重新建立這台主機的安全連線設定。
  goto FAILED
)

echo 正在檢查每日自動備份...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --backup-if-due-hours 24 --backup-label auto
) else (
  "%PYTHON_EXE%" backup_postgresql.py --label auto --if-due-hours 24
)
if errorlevel 1 goto FAILED

echo.
echo NetBird 私人 VPN 已就緒。
echo iPhone 連上 NetBird 後請開啟：
echo https://%VPN_IP%:8732/mobile/
echo.
echo 若無法連線，請先以系統管理員身分執行 allow_netbird_vpn_firewall.bat。
echo 不要在路由器開放 8732、8733 或 PostgreSQL 5432。
echo.

if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --lan --prefer-vpn --ssl-certfile "%SERVER_CERT%" --ssl-keyfile "%SERVER_KEY%"
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --lan --prefer-vpn --ssl-certfile "%SERVER_CERT%" --ssl-keyfile "%SERVER_KEY%"
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto FAILED_WITH_CODE
goto FINISH

:FAILED
set "EXIT_CODE=1"
:FAILED_WITH_CODE
echo.
echo 私人 VPN 伺服器啟動失敗，請依上方訊息檢查。

:FINISH
echo.
echo 按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
