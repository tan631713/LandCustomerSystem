@echo off
chcp 65001 >nul
cd /d "%~dp0"
python migrate_sqlite_to_postgresql_gui.py
