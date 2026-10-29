"""The installer engine: copy, venv, shortcuts, install.json, uninstall.

No Qt in this file. The wizard in ``installer_ui.py`` is only a shell around
it, which means the whole install can be tested headlessly and can also run
unattended:

    python installer.py --auto
    python -m voiceforge.installer_core --auto      # same thing, no UI

A per-user install never needs administrator rights. The program goes in a
folder the user owns, dependencies go in a venv beside it, and the user's
voices and renders live wherever they chose. ``install.json`` in the program
folder is the one pointer that ties the two together.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import branding
from . import env as vf_env
from . import themes

APP_NAME = "VoiceForge"
VERSION = "1.1.0"
CONFIG_NAME = "install.json"
PAYLOAD_NAME = "payload.zip"
RUNTIME_DIR = "runtime"

ROOT_FILES = (
    "launcher.py", "desktop.py", "app.py", "native_window.py", "flet_app.py",
    "uninstall.py", "installer.py", "installer.pyw",
    "VoiceForge.pyw", "VoiceForge.bat", "VoiceForge-Setup.bat", "run.sh",
    "README.md", "LICENSE", "pyproject.toml", "requirements.txt",
    "THIRD_PARTY_NOTICES.md",
    "requirements-app.txt", "requirements-extras.txt",
    "requirements-clone.txt",
)
ROOT_DIRS = ("src", "launchers", "assets", "licenses")
IGNORE = shutil.ignore_patterns(
    ".venv", "__pycache__", "*.pyc", "*.pyo", ".cache", ".git", ".idea",
    "downloads", "voices", "project.json", "preferences.json", CONFIG_NAME,
    "tests", "~", "*.lnk", "*.log", "build", "dist", "releases",
)

IS_WINDOWS = sys.platform.startswith("win")


def _fs_path(path: Path | str) -> str:
    """Return a Windows extended-length path when the normal path is too long.

    The default Windows MAX_PATH limit is 260 characters. A bundled Python
    runtime contains paths close to that, and a user is free to install into a
    deeper folder, so every file operation that can create a path uses this.
    """
    text = os.fspath(path)
    if not IS_WINDOWS or text.startswith("\\\\?\\"):
        return text
    if len(text) < 240:
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + os.path.abspath(text)
IS_MAC = sys.platform == "darwin"


class InstallError(RuntimeError):
    pass


# -------------------------------------------------------------------- paths
def payload_archive() -> Path | None:
    """The self-contained payload bundled by a frozen Setup executable."""
    if not getattr(sys, "frozen", False):
        return None
    bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for candidate in (bundled / PAYLOAD_NAME,
                      Path(sys.executable).parent / PAYLOAD_NAME):
        if candidate.is_file():
            return candidate
    return None


def source_root() -> Path:
    """The folder that holds launcher.py - a checkout, or a frozen payload."""
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for candidate in (bundled / "payload", bundled):
            if (candidate / "launcher.py").exists():
                return candidate
        # The archive mode unpacks straight into the destination folder; the
        # staging folder only needs to exist for branding and validation.
        return bundled
    return Path(__file__).resolve().parents[2]


def default_app_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        return base / "Programs" / APP_NAME
    if IS_MAC:
        return Path.home() / "Applications" / f"{APP_NAME}.app"
    return Path.home() / ".local" / "opt" / APP_NAME.lower()


def default_data_dir() -> Path:
    if IS_WINDOWS:
        documents = Path.home() / "Documents"
        return (documents if documents.is_dir() else Path.home()) / APP_NAME
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    share = os.environ.get("XDG_DATA_HOME")
    base = Path(share) if share else Path.home() / ".local" / "share"
    return base / APP_NAME.lower()


def desktop_dir() -> Path:
    if IS_WINDOWS:
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            value, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            if value:
                return Path(value)
        except Exception:
            pass
    elif not IS_MAC:
        configured = os.environ.get("XDG_DESKTOP_DIR")
        if configured:
            return Path(configured)
    return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData/Roaming"
        return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / ".local" / "share" / "applications"


def _safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in (name or APP_NAME)
                      if ch.isalnum() or ch in " -_.").strip(" .")
    return cleaned or APP_NAME


def _base_python() -> Path:
    """Prefer the real interpreter over the venv redirector."""
    base = getattr(sys, "_base_executable", None)
    candidate = Path(base) if base else Path(sys.executable)
    if IS_WINDOWS and candidate.name.lower() == "pythonw.exe":
        console = candidate.with_name("python.exe")
        if console.exists():
            return console
    return candidate


def _venv_python(venv: Path) -> Path:
    rel = Path("Scripts/python.exe") if IS_WINDOWS else Path("bin/python")
    return venv / rel


def _gui_python(venv: Path) -> Path:
    python = _venv_python(venv)
    if IS_WINDOWS:
        quiet = python.with_name("pythonw.exe")
        return quiet if quiet.exists() else python
    return python


def _launch_python(plan: "InstallPlan") -> Path:
    """The interpreter a shortcut should start, console-free on Windows."""
    python = plan.interpreter()
    if IS_WINDOWS:
        quiet = python.with_name("pythonw.exe")
        if quiet.exists():
            return quiet
    return python


# ------------------------------------------------------------------- colours
def install_icon(icon_dir: Path) -> tuple[Path, Path]:
    """Return (ico, png) for the app, preferring the prebuilt brand assets.

    The shipping icon is an original WinterGate-aligned mark drawn in SVG and
    rasterised by ``tools/make_icon.py``. The procedural fallback below keeps
    setup working even when a frozen payload forgot to include ``assets/``.
    """
    icon_dir.mkdir(parents=True, exist_ok=True)
    ico_path = icon_dir / "voiceforge.ico"
    png_path = icon_dir / "voiceforge.png"
    prebuilt_ico = branding.asset(branding.ICON_FILE)
    prebuilt_png = branding.icon_png(256)
    if prebuilt_ico is not None and prebuilt_png is not None:
        for source, target in ((prebuilt_ico, ico_path), (prebuilt_png, png_path)):
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        return ico_path, png_path

    # Procedural fallback: a dark tile with a waveform.
    palette = themes.get("midnight")
    scale = 2
    size = 256
    big = size * scale
    pixels = bytearray(big * big * 4)

    def inside_round_rect(x: float, y: float, w: float, h: float,
                          r: float) -> bool:
        cx = min(max(x, r), w - r)
        cy = min(max(y, r), h - r)
        if r <= 0:
            return 0 <= x < w and 0 <= y < h
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def put(x: int, y: int, colour: tuple[int, int, int], alpha: int = 255) -> None:
        if 0 <= x < big and 0 <= y < big:
            offset = (y * big + x) * 4
            pixels[offset:offset + 4] = bytes((colour[0], colour[1], colour[2], alpha))

    def hex_rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    top = hex_rgb(palette["ACCENT_HOVER"])
    bottom = hex_rgb(palette["SHADOW"])
    white = (255, 255, 255)

    # Background tile with a vertical gradient.
    for y in range(big):
        blend = y / (big - 1)
        colour = tuple(int(top[i] * (1 - blend) + bottom[i] * blend) for i in range(3))
        for x in range(big):
            if inside_round_rect(x + .5, y + .5, big, big, 56 * scale):
                put(x, y, colour, 255)

    # Waveform: seven rounded bars of differing height.
    heights = (0.22, 0.40, 0.62, 0.82, 0.62, 0.40, 0.22)
    bar_w = 18 * scale
    gap = 9 * scale
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    left = (big - total) / 2
    for index, share in enumerate(heights):
        bar_h = int(big * share)
        x0 = int(left + index * (bar_w + gap))
        y0 = int((big - bar_h) / 2)
        radius = bar_w / 2
        for y in range(y0, y0 + bar_h):
            for x in range(x0, x0 + bar_w):
                if inside_round_rect(x - x0 + .5, y - y0 + .5, bar_w, bar_h, radius):
                    put(x, y, white, 245)

    # Box-filter 2x down to the final 256px image.
    small = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for dy in range(scale):
                for dx in range(scale):
                    offset = ((y * scale + dy) * big + (x * scale + dx)) * 4
                    r += pixels[offset]
                    g += pixels[offset + 1]
                    b += pixels[offset + 2]
                    a += pixels[offset + 3]
            offset = (y * size + x) * 4
            count = scale * scale
            small[offset:offset + 4] = bytes(
                (r // count, g // count, b // count, a // count))

    rows = []
    stride = size * 4
    for y in range(size):
        rows.append(b"\x00" + bytes(small[y * stride:(y + 1) * stride]))
    raw = b"".join(rows)

    def png_chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + png_chunk(b"IDAT", zlib.compress(raw, 9))
           + png_chunk(b"IEND", b""))
    png_path.write_bytes(png)

    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    ico_path.write_bytes(header + entry + png)
    return ico_path, png_path


# ---------------------------------------------------------------------- plan
@dataclass
class InstallPlan:
    app_dir: Path
    data_dir: Path
    source: Path = field(default_factory=source_root)
    payload: Path | None = field(default_factory=payload_archive)
    create_venv: bool = True
    install_deps: bool = True
    extras: bool = False
    shortcuts: bool = True
    desktop_shortcut: bool = True
    start_menu_shortcut: bool = True
    shortcut_name: str = APP_NAME
    python: Path | None = None
    in_place: bool = False
    allow_nonempty: bool = False
    desktop_path: Path | None = None
    start_menu_path: Path | None = None
    log: Callable[[str], None] | None = None
    progress: Callable[[int, str], None] | None = None

    def __post_init__(self) -> None:
        self.app_dir = Path(self.app_dir).expanduser().absolute()
        self.data_dir = Path(self.data_dir).expanduser().absolute()
        self.source = Path(self.source).expanduser().absolute()
        self.payload = Path(self.payload).absolute() if self.payload else None
        self.shortcut_name = _safe_name(self.shortcut_name)

    def say(self, message: str) -> None:
        if self.log is not None:
            self.log(message)

    def step(self, percent: int, message: str) -> None:
        self.say(message)
        if self.progress is not None:
            self.progress(percent, message)

    @property
    def venv_dir(self) -> Path:
        return self.app_dir / ".venv"

    def bundled_python(self) -> Path | None:
        """The relocatable interpreter that ships inside the release."""
        for base in (self.app_dir, self.source):
            for rel in (Path(f"{RUNTIME_DIR}/python.exe"),
                        Path(f"{RUNTIME_DIR}/bin/python"),
                        Path("python/python.exe"), Path("python/bin/python")):
                candidate = base / rel
                if candidate.exists():
                    return candidate
        return None

    def interpreter(self) -> Path:
        bundled = self.bundled_python()
        if bundled is not None:
            return bundled
        installed = _venv_python(self.venv_dir)
        if self.create_venv and installed.exists():
            return installed
        return Path(self.python or _base_python())

    def validate(self) -> None:
        app = self.app_dir
        data = self.data_dir
        if app == data:
            raise InstallError(
                "The program folder and the library folder must be different.")
        if data == app or app in data.parents:
            raise InstallError(
                "The library folder cannot be inside the program folder - "
                "uninstalling would delete your voices.")
        if not self.in_place and app == self.source:
            raise InstallError(
                "Install to a different folder, or choose 'install here'.")
        if self.payload is not None:
            try:
                with zipfile.ZipFile(self.payload) as archive:
                    raw_names = [item.filename for item in archive.infolist()
                                 if not item.is_dir()]
            except (OSError, zipfile.BadZipFile) as exc:
                raise InstallError(
                    f"The bundled program payload is damaged: {exc}") from exc
            prefix = _payload_prefix(raw_names)
            names = {name[len(prefix):].replace("\\", "/")
                     for name in raw_names}
            required = {"launcher.py", "desktop.py", "src/voiceforge/render.py"}
            if not required.issubset(names):
                raise InstallError(
                    "The bundled program payload is incomplete. Download "
                    "VoiceForge Setup again.")
            if not any(name.startswith(f"{RUNTIME_DIR}/")
                       and name.endswith(("/python.exe", "/python"))
                       for name in names):
                raise InstallError(
                    "The bundled Python runtime is missing from this Setup.")
        elif not self.source.is_dir() or not (self.source / "launcher.py").exists():
            raise InstallError(
                f"The program files are missing from {self.source}.")
        parent = app.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = app.parent / f".voiceforge-write-{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise InstallError(
                f"Cannot write to {parent}. Choose a folder you own.\n{exc}")
        if data.exists() and not data.is_dir():
            raise InstallError(f"{data} exists but is not a folder.")

    def as_dict(self) -> dict:
        return {
            "app_dir": str(self.app_dir),
            "data_dir": str(self.data_dir),
            "create_venv": self.create_venv,
            "install_deps": self.install_deps,
            "extras": self.extras,
        }


# -------------------------------------------------------------------- pieces
def _payload_prefix(names: list[str]) -> str:
    """The single top-level folder in a release zip, if there is one."""
    clean = [name.replace("\\", "/").lstrip("/") for name in names if name]
    tops = {name.split("/", 1)[0] for name in clean if "/" in name}
    if not clean or len(tops) != 1:
        return ""
    top = next(iter(tops))
    if all(name.startswith(top + "/") for name in clean):
        return top + "/"
    return ""


def _extract_payload(plan: InstallPlan, archive_path: Path) -> int:
    """Unpack the bundled program straight into the install folder."""
    app = plan.app_dir
    with zipfile.ZipFile(archive_path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        total = len(members)
        if total == 0:
            raise InstallError("The bundled program payload is empty.")
        prefix = _payload_prefix([item.filename for item in members])
        step = max(1, total // 40)
        for index, item in enumerate(members, 1):
            name = item.filename.replace("\\", "/")
            if prefix:
                name = name[len(prefix):]
            parts = Path(name).parts
            if not name or name.startswith("/") or ".." in parts:
                continue
            target = app.joinpath(*parts)
            os.makedirs(_fs_path(target.parent), exist_ok=True)
            with archive.open(item) as source, open(_fs_path(target), "wb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
            if index % step == 0 or index == total:
                message = f"Unpacking the program … {index}/{total} files"
                if plan.progress is not None:
                    plan.progress(18 + int(24 * index / total), message)
    return total


def _copy_program(plan: InstallPlan) -> None:
    if plan.in_place:
        plan.say("Installing in place - program files stay where they are.")
        return
    app = plan.app_dir
    existing = list(app.iterdir()) if app.is_dir() else []
    if existing and not (app / CONFIG_NAME).exists() and not plan.allow_nonempty:
        raise InstallError(
            f"{app} is not empty and does not look like a VoiceForge install. "
            "Pick another folder or allow overwriting.")
    app.mkdir(parents=True, exist_ok=True)

    if plan.payload is not None:
        plan.say("Unpacking the bundled VoiceForge release (this is the big step) …")
        copied = _extract_payload(plan, plan.payload)
        plan.say(f"Unpacked {copied} program file(s) to {app}.")
        return

    copied = 0
    for name in ROOT_FILES:
        source = plan.source / name
        if source.is_file():
            shutil.copy2(source, app / name)
            copied += 1
    for name in ROOT_DIRS:
        source = plan.source / name
        if not source.is_dir():
            continue
        destination = app / name
        shutil.copytree(source, destination, dirs_exist_ok=True, ignore=IGNORE)
        copied += 1
    runtime = plan.source / RUNTIME_DIR
    if runtime.is_dir():
        plan.say("Copying the bundled Python runtime …")
        shutil.copytree(runtime, app / RUNTIME_DIR, dirs_exist_ok=True,
                        ignore=IGNORE)
        copied += 1
    if copied == 0:
        raise InstallError("Nothing was copied - the source folder looks empty.")
    plan.say(f"Copied {copied} program item(s) to {app}.")


def _create_venv(plan: InstallPlan) -> None:
    if plan.bundled_python() is not None:
        plan.say("Using the bundled Python runtime - nothing to create.")
        return
    if not plan.create_venv:
        return
    python = _venv_python(plan.venv_dir)
    if python.exists():
        plan.say(f"Using the existing virtual environment at {plan.venv_dir}.")
        return
    base = Path(plan.python or _base_python())
    plan.say(f"Creating a virtual environment with {base} …")
    command = [str(base), "-m", "venv", str(plan.venv_dir)]
    result = subprocess.run(command, capture_output=True, text=True,
                            env=vf_env.clean_env(plan.source, plan.data_dir))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise InstallError(f"Could not create the virtual environment.\n{detail}")
    if not python.exists():
        raise InstallError("The virtual environment was created but has no Python.")


def _pip_install(plan: InstallPlan, requirement: str) -> None:
    if plan.bundled_python() is not None:
        plan.say("Dependencies are already included - no download needed.")
        return
    python = plan.interpreter()
    command = [str(python), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-input",
               "-r", str(plan.source / requirement)]
    if not (plan.source / requirement).exists():
        # A frozen Setup exe may not ship the requirements files; the native
        # app's dependencies are few enough to name here as a fallback.
        command = [str(python), "-m", "pip", "install",
                   "--disable-pip-version-check", "--no-input",
                   "edge-tts>=7.0.0", "numpy>=1.26", "soundfile>=0.12.1",
                   "PySide6-Addons>=6.6"]
    plan.say(f"> {python.name} -m pip install -r {requirement}")
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        env=vf_env.clean_env(plan.source, plan.data_dir))
    assert process.stdout is not None
    tail: list[str] = []
    for line in process.stdout:
        text = line.rstrip()
        if text:
            tail.append(text)
            del tail[:-12]
            plan.say(text)
    code = process.wait()
    if code != 0:
        raise InstallError(
            "Dependency installation failed. Last lines:\n"
            + "\n".join(tail[-8:]))


def _write_config(plan: InstallPlan, shortcuts: list[Path],
                  icon: Path, png_icon: Path) -> dict:
    bundled = plan.bundled_python()
    config = {
        "app": APP_NAME,
        "version": VERSION,
        "app_dir": str(plan.app_dir),
        "data_dir": str(plan.data_dir),
        "venv": str(plan.venv_dir) if plan.venv_dir.exists() else "",
        "python": str(plan.interpreter()),
        "bundled": bundled is not None,
        "runtime": str(plan.app_dir / RUNTIME_DIR) if bundled else "",
        "shortcuts": [str(path) for path in shortcuts],
        "icon": str(icon),
        "png_icon": str(png_icon),
        "installed_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "extras": plan.extras,
    }
    path = plan.app_dir / CONFIG_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    tmp.replace(path)
    return config


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _windows_shortcut(link: Path, target: Path, arguments: str,
                      working_dir: Path, icon: Path, description: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut({_ps_quote(str(link))})
$shortcut.TargetPath = {_ps_quote(str(target))}
$shortcut.Arguments = {_ps_quote(arguments)}
$shortcut.WorkingDirectory = {_ps_quote(str(working_dir))}
$shortcut.IconLocation = {_ps_quote(str(icon))}
$shortcut.Description = {_ps_quote(description)}
$shortcut.Save()
"""
    encoded = script.encode("utf-16-le")
    import base64

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
         base64.b64encode(encoded).decode("ascii")],
        capture_output=True, text=True, timeout=60,
        env=vf_env.clean_env(working_dir))
    if result.returncode != 0:
        raise InstallError(
            "Could not create the shortcut.\n"
            + (result.stderr or result.stdout or "").strip())


