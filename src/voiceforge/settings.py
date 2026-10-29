"""Parameter registry for VoiceForge.

Every adjustable knob lives here exactly once: default, type, which engine
honours it, valid range and help text. The CLI, the undo system and the
preset system all read from this table, so adding a knob is a one-line change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class ParamError(ValueError):
    """Raised when a user-supplied parameter value is invalid."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str  # pct | hz | float | int | str
    default: Any
    engines: tuple[str, ...]
    help: str
    lo: float | None = None
    hi: float | None = None

    def coerce(self, raw: str) -> Any:
        """Turn a CLI string into a validated, normalised value."""
        if self.kind == "str":
            return raw.strip()

        if self.kind in ("pct", "hz"):
            unit = "%" if self.kind == "pct" else "Hz"
            v = raw.strip().replace(" ", "")
            if v.endswith(unit):
                v = v[: -len(unit)]
            if not v:
                raise ParamError(f"{self.name}: expected e.g. +10{unit}, got {raw!r}")
            if v[0] not in "+-":
                v = "+" + v
            pattern = r"^[+-]\d{1,3}$" if self.kind == "pct" else r"^[+-]\d{1,4}$"
            if not re.match(pattern, v):
                raise ParamError(
                    f"{self.name}: expected e.g. +10{unit} or -5{unit}, got {raw!r}")
            return f"{v}{unit}"

        try:
            if self.kind == "int":
                value: Any = int(str(raw).strip())
            else:
                value = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ParamError(f"{self.name}: expected a number, got {raw!r}") from None

        if self.kind == "float" and self.lo is not None and not (self.lo <= value <= self.hi):  # type: ignore[operator]
            raise ParamError(f"{self.name}: must be between {self.lo} and {self.hi}, got {value}")
        if self.kind == "int" and self.lo is not None and not (self.lo <= value <= self.hi):  # type: ignore[operator]
            raise ParamError(f"{self.name}: must be an integer between {self.lo} and {self.hi}, got {value}")
        return value

    def fmt(self, value: Any) -> str:
        if self.kind == "float":
            return f"{float(value):g}"
        return str(value)


