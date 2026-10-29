"""Build the complete, offline VoiceForge release.

The result is a timestamped folder under ``releases/`` containing exactly the
four things a person needs:

    VoiceForge-1.1.0-windows-x64.zip   the portable app and its Python runtime
    VoiceForge-Setup-1.1.0.exe         the offline Qt installer
    README.md
    LICENSE

The important constraint is that the Setup executable must work *by itself*,
on a machine with no Python, no pip and no network. It therefore embeds the
same main-package zip as ``payload.zip``; ``installer_core`` unpacks it and
uses the relocatable runtime inside it.

Run it with the project virtual environment:

    .venv\\Scripts\\python.exe tools\\build_release.py

Useful test shortcuts while editing this file:

    --skip-setup     stop after the package zip (fast)
    --skip-tests     skip the smoke tests (not for a real release)
    --no-clean       keep the previous build folder
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env as vf_env  # noqa: E402
from voiceforge.installer_core import (  # noqa: E402
    IGNORE, ROOT_DIRS, ROOT_FILES, RUNTIME_DIR,
)

VERSION = "1.1.0"
PLATFORM_TAG = "windows-x64"
PACKAGE_NAME = f"VoiceForge-{VERSION}-{PLATFORM_TAG}.zip"
SETUP_NAME = f"VoiceForge-Setup-{VERSION}.exe"
STAGE_FOLDER = "VoiceForge"

BUILD = ROOT / "build"
RELEASES = ROOT / "releases"
STAGE_ROOT = BUILD / "stage"
PACKAGE_DIR = BUILD / "package"
SETUP_DIR = BUILD / "setup"
TEST_DIR = BUILD / "test-install"

# Anything here is build tooling, not something the running app needs.
SITE_EXCLUDE_TOP = {
    "__pycache__",
    "PyInstaller",
    "altgraph",
    "_pyinstaller_hooks_contrib",
    "pyinstaller_hooks_contrib",
    "pefile.py",
    "peutils.py",
}
SITE_EXCLUDE_PREFIX = (
    "pyinstaller-",
    "altgraph-",
    "pefile-",
    "pyinstaller_hooks_contrib-",
    "pywin32_ctypes-",
)

# The Qt deployment tools are large standalone programs, not importable
# modules. The app never starts them. Keeping the Qt libraries themselves is
# deliberate: trimming those by hand is how a release ends up without an
# audio or platform plugin on a customer's machine.
PYSIDE_EXCLUDE_DIRS = {
    "doc", "include", "typesystems", "scripts", "support", "glue",
    "metatypes",
}

# Python's own test/demo/teaching trees are not needed to run an app.
PY_LIB_EXCLUDE = {
    "site-packages", "test", "tests", "idlelib", "turtledemo", "tkinter",
    "lib2to3", "ensurepip", "curses", "msilib",
}

IS_WINDOWS = sys.platform.startswith("win")
START = time.perf_counter()
SITE_PACKAGES = Path()


# --------------------------------------------------------------------- output
def log(message: str) -> None:
    elapsed = time.perf_counter() - START
    print(f"[{elapsed:7.1f}s] {message}", flush=True)


def fail(message: str) -> None:
    print(f"\nbuild failed: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def human_size(path: Path) -> str:
    try:
        size = path.stat().st_size if path.is_file() else sum(
            item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def clean(path: Path) -> None:
    if path.exists():
        log(f"removing {path}")
        shutil.rmtree(path, ignore_errors=True)


def runtime_env(root: Path | None = None,
                data: Path | None = None) -> dict[str, str]:
    """A clean environment for a portable runtime process.

    ``PYTHONPATH``/``PYTHONHOME`` are removed rather than extended: the whole
    point of the smoke tests is to prove the copied runtime can find its own
    standard library and packages. The dead proxy on this machine is cleared
    too, or Gradio fails to import before the test even starts.
    """
    env = vf_env.clean_env(root or ROOT, data)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("VIRTUAL_ENV_PROMPT", None)
    if data is not None:
        env["VOICEFORGE_DATA"] = str(data)
    else:
        env.pop("VOICEFORGE_DATA", None)
    return env


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None,
        timeout: int = 3600, quiet: bool = False,
        retries: int = 0) -> subprocess.CompletedProcess:
    """Run a command and fail the build if it cannot succeed.

    GUI self-tests occasionally die with a Windows stack-overrun status while
    the interpreter is still warming up, so those callers ask for a retry.
    """
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        log("> " + " ".join(str(part) for part in command))
        result = subprocess.run(
            [str(part) for part in command], cwd=str(cwd), env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout)
        if result.returncode == 0:
            if not quiet and result.stdout.strip():
                print(result.stdout[-3000:].rstrip(), flush=True)
            return result
        if attempt < attempts:
            log(f"command exited {result.returncode}; retrying "
                f"({attempt}/{attempts - 1})")
            time.sleep(3)
            continue
        if not quiet:
            print(result.stdout[-4000:], flush=True)
            print(result.stderr[-4000:], file=sys.stderr, flush=True)
        fail(f"command exited {result.returncode}: {command[0]}")
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------- stage
def stage_program(destination: Path) -> None:
    """Copy the program exactly as ``installer_core`` would for a checkout."""
    log(f"staging the program in {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ROOT_FILES:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied += 1
    for name in ROOT_DIRS:
        source = ROOT / name
        if not source.is_dir():
            continue
        shutil.copytree(source, destination / name,
                        ignore=IGNORE, dirs_exist_ok=True)
        copied += 1
    if not (destination / "launcher.py").is_file():
        fail("staging did not produce launcher.py")
    if not (destination / "src/voiceforge").is_dir():
        fail("staging did not produce src/voiceforge")
    log(f"staged {copied} program item(s)")


def _lib_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in PY_LIB_EXCLUDE or name == "__pycache__":
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo")):
            ignored.add(name)
    return ignored


def _site_ignore(directory: str, names: list[str]) -> set[str]:
    here = Path(directory)
    try:
        relative = here.relative_to(SITE_PACKAGES)
    except ValueError:
        relative = Path()
    ignored: set[str] = set()
    for name in names:
        lower = name.lower()
        if name == "__pycache__" or lower.endswith((".pyc", ".pyo")):
            ignored.add(name)
            continue
        if not relative.parts and (name in SITE_EXCLUDE_TOP
                                   or lower.startswith(SITE_EXCLUDE_PREFIX)):
            ignored.add(name)
            continue
        if relative.parts and relative.parts[0] == "PySide6":
            if name in PYSIDE_EXCLUDE_DIRS:
                ignored.add(name)
            elif lower.endswith(".exe"):
                ignored.add(name)
    return ignored


def assemble_runtime(destination: Path) -> None:
    """A relocatable WinPython: base interpreter + the venv's packages."""
    base = Path(sys.base_prefix)
    site = Path(sys.prefix) / "Lib" / "site-packages"
    if not (site / "PySide6").is_dir():
        fail("PySide6 is not in this interpreter. Run the builder with "
             ".venv\\Scripts\\python.exe, not the system Python.")
    destination.mkdir(parents=True, exist_ok=True)

    log(f"copying the Python {sys.version_info.major}.{sys.version_info.minor} "
        f"interpreter from {base}")
    for name in ("python.exe", "pythonw.exe", "python3.dll",
                 f"python{sys.version_info.major}{sys.version_info.minor}.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        source = base / name
        if source.is_file():
            shutil.copy2(source, destination / name)
        elif name not in ("LICENSE.txt",):
            fail(f"the base Python is missing {name}")

    dlls = base / "DLLs"
    if not dlls.is_dir():
        fail(f"the base Python is missing {dlls}")
    log("copying the standard library and extension modules")
    shutil.copytree(dlls, destination / "DLLs", ignore=_lib_ignore,
                    dirs_exist_ok=True)
    shutil.copytree(base / "Lib", destination / "Lib", ignore=_lib_ignore,
                    dirs_exist_ok=True)

    global SITE_PACKAGES
    SITE_PACKAGES = site
    target_site = destination / "Lib" / "site-packages"
    log(f"copying installed packages from {site} ({human_size(site)})")
    shutil.copytree(site, target_site, ignore=_site_ignore,
                    dirs_exist_ok=True)

    # Prove the tree is internally consistent before it is compressed. A
    # missing standard-library file here is cheap to find; discovering it in
    # the installed copy on another machine is not.
    probe = destination / "python.exe" if IS_WINDOWS else destination / "bin/python"
    if not probe.is_file():
        fail(f"the runtime has no interpreter at {probe}")
    log(f"runtime assembled: {human_size(destination)}")


# -------------------------------------------------------------------- package
def make_package_zip(stage: Path, target: Path) -> None:
    """Zip the staged folder with one top-level ``VoiceForge/`` folder."""
    log(f"creating the main package {target.name} from {human_size(stage)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            arcname = (Path(STAGE_FOLDER) / path.relative_to(stage)).as_posix()
            archive.write(path, arcname)
            count += 1
    if count == 0:
        fail("the package zip is empty")
    log(f"wrote {count} files, {human_size(target)}")


# --------------------------------------------------------------- smoke tests
def smoke_program(runtime_python: Path, program: Path, data: Path,
                  offscreen: bool = True) -> None:
    log(f"smoke-testing {program.name}")
    env = runtime_env(program, data)
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"

    imports = (
        "import PySide6, PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, "
        "PySide6.QtMultimedia, shiboken6, numpy, soundfile, edge_tts, "
        "gradio, webview, flet, pythonnet; "
        "print('imports ok', PySide6.__version__, numpy.__version__)"
    )
    result = run([str(runtime_python), "-c", imports], program, env=env,
                 timeout=300)
    if "imports ok" not in result.stdout:
        fail("the runtime did not report a successful import set")

    check = run([str(runtime_python), str(program / "launcher.py"), "--check"],
                program, env=env, timeout=300)
    try:
        import json

        report = json.loads(check.stdout)
        missing = sorted(name for name, found in report["modules"].items()
                         if not found)
    except (ValueError, KeyError):
        missing = ["<unreadable dependency report>"]
    if missing:
        fail("the portable runtime is missing front-end modules: "
             + ", ".join(missing))

    env["QT_QPA_PLATFORM"] = "offscreen"
    run([str(runtime_python), str(program / "launcher.py"), "--self-test"],
        program, env=env, timeout=300, retries=2)
    run([str(runtime_python), str(program / "desktop.py"), "--self-test"],
        program, env=env, timeout=300, retries=2)


def build_setup(payload: Path) -> Path:
    """Freeze the Qt installer with the release payload embedded."""
    log("freezing VoiceForge Setup with PyInstaller")
    setup_work = BUILD / "setup-work"
    setup_dist = BUILD / "setup-dist"
    setup_spec = BUILD / "spec"
    clean(setup_work)
    clean(setup_dist)
    clean(setup_spec)
    setup_spec.mkdir(parents=True, exist_ok=True)

    python = Path(sys.executable)
    command = [
        str(python), "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", SETUP_NAME.removesuffix(".exe"),
        "--icon", str(ROOT / "assets" / "voiceforge.ico"),
        "--add-data", f"{payload}{os.pathsep}.",
        "--add-data", f"{ROOT / 'assets'}{os.pathsep}assets",
        "--paths", str(ROOT / "src"),
        "--distpath", str(setup_dist),
        "--workpath", str(setup_work),
        "--specpath", str(setup_spec),
        str(ROOT / "setup_entry.py"),
    ]
    env = vf_env.clean_env(ROOT)
    env.pop("PYTHONPATH", None)
    run(command, ROOT, env=env, timeout=3600)

    produced = setup_dist / SETUP_NAME
    if not produced.is_file():
        fail(f"PyInstaller did not produce {produced}")
    log(f"Setup executable: {human_size(produced)}")
    return produced


def test_installer(setup_exe: Path) -> None:
    """Run the frozen installer on a throw-away copy and check the result."""
    log("testing the Setup executable from a copied location")
    clean(TEST_DIR)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    moved = TEST_DIR / setup_exe.name
    shutil.copy2(setup_exe, moved)

    app_dir = TEST_DIR / "program"
    data_dir = TEST_DIR / "library"
    log_path = TEST_DIR / "setup.log"
    env = vf_env.clean_env(TEST_DIR, data_dir)
    env["VOICEFORGE_SETUP_LOG"] = str(log_path)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("VIRTUAL_ENV", None)

    try:
        result = subprocess.run(
            [str(moved), "--auto", "--quiet", "--no-shortcuts",
             "--app-dir", str(app_dir), "--data-dir", str(data_dir)],
            cwd=str(TEST_DIR), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        fail("the Setup executable did not finish installing in 30 minutes")
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    if result.returncode != 0:
        print(log_text[-4000:], file=sys.stderr, flush=True)
        fail(f"Setup exited {result.returncode}")
    if "installed" not in log_text:
        print(log_text[-4000:], file=sys.stderr, flush=True)
        fail("Setup did not report a finished install")

    config_path = app_dir / "install.json"
    if not config_path.is_file():
        fail("the installed copy has no install.json")
    import json

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("bundled"):
        fail("install.json does not record a bundled runtime")
    runtime_python = app_dir / RUNTIME_DIR / "python.exe"
    if not runtime_python.is_file():
        fail("the installed copy has no runtime/python.exe")
    for required in ("launcher.py", "desktop.py", "uninstall.py",
                     "src/voiceforge/render.py", "assets/voiceforge.ico"):
        if not (app_dir / required).exists():
            fail(f"the installed copy is missing {required}")
    if not (data_dir / "voices").is_dir():
        fail("the installer did not create the library")

    log(f"installed {human_size(app_dir)} to a clean folder; testing it")

    # This is the real proof: use the installed runtime, not the builder's
    # Python, and run the installed copy from its own folder.
    env = runtime_env(app_dir, data_dir)
    env["QT_QPA_PLATFORM"] = "offscreen"
    run([str(runtime_python), str(app_dir / "launcher.py"), "--check"],
        app_dir, env=env, timeout=300)
    run([str(runtime_python), str(app_dir / "launcher.py"), "--self-test"],
        app_dir, env=env, timeout=300, retries=2)
    run([str(runtime_python), str(app_dir / "desktop.py"), "--self-test"],
        app_dir, env=env, timeout=300, retries=2)
    run([str(runtime_python), str(app_dir / "uninstall.py"), "--yes",
         "--keep-data", "--app-dir", str(app_dir)],
        app_dir, env=env, timeout=300)

    if (app_dir / "install.json").exists():
        fail("uninstall left install.json behind")
    if not (data_dir / "voices").is_dir():
        fail("uninstall removed the library even though --keep-data was used")
    log("install, launch and uninstall all passed; the library was kept")
    time.sleep(4)  # let the deferred folder removal finish
    clean(TEST_DIR)


# -------------------------------------------------------------------- release
def make_release(package: Path, setup_exe: Path) -> Path:
    RELEASES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = RELEASES / f"VoiceForge-{stamp}.zip"
    log(f"assembling the outer release {target.name}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        archive.write(package, package.name)
        archive.write(setup_exe, setup_exe.name)
        for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            source = ROOT / name
            if not source.is_file():
                fail(f"the release is missing {name}")
            archive.write(source, name)
        licenses = ROOT / "licenses"
        if not licenses.is_dir():
            fail("the release is missing licenses/")
        for path in sorted(licenses.rglob("*")):
            if path.is_file():
                archive.write(path, (Path("licenses")
                                     / path.relative_to(licenses)).as_posix())
    log(f"release ready: {target} ({human_size(target)})")
    with zipfile.ZipFile(target) as archive:
        names = sorted(archive.namelist())
    expected = sorted(
        [package.name, setup_exe.name, "README.md", "LICENSE",
         "THIRD_PARTY_NOTICES.md"]
        + [(Path("licenses") / path.relative_to(licenses)).as_posix()
           for path in sorted(licenses.rglob("*")) if path.is_file()])
    if names != expected:
        fail(f"the release has unexpected contents: {names}")
    log("release contents: " + ", ".join(names))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-setup", action="store_true",
                        help="stop after the portable package zip")
    parser.add_argument("--skip-tests", action="store_true",
                        help="skip the runtime smoke tests")
    parser.add_argument("--no-clean", action="store_true",
                        help="reuse the existing build folder")
    args = parser.parse_args(argv)

    vf_env.sanitize()
    if not IS_WINDOWS:
        log("warning: this builder assembles a Windows runtime; run it on "
            "Windows for a release")
    BUILD.mkdir(parents=True, exist_ok=True)
    if not args.no_clean:
        for folder in (STAGE_ROOT, PACKAGE_DIR, SETUP_DIR):
            clean(folder)
    stage = STAGE_ROOT / STAGE_FOLDER
    stage.mkdir(parents=True, exist_ok=True)

    stage_program(stage)
    assemble_runtime(stage / RUNTIME_DIR)

    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    package = PACKAGE_DIR / PACKAGE_NAME
    if not args.no_clean and package.exists():
        package.unlink()
    make_package_zip(stage, package)

    if not args.skip_tests:
        smoke_data = BUILD / "smoke-data"
        clean(smoke_data)
        smoke_data.mkdir(parents=True, exist_ok=True)
        smoke_program(stage / RUNTIME_DIR / "python.exe", stage, smoke_data)
        log("portable smoke tests passed")
        clean(smoke_data)

    if args.skip_setup:
        log("stopping after the package zip (--skip-setup)")
        return 0

    payload = BUILD / "payload.zip"
    if payload.exists():
        payload.unlink()
    log("copying the package into the installer payload")
    shutil.copy2(package, payload)
    setup_exe = build_setup(payload)
    if not args.skip_tests:
        test_installer(setup_exe)

    make_release(package, setup_exe)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
