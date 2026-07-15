@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 PostgreSQL 備份
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set "SERVER_EXE=%~dp0LandCustomerServer\LandCustomerServer.exe"

echo 正在備份 PostgreSQL 與附件，請勿關閉視窗...
if exist "%SERVER_EXE%" (
  "%SERVER_EXE%" --backup --backup-label manual
) else (
  "%PYTHON_EXE%" backup_postgresql.py --label manual
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo 備份失敗，舊備份不會被刪除。請保留畫面並回報錯誤內容。
) else (
  echo.
  echo 備份完成。預設會保留最新 30 份與最近 90 天，且最少保留 3 份。
)
echo 按任意鍵關閉這個視窗...
pause >nul
exit /b %EXIT_CODE%
