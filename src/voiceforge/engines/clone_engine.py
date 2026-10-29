"""Clone backend: XTTS v2 zero-shot voice cloning from a short sample.

Optional. Needs `pip install coqui-tts` (a ~2.5 GB torch stack) and it is
CPU-bound on machines without an NVIDIA GPU: expect roughly 0.3-0.5x realtime
on a 4-core Ryzen. Fine for final takes, painful for drafts.

XTTS-v2's weights are licenced CPML (non-commercial), so keep commercial work
on the edge engine or a different checkpoint.

Only put voices here that you own or have written permission to imitate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Engine, EngineError

AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".ogg")
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


class CloneEngine(Engine):
    name = "clone"
    extension = ".wav"

    def reference_path(self, name: str) -> Path | None:
        if not name:
            return None
        folder = self.root / "voices" / name
        if not folder.is_dir():
            return None
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in AUDIO_SUFFIXES:
                return f
        return None

    def available(self, reference: str = "") -> tuple[bool, str]:
        try:
            import TTS  # noqa: F401
        except ImportError:
            return False, ("coqui-tts not installed. Run: pip install coqui-tts "
                           "(~2.5 GB, and slow on CPU)")
        if not reference:
            return False, "no reference voice set. Run: vf voice add <name> <sample.mp3>"
        ref = self.reference_path(reference)
        if ref is None:
            return False, f"no audio found in voices/{reference}/ (need a wav/mp3 sample)"
        return True, f"XTTS v2 on CPU, reference clip: {ref.name}"

    def render(self, text: str, settings: dict[str, Any], out_path: Path) -> Path:
        reference = str(settings.get("reference", "")).strip()
        ok, reason = self.available(reference)
        if not ok:
            raise EngineError(reason)

        ref = self.reference_path(reference)
        assert ref is not None

        import torch
        from TTS.api import TTS

        out_path.parent.mkdir(parents=True, exist_ok=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            api = TTS(MODEL).to(device)
            api.tts_to_file(
                text=text,
                speaker_wav=str(ref),
                language=settings.get("language", "en"),
                file_path=str(out_path),
                speed=float(settings.get("speed", 1.0)),
                temperature=float(settings.get("temperature", 0.75)),
                top_k=int(settings.get("top_k", 50)),
                top_p=float(settings.get("top_p", 0.85)),
                repetition_penalty=float(settings.get("repetition_penalty", 5.0)),
                split_sentences=True,
            )
        except Exception as exc:
            raise EngineError(f"clone render failed: {exc}") from exc

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise EngineError("clone produced no audio")
        return out_path