def _linux_desktop_entry(plan: InstallPlan, icon: Path) -> str:
    python = _launch_python(plan)
    exec_line = f'"{python}" "{plan.app_dir / "launcher.py"}"'
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={plan.shortcut_name}",
        "Comment=Local text to speech with voices you own",
        f"Exec={exec_line}",
        f"Path={plan.app_dir}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;Utility;",
        "StartupNotify=true",
        "StartupWMClass=VoiceForge",
        "",
    ])


def _make_shortcuts(plan: InstallPlan, icon: Path, png_icon: Path) -> list[Path]:
    if not plan.shortcuts:
        return []
    created: list[Path] = []
    name = plan.shortcut_name
    launcher = plan.app_dir / "launcher.py"

    if IS_WINDOWS:
        python = _launch_python(plan)
        if plan.desktop_shortcut:
            link = (plan.desktop_path or desktop_dir()) / f"{name}.lnk"
            _windows_shortcut(link, python, f'"{launcher}"', plan.app_dir,
                              icon, "VoiceForge - voices you own")
            created.append(link)
        if plan.start_menu_shortcut:
            link = (plan.start_menu_path or start_menu_dir()) / f"{name}.lnk"
            _windows_shortcut(link, python, f'"{launcher}"', plan.app_dir,
                              icon, "VoiceForge - voices you own")
            created.append(link)
            uninstaller = plan.app_dir / "uninstall.py"
            if uninstaller.exists():
                link = ((plan.start_menu_path or start_menu_dir())
                        / f"Uninstall {name}.lnk")
                _windows_shortcut(link, python, f'"{uninstaller}"',
                                  plan.app_dir, icon,
                                  "Remove VoiceForge from this computer")
                created.append(link)
        return created

    # Linux / other POSIX desktops
    entry_text = _linux_desktop_entry(plan, png_icon)
    applications = plan.start_menu_path or start_menu_dir()
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "voiceforge.desktop"
    entry.write_text(entry_text, encoding="utf-8")
    try:
        entry.chmod(0o755)
    except OSError:
        pass
    created.append(entry)

    if plan.desktop_shortcut:
        target = plan.desktop_path or desktop_dir()
        if target.is_dir():
            copy = target / "voiceforge.desktop"
            copy.write_text(entry_text, encoding="utf-8")
            try:
                copy.chmod(0o755)
            except OSError:
                pass
            created.append(copy)

    # A command on PATH, which is the friendly thing to do on Linux.
    bin_dir = Path.home() / ".local" / "bin"
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        wrapper = bin_dir / "voiceforge"
        python = _launch_python(plan)
        wrapper.write_text(
            "#!/bin/sh\n"
            f'exec "{python}" "{launcher}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        created.append(wrapper)
    except OSError:
        pass
    return created


def grant_permissions(plan: InstallPlan) -> list[str]:
    """Make the two folders genuinely usable, and report what was checked."""
    report: list[str] = []
    for label, folder in (("program", plan.app_dir), ("library", plan.data_dir)):
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{os.getpid()}"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            report.append(f"{label} folder is writable")
        except OSError as exc:
            raise InstallError(f"The {label} folder is not writable: {exc}")
    (plan.data_dir / "voices").mkdir(parents=True, exist_ok=True)
    (plan.data_dir / "downloads").mkdir(parents=True, exist_ok=True)
    report.append("voices and downloads folders are ready")
    if not IS_WINDOWS:
        for folder in (plan.app_dir, plan.data_dir,
                       plan.data_dir / "voices", plan.data_dir / "downloads"):
            try:
                folder.chmod(0o755)
            except OSError:
                pass
        script = plan.app_dir / "run.sh"
        if script.exists():
            try:
                script.chmod(0o755)
                report.append("run.sh is executable")
            except OSError:
                pass
    return report


# --------------------------------------------------------------------- main
def install(plan: InstallPlan) -> dict:
    """Run a full install. Raises InstallError with a readable message."""
    plan.validate()
    plan.step(4, f"Preparing {plan.app_dir} …")

    plan.step(10, "Checking folder permissions …")
    permissions = grant_permissions(plan)

    plan.step(18, "Copying program files …")
    _copy_program(plan)

    if plan.bundled_python() is not None:
        plan.step(58, "Using the bundled Python runtime - no downloads "
                      "and no extra setup needed.")
    else:
        plan.step(34, "Creating the virtual environment …")
        _create_venv(plan)
        if plan.install_deps:
            plan.step(46, "Installing the native app (this downloads once) …")
            _pip_install(plan, "requirements-app.txt")
            if plan.extras:
                plan.step(74, "Installing the optional front-ends …")
                _pip_install(plan, "requirements-extras.txt")
        else:
            plan.step(74, "Skipping dependency installation.")

    plan.step(86, "Drawing the app icon …")
    icon, png_icon = install_icon(plan.app_dir / "assets")

    plan.step(92, "Creating shortcuts …")
    shortcuts = _make_shortcuts(plan, icon, png_icon)

    plan.step(96, "Writing install.json …")
    config = _write_config(plan, shortcuts, icon, png_icon)

    plan.step(100, "Finished.")
    config["permissions"] = permissions
    config["shortcut_count"] = len(shortcuts)
    return config


# ----------------------------------------------------------------- uninstall
def uninstall(app_dir: Path, purge_data: bool = False,
              log: Callable[[str], None] | None = None) -> dict:
    """Remove an installed copy. The program folder goes; data only on request."""
    app_dir = Path(app_dir).expanduser().absolute()
    say = log or (lambda _message: None)
    config_path = app_dir / CONFIG_NAME
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}

    removed: list[str] = []
    for shortcut in config.get("shortcuts", []):
        path = Path(shortcut)
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
                say(f"Removed {path}")
        except OSError as exc:
            say(f"Could not remove {path}: {exc}")

    data_dir = Path(config.get("data_dir", "")) if config.get("data_dir") else None
    if purge_data and data_dir and data_dir.is_dir():
        try:
            shutil.rmtree(_fs_path(data_dir))
            removed.append(str(data_dir))
            say(f"Removed your data at {data_dir}")
        except OSError as exc:
            say(f"Could not remove {data_dir}: {exc}")

    # The bundled runtime and the venv are in use while this Python is
    # running, so the caller removes the folder after this process exits.
    for child in sorted(app_dir.iterdir()) if app_dir.is_dir() else []:
        if child.name in (".venv", RUNTIME_DIR):
            continue
        try:
            if child.is_dir():
                shutil.rmtree(_fs_path(child))
            else:
                os.unlink(_fs_path(child))
            removed.append(str(child))
        except OSError as exc:
            say(f"Could not remove {child}: {exc}")

    result = {"removed": removed, "data_kept": data_dir if not purge_data else None}
    return result


