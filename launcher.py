"""VoiceForge launcher - one window that picks how the app runs.

Four front-ends share one core, so the only real question is which shell you
want around it:

    Native       desktop.py       PySide6 widgets, built-in player
    Browser      app.py           Gradio in your default browser
    Window       native_window.py Gradio inside a native OS window (pywebview)
    Flet         flet_app.py      Flutter-rendered alternative UI

This file is the chooser and the one entry point to remember. It sits at the
project root, next to the front-end scripts, so the folder is self-explanatory.
The shell wrappers live in launchers/ and all route back here.

    VoiceForge.bat                    open the chooser (Windows, double-click)
    VoiceForge.pyw                    same, with no console window
    ./run.sh                          open the chooser (bash/WSL)
    python launcher.py --launch native
    python launcher.py --check        availability as JSON (no GUI)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_HINT = Path(sys.executable).parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent

# The shared modules live in src/ and are not installed system-wide.
sys.path.insert(0, str(ROOT_HINT / "src"))

from PySide6.QtCore import QProcess, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QAction, QTextCursor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from voiceforge import help_dialogs  # noqa: E402
from voiceforge import branding, env as vf_env, paths, qt_theme  # noqa: E402
from voiceforge.preferences import Preferences  # noqa: E402
from voiceforge.settings_dialog import SettingsDialog  # noqa: E402

# Drop the dead Tor proxy before anything can open a socket or import httpx.
vf_env.sanitize()


# ------------------------------------------------------------------ front-ends
@dataclass(frozen=True)
class Frontend:
    key: str
    title: str
    blurb: str
    script: str
    module: str          # import name used to test availability
    package: str         # pip requirement installed on demand
    best: bool = False


FRONTENDS: tuple[Frontend, ...] = (
    Frontend(
        "native", "Native Desktop",
        "PySide6 widgets, built-in audio player, no browser process.\n"
        "The quickest way in and the one to use for real work.",
        "desktop.py", "PySide6", "PySide6-Addons", best=True),
    Frontend(
        "web", "Browser UI",
        "The full Gradio interface in your default browser.\n"
        "Useful for microphone capture and drag-and-drop uploads.",
        "app.py", "gradio", "gradio"),
    Frontend(
        "window", "Desktop Window",
        "That same Gradio interface inside a native window,\n"
        "with no address bar. Needs WebView2 on Windows, WebKitGTK on Linux.",
        "native_window.py", "webview", "pywebview"),
    Frontend(
        "flet", "Flet UI",
        "A second independent UI rendered by Flutter.\n"
        "Smaller surface than the others; handy as a fallback.",
        "flet_app.py", "flet", "flet[all]==0.28.3"),
)

BY_KEY = {f.key: f for f in FRONTENDS}


# ------------------------------------------------------------------- discovery
def find_root() -> Path | None:
    """Project root: $VOICEFORGE_HOME, else the launcher's own folder/parents."""
    env = os.environ.get("VOICEFORGE_HOME")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates.append(ROOT_HINT)
    candidates.extend(ROOT_HINT.parents)
    candidates.append(Path.cwd())
    for base in candidates:
        for probe in (base, *base.parents):
            if (probe / "src" / "voiceforge" / "render.py").exists():
                return probe.resolve()
    return None


def project_python(root: Path) -> Path | None:
    # A release build carries its own relocatable Python. Prefer it so an
    # installed or portable copy never depends on the machine's Python.
    for rel in (Path("runtime/python.exe"), Path("runtime/bin/python"),
                Path("python/python.exe"), Path("python/bin/python")):
        candidate = root / rel
        if candidate.exists():
            return candidate
    for rel in (Path(".venv/Scripts/python.exe"), Path(".venv/bin/python")):
        candidate = root / rel
        if candidate.exists():
            return candidate
    if not getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def gui_python(py: Path) -> Path:
    """Prefer pythonw on Windows so launching does not flash a console."""
    if sys.platform.startswith("win"):
        quiet = py.with_name("pythonw.exe")
        if quiet.exists():
            return quiet
    return py


def clean_env(root: Path) -> dict[str, str]:
    """Scrubbed environment for every child process (no dead proxies)."""
    return vf_env.clean_env(root)


def detect(py: Path, root: Path) -> dict[str, bool]:
    """Which front-end import names exist in the project interpreter."""
    modules = sorted({f.module for f in FRONTENDS})
    code = (
        "import importlib.util as u, json\n"
        f"names = {modules!r}\n"
        "print(json.dumps({n: u.find_spec(n) is not None for n in names}))\n"
    )
    try:
        out = subprocess.run(
            [str(py), "-c", code], cwd=str(root), timeout=45,
            capture_output=True, text=True, env=clean_env(root))
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {name: False for name in modules}


