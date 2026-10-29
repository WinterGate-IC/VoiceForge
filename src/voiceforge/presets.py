"""Named presets: a settings snapshot you can reapply in one command."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9 _.-]")


class PresetError(ValueError):
    pass


def _dir(root: Path) -> Path:
    d = root / "presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(root: Path, name: str) -> Path:
    clean = _SAFE.sub("_", name.strip())[:60].strip() or "untitled"
    return _dir(root) / f"{clean}.json"


def save(root: Path, name: str, settings: dict[str, Any]) -> Path:
    p = _path(root, name)
    p.write_text(json.dumps({"name": name, "settings": settings}, indent=2), encoding="utf-8")
    return p


def load(root: Path, name: str) -> dict[str, Any]:
    p = _path(root, name)
    if not p.exists():
        known = ", ".join(n for n, _ in listing(root)) or "none"
        raise PresetError(f"no preset {name!r}. Saved: {known}")
    return json.loads(p.read_text(encoding="utf-8"))["settings"]


def delete(root: Path, name: str) -> bool:
    p = _path(root, name)
    if p.exists():
        p.unlink()
        return True
    return False


def listing(root: Path) -> list[tuple[str, Path]]:
    d = _dir(root)
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            name = json.loads(p.read_text(encoding="utf-8")).get("name", p.stem)
        except (json.JSONDecodeError, OSError):
            name = p.stem
        out.append((name, p))
    return out
