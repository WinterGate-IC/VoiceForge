"""User preferences, persisted next to the user's data.

These are the options a person actually changes: the dark scheme, where voices
and renders are kept, whether the launcher closes itself, how long text is
split, and so on. They are deliberately separate from `project.json`: the
project file is undo-tracked creative state, this is the app's own setup.

The file is written atomically, and every value is validated on load, so a
hand-edited or truncated file can never stop the app from starting.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import themes

PREFERENCES_FILE = "preferences.json"
FRONTENDS = ("native", "web", "window", "flet")
OUTPUT_FORMATS = ("mp3", "wav", "flac", "ogg")
DEFAULT_OUTPUT_FORMAT = "mp3"

DEFAULTS: dict[str, Any] = {
    "theme": themes.DEFAULT_THEME,
    "voices_dir": "",          # empty string = <data>/voices
    "output_dir": "",          # empty string = <data>/downloads
    "text_dir": "",            # empty string = <data>/texts
    "output_format": DEFAULT_OUTPUT_FORMAT,
    "default_frontend": "native",
    "close_launcher_after_start": True,
    "confirm_delete": True,
    "autoplay_after_render": False,
    "last_text_file": "",      # saved .txt the user last opened
    "chunk_chars": 1800,
    "chunk_gap": 0.25,
    "adaptive_performance": True,   # let the governor choose the worker count
    "render_workers": 0,            # 0 = automatic; 1..8 = fixed parts at a time
    "player_volume": 90,
    "show_hints": True,
    "start_maximized": False,
}

_BOOL_KEYS = {
    "close_launcher_after_start", "confirm_delete", "autoplay_after_render",
    "show_hints", "start_maximized", "adaptive_performance",
}
_INT_RANGES = {
    "chunk_chars": (400, 8000), "player_volume": (0, 100),
    "render_workers": (0, 8),
}
_FLOAT_RANGES = {"chunk_gap": (0.0, 3.0)}


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return fallback


def _as_number(value: Any, fallback: float, lo: float, hi: float,
               integer: bool) -> float | int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    number = min(hi, max(lo, number))
    return int(round(number)) if integer else round(number, 2)


def _clean(raw: dict, root: Path) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key not in raw:
            continue
        value = raw[key]
        if key in _BOOL_KEYS:
            out[key] = _as_bool(value, bool(DEFAULTS[key]))
        elif key in _INT_RANGES:
            lo, hi = _INT_RANGES[key]
            out[key] = _as_number(value, DEFAULTS[key], lo, hi, True)
        elif key in _FLOAT_RANGES:
            lo, hi = _FLOAT_RANGES[key]
            out[key] = _as_number(value, DEFAULTS[key], lo, hi, False)
        elif key == "theme":
            out[key] = value if value in themes.THEME_KEYS else themes.DEFAULT_THEME
        elif key == "default_frontend":
            out[key] = value if value in FRONTENDS else DEFAULTS[key]
        elif key == "output_format":
            out[key] = (str(value or "").strip().lower()
                        if str(value or "").strip().lower() in OUTPUT_FORMATS
                        else DEFAULT_OUTPUT_FORMAT)
        elif key in ("voices_dir", "output_dir", "text_dir", "last_text_file"):
            out[key] = str(value or "").strip()
        else:
            out[key] = value
    return out


class Preferences:
    """A validated view over preferences.json for one data folder."""

    def __init__(self, root: Path, values: dict[str, Any] | None = None) -> None:
        self.root = Path(root)
        self.values = _clean(values or {}, self.root)

    # ---- io ----------------------------------------------------------
    @property
    def path(self) -> Path:
        return self.root / PREFERENCES_FILE

    @classmethod
    def load(cls, root: Path) -> "Preferences":
        root = Path(root)
        path = root / PREFERENCES_FILE
        had_file = path.exists()
        raw: dict[str, Any] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, ValueError):
            raw = {}
        prefs = cls(root, raw)
        if not had_file:
            prefs._migrate_output_folder()
        return prefs

    def _migrate_output_folder(self) -> None:
        """One-time rename of the old ``output/`` folder to ``downloads/``.

        Only ever runs when there is no preferences file yet (so the user has
        not chosen a folder) and the new name is free. A failed rename simply
        leaves the old folder where it is; nothing is deleted.
        """
        if self.values.get("output_dir"):
            return
        old = self.root / "output"
        new = self.root / "downloads"
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.values, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---- access ------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, DEFAULTS.get(key, default))

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown preference {key!r}")
        self.values[key] = _clean({key: value}, self.root)[key]

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in DEFAULTS:
                self.set(key, value)

    def reset(self) -> None:
        self.values = dict(DEFAULTS)

    # ---- resolved folders -------------------------------------------
    def _resolve(self, value: str, fallback: str) -> Path:
        if value:
            path = Path(value).expanduser()
            return path.resolve() if path.is_absolute() else (self.root / path).resolve()
        return (self.root / fallback).resolve()

    @property
    def voices_dir(self) -> Path:
        return self._resolve(self.values.get("voices_dir", ""), "voices")

    @property
    def output_dir(self) -> Path:
        return self._resolve(self.values.get("output_dir", ""), "downloads")

    @property
    def text_dir(self) -> Path:
        return self._resolve(self.values.get("text_dir", ""), "texts")

    @property
    def output_format(self) -> str:
        value = str(self.values.get("output_format", DEFAULT_OUTPUT_FORMAT))
        return value if value in OUTPUT_FORMATS else DEFAULT_OUTPUT_FORMAT

    def format_extension(self) -> str:
        return "." + self.output_format

    def relocate_voices(self, new_dir: str | Path, move: bool = True) -> dict:
        """Point the library at `new_dir`, optionally carrying voices over.

        Same volume -> a rename; another volume -> a real move. Existing files
        at the destination are never overwritten: they are skipped and
        reported, so two libraries can be merged safely.
        """
        old = self.voices_dir
        target = Path(new_dir).expanduser()
        if not target.is_absolute():
            target = (self.root / target)
        target = target.resolve()

        if target == old:
            self.set("voices_dir", str(target))
            self.save()
            return {"moved": [], "skipped": [], "target": str(target)}

        if old in target.parents or target in old.parents:
            raise ValueError("The new voices folder cannot be inside the old one.")

        target.mkdir(parents=True, exist_ok=True)
        moved: list[str] = []
        skipped: list[str] = []
        if move and old.is_dir():
            for child in sorted(old.iterdir()):
                destination = target / child.name
                if destination.exists():
                    skipped.append(child.name)
                    continue
                shutil.move(str(child), str(destination))
                moved.append(child.name)
            try:
                old.rmdir()
            except OSError:
                pass

        self.set("voices_dir", str(target))
        self.save()
        return {"moved": moved, "skipped": skipped, "target": str(target)}

    def default_voices_dir(self) -> Path:
        return (self.root / "voices").resolve()

    def default_output_dir(self) -> Path:
        return (self.root / "downloads").resolve()

    def default_text_dir(self) -> Path:
        return (self.root / "texts").resolve()
