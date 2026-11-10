"""LandCustomerServerConsole: a Windows GUI wrapper around
home_server_runtime.ps1 and LandCustomerServer.exe.

This package only starts, watches and operates the existing home-server
startup script and executable through their existing, unmodified command
line and diagnostics file. It never talks to PostgreSQL, the API, or the
network directly.
"""
