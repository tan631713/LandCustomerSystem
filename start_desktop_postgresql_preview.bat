@echo off
rem 舊檔名保留相容性；正式入口已改為 PostgreSQL 正式版。
call "%~dp0start_land_customer_system_postgresql.bat"
exit /b %ERRORLEVEL%
