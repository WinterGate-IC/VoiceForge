"""VoiceForge Setup - the Qt installer window.

Three ways in, one engine:

    Install now     defaults, no questions
    Customise       choose folders, shortcuts, optional front-ends
    Auto install    express defaults + Desktop shortcut, one click

The actual copying, venv creation, pip run and shortcut writing live in
``installer_core`` and run on a worker thread so the window keeps painting.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from . import branding
from . import env as vf_env
from . import installer_core as core
from . import qt_theme

WELCOME, OPTIONS, PROGRESS, FINISH, FAILED = range(5)


class InstallWorker(QThread):
    progress = Signal(int, str)
    line = Signal(str)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, plan: core.InstallPlan, parent=None) -> None:
        super().__init__(parent)
        self.plan = plan
        plan.log = self.line.emit
        plan.progress = self.progress.emit

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            result = core.install(self.plan)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(result)


class Installer(QDialog):
    def __init__(self, app_dir: Path | None = None,
                 data_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VoiceForge Setup")
        self.setMinimumSize(920, 640)
        self.resize(1020, 740)
        self.config: dict | None = None
        self.worker: InstallWorker | None = None
        self._close_when_done = False

        self.app_dir = Path(app_dir or core.default_app_dir())
        self.data_dir = Path(data_dir or core.default_data_dir())
        self.bundled = (core.payload_archive() is not None
                        or (core.source_root() / core.RUNTIME_DIR).is_dir())

        self.setWindowIcon(self._make_window_icon())
        self._build()
        self._show(WELCOME)

    # ------------------------------------------------------------- utilities
    def _make_window_icon(self) -> QIcon:
        self._icon_dir: Path | None = None
        self._icon_png: Path | None = branding.icon_png(512)
        icon = branding.qicon()
        if icon is not None and not icon.isNull():
            return icon
        try:
            self._icon_dir = Path(tempfile.mkdtemp(prefix="voiceforge-icon-"))
            _ico, png = core.install_icon(self._icon_dir)
            self._icon_png = png
            return QIcon(str(png))
        except Exception:
            return QIcon()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("installerHeader")
        head = QHBoxLayout(self.header)
        head.setContentsMargins(24, 18, 24, 18)
        self.header_title = QLabel("VoiceForge")
        self.header_title.setObjectName("installerTitle")
        self.header_sub = QLabel("Local text to speech with voices you own")
        self.header_sub.setObjectName("muted")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.header_title)
        titles.addWidget(self.header_sub)
        head.addLayout(titles)
        head.addStretch(1)
        self.header_badge = QLabel(f"Setup {core.VERSION}")
        self.header_badge.setObjectName("pill")
        head.addWidget(self.header_badge)
        outer.addWidget(self.header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_options())
        self.stack.addWidget(self._page_progress())
        self.stack.addWidget(self._page_finish())
        self.stack.addWidget(self._page_failed())
        outer.addWidget(self.stack, 1)

        footer = QFrame()
        footer.setObjectName("installerFooter")
        bar = QHBoxLayout(footer)
        bar.setContentsMargins(24, 12, 24, 12)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        bar.addWidget(self.status, 1)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton("Continue")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self._next)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        bar.addWidget(self.back_btn)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.next_btn)
        self.footer = footer
        outer.addWidget(footer)

    # --------------------------------------------------------------- pages
    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 26, 32, 22)
        layout.setSpacing(14)

        hero = QHBoxLayout()
        icon = QLabel()
        try:
            png = self._icon_png
            pixmap = QPixmap(str(png)) if png else QPixmap()
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(
                    92, 92, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        hero.addWidget(icon)

        words = QVBoxLayout()
        title = QLabel("Install VoiceForge")
        title.setObjectName("installerHero")
        blurb = QLabel(
            "A desktop app that turns any amount of text into MP3 audio, using "
            "voices you create, tune and keep. No account, no cloud library, "
            "no telemetry.")
        blurb.setWordWrap(True)
        blurb.setObjectName("subtitle")
        if self.bundled:
            blurb.setText(
                "A complete offline edition: the app, its Python runtime and "
                "all four front-ends are inside this Setup file. No downloads, "
                "no account, no telemetry.")
        words.addWidget(title)
        words.addWidget(blurb)
        hero.addLayout(words, 1)
        layout.addLayout(hero)

        points = QGridLayout()
        points.setHorizontalSpacing(18)
        points.setVerticalSpacing(10)
        entries = (
            ("Native app", "PySide6 window with a built-in player and undo."),
            ("Your voices", "Profiles live in a folder you can back up."),
            ("MP3 output", "Small files that play on any device."),
            ("Works offline", "Only the voice service needs the network."),
            ("Four front-ends", "Native, browser, desktop window and Flet."),
            ("Per-user install", "No administrator password needed."),
        )
        for index, (heading, text) in enumerate(entries):
            cell = QFrame()
            cell.setObjectName("card")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(12, 8, 12, 8)
            cell_layout.setSpacing(2)
            label = QLabel(heading)
            label.setObjectName("heading")
            detail = QLabel(text)
            detail.setWordWrap(True)
            detail.setObjectName("mutedSmall")
            cell_layout.addWidget(label)
            cell_layout.addWidget(detail)
            points.addWidget(cell, index // 3, index % 3)
        for column in range(3):
            points.setColumnStretch(column, 1)
        layout.addLayout(points)

        self.welcome_paths = QLabel()
        self.welcome_paths.setWordWrap(True)
        self.welcome_paths.setObjectName("hint")
        layout.addWidget(self.welcome_paths)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        auto = QPushButton("Auto install")
        auto.setToolTip(
            "Install to the recommended folders and put VoiceForge on the "
            "Desktop, with no questions asked.")
        auto.clicked.connect(self._auto_install)
        custom = QPushButton("Customise…")
        custom.clicked.connect(lambda: self._show(OPTIONS))
        express = QPushButton("Install now")
        express.setObjectName("primary")
        express.clicked.connect(self._express_install)
        buttons.addWidget(auto)
        buttons.addWidget(custom)
        buttons.addStretch(1)
        buttons.addWidget(express)
        layout.addLayout(buttons)
        return page

    def _folder_row(self, grid: QGridLayout, row: int, label: str,
                    blurb: str, value: Path, browse) -> QLineEdit:
        title = QLabel(label)
        title.setObjectName("heading")
        detail = QLabel(blurb)
        detail.setObjectName("mutedSmall")
        detail.setWordWrap(True)

        edit = QLineEdit(str(value))
        edit.setClearButtonEnabled(False)
        button = QPushButton("Browse…")
        button.clicked.connect(lambda: browse(edit))

        grid.addWidget(title, row, 0)
        grid.addWidget(edit, row, 1)
        grid.addWidget(button, row, 2)
        grid.addWidget(detail, row + 1, 1, 1, 2)
        return edit

    def _page_options(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 20, 32, 16)
        layout.setSpacing(14)

        title = QLabel("Where should it go?")
        title.setObjectName("installerHero")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self.opt_app = self._folder_row(
            grid, 0, "Program folder",
            "The app itself and its private Python environment.",
            self.app_dir, self._browse_app)
        self.opt_data = self._folder_row(
            grid, 2, "Library folder",
            "Your voices, recordings, renders and undo history. This survives "
            "reinstalls, and you can move it later in Settings.",
            self.data_dir, self._browse_data)
        layout.addLayout(grid)

        options = QFrame()
        options.setObjectName("card")
        opts = QVBoxLayout(options)
        opts.setContentsMargins(14, 10, 14, 10)
        opts.setSpacing(6)
        label = QLabel("Shortcuts")
        label.setObjectName("heading")
        opts.addWidget(label)
        self.opt_desktop = QCheckBox("Put VoiceForge on the Desktop")
        self.opt_desktop.setChecked(True)
        self.opt_start = QCheckBox(
            f"Add to the {'Start Menu' if core.IS_WINDOWS else 'applications menu'}")
        self.opt_start.setChecked(True)
        self.opt_extras = QCheckBox(
            "Also install the browser, desktop-window and Flet front-ends")
        self.opt_extras.setChecked(False)
        self.opt_extras.setToolTip(
            "Adds Gradio, pywebview and Flet - roughly another 250 MB. The "
            "launcher can install them later if you skip this.")
        if self.bundled:
            self.opt_extras.setChecked(True)
            self.opt_extras.setText(
                "All four front-ends are included in this release")
            self.opt_extras.setEnabled(False)
            self.opt_extras.setToolTip(
                "This offline edition already contains Native, Browser, "
                "Desktop Window and Flet.")
        for box in (self.opt_desktop, self.opt_start, self.opt_extras):
            opts.addWidget(box)

        name_row = QHBoxLayout()
        name_label = QLabel("Shortcut name")
        name_label.setObjectName("muted")
        self.opt_name = QLineEdit(core.APP_NAME)
        self.opt_name.setMaximumWidth(260)
        name_row.addWidget(name_label)
        name_row.addWidget(self.opt_name)
        name_row.addStretch(1)
        opts.addLayout(name_row)
        layout.addWidget(options)

        perms = QHBoxLayout()
        self.perms_label = QLabel(
            "Per-user install - no administrator rights are needed.")
        self.perms_label.setWordWrap(True)
        self.perms_label.setObjectName("mutedSmall")
        check = QPushButton("Grant folder permissions")
        check.setToolTip(
            "Create the folders if needed and verify they are writable.")
        check.clicked.connect(self._check_permissions)
        perms.addWidget(self.perms_label, 1)
        perms.addWidget(check)
        layout.addLayout(perms)

        self.options_summary = QLabel("")
        self.options_summary.setWordWrap(True)
        self.options_summary.setObjectName("hint")
        layout.addWidget(self.options_summary)
        layout.addStretch(1)
        return page

    def _page_progress(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 20)
        layout.setSpacing(12)

        self.progress_title = QLabel("Installing VoiceForge")
        self.progress_title.setObjectName("installerHero")
        self.progress_text = QLabel("Preparing…")
        self.progress_text.setObjectName("subtitle")
        self.progress_text.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace;")
        self.log.setPlaceholderText("Install log")
        layout.addWidget(self.progress_title)
        layout.addWidget(self.progress_text)
        layout.addWidget(self.bar)
        layout.addWidget(self.log, 1)
        return page

    def _page_finish(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 40, 32, 30)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        mark = QLabel("✓")
        mark.setObjectName("finishMark")
        title = QLabel("VoiceForge is installed")
        title.setObjectName("installerHero")
        self.finish_text = QLabel("")
        self.finish_text.setWordWrap(True)
        self.finish_text.setObjectName("subtitle")
        self.open_box = QCheckBox("Open VoiceForge now")
        self.open_box.setChecked(True)
        self.open_library = QCheckBox("Open the library folder")
        self.open_library.setChecked(False)
        layout.addWidget(mark)
        layout.addWidget(title)
        layout.addWidget(self.finish_text)
        layout.addWidget(self.open_box)
        layout.addWidget(self.open_library)
        layout.addStretch(1)
        return page

    def _page_failed(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 24)
        layout.setSpacing(12)
        title = QLabel("The install did not finish")
        title.setObjectName("installerHero")
        self.failed_text = QLabel("")
        self.failed_text.setWordWrap(True)
        self.failed_text.setObjectName("subtitle")
        self.failed_log = QPlainTextEdit()
        self.failed_log.setReadOnly(True)
        self.failed_log.setStyleSheet(
            "font-family: Consolas, 'DejaVu Sans Mono', monospace;")
        layout.addWidget(title)
        layout.addWidget(self.failed_text)
        layout.addWidget(self.failed_log, 1)
        return page

    # ------------------------------------------------------------- navigation
    def _show(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.back_btn.setVisible(page == OPTIONS)
        self.next_btn.setVisible(page in (OPTIONS,))
        self.cancel_btn.setVisible(page in (WELCOME, OPTIONS, FINISH, FAILED))
        self.cancel_btn.setText("Close" if page == FINISH else "Cancel")
        self.next_btn.setText("Install")
        if page == WELCOME:
            self.status.setText(
                "This is the complete offline edition - no downloads needed."
                if self.bundled else
                "Tip: Auto install uses the recommended folders and a "
                "Desktop shortcut.")
            self.welcome_paths.setText(
                f"Program: {self.app_dir}\nLibrary: {self.data_dir}")
        elif page == OPTIONS:
            self.status.setText(
                "Everything needed is inside this Setup file."
                if self.bundled else
                "Nothing is downloaded until you press Install.")
            self._update_options_summary()
        elif page == PROGRESS:
            self.status.setText("You can close this window when it finishes.")
        elif page == FINISH:
            self.status.setText("Installed for the current user.")
        elif page == FAILED:
            self.status.setText("The log above is the full story.")
        self.header_badge.setText(
            "Installing…" if page == PROGRESS else f"Setup {core.VERSION}")

    def _back(self) -> None:
        self._show(WELCOME if self.stack.currentIndex() == OPTIONS else WELCOME)

    def _next(self) -> None:
        if self.stack.currentIndex() == OPTIONS:
            self._start_install(self._plan_from_options())

    def _browse_app(self, edit: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the program folder", str(self.app_dir))
        if chosen:
            edit.setText(os.path.join(chosen, core.APP_NAME))

    def _browse_data(self, edit: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the library folder", str(self.data_dir))
        if chosen:
            edit.setText(chosen)

    def _update_options_summary(self) -> None:
        try:
            app = Path(self.opt_app.text()).expanduser()
            data = Path(self.opt_data.text()).expanduser()
            if self.bundled:
                self.options_summary.setText(
                    f"Program: {app}\nLibrary: {data}\n"
                    "Everything is included. Setup copies the app, creates "
                    "the shortcuts and needs no network connection.")
                return
            extras = (" plus the optional front-ends" if self.opt_extras.isChecked()
                      else "")
            self.options_summary.setText(
                f"Program: {app}\nLibrary: {data}\n"
                f"Downloads the native app{extras}. Needs a network connection "
                "for the first install.")
        except Exception:
            self.options_summary.setText("")

    def _check_permissions(self) -> None:
        try:
            plan = self._plan_from_options()
            plan.validate()
            report = core.grant_permissions(plan)
        except core.InstallError as exc:
            self.perms_label.setText(str(exc))
            self.perms_label.setObjectName("error")
            self.perms_label.style().unpolish(self.perms_label)
            self.perms_label.style().polish(self.perms_label)
            return
        except Exception as exc:
            self.perms_label.setText(str(exc))
            return
        self.perms_label.setObjectName("ok")
        self.perms_label.style().unpolish(self.perms_label)
        self.perms_label.style().polish(self.perms_label)
        self.perms_label.setText("Ready: " + "; ".join(report) + ".")

    # ---------------------------------------------------------------- plans
    def _plan_from_options(self) -> core.InstallPlan:
        return core.InstallPlan(
            app_dir=Path(self.opt_app.text()).expanduser(),
            data_dir=Path(self.opt_data.text()).expanduser(),
            create_venv=not self.bundled,
            install_deps=not self.bundled,
            extras=self.opt_extras.isChecked(),
            shortcuts=True,
            desktop_shortcut=self.opt_desktop.isChecked(),
            start_menu_shortcut=self.opt_start.isChecked(),
            shortcut_name=self.opt_name.text().strip() or core.APP_NAME,
        )

    def _express_plan(self) -> core.InstallPlan:
        return core.InstallPlan(
            app_dir=self.app_dir,
            data_dir=self.data_dir,
            create_venv=not self.bundled,
            install_deps=not self.bundled,
            extras=False,
            shortcuts=True,
            desktop_shortcut=True,
            start_menu_shortcut=True,
        )

    def _express_install(self) -> None:
        self._start_install(self._express_plan())

    def _auto_install(self) -> None:
        self._start_install(core.auto_plan(self.app_dir, self.data_dir))

    def _start_install(self, plan: core.InstallPlan) -> None:
        try:
            plan.validate()
        except core.InstallError as exc:
            QMessageBox.warning(self, "Cannot install here", str(exc))
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.log.clear()
        self.bar.setValue(0)
        self._show(PROGRESS)
        self._close_when_done = False
        self.worker = InstallWorker(plan, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.line.connect(self._on_line)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    # --------------------------------------------------------------- signals
    def _on_progress(self, percent: int, message: str) -> None:
        self.bar.setValue(max(0, min(100, percent)))
        self.progress_text.setText(message)

    def _on_line(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _on_done(self, config: dict) -> None:
        self.config = config
        self.bar.setValue(100)
        shortcuts = config.get("shortcut_count", 0)
        self.finish_text.setText(
            f"Program: {config.get('app_dir')}\n"
            f"Library: {config.get('data_dir')}\n"
            f"{shortcuts} shortcut(s) created. Open the launcher from the "
            "Desktop, or run it again any time - your voices are already here.")
        self._show(FINISH)
        if self._close_when_done:
            self.accept()

    def _on_failed(self, message: str) -> None:
        self.failed_text.setText(
            "Nothing was left half-finished that you need to clean up by hand. "
            "You can change a folder and try again.\n\n" + message)
        self.failed_log.setPlainText(self.log.toPlainText())
        self._show(FAILED)
        self.next_btn.setVisible(True)
        self.next_btn.setText("Back to options")
        self.next_btn.setEnabled(True)
        try:
            self.next_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.next_btn.clicked.connect(lambda: self._show(OPTIONS))
        self.cancel_btn.setText("Close")

    # ---------------------------------------------------------------- finish
    def _open_installed(self) -> None:
        config = self.config or {}
        app_dir = Path(config.get("app_dir", self.app_dir))
        launcher = app_dir / "launcher.py"
        python = config.get("python")
        if not python or not launcher.exists():
            return
        interpreter = Path(python)
        if config.get("bundled"):
            runtime = Path(config.get("runtime")
                           or app_dir / core.RUNTIME_DIR)
            quiet = runtime / ("pythonw.exe" if core.IS_WINDOWS
                               else "bin/python")
            if quiet.exists():
                interpreter = quiet
        elif config.get("venv"):
            quiet = Path(config["venv"]) / (
                "Scripts/pythonw.exe" if core.IS_WINDOWS else "bin/python")
            if quiet.exists():
                interpreter = quiet
        if core.IS_WINDOWS and interpreter.name.lower() == "python.exe":
            quiet = interpreter.with_name("pythonw.exe")
            if quiet.exists():
                interpreter = quiet
        env = vf_env.clean_env(app_dir, config.get("data_dir", self.data_dir))
        process = QProcess(self)
        process.setProgram(str(interpreter))
        process.setArguments([str(launcher)])
        process.setWorkingDirectory(str(app_dir))
        process.setEnvironment(env)
        if not process.startDetached():
            QMessageBox.warning(self, "VoiceForge",
                                "Installed, but could not start it just now.")

    def accept(self) -> None:
        if self.stack.currentIndex() == FINISH and self.open_box.isChecked():
            self._open_installed()
        if self.stack.currentIndex() == FINISH and self.open_library.isChecked():
            target = self.config.get("data_dir") if self.config else self.data_dir
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        self._cleanup_icon()
        super().accept()

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            if not self._close_when_done:
                answer = QMessageBox.question(
                    self, "Still installing",
                    "The install is still running. Close the window anyway?\n\n"
                    "It will stop where it is, and you can run Setup again.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self._cleanup_icon()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.worker is not None and self.worker.isRunning():
            self.reject()
            event.ignore()
            return
        self._cleanup_icon()
        super().closeEvent(event)

    def _cleanup_icon(self) -> None:
        folder = getattr(self, "_icon_dir", None)
        if folder is None:
            return
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
        self._icon_dir = None


def _emit(message: str) -> None:
    """Print when a console exists; stay silent in a windowed frozen exe.

    A windowed executable has no stderr at all, so unattended runs can also
    append their result to ``VOICEFORGE_SETUP_LOG`` when that is set. The
    release builder uses it to explain a failed smoke install.
    """
    log_path = os.environ.get("VOICEFORGE_SETUP_LOG")
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass
    stream = sys.stderr or sys.stdout
    if stream is not None:
        print(message, file=stream)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    vf_env.sanitize()

    auto = "--auto" in argv
    extras = "--no-extras" not in argv
    no_shortcuts = "--no-shortcuts" in argv
    app_dir = _argument(argv, "--app-dir")
    data_dir = _argument(argv, "--data-dir")

    if auto and "--quiet" in argv:
        plan = core.auto_plan(app_dir, data_dir)
        plan.extras = extras
        plan.shortcuts = not no_shortcuts
        try:
            core.install(plan)
        except Exception as exc:  # noqa: BLE001 - report, never traceback
            _emit(f"error: {exc}")
            return 1
        _emit("installed")
        return 0

    app = QApplication([sys.argv[0], *argv])
    app.setApplicationName("VoiceForge Setup")
    app.setApplicationDisplayName("VoiceForge Setup")
    qt_theme.apply(app, "midnight")

    window = Installer(app_dir, data_dir)
    window.show()
    if auto:
        # Auto is the no-questions path: recommended folders, Desktop
        # shortcut, optional front-ends included (the same policy as the
        # button). --no-extras keeps that path light for a quick install.
        plan = core.auto_plan(app_dir, data_dir)
        plan.extras = extras
        plan.shortcuts = not no_shortcuts
        window._start_install(plan)
    return app.exec()


def _argument(argv: list[str], flag: str) -> Path | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser()
        if value.startswith(flag + "="):
            return Path(value.split("=", 1)[1]).expanduser()
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
