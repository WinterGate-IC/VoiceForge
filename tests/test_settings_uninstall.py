"""Settings has a guarded uninstall path, and it only removes installed copies."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from voiceforge import installer_core, settings_dialog  # noqa: E402


class TestUninstallSetting(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / "library"
        (self.data / "voices").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _dialog(self, app_dir: Path):
        dialog = settings_dialog.SettingsDialog(self.data)
        dialog._install_app = app_dir
        dialog._install_config = {
            "data_dir": str(self.data),
            "shortcuts": [],
        }
        return dialog

    def test_uninstall_tab_and_warning_are_present(self) -> None:
        dialog = settings_dialog.SettingsDialog(self.data)
        names = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        self.assertIn("Uninstall", names)
        self.assertTrue(dialog.uninstall_btn.isEnabled())
        dialog.deleteLater()

    def test_portable_copy_explains_there_is_nothing_to_uninstall(self) -> None:
        dialog = settings_dialog.SettingsDialog(self.data)
        dialog._install_app = self.base / "portable"
        dialog._install_config = {}

        with mock.patch.object(
                settings_dialog.QMessageBox, "information") as info, \
                mock.patch.object(
                    settings_dialog.installer_core, "uninstall") as remove:
            dialog._uninstall()
        self.assertTrue(info.called)
        self.assertIn("portable", info.call_args.args[2].lower())
        remove.assert_not_called()
        dialog.deleteLater()

    def test_installed_copy_uninstalls_but_keeps_the_library(self) -> None:
        app_dir = self.base / "program"
        app_dir.mkdir()
        (app_dir / "install.json").write_text(json.dumps({
            "data_dir": str(self.data), "shortcuts": []}), encoding="utf-8")
        (app_dir / "launcher.py").write_text("# launcher", encoding="utf-8")
        (app_dir / "src").mkdir()
        (app_dir / "src" / "voiceforge.py").write_text("", encoding="utf-8")
        runtime = app_dir / "runtime"
        runtime.mkdir()
        (runtime / "python.exe").write_bytes(b"placeholder")

        dialog = self._dialog(app_dir)
        with mock.patch.object(
                settings_dialog.QMessageBox, "warning",
                side_effect=[QMessageBox.StandardButton.Yes,
                             QMessageBox.StandardButton.No]) as warn, \
                mock.patch.object(
                    settings_dialog.QMessageBox, "information"), \
                mock.patch.object(
                    settings_dialog.installer_core, "schedule_folder_removal") as schedule, \
                mock.patch.object(QApplication, "quit"):
            dialog._uninstall()

        self.assertEqual(warn.call_count, 2)
        self.assertFalse((app_dir / "launcher.py").exists())
        self.assertFalse((app_dir / "install.json").exists())
        self.assertTrue((self.data / "voices").is_dir())
        self.assertTrue(runtime.exists(), "the running runtime is removed later")
        schedule.assert_called_once()
        dialog.deleteLater()

    def test_choosing_delete_removes_the_library_too(self) -> None:
        app_dir = self.base / "program"
        app_dir.mkdir()
        (app_dir / "install.json").write_text(json.dumps({
            "data_dir": str(self.data), "shortcuts": []}), encoding="utf-8")
        dialog = self._dialog(app_dir)
        with mock.patch.object(
                settings_dialog.QMessageBox, "warning",
                side_effect=[QMessageBox.StandardButton.Yes,
                             QMessageBox.StandardButton.Yes]), \
                mock.patch.object(settings_dialog.QMessageBox, "information"), \
                mock.patch.object(
                    settings_dialog.installer_core, "schedule_folder_removal"), \
                mock.patch.object(QApplication, "quit"):
            dialog._uninstall()
        self.assertFalse(self.data.exists())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
