"""The voice library: user-made voice profiles.

A profile is the unit of "a voice you own":

    voices/<name>/
        profile.json      the signature: rate, pitch, volume, clone params, notes
        reference.<ext>   optional recording of your actual voice

A profile *with* a reference recording is a cloned voice (needs the clone
engine). A profile *without* one is a designed voice: a tuned instrument built
from an edge voice, still yours, still reproducible, instantly renderable.

Nothing here sends audio anywhere. Everything stays under the project folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .preferences import PREFERENCES_FILE, Preferences

AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".ogg")
_SAFE = re.compile(r"[^A-Za-z0-9 _.-]")


class LibraryError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(name: str) -> str:
    clean = _SAFE.sub("_", name.strip())[:60].strip(" .")
    if not clean:
        raise LibraryError("voice name cannot be empty")
    return clean


def _base(root: Path) -> Path:
    try:
        return Path(root).expanduser().resolve()
    except OSError:
        return Path(root).expanduser()


def _voices_root(root: Path) -> Path:
    """Where the profiles live: ``<data>/voices`` unless preferences moved it.

    The library API keeps taking the data root, so nothing that calls
    `library.*` needs to know about preferences. The lookup is cached against
    the file's mtime, which keeps `listing()` from re-reading it per voice.
    """
    base = _base(root)
    marker = base / PREFERENCES_FILE
    try:
        stamp = marker.stat().st_mtime_ns
    except OSError:
        return base / "voices"
    cached = _voices_cache.get(str(base))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        located = Preferences.load(base).voices_dir
    except Exception:  # a broken preferences file must not hide the library
        located = base / "voices"
    _voices_cache[str(base)] = (stamp, located)
    return located


_voices_cache: dict[str, tuple[int, Path]] = {}


def voices_root(root: Path) -> Path:
    """Public form of the lookup above."""
    return _voices_root(root)


def folder(root: Path, name: str) -> Path:
    return _voices_root(root) / slug(name)


def audio_in(root: Path, name: str) -> Path | None:
    d = folder(root, name)
    if not d.is_dir():
        return None
    for f in sorted(d.iterdir()):
        if f.suffix.lower() in AUDIO_SUFFIXES:
            return f
    return None


@dataclass
class Profile:
    name: str
    settings: dict[str, Any]
    notes: str = ""
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    has_audio: bool = False
    builtin: bool = False

    @property
    def kind(self) -> str:
        return "cloned" if self.has_audio else "designed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "notes": self.notes,
            "created": self.created,
            "updated": self.updated,
            "builtin": self.builtin,
            "settings": self.settings,
        }

    def summary(self, root: Path) -> dict[str, Any]:
        audio = audio_in(root, self.name)
        s = self.settings
        kind = "cloned" if audio else ("default" if self.builtin else "designed")
        return {
            "name": self.name,
            "kind": kind,
            "builtin": self.builtin,
            "audio": audio.name if audio else "",
            "rate": s.get("rate", ""),
            "pitch": s.get("pitch", ""),
            "volume": s.get("volume", ""),
            "voice": s.get("voice", ""),
            "notes": self.notes,
            "created": self.created,
        }


def create(root: Path, name: str, settings: dict[str, Any],
           notes: str = "", overwrite: bool = False,
           builtin: bool = False) -> Profile:
    d = folder(root, name)
    meta = d / "profile.json"
    if meta.exists() and not overwrite:
        raise LibraryError(f"voice {slug(name)!r} already exists "
                           f"(use --overwrite, or `vf voice update`)")
    d.mkdir(parents=True, exist_ok=True)
    prof = Profile(name=slug(name), settings=dict(settings), notes=notes,
                   has_audio=audio_in(root, name) is not None, builtin=builtin)
    if meta.exists():
        old = json.loads(meta.read_text(encoding="utf-8"))
        prof.created = old.get("created", prof.created)
        if "builtin" not in old:
            prof.builtin = builtin
    meta.write_text(json.dumps(prof.to_dict(), indent=2), encoding="utf-8")
    return prof


def load(root: Path, name: str) -> Profile:
    d = folder(root, name)
    meta = d / "profile.json"
    if not meta.exists():
        known = ", ".join(p["name"] for p in listing(root)) or "none"
        raise LibraryError(f"no voice {name!r}. Library: {known}")
    data = json.loads(meta.read_text(encoding="utf-8"))
    return Profile(
        name=data.get("name", slug(name)),
        settings=dict(data.get("settings", {})),
        notes=data.get("notes", ""),
        created=data.get("created", _now()),
        updated=data.get("updated", _now()),
        has_audio=audio_in(root, name) is not None,
        builtin=bool(data.get("builtin", False)),
    )


def update(root: Path, name: str, settings: dict[str, Any],
           notes: str | None = None) -> Profile:
    prof = load(root, name)
    prof.settings = dict(settings)
    if notes is not None:
        prof.notes = notes
    prof.updated = _now()
    (folder(root, name) / "profile.json").write_text(
        json.dumps(prof.to_dict(), indent=2), encoding="utf-8")
    return prof


def _resolve_source(src: Path, source_root: Path | None) -> Path:
    """Canonicalise a recording path, optionally confined to an upload root.

    The CLI passes no root: a local user may attach any file they can read.
    The web UI passes its upload folder, so a request cannot name an arbitrary
    file on the server (CWE-22).
    """
    candidate = Path(os.path.realpath(Path(src).expanduser()))
    if source_root is not None:
        root = Path(os.path.realpath(Path(source_root)))
        if not str(candidate).startswith(str(root) + os.sep):
            raise LibraryError("recording must be uploaded through the app")
    if not candidate.is_file():
        raise LibraryError(f"no such file: {candidate}")
    if candidate.suffix.lower() not in AUDIO_SUFFIXES:
        raise LibraryError(f"unsupported audio type {candidate.suffix} (wav/mp3/flac/m4a/ogg)")
    return candidate


def attach_sample(root: Path, name: str, src: Path,
                  source_root: Path | None = None) -> Path:
    src = _resolve_source(src, source_root)
    d = folder(root, name)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.iterdir():
        if old.suffix.lower() in AUDIO_SUFFIXES:
            old.unlink()  # one reference clip per voice, no ambiguity
    dest = d / f"reference{src.suffix.lower()}"
    shutil.copy2(src, dest)
    if not (d / "profile.json").exists():
        create(root, name, {}, notes="")
    return dest


def listing(root: Path) -> list[dict[str, Any]]:
    d = _voices_root(root)
    if not d.is_dir():
        return []
    out = []
    for sub in sorted(d.iterdir()):
        if sub.is_dir() and (sub / "profile.json").exists():
            try:
                out.append(load(root, sub.name).summary(root))
            except (json.JSONDecodeError, OSError):
                continue
    return out


def delete(root: Path, name: str) -> bool:
    d = folder(root, name)
    if not d.is_dir():
        return False
    shutil.rmtree(d)
    return True


def rename(root: Path, old: str, new: str) -> Profile:
    src = folder(root, old)
    if not src.is_dir():
        raise LibraryError(f"no voice {old!r}")
    dst = folder(root, new)
    if dst.exists():
        raise LibraryError(f"voice {slug(new)!r} already exists")
    src.rename(dst)
    prof = load(root, new)
    prof.name = slug(new)
    prof.updated = _now()
    (dst / "profile.json").write_text(json.dumps(prof.to_dict(), indent=2),
                                      encoding="utf-8")
    return prof
