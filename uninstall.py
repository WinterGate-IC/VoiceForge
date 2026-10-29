"""VoiceForge uninstaller.

Removes an *installed* copy - the program folder, the shortcuts recorded in
``install.json`` and, only if you ask for it, your voices.

    python uninstall.py                 ask first
    python uninstall.py --yes           keep your voices, no questions
    python uninstall.py --yes --purge-data
    python uninstall.py --app-dir "D:\\Apps\\VoiceForge" --yes

The check for ``install.json`` is deliberate: this script refuses to touch a
source checkout, where deleting the "program folder" would delete the project
you are working on. Uninstall an installed copy from its own folder, or point
``--app-dir`` at it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env as vf_env  # noqa: E402
from voiceforge import installer_core as core  # noqa: E402
from voiceforge import paths  # noqa: E402

vf_env.sanitize()

TITLE = "Uninstall VoiceForge"


def _describe(app_dir: Path, data_dir: Path | None) -> str:
    lines = [f"Program folder:\n    {app_dir}"]
    if data_dir is not None:
        lines.append(
            f"Your library (voices, downloads and saved text):\n    {data_dir}\n"
            "This folder is kept unless you choose to remove it.")
    return "\n\n".join(lines)


def _ask_gui(app_dir: Path, data_dir: Path | None) -> tuple[bool, bool] | None:
    """Return (proceed, purge_data) or None when the user cancels."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return None

    from voiceforge import qt_theme

    app = QApplication.instance() or QApplication([TITLE])
    qt_theme.apply(app, "midnight")
    box = QMessageBox()
    box.setWindowTitle(TITLE)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText("Remove VoiceForge from this computer?")
    box.setInformativeText(_describe(app_dir, data_dir))
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    if box.exec() != QMessageBox.StandardButton.Yes:
        return None

    purge = False
    if data_dir is not None:
        second = QMessageBox()
        second.setWindowTitle(TITLE)
        second.setIcon(QMessageBox.Icon.Question)
        second.setText("Delete your saved voices and audio too?")
        second.setInformativeText(
            f"Choose No to keep everything in:\n    {data_dir}\n\n"
            "Your voices, downloads, saved text and settings stay exactly "
            "where they are, ready for a reinstall.")
        second.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        second.setDefaultButton(QMessageBox.StandardButton.No)
        purge = second.exec() == QMessageBox.StandardButton.Yes
    return True, purge


def _ask_console(app_dir: Path, data_dir: Path | None) -> tuple[bool, bool] | None:
    print(TITLE)
    print("=" * len(TITLE))
    print(_describe(app_dir, data_dir))
    try:
        answer = input("\nRemove the program? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer not in ("y", "yes"):
        return None
    purge = False
    if data_dir is not None:
        try:
            answer = input(
                "Delete your saved voices and audio as well? [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        purge = answer in ("y", "yes")
    return True, purge


def run(app_dir: Path, proceed: bool | None, purge: bool) -> int:
    config_path = app_dir / core.CONFIG_NAME
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = None

    if not isinstance(config, dict) or not config:
        print(
            f"No {core.CONFIG_NAME} in {app_dir}.\n\n"
            "This does not look like an installed copy - it may be the source "
            "checkout. To remove an installed VoiceForge, run uninstall.py "
            "from its program folder, or pass --app-dir.",
            file=sys.stderr)
        return 2

    data_dir = Path(config["data_dir"]) if config.get("data_dir") else None
    if proceed is None:
        proceed = False

    if proceed:
        kept = None if purge else data_dir
        result = core.uninstall(app_dir, purge_data=purge, log=print)
        print(f"\nRemoved {len(result['removed'])} item(s).")
        if kept is not None:
            print(f"Your library is still at {kept}")
        elif data_dir is not None:
            print(f"Your library at {data_dir} was removed.")
        if app_dir.is_dir():
            core.schedule_folder_removal(app_dir)
            print(f"{app_dir} will be deleted when this window closes.")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove an installed copy of VoiceForge.")
    parser.add_argument("--app-dir", type=Path, default=None,
                        help="the installed program folder (default: this one)")
    parser.add_argument("--yes", action="store_true",
                        help="do not ask for confirmation")
    parser.add_argument("--purge-data", action="store_true",
                        help="also delete voices, downloads, text and settings")
    parser.add_argument("--keep-data", action="store_true",
                        help="keep the library even when asking")
    args = parser.parse_args(argv)

    app_dir = (args.app_dir or paths.app_dir(__file__)).expanduser().absolute()
    config_path = app_dir / core.CONFIG_NAME
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    data_dir = Path(config["data_dir"]) if config.get("data_dir") else None

    if args.yes:
        proceed = True
        purge = bool(args.purge_data) and not args.keep_data
    else:
        answer = _ask_gui(app_dir, data_dir)
        if answer is None:
            answer = _ask_console(app_dir, data_dir)
        if answer is None:
            print("Cancelled.")
            return 1
        proceed, asked_purge = answer
        purge = bool(args.purge_data) or (asked_purge and not args.keep_data)

    return run(app_dir, proceed, purge)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
