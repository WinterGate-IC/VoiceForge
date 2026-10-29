#!/usr/bin/env python3
"""Fail if private material or paid add-on code is present in this tree.

Run locally before committing, and in CI on every push:

    python tools/check_public_tree.py

The check is deliberately conservative. It looks for the things that actually
go wrong: a signing key, a vendored add-on, or a paid module copied into
``src/``.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    problems: list[str] = []
    for path, relative in iter_files(root):
        if PRIVATE_NAMES.search(path.name):
            problems.append(f"private key material: {relative}")
        if not looks_binary(path):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
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
        print("\nMove private material to the WinterGate-Pro repository.", file=sys.stderr)
        return 1

    print("public-tree check passed (no keys, no paid add-ons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
