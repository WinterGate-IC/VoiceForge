"""Project state: settings history persisted to project.json."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .history import History
from .settings import PARAMS, ParamError, defaults, spec

PROJECT_FILE = "project.json"


def find_root(start: Path | None = None) -> Path:
    """Locate the data root: $VOICEFORGE_DATA, $VOICEFORGE_HOME, else cwd.

    The first two are how an installed copy and its child processes agree on
    one library; the cwd search is what a source checkout wants.
    """
    for variable in ("VOICEFORGE_DATA", "VOICEFORGE_HOME"):
        env = os.environ.get(variable)
        if env:
            return Path(env).expanduser().resolve()

    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / PROJECT_FILE).exists():
            return candidate
    return here


class Project:
    def __init__(self, root: Path, history: History | None = None,
                 created: str | None = None) -> None:
        self.root = Path(root)
        self.history = history or History()
        self.created = created or datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ---- io ----------------------------------------------------------
    @property
    def path(self) -> Path:
        return self.root / PROJECT_FILE

    @classmethod
    def load(cls, root: Path | None = None) -> "Project":
        root = Path(root) if root else find_root()
        path = root / PROJECT_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(root, History.from_dict(data["history"]), data.get("created"))
        return cls(root)

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "created": self.created,
            "settings": self.settings,
            "history": self.history.to_dict(),
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic: never leave a half-written project

    # ---- settings ----------------------------------------------------
    @property
    def settings(self) -> dict[str, Any]:
        return self.history.current

    def active_engine(self) -> str:
        """Pick a backend: clone if a reference voice is set, else edge."""
        if self.settings.get("reference", ""):
            return "clone"
        return "edge"

    def set_many(self, pairs: list[str], label: str | None = None) -> list[dict[str, Any]]:
        """Apply `name=value` assignments. One undo step per parameter.

        Validated up-front so a typo halfway through cannot leave settings
        half-applied.
        """
        parsed: list[tuple[str, Any]] = []
        for pair in pairs:
            if "=" not in pair:
                raise ParamError(f"expected name=value, got {pair!r}")
            name, raw = pair.split("=", 1)
            name = name.strip().lower().replace("-", "_")
            sp = spec(name)
            parsed.append((name, sp.coerce(raw)))

        applied = []
        for name, value in parsed:
            state = self.settings
            old = state.get(name)
            if old == value:
                applied.append({"param": name, "old": old, "new": value, "noop": True})
                continue
            state[name] = value
            self.history.record(name, old, value, label or f"set {name}", state)
            applied.append({"param": name, "old": old, "new": value, "noop": False})
        self.save()
        return applied

    def apply_settings(self, values: dict[str, Any], label: str = "apply") -> list[dict[str, Any]]:
        """Apply a whole settings dict as ONE undo step (used by the GUI).

        Unknown keys are ignored so the UI can pass every widget blindly.
        Returns the list of parameters that actually changed.
        """
        coerced: dict[str, Any] = {}
        for name, raw in values.items():
            if name not in PARAMS:
                continue
            coerced[name] = spec(name).coerce(raw)

        state = self.settings
        changed = {k: (state.get(k), v) for k, v in coerced.items() if state.get(k) != v}
        if not changed:
            return []

        before = dict(state)
        for k, v in coerced.items():
            state[k] = v
        self.history.record(None, before, dict(state), label, state)
        self.save()
        return [{"param": k, "old": old, "new": new} for k, (old, new) in changed.items()]

    def reset_param(self, name: str) -> Any:
        name = name.strip().lower().replace("-", "_")
        sp = spec(name)
        state = self.settings
        old = state.get(name)
        state[name] = sp.default
        self.history.record(name, old, sp.default, f"reset {name}", state)
        self.save()
        return sp.default

    def reset_all(self) -> None:
        self.history = History([defaults()], [], 0)
        self.save()
