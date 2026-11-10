@echo off
setlocal
if "%~1"=="" (
    title Daifeilong - Starting services
    echo Starting MaiBot, NapCat and the configured AI backend...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage.ps1" start
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\manage.ps1" %*
)
set "PROJECT_EXIT=%ERRORLEVEL%"
if "%~1"=="" (
    echo.
    if "%PROJECT_EXIT%"=="0" (
        echo Services started. You can close this window; services keep running.
    ) else (
        echo Startup failed. Please check the error above. Exit code: %PROJECT_EXIT%
    )
    pause
)
exit /b %PROJECT_EXIT%
