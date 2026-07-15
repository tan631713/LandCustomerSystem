@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 NetBird 私人 VPN 設定
cd /d "%~dp0"

set "NETBIRD_EXE=%ProgramFiles%\NetBird\netbird.exe"
if not exist "%NETBIRD_EXE%" (
  where winget >nul 2>&1
  if errorlevel 1 goto NO_INSTALLER
  echo 尚未安裝 NetBird，正在透過 Windows 套件管理員安裝官方用戶端...
  winget install --id Netbird.Netbird --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto FAILED
)
if not exist "%NETBIRD_EXE%" goto FAILED

set "VPN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if defined VPN_IP goto CONNECTED

echo 即將開啟 NetBird 官方登入頁。
echo 請使用同一個帳號登入筆電與 iPhone。
"%NETBIRD_EXE%" up
if errorlevel 1 goto FAILED

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if not defined VPN_IP goto FAILED

:CONNECTED
echo.
echo NetBird 已連線，這台筆電的私人 IP：%VPN_IP%
echo 下一步請以系統管理員身分執行 allow_netbird_vpn_firewall.bat。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 0

:FAILED
echo.
echo NetBird 尚未完成連線。請確認瀏覽器登入與授權已完成後再執行一次。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 1

:NO_INSTALLER
echo 找不到 Windows 套件管理員 winget，無法自動安裝 NetBird。
echo 請到 https://netbird.io/download 下載官方 Windows 用戶端。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 1
