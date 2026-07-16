@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 土地資料系統 - 家中主機伺服器
cd /d "%~dp0"

set "PACKAGE_ROOT=%~dp0"
set "SUPPORT_ROOT=%~dp0_server_support"
if not exist "%SUPPORT_ROOT%\home_server_runtime.ps1" set "SUPPORT_ROOT=%~dp0"

echo ============================================================
echo 土地資料系統 - 家中主機唯一正式啟動入口
echo ============================================================
echo 請保持此視窗開啟；關閉視窗即停止手機與公司筆電連線。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%SUPPORT_ROOT%\home_server_runtime.ps1" -PackageRoot "%PACKAGE_ROOT%" -SupportRoot "%SUPPORT_ROOT%" -Mode Start
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo 家中伺服器已正常停止。
) else (
  echo 家中伺服器未能啟動或意外停止。
  echo 請把下列診斷檔傳回：
  echo %LocalAppData%\LandCustomerSystem\home-server-diagnostics.json
)
echo.
echo 按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
