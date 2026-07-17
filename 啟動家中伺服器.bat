@echo off
setlocal EnableExtensions
title Land Customer System - Home Server
cd /d "%~dp0"

for %%I in ("%~dp0.") do set "PACKAGE_ROOT=%%~fI"
set "SUPPORT_ROOT=%~dp0_server_support"
if not exist "%SUPPORT_ROOT%\home_server_runtime.ps1" set "SUPPORT_ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SUPPORT_ROOT%\home_server_runtime.ps1" -PackageRoot "%PACKAGE_ROOT%" -SupportRoot "%SUPPORT_ROOT%" -Mode Start
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo Home server stopped normally.
) else (
  echo Home server failed to start or stopped unexpectedly.
  echo Diagnostics:
  echo %LocalAppData%\LandCustomerSystem\home-server-diagnostics.json
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %EXIT_CODE%
