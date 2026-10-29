"""The curated voice list behind the Speak tab's quick picks.

These tests stay Qt-free on purpose: the same catalogue is used by the native
window, the other front-ends and (soon) the CLI, so it should be correct even
when no GUI is installed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import voice_choices  # noqa: E402


class TestCuratedVoices(unittest.TestCase):
    def test_default_and_featured_voices_are_present(self) -> None:
        self.assertEqual(
            voice_choices.BY_SHORT["en-US-AndrewMultilingualNeural"].gender,
            voice_choices.MALE)
        self.assertEqual(
            voice_choices.BY_SHORT["en-US-AvaMultilingualNeural"].gender,
            voice_choices.FEMALE)
        featured = {choice.short for choice in voice_choices.FEATURED}
        self.assertIn("en-US-AndrewMultilingualNeural", featured)
        self.assertIn("en-US-AvaMultilingualNeural", featured)

    def test_male_and_female_filters_return_options(self) -> None:
        men = voice_choices.curated(voice_choices.MALE)
        women = voice_choices.curated(voice_choices.FEMALE)
        self.assertGreaterEqual(len(men), 4)
        self.assertGreaterEqual(len(women), 4)
        self.assertTrue(all(item.gender == voice_choices.MALE for item in men))
        self.assertTrue(all(item.gender == voice_choices.FEMALE
                            for item in women))
        self.assertNotEqual({item.short for item in men},
                            {item.short for item in women})

    def test_other_voices_exist_for_characters(self) -> None:
        others = voice_choices.curated(voice_choices.OTHER)
        self.assertTrue(others)
        self.assertTrue(all(item.gender == voice_choices.OTHER
                            for item in others))

    def test_parse_short_handles_multilingual_names(self) -> None:
        self.assertEqual(
            voice_choices.parse_short("en-US-AndrewMultilingualNeural"),
            ("Andrew", "en-US"))
        self.assertEqual(voice_choices.parse_short("en-GB-SoniaNeural"),
                         ("Sonia", "en-GB"))

    def test_gender_inference_for_uncurated_catalogue_voices(self) -> None:
        self.assertEqual(voice_choices.gender_for("en-US-JasonNeural"),
                         voice_choices.MALE)
        self.assertEqual(voice_choices.gender_for("fr-FR-HenriNeural"),
                         voice_choices.OTHER)
        self.assertEqual(voice_choices.gender_for("en-US-AriaNeural"),
                         voice_choices.FEMALE)

    def test_merge_keeps_curated_order_and_adds_extras(self) -> None:
        fetched = ["en-US-AndrewMultilingualNeural", "xx-XX-MysteryNeural",
                   "en-US-AvaMultilingualNeural"]
        merged = voice_choices.merge_choices(fetched)
        shorts = [item.short for item in merged]
        self.assertEqual(shorts[:2],
                         [choice.short for choice in voice_choices.CURATED[:2]])
        self.assertIn("xx-XX-MysteryNeural", shorts)
        self.assertEqual(len(shorts), len(set(shorts)))
        mystery = merged[shorts.index("xx-XX-MysteryNeural")]
        self.assertEqual(mystery.gender, voice_choices.OTHER)

    def test_all_names_includes_the_curated_list(self) -> None:
        names = voice_choices.all_names(["en-US-AriaNeural"])
        self.assertIn("en-US-AriaNeural", names)
        self.assertIn("en-US-AvaMultilingualNeural", names)
        self.assertEqual(len(names), len(set(names)))

    def test_labels_read_like_choices(self) -> None:
        ava = voice_choices.BY_SHORT["en-US-AvaMultilingualNeural"]
        self.assertIn("Ava", ava.label)
        self.assertIn("Female", ava.label)
        self.assertIn("en-US", ava.label)
        self.assertIn("featured", ava.detailed_label)


if __name__ == "__main__":
    unittest.main()
