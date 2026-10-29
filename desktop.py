"""VoiceForge Desktop - native PySide6 front-end for Windows and Linux.

Same core as every other front-end (voiceforge.render / project / library /
styles / effects); only the presentation layer differs. Nothing here imports
gradio.

    python desktop.py
    python desktop.py --self-test     # build the window and exit (no display)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import (
    QSettings, QStringListModel, Qt, QThread, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (  # noqa: E402
    QAction, QBrush, QColor, QGuiApplication, QKeySequence, QShortcut,
)
from PySide6.QtMultimedia import (  # noqa: E402
    QAudioFormat, QAudioOutput, QAudioSource, QMediaDevices, QMediaPlayer,
)
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QComboBox, QCompleter, QDialog,
    QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from voiceforge import branding, env as vf_env  # noqa: E402
from voiceforge import audio_io, help_content, help_dialogs  # noqa: E402
from voiceforge import library, paths, qt_theme, seed, styles  # noqa: E402
from voiceforge import voice_choices  # noqa: E402
from voiceforge.advanced_effects import (  # noqa: E402
    AdvancedEffectsDialog, describe_effects, lab_values,
)
from voiceforge.effects import CHAINS  # noqa: E402
from voiceforge.preferences import Preferences  # noqa: E402
from voiceforge.project import Project  # noqa: E402
from voiceforge.render import (  # noqa: E402
    FORMAT_LABELS, cleanup_partials, normalize_format, output_dir, render_text)
from voiceforge.settings import ADVANCED_PARAMS, PARAMS  # noqa: E402
from voiceforge.settings_dialog import SettingsDialog  # noqa: E402
from voiceforge.textsplit import plan as speech_plan  # noqa: E402

vf_env.sanitize()

NONE = "(no library voice)"
DATA = paths.data_root(__file__)
CACHE = DATA / ".cache"
VOICE_CACHE = CACHE / "edge_voices.json"
PREVIEW_DIR = CACHE / "preview"
LOG = CACHE / "desktop-errors.log"
FALLBACK_VOICES = [
    "en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural",
    "en-US-EmmaMultilingualNeural", "en-US-BrianMultilingualNeural",
    "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural",
]


# ----------------------------------------------------------------- utilities
def open_path(path) -> None:
    """Open a file or folder in whatever the OS uses for it."""
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def cached_voices() -> list[str]:
    try:
        data = json.loads(VOICE_CACHE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def fetch_voices() -> list[str]:
    """Network call - only ever run from a background worker."""
    from voiceforge.engines import list_voices

    names = sorted({r["short"] for r in list_voices() if r.get("short")})
    if names:
        CACHE.mkdir(parents=True, exist_ok=True)
        VOICE_CACHE.write_text(json.dumps(names, indent=2), encoding="utf-8")
    return names


def _read_int(text) -> int:
    m = re.match(r"\s*([+-]?\d+)", str(text or "0"))
    return int(m.group(1)) if m else 0


def preview_excerpt(text: str, limit: int = 320) -> str:
    """A short, sentence-aware slice for the Quick preview button.

    Previews should be fast and let you judge the voice, not wait for a whole
    chapter. We take the first sentence or two and never cut mid-word.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for stop in (". ", "! ", "? ", "… "):
        index = cut.rfind(stop)
        if index >= 60:
            return cut[:index + 1].strip()
    index = cut.rfind(" ")
    return (cut[:index] if index > 0 else cut).strip() + "…"


class VoicePickerDialog(QDialog):
    """A small, filterable voice catalogue.

    The type box is still the fastest way in when you know the short name.
    This dialog is for the other case: you want a male voice, a female voice,
    Ava specifically, or a different accent, and you want to see the options.
    """

    def __init__(self, current: str, names: list[str], parent=None,
                 mode: str = "All") -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a voice")
        self.setMinimumSize(760, 560)
        self._choices = voice_choices.merge_choices(names)
        self._current = current

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Pick a voice by gender or accent, or search for a name. "
            "The short name in brackets is what the type box uses.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a name, accent or short name")
        self.search.setClearButtonEnabled(True)
        self.mode = QComboBox()
        for label, value in (
                ("All voices", "All"), ("Featured", "Featured"),
                ("Male voices", voice_choices.MALE),
                ("Female voices", voice_choices.FEMALE),
                ("Other / characters", voice_choices.OTHER)):
            self.mode.addItem(label, value)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.mode)
        layout.addLayout(filters)

        self.voices = QListWidget()
        self.voices.setAlternatingRowColors(True)
        self.voices.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.voices, 1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("mutedSmall")
        layout.addWidget(self.detail)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._refill)
        self.mode.currentIndexChanged.connect(self._refill)
        self.voices.currentItemChanged.connect(self._show_detail)
        self.voices.itemDoubleClicked.connect(lambda _item: self.accept())
        wanted = self.mode.findData(mode)
        if wanted >= 0:
            self.mode.setCurrentIndex(wanted)
        self._refill()

    def _refill(self) -> None:
        query = self.search.text().strip().lower()
        mode = self.mode.currentData()
        self.voices.clear()
        for choice in self._choices:
            if mode == "Featured" and not choice.featured:
                continue
            if mode in (voice_choices.MALE, voice_choices.FEMALE,
                        voice_choices.OTHER) and choice.gender != mode:
                continue
            haystack = " ".join(
                (choice.name, choice.short, choice.locale, choice.note)).lower()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(
                f"{choice.name}  -  {choice.gender}  -  {choice.locale}"
                f"    [{choice.short}]")
            item.setData(Qt.ItemDataRole.UserRole, choice.short)
            item.setToolTip(choice.detailed_label)
            self.voices.addItem(item)
            if choice.short == self._current:
                self.voices.setCurrentItem(item)
        if self.voices.currentItem() is None and self.voices.count():
            self.voices.setCurrentRow(0)
        if not self.voices.count():
            self.detail.setText("No voice matches that search.")

    def _show_detail(self, current, _previous=None) -> None:
        if current is None:
            return
        short = str(current.data(Qt.ItemDataRole.UserRole))
        choice = voice_choices.describe(short)
        self.detail.setText(
            f"{choice.detailed_label}    Short name: {choice.short}")

    def selected_short(self) -> str:
        item = self.voices.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole))


