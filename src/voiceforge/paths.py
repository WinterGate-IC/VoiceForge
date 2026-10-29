"""Program files versus user data - the one place that decides both.

A normal source checkout keeps everything in one folder. An installed copy is
different: the program lives in a read-only-ish location and the user's voices,
renders and settings live in a data folder they chose during setup.

    <install>/launcher.py, desktop.py, src/ ...   program
    <data>/voices, downloads, presets, preferences.json, project.json   user data

`install.json` (written by the installer) records the data folder. Everything
else falls back to "data is next to the program", which is what a checkout
wants.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CONFIG_NAME = "install.json"
ENV_DATA = "VOICEFORGE_DATA"
ENV_HOME = "VOICEFORGE_HOME"


def app_dir(start_file: str | Path | None = None) -> Path:
    """Where the program lives (the folder holding launcher.py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if start_file is not None:
        return Path(start_file).resolve().parent
    return Path(__file__).resolve().parents[2]


def read_install(app: Path | None = None) -> dict:
    """The installer's record, or an empty dict when running from a checkout."""
    base = Path(app) if app is not None else app_dir()
    path = base / CONFIG_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def data_root(start_file: str | Path | None = None,
              create: bool = True) -> Path:
    """The user-data folder: env override, then install.json, then app folder."""
    app = app_dir(start_file)
    override = os.environ.get(ENV_DATA)
    if override:
        root = Path(override).expanduser()
    else:
        recorded = read_install(app).get("data_dir")
        root = Path(recorded).expanduser() if recorded else app
    if not root.is_absolute():
        root = app / root
    root = root.resolve()
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A read-only location should fail later with a useful message,
            # not prevent the UI from opening.
            pass
    return root


def install_config_path(app: Path | None = None) -> Path:
    return (Path(app) if app is not None else app_dir()) / CONFIG_NAME
