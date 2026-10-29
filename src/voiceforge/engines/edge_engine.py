"""Edge backend: Microsoft's neural voices.

Free, no API key, no model downloads, MP3 output, and it honours rate/pitch/
volume. This is the fast-draft engine: near-instant regardless of your CPU.
Requires a network connection.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from .base import Engine, EngineError


class EdgeEngine(Engine):
    name = "edge"
    extension = ".mp3"
    # Each part is an independent HTTPS request; a small thread pool shortens
    # long renders without touching the local CPU.
    parallel_safe = True

    def available(self, reference: str = "") -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "edge-tts not installed. Run: pip install edge-tts"
        return True, "Microsoft neural voices over HTTPS (no API key)"

    async def _speak(self, text: str, settings: dict[str, Any], out: Path) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=settings["voice"],
            rate=settings.get("rate", "+0%"),
            volume=settings.get("volume", "+0%"),
            pitch=settings.get("pitch", "+0Hz"),
        )
        await communicate.save(str(out))

    def render(self, text: str, settings: dict[str, Any], out_path: Path) -> Path:
        ok, reason = self.available()
        if not ok:
            raise EngineError(reason)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        voice = str(settings.get("voice", "") or "the selected voice")
        last: Exception | None = None
        no_audio = False
        for attempt in range(3):
            try:
                asyncio.run(self._speak(text, settings, out_path))
                last = None
                break
            except Exception as exc:  # network, bad voice name, etc.
                last = exc
                no_audio = _is_no_audio(exc)
                # Never leave a partial MP3 behind for the caller to trust.
                try:
                    out_path.unlink()
                except OSError:
                    pass
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
                    continue
        if last is not None:
            if no_audio:
                raise EngineError(
                    f"Edge returned no audio for “{voice}”, even after "
                    "retrying.\n\nThis usually means that voice is no longer "
                    "in Microsoft's catalogue, or Edge's speech service is "
                    "temporarily refusing requests.\n\nTry the Male… or "
                    "Female… quick picks, or Andrew and Ava, then press "
                    "Refresh voice list and choose again. Make sure a VPN or "
                    "proxy is not blocking speech.platform.bing.com, then "
                    "try once more.") from last
            if _is_connection(last):
                raise EngineError(
                    "Edge could not be reached. Check your internet "
                    "connection, VPN or proxy, then try again - nothing was "
                    f"written. ({last})") from last
            raise EngineError(
                f"Edge could not finish the render: {last}. Nothing was "
                "written; check the voice name and your connection, then "
                "try again.") from last
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise EngineError(
                f"Edge produced no audio for “{voice}”. Pick a voice from the "
                "quick list or refresh the catalogue, then try again.")
        return out_path


def _is_no_audio(exc: Exception) -> bool:
    """Recognise every spelling of Edge's 'no audio' failure.

    The class is checked first: edge-tts has changed the human-readable text
    between releases, and some versions send an empty message. Matching only
    the sentence is what let a raw ``NoAudioReceived`` reach the user as a
    generic 'edge render failed' in older builds.
    """
    name = type(exc).__name__.casefold()
    text = str(exc).casefold()
    return ("noaudioreceived" in name or "no_audio" in name
            or "no audio" in text or "invalid voice" in text)


def _is_connection(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(marker in text for marker in (
        "handshake", "timed out", "timeout", "connection", "connect",
        "ssl", "proxy", "dns", "certificate", "403", "401", "429",
        "websocket", "unreachable", "network"))


async def _list() -> list[dict[str, Any]]:
    import edge_tts

    return await edge_tts.list_voices()


def list_voices() -> list[dict[str, Any]]:
    """All available Edge voices as flat dicts."""
    rows = asyncio.run(_list())
    return [
        {
            "short": v.get("ShortName", ""),
            "gender": v.get("Gender", ""),
            "locale": v.get("Locale", ""),
            "name": v.get("FriendlyName", ""),
        }
        for v in rows
    ]
