"""Rendering pipeline shared by the CLI and every GUI.

One place decides which engine runs, resolves a library voice, applies
overrides and picks an output filename. Callers get back a `RenderOutcome`:
a normal ``(path, engine_name)`` tuple that also carries ``.meta`` with the
real bytes, duration, sample rate, part count and timings of the finished file.

Long text is split into sentence-safe parts. Edge parts are independent HTTPS
requests, so they are rendered in a small, adaptive pool of threads. The
governor in `resources.py` watches CPU and memory: when the device is under
pressure it drops back to one part at a time until things are healthy again.
The clone engine stays sequential because it is local and resource-hungry.

Every part and the final file are validated before they are exposed. The
finished file is written through `audio_io`, which writes a hidden temporary
sibling and renames it into place, so a crash or full disk can never leave a
truncated file where the user expects a playable one.
"""

from __future__ import annotations

import concurrent.futures as futures
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import audio_io, library
from .effects import has_effects, process_file
from .engines import EngineError, get_engine
from .preferences import PREFERENCES_FILE, Preferences
from .project import Project
from .resources import Governor
from .textsplit import DEFAULT_LIMIT, split_for_speech

AUDIO_EXTS = (".mp3", ".wav", ".flac", ".ogg", ".m4a")

# The formats a finished render can be handed to the user in. MP3 is the
# default: small, universal, and already what the edge engine speaks.
FORMAT_LABELS: dict[str, str] = {
    "mp3": "MP3 (recommended)",
    "wav": "WAV (lossless)",
    "flac": "FLAC (lossless, smaller)",
    "ogg": "OGG Vorbis (smallest)",
}
FORMAT_SUFFIX = {key: "." + key for key in FORMAT_LABELS}
_SUFFIX_FORMAT = {suffix: key for key, suffix in FORMAT_SUFFIX.items()}
_WRITE_SETTINGS = audio_io.FORMAT_SETTINGS


class RenderOutcome(tuple):
    """``(path, engine)`` with a ``meta`` dict, so old callers still unpack."""

    def __new__(cls, path: Path, engine: str, meta: dict | None = None):
        outcome = super().__new__(cls, (Path(path), engine))
        outcome.meta = dict(meta or {})
        return outcome

    @property
    def path(self) -> Path:
        return self[0]

    @property
    def engine(self) -> str:
        return self[1]


def normalize_format(name: str | None, fallback: str = "mp3") -> str:
    value = str(name or "").strip().lower().lstrip(".")
    return value if value in FORMAT_LABELS else fallback


def format_for_path(path: Path, fallback: str = "mp3") -> str:
    return _SUFFIX_FORMAT.get(Path(path).suffix.lower(), fallback)


_output_cache: dict[str, tuple[int, object]] = {}


def _prefs(project: Project) -> Preferences:
    """Preferences for a project's data root, cached against file mtime."""
    base = Path(project.root).expanduser()
    marker = base / PREFERENCES_FILE
    try:
        stamp = marker.stat().st_mtime_ns
    except OSError:
        return Preferences(base)
    key = str(base)
    cached = _output_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]  # type: ignore[return-value]
    loaded = Preferences.load(base)
    _output_cache[key] = (stamp, loaded)
    return loaded


def slug(text: str, limit: int = 36) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].rstrip("-") or "clip"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def output_dir(project: Project) -> Path:
    d = _prefs(project).output_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(project: Project) -> Path:
    """Hidden scratch space for chunk files and half-written renders.

    Parts used to live beside the finished download, so a long script looked
    like it was spamming the downloads folder while it worked. They now live
    here and only the stitched result ever reaches `downloads`.
    """
    path = Path(project.root) / ".cache" / "render"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Only timestamped VoiceForge chunk names and its own atomic temp files are
# ever removed. A user file called "notes.part001.mp3" is left alone because it
# does not start with a stamp.
_PART_RE = re.compile(
    r"^\d{8}-\d{6}-.*\.part\d{3}\.(?:mp3|wav|flac|ogg|m4a)$", re.IGNORECASE)
_VF_WORK_RE = re.compile(
    r"^\..+\.vf(?:[-.][^.]+)?\.(?:mp3|wav|flac|ogg|m4a)$", re.IGNORECASE)


def cleanup_partials(directory: Path) -> int:
    """Remove abandoned chunk/half-way files from a downloads folder.

    Older builds wrote `20261025-142250-script.part001.mp3` next to the final
    download, and a crash could leave them behind. This is the migration path:
    it is safe to call at startup and only touches VoiceForge's own names.
    """
    directory = Path(directory)
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_file():
            continue
        if not (_PART_RE.match(entry.name) or _VF_WORK_RE.match(entry.name)):
            continue
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _read_audio(path: Path):
    return audio_io.read_audio(path)


