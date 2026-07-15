@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo [1/2] 建立 Windows 桌面程式...
call build_exe.bat
if errorlevel 1 goto FAILED

echo [2/2] 建立 PostgreSQL 伺服器與正式交付包...
"%PYTHON_EXE%" build_postgresql_release.py
if errorlevel 1 goto FAILED

echo.
echo PostgreSQL 正式版打包完成，請查看 releases 資料夾。
pause >nul
exit /b 0

:FAILED
echo.
echo 打包失敗，請保留畫面並回報上方錯誤內容。
pause >nul
exit /b 1
