@echo off
setlocal
cd /d "%~dp0"

if exist "dist\LandCustomerSystem\LandCustomerSystem.exe" (
    start "" "dist\LandCustomerSystem\LandCustomerSystem.exe"
) else (
    start "" pythonw "%~dp0customer_ui.py"
)

exit /b