def _resample_linear(data, src_rate: int, dst_rate: int):
    """Dependency-free resampling, only used if two engines disagree on rate."""
    import numpy as np

    if data.shape[0] == 0 or src_rate == dst_rate:
        return data
    n_out = max(1, int(round(data.shape[0] * dst_rate / src_rate)))
    old = np.linspace(0.0, 1.0, data.shape[0], endpoint=False)
    new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    cols = [np.interp(new, old, data[:, c]) for c in range(data.shape[1])]
    return np.stack(cols, axis=1).astype(np.float32)


def _write_audio(data, rate: int, target: Path) -> Path:
    """Write `data` in the target's format, atomically and validated."""
    return audio_io.write_audio(data, rate, target)


def _convert_audio(source: Path, target: Path) -> Path:
    """Decode `source` and re-encode it in `target`'s format."""
    data, rate = _read_audio(source)
    return _write_audio(data, rate, target)


def concatenate_audio(paths: list[Path], target: Path,
                      gap_seconds: float = 0.25) -> Path:
    """Join rendered parts into one file with a short, natural pause between.

    The write is atomic: the finished name only appears once libsndfile has
    successfully written and reopened the complete file.
    """
    import numpy as np

    frames = []
    rate = None
    channels = 1
    for path in paths:
        audio_io.validate_audio(path)
        data, this_rate = _read_audio(path)
        if rate is None:
            rate, channels = this_rate, data.shape[1]
        elif this_rate != rate:
            data = _resample_linear(data, this_rate, rate)
        if data.shape[1] != channels:
            if data.shape[1] == 1:
                data = np.repeat(data, channels, axis=1)
            else:
                data = data.mean(axis=1, keepdims=True)
        frames.append(data)
        frames.append(np.zeros((int(rate * gap_seconds), channels),
                               dtype=np.float32))

    if not frames:
        raise EngineError("nothing was rendered")
    merged = np.concatenate(frames[:-1], axis=0)
    peak = float(np.max(np.abs(merged)) or 1.0)
    if peak > 0.995:
        merged = merged / peak * 0.98
    return _write_audio(np.clip(merged, -1.0, 1.0).astype(np.float32), rate, target)


def _install_take(take: Path, target: Path) -> Path:
    """Move an engine's validated output into the final name, atomically."""
    take = Path(take)
    target = Path(target)
    audio_io.validate_audio(take)
    if take.suffix.lower() == target.suffix.lower():
        return audio_io.copy_into_place(take, target)
    data, rate = audio_io.read_audio(take)
    written = audio_io.write_audio(data, rate, target)
    try:
        take.unlink()
    except OSError:
        pass
    return written


def _space_check(parts: list[Path], target: Path) -> None:
    """Refuse to start a stitch that cannot possibly fit on the disk."""
    free = audio_io.free_space_mb(target.parent)
    if free <= 0:
        return
    try:
        import soundfile as sf

        seconds = 0.0
        rate = 48000
        channels = 2
        for path in parts:
            info = sf.info(str(path))
            seconds += float(info.frames) / max(1, info.samplerate)
            rate = max(rate, int(info.samplerate or 0))
            channels = max(channels, int(info.channels or 1))
    except Exception:
        return
    seconds += max(0.0, len(parts) - 1) * 0.3
    fmt = format_for_path(target)
    if fmt == "wav":
        need = seconds * rate * channels * 2
    elif fmt == "flac":
        need = seconds * rate * channels * 1.3
    elif fmt == "ogg":
        need = seconds * 128_000 / 8
    else:
        need = seconds * 160_000 / 8
    need_mb = need / (1024 * 1024)
    required = max(24.0, need_mb * 1.35 + 12.0)
    if free < required:
        raise EngineError(
            f"Not enough free space in {target.parent}: this render needs "
            f"about {required:.0f} MB but only {free:.0f} MB is available. "
            "Free some space and try again - nothing was written.")


