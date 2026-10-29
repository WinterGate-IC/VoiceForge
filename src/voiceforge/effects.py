"""Post-processing DSP chains and the voice lab.

Deliberately dependency-light: numpy for the maths, soundfile for audio I/O.
No ffmpeg, no scipy. Filters are applied in the frequency domain (fast, and
stable for static curves) while the recursive pieces - comb and allpass
reverb, compression - are computed block-wise so they stay vectorised.

There are two layers:

*   **Chains** are fixed, named characters (room, demon, telephone, robot,
    cave, cathedral...) available everywhere: CLI, presets, styles.
*   **The voice lab** is a set of continuous knobs (bass, echo, chorus, ring,
    vibrato, crush...) persisted like any other setting, so every experiment
    is undoable and can be saved into a voice profile.

Every function takes a mono signal unless it is explicitly a file-level
helper, and every output stays finite, bounded and the same length as its
input.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .settings import ADVANCED_PARAMS, PARAMS

CHAINS = (
    "none", "room", "hall", "demon", "masked", "telephone", "broadcast",
    "loudspeaker", "cave", "cathedral", "robot", "underwater", "megaphone",
    "cinema", "ghost", "vintage", "alien",
)


# --------------------------------------------------------------- primitives
def _comb(x: np.ndarray, delay: int, feedback: float) -> np.ndarray:
    """y[n] = x[n] + feedback * y[n - delay], computed in blocks of `delay`."""
    y = x.astype(np.float32, copy=True)
    delay = max(1, delay)
    for start in range(delay, len(y), delay):
        end = min(start + delay, len(y))
        y[start:end] += feedback * y[start - delay:end - delay]
    return y


def _delay(x: np.ndarray, delay: int) -> np.ndarray:
    out = np.zeros_like(x)
    delay = max(1, min(delay, len(x)))
    out[delay:] = x[:-delay]
    return out


def _allpass(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    y = np.zeros_like(x)
    d = max(1, delay)
    for start in range(0, len(x), d):
        end = min(start + d, len(x))
        xdel = x[start - d:end - d] if start >= d else np.zeros(end - start, dtype=np.float32)
        ydel = y[start - d:end - d] if start >= d else np.zeros(end - start, dtype=np.float32)
        y[start:end] = -g * x[start:end] + xdel + g * ydel
    return y


def _reverb(x: np.ndarray, sr: int, room: float = 0.78,
            wet: float = 0.14) -> np.ndarray:
    """Small Schroeder reverb: four parallel combs into two allpass stages."""
    scale = sr / 44100.0
    combs = [int(d * scale) for d in (1116, 1188, 1277, 1356)]
    acc = np.zeros_like(x)
    for d in combs:
        acc += _comb(x, d, room)
    acc /= len(combs)
    for d, g in ((int(556 * scale), 0.5), (int(441 * scale), 0.5)):
        acc = _allpass(acc, d, g)
    peak = np.max(np.abs(acc)) or 1.0
    acc /= peak
    return ((1.0 - wet) * x + wet * acc).astype(np.float32)


def _spectral_shape(x: np.ndarray, sr: int, lo: float | None, hi: float | None,
                    slope: float = 0.15) -> np.ndarray:
    """Smooth band-limiting in the frequency domain (no ringing artefacts)."""
    n = len(x)
    if n < 32:
        return x
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    mask = np.ones_like(freqs)
    if lo:
        mask *= 1.0 / (1.0 + np.exp(-(freqs - lo) / (lo * slope + 1e-6)))
    if hi:
        mask *= 1.0 / (1.0 + np.exp((freqs - hi) / (hi * slope + 1e-6)))
    return np.fft.irfft(spec * mask, n=n).astype(np.float32)


def _eq(x: np.ndarray, sr: int, bass_db: float = 0.0,
        treble_db: float = 0.0) -> np.ndarray:
    """Two gentle shelves: weight rises below ~180 Hz and above ~3.5 kHz."""
    if abs(bass_db) < 0.01 and abs(treble_db) < 0.01:
        return x
    n = len(x)
    if n < 32:
        return x
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    low = 1.0 / (1.0 + np.square(freqs / 180.0))
    high = np.square(freqs / 3500.0) / (1.0 + np.square(freqs / 3500.0))
    gain = 10.0 ** ((bass_db * low + treble_db * high) / 20.0)
    return np.fft.irfft(spec * gain, n=n).astype(np.float32)


def _compress(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Soft compressor with a fast attack and a lazy release.

    Works on 10 ms blocks, so it stays fast on hour-long audiobooks while
    still removing the biggest peaks. `amount` is 0-1.
    """
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0 or len(x) < 32:
        return x
    n = len(x)
    block = max(16, int(sr * 0.01))
    padded = np.pad(np.abs(x), (0, (-n) % block), mode="constant")
    env = padded.reshape(-1, block).mean(axis=1).astype(np.float32)
    gains = np.empty_like(env)
    threshold = 0.08
    ratio = 1.0 + amount * 7.0
    g = 1.0
    for index, level in enumerate(env):
        if level <= threshold:
            desired = 1.0
        else:
            desired = (threshold + (level - threshold) / ratio) / max(float(level), 1e-9)
        # Snap down quickly, recover gently: keeps consonants but tames peaks.
        coeff = 0.45 if desired < g else 0.10
        g += coeff * (desired - g)
        gains[index] = g
    return (x * np.repeat(gains, block)[:n]).astype(np.float32)