class Worker(QThread):
    """Run a blocking call off the UI thread; report result, message or progress."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class LabeledSlider(QWidget):
    """Slider with a live numeric readout. Real value = int / scale."""

    def __init__(self, title: str, lo: int, hi: int, value: int,
                 scale: int = 1, suffix: str = "", signed: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.scale = scale
        self.suffix = suffix
        self.signed = signed

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.setPageStep(max(1, (hi - lo) // 10))
        self.slider.valueChanged.connect(self._refresh)

        self.name = QLabel(title)
        self.name.setMinimumWidth(112)
        self.readout = QLabel()
        self.readout.setMinimumWidth(64)
        self.readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.name)
        row.addWidget(self.slider, 1)
        row.addWidget(self.readout)
        self._refresh(self.slider.value())

    def _refresh(self, _=None) -> None:
        v = self.slider.value()
        if self.scale == 1:
            text = f"{v:+d}" if self.signed else str(v)
        else:
            text = f"{v / self.scale:.2f}"
        self.readout.setText(f"{text}{self.suffix}")

    def value(self) -> float:
        return self.slider.value() / self.scale

    def set_value(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(float(value) * self.scale)))
        self.slider.blockSignals(False)
        self._refresh()


class RecorderDialog(QDialog):
    """Capture a reference clip from the default microphone, raw PCM -> WAV.

    Deliberately codec-free: QMediaRecorder would drag in container/codec
    support that varies per Qt build. QAudioSource hands us bytes and the
    standard library writes the WAV header, so it works the same on every
    platform.
    """

    MAX_SECONDS = 30
    RATE = 22050
    CHANNELS = 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record a voice sample")
        self.setMinimumWidth(420)
        self.bytes = bytearray()
        self.io = None
        self.source: QAudioSource | None = None
        self.format = QAudioFormat()
        self.path: Path | None = None
        self.seconds = 0

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self.info = QLabel(
            "Read 6-20 seconds of ordinary speech. Hold a steady distance from "
            "the microphone, no music, no other voices."
        )
        self.info.setWordWrap(True)

        self.elapsed = QLabel("00:00")
        self.elapsed.setStyleSheet("font-size: 28px; font-weight: 700;")
        self.elapsed.setAlignment(Qt.AlignCenter)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")

        self.record_btn = QPushButton("●  Start recording")
        self.record_btn.setObjectName("primary")
        self.record_btn.clicked.connect(self._toggle)

        self.save_btn = QPushButton("Use this recording")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.elapsed)
        layout.addWidget(self.record_btn)
        layout.addLayout(buttons)
        layout.addWidget(self.status)

        self._probe()

    # -- device handling --------------------------------------------------
    def _probe(self) -> None:
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.record_btn.setEnabled(False)
            self.status.setText(
                "No microphone detected. You can still attach an existing "
                "recording with Browse…")
            return

        fmt = QAudioFormat()
        fmt.setSampleRate(self.RATE)
        fmt.setChannelCount(self.CHANNELS)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if not device.isFormatSupported(fmt):
            preferred = device.preferredFormat()
            if preferred.sampleFormat() != QAudioFormat.Int16:
                self.record_btn.setEnabled(False)
                self.status.setText(
                    f"The microphone ({device.description()}) does not offer "
                    "16-bit PCM audio, so in-app recording is unavailable. "
                    "Record with another app and use Browse…")
                return
            fmt = preferred
        self.format = fmt
        self.source = QAudioSource(device, fmt, self)

    # -- recording --------------------------------------------------------
    def _toggle(self) -> None:
        if self.source is None:
            return
        if self.io is None:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        self.bytes.clear()
        self.seconds = 0
        self.elapsed.setText("00:00")
        self.save_btn.setEnabled(False)
        self.io = self.source.start()
        if self.io is None:
            self.status.setText("Could not start the microphone (it may be in use).")
            return
        self.io.readyRead.connect(self._read)
        self.timer.start()
        self.record_btn.setText("■  Stop recording")
        self.status.setText("Recording…")

    def _read(self) -> None:
        if self.io is None:
            return
        chunk = self.io.readAll()
        if chunk:
            self.bytes.extend(bytes(chunk.data()))

    def _stop(self) -> None:
        self.timer.stop()
        if self.io is not None:
            self.io.readyRead.disconnect(self._read)
        self.source.stop()
        self.io = None
        self.record_btn.setText("●  Start recording")

        if len(self.bytes) < self.RATE * 2:  # under one second
            self.bytes.clear()
            self.status.setText("Too short - hold the recording for at least a second.")
            return
        self.save_btn.setEnabled(True)
        duration = len(self.bytes) / 2 / self.format.sampleRate()
        self.status.setText(f"Captured {duration:.1f}s. Listen back in any player, "
                            "or record again if it is noisy.")

    def _tick(self) -> None:
        self.seconds += 1
        self.elapsed.setText(f"{self.seconds // 60:02d}:{self.seconds % 60:02d}")
        if self.seconds >= self.MAX_SECONDS:
            self._stop()
            self.status.setText("Stopped at the 30 second limit.")

    # -- output -----------------------------------------------------------
    def _save(self) -> None:
        if not self.bytes:
            return
        out = CACHE / "recordings"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"take-{datetime.now():%Y%m%d-%H%M%S}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(self.format.channelCount())
            wav.setsampwidth(2)  # Int16
            wav.setframerate(self.format.sampleRate())
            wav.writeframes(bytes(self.bytes))
        self.path = path
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.io is not None and self.source is not None:
            self.io.readyRead.disconnect(self._read)
            self.source.stop()
            self.io = None
        super().closeEvent(event)


# ------------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VoiceForge - Native")
        self.setMinimumSize(1080, 720)
        self.resize(1380, 900)
        self.current_path: Path | None = None
        self._current_text_path: Path | None = None
        self.render_worker: Worker | None = None
        self.voice_worker: Worker | None = None
        self._loading = False
        self._seeking = False
        self._advanced: dict = lab_values()
        self.prefs = Preferences.load(DATA)

        # Live render progress. The renderer reports exact character counts as
        # each part finishes; between reports the timer estimates how far into
        # the current part we are, so the bar keeps moving and the ETA updates.
        self._progress_info: dict = {}
        self._progress_started = 0.0
        self._progress_part_started = 0.0
        self._progress_rate = 0.0       # characters per second, learned
        self._progress_label = ""
        self._progress_adapt = ""
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(400)
        self._progress_timer.timeout.connect(self._tick_progress)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(int(self.prefs["player_volume"]) / 100)

        self._build_toolbar()
        self._build_ui()
        seed.ensure_defaults(DATA)
        self._refresh_library()
        self._refresh_history()
        self._sync_from_project()
        self._apply_hints()
        self._restore_geometry()
        self._discard_legacy_script()
        self._refresh_texts()
        self._restore_last_text()
        # Remove chunk files left by older builds: downloads should only ever
        # show finished audio.
        try:
            cleanup_partials(output_dir(self._project()))
        except OSError:
            pass

    # ---------------------------------------------------------- construction
    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        self.addToolBar(bar)

        act_out = QAction("Open downloads folder", self)
        act_out.setShortcut(QKeySequence("Ctrl+O"))
        act_out.triggered.connect(lambda: open_path(output_dir(self._project())))
        bar.addAction(act_out)

        act_voices = QAction("Refresh voice list", self)
        act_voices.triggered.connect(self._refresh_edge_voices)
        bar.addAction(act_voices)

        act_web = QAction("Open browser UI", self)
        act_web.triggered.connect(self._launch_web_ui)
        bar.addAction(act_web)

        bar.addSeparator()
        act_settings = QAction("Settings…", self)
        act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(self.open_settings)
        bar.addAction(act_settings)

        act_refresh = QAction("Refresh", self)
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._refresh_all)
        bar.addAction(act_refresh)

        bar.addSeparator()
        act_help = QAction("Help & guides…", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self._open_help)
        bar.addAction(act_help)
        act_about = QAction("About VoiceForge…", self)
        act_about.triggered.connect(self._open_about)
        bar.addAction(act_about)

        menu = self.menuBar()
        help_menu = menu.addMenu("&Help")
        help_menu.addAction(act_help)
        help_menu.addAction(act_about)
        help_menu.addSeparator()
        act_launcher = QAction("Back to Launcher…", self)
        act_launcher.triggered.connect(self._menu_back_to_launcher)
        help_menu.addAction(act_launcher)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(12)

        title = QLabel("VoiceForge")
        title.setObjectName("title")
        subtitle = QLabel(
            "Write on Script, shape the voice on Speak, hear it back, then "
            "download the exact file you picked.")
        subtitle.setObjectName("subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.editor_page = self._build_editor_tab()
        self.speak_page = self._build_speak_tab()
        self.tabs.addTab(self.editor_page, "1 · Script")
        self.tabs.addTab(self.speak_page, "2 · Speak")
        self.tabs.addTab(self._build_library_tab(), "Voice Library")
        self.tabs.addTab(self._build_history_tab(), "History & Undo")

    # ---- script tab
    def _build_editor_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 16, 10, 8)
        layout.setSpacing(12)

        head = QHBoxLayout()
        heading = QLabel("Your script")
        heading.setObjectName("heading")
        head.addWidget(heading)
        head.addStretch(1)
        self.plan_label = QLabel("Empty script")
        self.plan_label.setObjectName("mutedSmall")
        head.addWidget(self.plan_label)
        layout.addLayout(head)

        hint = QLabel(
            "Paste, open a .txt file, or type straight in. Long scripts are "
            "split into parts automatically and stitched back together with a "
            "short pause. Nothing is rendered here - that happens on the Speak "
            "tab.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        paste = QPushButton("Paste clipboard")
        paste.setToolTip("Paste from the clipboard (Ctrl+V also works)")
        paste.setObjectName("primary")
        paste.clicked.connect(self._paste_script)
        load = QPushButton("Open .txt…")
        load.clicked.connect(self._load_script)
        save = QPushButton("Save .txt…")
        save.clicked.connect(self._save_script)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.script_clear)
        for b in (paste, load, save, clear):
            b.setMinimumWidth(124)
            tools.addWidget(b)
        tools.addStretch(1)
        layout.addLayout(tools)

        saved_row = QHBoxLayout()
        saved_row.setSpacing(8)
        saved_label = QLabel("Saved text")
        saved_label.setObjectName("muted")
        saved_row.addWidget(saved_label)
        self.text_combo = QComboBox()
        self.text_combo.setMinimumWidth(320)
        self.text_combo.setToolTip(
            "Pick a saved .txt file to open it. The last one you chose is "
            "reopened next time.")
        self.text_combo.activated.connect(self._open_saved_text)
        saved_row.addWidget(self.text_combo, 1)
        open_saved = QPushButton("Open")
        open_saved.clicked.connect(self._open_selected_text)
        folder = QPushButton("Text folder")
        folder.clicked.connect(self._open_text_folder)
        saved_row.addWidget(open_saved)
        saved_row.addWidget(folder)
        layout.addLayout(saved_row)

        self.script = QPlainTextEdit()
        self.script.setPlaceholderText(
            "Paste or type your script here. A line, a chapter, or a whole "
            "audiobook - it all works.")
        self.script.setMinimumHeight(340)
        self.script.textChanged.connect(self._update_plan)
        layout.addWidget(self.script, 1)

        QShortcut(QKeySequence("Ctrl+Return"), self.script,
                  activated=self._on_generate)
        QShortcut(QKeySequence("Ctrl+Enter"), self.script,
                  activated=self._on_generate)

        footer = QHBoxLayout()
        next_hint = QLabel(
            "Next: choose a voice, preview it, then download.")
        next_hint.setObjectName("mutedSmall")
        footer.addWidget(next_hint, 1)
        cont = QPushButton("Continue to Speak →")
        cont.setObjectName("primary")
        cont.setMinimumWidth(210)
        cont.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.speak_page))
        footer.addWidget(cont)
        layout.addLayout(footer)
        return page

    # ---- speak tab
    def _build_speak_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 16, 10, 8)
        layout.setSpacing(16)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 10, 0)
        lv.setSpacing(12)

        script_box = QGroupBox("Script")
        sv = QVBoxLayout(script_box)
        sv.setSpacing(8)
        self.script_summary = QLabel("No script yet.")
        self.script_summary.setWordWrap(True)
        self.script_summary.setObjectName("muted")
        sv.addWidget(self.script_summary)
        edit_row = QHBoxLayout()
        edit = QPushButton("Edit script")
        edit.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.editor_page))
        edit_row.addWidget(edit)
        edit_row.addStretch(1)
        sv.addLayout(edit_row)
        lv.addWidget(script_box)

        voice_box = QGroupBox("Voice")
        vg = QGridLayout(voice_box)
        vg.setHorizontalSpacing(12)
        vg.setVerticalSpacing(8)
        self.style_combo = QComboBox()
        for st in styles.listing():
            self.style_combo.addItem(st.name)
        self.style_combo.currentTextChanged.connect(self._on_style)

        self.lib_combo = QComboBox()
        self.lib_combo.currentTextChanged.connect(self._on_library_voice)

        vg.addWidget(QLabel("Style preset"), 0, 0)
        vg.addWidget(QLabel("Your voice library"), 0, 1)
        vg.addWidget(self.style_combo, 1, 0)
        vg.addWidget(self.lib_combo, 1, 1)

        self.edge_edit = QLineEdit()
        self.edge_edit.setPlaceholderText(PARAMS["voice"].default)
        self.edge_edit.setClearButtonEnabled(True)
        self.edge_edit.setToolTip(
            "Type any Microsoft edge voice short name (for example "
            "en-US-AndrewMultilingualNeural). Start typing to see matches, "
            "or press Voices… to pick from the fetched list.")
        self.edge_pick = QPushButton("Voices…")
        self.edge_pick.setToolTip(
            "Pick from the cached Microsoft voice list. Refresh it from the "
            "toolbar when you need the full catalogue.")
        self.edge_pick.clicked.connect(self._pick_edge_voice)
        self._edge_completer = QCompleter(cached_voices() or FALLBACK_VOICES, self)
        self._edge_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._edge_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._edge_completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self.edge_edit.setCompleter(self._edge_completer)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(8)
        voice_row.addWidget(self.edge_edit, 1)
        voice_row.addWidget(self.edge_pick)

        vg.addWidget(QLabel("Edge voice (type a short name, or pick one)"),
                     2, 0, 1, 2)
        vg.addLayout(voice_row, 3, 0, 1, 2)

        quick = QHBoxLayout()
        quick.setSpacing(6)
        quick_label = QLabel("Quick pick")
        quick_label.setObjectName("mutedSmall")
        quick.addWidget(quick_label)
        self.voice_male_btn = QPushButton("Male…")
        self.voice_male_btn.setToolTip(
            "Browse the male voices and choose one.")
        self.voice_female_btn = QPushButton("Female…")
        self.voice_female_btn.setToolTip(
            "Browse the female voices and choose one.")
        self.voice_ava_btn = QPushButton("Ava")
        self.voice_ava_btn.setToolTip(
            "Use Ava, the featured natural female voice, straight away.")
        self.voice_andrew_btn = QPushButton("Andrew")
        self.voice_andrew_btn.setToolTip(
            "Use Andrew, the default warm male voice, straight away.")
        self.voice_more_btn = QPushButton("More voices…")
        self.voice_more_btn.setToolTip(
            "Search the whole catalogue, including character voices, accents "
            "and the fetched Microsoft list.")
        self.voice_male_btn.clicked.connect(
            lambda _checked=False: self._pick_edge_voice(voice_choices.MALE))
        self.voice_female_btn.clicked.connect(
            lambda _checked=False: self._pick_edge_voice(voice_choices.FEMALE))
        self.voice_ava_btn.clicked.connect(
            lambda _checked=False: self._use_edge_voice(
                "en-US-AvaMultilingualNeural"))
        self.voice_andrew_btn.clicked.connect(
            lambda _checked=False: self._use_edge_voice(
                "en-US-AndrewMultilingualNeural"))
        self.voice_more_btn.clicked.connect(
            lambda _checked=False: self._pick_edge_voice("All"))
        for button in (self.voice_male_btn, self.voice_female_btn,
                       self.voice_andrew_btn, self.voice_ava_btn,
                       self.voice_more_btn):
            quick.addWidget(button)
        quick.addStretch(1)
        vg.addLayout(quick, 4, 0, 1, 2)

        self.voice_hint = QLabel()
        self.voice_hint.setWordWrap(True)
        self.voice_hint.setObjectName("mutedSmall")
        vg.addWidget(self.voice_hint, 5, 0, 1, 2)
        self.edge_edit.textChanged.connect(self._update_voice_hint)
        self._update_voice_hint()
        lv.addWidget(voice_box)

        delivery = QGroupBox("Delivery")
        dv = QVBoxLayout(delivery)
        dv.setSpacing(8)
        self.s_rate = LabeledSlider("Rate", -50, 50, 0, suffix="%", signed=True)
        self.s_pitch = LabeledSlider("Pitch", -60, 60, 0, suffix="Hz", signed=True)
        self.s_volume = LabeledSlider("Volume", -50, 50, 0, suffix="%", signed=True)
        for s in (self.s_rate, self.s_pitch, self.s_volume):
            dv.addWidget(s)
        lv.addWidget(delivery)

        tuning = QGroupBox("Effects & clone tuning")
        tv = QVBoxLayout(tuning)
        tv.setSpacing(8)
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(list(CHAINS))
        self.effect_combo.setToolTip(
            "A fixed character chain. Combine it with the Advanced voice lab "
            "for fully custom sound design.")
        fx_row = QHBoxLayout()
        fx_row.addWidget(QLabel("Effect chain"))
        fx_row.addWidget(self.effect_combo, 1)
        tv.addLayout(fx_row)

        advanced_row = QHBoxLayout()
        self.advanced_btn = QPushButton("Advanced voice lab…")
        self.advanced_btn.setToolTip(
            "Echo, bass, compression, stereo width, chorus, ring modulation, "
            "vibrato, tape flutter, bit-crush and more. Every value is "
            "undoable and can be saved into a voice.")
        self.advanced_btn.clicked.connect(self._open_advanced)
        advanced_row.addWidget(self.advanced_btn)
        advanced_row.addStretch(1)
        tv.addLayout(advanced_row)
        self.advanced_summary = QLabel("Voice lab: off - the voice is untouched.")
        self.advanced_summary.setWordWrap(True)
        self.advanced_summary.setObjectName("mutedSmall")
        tv.addWidget(self.advanced_summary)

        clone_note = QLabel("Clone-engine knobs (ignored by the edge engine)")
        clone_note.setObjectName("mutedSmall")
        tv.addWidget(clone_note)

        self.s_speed = LabeledSlider("Speed", 50, 200, 100, scale=100)
        self.s_temp = LabeledSlider("Temperature", 5, 150, 75, scale=100)
        self.s_topk = LabeledSlider("top_k", 1, 200, 50)
        self.s_topp = LabeledSlider("top_p", 10, 100, 85, scale=100)
        self.s_rep = LabeledSlider("Repetition", 10, 200, 50, scale=10)
        for s in (self.s_speed, self.s_temp, self.s_topk, self.s_topp, self.s_rep):
            tv.addWidget(s)
        lv.addWidget(tuning)
        lv.addStretch(1)

        # Keep every control reachable on a small laptop screen: the left
        # column scrolls instead of squeezing sliders into nothing.
        left.setMinimumWidth(520)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 0, 0, 0)
        rv.setSpacing(12)

        listen = QGroupBox("Listen before you download")
        lv2 = QVBoxLayout(listen)
        lv2.setSpacing(8)
        self.status = QLabel(
            "Press Quick preview to hear the first lines with the current "
            "voice and effects. Nothing is saved to downloads.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        lv2.addWidget(self.status)

        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.sliderPressed.connect(self._seek_start)
        self.seek.sliderReleased.connect(self._seek_end)
        lv2.addWidget(self.seek)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("mutedSmall")
        lv2.addWidget(self.time_label)

        self.preview_btn = QPushButton("▶  Quick preview")
        self.preview_btn.setToolTip(
            "Render the first lines with the current voice and effects and "
            "play them straight away. Nothing is written to downloads.")
        self.preview_btn.clicked.connect(self._on_preview)

        player_buttons = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.clicked.connect(self._toggle_play)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.show_btn = QPushButton("Open in player")
        self.show_btn.clicked.connect(self._open_current)
        for b in (self.play_btn, self.stop_btn, self.show_btn):
            b.setEnabled(False)
            player_buttons.addWidget(b)
        lv2.addWidget(self.preview_btn)
        lv2.addLayout(player_buttons)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.prefs["player_volume"]))
        self.volume.valueChanged.connect(
            lambda v: self.audio_out.setVolume(v / 100))
        volume_row.addWidget(self.volume, 1)
        lv2.addLayout(volume_row)
        rv.addWidget(listen)

        self.progress_box = QGroupBox("Render progress")
        pv = QVBoxLayout(self.progress_box)
        pv.setSpacing(6)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setToolTip(
            "Fills as each part renders. The estimate learns from finished "
            "parts and the current parallel speed, so it gets more accurate "
            "as the script goes on.")
        pv.addWidget(self.progress_bar)
        self.progress_stats = QLabel("")
        self.progress_stats.setObjectName("mutedSmall")
        self.progress_stats.setWordWrap(True)
        pv.addWidget(self.progress_stats)
        self.progress_adapt = QLabel("")
        self.progress_adapt.setObjectName("hint")
        self.progress_adapt.setWordWrap(True)
        self.progress_adapt.setVisible(False)
        pv.addWidget(self.progress_adapt)
        self.progress_eta = QLabel("No render running.")
        self.progress_eta.setObjectName("mutedSmall")
        pv.addWidget(self.progress_eta)
        self.progress_detail = QLabel(
            "Start a preview or Generate and the part-by-part progress appears "
            "here.")
        self.progress_detail.setWordWrap(True)
        self.progress_detail.setObjectName("mutedSmall")
        pv.addWidget(self.progress_detail)
        rv.addWidget(self.progress_box)

        # When a render finishes the progress widgets clear and this result
        # card takes their place: folder, filename, size and exact length.
        self.result_box = QGroupBox("Result")
        self.result_box.setVisible(False)
        rb = QVBoxLayout(self.result_box)
        rb.setSpacing(6)
        self.result_title = QLabel("One finished file")
        self.result_title.setObjectName("heading")
        rb.addWidget(self.result_title)
        self.result_name = QLabel("")
        self.result_name.setObjectName("subtitle")
        self.result_name.setWordWrap(True)
        self.result_name.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        rb.addWidget(self.result_name)
        self.result_dir = QLabel("")
        self.result_dir.setObjectName("mutedSmall")
        self.result_dir.setWordWrap(True)
        self.result_dir.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        rb.addWidget(self.result_dir)
        self.result_meta = QLabel("")
        self.result_meta.setObjectName("mutedSmall")
        self.result_meta.setWordWrap(True)
        rb.addWidget(self.result_meta)
        result_buttons = QHBoxLayout()
        self.result_open_btn = QPushButton("Open file")
        self.result_open_btn.clicked.connect(self._open_result_file)
        self.result_folder_btn = QPushButton("Open folder")
        self.result_folder_btn.clicked.connect(self._open_result_folder)
        result_buttons.addWidget(self.result_open_btn)
        result_buttons.addWidget(self.result_folder_btn)
        result_buttons.addStretch(1)
        rb.addLayout(result_buttons)
        self._result_path: Path | None = None
        rv.addWidget(self.result_box)

        download = QGroupBox("Download")
        dl = QVBoxLayout(download)
        dl.setSpacing(8)
        self.format_combo = QComboBox()
        for key, label in FORMAT_LABELS.items():
            self.format_combo.addItem(label, key)
        index = self.format_combo.findData(normalize_format(
            self.prefs["output_format"]))
        self.format_combo.setCurrentIndex(max(0, index))
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("File type"))
        format_row.addWidget(self.format_combo, 1)
        dl.addLayout(format_row)

        format_note = QLabel(
            "MP3 is the best default for sharing and small files.")
        format_note.setObjectName("mutedSmall")
        format_note.setWordWrap(True)
        dl.addWidget(format_note)

        self.go_btn = QPushButton("Generate")
        self.go_btn.setObjectName("primary")
        self.go_btn.clicked.connect(self._on_generate)
        dl.addWidget(self.go_btn)

        open_btn = QPushButton("Open downloads folder")
        open_btn.clicked.connect(lambda: open_path(output_dir(self._project())))
        dl.addWidget(open_btn)
        rv.addWidget(download)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)

        rv.addStretch(1)

        note = QLabel(
            "Effects run after rendering, so the file you hear is the file you "
            "get. Cloned voices need `pip install -r requirements-clone.txt`."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedSmall")
        rv.addWidget(note)
        self.bottom_hint = note

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([740, 480])
        self._update_generate_label()
        return page

    # ---- library tab
    def _build_library_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.lib_table = QTableWidget(0, 7)
        self.lib_table.setHorizontalHeaderLabels(
            ["name", "kind", "rate", "pitch", "volume", "sample", "notes"])
        self.lib_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lib_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lib_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lib_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.lib_table.doubleClicked.connect(self._on_library_double_click)
        layout.addWidget(self.lib_table, 1)

        form = QGridLayout()
        self.vname = QLineEdit()
        self.vname.setPlaceholderText("e.g. narrator-deep")
        self.vnotes = QLineEdit()
        self.vnotes.setPlaceholderText("what this voice is for")
        self.vsample = QLineEdit()
        self.vsample.setPlaceholderText("optional 6–20 s recording of your own voice")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_sample)
        record = QPushButton("Record…")
        record.clicked.connect(self._record_sample)

        form.addWidget(QLabel("Name"), 0, 0)
        form.addWidget(self.vname, 0, 1, 1, 2)
        form.addWidget(QLabel("Notes"), 1, 0)
        form.addWidget(self.vnotes, 1, 1, 1, 2)
        form.addWidget(QLabel("Recording"), 2, 0)
        form.addWidget(self.vsample, 2, 1)
        sample_buttons = QHBoxLayout()
        sample_buttons.addWidget(browse)
        sample_buttons.addWidget(record)
        form.addLayout(sample_buttons, 2, 2)
        layout.addLayout(form)

        row = QHBoxLayout()
        create = QPushButton("Create from current settings")
        create.setObjectName("primary")
        create.clicked.connect(self._create_voice)
        update = QPushButton("Update from current settings")
        update.clicked.connect(self._update_voice)
        attach = QPushButton("Attach recording")
        attach.clicked.connect(self._attach_sample)
        use = QPushButton("Use voice")
        use.clicked.connect(self._use_voice)
        rename = QPushButton("Rename…")
        rename.clicked.connect(self._rename_voice)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete_voice)
        play_sample = QPushButton("Play sample")
        play_sample.clicked.connect(self._play_sample)
        restore = QPushButton("Restore defaults")
        restore.setToolTip("Re-create any of the built-in starter voices you deleted")
        restore.clicked.connect(self._restore_defaults)
        for b in (create, update, attach, use, rename, delete, play_sample, restore):
            row.addWidget(b)
        layout.addLayout(row)

        self.lib_status = QLabel("")
        self.lib_status.setWordWrap(True)
        self.lib_status.setObjectName("muted")
        layout.addWidget(self.lib_status)

        hint = QLabel(
            "Designed = tuned settings, renders instantly. Cloned = settings + a "
            "recording, needs the clone engine. Editing a voice is just "
            "loading it, tuning, then Update."
        )
        hint.setWordWrap(True)
        hint.setObjectName("mutedSmall")
        layout.addWidget(hint)
        self.library_hint = hint
        return page

    # ---- history tab
    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.hist_table = QTableWidget(0, 6)
        self.hist_table.setHorizontalHeaderLabels(
            ["#", "now", "change", "from", "to", "when"])
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.hist_table, 1)

        row1 = QHBoxLayout()
        for label, fn in (
            ("Undo 1", lambda: self._undo(1)),
            ("Undo 5", lambda: self._undo(5)),
            ("Undo all", self._undo_all),
            ("Redo", lambda: self._redo(1)),
            ("Reset to defaults", self._reset),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row1.addWidget(b)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.param_combo = QComboBox()
        self.param_combo.addItems(list(PARAMS))
        revert = QPushButton("Revert this parameter")
        revert.clicked.connect(self._revert_param)
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(0, 9999)
        jump = QPushButton("Jump to snapshot")
        jump.clicked.connect(self._jump)

        row2.addWidget(QLabel("Parameter"))
        row2.addWidget(self.param_combo, 1)
        row2.addWidget(revert)
        row2.addWidget(QLabel("Snapshot"))
        row2.addWidget(self.jump_spin)
        row2.addWidget(jump)
        layout.addLayout(row2)

        self.hist_status = QLabel("")
        self.hist_status.setObjectName("muted")
        layout.addWidget(self.hist_status)
        return page

    # ------------------------------------------------------------- utilities
    def _project(self) -> Project:
        return Project.load(DATA)

    def _busy(self, on: bool) -> None:
        self.go_btn.setEnabled(not on)
        self.go_btn.setText("Rendering…" if on else "")
        preview = getattr(self, "preview_btn", None)
        if preview is not None:
            preview.setEnabled(not on)
            preview.setText("Previewing…" if on else "▶  Quick preview")
        if not on:
            self._update_generate_label()

    # -- live render progress ---------------------------------------------
    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(round(seconds)))
        return f"{seconds // 60}:{seconds % 60:02d}"

    @classmethod
    def _wait_text(cls, seconds: float | None) -> str:
        if seconds is None:
            return "Estimating the wait…"
        if seconds <= 2:
            return "Almost done"
        if seconds < 60:
            return f"About {int(round(seconds))} seconds remaining"
        minutes, secs = divmod(int(round(seconds)), 60)
        if minutes < 60:
            return f"About {minutes} min {secs:02d} s remaining"
        hours, minutes = divmod(minutes, 60)
        return f"About {hours} h {minutes:02d} min remaining"

    def _start_progress(self, label: str) -> None:
        now = time.monotonic()
        self._progress_info = {}
        self._progress_started = now
        self._progress_part_started = now
        self._progress_rate = 0.0
        self._progress_label = label
        self._progress_adapt = ""
        self.progress_box.setVisible(True)
        self.result_box.setVisible(False)
        self._result_path = None
        self.progress_adapt.clear()
        self.progress_adapt.setVisible(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Preparing…")
        self.progress_stats.setText("Preparing the engine and the script…")
        self.progress_eta.setText("Estimating the wait…")
        self.progress_detail.setText(label)
        self._progress_timer.start()

    def _on_render_progress(self, info) -> None:
        if not isinstance(info, dict):
            return
        phase = str(info.get("phase") or "")
        if phase == "adapt":
            message = str(info.get("message") or "").strip()
            if message:
                self._progress_adapt = message
                self.progress_adapt.setText(message)
                self.progress_adapt.setVisible(True)
            return
        now = time.monotonic()
        if phase == "part":
            self._progress_part_started = now
        elif phase == "part_done":
            measured = float(info.get("chars_per_second") or 0.0)
            seconds = float(info.get("seconds") or 0.0)
            chars = int(info.get("part_chars") or 0)
            if measured > 0:
                # Parallel renders report global throughput; that is the
                # honest number for the estimate.
                self._progress_rate = measured
            elif seconds >= 0.4 and chars > 0:
                observed = chars / seconds
                self._progress_rate = (
                    observed if not self._progress_rate
                    else 0.55 * self._progress_rate + 0.45 * observed)
        self._progress_info = info
        self._tick_progress()

    def _tick_progress(self) -> None:
        info = self._progress_info
        if not info:
            return
        phase = str(info.get("phase") or "")
        total = max(1, int(info.get("total_chars") or 1))
        done = min(total, max(0.0, float(info.get("chars_done") or 0)))
        parts = max(1, int(info.get("parts") or 1))
        parts_done = max(0, int(info.get("parts_done") or 0))
        index = int(info.get("index") or 0)
        active = max(0, int(info.get("active") or 0))
        workers = max(1, int(info.get("workers") or 1))
        elapsed = max(0.0, time.monotonic() - self._progress_started)

        measured = float(info.get("chars_per_second") or 0.0)
        rate = measured or self._progress_rate
        if rate <= 0 and done > 0 and elapsed > 0.4:
            rate = done / elapsed
        known_rate = rate > 0
        if rate <= 0:
            rate = 28.0  # chars/second until we learn better

        eta: float | None = None
        detail = ""
        fraction = 0.0

        if phase == "prepare":
            fraction = 0.01
            detail = "Preparing the engine and splitting the script…"
        elif phase == "plan":
            fraction = 0.02
            detail = (f"{parts} part{'s' if parts != 1 else ''} ready · "
                      f"starting {workers} at a time")
        elif phase == "part":
            part_chars = max(1, int(info.get("part_chars") or 1))
            if workers > 1:
                # Several parts are in flight; don't fake progress inside
                # them. Completed characters are the honest signal.
                fraction = min(0.965, (done / total) * 0.97)
                eta = max(0.0, (total - done) / rate + 3.0)
                detail = (f"Part {index} of {parts} started · {active} "
                          f"rendering now · {int(done):,} of {total:,} "
                          "characters done")
            else:
                since = max(0.0, time.monotonic() - self._progress_part_started)
                estimated = min(part_chars * 0.92, since * rate)
                work_done = done + estimated
                fraction = min(0.965, (work_done / total) * 0.97)
                eta = max(0.0, (total - work_done) / rate + 2.0)
                expected = part_chars / rate
                slower = since > max(25.0, expected * 2.2)
                detail = (f"Part {index} of {parts} · {int(done):,} of "
                          f"{total:,} characters done")
                if slower:
                    detail += " · this part is taking longer than estimated"
        elif phase == "part_done":
            fraction = min(0.97, (done / total) * 0.97)
            eta = max(0.0, (total - done) / rate + 3.0)
            detail = (f"Part {index} of {parts} finished · {int(done):,} of "
                      f"{total:,} characters")
        elif phase == "stitch":
            fraction = 0.985
            eta = 3.0
            detail = f"Stitching {parts} parts into one file with a short pause…"
        elif phase == "effects":
            fraction = 0.992
            eta = 2.0
            detail = "Applying the effect chain and finishing the file…"
        elif phase == "done":
            self._finish_progress("One finished file ready.")
            return

        value = max(0, min(1000, int(round(fraction * 1000))))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value / 10:.0f}%")
        waiting = self._wait_text(eta)
        if eta is not None:
            waiting += f" · elapsed {self._clock(elapsed)}"
        self.progress_eta.setText(waiting)
        self.progress_detail.setText(detail)

        stats: list[str] = []
        if parts > 1:
            stats.append(f"{parts_done} of {parts} parts done")
        else:
            stats.append("1 part")
        if active > 1:
            stats.append(f"{active} rendering now")
        stats.append(f"{workers} at a time" if workers > 1 else "one at a time")
        if known_rate:
            stats.append(f"{rate:.0f} chars/s")
        if elapsed >= 1.0:
            stats.append(f"{self._clock(elapsed)} elapsed")
        self.progress_stats.setText(" · ".join(stats))

    def _finish_progress(self, detail: str = "Finished.") -> None:
        self._progress_timer.stop()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.progress_bar.setFormat("100%")
        elapsed = time.monotonic() - self._progress_started
        self.progress_eta.setText(
            f"Finished in {self._clock(elapsed)}" if self._progress_started
            else "Finished")
        if detail:
            self.progress_detail.setText(detail)
        self._progress_info = {}

    def _fail_progress(self, message: str) -> None:
        self._progress_timer.stop()
        self.progress_box.setVisible(True)
        self.result_box.setVisible(False)
        self.progress_bar.setFormat("Stopped")
        self.progress_stats.setText("Stopped")
        elapsed = time.monotonic() - self._progress_started
        self.progress_eta.setText(
            f"Stopped after {self._clock(elapsed)}"
            if self._progress_started else "Stopped")
        self.progress_detail.setText(message)
        self._progress_info = {}

    # -- finished-file card ------------------------------------------------
    @staticmethod
    def _size_text(size: int | float) -> str:
        size = max(0.0, float(size))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @staticmethod
    def _length_text(seconds: float) -> str:
        seconds = max(0, int(round(float(seconds or 0))))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        return (f"{hours}:{minutes:02d}:{secs:02d}" if hours
                else f"{minutes}:{secs:02d}")

    @staticmethod
    def _channels_text(channels: int) -> str:
        return {1: "mono", 2: "stereo"}.get(int(channels or 0),
                                             f"{channels} channels")

    def _show_result(self, path: Path, meta: dict | None = None,
                     preview: bool = False) -> None:
        self._result_path = Path(path)
        values = dict(meta or {})
        try:
            values = {**audio_io.validate_audio(self._result_path), **values}
        except Exception:
            pass
        try:
            fallback_size = self._result_path.stat().st_size
        except OSError:
            fallback_size = 0
        size = values.get("bytes") or fallback_size
        duration = float(values.get("duration") or 0.0)
        rate = int(values.get("sample_rate") or 0)
        channels = int(values.get("channels") or 0)
        fmt = str(values.get("format") or
                  self._result_path.suffix.lstrip(".")).upper()

        self.result_title.setText(
            "Preview ready (not saved)" if preview else "One finished file")
        self.result_name.setText(self._result_path.name)
        self.result_dir.setText(f"In {self._result_path.parent}")
        bits = [fmt, self._size_text(size)]
        if duration > 0:
            bits.append(self._length_text(duration))
        if rate > 0:
            bits.append(f"{rate / 1000:g} kHz")
        if channels > 0:
            bits.append(self._channels_text(channels))
        self.result_meta.setText(" · ".join(bits))
        self.result_open_btn.setEnabled(self._result_path.exists())
        self.result_folder_btn.setEnabled(self._result_path.parent.is_dir())
        self.progress_box.setVisible(False)
        self.result_box.setVisible(True)

    def _open_result_file(self) -> None:
        if self._result_path and self._result_path.exists():
            open_path(self._result_path)

    def _open_result_folder(self) -> None:
        if self._result_path:
            open_path(self._result_path.parent)

    def _guard(self, fn) -> None:
        """Run a state mutation; report failures instead of crashing the app."""
        try:
            fn()
        except Exception as exc:
            QMessageBox.warning(self, "VoiceForge", str(exc))

    # ---------------------------------------------------------- preferences
    def _on_format_changed(self, _index: int = -1) -> None:
        fmt = normalize_format(self.format_combo.currentData())
        self._update_generate_label()
        if self.prefs["output_format"] != fmt:
            self.prefs.update({"output_format": fmt})
            try:
                self.prefs.save()
            except OSError:
                pass

    def _update_generate_label(self) -> None:
        fmt = normalize_format(self.format_combo.currentData())
        self.go_btn.setText(f"Generate {fmt.upper()}")

    def open_settings(self) -> None:
        dialog = SettingsDialog(DATA, self.prefs, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.prefs = Preferences.load(DATA)
        self.volume.setValue(int(self.prefs["player_volume"]))
        index = self.format_combo.findData(
            normalize_format(self.prefs["output_format"]))
        self.format_combo.blockSignals(True)
        self.format_combo.setCurrentIndex(max(0, index))
        self.format_combo.blockSignals(False)
        self._update_generate_label()
        self._apply_hints()
        self._refresh_library()
        self._sync_from_project()
        self._refresh_texts()
        self.status.setText(dialog.summary())

    def _open_help(self) -> None:
        help_dialogs.show_help(self)

    def _open_about(self) -> None:
        if help_dialogs.show_about(self, on_back=self._back_to_launcher):
            self._leave_for_launcher()

    def _back_to_launcher(self) -> bool:
        """Confirm the hand-off; returns False to keep this window open."""
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(
                self, "Back to Launcher",
                "A render is still running. Wait for it to finish, then open "
                "the launcher.")
            return False
        if self.script.toPlainText().strip():
            answer = QMessageBox.question(
                self, "Back to Launcher",
                "Open the VoiceForge launcher and close this window?\n\n"
                "Any unsaved script text will not be reopened automatically. "
                "Save it first if you want to keep it.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return True

    def _leave_for_launcher(self) -> None:
        ok, message = help_content.start_launcher()
        if not ok:
            QMessageBox.warning(self, "Back to Launcher", message)
            return
        self.close()

    def _menu_back_to_launcher(self) -> None:
        if self._back_to_launcher():
            self._leave_for_launcher()

    def restyle(self) -> None:
        app = QApplication.instance()
        if app is not None:
            qt_theme.apply(app, self.prefs["theme"])

    def _apply_hints(self) -> None:
        show = bool(self.prefs["show_hints"])
        for widget in (getattr(self, "bottom_hint", None),
                       getattr(self, "library_hint", None)):
            if widget is not None:
                widget.setVisible(show)

    def _discard_legacy_script(self) -> None:
        """Remove the auto-remembered script file used by older versions.

        Unsaved text is no longer kept. Only a text file the user explicitly
        opens or saves is remembered, which is far less surprising.
        """
        legacy = CACHE / "last-script.txt"
        try:
            if legacy.exists():
                legacy.unlink()
        except OSError:
            pass

    def _text_dir(self) -> Path:
        try:
            folder = self.prefs.text_dir
        except Exception:
            folder = DATA / "texts"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return folder

    def _refresh_texts(self) -> None:
        combo = getattr(self, "text_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        try:
            files = sorted(self._text_dir().glob("*.txt"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            files = []
        if files:
            combo.setEnabled(True)
            for path in files:
                combo.addItem(path.name, str(path))
        else:
            combo.setEnabled(False)
            combo.addItem("No saved text files yet", None)
        combo.blockSignals(False)

    def _remember_text_file(self, path: Path) -> None:
        self._current_text_path = path
        try:
            self.prefs.update({"last_text_file": str(path)})
            self.prefs.save()
        except OSError:
            pass
        index = self.text_combo.findData(str(path))
        if index >= 0:
            self.text_combo.setCurrentIndex(index)

    def _restore_last_text(self) -> None:
        """Reopen the text file the user chose last time, if it still exists."""
        raw = str(self.prefs["last_text_file"] or "").strip()
        if not raw:
            return
        path = Path(raw).expanduser()
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return
        if not text.strip():
            return
        self.script.setPlainText(text)
        self.status.setText(f"Opened your last text: {path.name}")
        self._current_text_path = path
        index = self.text_combo.findData(str(path))
        if index >= 0:
            self.text_combo.setCurrentIndex(index)

    def _open_text_path(self, path: Path) -> None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "VoiceForge",
                                f"Could not read {path}:\n{exc}")
            return
        for encoding in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            self.script.setPlainText(text)
            self.tabs.setCurrentWidget(self.editor_page)
            self.status.setText(f"Opened {path.name}")
            self._remember_text_file(path)
            return
        QMessageBox.warning(self, "VoiceForge",
                            "Could not decode that file as text.")

    def _open_saved_text(self, index: int) -> None:
        if index < 0:
            return
        data = self.text_combo.itemData(index)
        if data:
            self._open_text_path(Path(data))

    def _open_selected_text(self) -> None:
        self._open_saved_text(self.text_combo.currentIndex())

    def _open_text_folder(self) -> None:
        open_path(self._text_dir())

    def _save_window_prefs(self) -> None:
        changed = {}
        if int(self.prefs["player_volume"]) != self.volume.value():
            changed["player_volume"] = self.volume.value()
        if changed:
            self.prefs.update(changed)
            try:
                self.prefs.save()
            except OSError:
                pass

    # -------------------------------------------------------------- values
    def _advanced_values(self) -> dict:
        return {key: self._advanced.get(key, PARAMS[key].default)
                for key in ADVANCED_PARAMS}

    def _set_advanced(self, settings: dict | None) -> None:
        self._advanced = lab_values(settings)
        self._update_advanced_summary()

    def _update_advanced_summary(self) -> None:
        label = getattr(self, "advanced_summary", None)
        if label is None:
            return
        text = describe_effects(self._advanced_values())
        label.setText(f"Voice lab: {text}" if text else
                      "Voice lab: off - the voice is untouched.")

    def _effect_label(self) -> str:
        chain = self.effect_combo.currentText() or "none"
        lab = describe_effects(self._advanced_values())
        if chain in ("", "none"):
            return lab or "no effects"
        return f"{chain} + {lab}" if lab else chain

    def collect_values(self) -> dict:
        values = {
            "rate": f"{int(self.s_rate.value()):+d}%",
            "pitch": f"{int(self.s_pitch.value()):+d}Hz",
            "volume": f"{int(self.s_volume.value()):+d}%",
            "effect": self.effect_combo.currentText() or "none",
            "speed": round(float(self.s_speed.value()), 2),
            "temperature": round(float(self.s_temp.value()), 2),
            "top_k": int(self.s_topk.value()),
            "top_p": round(float(self.s_topp.value()), 2),
            "repetition_penalty": round(float(self.s_rep.value()), 1),
        }
        values.update(self._advanced_values())
        voice = self.edge_edit.text().strip() or PARAMS["voice"].default
        values["voice"] = voice

        name = self.lib_combo.currentText()
        reference = ""
        if name and name != NONE and library.audio_in(DATA, name):
            reference = name
        values["reference"] = reference
        return values

    def _capture_settings(self, label: str) -> dict:
        """Persist what the sliders show before saving a voice.

        Sliders are a preview; the project only stores what was generated. Without
        this, Create/Update would save the previous render's settings.
        """
        project = self._project()
        project.apply_settings(self.collect_values(), label=label)
        return dict(project.settings)

    def _sync_from_project(self) -> None:
        self._load_profile_into_sliders(self._project().settings)

    def _refresh_all(self) -> None:
        self._refresh_library()
        self._refresh_history()
        self._sync_from_project()
        self.status.setText("Refreshed.")

    # ------------------------------------------------------------ selection
    def _selected_voice(self) -> str:
        row = self.lib_table.currentRow()
        if row >= 0:
            item = self.lib_table.item(row, 0)
            if item:
                return item.text()
        name = self.lib_combo.currentText()
        return "" if name == NONE else name

    def _load_profile_into_sliders(self, settings: dict) -> None:
        self._loading = True
        self.s_rate.set_value(_read_int(settings.get("rate")))
        self.s_pitch.set_value(_read_int(settings.get("pitch")))
        self.s_volume.set_value(_read_int(settings.get("volume")))
        self.s_speed.set_value(float(settings.get("speed", 1.0)))
        self.s_temp.set_value(float(settings.get("temperature", 0.75)))
        self.s_topk.set_value(int(settings.get("top_k", 50)))
        self.s_topp.set_value(float(settings.get("top_p", 0.85)))
        self.s_rep.set_value(float(settings.get("repetition_penalty", 5.0)))
        idx = self.effect_combo.findText(settings.get("effect", "none"))
        if idx >= 0:
            self.effect_combo.setCurrentIndex(idx)
        self.edge_edit.setText(
            str(settings.get("voice") or PARAMS["voice"].default))
        self._set_advanced(settings)
        self._loading = False

    # ---------------------------------------------------------------- script
    def _update_plan(self) -> None:
        text = self.script.toPlainText()
        info = speech_plan(text)
        self.plan_label.setText(
            info.describe() if info.characters else "Empty script")
        summary = getattr(self, "script_summary", None)
        if summary is None:
            return
        if not info.characters:
            summary.setText(
                "No script yet. Open the Script tab to paste or type one.")
            return
        preview = " ".join(text.split())
        if len(preview) > 180:
            preview = preview[:180].rstrip() + "…"
        summary.setText(f"{info.describe()}\n\n“{preview}”")

    def _paste_script(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            return
        cursor = self.script.textCursor()
        if cursor.hasSelection():
            cursor.insertText(text)
        else:
            self.script.insertPlainText(text)
        self.script.setFocus()

    def script_clear(self) -> None:
        self.script.clear()
        self.script.setFocus()
        self._current_text_path = None
        self.status.setText(
            "Cleared. Your saved text files are untouched.")
        # Forget which file was open, so an empty editor stays empty next launch.
        try:
            self.prefs.update({"last_text_file": ""})
            self.prefs.save()
        except OSError:
            pass

    def _load_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a text file", str(self._text_dir()),
            "Text (*.txt *.md *.srt *.csv);;All files (*.*)")
        if path:
            self._open_text_path(Path(path))

    @staticmethod
    def _suggest_text_name(text: str) -> str:
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        words = " ".join(first_line.split())[:48]
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", words)
        safe = re.sub(r"\s+", " ", safe).strip(" .")
        return safe or f"text-{datetime.now():%Y%m%d-%H%M%S}"

    @staticmethod
    def _safe_text_name(name: str) -> str:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", name or "")
        clean = re.sub(r"\s+", " ", clean).strip(" .")
        if clean.lower().endswith(".txt"):
            clean = clean[:-4].strip()
        return (clean or f"text-{datetime.now():%Y%m%d-%H%M%S}") + ".txt"

    def _save_script(self) -> None:
        text = self.script.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "VoiceForge",
                                    "There is nothing to save yet.")
            return
        current = self._current_text_path
        suggested = current.stem if current else self._suggest_text_name(text)
        name, accepted = QInputDialog.getText(
            self, "Save text",
            "Name this text (it is saved in your Text folder).\n"
            "Leave it empty to keep the current name:",
            text=suggested)
        if not accepted:
            return
        if name.strip():
            target = self._text_dir() / self._safe_text_name(name)
        elif current is not None:
            # A blank name on an open file means "save over this file".
            target = current
        else:
            target = self._text_dir() / self._safe_text_name(suggested)
        if target.exists() and target != current:
            answer = QMessageBox.question(
                self, "Replace text?",
                f"“{target.name}” already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._refresh_texts()
        self._remember_text_file(target)
        self.status.setText(f"Saved “{target.name}” to {target.parent}")

    # --------------------------------------------------------------- speak
    def _on_style(self, name: str) -> None:
        if self._loading:
            return
        try:
            st = styles.get(name)
        except styles.StyleError:
            return
        merged = dict(self._project().settings)
        for key in ADVANCED_PARAMS:
            merged[key] = PARAMS[key].default
        merged.update(st.params)
        merged["effect"] = st.effect
        self._load_profile_into_sliders(merged)
        self.status.setText(f"Style “{st.name}” loaded - {st.description}")

    def _on_library_voice(self, name: str) -> None:
        if self._loading or not name or name == NONE:
            return
        try:
            prof = library.load(DATA, name)
        except library.LibraryError as exc:
            self.status.setText(str(exc))
            return
        merged = dict(self._project().settings)
        for key in ADVANCED_PARAMS:
            merged[key] = PARAMS[key].default
        merged.update(prof.settings)
        self._load_profile_into_sliders(merged)
        kind = "cloned" if library.audio_in(DATA, name) else "designed"
        self.status.setText(f"Loaded “{name}” ({kind}).")

    def _open_advanced(self) -> None:
        dialog = AdvancedEffectsDialog(self._advanced_values(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._advanced = dialog.values()
        self._update_advanced_summary()
        self.status.setText(
            f"Voice lab applied: {describe_effects(self._advanced_values())}. "
            "Preview it or Generate to keep it.")
        if dialog.apply_and_preview:
            self._on_preview()

    def _voice_names(self) -> list[str]:
        model = self._edge_completer.model()
        names = model.stringList() if isinstance(model, QStringListModel) else []
        return list(names) or list(FALLBACK_VOICES)

    def _update_voice_hint(self) -> None:
        hint = getattr(self, "voice_hint", None)
        if hint is None:
            return
        short = self.edge_edit.text().strip()
        if not short:
            hint.setText(
                "No voice chosen yet - the default male voice is used "
                f"({PARAMS['voice'].default}).")
            return
        choice = voice_choices.describe(short)
        note = f" · {choice.note}" if choice.note else ""
        known = cached_voices()
        missing = bool(known) and short not in known
        hint.setText(
            f"Current: {choice.name} · {choice.gender} · {choice.locale}{note}"
            + ("  ·  not in the last fetched list - refresh it or pick a "
               "quick voice" if missing else ""))

    def _use_edge_voice(self, short: str) -> None:
        short = (short or "").strip()
        if not short:
            return
        self.edge_edit.setText(short)
        self._update_voice_hint()
        choice = voice_choices.describe(short)
        self.status.setText(f"Voice set to {choice.label}.")

    def _pick_edge_voice(self, mode: str = "All") -> None:
        dialog = VoicePickerDialog(
            self.edge_edit.text().strip(), self._voice_names(), self, mode=mode)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._use_edge_voice(dialog.selected_short())

    def _on_generate(self) -> None:
        text = self.script.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "VoiceForge", "Paste a script first.")
            self.tabs.setCurrentWidget(self.editor_page)
            return
        if self.render_worker and self.render_worker.isRunning():
            return

        self.tabs.setCurrentWidget(self.speak_page)
        info = speech_plan(text)
        project = self._project()
        values = self.collect_values()
        project.apply_settings(values, label="generate")

        engine = "clone" if values.get("reference") else "edge"
        self._busy(True)
        self._start_progress(
            f"Rendering with the {engine} engine · {info.chunks} part"
            + ("s" if info.chunks != 1 else ""))
        if info.chunks > 1:
            self.status.setText(
                f"Rendering {info.chunks} parts with the {engine} engine… "
                "They are stitched into one finished file when done.")
        else:
            self.status.setText(f"Rendering with the {engine} engine…")
        worker = Worker(
            lambda: render_text(
                project, text,
                output_format=self.format_combo.currentData(),
                progress=worker.progress.emit),
            self)
        worker.done.connect(self._on_rendered)
        worker.failed.connect(self._on_render_failed)
        worker.progress.connect(self._on_render_progress)
        self.render_worker = worker
        self.render_worker.start()
        self._refresh_history()

    def _on_preview(self) -> None:
        """Render a short excerpt and play it without touching downloads."""
        text = self.script.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "VoiceForge",
                                    "Paste a script on the Script tab first.")
            self.tabs.setCurrentWidget(self.editor_page)
            return
        if self.render_worker and self.render_worker.isRunning():
            return

        excerpt = preview_excerpt(text)
        project = self._project()
        values = self.collect_values()
        try:
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            for old in PREVIEW_DIR.glob("preview-*"):
                try:
                    old.unlink()
                except OSError:
                    pass
        except OSError:
            pass
        target = PREVIEW_DIR / f"preview-{datetime.now():%H%M%S}.wav"

        self._busy(True)
        self._start_progress("Quick preview · first lines with the current voice")
        self.status.setText(
            "Building a quick preview with the current voice and effects…")
        worker = Worker(
            lambda: render_text(
                project, excerpt, out=target, overrides=values,
                output_format="wav", progress=worker.progress.emit),
            self)
        worker.done.connect(self._on_previewed)
        worker.failed.connect(self._on_render_failed)
        worker.progress.connect(self._on_render_progress)
        self.render_worker = worker
        self.render_worker.start()

    def _on_previewed(self, result) -> None:
        self._busy(False)
        path, engine = result
        meta = dict(getattr(result, "meta", {}) or {})
        self.current_path = Path(path)
        self._finish_progress(
            "Preview ready and playing. Nothing was saved to downloads.")
        self._show_result(self.current_path, meta, preview=True)
        self.player.setSource(QUrl.fromLocalFile(str(self.current_path)))
        for b in (self.play_btn, self.stop_btn, self.show_btn):
            b.setEnabled(True)
        self.seek.setEnabled(True)
        self.status.setText(
            f"Preview ready with {engine} + "
            f"“{self._effect_label()}” · press Play to hear it "
            "again, or Generate to save the full file in your chosen format.")
        self.player.play()

    def _on_rendered(self, result) -> None:
        self._busy(False)
        path, engine = result
        meta = dict(getattr(result, "meta", {}) or {})
        self.current_path = Path(path)
        self.player.setSource(QUrl.fromLocalFile(str(self.current_path)))
        for b in (self.play_btn, self.stop_btn, self.show_btn):
            b.setEnabled(True)
        self.seek.setEnabled(True)
        size = int(meta.get("bytes") or self.current_path.stat().st_size)
        duration = float(meta.get("duration") or 0.0)
        try:
            shown = self.current_path.relative_to(DATA)
        except ValueError:
            shown = self.current_path
        self._finish_progress(f"One finished file · {shown}")
        self._show_result(self.current_path, meta)
        length = f"  ·  {self._length_text(duration)}" if duration else ""
        self.status.setText(
            f"Rendered with {engine} + “{self._effect_label()}”"
            f"  ·  {self._size_text(size)}{length}\n{shown}")
        if self.prefs["autoplay_after_render"]:
            self.player.play()

    def _on_render_failed(self, message: str) -> None:
        self._busy(False)
        self._fail_progress(message)
        self.status.setText(f"Could not render: {message}")
        QMessageBox.warning(self, "Render failed", message)

    # ----------------------------------------------------------- playback
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop(self) -> None:
        self.player.stop()
        self.seek.setValue(0)
        self.time_label.setText(f"00:00 / {self._fmt(self.player.duration())}")

    def _open_current(self) -> None:
        if self.current_path and self.current_path.exists():
            open_path(self.current_path)

    def _seek_start(self) -> None:
        self._seeking = True

    def _seek_end(self) -> None:
        self._seeking = False
        self.player.setPosition(self.seek.value())

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸  Pause" if playing else "▶  Play")

    def _on_position(self, ms: int) -> None:
        self.time_label.setText(f"{self._fmt(ms)} / {self._fmt(self.player.duration())}")
        if not self._seeking and self.seek.isEnabled():
            self.seek.blockSignals(True)
            self.seek.setValue(int(ms))
            self.seek.blockSignals(False)

    def _on_duration(self, ms: int) -> None:
        self.time_label.setText(f"{self._fmt(self.player.position())} / {self._fmt(ms)}")
        self.seek.blockSignals(True)
        self.seek.setRange(0, max(0, int(ms)))
        self.seek.blockSignals(False)
        self.seek.setEnabled(ms > 0)

    @staticmethod
    def _fmt(ms: int) -> str:
        seconds = max(0, int(ms // 1000))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    # ------------------------------------------------------------ library
    def _refresh_library(self) -> None:
        rows = library.listing(DATA)
        self.lib_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (row["name"], row["kind"], row["rate"], row["pitch"],
                      row["volume"], row["audio"], row["notes"])
            for c, value in enumerate(values):
                self.lib_table.setItem(r, c, QTableWidgetItem(str(value)))

        current = self.lib_combo.currentText()
        self._loading = True
        self.lib_combo.clear()
        self.lib_combo.addItem(NONE)
        self.lib_combo.addItems([row["name"] for row in rows])
        idx = self.lib_combo.findText(current)
        self.lib_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading = False

    def _refresh_history(self) -> None:
        rows = self._project().history.describe()
        self.hist_table.setRowCount(len(rows))
        current_brush = QBrush(QColor(qt_theme.ACCENT_SOFT))
        for r, row in enumerate(rows):
            values = (row["index"], ">" if row["current"] else "", row["label"],
                      row["old"], row["new"], row["at"])
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row["current"]:
                    item.setBackground(current_brush)
                self.hist_table.setItem(r, c, item)
        self.hist_table.scrollToBottom()

    def _pick_sample(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a reference recording", str(Path.home()),
            "Audio (*.wav *.mp3 *.flac *.m4a *.ogg)")
        if path:
            self.vsample.setText(path)

    def _record_sample(self) -> None:
        dialog = RecorderDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.path:
            self.vsample.setText(str(dialog.path))
            self.lib_status.setText(
                f"Recorded {dialog.path.name}. Now choose a voice and press "
                "Attach recording, or name a new voice and press Create.")
            self.tabs.setCurrentIndex(1)

    def _create_voice(self) -> None:
        name = self.vname.text().strip()
        if not name:
            QMessageBox.information(self, "VoiceForge", "Give the voice a name first.")
            return
        if library.folder(DATA, name).exists():
            confirm = QMessageBox.question(
                self, "Overwrite voice",
                f"“{name}” already exists. Replace its settings with the current ones?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return

        def action() -> None:
            settings = self._capture_settings("create voice")
            prof = library.create(DATA, name, settings,
                                  notes=self.vnotes.text().strip(), overwrite=True)
            sample = self.vsample.text().strip()
            if sample:
                library.attach_sample(DATA, prof.name, Path(sample))
            self._refresh_library()
            self._refresh_history()
            self.lib_combo.setCurrentText(prof.name)
            kind = "cloned" if library.audio_in(DATA, prof.name) else "designed"
            self.lib_status.setText(f"Saved “{prof.name}” ({kind}).")

        self._guard(action)

    def _update_voice(self) -> None:
        name = self._selected_voice()
        if not name:
            self.lib_status.setText("Select a voice in the table first.")
            return

        def action() -> None:
            notes = self.vnotes.text().strip()
            settings = self._capture_settings("update voice")
            library.update(DATA, name, settings,
                           notes=notes if notes else None)
            self._refresh_library()
            self._refresh_history()
            self.lib_status.setText(f"“{name}” now uses the current settings.")

        self._guard(action)

    def _attach_sample(self) -> None:
        name = self._selected_voice()
        path = self.vsample.text().strip()

        def action() -> None:
            if not name:
                raise ValueError("Select a voice in the table first.")
            if not path:
                raise ValueError("Choose or record a sample first.")
            dest = library.attach_sample(DATA, name, Path(path))
            self._refresh_library()
            self.lib_status.setText(f"Attached {dest.name} to “{name}” - now cloneable.")

        self._guard(action)

    def _use_voice(self) -> None:
        name = self._selected_voice()
        if not name:
            return

        def action() -> None:
            prof = library.load(DATA, name)
            project = self._project()
            pairs = [f"{k}={v}" for k, v in prof.settings.items() if k in PARAMS]
            if pairs:
                project.set_many(pairs, label=f"use voice {prof.name}")
            has_audio = library.audio_in(DATA, prof.name) is not None
            project.set_many([f"reference={prof.name if has_audio else ''}"],
                             label=f"use voice {prof.name}")
            self._sync_from_project()
            self._refresh_history()
            self.lib_status.setText(f"Active voice: {prof.name} ({prof.kind}).")

        self._guard(action)

    def _rename_voice(self) -> None:
        name = self._selected_voice()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Rename voice", "New name:", text=name)
        if not ok or not new.strip():
            return

        def action() -> None:
            prof = library.rename(DATA, name, new.strip())
            project = self._project()
            if project.settings.get("reference") == library.slug(name):
                project.set_many([f"reference={prof.name}"], label="rename voice")
            self._refresh_library()
            self.lib_status.setText(f"Renamed to “{prof.name}”.")

        self._guard(action)

    def _delete_voice(self) -> None:
        name = self._selected_voice()
        if not name:
            return
        if self.prefs["confirm_delete"]:
            confirm = QMessageBox.question(
                self, "Delete voice",
                f"Delete “{name}” and its recording? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return

        def action() -> None:
            project = self._project()
            if project.settings.get("reference") == library.slug(name):
                project.apply_settings({"reference": ""}, label="delete voice")
            library.delete(DATA, name)
            self._refresh_library()
            self.lib_status.setText(f"Deleted “{name}”.")

        self._guard(action)

    def _play_sample(self) -> None:
        name = self._selected_voice()
        if not name:
            return
        audio = library.audio_in(DATA, name)
        if not audio:
            self.lib_status.setText("That voice has no recording.")
            return
        self.current_path = audio
        self.player.setSource(QUrl.fromLocalFile(str(audio)))
        for b in (self.play_btn, self.stop_btn, self.show_btn):
            b.setEnabled(True)
        self.player.play()
        self.lib_status.setText(f"Playing {audio.name}.")

    def _on_library_double_click(self, _index) -> None:
        name = self._selected_voice()
        if name:
            self.lib_combo.setCurrentText(name)

    def _restore_defaults(self) -> None:
        def action() -> None:
            created = seed.restore(DATA)
            self._refresh_library()
            self.lib_status.setText(
                f"Restored {len(created)} default voice(s)." if created
                else "All default voices are already present.")

        self._guard(action)

    # ------------------------------------------------------------ history
    def _after_history(self, message: str) -> None:
        self._refresh_history()
        self._sync_from_project()
        self.hist_status.setText(message)

    def _undo(self, steps: int) -> None:
        def action() -> None:
            project = self._project()
            cursor = project.history.undo(steps=steps)
            project.save()
            self._after_history(f"Stepped back {steps}. Now at snapshot {cursor}.")

        self._guard(action)

    def _redo(self, steps: int) -> None:
        def action() -> None:
            project = self._project()
            cursor = project.history.redo(steps=steps)
            project.save()
            self._after_history(f"Stepped forward {steps}. Now at snapshot {cursor}.")

        self._guard(action)

    def _undo_all(self) -> None:
        def action() -> None:
            project = self._project()
            project.history.undo_to(0)
            project.save()
            self._after_history("Back to the initial state.")

        self._guard(action)

    def _jump(self) -> None:
        def action() -> None:
            project = self._project()
            cursor = project.history.undo_to(int(self.jump_spin.value()))
            project.save()
            self._after_history(f"Jumped to snapshot {cursor}.")

        self._guard(action)

    def _revert_param(self) -> None:
        name = self.param_combo.currentText()

        def action() -> None:
            project = self._project()
            value = project.history.undo_param(name)
            project.save()
            self._after_history(f"Reverted {name} to {value}.")

        self._guard(action)

    def _reset(self) -> None:
        def action() -> None:
            self._project().reset_all()
            self._after_history("All settings reset to defaults.")

        self._guard(action)

    # ------------------------------------------------------------- misc
    def _refresh_edge_voices(self) -> None:
        if self.voice_worker and self.voice_worker.isRunning():
            return
        self.status.setText("Fetching the Microsoft voice list…")
        self.voice_worker = Worker(fetch_voices, self)
        self.voice_worker.done.connect(self._on_voices)
        self.voice_worker.failed.connect(
            lambda msg: self.status.setText(f"Voice list unavailable: {msg}"))
        self.voice_worker.start()

    def _on_voices(self, names) -> None:
        if not names:
            self.status.setText("The voice service returned an empty list.")
            return
        names = list(names)
        self._edge_completer.setModel(QStringListModel(names, self))
        self._edge_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._edge_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        if not self.edge_edit.text().strip():
            self.edge_edit.setText(PARAMS["voice"].default)
        self.status.setText(f"Voice list refreshed - {len(names)} voices.")

    def _launch_web_ui(self) -> None:
        try:
            subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=str(ROOT),
                             env=vf_env.clean_env(ROOT, DATA))
            self.status.setText("Browser UI starting on http://127.0.0.1:7860")
        except Exception as exc:
            QMessageBox.warning(self, "VoiceForge", str(exc))

    def _restore_geometry(self) -> None:
        geo = QSettings("VoiceForge", "Desktop").value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def _wait_for_workers(self) -> bool:
        for worker in (self.render_worker, self.voice_worker):
            if worker and worker.isRunning() and not worker.wait(5000):
                return False
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._wait_for_workers():
            QMessageBox.information(
                self, "Still working",
                "A render or voice fetch is still running. Give it a few seconds "
                "and close again.")
            event.ignore()
            return
        QSettings("VoiceForge", "Desktop").setValue("geometry", self.saveGeometry())
        self._save_window_prefs()
        self.player.stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VoiceForge")
    app.setApplicationDisplayName("VoiceForge")
    icon = branding.qicon()
    if icon is not None and not icon.isNull():
        app.setWindowIcon(icon)
    prefs = Preferences.load(DATA)
    qt_theme.apply(app, prefs["theme"])
    window = MainWindow()
    if prefs["start_maximized"]:
        window.showMaximized()
    else:
        window.show()
    if "--self-test" in sys.argv:
        QTimer.singleShot(300, app.quit)
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        CACHE.mkdir(parents=True, exist_ok=True)
        LOG.write_text(traceback.format_exc(), encoding="utf-8")
        raise
