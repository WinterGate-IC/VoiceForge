"""Offscreen smoke tests for the native PySide6 front-end.

Qt is happy to build widgets without a display when QT_QPA_PLATFORM=offscreen,
which lets the test suite catch broken imports, bad signal wiring and the
"sliders were ignored when saving a voice" class of bug.

Everything runs against a throwaway project folder, so no real voice or
setting is touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import desktop  # noqa: E402
import launcher  # noqa: E402
from voiceforge import library, qt_theme, seed  # noqa: E402


class TestNativeWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls._original_root = desktop.DATA
        desktop.DATA = cls.root  # every helper reads the module global at call time
        cls._original_paths = {
            name: getattr(desktop, name)
            for name in ("CACHE", "VOICE_CACHE", "PREVIEW_DIR", "LOG")
        }
        desktop.CACHE = cls.root / ".cache"
        desktop.VOICE_CACHE = desktop.CACHE / "edge_voices.json"
        desktop.PREVIEW_DIR = desktop.CACHE / "preview"
        desktop.LOG = desktop.CACHE / "desktop-errors.log"

        cls.app = QApplication.instance() or QApplication([])
        qt_theme.apply(cls.app)

    @classmethod
    def tearDownClass(cls) -> None:
        desktop.DATA = cls._original_root
        for name, value in cls._original_paths.items():
            setattr(desktop, name, value)
        cls.tmp.cleanup()

    def setUp(self) -> None:
        # Settings are shared by the temp project; start each test from defaults.
        project = desktop.Project.load(self.root)
        project.reset_all()
        project.save()
        self.window = desktop.MainWindow()
        # A modal dialog would hang a headless run; say "yes" instead.
        self._patches = [
            mock.patch.object(desktop.QMessageBox, "warning"),
            mock.patch.object(desktop.QMessageBox, "information"),
            mock.patch.object(desktop.QMessageBox, "question",
                              return_value=desktop.QMessageBox.StandardButton.Yes),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        self.window.close()
        self.window.deleteLater()

    # -- construction -----------------------------------------------------
    def test_builds_every_tab(self) -> None:
        self.assertEqual(self.window.tabs.count(), 4)
        self.assertEqual(self.window.tabs.tabText(0), "1 · Script")
        self.assertEqual(self.window.tabs.tabText(1), "2 · Speak")
        self.assertEqual(self.window.tabs.tabText(3), "History & Undo")
        self.assertTrue(self.window.script.placeholderText())

    def test_script_and_speak_are_separate_tabs(self) -> None:
        self.assertIs(self.window.tabs.widget(0), self.window.editor_page)
        self.assertIs(self.window.tabs.widget(1), self.window.speak_page)
        self.assertIs(self.window.script.parent(), self.window.editor_page)
        self.assertFalse(self.window.speak_page.isAncestorOf(self.window.script))
        self.assertIsNotNone(self.window.preview_btn)
        self.assertIsNotNone(self.window.format_combo)

    def test_preview_button_is_visible_before_generating(self) -> None:
        self.assertTrue(self.window.preview_btn.isEnabled())
        self.assertIn("preview", self.window.preview_btn.text().lower())

    def test_advanced_voice_lab_is_available(self) -> None:
        self.assertTrue(self.window.advanced_btn.isEnabled())
        self.assertIn("lab", self.window.advanced_btn.text().lower())
        self.assertIn("off", self.window.advanced_summary.text().lower())
        self.window._set_advanced({"bass": 7, "echo_mix": 0.25})
        self.assertIn("Bass", self.window.advanced_summary.text())
        self.assertIn("Echo", self.window.advanced_summary.text())

    def test_edge_voice_is_a_type_box_not_a_dropdown(self) -> None:
        from PySide6.QtWidgets import QComboBox, QLineEdit

        self.assertIsInstance(self.window.edge_edit, QLineEdit)
        self.assertNotIsInstance(self.window.edge_edit, QComboBox)
        self.assertEqual(self.window.edge_edit.text(),
                         "en-US-AndrewMultilingualNeural")
        self.window.edge_edit.setText("en-GB-RyanNeural")
        self.assertEqual(self.window.collect_values()["voice"],
                         "en-GB-RyanNeural")

    def test_voice_quick_picks_offer_male_female_ava_and_more(self) -> None:
        for name in ("voice_male_btn", "voice_female_btn", "voice_andrew_btn",
                     "voice_ava_btn", "voice_more_btn"):
            self.assertTrue(hasattr(self.window, name), name)
            self.assertTrue(getattr(self.window, name).isEnabled(), name)
        self.window.voice_andrew_btn.click()
        self.assertEqual(self.window.edge_edit.text(),
                         "en-US-AndrewMultilingualNeural")
        self.assertIn("Andrew", self.window.voice_hint.text())
        self.assertIn("Male", self.window.voice_hint.text())
        self.window.voice_ava_btn.click()
        self.assertEqual(self.window.edge_edit.text(),
                         "en-US-AvaMultilingualNeural")
        self.assertIn("Ava", self.window.voice_hint.text())
        self.assertIn("Female", self.window.voice_hint.text())
        self.assertEqual(self.window.collect_values()["voice"],
                         "en-US-AvaMultilingualNeural")

    def test_render_progress_bar_reports_parts_and_estimates(self) -> None:
        self.window._start_progress("Rendering 2 parts")
        self.assertIn("Estimating", self.window.progress_eta.text())
        self.window._on_render_progress({
            "phase": "part_done", "index": 1, "parts": 2,
            "part_chars": 100, "chars_done": 100,
            "total_chars": 200, "seconds": 2.0})
        self.assertGreater(self.window.progress_bar.value(), 0)
        self.assertIn("remaining", self.window.progress_eta.text())
        self.assertIn("Part 1 of 2", self.window.progress_detail.text())
        self.window._finish_progress("One finished file.")
        self.assertEqual(self.window.progress_bar.value(), 1000)
        self.assertEqual(self.window.progress_bar.format(), "100%")
        self.assertIn("Finished", self.window.progress_eta.text())

    def test_render_progress_bar_reports_failure(self) -> None:
        self.window._start_progress("Rendering")
        self.window._fail_progress("The voice was not available.")
        self.assertEqual(self.window.progress_bar.format(), "Stopped")
        self.assertIn("Stopped", self.window.progress_eta.text())
        self.assertIn("not available", self.window.progress_detail.text())

    def test_progress_reports_parallel_stats_and_adapt_notices(self) -> None:
        self.window._start_progress("Rendering 4 parts")
        self.window._on_render_progress({
            "phase": "part_done", "index": 2, "parts": 4,
            "parts_done": 2, "active": 2, "workers": 3,
            "part_chars": 110, "chars_done": 220, "total_chars": 440,
            "seconds": 1.0, "chars_per_second": 100.0})
        stats = self.window.progress_stats.text()
        self.assertIn("2 of 4 parts done", stats)
        self.assertIn("2 rendering now", stats)
        self.assertIn("3 at a time", stats)
        self.assertIn("100 chars/s", stats)

        self.window._on_render_progress({
            "phase": "adapt",
            "message": "CPU is at 95% - slowing down to 1 part at a time."})
        self.assertFalse(self.window.progress_adapt.isHidden())
        self.assertIn("CPU", self.window.progress_adapt.text())

    def test_finished_render_shows_a_result_card(self) -> None:
        import numpy as np
        import soundfile as sf

        target = self.root / "downloads" / "story.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), np.zeros(16000, dtype=np.float32), 8000)

        self.window._start_progress("Rendering")
        self.window._show_result(target, {
            "format": "WAV", "duration": 2.0,
            "bytes": target.stat().st_size,
            "sample_rate": 8000, "channels": 1})

        self.assertFalse(self.window.result_box.isHidden())
        self.assertTrue(self.window.progress_box.isHidden())
        self.assertEqual(self.window.result_name.text(), "story.wav")
        self.assertIn(str(target.parent), self.window.result_dir.text())
        meta = self.window.result_meta.text()
        self.assertIn("WAV", meta)
        self.assertIn("0:02", meta)
        self.assertIn("mono", meta)
        self.assertIn("8 kHz", meta)
        self.assertTrue(self.window.result_open_btn.isEnabled())
        self.assertTrue(self.window.result_folder_btn.isEnabled())
        self.assertEqual(self.window._result_path, target)

    def test_help_about_and_back_actions_are_wired(self) -> None:
        titles = [action.text() for action in
                  self.window.findChildren(desktop.QAction)]
        self.assertIn("Help & guides…", titles)
        self.assertIn("About VoiceForge…", titles)
        self.assertIn("Back to Launcher…", titles)

        with mock.patch.object(desktop.help_dialogs, "show_help") as show:
            self.window._open_help()
        show.assert_called_once()

        with mock.patch.object(desktop.help_dialogs, "show_about",
                               return_value=False) as about:
            self.window._open_about()
        about.assert_called_once()

    def test_back_to_launcher_confirms_unsaved_script(self) -> None:
        self.window.script.setPlainText("words that were never saved")
        self.assertTrue(self.window._back_to_launcher())

    def test_menu_back_respects_a_cancelled_confirmation(self) -> None:
        with mock.patch.object(self.window, "_back_to_launcher",
                               return_value=False) as confirm, \
                mock.patch.object(self.window, "_leave_for_launcher") as leave:
            self.window._menu_back_to_launcher()
        confirm.assert_called_once()
        leave.assert_not_called()

        with mock.patch.object(self.window, "_back_to_launcher",
                               return_value=True), \
                mock.patch.object(self.window, "_leave_for_launcher") as leave:
            self.window._menu_back_to_launcher()
        leave.assert_called_once()

    def test_settings_has_a_performance_tab(self) -> None:
        from voiceforge import settings_dialog

        dialog = settings_dialog.SettingsDialog(self.root)
        try:
            names = [dialog.tabs.tabText(i)
                     for i in range(dialog.tabs.count())]
            self.assertIn("Performance", names)
            self.assertTrue(dialog.adaptive.isChecked())
            self.assertEqual(dialog.render_workers.value(), 0)
            self.assertTrue(dialog.perf_status.text())
        finally:
            dialog.deleteLater()


    def test_male_and_female_buttons_open_a_filtered_picker(self) -> None:
        with mock.patch.object(desktop, "VoicePickerDialog") as picker:
            picker.return_value.exec.return_value = \
                desktop.QDialog.DialogCode.Rejected
            self.window.voice_male_btn.click()
            self.assertEqual(picker.call_args.kwargs["mode"],
                             desktop.voice_choices.MALE)

            self.window.voice_female_btn.click()
            self.assertEqual(picker.call_args.kwargs["mode"],
                             desktop.voice_choices.FEMALE)

    def test_voice_picker_filters_to_the_requested_gender(self) -> None:
        dialog = desktop.VoicePickerDialog(
            "", list(desktop.FALLBACK_VOICES), self.window,
            mode=desktop.voice_choices.FEMALE)
        self.assertGreater(dialog.voices.count(), 0)
        for row in range(dialog.voices.count()):
            self.assertIn("Female", dialog.voices.item(row).text())
        dialog.deleteLater()

    def test_theme_is_dark(self) -> None:
        colour = self.window.palette().color(QPalette.ColorRole.Window)
        self.assertLess(colour.lightness(), 80,
                        f"window background is {colour.name()}, not dark")

    def test_default_voices_are_seeded(self) -> None:
        rows = library.listing(self.root)
        builtins = [row for row in rows if row["builtin"]]
        self.assertGreaterEqual(len(builtins), 5, "expected built-in defaults")
        self.assertTrue(all(row["kind"] in ("default", "cloned")
                            for row in builtins))

    # -- long text --------------------------------------------------------
    def test_long_script_reports_multiple_parts(self) -> None:
        self.window.script.setPlainText("word " * 4000)
        text = self.window.plan_label.text()
        self.assertIn("part", text.lower())
        self.assertIn("part", self.window.script_summary.text().lower())

    # -- quick preview ----------------------------------------------------
    def test_preview_excerpt_is_short_and_sentence_aware(self) -> None:
        sentence = "This is one sentence. "
        excerpt = desktop.preview_excerpt(sentence * 60)
        self.assertLessEqual(len(excerpt), 321)
        self.assertTrue(excerpt.endswith("."), excerpt[-20:])
        self.assertNotIn("  ", excerpt)

    def test_preview_excerpt_leaves_short_text_alone(self) -> None:
        self.assertEqual(desktop.preview_excerpt("A short line."), "A short line.")
        self.assertEqual(desktop.preview_excerpt(""), "")

    # -- saved text -------------------------------------------------------
    def test_save_text_names_the_file_and_remembers_it(self) -> None:
        body = "First line of the read.\nSecond line."
        self.window.script.setPlainText(body)
        with mock.patch.object(desktop.QInputDialog, "getText",
                               return_value=("my-script", True)):
            self.window._save_script()
        target = self.window.prefs.text_dir / "my-script.txt"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), body)
        self.assertEqual(self.window.prefs["last_text_file"], str(target))
        self.assertEqual(self.window._current_text_path, target)

    def test_blank_save_name_reuses_the_open_file(self) -> None:
        self.window.script.setPlainText("first draft")
        with mock.patch.object(desktop.QInputDialog, "getText",
                               return_value=("chapter-one", True)):
            self.window._save_script()
        self.window.script.setPlainText("second draft")
        with mock.patch.object(desktop.QInputDialog, "getText",
                               return_value=("", True)):
            self.window._save_script()
        target = self.window.prefs.text_dir / "chapter-one.txt"
        self.assertEqual(target.read_text(encoding="utf-8"), "second draft")

    def test_last_saved_text_is_reopened(self) -> None:
        body = "Remember me between launches."
        self.window.script.setPlainText(body)
        with mock.patch.object(desktop.QInputDialog, "getText",
                               return_value=("remembered", True)):
            self.window._save_script()
        self.window.script.clear()
        self.window._restore_last_text()
        self.assertEqual(self.window.script.toPlainText(), body)

    def test_clear_forgets_the_open_file_but_keeps_it(self) -> None:
        self.window.script.setPlainText("keep this file")
        with mock.patch.object(desktop.QInputDialog, "getText",
                               return_value=("keep-me", True)):
            self.window._save_script()
        target = self.window.prefs.text_dir / "keep-me.txt"
        self.window.script_clear()
        self.assertEqual(self.window.script.toPlainText(), "")
        self.assertTrue(target.exists())
        self.assertEqual(self.window.prefs["last_text_file"], "")

    def test_legacy_autosaved_script_is_discarded(self) -> None:
        desktop.CACHE.mkdir(parents=True, exist_ok=True)
        legacy = desktop.CACHE / "last-script.txt"
        legacy.write_text("word " * 4000, encoding="utf-8")
        self.window._discard_legacy_script()
        self.assertFalse(legacy.exists())

    # -- the settings-capture bug ----------------------------------------
    def test_create_voice_saves_live_sliders_not_last_render(self) -> None:
        self.window.s_rate.set_value(17)
        self.window.s_pitch.set_value(-9)
        self.window.s_volume.set_value(6)
        self.window.s_temp.set_value(0.55)
        self.window.s_topk.set_value(80)
        self.window.effect_combo.setCurrentText("room")
        self.window.edge_edit.setText("en-GB-SoniaNeural")
        self.window._set_advanced({"bass": 8, "punch": 45, "reverb": 0.2})
        self.window.vname.setText("ui-test-voice")
        self.window.vnotes.setText("created by the offscreen test")

        self.window._create_voice()

        prof = library.load(self.root, "ui-test-voice")
        self.assertEqual(prof.settings["rate"], "+17%")
        self.assertEqual(prof.settings["pitch"], "-9Hz")
        self.assertEqual(prof.settings["volume"], "+6%")
        self.assertEqual(prof.settings["effect"], "room")
        self.assertEqual(prof.settings["bass"], 8)
        self.assertEqual(prof.settings["punch"], 45)
        self.assertAlmostEqual(float(prof.settings["reverb"]), 0.2)
        self.assertEqual(prof.settings["temperature"], 0.55)
        self.assertEqual(prof.settings["top_k"], 80)
        self.assertEqual(prof.settings["voice"], "en-GB-SoniaNeural")
        self.assertEqual(prof.notes, "created by the offscreen test")

    def test_update_voice_uses_current_sliders(self) -> None:
        self.window.s_rate.set_value(3)
        self.window.vname.setText("ui-update-voice")
        self.window._create_voice()

        self.window.s_rate.set_value(-12)
        self.window._refresh_library()
        # Select the row in the table so _selected_voice finds it.
        for row in range(self.window.lib_table.rowCount()):
            if self.window.lib_table.item(row, 0).text() == "ui-update-voice":
                self.window.lib_table.selectRow(row)
                break
        self.window._update_voice()

        prof = library.load(self.root, "ui-update-voice")
        self.assertEqual(prof.settings["rate"], "-12%")

    def test_delete_voice(self) -> None:
        self.window.vname.setText("ui-delete-voice")
        self.window._create_voice()
        for row in range(self.window.lib_table.rowCount()):
            if self.window.lib_table.item(row, 0).text() == "ui-delete-voice":
                self.window.lib_table.selectRow(row)
                break
        with mock.patch.object(desktop.QMessageBox, "question",
                               return_value=desktop.QMessageBox.StandardButton.Yes):
            self.window._delete_voice()
        self.assertFalse(library.folder(self.root, "ui-delete-voice").exists())

    # -- undo -------------------------------------------------------------
    def test_undo_restores_the_previous_setting(self) -> None:
        project = self.window._project()
        project.set_many(["rate=+30%"], label="test rate")
        project.save()
        self.window._undo(1)
        project = self.window._project()
        self.assertNotEqual(project.settings["rate"], "+30%")

    def test_undo_all_returns_to_defaults(self) -> None:
        project = self.window._project()
        project.set_many(["pitch=+25Hz"], label="test pitch")
        project.save()
        self.window._undo_all()
        project = self.window._project()
        self.assertEqual(project.settings["pitch"], "+0Hz")

    # -- misc wiring ------------------------------------------------------
    def test_style_preset_updates_sliders(self) -> None:
        self.window.style_combo.setCurrentText("hacker")
        self.assertEqual(self.window.effect_combo.currentText(), "telephone")
        self.assertEqual(self.window._advanced_values()["crush"], 4)

    def test_style_preset_replaces_an_old_lab_experiment(self) -> None:
        self.window._set_advanced({"ring": 0.6, "echo_mix": 0.5})
        self.window.style_combo.setCurrentText("narrator")
        lab = self.window._advanced_values()
        self.assertEqual(lab["ring"], 0.0)
        self.assertEqual(lab["echo_mix"], 0.0)
        self.assertEqual(lab["bass"], 3)


class TestLauncherWiring(unittest.TestCase):
    def test_every_frontend_script_exists_in_the_real_project(self) -> None:
        for front in launcher.FRONTENDS:
            self.assertTrue((ROOT / front.script).exists(),
                            f"{front.title} points at missing {front.script}")

    def test_root_detection_finds_the_project(self) -> None:
        found = launcher.find_root()
        self.assertIsNotNone(found)
        self.assertEqual(found, ROOT)

    def test_clean_env_strips_proxies(self) -> None:
        with mock.patch.dict(os.environ, {"ALL_PROXY": "socks5://x:1"}):
            child = launcher.clean_env(ROOT)
        self.assertNotIn("ALL_PROXY", child)
        self.assertEqual(child["VOICEFORGE_HOME"], str(ROOT))


if __name__ == "__main__":
    unittest.main()
