@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"

echo 正在建立區域網路 HTTPS 憑證...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --setup-https
) else (
"%PYTHON_EXE%" setup_local_https.py
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo HTTPS 憑證建立失敗，請保留這個畫面並回報錯誤內容。
  pause >nul
  exit /b %EXIT_CODE%
)

echo.
echo 憑證已建立。請依「iPhone連線說明.txt」安裝公開 CA 憑證。
echo 按任意鍵關閉這個視窗...
pause >nul
exit /b 0
