"""No-console entry point for VoiceForge Setup (Windows).

Windows opens .pyw files with pythonw.exe, which usually does not have
PySide6. This shim finds the project interpreter and hands the work to
``installer.py`` - the same trick ``VoiceForge.pyw`` uses for the launcher.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTALLER = ROOT / "installer.py"

PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy")


def alert(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, message, "VoiceForge Setup", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def interpreter() -> Path | None:
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


def main() -> int:
    if not INSTALLER.exists():
        alert(f"installer.py is missing from:\n{ROOT}")
        return 1
    python = interpreter()
    if python is None:
        alert("VoiceForge Setup needs its dependencies first.\n\n"
              f"Run this once, then try again:\n{ROOT / 'launchers' / 'setup.cmd'}")
        return 1
    try:
        subprocess.Popen([str(python), str(INSTALLER), *sys.argv[1:]],
                         cwd=str(ROOT), env=clean_env(), close_fds=True)
    except Exception as exc:  # pragma: no cover - environment failure
        alert(f"Could not start VoiceForge Setup:\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
