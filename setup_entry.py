"""Frozen entry point for the VoiceForge Setup executable.

PyInstaller analyses this file, bundles the ``voiceforge`` package from
``src`` together with Qt, and embeds the release payload (``payload.zip``).
The installer engine finds that archive through ``installer_core`` and
unpacks it straight into the folder the user chooses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / "src").is_dir():
    sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env as vf_env  # noqa: E402

vf_env.sanitize()

from voiceforge.installer_ui import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
