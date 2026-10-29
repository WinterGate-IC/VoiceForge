"""Crash-safe audio file IO.

Every finished file is written to a hidden temporary name in the *destination*
folder, checked with libsndfile, and only then renamed over the real name. A
crash, a full disk, or a half-written encoder frame can therefore never leave a
truncated file where the user expects a playable one.

The same helpers are used by the renderer, the effects chain and the preview
path, so "the file the app says exists" is always a file that opens.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

# The formats a finished render can be handed to the user in.
FORMAT_SETTINGS: dict[str, tuple[str, str]] = {
    "mp3": ("MP3", "MPEG_LAYER_III"),
    "wav": ("WAV", "PCM_16"),
    "flac": ("FLAC", "PCM_16"),
    "ogg": ("OGG", "VORBIS"),
}
AUDIO_SUFFIXES = tuple("." + key for key in FORMAT_SETTINGS)
MIN_AUDIO_BYTES = 32


class AudioValidationError(RuntimeError):
    """A file exists but is not usable audio."""


def format_for_suffix(path: Path, fallback: str = "mp3") -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix if suffix in FORMAT_SETTINGS else fallback


def read_audio(path: Path):
    """Read a file as float32, always two-dimensional (frames, channels)."""
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return data, rate


def validate_audio(path: Path) -> dict:
    """Open `path` and return its real audio properties.

    Raises AudioValidationError when the file is missing, empty, has no frames
    or cannot be decoded. This is deliberately strict: a zero-byte render is
    the failure mode that used to reach the user's downloads folder.
    """
    path = Path(path)
    if not path.is_file():
        raise AudioValidationError(f"{path.name} was not written")
    size = path.stat().st_size
    if size < MIN_AUDIO_BYTES:
        raise AudioValidationError(
            f"{path.name} is empty ({size} bytes) - the render did not finish")
    import soundfile as sf

    try:
        info = sf.info(str(path))
    except Exception as exc:  # noqa: BLE001 - libsndfile raises several types
        raise AudioValidationError(
            f"{path.name} is not readable audio: {exc}") from exc
    if info.frames <= 0:
        raise AudioValidationError(f"{path.name} contains no audio frames")
    duration = float(info.frames) / float(info.samplerate or 1)
    if duration <= 0.0 or duration != duration:  # NaN guard
        raise AudioValidationError(f"{path.name} has an invalid duration")
    return {
        "frames": int(info.frames),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "duration": duration,
        "format": str(info.format),
        "subtype": str(info.subtype),
        "bytes": int(size),
    }


def _temp_name(target: Path) -> Path:
    return target.parent / (
        f".{target.stem}.vf-{os.getpid()}-{uuid.uuid4().hex[:8]}{target.suffix}")


def _write_raw(data, rate: int, target: Path, fmt: str) -> None:
    import soundfile as sf

    container, subtype = FORMAT_SETTINGS[fmt]
    sf.write(str(target), data, rate, format=container, subtype=subtype)


def _replace(tmp: Path, target: Path) -> None:
    """Atomically move `tmp` over `target`, working across drives too."""
    try:
        os.replace(tmp, target)
        return
    except OSError:
        pass
    # A cross-device rename cannot be atomic. Copy to a sibling temp first and
    # replace that, so the target still only ever changes in one step.
    bridge = _temp_name(target)
    try:
        shutil.copy2(tmp, bridge)
        validate_audio(bridge)
        os.replace(bridge, target)
    finally:
        for leftover in (tmp, bridge):
            try:
                leftover.unlink()
            except OSError:
                pass


def write_audio(data, rate: int, target: Path) -> Path:
    """Write `data` in the format implied by `target`'s suffix, atomically.

    MP3 is preferred. If this build of libsndfile has no MP3 encoder, the
    audio is written as WAV beside the requested name and that real path is
    returned. Callers must always trust the return value.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = FORMAT_SETTINGS.get(target.suffix.lower().lstrip("."))
    if fmt is None:
        fmt = FORMAT_SETTINGS["wav"]
        target = target.with_suffix(".wav")

    written = target
    tmp = _temp_name(target)
    try:
        try:
            _write_raw(data, rate, tmp, format_for_suffix(target))
        except Exception:
            if format_for_suffix(target) != "mp3":
                raise
            # No MP3 encoder in this libsndfile build: keep a WAV instead of
            # failing the whole render.
            try:
                tmp.unlink()
            except OSError:
                pass
            written = target.with_suffix(".wav")
            tmp = _temp_name(written)
            _write_raw(data, rate, tmp, "wav")
        validate_audio(tmp)
        _replace(tmp, written)
        return written
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def copy_into_place(source: Path, target: Path) -> Path:
    """Validate `source`, copy it beside `target`, then rename it into place."""
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_audio(source)
    tmp = _temp_name(target)
    try:
        shutil.copy2(source, tmp)
        validate_audio(tmp)
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    try:
        source.unlink()
    except OSError:
        pass
    return target


def free_space_mb(path: Path) -> float:
    try:
        return shutil.disk_usage(str(path)).free / (1024 * 1024)
    except OSError:
        return 0.0
