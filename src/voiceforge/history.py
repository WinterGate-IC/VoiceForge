"""Undo/redo history for voice settings.

Design: a linear list of full settings snapshots plus a cursor. Settings are
tiny (a dozen scalars) so snapshots are cheaper and far less bug-prone than
inverse operations. Everything the user can do is expressible as:

    undo()              -> step back one change
    undo(steps=N)       -> step back N changes
    undo_to(index)      -> jump to snapshot N  (this is "undo everything")
    undo_param(name)    -> revert just this one knob, leave the rest alone
    redo()              -> step forward again

Anything new recorded after an undo discards the redo tail.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .settings import defaults


@dataclass
class Change:
    param: str | None  # None means a batch of params changed at once
    old: Any
    new: Any
    label: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Change":
        return Change(d["param"], d["old"], d["new"], d["label"], d["at"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, states: list[dict[str, Any]] | None = None,
                 changes: list[Change] | None = None, cursor: int = 0) -> None:
        self._states: list[dict[str, Any]] = list(states) if states else [defaults()]
        self._changes: list[Change] = list(changes) if changes else []
        self._cursor = cursor if states else 0

    # ---- state -------------------------------------------------------
    @property
    def current(self) -> dict[str, Any]:
        return dict(self._states[self._cursor])

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def length(self) -> int:
        return len(self._states)

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._states) - 1

    # ---- mutation ----------------------------------------------------
    def record(self, param: str | None, old: Any, new: Any, label: str,
               next_state: dict[str, Any]) -> None:
        """Append a new snapshot, dropping any redo tail."""
        del self._states[self._cursor + 1:]
        del self._changes[self._cursor:]
        self._states.append(dict(next_state))
        self._changes.append(Change(param, old, new, label, _now()))
        self._cursor = len(self._states) - 1

    def undo(self, steps: int = 1) -> int:
        if steps <= 0:
            raise ValueError("steps must be positive")
        if not self.can_undo:
            raise ValueError("nothing to undo")
        self._cursor = max(0, self._cursor - steps)
        return self._cursor

    def redo(self, steps: int = 1) -> int:
        if steps <= 0:
            raise ValueError("steps must be positive")
        if not self.can_redo:
            raise ValueError("nothing to redo")
        self._cursor = min(len(self._states) - 1, self._cursor + steps)
        return self._cursor

    def undo_to(self, index: int) -> int:
        if not (0 <= index < len(self._states)):
            raise ValueError(f"no snapshot {index}; valid 0..{len(self._states) - 1}")
        self._cursor = index
        return self._cursor

    def undo_param(self, name: str) -> Any:
        """Revert one knob to its value before its most recent change.

        Falls back to the factory default when the knob was never changed.
        """
        target: Any = defaults().get(name)
        for i in range(self._cursor - 1, -1, -1):
            ch = self._changes[i]
            if ch.param == name:
                target = ch.old
                break

        state = self.current
        previous = state.get(name)
        state[name] = target
        self.record(name, previous, target, f"undo {name}", state)
        return target

    # ---- introspection ----------------------------------------------
    def entries(self) -> Iterable[tuple[int, Change | None]]:
        """Yield (snapshot_index, change_that_produced_it)."""
        yield 0, None
        for i, ch in enumerate(self._changes, start=1):
            yield i, ch

    def describe(self) -> list[dict[str, Any]]:
        rows = []
        for i, ch in self.entries():
            if ch is None:
                rows.append({"index": i, "current": i == self._cursor,
                             "label": "initial state", "old": "", "new": "", "at": ""})
                continue
            old, new = ch.old, ch.new
            if isinstance(old, dict) and isinstance(new, dict):
                parts = [f"{k}: {old.get(k)} -> {new.get(k)}"
                         for k in new if old.get(k) != new.get(k)]
                old_s, new_s = "", "; ".join(parts)
            else:
                old_s, new_s = str(old), str(new)
            rows.append({
                "index": i,
                "current": i == self._cursor,
                "label": ch.label,
                "old": old_s,
                "new": new_s,
                "at": ch.at,
            })
        return rows

    # ---- persistence -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "states": [dict(s) for s in self._states],
            "changes": [c.to_dict() for c in self._changes],
            "cursor": self._cursor,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "History":
        return History(
            states=[dict(s) for s in d.get("states", [])],
            changes=[Change.from_dict(c) for c in d.get("changes", [])],
            cursor=int(d.get("cursor", 0)),
        )
