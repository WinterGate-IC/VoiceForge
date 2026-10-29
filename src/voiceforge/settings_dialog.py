"""The one Settings dialog, shared by the launcher and the native app.

Every option here is a real behaviour change, not decoration: the scheme is
applied live, the folders are where the library and renders actually go, and
the long-text numbers are what the renderer splits on.

The dialog edits a copy. Nothing is written until Save, and Cancel (or Esc)
puts the old scheme back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from . import installer_core, paths, qt_theme, resources, themes
from .preferences import DEFAULTS, FRONTENDS, Preferences
from .render import FORMAT_LABELS, normalize_format

FRONTEND_LABELS = {
    "native": "Native Desktop (PySide6)",
    "web": "Browser UI (Gradio)",
    "window": "Desktop Window (pywebview)",
    "flet": "Flet UI (Flutter)",
}


def _resolve(root: Path, text: str) -> Path | None:
    text = (text or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path(root) / path
    try:
        return path.resolve()
    except OSError:
        return path


def _open(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class ThemeSwatch(QFrame):
    """A small clickable preview of one scheme."""

    clicked = Signal(str)

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self.name = name
        palette = themes.get(name)
        self.setObjectName("swatch")
        self.setProperty("selected", False)
        self.setFixedHeight(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        title = QLabel(palette["label"])
        title.setStyleSheet("font-weight: 700; font-size: 12px;")
        blurb = QLabel(palette["blurb"])
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 10px; color: #9aa4b2;")

        bars = QHBoxLayout()
        bars.setSpacing(3)
        for colour in (palette["ACCENT"], palette["ACCENT_SOFT"],
                       palette["BORDER"], palette["TEXT"]):
            bar = QFrame()
            bar.setFixedHeight(6)
            bar.setStyleSheet(f"background:{colour}; border-radius:3px;")
            bars.addWidget(bar, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addWidget(title)
        layout.addLayout(bars)
        layout.addWidget(blurb, 1)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(event)


class SettingsDialog(QDialog):
    """Edit preferences in place; `exec()` returns Accepted when saved."""

    def __init__(self, root: Path, prefs: Preferences | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self.prefs = prefs or Preferences.load(self.root)
        self._original_theme = self.prefs["theme"]
        self.moved_report: dict | None = None

        self.setWindowTitle("VoiceForge Settings")
        self.setMinimumSize(860, 660)
        self.resize(920, 740)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.path_label = QLabel(str(self.root))
        self.path_label.setObjectName("hint")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.path_label)
        open_data = QPushButton("Open data folder")
        open_data.clicked.connect(lambda: _open(self.root))
        head.addWidget(open_data)
        outer.addLayout(head)

        subtitle = QLabel("Dark by design. Changes apply when you press Save.")
        subtitle.setObjectName("subtitle")
        outer.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._wrap(self._appearance_tab()), "Appearance")
        self.tabs.addTab(self._wrap(self._folders_tab()), "Files & downloads")
        self.tabs.addTab(self._wrap(self._behavior_tab()), "Behaviour")
        self.tabs.addTab(self._wrap(self._long_text_tab()), "Long text")
        self.tabs.addTab(self._wrap(self._performance_tab()), "Performance")
        self.tabs.addTab(self._wrap(self._uninstall_tab()), "Uninstall")
        outer.addWidget(self.tabs, 1)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        footer = QHBoxLayout()
        self.restore_btn = QPushButton("Restore defaults")
        self.restore_btn.clicked.connect(self._restore_defaults)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        footer.addWidget(self.restore_btn)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        outer.addLayout(footer)

        self._load()

    # -- construction helpers --------------------------------------------
    @staticmethod
    def _wrap(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(10)

        intro = QLabel(
            "Five schemes, all genuinely dark. The whole app re-colours as "
            "soon as you pick one - no bright flash, ever.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.swatches: dict[str, ThemeSwatch] = {}
        for index, name in enumerate(themes.THEME_KEYS):
            swatch = ThemeSwatch(name)
            swatch.clicked.connect(self._choose_theme)
            self.swatches[name] = swatch
            grid.addWidget(swatch, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        self.theme_note = QLabel("")
        self.theme_note.setObjectName("mutedSmall")
        layout.addWidget(self.theme_note)
        layout.addStretch(1)
        return page

    def _folders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(14)

        voices_box, self.voices_edit, voices_browse, voices_default = \
            self._folder_row(
                "Voices folder",
                "Where your profiles and reference recordings live. Point it "
                "at another drive, or type a new name to rename the folder.")
        voices_browse.clicked.connect(lambda: self._browse(self.voices_edit))
        voices_default.clicked.connect(
            lambda: self.voices_edit.setText(str(self.root / "voices")))
        layout.addWidget(voices_box)

        self.carry_voices = QCheckBox(
            "Carry existing voices across when the folder changes")
        self.carry_voices.setToolTip(
            "On: the old folder is renamed/moved. Off: the app simply starts "
            "using the new folder and leaves the old one untouched.")
        layout.addWidget(self.carry_voices)

        output_box, self.output_edit, output_browse, output_default = \
            self._folder_row(
                "Downloads folder",
                "Every render is written here. MP3 by default; WAV, FLAC and "
                "OGG are available in the format list below.")
        output_browse.clicked.connect(lambda: self._browse(self.output_edit))
        output_default.clicked.connect(
            lambda: self.output_edit.setText(str(self.root / "downloads")))
        layout.addWidget(output_box)

        text_box, self.text_edit, text_browse, text_default = \
            self._folder_row(
                "Text folder",
                "Save .txt scripts here and open them again from the Script "
                "tab. Nothing is remembered automatically between sessions.")
        text_browse.clicked.connect(lambda: self._browse(self.text_edit))
        text_default.clicked.connect(
            lambda: self.text_edit.setText(str(self.root / "texts")))
        layout.addWidget(text_box)

        format_box = QFrame()
        format_box.setObjectName("card")
        fb = QVBoxLayout(format_box)
        fb.setContentsMargins(12, 10, 12, 10)
        fb.setSpacing(6)
        format_label = QLabel("Download format")
        format_label.setObjectName("heading")
        format_blurb = QLabel(
            "MP3 is the default because it plays everywhere and stays small. "
            "WAV and FLAC are lossless; OGG is the smallest lossy option.")
        format_blurb.setWordWrap(True)
        format_blurb.setObjectName("mutedSmall")
        self.format_combo = QComboBox()
        for key, label in FORMAT_LABELS.items():
            self.format_combo.addItem(label, key)
        fb.addWidget(format_label)
        fb.addWidget(format_blurb)
        fb.addWidget(self.format_combo)
        layout.addWidget(format_box)

        note = QLabel(
            f"Default locations: <code>{self.root / 'voices'}</code>, "
            f"<code>{self.root / 'downloads'}</code> and "
            f"<code>{self.root / 'texts'}</code>. Leave a field empty to use "
            "them. Existing files are never overwritten.")
        note.setWordWrap(True)
        note.setObjectName("mutedSmall")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _folder_row(self, title: str, blurb: str):
        box = QFrame()
        box.setObjectName("card")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setObjectName("heading")
        text = QLabel(blurb)
        text.setWordWrap(True)
        text.setObjectName("mutedSmall")

        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setClearButtonEnabled(True)
        browse = QPushButton("Browse…")
        default = QPushButton("Default")
        row.addWidget(edit, 1)
        row.addWidget(browse)
        row.addWidget(default)

        layout.addWidget(label)
        layout.addWidget(text)
        layout.addLayout(row)
        return box, edit, browse, default

    def _behavior_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(12)

        row = QHBoxLayout()
        label = QLabel("Default front-end")
        label.setObjectName("heading")
        self.frontend_combo = QComboBox()
        for key in FRONTENDS:
            self.frontend_combo.addItem(FRONTEND_LABELS.get(key, key), key)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.frontend_combo, 1)
        layout.addLayout(row)

        self.close_after = QCheckBox(
            "Close the launcher once a front-end starts")
        self.confirm_delete = QCheckBox(
            "Ask before deleting a voice")
        self.autoplay = QCheckBox(
            "Play the result automatically after a render")
        self.maximized = QCheckBox(
            "Open the native app maximised")
        self.hints = QCheckBox(
            "Show inline hints and keyboard shortcuts")
        for box in (self.close_after, self.confirm_delete, self.autoplay,
                    self.maximized, self.hints):
            layout.addWidget(box)

        volume = QHBoxLayout()
        volume_label = QLabel("Player volume")
        volume_label.setObjectName("heading")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setTickInterval(10)
        self.volume.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.volume_value = QLabel("90%")
        self.volume_value.setFixedWidth(44)
        self.volume.valueChanged.connect(
            lambda value: self.volume_value.setText(f"{value}%"))
        volume.addWidget(volume_label)
        volume.addWidget(self.volume, 1)
        volume.addWidget(self.volume_value)
        layout.addSpacing(6)
        layout.addLayout(volume)
        layout.addStretch(1)
        return page

    def _long_text_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(12)

        intro = QLabel(
            "Long scripts are split at sentence boundaries and stitched back "
            "together with a short pause. These two numbers control that.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        size_row = QHBoxLayout()
        size_label = QLabel("Characters per part")
        size_label.setObjectName("heading")
        self.chunk_chars = QSpinBox()
        self.chunk_chars.setRange(400, 8000)
        self.chunk_chars.setSingleStep(100)
        self.chunk_chars.setSuffix(" chars")
        self.chunk_chars.setToolTip(
            "The edge engine reads roughly 1,800 characters comfortably. "
            "Smaller parts are more reliable on very long books.")
        size_row.addWidget(size_label)
        size_row.addStretch(1)
        size_row.addWidget(self.chunk_chars)
        layout.addLayout(size_row)

        gap_row = QHBoxLayout()
        gap_label = QLabel("Pause between parts")
        gap_label.setObjectName("heading")
        self.chunk_gap = QDoubleSpinBox()
        self.chunk_gap.setRange(0.0, 3.0)
        self.chunk_gap.setSingleStep(0.05)
        self.chunk_gap.setDecimals(2)
        self.chunk_gap.setSuffix(" s")
        gap_row.addWidget(gap_label)
        gap_row.addStretch(1)
        gap_row.addWidget(self.chunk_gap)
        layout.addLayout(gap_row)

        self.plan_label = QLabel("")
        self.plan_label.setObjectName("hint")
        self.plan_label.setWordWrap(True)
        self.chunk_chars.valueChanged.connect(self._update_estimate)
        self.chunk_gap.valueChanged.connect(self._update_estimate)
        layout.addWidget(self.plan_label)
        layout.addStretch(1)
        return page

    def _performance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(12)

        intro = QLabel(
            "Long scripts are rendered in parts. Edge parts are independent "
            "network requests, so a few can run at once and finish in a "
            "fraction of the wait. VoiceForge watches the machine while it "
            "works and slows down on its own if it starts to struggle.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(8)

        self.adaptive = QCheckBox(
            "Adapt rendering to this computer automatically (recommended)")
        self.adaptive.setToolTip(
            "On: VoiceForge picks a safe number of parallel parts and backs "
            "off to one at a time when CPU or memory gets busy or a part "
            "fails. It ramps back up after a few healthy parts.\n\n"
            "Off: no automatic changes. Auto below means one part at a time.")
        inner.addWidget(self.adaptive)

        row = QHBoxLayout()
        label = QLabel("Parts at a time")
        label.setObjectName("heading")
        self.render_workers = QSpinBox()
        self.render_workers.setRange(0, 8)
        self.render_workers.setSpecialValueText("Auto (recommended)")
        self.render_workers.setToolTip(
            "Auto lets VoiceForge decide (up to four for Edge). A fixed number "
            "is always honoured, even when the machine is busy - useful if you "
            "know your connection handles more.")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(self.render_workers)
        inner.addLayout(row)

        self.perf_status = QLabel("")
        self.perf_status.setObjectName("hint")
        self.perf_status.setWordWrap(True)
        inner.addWidget(self.perf_status)

        check = QPushButton("Check this computer now")
        check.clicked.connect(self._refresh_performance)
        inner.addWidget(check)
        layout.addWidget(card)

        safety = QLabel(
            "Safety net: each part and the final file are written to a hidden "
            "temporary name, verified, then renamed into place. A crash, a "
            "full disk, or a half-finished download can never leave a broken "
            "file in your downloads folder. A corrupt part is deleted and "
            "rendered once more before the render stops with a clear message.")
        safety.setWordWrap(True)
        safety.setObjectName("mutedSmall")
        layout.addWidget(safety)

        note = QLabel(
            "The local clone engine holds a large model in memory, so it stays "
            "sequential no matter what is chosen here. Edge is the engine that "
            "benefits from parallel parts.")
        note.setWordWrap(True)
        note.setObjectName("mutedSmall")
        layout.addWidget(note)
        layout.addStretch(1)

        self.adaptive.toggled.connect(self._refresh_performance)
        self.render_workers.valueChanged.connect(self._refresh_performance)
        return page

    def _refresh_performance(self, *_args) -> None:
        info = resources.snapshot()
        now = resources.choose_workers(
            1000, self.render_workers.value(), self.adaptive.isChecked(), info)
        if not self.adaptive.isChecked() and not self.render_workers.value():
            timing = "one part at a time"
        else:
            timing = f"{now} part{'s' if now != 1 else ''} at a time"
        self.perf_status.setText(
            f"Right now: {timing}.\n{resources.describe(info)}")

    def _uninstall_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(12)

        self._install_app = paths.app_dir()
        self._install_config = paths.read_install(self._install_app)

        heading = QLabel("Remove VoiceForge from this computer")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        warning = QLabel(
            "This removes the installed program, its bundled runtime, the "
            "installer record and the Desktop/Start Menu shortcuts.\n\n"
            "Your voices, downloads, saved text and settings are separate. "
            "You will be asked whether to keep them; keeping them is the "
            "default and lets a reinstall find everything again.")
        warning.setWordWrap(True)
        warning.setObjectName("muted")
        layout.addWidget(warning)

        if self._install_config:
            where = QLabel(
                f"Installed at: {self._install_app}\n"
                f"Library: {self._install_config.get('data_dir') or '(not recorded)'}")
        else:
            where = QLabel(
                "This copy was not created by VoiceForge Setup - it is a "
                "portable or source copy. There is no installer record to "
                "remove. Close VoiceForge and delete the folder to remove it.")
        where.setWordWrap(True)
        where.setObjectName("mutedSmall")
        layout.addWidget(where)

        self.uninstall_btn = QPushButton("Uninstall VoiceForge…")
        self.uninstall_btn.setToolTip(
            "Asks for confirmation first, then lets you choose whether to "
            "keep or delete your voice library.")
        self.uninstall_btn.clicked.connect(self._uninstall)
        layout.addWidget(self.uninstall_btn)

        note = QLabel(
            "Uninstalling cannot be undone. If you choose to delete your "
            "library, every voice, render and saved script in that folder is "
            "removed permanently.")
        note.setWordWrap(True)
        note.setObjectName("mutedSmall")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _uninstall(self) -> None:
        app = self._install_app
        config = self._install_config or paths.read_install(app)
        if not config:
            QMessageBox.information(
                self, "Uninstall VoiceForge",
                "This copy was not installed by VoiceForge Setup, so there is "
                "no uninstaller record.\n\nClose VoiceForge and delete the "
                "program folder to remove a portable copy. Your library folder "
                "is separate and can be kept.")
            return
        data_dir = config.get("data_dir") or "(not recorded)"
        answer = QMessageBox.warning(
            self, "Uninstall VoiceForge",
            "Remove VoiceForge from this computer?\n\n"
            f"Program folder:\n    {app}\n\n"
            f"Library folder:\n    {data_dir}\n\n"
            "The program, runtime and shortcuts will be deleted. Your library "
            "is kept unless you choose to delete it in the next step.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        purge = False
        if config.get("data_dir"):
            second = QMessageBox.warning(
                self, "Delete your saved voices too?",
                f"Also delete the library folder?\n    {data_dir}\n\n"
                "Choose No to keep every voice, download, saved script and "
                "setting. Choose Yes only if you want them permanently erased.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            purge = second == QMessageBox.StandardButton.Yes

        try:
            result = installer_core.uninstall(app, purge_data=purge)
            if app.is_dir():
                installer_core.schedule_folder_removal(app)
        except Exception as exc:
            QMessageBox.critical(
                self, "Could not uninstall VoiceForge", str(exc))
            return

        kept = None if purge else (config.get("data_dir") or None)
        tail = (f"\n\nYour library is still at:\n    {kept}" if kept else
                "\n\nYour library folder was deleted.")
        QMessageBox.information(
            self, "VoiceForge removed",
            f"Removed {len(result['removed'])} program item(s).{tail}\n\n"
            "VoiceForge will close now. Any remaining program files are "
            "removed a moment later.")
        self.accept()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    # -- state -----------------------------------------------------------
    def _load(self) -> None:
        prefs = self.prefs
        self._choose_theme(prefs["theme"], preview=False)
        self.voices_edit.setText(prefs["voices_dir"])
        self.voices_edit.setPlaceholderText(str(self.root / "voices"))
        self.output_edit.setText(prefs["output_dir"])
        self.output_edit.setPlaceholderText(str(self.root / "downloads"))
        self.text_edit.setText(prefs["text_dir"])
        self.text_edit.setPlaceholderText(str(self.root / "texts"))
        format_index = self.format_combo.findData(prefs["output_format"])
        self.format_combo.setCurrentIndex(max(0, format_index))
        self.carry_voices.setChecked(True)
        index = self.frontend_combo.findData(prefs["default_frontend"])
        self.frontend_combo.setCurrentIndex(max(0, index))
        self.close_after.setChecked(bool(prefs["close_launcher_after_start"]))
        self.confirm_delete.setChecked(bool(prefs["confirm_delete"]))
        self.autoplay.setChecked(bool(prefs["autoplay_after_render"]))
        self.maximized.setChecked(bool(prefs["start_maximized"]))
        self.hints.setChecked(bool(prefs["show_hints"]))
        self.volume.setValue(int(prefs["player_volume"]))
        self.chunk_chars.setValue(int(prefs["chunk_chars"]))
        self.chunk_gap.setValue(float(prefs["chunk_gap"]))
        self.adaptive.setChecked(bool(prefs["adaptive_performance"]))
        self.render_workers.setValue(int(prefs["render_workers"]))
        self._refresh_performance()
        self._update_estimate()

    def _choose_theme(self, name: str, preview: bool = True) -> None:
        if name not in themes.THEMES:
            name = themes.DEFAULT_THEME
        self._theme = name
        for key, swatch in self.swatches.items():
            swatch.set_selected(key == name)
        detail = themes.get(name)
        self.theme_note.setText(f"{detail['label']}: {detail['blurb']}")
        if preview:
            app = QApplication.instance()
            if app is not None:
                qt_theme.apply(app, name)

    def _browse(self, edit: QLineEdit) -> None:
        start = edit.text().strip() or str(self.root)
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a folder", start,
            QFileDialog.Option.ShowDirsOnly)
        if chosen:
            edit.setText(chosen)

    def _update_estimate(self) -> None:
        chars = self.chunk_chars.value()
        books = 90_000
        parts = max(1, -(-books // max(chars, 1)))
        pause = parts * self.chunk_gap.value()
        self.plan_label.setText(
            f"A 90,000-character book becomes about {parts} parts, adding "
            f"roughly {pause:.0f}s of pauses in total. "
            f"One part is never split.")

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self, "Restore defaults",
            "Reset every setting on this page to its factory value?\n\n"
            "Your voices, recordings and renders are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._choose_theme(str(DEFAULTS["theme"]))
        self.voices_edit.setText("")
        self.output_edit.setText("")
        self.text_edit.setText("")
        format_index = self.format_combo.findData(DEFAULTS["output_format"])
        self.format_combo.setCurrentIndex(max(0, format_index))
        self.carry_voices.setChecked(True)
        index = self.frontend_combo.findData(DEFAULTS["default_frontend"])
        self.frontend_combo.setCurrentIndex(max(0, index))
        self.close_after.setChecked(bool(DEFAULTS["close_launcher_after_start"]))
        self.confirm_delete.setChecked(bool(DEFAULTS["confirm_delete"]))
        self.autoplay.setChecked(bool(DEFAULTS["autoplay_after_render"]))
        self.maximized.setChecked(bool(DEFAULTS["start_maximized"]))
        self.hints.setChecked(bool(DEFAULTS["show_hints"]))
        self.volume.setValue(int(DEFAULTS["player_volume"]))
        self.chunk_chars.setValue(int(DEFAULTS["chunk_chars"]))
        self.chunk_gap.setValue(float(DEFAULTS["chunk_gap"]))
        self.adaptive.setChecked(bool(DEFAULTS["adaptive_performance"]))
        self.render_workers.setValue(int(DEFAULTS["render_workers"]))
        self._refresh_performance()
        self.status.setText(
            "Factory values shown. Press Save to apply them.")

    # -- save ------------------------------------------------------------
    def _save(self) -> None:
        voices = _resolve(self.root, self.voices_edit.text())
        output = _resolve(self.root, self.output_edit.text())
        text = _resolve(self.root, self.text_edit.text())
        folders = [("voices", voices), ("renders", output), ("text", text)]
        chosen = [(name, path) for name, path in folders if path is not None]
        for index, (name, path) in enumerate(chosen):
            for other_name, other_path in chosen[index + 1:]:
                if path == other_path:
                    QMessageBox.warning(
                        self, "Folders overlap",
                        f"The {name} and {other_name} folders cannot be the "
                        "same. Pick a separate folder for each so nothing gets "
                        "mixed up.")
                    return

        old_voices = self.prefs.voices_dir
        try:
            if voices is None:
                # An empty field means "the default folder". Moving back is
                # still a move, so honour the same carry option.
                default_voices = self.prefs.default_voices_dir()
                if (self.carry_voices.isChecked()
                        and default_voices != old_voices):
                    self.moved_report = self.prefs.relocate_voices(
                        default_voices, move=True)
                self.prefs.set("voices_dir", "")
            elif voices != old_voices:
                if self.carry_voices.isChecked():
                    self.moved_report = self.prefs.relocate_voices(
                        voices, move=True)
                else:
                    voices.mkdir(parents=True, exist_ok=True)
                    self.prefs.set("voices_dir", str(voices))
            else:
                self.prefs.set("voices_dir", str(voices))

            if output is not None:
                output.mkdir(parents=True, exist_ok=True)
            if text is not None:
                text.mkdir(parents=True, exist_ok=True)
            self.prefs.update({
                "output_dir": str(output) if output is not None else "",
                "output_format": normalize_format(
                    self.format_combo.currentData(), DEFAULTS["output_format"]),
                "text_dir": str(text) if text is not None else "",
                "theme": self._theme,
                "default_frontend": self.frontend_combo.currentData(),
                "close_launcher_after_start": self.close_after.isChecked(),
                "confirm_delete": self.confirm_delete.isChecked(),
                "autoplay_after_render": self.autoplay.isChecked(),
                "start_maximized": self.maximized.isChecked(),
                "show_hints": self.hints.isChecked(),
                "player_volume": self.volume.value(),
                "chunk_chars": self.chunk_chars.value(),
                "chunk_gap": self.chunk_gap.value(),
                "adaptive_performance": self.adaptive.isChecked(),
                "render_workers": self.render_workers.value(),
            })
            self.prefs.save()
        except Exception as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            return

        app = QApplication.instance()
        if app is not None:
            qt_theme.apply(app, self._theme)
        self.accept()

    def reject(self) -> None:
        # Leave the app looking the way it did before the dialog opened.
        app = QApplication.instance()
        if app is not None:
            qt_theme.apply(app, self._original_theme)
        super().reject()

    # -- results ---------------------------------------------------------
    def summary(self) -> str:
        report = self.moved_report or {}
        moved = report.get("moved") or []
        skipped = report.get("skipped") or []
        if not moved and not skipped:
            return "Settings saved."
        text = f"Settings saved. Moved {len(moved)} voice folder(s)"
        if skipped:
            text += f"; skipped {len(skipped)} already present"
        return text + "."
