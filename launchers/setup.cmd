@echo off
rem One-time (or repair) setup: builds the venv and installs dependencies.
rem Lives in launchers\; works on the project root above it.
setlocal
set "ALL_PROXY="
set "NO_PROXY=*"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail

echo.
echo Done. Start with:  launchers\VoiceForge.bat
echo The launcher can add the optional front-ends (PySide6, pywebview, Flet)
echo from its own window the first time you pick one.
goto :eof

:fail
echo.
echo Setup failed. If pip reports SOCKS support errors, ALL_PROXY is set to a dead
echo proxy; this script clears it, but check:  setx ALL_PROXY ""
pause
exit /b 1
