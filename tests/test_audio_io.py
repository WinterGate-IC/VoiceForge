"""Crash-safe audio writes: validate, atomic rename, cross-format fallback."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from voiceforge import audio_io  # noqa: E402


def tone(seconds: float = 0.25, rate: int = 8000) -> np.ndarray:
    t = np.arange(max(1, int(rate * seconds)), dtype=np.float32) / rate
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)


class TestAudioIO(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_written_file_is_valid_and_has_no_temp_siblings(self) -> None:
        target = self.root / "clip.wav"
        written = audio_io.write_audio(tone(), 8000, target)

        self.assertEqual(written, target)
        info = audio_io.validate_audio(written)
        self.assertGreater(info["frames"], 0)
        self.assertEqual(info["sample_rate"], 8000)
        self.assertEqual(info["channels"], 1)
        self.assertGreater(info["duration"], 0.1)
        leftovers = [p.name for p in self.root.iterdir() if ".vf-" in p.name]
        self.assertEqual(leftovers, [], "hidden temp files must be renamed")

    def test_writing_over_an_existing_file_replaces_it_whole(self) -> None:
        target = self.root / "clip.wav"
        audio_io.write_audio(tone(0.5), 8000, target)
        before = audio_io.validate_audio(target)["frames"]

        audio_io.write_audio(tone(0.1), 8000, target)
        after = audio_io.validate_audio(target)["frames"]
        self.assertNotEqual(before, after)
        self.assertLess(after, before)

    def test_unknown_suffix_falls_back_to_wav(self) -> None:
        written = audio_io.write_audio(tone(), 8000, self.root / "clip.xyz")
        self.assertEqual(written.suffix, ".wav")
        self.assertTrue(written.exists())

    def test_missing_and_empty_files_are_rejected(self) -> None:
        with self.assertRaises(audio_io.AudioValidationError):
            audio_io.validate_audio(self.root / "missing.wav")

        empty = self.root / "empty.wav"
        empty.write_bytes(b"")
        with self.assertRaises(audio_io.AudioValidationError):
            audio_io.validate_audio(empty)

    def test_garbage_is_rejected_not_trusted(self) -> None:
        junk = self.root / "junk.mp3"
        junk.write_bytes(b"\x00" * 200)
        with self.assertRaises(audio_io.AudioValidationError):
            audio_io.validate_audio(junk)

    def test_copy_into_place_moves_and_removes_the_source(self) -> None:
        source = self.root / "engine-take.wav"
        audio_io.write_audio(tone(), 8000, source)
        target = self.root / "downloads" / "final.wav"

        written = audio_io.copy_into_place(source, target)
        self.assertEqual(written, target)
        self.assertTrue(target.exists())
        self.assertFalse(source.exists())
        self.assertGreater(audio_io.validate_audio(target)["frames"], 0)

    def test_copy_into_place_refuses_invalid_source(self) -> None:
        source = self.root / "broken.wav"
        source.write_bytes(b"not audio at all" * 8)
        target = self.root / "final.wav"
        with self.assertRaises(audio_io.AudioValidationError):
            audio_io.copy_into_place(source, target)
        self.assertFalse(target.exists())

    def test_free_space_is_reported(self) -> None:
        self.assertGreater(audio_io.free_space_mb(self.root), 0)


if __name__ == "__main__":
    unittest.main()