def _looks_permanent(message: str) -> bool:
    """Engine errors that a retry will not fix (bad voice, no catalog entry)."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in (
        "not in microsoft's current catalogue",
        "not in microsoft's current catalog",
        "not installed",
        "unavailable:",
        "unknown engine",
        "no text to speak",
    ))


def render_text(project: Project, text: str, out: Path | str | None = None,
                engine_name: str | None = None,
                overrides: dict[str, Any] | None = None,
                profile: str | None = None,
                chunk_chars: int | None = None,
                output_format: str | None = None,
                progress: Callable[[dict[str, Any]], None] | None = None,
                adaptive: bool | None = None,
                workers: int | None = None) -> RenderOutcome:
    """Render `text` to audio, in as many parts as the length requires.

    Precedence: project settings -> library profile -> explicit overrides.
    Engine defaults to clone when a reference voice is resolved, else edge.

    `chunk_chars=None` means "use the size from preferences", which is what
    every front-end wants; pass a number to override it for one render.
    `output_format` likewise defaults to the download format in preferences.
    An explicit `out` filename with a known audio suffix wins over both.

    `adaptive` and `workers` override the performance preferences for one
    render (used by tests and by previews). `workers=0` means automatic.

    `progress` is called from the rendering thread with small dictionaries
    describing the current phase (`prepare`, `part`, `part_done`, `stitch`,
    `effects`, `done`), the part index/count, characters done, active parts,
    current worker budget, throughput and how long the last part took.
    Front-ends use it for a live bar, statistics and an estimated wait; it is
    deliberately best-effort and never allowed to break a render.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("no text to speak")

    prefs = _prefs(project)
    limit = int(chunk_chars or prefs["chunk_chars"] or DEFAULT_LIMIT)
    gap = float(prefs["chunk_gap"])
    fmt = normalize_format(output_format or prefs["output_format"])
    use_adaptive = (bool(prefs["adaptive_performance"])
                    if adaptive is None else bool(adaptive))
    requested_workers = (int(prefs["render_workers"]) if workers is None
                         else max(0, int(workers)))

    settings = dict(project.settings)

    if profile:
        prof = library.load(project.root, profile)
        settings.update(prof.settings)
        has_audio = library.audio_in(project.root, prof.name) is not None
        settings["reference"] = prof.name if has_audio else ""

    settings.update({k: v for k, v in (overrides or {}).items() if v is not None})

    name = (engine_name or ("clone" if settings.get("reference") else "edge")).lower()
    engine = get_engine(name, project.root)
    ok, reason = engine.available(str(settings.get("reference", "")))
    if not ok:
        raise EngineError(f"{name} engine unavailable: {reason}")

    if out is None:
        target = output_dir(project) / f"{stamp()}-{slug(text)}{FORMAT_SUFFIX[fmt]}"
    else:
        target = Path(out).expanduser()
        if not target.is_absolute():
            target = project.root / target
        if target.suffix.lower() in _SUFFIX_FORMAT:
            fmt = format_for_path(target)
        else:
            target = target.with_suffix(FORMAT_SUFFIX[fmt])

    chunks = split_for_speech(text, limit=limit)
    total_chars = sum(len(chunk) for chunk in chunks) or len(text) or 1

    started_all = time.monotonic()
    started_parts = 0.0
    done_chars = 0
    parts_done = 0
    peak_workers = 1
    adapt_notes: list[str] = []

    governor = Governor(len(chunks), requested_workers, use_adaptive)
    parallel_ok = (bool(getattr(engine, "parallel_safe", False))
                   and len(chunks) > 1 and governor.limit() > 1)

    def status() -> dict[str, Any]:
        elapsed = max(0.0, time.monotonic() - started_parts)
        rate = (done_chars / elapsed) if started_parts and elapsed > 0.05 else 0.0
        fields = governor.status_fields()
        fields.update({
            "parts": len(chunks),
            "parts_done": parts_done,
            "chars_done": done_chars,
            "total_chars": total_chars,
            "chars_per_second": round(rate, 1),
            "elapsed": max(0.0, time.monotonic() - started_all),
        })
        return fields

    def report(phase: str, seconds: float = 0.0, **extra: Any) -> None:
        if progress is None:
            return
        payload = {"phase": phase, "seconds": seconds}
        payload.update(status())
        payload.update(extra)
        try:
            progress(payload)
        except Exception:
            # A broken progress sink must never take a render down with it.
            pass

    def note(text_note: str) -> None:
        if not text_note:
            return
        if text_note not in adapt_notes:
            adapt_notes.append(text_note)
        report("adapt", message=text_note)

    # Any abandoned part files from an older build are cleared before the new
    # run, so downloads shows exactly one file per finished render.
    cleanup_partials(target.parent)
    report("prepare")
    report("plan", parallel=parallel_ok, **governor.status_fields())

    scratch = Path(tempfile.mkdtemp(prefix="render-", dir=work_dir(project)))

    def render_one(index: int, chunk: str) -> tuple[Path, dict]:
        """Render one part, validating it and retrying once on corruption."""
        last: Exception | None = None
        for attempt in range(2):
            part = scratch / f"part{index:03d}{engine.extension}"
            try:
                produced = Path(engine.render(chunk, settings, part))
                info = audio_io.validate_audio(produced)
                return produced, info
            except Exception as exc:
                last = exc
                for leftover in {part, part.with_suffix(".wav")}:
                    try:
                        leftover.unlink()
                    except OSError:
                        pass
                if _looks_permanent(str(exc)):
                    break
                if attempt == 0:
                    message = governor.observe(False, exc)
                    if message:
                        note(message)
                    time.sleep(0.35)
        if isinstance(last, EngineError):
            raise last
        raise EngineError(
            f"A rendered part was corrupt or incomplete ({last}). VoiceForge "
            "removed it and tried again; free some disk space or check the "
            "connection, then retry.") from last

    try:
        if len(chunks) <= 1:
            started_parts = time.monotonic()
            report("part", index=1, part_chars=total_chars, active=1)
            began = time.monotonic()
            produced, _info = render_one(1, text)
            path = _install_take(produced, target)
            done_chars = total_chars
            parts_done = 1
            report("part_done", seconds=time.monotonic() - began, index=1,
                   part_chars=total_chars, active=0)
        elif not parallel_ok:
            started_parts = time.monotonic()
            rendered: list[Path] = []
            for index, chunk in enumerate(chunks, start=1):
                report("part", index=index, part_chars=len(chunk), active=1)
                began = time.monotonic()
                produced, _info = render_one(index, chunk)
                rendered.append(produced)
                done_chars += len(chunk)
                parts_done = index
                message = governor.observe(True)
                if message:
                    note(message)
                report("part_done", seconds=time.monotonic() - began,
                       index=index, part_chars=len(chunk), active=0)
            _space_check(rendered, target)
            report("stitch")
            path = concatenate_audio(rendered, target, gap_seconds=gap)
        else:
            started_parts = time.monotonic()
            rendered_by_index: dict[int, Path] = {}
            pending: dict[futures.Future, tuple[int, str]] = {}
            attempts: dict[int, int] = {}
            reported: set[int] = set()
            pool = futures.ThreadPoolExecutor(
                max_workers=governor.limit(), thread_name_prefix="vf-part")

            def submit(index: int, chunk: str) -> None:
                pending[pool.submit(render_one, index, chunk)] = (index, chunk)
                if index not in reported:
                    reported.add(index)
                    report("part", index=index, part_chars=len(chunk),
                           active=len(pending))
                peak_workers_local = len(pending)
                nonlocal peak_workers
                peak_workers = max(peak_workers, peak_workers_local)

            try:
                next_index = 0
                while next_index < len(chunks) or pending:
                    limit_now = max(1, governor.limit())
                    while next_index < len(chunks) and len(pending) < limit_now:
                        submit(next_index + 1, chunks[next_index])
                        next_index += 1
                    if not pending:
                        continue
                    finished, _ = futures.wait(
                        tuple(pending), return_when=futures.FIRST_COMPLETED)
                    for done in finished:
                        index, chunk = pending.pop(done)
                        try:
                            produced, _info = done.result()
                        except Exception as exc:
                            attempts[index] = attempts.get(index, 1) + 1
                            # render_one already retried once; a second
                            # failure is a real problem, not a transient one.
                            raise exc
                        rendered_by_index[index] = produced
                        done_chars += len(chunk)
                        parts_done += 1
                        governor.observe(True)
                        report("part_done",
                               seconds=0.0, index=index,
                               part_chars=len(chunk),
                               active=len(pending))
                    while next_index < len(chunks) and len(pending) < max(
                            1, governor.limit()):
                        submit(next_index + 1, chunks[next_index])
                        next_index += 1
            finally:
                pool.shutdown(wait=True, cancel_futures=True)

            if len(rendered_by_index) != len(chunks):
                raise EngineError(
                    "The render stopped before every part was finished - "
                    "nothing was written to downloads. Please try again.")
            rendered = [rendered_by_index[i] for i in range(1, len(chunks) + 1)]
            _space_check(rendered, target)
            report("stitch")
            path = concatenate_audio(rendered, target, gap_seconds=gap)
    finally:
        # Only the stitched result survives; chunk files never touch downloads.
        shutil.rmtree(scratch, ignore_errors=True)

    effect = str(settings.get("effect", "none") or "none").lower()
    applied_effects = effect not in ("", "none") or has_effects(settings)
    if applied_effects:
        report("effects")
        try:
            path = Path(process_file(path, effect, settings))
        except Exception as exc:
            raise EngineError(f"effect {effect!r} failed: {exc}") from exc
        audio_io.validate_audio(path)

    info = audio_io.validate_audio(path)
    elapsed = max(0.0, time.monotonic() - started_all)
    meta = {
        "bytes": info["bytes"],
        "duration": info["duration"],
        "sample_rate": info["sample_rate"],
        "channels": info["channels"],
        "format": format_for_path(path, fmt),
        "parts": len(chunks),
        "workers": peak_workers,
        "adaptive": use_adaptive,
        "elapsed": elapsed,
        "engine": engine.name,
        "effects": effect if applied_effects else "none",
        "adapt_notes": list(adapt_notes),
    }
    report("done", meta=meta)
    return RenderOutcome(path, engine.name, meta)
