"""Backend registry."""

from __future__ import annotations

from pathlib import Path

from .base import Engine, EngineError
from .clone_engine import CloneEngine
from .edge_engine import EdgeEngine, list_voices

__all__ = ["Engine", "EngineError", "EdgeEngine", "CloneEngine", "list_voices", "get_engine"]


def get_engine(name: str, root: Path) -> Engine:
    name = (name or "edge").lower()
    if name == "edge":
        return EdgeEngine(root)
    if name == "clone":
        return CloneEngine(root)
    raise EngineError(f"unknown engine {name!r} (choose: edge, clone)")
