#!/usr/bin/env python3
"""Fail if private material, paid add-on code or unsafe text is in this tree.

Run locally before committing, and in CI on every push:

    python tools/check_public_tree.py

The check is deliberately conservative. It looks for the things that actually
go wrong: a signing key, a vendored add-on, a paid module copied into ``src/``,
or a document that leaks a local path or is stored as mis-encoded text.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "build", "dist",
    "releases", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".idea", ".vscode", "keys",
}
PRIVATE_NAMES = re.compile(
    r"(^signing-key\.json$|\.pem$|\.pfx$|\.p12$|^id_rsa$|^id_ed25519$)",
    re.IGNORECASE,
)
PRIVATE_MARKERS = (
    "BEGIN RSA PRIVATE KEY",
    "BEGIN PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
    "WINTERGATE_PRO_SECRET",
    "PRIVATE_KEY_D =",
    "signing-key.json",
)
ADDON_DIRS = {"addons", "pro", "_pro"}

DOC_SUFFIXES = {".md", ".txt", ".rst"}
# A path that only exists on someone's own machine. Relative paths and
# environment variables (%LOCALAPPDATA%, Path.home()) are fine.
LOCAL_PATH = re.compile(
    r"[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\\\s\"'<>]+"
    r"|/home/[A-Za-z0-9._-]+/"
    r"|/Users/[A-Za-z0-9._-]+/",
    re.IGNORECASE,
)
# UTF-8 read as cp1252 and re-encoded, e.g. "â€”" for an em dash, plus the
# replacement character left by a lossy decode.
MOJIBAKE = (
    "\u00e2\u20ac",
    "\u00e2\u2020",
    "\u00c3\u00a2",
    "\u00c3\u00a9",
    "\u00c3\u00bc",
    "\u00c3\u00b6",
    "\u00c3\u00a4",
    "\u00c3\u0178",
    "\ufffd",
)
# A PowerShell object dumped into Markdown instead of the string it held.
DUMP_MARKERS = ("PSPath", "PSProvider", '{"value"')


def iter_files(root: Path):
    checker = Path(__file__).resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.resolve() == checker:
                continue
            relative = path.relative_to(root)
        except (OSError, ValueError):
            continue
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        yield path, relative


def looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return True
    return b"\x00" in chunk


def check_text(relative: Path, raw: bytes, problems: list[str]) -> str | None:
    """Check one text file and return its decoded contents."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if relative.suffix.lower() in DOC_SUFFIXES:
            problems.append(f"not valid UTF-8: {relative}")
        text = raw.decode("utf-8", errors="replace")

    for match in LOCAL_PATH.finditer(text):
        problems.append(f"local path {match.group(0)!r}: {relative}")
        break

    if relative.suffix.lower() in DOC_SUFFIXES:
        for marker in DUMP_MARKERS:
            if marker in text:
                problems.append(f"serialized-object dump marker {marker!r}: {relative}")
                break
        for marker in MOJIBAKE:
            if marker in text:
                problems.append(f"mojibake {marker!r}: {relative}")
                break

    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    problems: list[str] = []
    for path, relative in iter_files(root):
        if PRIVATE_NAMES.search(path.name):
            problems.append(f"private key material: {relative}")
        if looks_binary(path):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        text = check_text(relative, raw, problems)
        if text is None:
            continue
        for marker in PRIVATE_MARKERS:
            if marker in text:
                problems.append(f"private marker {marker!r}: {relative}")
                break

    src = root / "src"
    if src.is_dir():
        for package in src.iterdir():
            if not package.is_dir():
                continue
            for name in ADDON_DIRS:
                candidate = package / name
                if candidate.exists():
                    problems.append(
                        f"paid add-on directory in the public tree: {candidate.relative_to(root)}"
                    )

    if problems:
        print("public-tree check FAILED:", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nMove private material to the WinterGate-Pro repository, and rewrite "
            "leaking or mis-encoded documents as UTF-8.",
            file=sys.stderr,
        )
        return 1

    print(
        "public-tree check passed "
        "(no keys, no paid add-ons, no local paths, no mojibake)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
