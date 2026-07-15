@echo off
setlocal
chcp 65001 >nul
title 安裝土地資料系統 iPhone 憑證
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"

echo 即將只在區域網路提供公開 CA 憑證，不會提供資料庫或私鑰。
echo 安裝完成後回到此視窗按 Ctrl+C 即可停止。
echo.
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --install-iphone-certificate
) else (
  "%PYTHON_EXE%" install_iphone_certificate_server.py
)
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo 憑證安裝服務已停止。按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
