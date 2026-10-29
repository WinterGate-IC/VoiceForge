"""Long-form splitting, audio stitching, and starter voices."""

from __future__ import annotations

import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import library, seed  # noqa: E402
from voiceforge.render import concatenate_audio  # noqa: E402
from voiceforge.textsplit import (  # noqa: E402
    DEFAULT_LIMIT, _hard_split, normalise, plan, split_for_speech,
)


class TestSplitter(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        text = "A short line, exactly as written."
        self.assertEqual(split_for_speech(text), [text])

    def test_empty_returns_nothing(self):
        self.assertEqual(split_for_speech(""), [])
        self.assertEqual(split_for_speech("   \n\n  "), [])

    def test_limit_respected_and_words_preserved(self):
        text = " ".join(f"Sentence number {i} has a few words." for i in range(200))
        chunks = split_for_speech(text, limit=300)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 300)
            self.assertTrue(chunk.strip())
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_paragraphs_pack_until_limit(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = split_for_speech(text, limit=1000)
        self.assertEqual(len(chunks), 1)
        self.assertIn("\n\n", chunks[0])

    def test_paragraphs_split_when_over_limit(self):
        text = "\n\n".join(["word " * 60, "more " * 60])
        chunks = split_for_speech(text, limit=300)
        self.assertEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 300)

    def test_single_giant_token_is_sliced(self):
        token = "x" * 900
        pieces = _hard_split(token, 200)
        self.assertEqual(len(pieces), 5)
        self.assertEqual("".join(pieces), token)

    def test_trailing_whitespace_is_trimmed_per_line(self):
        self.assertEqual(normalise("a  \t\nb\t\t\nc"), "a\nb\nc")
        self.assertEqual(normalise("  one \n\n two  "), "one\n\n two")

    def test_pathological_tabs_stay_linear(self):
        # A regex like r"[ \t]+\n" is quadratic here; the splitter must not
        # spend seconds on input a hostile page could send.
        text = "\t" * 200_000 + "end"
        started = time.perf_counter()
        self.assertEqual(normalise(text), "end")
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_plan_counts(self):
        info = plan("One two three. Four five.")
        self.assertEqual(info.words, 5)
        self.assertEqual(info.chunks, 1)
        self.assertEqual(info.limit, DEFAULT_LIMIT)
        self.assertIn("words", info.describe())


class TestConcatenation(unittest.TestCase):
    def test_two_parts_join_with_gap(self):
        import numpy as np
        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sr = 22050
            t = np.linspace(0, 0.25, int(sr * 0.25), endpoint=False)
            tone = (0.2 * np.sin(2 * math.pi * 220 * t)).astype("float32")
            first = root / "a.wav"
            second = root / "b.wav"
            sf.write(str(first), tone, sr)
            sf.write(str(second), tone, sr)

            target = root / "joined.mp3"
            out = concatenate_audio([first, second], target, gap_seconds=0.25)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

            data, rate = sf.read(str(out))
            self.assertEqual(rate, sr)
            expected = 0.25 + 0.25 + 0.25  # part, gap, part
            self.assertAlmostEqual(len(data) / rate, expected, delta=0.15)


class TestDefaultVoices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds_an_empty_library(self):
        created = seed.ensure_defaults(self.root)
        self.assertEqual(len(created), len(seed.DEFAULT_VOICES))
        rows = library.listing(self.root)
        self.assertEqual(len(rows), len(seed.DEFAULT_VOICES))
        self.assertTrue(all(row["builtin"] for row in rows))
        self.assertTrue(all(row["kind"] == "default" for row in rows))

    def test_second_call_is_a_no_op(self):
        seed.ensure_defaults(self.root)
        self.assertEqual(seed.ensure_defaults(self.root), [])
        self.assertEqual(len(library.listing(self.root)), len(seed.DEFAULT_VOICES))

    def test_does_not_seed_over_a_user_library(self):
        library.create(self.root, "mine", {"rate": "+5%"})
        self.assertEqual(seed.ensure_defaults(self.root), [])
        self.assertEqual([r["name"] for r in library.listing(self.root)], ["mine"])

    def test_restore_brings_back_a_deleted_default(self):
        seed.ensure_defaults(self.root)
        library.delete(self.root, "hacker")
        created = seed.restore(self.root)
        self.assertEqual(created, ["hacker"])
        self.assertTrue(library.load(self.root, "hacker").builtin)

    def test_restore_never_overwrites_an_edit(self):
        seed.ensure_defaults(self.root)
        library.update(self.root, "narrator", {"rate": "+25%"}, notes="mine now")
        seed.restore(self.root)
        prof = library.load(self.root, "narrator")
        self.assertEqual(prof.settings["rate"], "+25%")
        self.assertEqual(prof.notes, "mine now")

    def test_defaults_are_usable_settings(self):
        seed.ensure_defaults(self.root)
        prof = library.load(self.root, "scary-storyteller")
        self.assertIn(prof.settings["effect"], ("demon", "hall", "none"))
        self.assertTrue(prof.settings["voice"].endswith("Neural"))

    def test_defaults_are_actually_different_characters(self):
        seed.ensure_defaults(self.root)
        rows = library.listing(self.root)
        signatures = set()
        for row in rows:
            prof = library.load(self.root, row["name"])
            s = prof.settings
            signatures.add((
                s.get("voice"), s.get("effect"), s.get("rate"),
                s.get("pitch"), s.get("bass"), s.get("punch"),
                s.get("echo_mix"), s.get("ring"), s.get("crush"),
                s.get("flutter"), s.get("vibrato"),
            ))
        self.assertEqual(len(signatures), len(rows),
                         "each default voice should have a distinct character")

    def test_upgrade_adds_new_keys_without_overwriting_edits(self):
        seed.ensure_defaults(self.root)
        library.update(self.root, "narrator", {"rate": "+25%", "bass": 12},
                       notes="mine now")
        # Simulate a library seeded before the voice lab existed.
        prof = library.load(self.root, "narrator")
        old = dict(prof.settings)
        for key in ("treble", "punch", "width", "echo_ms",
                    "echo_feedback", "echo_mix", "reverb", "chorus",
                    "drive", "ring", "ring_rate", "tremolo",
                    "tremolo_rate", "vibrato", "vibrato_rate", "flutter",
                    "crush"):
            old.pop(key, None)
        library.update(self.root, "narrator", old, notes=prof.notes)

        seed.ensure_defaults(self.root)
        upgraded = library.load(self.root, "narrator")
        self.assertEqual(upgraded.settings["rate"], "+25%")
        self.assertEqual(upgraded.settings["bass"], 12)
        self.assertEqual(upgraded.settings["treble"], -2)
        self.assertIn("echo_ms", upgraded.settings)
        self.assertEqual(upgraded.notes, "mine now")


if __name__ == "__main__":
    unittest.main()
