@echo off
rem ============================================================
rem  VoiceForge Setup - run the installer from a source checkout.
rem
rem  The release ships VoiceForge-Setup-1.0.0.exe instead; this
rem  wrapper is for testing the installer from the project folder.
rem
rem  Setup needs PySide6. It lives in the project virtual
rem  environment, which launchers\setup.cmd creates on first use.
rem ============================================================

setlocal EnableExtensions
title VoiceForge Setup
cd /d "%~dp0"

set "PYW=%~dp0runtime\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0runtime\python.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\python.exe"

if exist "%PYW%" (
    start "" "%PYW%" "%~dp0installer.py" %*
    exit /b 0
)

echo(
echo   VoiceForge Setup needs its project environment first.
echo   Running launchers\setup.cmd now - this happens only once.
echo(
call "%~dp0launchers\setup.cmd"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo(
    echo   Setup could not prepare Python. See the message above.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0installer.py" %*
exit /b 0
