#!/usr/bin/env bash
# VoiceForge launcher (bash / Git Bash / WSL).
#
#   ./run.sh                        -> the launcher window (pick a front-end)
#   ./run.sh native|web|window|flet -> start that front-end directly
#   ./run.sh --check                -> dependency report, no GUI
#   ./run.sh get                    -> any CLI command, e.g. `./run.sh style list`
#   ./run.sh say "hello"            -> render audio
#
# This file is the main launcher on Linux/macOS; the project root is here.
# It prefers the existing Windows venv (.venv/Scripts/python.exe) so you do not
# end up with a second, half-installed Python. On a POSIX-only setup it falls
# back to .venv/bin/python.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# This machine has ALL_PROXY pointed at a dead Tor SOCKS port (127.0.0.1:9050),
# which breaks pip and anything that trusts the environment proxy.
unset ALL_PROXY HTTP_PROXY HTTPS_PROXY all_proxy http_proxy https_proxy || true
export NO_PROXY='*'
export no_proxy='*'

pick_python() {
    if [ -x "runtime/bin/python" ]; then
        PY="runtime/bin/python"         # portable release runtime
    elif [ -x "runtime/python.exe" ]; then
        PY="runtime/python.exe"
    elif [ -x ".venv/Scripts/python.exe" ]; then
        PY=".venv/Scripts/python.exe"   # Windows venv (normal case)
    elif [ -x ".venv/bin/python" ]; then
        PY=".venv/bin/python"           # POSIX venv
    else
        PY=""
    fi
}

pick_python

if [ -z "$PY" ]; then
    echo "No virtual environment found - creating it (one time only)..."
    if command -v python >/dev/null 2>&1; then
        BOOTSTRAP=python
    elif command -v python3 >/dev/null 2>&1; then
        BOOTSTRAP=python3
    else
        echo "error: no python on PATH. Install Python 3.10+ and try again." >&2
        exit 1
    fi
    "$BOOTSTRAP" -m venv .venv
    pick_python
    echo "Installing dependencies (a few hundred MB, one time)..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
fi

# Deliberately NOT setting VOICEFORGE_HOME: under WSL, a /mnt/c path would be
# meaningless to the Windows interpreter. The project is found from the working
# directory instead, which Python resolves natively.

if [ "$#" -eq 0 ]; then
    echo "Opening the VoiceForge launcher - pick how you want to work."
    exec "$PY" "launcher.py"
fi

case "$1" in
    native|web|window|flet)
        exec "$PY" "launcher.py" --launch "$1"
        ;;
    launcher)
        exec "$PY" "launcher.py"
        ;;
    --*)
        exec "$PY" "launcher.py" "$@"
        ;;
esac

exec "$PY" -c "import sys; sys.path.insert(0, 'src'); from voiceforge.cli import main; sys.exit(main(sys.argv[1:]))" "$@"
