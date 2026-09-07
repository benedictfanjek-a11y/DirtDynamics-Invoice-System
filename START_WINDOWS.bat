@echo off
setlocal
cd /d "%~dp0"
title Dirt Dynamics Invoice System
echo ==============================================
echo   DIRT DYNAMICS INVOICE SYSTEM
echo ==============================================
echo.
echo Starting from:
echo %CD%
echo.
py -m pip install -r requirements.txt
if errorlevel 1 goto :error
py app.py
if errorlevel 1 goto :error
goto :end

:error
echo.
echo ==============================================
echo ERROR: The application stopped.
echo The full Python error is shown above.
echo ==============================================
pause

:end
