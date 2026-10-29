"""Proxy/env hygiene, in one place.

This machine (and plenty of others) has ALL_PROXY pointing at a dead SOCKS
port. httpx, aiohttp and pip all trust it, so Gradio fails to import, voice
rendering fails to resolve, and pip cannot install anything. Nothing in the
app needs an outbound proxy, so the entry points drop those variables before
the first network import and hand a scrubbed copy to child processes.
"""

from __future__ import annotations

import os
from pathlib import Path

PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy")


def sanitize() -> None:
    """Remove dead proxy settings from this process, before network imports."""
    for key in PROXY_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def clean_env(root: Path | str | None = None,
              data: Path | str | None = None) -> dict[str, str]:
    """A scrubbed environment dict for a child process.

    `root` is the program folder (so children can find ``src/``); `data` is
    the user-data folder when it differs, which installed copies need.
    """
    env = os.environ.copy()
    for key in PROXY_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    if root is not None:
        base = Path(root)
        env["VOICEFORGE_HOME"] = str(base)
        env["PYTHONPATH"] = (str(base / "src") + os.pathsep
                             + env.get("PYTHONPATH", ""))
    if data is not None:
        env["VOICEFORGE_DATA"] = str(data)
    return env
