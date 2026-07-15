@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 NetBird 客戶端設定

set "NETBIRD_EXE=%ProgramFiles%\NetBird\netbird.exe"
if not exist "%NETBIRD_EXE%" (
  where winget >nul 2>&1
  if errorlevel 1 goto NO_INSTALLER
  echo 尚未安裝 NetBird，正在安裝官方 Windows 用戶端...
  winget install --id Netbird.Netbird --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto FAILED
)
if not exist "%NETBIRD_EXE%" goto FAILED

set "VPN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if defined VPN_IP goto CONNECTED

echo 即將開啟 NetBird 官方登入頁。
echo 公司筆電請使用與家中主機、iPhone 相同的帳號登入。
"%NETBIRD_EXE%" up
if errorlevel 1 goto FAILED
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if not defined VPN_IP goto FAILED

:CONNECTED
echo.
echo NetBird 客戶端已連線：%VPN_IP%
echo 公司筆電不需要建立伺服器防火牆規則，也不需要安裝 PostgreSQL。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 0

:NO_INSTALLER
echo 找不到 winget，請到 https://netbird.io/download 安裝官方 NetBird。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 1

:FAILED
echo.
echo NetBird 客戶端設定失敗，請確認安裝與瀏覽器登入已完成。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 1
