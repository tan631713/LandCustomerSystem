@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 家中主機伺服器
cd /d "%~dp0"

echo 此視窗是家中唯一正式伺服器。
echo 手機瀏覽器與公司筆電桌面程式都會透過 NetBird 連到這裡。
echo.
call "%~dp0start_mobile_server_vpn.bat"
exit /b %ERRORLEVEL%
