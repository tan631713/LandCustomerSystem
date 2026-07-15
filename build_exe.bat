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
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 exit /b 1

echo [2/3] Clean old build output
"%PYTHON_EXE%" build_data_guard.py save "%CD%"
if errorlevel 1 exit /b 1
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [3/3] Build EXE
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --windowed --name LandCustomerSystem --icon "assets\app_icon.ico" --version-file "version_info.txt" --exclude-module numpy --exclude-module lxml --add-data "schema.sql;." --add-data "seed.sql;." --add-data "assets\app_icon.png;assets" customer_ui.py
if errorlevel 1 (
    echo Build failed. Preserved customer data remains in .build-preserved-data
    exit /b 1
)

"%PYTHON_EXE%" build_data_guard.py restore "%CD%"
if errorlevel 1 exit /b 1

echo.
echo Build complete:
echo %CD%\dist\LandCustomerSystem\
echo.
echo Copy the whole folder to another Windows PC.
exit /b
