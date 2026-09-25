@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app.ps1" %*
exit /b %errorlevel%