def schedule_folder_removal(folder: Path) -> None:
    """Delete `folder` after this process exits (Windows and POSIX).

    The delete is retried for a while: the launcher may still be shutting down
    and holding a DLL in the bundled runtime when the first attempt runs.
    """
    folder = Path(folder)
    if IS_WINDOWS:
        script = (
            "@echo off\r\n"
            "ping -n 3 127.0.0.1 >nul\r\n"
            "for /L %%i in (1,1,30) do (\r\n"
            f'  rmdir /s /q "{folder}" 2>nul\r\n'
            f'  if not exist "{folder}" goto done\r\n'
            "  ping -n 2 127.0.0.1 >nul\r\n"
            ")\r\n"
            ":done\r\n"
        )
        path = Path(tempfile.gettempdir()) / f"voiceforge-cleanup-{os.getpid()}.bat"
        path.write_text(script, encoding="utf-8")
        subprocess.Popen(["cmd.exe", "/c", str(path)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        subprocess.Popen(
            ["/bin/sh", "-c",
             f'sleep 1; for i in $(seq 1 30); do rm -rf "{folder}" && '
             f'[ ! -e "{folder}" ] && break; sleep 1; done'],
            start_new_session=True)


# --------------------------------------------------------------- unattended
def auto_plan(app_dir: Path | None = None, data_dir: Path | None = None,
              log: Callable[[str], None] | None = None,
              progress: Callable[[int, str], None] | None = None) -> InstallPlan:
    return InstallPlan(
        app_dir=app_dir or default_app_dir(),
        data_dir=data_dir or default_data_dir(),
        log=log,
        progress=progress,
        extras=True,
    )


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Install VoiceForge without a UI")
    parser.add_argument("--app-dir", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--no-extras", action="store_true")
    parser.add_argument("--no-deps", action="store_true")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--source", type=Path, default=None)
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, flush=True)

    plan = auto_plan(args.app_dir, args.data_dir, log=log)
    plan.extras = not args.no_extras
    plan.install_deps = not args.no_deps
    plan.shortcuts = not args.no_shortcuts
    if args.source:
        plan.source = args.source
    try:
        config = install(plan)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(config, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
