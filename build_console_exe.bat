@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\Laptop\AppData\Local\Programs\Python\Python314\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Python runtime not found:
    echo %PYTHON_EXE%
    exit /b 1
)

echo [1/3] Verify pinned build dependencies
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements-console.txt
if errorlevel 1 exit /b 1

echo [2/3] Clean old build output
if exist "build\LandCustomerServerConsole" rmdir /s /q "build\LandCustomerServerConsole"
if exist "dist\LandCustomerServerConsole.exe" del /f /q "dist\LandCustomerServerConsole.exe"

echo [3/3] Build LandCustomerServerConsole.exe
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name LandCustomerServerConsole --icon "assets\app_icon.ico" --version-file "version_info_console.txt" server_console\main.py
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete:
echo %CD%\dist\LandCustomerServerConsole.exe
echo.
echo Copy this single file next to the home-server start bat in a release folder.
exit /b
