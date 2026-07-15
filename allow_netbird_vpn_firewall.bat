@echo off
setlocal
chcp 65001 >nul
title 土地資料系統 NetBird 私人 VPN 防火牆

net session >nul 2>&1
if errorlevel 1 (
  echo 需要系統管理員權限。
  echo 請在檔案上按滑鼠右鍵，選擇「以系統管理員身分執行」。
  if /I not "%~1"=="--no-pause" pause >nul
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_netbird_firewall.ps1"
if errorlevel 1 goto FAILED

echo.
echo NetBird 私人 VPN 防火牆規則已建立。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 0

:FAILED
echo 防火牆規則建立失敗。
if /I not "%~1"=="--no-pause" pause >nul
exit /b 1
