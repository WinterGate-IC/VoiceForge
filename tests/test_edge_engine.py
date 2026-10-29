"""The edge engine's error messages and retry path, without the network."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge.engines.base import EngineError  # noqa: E402
from voiceforge.engines.edge_engine import EdgeEngine  # noqa: E402


class _NoAudio:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def save(self, path: str) -> None:
        raise RuntimeError(
            "No audio was received. Please verify that your parameters are "
            "correct.")


class _Transient:
    calls = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def save(self, path: str) -> None:
        import soundfile as sf

        type(self).calls += 1
        if type(self).calls == 1:
            raise OSError("connection reset")
        sf.write(path, [0.0] * 800, 8000)


class TestEdgeErrors(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = EdgeEngine(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_voice_is_explained_and_names_the_voice(self) -> None:
        with mock.patch("edge_tts.Communicate", _NoAudio):
            with self.assertRaises(EngineError) as caught:
                self.engine.render(
                    "Hello.", {"voice": "en-US-NotARealNeural"},
                    self.root / "out.mp3")
        message = str(caught.exception)
        self.assertIn("en-US-NotARealNeural", message)
        self.assertIn("Male", message)
        self.assertIn("Refresh voice list", message)

    def test_transient_network_failure_is_retried_once(self) -> None:
        _Transient.calls = 0
        with mock.patch("edge_tts.Communicate", _Transient):
            out = self.engine.render(
                "Hello.", {"voice": "en-US-AndrewMultilingualNeural"},
                self.root / "retry.mp3")
        self.assertEqual(_Transient.calls, 2)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
