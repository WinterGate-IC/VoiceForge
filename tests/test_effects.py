"""DSP chain tests: shape, stability, boundedness, determinism."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge.effects import (  # noqa: E402
    CHAINS, apply_advanced_to_signal, apply_chain_to_signal, has_effects,
)

SR = 24000


def tone(seconds: float = 1.0, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestChains(unittest.TestCase):
    def test_all_chains_preserve_length_and_stay_finite(self):
        x = tone()
        for chain in CHAINS:
            with self.subTest(chain=chain):
                y = apply_chain_to_signal(x, SR, chain)
                self.assertEqual(len(y), len(x))
                self.assertTrue(np.all(np.isfinite(y)))
                self.assertLessEqual(float(np.max(np.abs(y))), 1.0)

    def test_effects_actually_change_the_signal(self):
        x = tone()
        for chain in ("hall", "telephone", "demon", "masked", "robot",
                      "cave", "underwater", "vintage", "alien"):
            with self.subTest(chain=chain):
                y = apply_chain_to_signal(x, SR, chain)
                self.assertGreater(float(np.mean(np.abs(y - x))), 1e-4)

    def test_none_is_identity(self):
        x = tone()
        np.testing.assert_array_equal(apply_chain_to_signal(x, SR, "none"), x)

    def test_unknown_chain_raises(self):
        with self.assertRaises(ValueError):
            apply_chain_to_signal(tone(), SR, "not-a-chain")

    def test_deterministic(self):
        x = tone()
        a = apply_chain_to_signal(x, SR, "masked")
        b = apply_chain_to_signal(x, SR, "masked")
        np.testing.assert_array_equal(a, b)

    def test_silence_stays_quiet(self):
        silence = np.zeros(SR, dtype=np.float32)
        for chain in ("room", "hall", "demon"):
            with self.subTest(chain=chain):
                y = apply_chain_to_signal(silence, SR, chain)
                self.assertLess(float(np.max(np.abs(y))), 1e-5)

    def test_stereo_chains_keep_shape_and_stay_bounded(self):
        mono = tone()
        stereo = np.stack([mono, mono * 0.5], axis=1)
        for chain in CHAINS:
            with self.subTest(chain=chain):
                y = apply_chain_to_signal(stereo, SR, chain)
                self.assertEqual(y.shape, stereo.shape)
                self.assertTrue(np.all(np.isfinite(y)))
                self.assertLessEqual(float(np.max(np.abs(y))), 1.0)

    def test_chains_land_in_a_consistent_loudness_range(self):
        # A band-limited chain should not leave the voice 15 dB quieter than
        # an unprocessed one. This is what made telephone-style effects feel
        # broken before the final stage normalised RMS.
        x = (tone(2.0, 220.0, 0.22) + tone(2.0, 880.0, 0.10)).astype(np.float32)
        for chain in CHAINS:
            if chain == "none":
                continue
            with self.subTest(chain=chain):
                y = apply_chain_to_signal(x, SR, chain)
                rms = float(np.sqrt(np.mean(np.square(y, dtype=np.float64))))
                self.assertGreater(rms, 0.075)
                self.assertLess(rms, 0.25)


class TestVoiceLab(unittest.TestCase):
    def test_neutral_lab_is_identity(self):
        x = tone()
        self.assertFalse(has_effects({}))
        np.testing.assert_array_equal(apply_advanced_to_signal(x, SR, {}), x)

    def test_every_lab_knob_changes_a_voice_like_signal(self):
        # A two-tone stereo mix exercises shelves, width, modulation and
        # crush better than a single sine. Each control must be audible alone.
        left = (tone(1.0, 220.0, 0.30) + tone(1.0, 900.0, 0.20)).astype(np.float32)
        right = (tone(1.0, 220.0, 0.30) + tone(1.0, 900.0, 0.10)).astype(np.float32)
        x = np.stack([left, right], axis=1)
        neutral = apply_advanced_to_signal(x, SR, {})
        cases = {
            "bass": 10, "treble": 8, "punch": 70, "width": 160,
            "echo_mix": 0.35, "reverb": 0.35, "chorus": 0.4, "drive": 0.5,
            "ring": 0.5, "tremolo": 0.5, "vibrato": 0.5, "flutter": 0.5,
            "crush": 5,
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                settings = {key: value}
                y = apply_advanced_to_signal(x, SR, settings)
                self.assertTrue(has_effects(settings))
                self.assertEqual(len(y), len(x))
                self.assertTrue(np.all(np.isfinite(y)))
                self.assertLessEqual(float(np.max(np.abs(y))), 1.0)
                self.assertGreater(float(np.mean(np.abs(y - neutral))), 1e-4)

    def test_stereo_width_keeps_mono_compatibility(self):
        mono = tone()
        stereo = np.stack([mono, mono * 0.5], axis=1)
        y = apply_advanced_to_signal(stereo, SR, {"width": 180})
        self.assertEqual(y.shape, stereo.shape)
        self.assertTrue(np.all(np.isfinite(y)))

    def test_modulation_knobs_accept_extremes(self):
        x = tone()
        settings = {
            "echo_ms": 1500, "echo_feedback": 0.95, "echo_mix": 1.0,
            "reverb": 1.0, "chorus": 1.0, "drive": 1.0, "ring": 1.0,
            "ring_rate": 2000.0, "tremolo": 1.0, "tremolo_rate": 14.0,
            "vibrato": 1.0, "vibrato_rate": 12.0, "flutter": 1.0,
            "crush": 12, "bass": 18, "treble": 16, "punch": 100,
            "width": 200,
        }
        y = apply_advanced_to_signal(np.stack([x, x], axis=1), SR, settings)
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertLessEqual(float(np.max(np.abs(y))), 1.0)

    def test_all_named_chains_are_listed(self):
        self.assertIn("cave", CHAINS)
        self.assertIn("cathedral", CHAINS)
        self.assertIn("robot", CHAINS)
        self.assertIn("cinema", CHAINS)
        self.assertIn("alien", CHAINS)


if __name__ == "__main__":
    unittest.main()
