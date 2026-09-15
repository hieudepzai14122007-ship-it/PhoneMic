@echo off
setlocal
cd /d "%~dp0"
title PhoneMic Wi-Fi
if exist ".venv\Scripts\python.exe" goto run
echo PhoneMic - first-time setup needs Internet and Python 3.12+.
py -3 -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,15)" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,15)" >nul 2>&1
if not errorlevel 1 goto use_python
echo.
echo Install Python 3.13 or 3.12 from https://www.python.org/downloads/windows/
echo This prototype targets Windows 11 x64. Keep Tcl/Tk enabled.
echo Enable Add python.exe to PATH, then run START.cmd again.
echo See HUONG-DAN.html for instructions.
pause
exit /b 1
:use_py
py -3 -m venv .venv
goto check_env
:use_python
python -m venv .venv
:check_env
if not exist ".venv\Scripts\python.exe" goto failed
:run
if exist ".venv\phonemic-ready" goto launch
echo Installing dependencies into this app folder...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter,aiohttp,cryptography,numpy,sounddevice,qrcode,PIL"
if errorlevel 1 goto failed
type nul > ".venv\phonemic-ready"
:launch
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo PhoneMic could not start. Keep this window open and send the error shown above.
echo Check your Internet connection and read HUONG-DAN.html.
pause
exit /b 1
