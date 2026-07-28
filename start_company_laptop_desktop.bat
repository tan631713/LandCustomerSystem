@echo off
setlocal EnableExtensions
chcp 65001 >nul
title 土地資料系統 公司筆電遠端桌面版
cd /d "%~dp0"

set "DESKTOP_EXE=%~dp0LandCustomerSystem\LandCustomerSystem.exe"

echo ============================================================
echo 土地資料系統 - 公司筆電一鍵客戶端
echo ============================================================
echo.

if not exist "%DESKTOP_EXE%" (
  echo 找不到完整桌面程式：%DESKTOP_EXE%
  goto FAILED
)
echo [1/2] 檢查 NetBird 安裝、登入與連線...
call "%~dp0setup_netbird_client.bat" --no-pause
if errorlevel 1 goto FAILED

set "LAND_CUSTOMER_DESKTOP_BACKEND=postgresql"
set "LAND_CUSTOMER_API_CA_CERT="

echo.
echo [2/2] 正在開啟完整桌面程式...
echo 第一次啟動時，程式會要求輸入家中伺服器的 NetBird IP。
echo 程式會從家中主機取得公開 CA，顯示指紋並在你確認後保存。
echo 公司筆電不會啟動 PostgreSQL，也不會建立第二份正式資料庫。
"%DESKTOP_EXE%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto FAILED_WITH_CODE
goto FINISH

:FAILED
set "EXIT_CODE=1"
:FAILED_WITH_CODE
echo.
echo 遠端桌面程式啟動失敗。
echo 請確認家中主機的「啟動家中伺服器.bat」視窗、NetBird 與網路都保持運作。
echo 伺服器 IP 可在桌面程式的「設定 ＞ 伺服器連線設定」重新輸入。

:FINISH
echo.
echo 按任意鍵關閉視窗...
pause >nul
exit /b %EXIT_CODE%
