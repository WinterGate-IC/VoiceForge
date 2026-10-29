@echo off
rem ============================================================
rem  VoiceForge - the file to double-click.
rem
rem  No arguments           -> the launcher window; pick a front-end
rem                            (Native, Browser, Desktop Window, Flet)
rem  native|web|window|flet -> start that front-end straight away
rem  --check / --list       -> launcher diagnostics, no window
rem  anything else          -> command line passthrough (vf ...)
rem
rem  Safe to double-click repeatedly. Builds the venv on first run.
rem  Errors pause so the window stays readable.
rem
rem  This file is the main launcher: double-click it.
rem ============================================================

setlocal EnableExtensions
title VoiceForge

cd /d "%~dp0"
set "ROOT=%CD%"

rem This machine has ALL_PROXY pointed at a dead Tor SOCKS port,
rem which breaks pip and any HTTP client trusting the env proxy.
set "ALL_PROXY="
set "NO_PROXY=*"
set "VOICEFORGE_HOME=%ROOT%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"

set "PY=%ROOT%\runtime\python.exe"
set "PYW=%ROOT%\runtime\pythonw.exe"
if not exist "%PY%" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYW%" set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"

set "LAUNCHER=%ROOT%\launcher.py"

if not exist "%PY%" (
    echo(
    echo   First run - building the virtual environment.
    echo   This downloads a few hundred MB and happens only once.
    echo(
    call "%ROOT%\launchers\setup.cmd"
    if not exist "%PY%" goto :fail
    set "PY=%ROOT%\.venv\Scripts\python.exe"
    set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
)

if not exist "%PYW%" set "PYW=%PY%"

rem ---- no arguments: open the chooser in the background ----------------
if "%~1"=="" goto :chooser

set "ARG=%~1"
if /I "%ARG%"=="native"   goto :direct
if /I "%ARG%"=="web"      goto :direct
if /I "%ARG%"=="window"   goto :direct
if /I "%ARG%"=="flet"     goto :direct
if /I "%ARG%"=="launcher" goto :chooser
if "%ARG:~0,2%"=="--"     goto :launcher_args
goto :cli

:chooser
echo(
echo   Opening the VoiceForge launcher - pick how you want to work.
echo(
start "" "%PYW%" "%LAUNCHER%"
exit /b 0

:direct
rem Start with no console; the launcher still checks the dependency first.
start "" "%PYW%" "%LAUNCHER%" --launch %ARG%
exit /b 0

:launcher_args
"%PY%" "%LAUNCHER%" %*
if errorlevel 1 goto :fail
exit /b 0

:cli
"%PY%" -c "import sys; sys.path.insert(0, 'src'); from voiceforge.cli import main; sys.exit(main(sys.argv[1:]))" %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo(
echo   VoiceForge stopped with an error.
echo   If this is the first run, see the message above - it is usually
echo   a network problem or the dead ALL_PROXY setting.
echo(
pause
exit /b 1
