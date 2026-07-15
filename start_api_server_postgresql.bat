@echo off
chcp 65001 >nul
title 土地資料系統 PostgreSQL API
cd /d "%~dp0"
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"

echo 正在檢查 PostgreSQL 與資料...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres --check
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres --check
)
if errorlevel 1 goto CHECK_FAILED

echo 正在檢查每日 PostgreSQL 備份...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --backup-if-due-hours 24 --backup-label auto
) else (
  "%PYTHON_EXE%" backup_postgresql.py --label auto --if-due-hours 24
)
if errorlevel 1 goto BACKUP_FAILED

echo.
echo 檢查成功，正在啟動 API...
echo API 文件：http://127.0.0.1:8732/docs
echo 請保持這個視窗開啟；關閉視窗即可停止 API。
echo.
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --postgres
) else (
  "%PYTHON_EXE%" start_api_server.py --postgres
)
set "API_EXIT_CODE=%ERRORLEVEL%"
if not "%API_EXIT_CODE%"=="0" goto SERVER_FAILED

echo.
echo PostgreSQL API 已停止。
goto FINISH

:CHECK_FAILED
set "API_EXIT_CODE=1"
echo.
echo PostgreSQL 或資料檢查失敗，請查看上方錯誤訊息。
goto FINISH

:BACKUP_FAILED
set "API_EXIT_CODE=1"
echo.
echo PostgreSQL 備份失敗。為避免未備份就繼續操作，API 未啟動。
goto FINISH

:SERVER_FAILED
echo.
echo PostgreSQL API 啟動失敗或意外停止，錯誤代碼：%API_EXIT_CODE%

:FINISH
echo.
echo 按任意鍵關閉這個視窗...
pause >nul
exit /b %API_EXIT_CODE%
