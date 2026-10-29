"""Double-click entry point for the VoiceForge launcher (Windows).

Windows opens .pyw files with pythonw.exe, so there is no console window. The
trouble is that the system Python usually does not have PySide6 - the project
virtual environment does. So this file is a tiny, dependency-free shim: it
finds the project's interpreter and hands the real work to launcher.py.

    double-click VoiceForge.pyw  -> the chooser (no console)
    also works from a shell:      pythonw launchers\\VoiceForge.pyw --check

VoiceForge.bat does the same thing and is the safer choice if .pyw files are
not associated with Python on your machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
LAUNCHER = ROOT / "launcher.py"

PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy")


def alert(message: str) -> None:
    """A message box is the only way to speak when there is no console."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, message, "VoiceForge", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def interpreter() -> Path | None:
    """The bundled runtime first, then the project venv."""
    for relative in (Path("runtime/pythonw.exe"),
                     Path("runtime/python.exe"),
                     Path("runtime/bin/python"),
                     Path(".venv/Scripts/pythonw.exe"),
                     Path(".venv/Scripts/python.exe"),
                     Path(".venv/bin/python")):
        candidate = ROOT / relative
        if candidate.exists():
            return candidate
    return None


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in PROXY_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env["VOICEFORGE_HOME"] = str(ROOT)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def has_qt(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", "import PySide6"], cwd=str(ROOT),
            env=clean_env(), capture_output=True, timeout=60)
        return result.returncode == 0
    except Exception:
        return False


def main() -> int:
    if not LAUNCHER.exists():
        alert(f"launcher.py is missing from:\n{HERE}")
        return 1

    python = interpreter()
    if python is None:
        alert("VoiceForge has no virtual environment yet.\n\n"
              f"Run this once, then try again:\n{HERE / 'launchers' / 'setup.cmd'}")
        return 1

    if not has_qt(python):
        alert("The launcher needs PySide6, which is not installed in the "
              f"project environment.\n\nRun this once, then try again:\n"
              f"{HERE / 'launchers' / 'setup.cmd'}")
        return 1

    try:
        subprocess.Popen(
            [str(python), str(LAUNCHER), *sys.argv[1:]],
            cwd=str(ROOT), env=clean_env(), close_fds=True)
    except Exception as exc:  # pragma: no cover - environment failure
        alert(f"Could not start VoiceForge:\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
