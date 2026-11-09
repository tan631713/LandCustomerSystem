@echo off
chcp 65001 >nul
rem Open Qt Designer with the Fluent widgets in its widget box.
rem   tools\open_designer.bat                      (empty Designer)
rem   tools\open_designer.bat ui\main_window.ui    (open a file; several files are fine)
setlocal
set "HERE=%~dp0"
set "PYSIDE_DESIGNER_PLUGINS=%HERE%designer_plugins"
cd /d "%HERE%.."
where pyside6-designer >nul 2>nul
if errorlevel 1 (
    echo 找不到 pyside6-designer。請先安裝：python -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" pyside6-designer %*
endlocal
