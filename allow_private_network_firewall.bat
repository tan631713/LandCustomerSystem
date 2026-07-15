@echo off
setlocal
chcp 65001 >nul
title 土地資料系統區域網路與手機熱點防火牆設定

net session >nul 2>&1
if errorlevel 1 (
  echo 此設定需要系統管理員權限。
  echo 請在檔案上按右鍵，選擇「以系統管理員身分執行」。
  pause >nul
  exit /b 1
)

echo 此操作只允許「目前區域網路子網路」連入 TCP 8732 與 8733。
echo 同時支援 Windows 的私人與公用網路（手機熱點通常會顯示為公用網路）。
echo 不會開放 PostgreSQL 連接埠，也不允許網際網路上的其他位址連入。
netsh advfirewall firewall delete rule name="土地資料系統 iPhone HTTPS" >nul 2>&1
netsh advfirewall firewall delete rule name="土地資料系統 iPhone 憑證安裝" >nul 2>&1
netsh advfirewall firewall add rule name="土地資料系統 iPhone HTTPS" dir=in action=allow protocol=TCP localport=8732 profile=any remoteip=localsubnet
if errorlevel 1 goto FAILED
netsh advfirewall firewall add rule name="土地資料系統 iPhone 憑證安裝" dir=in action=allow protocol=TCP localport=8733 profile=any remoteip=localsubnet
if errorlevel 1 goto FAILED

echo.
echo 區域網路與手機熱點防火牆規則設定完成。
pause >nul
exit /b 0

:FAILED
echo.
echo 防火牆設定失敗，請確認已使用系統管理員身分執行。
pause >nul
exit /b 1
