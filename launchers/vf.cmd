@echo off
rem VoiceForge command line. Lives in launchers\; runs from the project root.
rem Clears any inherited ALL_PROXY so pip and HTTP clients do not trust it.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "ALL_PROXY="
set "NO_PROXY=*"
set "VOICEFORGE_HOME=%ROOT%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
"%ROOT%\.venv\Scripts\python.exe" -m voiceforge %*
