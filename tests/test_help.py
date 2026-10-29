"""Help guides, About copy and the Back to Launcher hand-off."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from voiceforge import branding, help_content, help_dialogs  # noqa: E402


class TestHelpContent(unittest.TestCase):
    def test_guides_cover_the_questions_people_ask(self) -> None:
        keys = {guide.key for guide in help_content.GUIDES}
        for expected in ("start", "launcher", "voices", "script-speak",
                         "output", "speed", "effects", "troubleshooting",
                         "settings", "about"):
            self.assertIn(expected, keys)
        self.assertGreaterEqual(len(help_content.GUIDES), 8)

    def test_every_guide_has_a_title_summary_and_body(self) -> None:
        for guide in help_content.GUIDES:
            self.assertTrue(guide.title.strip(), guide.key)
            self.assertTrue(guide.summary.strip(), guide.key)
            self.assertGreater(len(guide.body.strip()), 80, guide.key)

    def test_search_finds_voices_and_audio_failures(self) -> None:
        voice_hits = help_content.find_guides("voice")
        self.assertIn("voices", {guide.key for guide in voice_hits})
        error_hits = help_content.find_guides("no audio")
        self.assertIn("troubleshooting", {guide.key for guide in error_hits})
        self.assertEqual(help_content.find_guides(""), list(help_content.GUIDES))
        self.assertEqual(help_content.find_guides("zzzznotathing"), [])

    def test_about_names_the_company_owner_and_site(self) -> None:
        html = help_content.about_html()
        for text in (branding.APP_NAME, branding.VERSION, branding.COMPANY,
                     branding.OWNER, branding.WEBSITE):
            self.assertIn(text, html)
        plain = help_content.about_plain_text()
        self.assertIn(branding.COMPANY_SHORT, plain)
        self.assertIn(branding.OWNER, plain)

    def test_launcher_can_be_found_in_the_checkout(self) -> None:
        found = help_content.find_launcher()
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "launcher.py")
        self.assertTrue(found.is_file())

    def test_start_launcher_passes_the_data_folder_through(self) -> None:
        with mock.patch.object(help_content.subprocess, "Popen") as popen, \
                mock.patch.object(help_content, "_python_command",
                                  return_value="pythonw.exe"):
            ok, data = help_content.start_launcher()
        self.assertTrue(ok)
        self.assertTrue(data)
        env = popen.call_args.kwargs["env"]
        self.assertIn("VOICEFORGE_DATA", env)
        self.assertIn("VOICEFORGE_HOME", env)
        args = popen.call_args.args[0]
        self.assertEqual(Path(args[1]).name, "launcher.py")

    def test_missing_launcher_explains_itself(self) -> None:
        with mock.patch.object(help_content, "find_launcher",
                               return_value=None):
            ok, message = help_content.start_launcher()
        self.assertFalse(ok)
        self.assertIn("launcher", message.lower())


class TestHelpDialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_help_dialog_lists_and_filters_guides(self) -> None:
        dialog = help_dialogs.HelpDialog()
        self.assertGreater(dialog.list.count(), 3)
        self.assertIn("guide", dialog.count.text())

        dialog.search.setText("format")
        self.assertGreater(dialog.list.count(), 0)
        self.assertLessEqual(dialog.list.count(),
                             len(help_content.GUIDES))
        self.assertTrue(dialog.browser.toHtml())
        dialog.deleteLater()

    def test_help_dialog_can_open_a_specific_guide(self) -> None:
        dialog = help_dialogs.HelpDialog(guide="troubleshooting")
        current = dialog.list.currentItem()
        self.assertIsNotNone(current)
        self.assertEqual(current.data(help_dialogs.Qt.ItemDataRole.UserRole),
                         "troubleshooting")
        self.assertIn("Edge", dialog.browser.toPlainText())
        dialog.deleteLater()

    def test_help_dialog_says_so_when_nothing_matches(self) -> None:
        dialog = help_dialogs.HelpDialog()
        dialog.search.setText("qwertyuiopasdf")
        self.assertEqual(dialog.list.count(), 0)
        self.assertIn("No guide", dialog.browser.toPlainText())
        dialog.deleteLater()

    def test_about_dialog_has_a_working_back_to_launcher(self) -> None:
        calls: list[bool] = []

        def back() -> bool:
            calls.append(True)
            return True

        dialog = help_dialogs.AboutDialog(on_back=back)
        self.assertIn(branding.OWNER, dialog.browser.toPlainText())
        dialog._back()
        self.assertEqual(calls, [True])
        self.assertTrue(dialog.back_requested)
        dialog.deleteLater()

    def test_back_can_be_cancelled(self) -> None:
        dialog = help_dialogs.AboutDialog(on_back=lambda: False)
        dialog._back()
        self.assertFalse(dialog.back_requested)
        dialog.deleteLater()


class TestWorkspaceLayout(unittest.TestCase):
    def test_help_modules_do_not_require_qt_to_read_content(self) -> None:
        # help_content is imported at module scope above without a QApplication;
        # this test documents that contract for the launcher/CLI.
        self.assertIsInstance(help_content.guide_titles(), list)


if __name__ == "__main__":
    unittest.main()
