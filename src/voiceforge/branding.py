"""VoiceForge brand constants and icon lookup.

One place knows the product name, the company behind it, and where the
prebuilt assets live - both in a checkout and in an installed copy. Qt is
imported lazily so the CLI and installer engine stay Qt-free.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

APP_NAME = "VoiceForge"
VERSION = "1.1.0"
COMPANY = "WinterGate Intelligence Collective"
COMPANY_SHORT = "WIC"
OWNER = "AnonCatalyst"
WEBSITE = "https://wintergate.org"
TAGLINE = "Where the shadows end, and the people stand."
PRODUCT_TAGLINE = "A voice you own."
DESCRIPTION = "Local text to speech with voices you own, per-parameter undo, and style chains."
COPYRIGHT = f"© 2026 {COMPANY}. VoiceForge is a {COMPANY_SHORT} tool by {OWNER}."

ICON_FILE = "voiceforge.ico"
ICON_PNG = "voiceforge-256.png"
AVATAR_FILE = "voiceforge-avatar-512.png"
LOCKUP_FILE = "voiceforge-lockup.png"
SVG_FILE = "voiceforge.svg"

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def asset_dirs() -> list[Path]:
    """Every place prebuilt assets may live, most specific first."""
    here = Path(__file__).resolve()
    roots = [here.parents[2] if len(here.parents) > 2 else here.parent,
             Path(sys.executable).resolve().parent,
             Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None]
    dirs: list[Path] = []
    for root in roots:
        if root is None:
            continue
        candidate = Path(root) / "assets"
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def asset(name: str) -> Path | None:
    for folder in asset_dirs():
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def icon_png(size: int = 256) -> Path | None:
    """The square PNG closest to (but not smaller than) `size`."""
    choices = [n for n in _ICON_SIZES if n >= size] or [max(_ICON_SIZES)]
    for candidate_size in sorted(choices):
        found = asset(f"voiceforge-{candidate_size}.png")
        if found is not None:
            return found
    return None


def icon_path() -> Path | None:
    return asset(ICON_FILE) or icon_png(256)


def avatar_path() -> Path | None:
    return asset(AVATAR_FILE) or asset("voiceforge-avatar.png") or icon_png(512)


def lockup_path() -> Path | None:
    return asset(LOCKUP_FILE)


def qicon():
    """A QIcon with every available size; empty QIcon if Qt/assets are absent."""
    try:
        from PySide6.QtGui import QIcon
    except ImportError:
        return None
    icon = QIcon()
    ico = asset(ICON_FILE)
    if ico is not None:
        icon.addFile(str(ico))
    for size in _ICON_SIZES:
        png = asset(f"voiceforge-{size}.png")
        if png is not None:
            icon.addFile(str(png))
    return icon


def favicon_data_uri(size: int = 64) -> str:
    """Inline PNG for Gradio's <link rel="icon"> - no local file access needed."""
    png = icon_png(size)
    if png is None:
        return ""
    payload = base64.b64encode(png.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"
