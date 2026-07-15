@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 土地資料系統 家中主機伺服器
cd /d "%~dp0"

set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo ============================================================
echo 土地資料系統 - 家中主機一鍵伺服器
echo ============================================================
echo 此視窗是家中唯一正式伺服器。
echo 手機瀏覽器與公司筆電桌面程式都會透過 NetBird 連到這裡。
echo.

echo [1/5] 檢查 NetBird 安裝與連線...
call "%~dp0setup_netbird_vpn.bat" --no-pause
if errorlevel 1 goto FAILED

set "VPN_IP="
set "NETBIRD_EXE=%ProgramFiles%\NetBird\netbird.exe"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $ip = & $env:NETBIRD_EXE status --ipv4; if ($ip -match '^100\.\d+\.\d+\.\d+$') { $ip }"`) do set "VPN_IP=%%I"
if not defined VPN_IP goto FAILED

powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8732 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 goto ALREADY_RUNNING

echo.
echo [2/5] 檢查 PostgreSQL 服務與私人 VPN 防火牆...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0home_server_preflight.ps1" -Mode Check
set "PREFLIGHT_CODE=%ERRORLEVEL%"
if "%PREFLIGHT_CODE%"=="0" goto PREFLIGHT_READY
if "%PREFLIGHT_CODE%"=="20" goto POSTGRES_NOT_INSTALLED
if "%PREFLIGHT_CODE%"=="30" goto FAILED
if not "%PREFLIGHT_CODE%"=="10" goto FAILED

echo.
echo 需要啟動 PostgreSQL 服務或更新防火牆。
echo Windows 將詢問一次系統管理員權限，請按「是」。
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0home_server_preflight.ps1" -Mode Repair
if errorlevel 1 goto FAILED

:PREFLIGHT_READY
echo.
echo [3/5] 檢查 PostgreSQL 專案資料庫連線...
call :CHECK_POSTGRESQL
if not errorlevel 1 goto POSTGRES_READY

echo.
echo 尚未完成這台主機的 PostgreSQL 專案設定。
echo 接下來會詢問 PostgreSQL 管理員 postgres 的密碼；這通常只需設定一次。
call "%~dp0setup_local_postgresql.bat" --no-pause
if errorlevel 1 goto FAILED

echo.
echo 正在重新檢查 PostgreSQL...
call :CHECK_POSTGRESQL
if errorlevel 1 goto FAILED

:POSTGRES_READY
echo.
echo [4/5] 環境檢查完成。
echo [5/5] 正在建立 HTTPS、執行備份並啟動正式伺服器...
echo.
call "%~dp0start_mobile_server_vpn.bat" --prepared
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%

:CHECK_POSTGRESQL
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --check
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --check
)
exit /b %ERRORLEVEL%

:ALREADY_RUNNING
echo.
echo 家中伺服器已經在執行，不需要重複開啟。
echo 手機請開啟：https://%VPN_IP%:8732/mobile/
echo 公司筆電的 home_server_ip.txt 請填入：%VPN_IP%
echo.
echo 按任意鍵關閉這個重複啟動視窗；原本的伺服器不會被關閉。
pause >nul
exit /b 0

:POSTGRES_NOT_INSTALLED
echo.
echo 找不到 PostgreSQL Windows 服務。
echo 請先在家中主機安裝 PostgreSQL，再重新開啟 start_home_server_vpn.bat。
goto FAILED

:FAILED
echo.
echo 家中伺服器尚未啟動，請依上方訊息處理後再執行一次。
echo 按任意鍵關閉視窗...
pause >nul
exit /b 1
