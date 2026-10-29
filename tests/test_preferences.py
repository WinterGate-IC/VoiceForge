"""Preferences validate and persist the performance options safely."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import preferences  # noqa: E402


class TestPerformancePreferences(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_defaults_are_adaptive_and_automatic(self) -> None:
        prefs = preferences.Preferences(self.root)
        self.assertTrue(prefs["adaptive_performance"])
        self.assertEqual(prefs["render_workers"], 0)

    def test_values_survive_a_save_and_load(self) -> None:
        prefs = preferences.Preferences(self.root)
        prefs.set("adaptive_performance", False)
        prefs.set("render_workers", 5)
        prefs.save()

        loaded = preferences.Preferences.load(self.root)
        self.assertFalse(loaded["adaptive_performance"])
        self.assertEqual(loaded["render_workers"], 5)

    def test_worker_count_is_limited_to_the_supported_range(self) -> None:
        prefs = preferences.Preferences(self.root)
        prefs.set("render_workers", 99)
        self.assertEqual(prefs["render_workers"], 8)
        prefs.set("render_workers", -3)
        self.assertEqual(prefs["render_workers"], 0)

    def test_broken_file_falls_back_to_defaults(self) -> None:
        (self.root / preferences.PREFERENCES_FILE).write_text(
            "{not json", encoding="utf-8")
        prefs = preferences.Preferences.load(self.root)
        self.assertTrue(prefs["adaptive_performance"])
        self.assertEqual(prefs["render_workers"], 0)
        self.assertEqual(prefs["output_format"], "mp3")

    def test_unknown_preference_is_rejected(self) -> None:
        prefs = preferences.Preferences(self.root)
        with self.assertRaises(KeyError):
            prefs.set("not_a_setting", 1)

    def test_no_temp_file_is_left_behind(self) -> None:
        prefs = preferences.Preferences(self.root)
        prefs.save()
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, [preferences.PREFERENCES_FILE])
        saved = json.loads((self.root / preferences.PREFERENCES_FILE)
                           .read_text(encoding="utf-8"))
        self.assertIn("adaptive_performance", saved)
        self.assertIn("render_workers", saved)


if __name__ == "__main__":
    unittest.main()
