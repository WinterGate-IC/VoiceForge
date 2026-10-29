"""Engine interface. A backend turns (text, settings) into an audio file."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EngineError(RuntimeError):
    """Backend cannot run or failed mid-render."""


class Engine:
    name: str = "base"
    extension: str = ".mp3"
    # True only for engines whose render() is safe to call from several
    # threads at once. Edge is network-bound and qualifies; local clone
    # models do not.
    parallel_safe: bool = False

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def available(self) -> tuple[bool, str]:
        """(usable, human-readable reason)."""
        raise NotImplementedError

    def render(self, text: str, settings: dict[str, Any], out_path: Path) -> Path:
        raise NotImplementedError