# ------------------------------------------------------------------- install log
class LogDialog(QDialog):
    """Shows pip / setup output instead of hiding it behind a spinner."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 420)
        self.done_ok: bool | None = None

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")

        self.status = QLabel("Working…")
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.log, 1)
        layout.addLayout(buttons)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._drain)
        self.proc.finished.connect(self._finished)

    def _drain(self) -> None:
        text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _finished(self, code: int, _status) -> None:
        self._drain()
        self.done_ok = code == 0
        self.status.setText("Finished." if code == 0 else f"Failed (exit {code}).")
        self.close_btn.setEnabled(True)

    def run(self, program: str, args: list[str], cwd: Path,
            env: dict[str, str]) -> int:
        self.log.appendPlainText(f"> {program} {' '.join(args)}\n")
        self.proc.setWorkingDirectory(str(cwd))
        self.proc.setEnvironment(env)
        self.proc.start(program, args)
        if not self.proc.waitForStarted(15000):
            self.log.appendPlainText("Could not start the process.")
            self.status.setText("Could not start.")
            self.close_btn.setEnabled(True)
        self.exec()
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(3000)
        return 0 if self.done_ok else 1


# ----------------------------------------------------------------------- cards
class FrontendCard(QFrame):
    launch = Signal(str)
    install = Signal(str)

    def __init__(self, front: Frontend, parent=None) -> None:
        super().__init__(parent)
        self.front = front
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        title = QLabel(front.title)
        title.setObjectName("heading")
        self.badge = QLabel("checking…")
        self.badge.setObjectName("badge")

        head = QHBoxLayout()
        head.addWidget(title)
        if front.best:
            default = QLabel("default")
            default.setObjectName("pill")
            head.addWidget(default)
        head.addStretch(1)
        head.addWidget(self.badge)

        blurb = QLabel(front.blurb)
        blurb.setWordWrap(True)
        blurb.setObjectName("blurb")

        self.launch_btn = QPushButton("Launch")
        self.launch_btn.setObjectName("primary")
        self.launch_btn.setEnabled(False)
        self.launch_btn.clicked.connect(lambda: self.launch.emit(front.key))

        self.install_btn = QPushButton("Install")
        self.install_btn.setVisible(False)
        self.install_btn.clicked.connect(lambda: self.install.emit(front.key))

        buttons = QHBoxLayout()
        buttons.addWidget(self.launch_btn, 1)
        buttons.addWidget(self.install_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addWidget(blurb, 1)
        layout.addLayout(buttons)
        self.setMinimumHeight(150)

    def set_state(self, installed: bool, usable: bool) -> None:
        self.install_btn.setVisible(not installed)
        self.install_btn.setEnabled(usable and not installed)
        self.launch_btn.setEnabled(installed)
        self.badge.setText("ready" if installed else "needs install")
        self.badge.setProperty("state", "ok" if installed else "todo")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


# ---------------------------------------------------------------------- window
class Launcher(QMainWindow):
    def __init__(self, root: Path, data: Path | None = None,
                 prefs: Preferences | None = None) -> None:
        super().__init__()
        self.root = root
        self.data = Path(data) if data is not None else root
        self.prefs = prefs or Preferences.load(self.data)
        self.python = project_python(root)
        self.cards: dict[str, FrontendCard] = {}
        self.available: dict[str, bool] = {}

        self.setWindowTitle("VoiceForge")
        self.setMinimumSize(1040, 680)
        self.resize(1200, 760)
        self._build()
        self._start_check()

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        page = QWidget()
        self.setCentralWidget(page)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(30, 24, 30, 20)
        outer.setSpacing(14)

        title = QLabel("VoiceForge")
        title.setObjectName("title")
        subtitle = QLabel(
            "One core, four shells. Pick how you want to work - the voices, "
            "settings and undo history are shared.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitle")

        outer.addWidget(title)
        outer.addWidget(subtitle)

        menu = self.menuBar()
        help_menu = menu.addMenu("&Help")
        act_help = QAction("Help and Guides…", self)
        act_help.setShortcut("F1")
        act_help.triggered.connect(self.open_help)
        help_menu.addAction(act_help)
        act_about = QAction("About VoiceForge…", self)
        act_about.triggered.connect(self.open_about)
        help_menu.addAction(act_about)
        help_menu.addSeparator()
        act_readme = QAction("Open Readme", self)
        act_readme.triggered.connect(lambda: self._open(self.root / "README.md"))
        help_menu.addAction(act_readme)

        self.env_label = QLabel()
        self.env_label.setWordWrap(True)
        self.env_label.setObjectName("hint")
        if self.python:
            text = f"Program: {self.root}\nPython:  {self.python}"
        else:
            text = (f"Program: {self.root}\n"
                    "No virtual environment found yet.")
        if self.data != self.root:
            text += f"\nData:    {self.data}"
        self.env_label.setText(text)
        outer.addWidget(self.env_label)

        grid = QGridLayout()
        grid.setSpacing(16)
        for i, front in enumerate(FRONTENDS):
            card = FrontendCard(front)
            card.launch.connect(self.launch)
            card.install.connect(self.install)
            self.cards[front.key] = card
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid, 1)

        footer = QHBoxLayout()
        self.close_after = QCheckBox("Close this launcher after starting")
        self.close_after.setChecked(
            bool(self.prefs["close_launcher_after_start"]))
        self.close_after.toggled.connect(self._set_close_after)

        settings_btn = QPushButton("Settings…")
        settings_btn.setToolTip("Theme, folders, long-text and launch options")
        settings_btn.clicked.connect(self.open_settings)
        folder_btn = QPushButton("Program folder")
        folder_btn.clicked.connect(lambda: self._open(self.root))
        out_btn = QPushButton("Downloads folder")
        out_btn.clicked.connect(
            lambda: self._open(self.prefs.output_dir))
        term_btn = QPushButton("Terminal here")
        term_btn.clicked.connect(self._terminal)
        readme_btn = QPushButton("Readme")
        readme_btn.clicked.connect(lambda: self._open(self.root / "README.md"))
        help_btn = QPushButton("Help")
        help_btn.setToolTip("Guides for every part of VoiceForge")
        help_btn.clicked.connect(self.open_help)
        about_btn = QPushButton("About")
        about_btn.setToolTip("Who made VoiceForge, and how to get back here")
        about_btn.clicked.connect(self.open_about)

        footer.addWidget(self.close_after, 1)
        footer.addWidget(settings_btn)
        for b in (folder_btn, out_btn, term_btn, readme_btn, help_btn,
                  about_btn):
            footer.addWidget(b)
        outer.addLayout(footer)

        hint = QLabel(
            "Command line: VoiceForge.bat native|web|window|flet|default    "
            "VoiceForge.bat get    ./run.sh style list")
        hint.setObjectName("hint")
        outer.addWidget(hint)

        if self.python is None:
            self.statusBar().showMessage(
                "No .venv yet - run launchers\\setup.cmd (Windows) or "
                "./run.sh (Linux).")

    # -- preferences ------------------------------------------------------
    def restyle(self) -> None:
        self.prefs = Preferences.load(self.data)
        app = QApplication.instance()
        if app is not None:
            qt_theme.apply(app, self.prefs["theme"])
        self.close_after.setChecked(
            bool(self.prefs["close_launcher_after_start"]))
        for card in self.cards.values():
            card.set_state(
                bool(self.available.get(card.front.module))
                and (self.root / card.front.script).exists(), True)

    def _set_close_after(self, on: bool) -> None:
        self.prefs.set("close_launcher_after_start", on)
        self.prefs.save()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.data, self.prefs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.restyle()
            self.statusBar().showMessage(dialog.summary(), 8000)

    def open_help(self) -> None:
        help_dialogs.show_help(self)

    def open_about(self) -> None:
        # "Back to Launcher" in About simply closes back to this window.
        help_dialogs.show_about(self)

    # -- availability -----------------------------------------------------
    def _start_check(self) -> None:
        if self.python is None:
            for card in self.cards.values():
                card.set_state(False, False)
            return
        self._checked(detect(self.python, self.root))

    def _checked(self, availability: dict) -> None:
        self.available = availability
        for front in FRONTENDS:
            card = self.cards[front.key]
            installed = bool(availability.get(front.module))
            script_exists = (self.root / front.script).exists()
            card.set_state(installed and script_exists, True)
            if installed and not script_exists:
                card.badge.setText("script missing")

    # -- actions ----------------------------------------------------------
    def _open(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.information(self, "VoiceForge", f"Not found yet:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "VoiceForge", str(exc))

    def _terminal(self) -> None:
        env = clean_env(self.root)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["cmd.exe", "/k", f'cd /d "{self.root}"'],
                                 env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
                return
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                exe = shutil.which(term)
                if exe:
                    subprocess.Popen([exe], cwd=str(self.root), env=env)
                    return
            QMessageBox.information(self, "VoiceForge", "No terminal emulator found.")
        except Exception as exc:
            QMessageBox.warning(self, "VoiceForge", str(exc))

    def install(self, key: str) -> None:
        front = BY_KEY[key]
        if self.python is None:
            QMessageBox.warning(
                self, "VoiceForge",
                "Create the virtual environment first: launchers\\setup.cmd "
                "on Windows, ./run.sh on Linux.")
            return
        dialog = LogDialog(f"Install {front.title}", self)
        code = dialog.run(
            str(self.python),
            ["-m", "pip", "install", "--disable-pip-version-check", front.package],
            self.root, clean_env(self.root))
        if code == 0:
            self.statusBar().showMessage(f"Installed {front.package}.")
            self._start_check()
        else:
            self.statusBar().showMessage("Install did not finish cleanly.")

    def launch(self, key: str) -> None:
        if key == "default":
            key = str(self.prefs["default_frontend"])
        front = BY_KEY.get(key)
        if front is None:
            QMessageBox.warning(self, "VoiceForge", f"Unknown front-end: {key}")
            return
        if self.python is None:
            QMessageBox.warning(self, "VoiceForge", "No virtual environment found.")
            return
        script = self.root / front.script
        if not script.exists():
            QMessageBox.warning(self, "VoiceForge", f"Missing file: {script}")
            return
        if not self.available.get(front.module):
            answer = QMessageBox.question(
                self, "Not installed",
                f"{front.title} needs {front.package}.\n\nInstall it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self.install(key)
            return

        interpreter = self.python if key == "web" else gui_python(self.python)
        # A detached QProcess carries its own environment, which the static
        # convenience overload cannot do. That matters here: inheriting the
        # dead proxy would break Gradio inside the child. The data folder is
        # passed explicitly so an installed copy keeps one library.
        env = clean_env(self.root)
        env["VOICEFORGE_DATA"] = str(self.data)
        process = QProcess(self)
        process.setProgram(str(interpreter))
        process.setArguments([str(script)])
        process.setWorkingDirectory(str(self.root))
        process.setEnvironment(env)
        if not process.startDetached():
            QMessageBox.warning(self, "VoiceForge",
                                f"Could not start {front.title}.")
            return

        self.statusBar().showMessage(f"Started {front.title}.")
        if self.close_after.isChecked():
            QApplication.instance().quit()


# ------------------------------------------------------------------------ main
def check_only(root: Path) -> int:
    """Headless dependency report, used by tests and `launcher.py --check`."""
    py = project_python(root)
    if py is None:
        print(json.dumps({"error": "no virtual environment", "root": str(root)}))
        return 1
    modules = sorted({f.module for f in FRONTENDS})
    code = (
        "import importlib.util as u, json\n"
        f"names = {modules!r}\n"
        "print(json.dumps({n: u.find_spec(n) is not None for n in names}))\n"
    )
    out = subprocess.run([str(py), "-c", code], cwd=str(root),
                         capture_output=True, text=True, env=clean_env(root))
    print(json.dumps({"root": str(root), "python": str(py),
                      "modules": json.loads(out.stdout.strip())}, indent=2))
    return 0


def main(argv: list[str]) -> int:
    root = find_root()
    if root is None:
        print("error: could not find the VoiceForge project folder. "
              "Set VOICEFORGE_HOME to the folder that contains src/voiceforge.",
              file=sys.stderr)
        return 2

    if "--check" in argv:
        return check_only(root)
    if "--list" in argv:
        for front in FRONTENDS:
            print(f"{front.key:8} {front.title:16} {front.script}")
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("VoiceForge Launcher")
    app.setApplicationDisplayName("VoiceForge")
    icon = branding.qicon()
    if icon is not None and not icon.isNull():
        app.setWindowIcon(icon)
    data = paths.data_root(__file__)
    prefs = Preferences.load(data)
    qt_theme.apply(app, prefs["theme"])

    window = Launcher(root, data, prefs)
    window.show()

    wanted = None
    for i, arg in enumerate(argv):
        if arg == "--launch" and i + 1 < len(argv):
            wanted = argv[i + 1]
        elif arg.startswith("--launch="):
            wanted = arg.split("=", 1)[1]
    if wanted:
        if wanted not in BY_KEY and wanted != "default":
            print(f"unknown front-end {wanted!r}; choose "
                  f"{', '.join(BY_KEY)}, default", file=sys.stderr)
            return 2
        QTimer.singleShot(600, lambda: window.launch(wanted))
    if "--self-test" in argv:
        QTimer.singleShot(400, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
