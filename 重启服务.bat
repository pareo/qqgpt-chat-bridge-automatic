@echo off
setlocal
title Daifeilong - Restart services
echo Restarting Daifeilong services...
call "%~dp0run.cmd" restart
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo Restart complete. You can close this window.
) else (
    echo Restart failed. See the error above. Exit code: %RESULT%
)
pause
exit /b %RESULT%
