"""Core behaviour tests: settings, history, project, presets, library."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import library, presets, styles  # noqa: E402
from voiceforge.history import History  # noqa: E402
from voiceforge.project import Project  # noqa: E402
from voiceforge.settings import ParamError, defaults, spec  # noqa: E402


class TestSettings(unittest.TestCase):
    def test_percent_normalisation(self):
        self.assertEqual(spec("rate").coerce("10%"), "+10%")
        self.assertEqual(spec("rate").coerce("-15%"), "-15%")
        self.assertEqual(spec("rate").coerce("  +5% "), "+5%")

    def test_percent_accepts_bare_numbers(self):
        self.assertEqual(spec("rate").coerce("10"), "+10%")

    def test_percent_rejects_junk(self):
        for bad in ("abc", "10%%", "+1e5", ""):
            with self.assertRaises(ParamError):
                spec("rate").coerce(bad)

    def test_hz(self):
        self.assertEqual(spec("pitch").coerce("-20Hz"), "-20Hz")
        self.assertEqual(spec("pitch").coerce("30"), "+30Hz")

    def test_float_range(self):
        self.assertAlmostEqual(spec("temperature").coerce("0.9"), 0.9)
        with self.assertRaises(ParamError):
            spec("temperature").coerce("2.0")

    def test_int_range(self):
        self.assertEqual(spec("top_k").coerce("80"), 80)
        with self.assertRaises(ParamError):
            spec("top_k").coerce("500")

    def test_unknown_param(self):
        with self.assertRaises(ParamError):
            spec("nonsense")


class TestHistory(unittest.TestCase):
    def test_undo_redo(self):
        h = History()
        state = h.current
        state["rate"] = "+10%"
        h.record("rate", "+0%", "+10%", "set rate", state)
        self.assertEqual(h.current["rate"], "+10%")
        h.undo()
        self.assertEqual(h.current["rate"], "+0%")
        h.redo()
        self.assertEqual(h.current["rate"], "+10%")

    def test_undo_beyond_start_raises(self):
        h = History()
        with self.assertRaises(ValueError):
            h.undo()

    def test_new_change_discards_redo_tail(self):
        h = History()
        s = h.current
        s["rate"] = "+10%"
        h.record("rate", "+0%", "+10%", "a", s)
        h.undo()
        s = h.current
        s["rate"] = "+25%"
        h.record("rate", "+0%", "+25%", "b", s)
        self.assertFalse(h.can_redo)
        self.assertEqual(h.current["rate"], "+25%")

    def test_undo_to_snapshot(self):
        h = History()
        for value in ("+10%", "+20%", "+30%"):
            s = h.current
            prev = s["rate"]
            s["rate"] = value
            h.record("rate", prev, value, f"set {value}", s)
        h.undo_to(1)
        self.assertEqual(h.current["rate"], "+10%")
        h.undo_to(0)
        self.assertEqual(h.current["rate"], defaults()["rate"])

    def test_undo_single_param_leaves_others(self):
        h = History()
        s = h.current
        s["rate"] = "+10%"
        h.record("rate", "+0%", "+10%", "rate", s)
        s = h.current
        s["pitch"] = "-20Hz"
        h.record("pitch", "+0Hz", "-20Hz", "pitch", s)

        h.undo_param("rate")
        self.assertEqual(h.current["rate"], "+0%")
        self.assertEqual(h.current["pitch"], "-20Hz")  # untouched

    def test_undo_param_never_set_falls_back_to_default(self):
        h = History()
        h.undo_param("volume")
        self.assertEqual(h.current["volume"], defaults()["volume"])

    def test_roundtrip_serialisation(self):
        h = History()
        s = h.current
        s["voice"] = "en-GB-RyanNeural"
        h.record("voice", "x", "en-GB-RyanNeural", "voice", s)
        clone = History.from_dict(h.to_dict())
        self.assertEqual(clone.current, h.current)
        self.assertEqual(clone.cursor, h.cursor)


class TestProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_many_and_persist(self):
        p = Project(self.root)
        p.set_many(["rate=+10%", "pitch=-20Hz"])
        self.assertEqual(p.settings["rate"], "+10%")

        reloaded = Project.load(self.root)
        self.assertEqual(reloaded.settings["rate"], "+10%")
        self.assertEqual(reloaded.settings["pitch"], "-20Hz")

    def test_set_many_is_atomic_on_bad_value(self):
        p = Project(self.root)
        with self.assertRaises(ParamError):
            p.set_many(["rate=+10%", "pitch=nonsense"])
        self.assertEqual(p.settings["rate"], defaults()["rate"])

    def test_apply_settings_is_one_undo_step(self):
        p = Project(self.root)
        p.apply_settings({"rate": "+10%", "pitch": "-20Hz",
                          "temperature": 0.9, "unknown": 1})
        self.assertEqual(p.history.length, 2)
        p.history.undo()
        self.assertEqual(p.settings["rate"], defaults()["rate"])
        self.assertEqual(p.settings["pitch"], defaults()["pitch"])

    def test_active_engine_follows_reference(self):
        p = Project(self.root)
        self.assertEqual(p.active_engine(), "edge")
        p.set_many(["reference=my-voice"])
        self.assertEqual(p.active_engine(), "clone")

    def test_reset_all(self):
        p = Project(self.root)
        p.set_many(["rate=+10%"])
        p.reset_all()
        self.assertEqual(p.settings, defaults())


class TestPresets(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            presets.save(root, "my preset", {"rate": "+5%"})
            self.assertEqual(presets.load(root, "my preset")["rate"], "+5%")
            self.assertEqual(len(presets.listing(root)), 1)
            self.assertTrue(presets.delete(root, "my preset"))
            self.assertEqual(presets.listing(root), [])

    def test_missing_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(presets.PresetError):
                presets.load(Path(tmp), "does-not-exist")


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lifecycle(self):
        prof = library.create(self.root, "My Voice", {"rate": "+10%"}, notes="n")
        self.assertEqual(prof.kind, "designed")
        self.assertEqual(len(library.listing(self.root)), 1)

        renamed = library.rename(self.root, "My Voice", "other")
        self.assertEqual(renamed.name, "other")
        self.assertTrue(library.delete(self.root, "other"))
        self.assertFalse(library.delete(self.root, "other"))

    def test_duplicate_create_requires_overwrite(self):
        library.create(self.root, "dup", {})
        with self.assertRaises(library.LibraryError):
            library.create(self.root, "dup", {})
        library.create(self.root, "dup", {}, overwrite=True)

    def test_attach_sample_makes_it_cloned(self):
        library.create(self.root, "v", {})
        dummy = self.root / "sample.wav"
        dummy.write_bytes(b"RIFF0000WAVE")
        library.attach_sample(self.root, "v", dummy)
        self.assertIsNotNone(library.audio_in(self.root, "v"))
        self.assertEqual(library.load(self.root, "v").kind, "cloned")

    def test_attach_rejects_bad_suffix(self):
        library.create(self.root, "v2", {})
        bad = self.root / "notes.txt"
        bad.write_text("hi")
        with self.assertRaises(library.LibraryError):
            library.attach_sample(self.root, "v2", bad)

    def test_attach_rejects_file_outside_the_upload_root(self):
        library.create(self.root, "v3", {})
        outside = self.root / "outside.wav"
        outside.write_bytes(b"RIFF0000WAVE")
        uploads = self.root / "uploads"
        uploads.mkdir()
        with self.assertRaises(library.LibraryError):
            library.attach_sample(self.root, "v3", outside, source_root=uploads)
        self.assertIsNone(library.audio_in(self.root, "v3"))

    def test_attach_accepts_file_inside_the_upload_root(self):
        library.create(self.root, "v4", {})
        uploads = self.root / "uploads"
        uploads.mkdir()
        inside = uploads / "recording.wav"
        inside.write_bytes(b"RIFF0000WAVE")
        library.attach_sample(self.root, "v4", inside, source_root=uploads)
        self.assertIsNotNone(library.audio_in(self.root, "v4"))


class TestStyles(unittest.TestCase):
    def test_every_style_is_valid(self):
        for st in styles.listing():
            for key, value in st.params.items():
                spec(key).coerce(value)
            spec("effect").coerce(st.effect)

    def test_pairs_include_effect(self):
        pairs = styles.as_pairs(styles.get("hacker"))
        self.assertIn("effect=telephone", pairs)

    def test_unknown_style(self):
        with self.assertRaises(styles.StyleError):
            styles.get("nope")


if __name__ == "__main__":
    unittest.main()