def _soft_clip(x: np.ndarray, drive: float) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


def _echo(x: np.ndarray, sr: int, ms: float, feedback: float,
          wet: float) -> np.ndarray:
    d = int(sr * ms / 1000.0)
    return (1.0 - wet) * x + wet * _comb(x, d, feedback)


def _chorus(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Two slowly detuned, delayed copies - a cheap doubled voice."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0 or len(x) < 64:
        return x
    n = len(x)
    index = np.arange(n, dtype=np.float64)
    time = index / sr
    scale = sr / 1000.0
    one = (18.0 + 9.0 * np.sin(2 * np.pi * 0.23 * time)) * scale
    two = (26.0 + 11.0 * np.sin(2 * np.pi * 0.31 * time + 1.7)) * scale
    first = np.interp(index - one, index, x)
    second = np.interp(index - two, index, x)
    wet = (first + second) * 0.5
    return ((1.0 - 0.5 * amount) * x + 0.5 * amount * wet).astype(np.float32)


def _ring_mod(x: np.ndarray, sr: int, amount: float,
              rate: float = 220.0) -> np.ndarray:
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0:
        return x
    time = np.arange(len(x), dtype=np.float64) / sr
    carrier = np.sin(2 * np.pi * max(20.0, float(rate)) * time).astype(np.float32)
    return ((1.0 - amount) * x + amount * x * carrier).astype(np.float32)


def _tremolo(x: np.ndarray, sr: int, amount: float,
             rate: float = 5.0) -> np.ndarray:
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0:
        return x
    time = np.arange(len(x), dtype=np.float64) / sr
    lfo = (0.5 + 0.5 * np.sin(2 * np.pi * max(0.1, float(rate)) * time)).astype(np.float32)
    return (x * (1.0 - amount + amount * lfo)).astype(np.float32)


def _vibrato(x: np.ndarray, sr: int, amount: float,
             rate: float = 5.5) -> np.ndarray:
    """Pitch wobble via a modulated read position (max ~4 ms)."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0 or len(x) < 32:
        return x
    n = len(x)
    index = np.arange(n, dtype=np.float64)
    time = index / sr
    depth = amount * 0.004
    offset = depth * np.sin(2 * np.pi * max(0.1, float(rate)) * time)
    read = index - offset * sr
    return np.interp(read, index, x).astype(np.float32)


def _flutter(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Tape-style wow (slow) plus flutter (fast) pitch drift."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0 or len(x) < 32:
        return x
    n = len(x)
    index = np.arange(n, dtype=np.float64)
    time = index / sr
    drift = (np.sin(2 * np.pi * 0.7 * time)
             + 0.45 * np.sin(2 * np.pi * 6.3 * time + 0.8))
    read = index - amount * drift * 0.003 * sr
    return np.interp(read, index, x).astype(np.float32)


def _crush(x: np.ndarray, amount: float) -> np.ndarray:
    """Bit-depth reduction: 0 is clean, 12 is a broken digital signal."""
    amount = max(0, min(12, int(amount)))
    if amount <= 0:
        return x
    bits = max(2, 16 - amount)
    steps = float(2 ** (bits - 1))
    return (np.round(x * steps) / steps).astype(np.float32)


def _hiss(x: np.ndarray, amount: float = 0.0015) -> np.ndarray:
    return x + np.random.default_rng(7).normal(0.0, amount, x.shape).astype(np.float32)


def _finish(x: np.ndarray) -> np.ndarray:
    """Guarantee finite, bounded, consistently loud output.

    Chain filters can leave a voice very quiet (a telephone band-pass, for
    example). Peak-only limiting preserved that unevenness, so this also
    lifts quiet results towards a common RMS target, with a generous ceiling
    so a near-silent reverb tail is never blown up into noise.
    """
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    if x.size == 0:
        return np.zeros_like(x, dtype=np.float32)
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    if rms > 1e-6:
        gain = min(max(0.14 / rms, 0.25), 4.0)
        x = x * gain
    peak = float(np.max(np.abs(x)))
    if peak > 0.98:
        x = x * (0.98 / peak)
    return np.clip(x, -1.0, 1.0).astype(np.float32)


# --------------------------------------------------------------- chains
def apply_chain_to_signal(x: np.ndarray, sr: int, chain: str) -> np.ndarray:
    chain = (chain or "none").lower()
    if chain in ("", "none"):
        return x
    if x.ndim > 1:
        # Chain processors are mono. Keep the public helper honest for callers
        # that hand it a stereo buffer instead of silently failing mid-way.
        return np.stack([apply_chain_to_signal(x[:, i], sr, chain)
                         for i in range(x.shape[1])], axis=1)

    if chain == "room":
        return _finish(_reverb(x, sr, room=0.72, wet=0.14))

    if chain == "hall":
        y = _reverb(x, sr, room=0.84, wet=0.34)
        y = _echo(y, sr, 115, 0.30, 0.28)
        return _finish(y)

    if chain == "demon":
        y = _reverb(x, sr, room=0.80, wet=0.30)
        y = _eq(y, sr, 5, -3)
        y = _soft_clip(y, 2.4)
        y = _spectral_shape(y, sr, 70, 5200, slope=0.25)
        return _finish(y)

    if chain == "masked":
        y = _spectral_shape(x, sr, 190, 5600, slope=0.20)
        y = _reverb(y, sr, room=0.66, wet=0.18)
        y = _soft_clip(y, 1.7)
        return _finish(_hiss(y))

    if chain == "telephone":
        y = _spectral_shape(x, sr, 360, 3100, slope=0.10)
        y = _soft_clip(y, 1.9)
        y = _spectral_shape(y, sr, 300, 3400, slope=0.14)
        return _finish(_hiss(y, 0.0022))

    if chain == "broadcast":
        y = _spectral_shape(x, sr, 95, 13000, slope=0.12)
        y = _eq(y, sr, 3, 1)
        y = _compress(y, sr, 0.35)
        y = _soft_clip(y, 1.35)
        y = _reverb(y, sr, room=0.55, wet=0.07)
        return _finish(y)

    if chain == "loudspeaker":
        y = _spectral_shape(x, sr, 320, 4300, slope=0.16)
        y = _eq(y, sr, 5, -3)
        y = _compress(y, sr, 0.55)
        y = _soft_clip(y, 2.3)
        y = _echo(y, sr, 62, 0.22, 0.18)
        y = _reverb(y, sr, room=0.74, wet=0.20)
        return _finish(y)

    if chain == "cave":
        y = _spectral_shape(x, sr, 80, 3800, slope=0.18)
        y = _eq(y, sr, 5, -3)
        y = _reverb(y, sr, room=0.90, wet=0.48)
        y = _echo(y, sr, 260, 0.42, 0.30)
        return _finish(y)

    if chain == "cathedral":
        y = _spectral_shape(x, sr, 70, 9000, slope=0.14)
        y = _reverb(y, sr, room=0.93, wet=0.56)
        y = _echo(y, sr, 420, 0.36, 0.22)
        return _finish(y)

    if chain == "robot":
        y = _ring_mod(x, sr, 0.65, 105)
        y = _crush(y, 4)
        y = _spectral_shape(y, sr, 180, 4200, slope=0.18)
        y = _soft_clip(y, 1.8)
        return _finish(y)

    if chain == "underwater":
        y = _spectral_shape(x, sr, 60, 1100, slope=0.12)
        y = _vibrato(y, sr, 0.35, 1.2)
        y = _tremolo(y, sr, 0.22, 0.9)
        y = _reverb(y, sr, room=0.82, wet=0.30)
        return _finish(y)

    if chain == "megaphone":
        y = _spectral_shape(x, sr, 500, 3200, slope=0.08)
        y = _compress(y, sr, 0.45)
        y = _soft_clip(y, 2.6)
        y = _echo(y, sr, 55, 0.18, 0.12)
        return _finish(y)

    if chain == "cinema":
        y = _eq(x, sr, 7, 1)
        y = _compress(y, sr, 0.55)
        y = _reverb(y, sr, room=0.62, wet=0.12)
        y = _soft_clip(y, 1.2)
        return _finish(y)

    if chain == "ghost":
        y = _spectral_shape(x, sr, 220, 7000, slope=0.20)
        y = _reverb(y, sr, room=0.95, wet=0.62)
        y = _chorus(y, sr, 0.45)
        y = _vibrato(y, sr, 0.18, 2.4)
        return _finish(y)

    if chain == "vintage":
        y = _spectral_shape(x, sr, 180, 4200, slope=0.12)
        y = _hiss(y, 0.0012)
        y = _flutter(y, sr, 0.35)
        y = _soft_clip(y, 1.5)
        y = _crush(y, 2)
        return _finish(y)

    if chain == "alien":
        y = _ring_mod(x, sr, 0.55, 310)
        y = _spectral_shape(y, sr, 220, 6000, slope=0.20)
        y = _vibrato(y, sr, 0.50, 7.0)
        y = _echo(y, sr, 150, 0.30, 0.20)
        return _finish(y)

    raise ValueError(f"unknown effect chain {chain!r} (known: {', '.join(CHAINS)})")


# --------------------------------------------------------------- voice lab
def has_effects(settings: dict | None) -> bool:
    """True when any voice-lab knob is away from its neutral value."""
    if not settings:
        return False
    for name in ADVANCED_PARAMS:
        default = PARAMS[name].default
        try:
            value = settings.get(name, default)
            if abs(float(value) - float(default)) > 1e-6:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _advanced_mono(x: np.ndarray, sr: int, settings: dict) -> np.ndarray:
    get = settings.get
    y = _eq(x, sr, float(get("bass", 0)), float(get("treble", 0)))
    y = _compress(y, sr, float(get("punch", 0)) / 100.0)
    y = _chorus(y, sr, float(get("chorus", 0.0)))
    echo_mix = float(get("echo_mix", 0.0))
    if echo_mix > 0.0:
        y = _echo(y, sr, float(get("echo_ms", 300)),
                  float(get("echo_feedback", 0.35)), min(1.0, echo_mix))
    reverb = float(get("reverb", 0.0))
    if reverb > 0.0:
        y = _reverb(y, sr, room=0.80, wet=min(1.0, reverb))
    y = _ring_mod(y, sr, float(get("ring", 0.0)),
                  float(get("ring_rate", 220)))
    y = _tremolo(y, sr, float(get("tremolo", 0.0)),
                 float(get("tremolo_rate", 5.0)))
    y = _vibrato(y, sr, float(get("vibrato", 0.0)),
                 float(get("vibrato_rate", 5.5)))
    y = _flutter(y, sr, float(get("flutter", 0.0)))
    drive = float(get("drive", 0.0))
    if drive > 0.0:
        y = _soft_clip(y, 1.0 + drive * 7.0)
    y = _crush(y, int(get("crush", 0)))
    return y


def apply_advanced_to_signal(data: np.ndarray, sr: int,
                             settings: dict | None = None) -> np.ndarray:
    """Apply the voice-lab knobs to mono or multichannel float audio."""
    if not has_effects(settings):
        return data
    assert settings is not None
    if data.ndim == 1:
        return _finish(_advanced_mono(data, sr, settings))

    cols = [_advanced_mono(data[:, i], sr, settings)
            for i in range(data.shape[1])]
    out = np.stack(cols, axis=1)
    width = int(round(float(settings.get("width", 100))))
    if out.shape[1] >= 2 and width != 100:
        left, right = out[:, 0], out[:, 1]
        mid = (left + right) * 0.5
        side = (left - right) * 0.5 * (max(0, width) / 100.0)
        out[:, 0] = mid + side
        out[:, 1] = mid - side
    return _finish(out)


# --------------------------------------------------------------- file I/O
def _process_buffer(data: np.ndarray, sr: int, chain: str,
                    settings: dict | None = None) -> np.ndarray:
    if data.ndim == 1:
        out = apply_chain_to_signal(data, sr, chain)
        return apply_advanced_to_signal(out, sr, settings)
    cols = [apply_chain_to_signal(data[:, i], sr, chain)
            for i in range(data.shape[1])]
    return apply_advanced_to_signal(np.stack(cols, axis=1), sr, settings)


def process_file(path: Path, chain: str,
                 settings: dict | None = None) -> Path:
    """Apply a chain and/or voice-lab settings to a file in place.

    Returns the path actually written. The chain may be ``none`` as long as
    at least one voice-lab knob is active.
    """
    chain = (chain or "none").lower()
    if chain in ("", "none") and not has_effects(settings):
        return path

    try:
        import soundfile as sf  # noqa: F401 - validated below for a clear error
    except ImportError as exc:
        raise RuntimeError(
            "soundfile is required for voice effects: pip install soundfile") from exc

    from . import audio_io

    path = Path(path)
    data, sr = audio_io.read_audio(path)
    out = _process_buffer(data, sr, chain, settings)

    # Write to a hidden sibling and rename it into place. If this build of
    # libsndfile cannot encode MP3, write_audio returns a WAV path instead;
    # remove the original MP3 so only the playable result remains.
    written = audio_io.write_audio(out, sr, path)
    if written != path:
        try:
            path.unlink()
        except OSError:
            pass
    return written
