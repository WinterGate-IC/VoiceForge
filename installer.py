"""VoiceForge Setup - the source-tree entry point.

Double-click ``VoiceForge-Setup.bat`` (Windows) or run:

    python installer.py                 the Setup window
    python installer.py --auto          no questions, recommended folders
    python installer.py --auto --quiet  no window at all (CI / scripting)

The window and the engine live in ``src/voiceforge/installer_ui.py`` and
``installer_core.py``. This file only makes sure the shared package is on the
path and gives a readable error when PySide6 is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# Clear the dead proxy before pip (run by the installer) inherits it.
from voiceforge import env as vf_env  # noqa: E402

vf_env.sanitize()

try:
    from voiceforge.installer_ui import main  # noqa: E402
except ImportError as exc:  # pragma: no cover - depends on the machine
    print("VoiceForge Setup needs PySide6, which is not installed for this "
          f"Python.\n\n{exc}\n\nRun launchers\\setup.cmd (Windows) or "
          "./run.sh (Linux) once, then try again.", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
