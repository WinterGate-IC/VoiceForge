"""Built-in starter voices.

A fresh install should not open onto an empty library. These are ordinary
designed profiles - the same thing `voice create` writes - just seeded on
first use so there is always something to press Generate with.

The point of a default is to demonstrate a *different* sound, not to give the
same announcer seven names. Each entry therefore combines a different base
voice, delivery and a deliberate mix of voice-lab character: warm shelves for
the narrator, compression and drive for the broadcaster, long tails for the
haunted host, ring modulation and crushed bits for the robot, and so on.

Rules:
  * only seeded when the library is empty, so they never bury your own work;
  * never overwritten, so editing one keeps your edit;
  * upgrades only *add* missing voice-lab keys to an existing default, so an
    old library gains the new depth without losing its saved edits;
  * `vf voice seed` (or the Restore defaults button) brings back any deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import library, styles
from .settings import defaults


@dataclass(frozen=True)
class DefaultVoice:
    name: str
    style: str
    voice: str
    notes: str


DEFAULT_VOICES: tuple[DefaultVoice, ...] = (
    DefaultVoice(
        "narrator", "narrator", "en-GB-RyanNeural",
        "Default - warm documentary read. Slow, grounded, small room."),
    DefaultVoice(
        "broadcaster", "broadcast", "en-US-AndrewMultilingualNeural",
        "Default - punchy trailer announcer with radio polish."),
    DefaultVoice(
        "scary-storyteller", "scary-deep", "en-US-BrianMultilingualNeural",
        "Default - low, slow and unsettling. Horror narration."),
    DefaultVoice(
        "halloween-host", "halloween-echo", "en-US-EmmaMultilingualNeural",
        "Default - haunted-house boom with a long tail."),
    DefaultVoice(
        "anonymous", "anonymous", "en-US-GuyNeural",
        "Default - masked and pitch-flattened. Hides identity, not intent."),
    DefaultVoice(
        "hacker", "hacker", "en-US-AvaMultilingualNeural",
        "Default - band-limited phone-line grit. 'I am in the mainframe.'"),
    DefaultVoice(
        "propaganda", "propaganda", "en-US-ChristopherNeural",
        "Default - mid-century PA announcement: slow, overdriven, huge room."),
    DefaultVoice(
        "cinema-trailer", "cinema", "en-US-AndrewMultilingualNeural",
        "Default - deep, wide, compressed trailer voice."),
    DefaultVoice(
        "cave-oracle", "cave", "en-GB-ThomasNeural",
        "Default - slow prophecy from a very large stone room."),
    DefaultVoice(
        "robot-host", "robot", "en-US-AvaMultilingualNeural",
        "Default - metallic machine host with crushed digital edges."),
    DefaultVoice(
        "ghost-whisper", "ghost", "en-US-EmmaMultilingualNeural",
        "Default - detuned, breathy and impossibly far away."),
    DefaultVoice(
        "alien-signal", "alien", "en-US-AriaNeural",
        "Default - unstable ring-modulated transmission from elsewhere."),
)


def _profile_settings(entry: DefaultVoice) -> dict:
    settings = defaults()
    style = styles.get(entry.style)
    settings.update(style.params)
    settings["effect"] = style.effect
    settings["voice"] = entry.voice
    settings["reference"] = ""
    return settings


def _already_has(root: Path, name: str) -> bool:
    return (library.folder(root, name) / "profile.json").exists()


def restore(root: Path) -> list[str]:
    """Create every default that is currently missing. Returns names created."""
    created: list[str] = []
    for entry in DEFAULT_VOICES:
        name = library.slug(entry.name)
        if _already_has(root, name):
            continue
        library.create(root, name, _profile_settings(entry),
                       notes=entry.notes, builtin=True)
        created.append(name)
    return created


def upgrade(root: Path) -> list[str]:
    """Add new voice-lab keys to existing built-in profiles.

    Only keys that are *missing* are filled in. A user who changed the bass or
    saved a different voice keeps every value they chose; they simply gain the
    controls that did not exist when their library was first seeded.
    """
    upgraded: list[str] = []
    for entry in DEFAULT_VOICES:
        name = library.slug(entry.name)
        if not _already_has(root, name):
            continue
        try:
            prof = library.load(root, name)
        except (library.LibraryError, ValueError):
            continue
        if not prof.builtin:
            continue
        fresh = _profile_settings(entry)
        merged = dict(prof.settings)
        changed = False
        for key, value in fresh.items():
            if key not in merged:
                merged[key] = value
                changed = True
        if changed:
            library.update(root, name, merged, notes=prof.notes)
            upgraded.append(name)
    return upgraded


def ensure_defaults(root: Path, only_when_empty: bool = True) -> list[str]:
    """Seed on an empty library (default) or restore everything missing.

    Existing defaults are always offered the newest voice-lab keys; that is
    additive only, so user edits survive.
    """
    created: list[str] = []
    if not only_when_empty or not library.listing(root):
        created = restore(root)
    upgrade(root)
    return created
