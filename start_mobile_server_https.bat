@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 iPhone HTTPS 伺服器
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"
set "CERT_DIR=%LocalAppData%\LandCustomerSystem\certificates"
set "SERVER_CERT=%CERT_DIR%\land-customer-server-cert.pem"
set "SERVER_KEY=%CERT_DIR%\land-customer-server-key.pem"

echo 正在檢查 HTTPS 憑證與目前區網 IP...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --setup-https
) else (
  "%PYTHON_EXE%" setup_local_https.py
)
if errorlevel 1 goto FAILED

echo 正在檢查 PostgreSQL 與資料...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --check
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --check
)
if errorlevel 1 goto FAILED

echo 正在檢查每日 PostgreSQL 備份...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --backup-if-due-hours 24 --backup-label auto
) else (
  "%PYTHON_EXE%" backup_postgresql.py --label auto --if-due-hours 24
)
if errorlevel 1 goto FAILED

echo.
echo 檢查成功，正在啟動 iPhone 行動版...
echo 請保持這個視窗開啟；關閉視窗即可停止手機連線。
echo 若剛切換 Wi-Fi 或手機熱點，請使用下方「本次啟動」重新顯示的 IP。
echo 手機瀏覽器必須完整輸入 https://IP:8732/mobile/，不可只輸入 IP。
echo 手機熱點首次使用前，請以系統管理員身分執行 allow_private_network_firewall.bat。
echo.
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --lan --ssl-certfile "%SERVER_CERT%" --ssl-keyfile "%SERVER_KEY%"
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --lan --ssl-certfile "%SERVER_CERT%" --ssl-keyfile "%SERVER_KEY%"
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto FAILED_WITH_CODE
goto FINISH

:FAILED
set "EXIT_CODE=1"
:FAILED_WITH_CODE
echo.
echo iPhone 伺服器啟動失敗，請查看上方錯誤訊息。

:FINISH
echo.
echo 按任意鍵關閉這個視窗...
pause >nul
exit /b %EXIT_CODE%
