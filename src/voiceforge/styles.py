"""Signature styles: a named voice setting plus a DSP chain.

A style is the fast path to a character. Everything it does is still just
parameters, so applying one is undoable and every value stays editable
afterwards - a style is a starting point, not a lock-in.

Styles deliberately reach into the voice-lab knobs now. Two scary voices
should not be the same rate/pitch pair wearing a different reverb; the bass
shelf, drive, flutter and echo are part of what makes each one a character.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    name: str
    description: str
    params: dict = field(default_factory=dict)
    effect: str = "none"


STYLES: dict[str, Style] = {
    "clean": Style(
        "clean", "Untouched voice. No colouring, no effects.", {}, "none"),

    "narrator": Style(
        "narrator", "Warm documentary read: slower, a touch deeper, small room.",
        {"rate": "-8%", "pitch": "-12Hz", "volume": "+4%",
         "bass": 3, "treble": -2, "reverb": 0.10}, "room"),

    "broadcast": Style(
        "broadcast", "Punchy trailer/announcer voice with radio polish.",
        {"rate": "-4%", "pitch": "-4Hz", "volume": "+10%",
         "bass": 4, "treble": 2, "punch": 55, "drive": 0.12}, "broadcast"),

    "scary-deep": Style(
        "scary-deep", "Low, slow and unsettling. Halloween narrator.",
        {"rate": "-18%", "pitch": "-35Hz", "volume": "+2%",
         "bass": 7, "treble": -5, "drive": 0.20, "reverb": 0.25,
         "vibrato": 0.10, "vibrato_rate": 3.2}, "demon"),

    "halloween-echo": Style(
        "halloween-echo", "Haunted-house boom with a long tail.",
        {"rate": "-10%", "pitch": "-20Hz", "volume": "+2%",
         "bass": 4, "treble": -2, "echo_ms": 430, "echo_feedback": 0.46,
         "echo_mix": 0.32, "reverb": 0.35, "width": 125}, "hall"),

    "anonymous": Style(
        "anonymous", "Masked, pitch-flattened, identity-hiding tone.",
        {"rate": "-5%", "pitch": "-10Hz", "volume": "+2%",
         "treble": -3, "chorus": 0.08, "crush": 2, "width": 90}, "masked"),

    "hacker": Style(
        "hacker", "Band-limited phone-line grit. Very 'I am in the mainframe'.",
        {"rate": "+2%", "pitch": "-2Hz",
         "treble": 4, "crush": 4, "drive": 0.10}, "telephone"),

    "loudspeaker": Style(
        "loudspeaker", "Old public-address horn: compressed, boxy, cavernous.",
        {"rate": "-12%", "pitch": "-8Hz", "volume": "+8%",
         "bass": 6, "treble": -4, "punch": 70, "drive": 0.18}, "loudspeaker"),

    "propaganda": Style(
        "propaganda", "Mid-century PA announcement: slow, overdriven, enormous room.",
        {"rate": "-15%", "pitch": "-10Hz", "volume": "+10%",
         "bass": 8, "treble": -3, "punch": 72, "drive": 0.25}, "loudspeaker"),

    "cave": Style(
        "cave", "Deep stone chamber: huge tail, dark body, slow delivery.",
        {"rate": "-14%", "pitch": "-22Hz", "bass": 6, "treble": -4,
         "reverb": 0.28, "echo_ms": 280, "echo_feedback": 0.40,
         "echo_mix": 0.25}, "cave"),

    "cathedral": Style(
        "cathedral", "Vast, sacred space. Long, clean reflections.",
        {"rate": "-10%", "pitch": "-12Hz", "reverb": 0.40, "echo_ms": 430,
         "echo_feedback": 0.35, "echo_mix": 0.20, "width": 120}, "cathedral"),

    "robot": Style(
        "robot", "Machine voice: metallic ring, crushed bits, tight image.",
        {"rate": "-2%", "ring": 0.55, "ring_rate": 110, "crush": 4,
         "drive": 0.12, "width": 70}, "robot"),

    "underwater": Style(
        "underwater", "Muffled, slow and swaying, like a voice through water.",
        {"rate": "-16%", "pitch": "-18Hz", "bass": 5, "treble": -10,
         "vibrato": 0.25, "vibrato_rate": 1.4, "chorus": 0.15}, "underwater"),

    "megaphone": Style(
        "megaphone", "Horn speaker at a rally: narrow, loud and overdriven.",
        {"rate": "-3%", "pitch": "+4Hz", "volume": "+8%", "punch": 70,
         "drive": 0.18}, "megaphone"),

    "cinema": Style(
        "cinema", "Trailer-grade weight: deep, wide, compressed and close.",
        {"rate": "-8%", "pitch": "-10Hz", "volume": "+6%", "bass": 8,
         "treble": 1, "punch": 60, "width": 135, "reverb": 0.15}, "cinema"),

    "ghost": Style(
        "ghost", "Breathy, detuned and far away, with a very long trail.",
        {"rate": "-12%", "pitch": "-6Hz", "chorus": 0.35, "reverb": 0.45,
         "width": 150, "vibrato": 0.10, "vibrato_rate": 2.2}, "ghost"),

    "vintage": Style(
        "vintage", "Worn tape or old radio: dull, wobbly and slightly broken.",
        {"rate": "-9%", "pitch": "-5Hz", "bass": 3, "treble": -7,
         "flutter": 0.35, "crush": 2}, "vintage"),

    "alien": Style(
        "alien", "Not from here: ring-modulated, unstable and wide.",
        {"rate": "-4%", "pitch": "+6Hz", "ring": 0.40, "ring_rate": 330,
         "vibrato": 0.40, "vibrato_rate": 8.0, "width": 140}, "alien"),
}


class StyleError(ValueError):
    pass


def get(name: str) -> Style:
    key = (name or "").strip().lower().replace("_", "-")
    if key not in STYLES:
        raise StyleError(f"unknown style {name!r}. Known: {', '.join(STYLES)}")
    return STYLES[key]


def as_pairs(style: Style) -> list[str]:
    """Style -> `name=value` list, including the effect chain."""
    pairs = [f"{k}={v}" for k, v in style.params.items()]
    pairs.append(f"effect={style.effect}")
    return pairs


def listing() -> list[Style]:
    return list(STYLES.values())
