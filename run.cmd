@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage.ps1" %*
set "PROJECT_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %PROJECT_EXIT%
