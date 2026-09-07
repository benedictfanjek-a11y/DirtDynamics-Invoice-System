@echo off
cd /d "%~dp0"
title Dirt Dynamics - Debug Start
echo Starting Dirt Dynamics...
echo.
py -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
py app.py
echo.
echo The application stopped. The error above is the full diagnostic.
pause