PARAMS: dict[str, ParamSpec] = {
    "voice": ParamSpec(
        "voice", "str", "en-US-AndrewMultilingualNeural", ("edge", "clone"),
        "Voice to speak with. For the edge engine this is a full short name "
        "(run: vf voices).",
    ),
    "rate": ParamSpec(
        "rate", "pct", "+0%", ("edge",),
        "Speaking speed offset. +25% is noticeably faster, -10% slower.",
    ),
    "pitch": ParamSpec(
        "pitch", "hz", "+0Hz", ("edge",),
        "Pitch shift in Hz. -30Hz deeper, +30Hz brighter.",
    ),
    "volume": ParamSpec(
        "volume", "pct", "+0%", ("edge",),
        "Output volume offset, e.g. +10%.",
    ),
    "effect": ParamSpec(
        "effect", "str", "none", ("edge", "clone"),
        "Post-processing chain: none, room, hall, demon, masked, telephone, "
        "broadcast, loudspeaker, cave, cathedral, robot, underwater, "
        "megaphone, cinema, ghost, vintage, alien (see: vf style list).",
    ),
    "bass": ParamSpec(
        "bass", "int", 0, ("edge", "clone"),
        "Low-shelf boost or cut in dB, -18 to +18. Warmer body at +6, "
        "thin and distant below zero.", -18, 18,
    ),
    "treble": ParamSpec(
        "treble", "int", 0, ("edge", "clone"),
        "High-shelf boost or cut in dB, -16 to +16. Air and presence above "
        "zero, muffled and dark below.", -16, 16,
    ),
    "punch": ParamSpec(
        "punch", "int", 0, ("edge", "clone"),
        "Compression amount, 0-100. Evens out dynamics and pushes the voice "
        "forward without simply making it louder.", 0, 100,
    ),
    "width": ParamSpec(
        "width", "int", 100, ("edge", "clone"),
        "Stereo width, 0-200%. 100 is untouched, above 100 widens the image, "
        "below 100 focuses it to the centre.", 0, 200,
    ),
    "echo_ms": ParamSpec(
        "echo_ms", "int", 300, ("edge", "clone"),
        "Echo delay in milliseconds. Short slapback around 80, long cave "
        "tails around 500+.", 40, 1500,
    ),
    "echo_feedback": ParamSpec(
        "echo_feedback", "float", 0.35, ("edge", "clone"),
        "How much echo repeats. 0 is a single slap, 0.9 is a long decaying "
        "trail.", 0.0, 0.95,
    ),
    "echo_mix": ParamSpec(
        "echo_mix", "float", 0.0, ("edge", "clone"),
        "Amount of echo in the output, 0-1. 0 leaves the dry voice alone.",
        0.0, 1.0,
    ),
    "reverb": ParamSpec(
        "reverb", "float", 0.0, ("edge", "clone"),
        "Room reverb amount, 0-1. Small rooms sit near 0.1; cathedrals near "
        "0.5.", 0.0, 1.0,
    ),
    "chorus": ParamSpec(
        "chorus", "float", 0.0, ("edge", "clone"),
        "Chorus / doubled-voice amount, 0-1. Thickens and detunes slightly.",
        0.0, 1.0,
    ),
    "drive": ParamSpec(
        "drive", "float", 0.0, ("edge", "clone"),
        "Saturation, 0-1. Gentle warmth, then radio grit, then a wall of "
        "distortion.", 0.0, 1.0,
    ),
    "ring": ParamSpec(
        "ring", "float", 0.0, ("edge", "clone"),
        "Ring-modulation amount, 0-1. Metallic robot and alien tones.",
        0.0, 1.0,
    ),
    "ring_rate": ParamSpec(
        "ring_rate", "float", 220.0, ("edge", "clone"),
        "Ring-modulation frequency in Hz, 20-2000. Low is a wobble, high is "
        "a machine buzz.", 20.0, 2000.0,
    ),
    "tremolo": ParamSpec(
        "tremolo", "float", 0.0, ("edge", "clone"),
        "Tremolo depth, 0-1. A pulsing volume wobble.", 0.0, 1.0,
    ),
    "tremolo_rate": ParamSpec(
        "tremolo_rate", "float", 5.0, ("edge", "clone"),
        "Tremolo speed in Hz, 0.5-14. Slow sway or nervous flutter.",
        0.5, 14.0,
    ),
    "vibrato": ParamSpec(
        "vibrato", "float", 0.0, ("edge", "clone"),
        "Pitch vibrato depth, 0-1. A subtle human wobble or an unstable "
        "ghost.", 0.0, 1.0,
    ),
    "vibrato_rate": ParamSpec(
        "vibrato_rate", "float", 5.5, ("edge", "clone"),
        "Vibrato speed in Hz, 1-12.", 1.0, 12.0,
    ),
    "flutter": ParamSpec(
        "flutter", "float", 0.0, ("edge", "clone"),
        "Tape wow-and-flutter, 0-1. Old tape, worn cassette, broken projector.",
        0.0, 1.0,
    ),
    "crush": ParamSpec(
        "crush", "int", 0, ("edge", "clone"),
        "Bit-crush amount, 0-12. 0 is clean; 4 is gritty; 12 is a broken "
        "digital signal.", 0, 12,
    ),
    "reference": ParamSpec(
        "reference", "str", "", ("clone",),
        "Name of a voice folder under voices/ to clone from.",
    ),
    "language": ParamSpec(
        "language", "str", "en", ("clone",),
        "Language code for the clone engine, e.g. en, es, fr.",
    ),
    "speed": ParamSpec(
        "speed", "float", 1.0, ("clone",),
        "Playback speed multiplier for the clone engine.", 0.5, 2.0,
    ),
    "temperature": ParamSpec(
        "temperature", "float", 0.75, ("clone",),
        "Expressiveness. Low = flat and safe, high = animated and risky.", 0.05, 1.5,
    ),
    "top_k": ParamSpec(
        "top_k", "int", 50, ("clone",),
        "Sample from the K most likely tokens.", 1, 200,
    ),
    "top_p": ParamSpec(
        "top_p", "float", 0.85, ("clone",),
        "Nucleus sampling cutoff.", 0.1, 1.0,
    ),
    "repetition_penalty": ParamSpec(
        "repetition_penalty", "float", 5.0, ("clone",),
        "Higher values fight stuttering and repeated syllables.", 1.0, 20.0,
    ),
}

# The voice-lab knobs: post-processing that runs on top of the effect chain.
# Kept together so the dialog, the seeder and the renderer share one list.
ADVANCED_PARAMS: tuple[str, ...] = (
    "bass", "treble", "punch", "width",
    "echo_ms", "echo_feedback", "echo_mix", "reverb",
    "chorus", "drive", "ring", "ring_rate",
    "tremolo", "tremolo_rate", "vibrato", "vibrato_rate",
    "flutter", "crush",
)


def defaults() -> dict[str, Any]:
    return {name: spec.default for name, spec in PARAMS.items()}


def advanced_defaults() -> dict[str, Any]:
    """Neutral values for the voice lab (all effects off)."""
    return {name: PARAMS[name].default for name in ADVANCED_PARAMS}


def spec(name: str) -> ParamSpec:
    try:
        return PARAMS[name]
    except KeyError:
        known = ", ".join(PARAMS)
        raise ParamError(f"unknown parameter {name!r}. Known: {known}") from None
