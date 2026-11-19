@echo off
setlocal
title Daifeilong - Stop services
echo Stopping Daifeilong services...
call "%~dp0run.cmd" stop
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo Services stopped. You can close this window.
) else (
    echo Stop failed. See the error above. Exit code: %RESULT%
)
pause
exit /b %RESULT%
