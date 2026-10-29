"""Flet front-end smoke test without opening a window.

main(page) only talks to a small part of the Page API, so a stub page is
enough to prove the UI builds, is dark, and that every control it touches
still exists in the pinned Flet version.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import flet as ft  # noqa: E402

import flet_app  # noqa: E402


class FakeWindow:
    width = height = min_width = min_height = 0


class FakePage:
    def __init__(self) -> None:
        self.controls: list = []
        self.overlay: list = []
        self.window = FakeWindow()
        self.title = ""
        self.theme_mode = None
        self.bgcolor = None
        self.theme = None
        self.dark_theme = None
        self.padding = 0

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self) -> None:
        pass

    def run_thread(self, fn) -> None:
        fn()

    def open(self, control) -> None:
        pass

    def close(self, control) -> None:
        pass

    def launch_url(self, url: str) -> None:
        pass


class TestFletUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls._original_root = flet_app.DATA
        flet_app.DATA = cls.root

    @classmethod
    def tearDownClass(cls) -> None:
        flet_app.DATA = cls._original_root
        cls.tmp.cleanup()

    def test_page_builds_dark(self) -> None:
        page = FakePage()
        flet_app.main(page)

        self.assertEqual(page.bgcolor, "#0b1220")
        self.assertEqual(page.theme_mode, ft.ThemeMode.DARK)
        self.assertEqual(len(page.controls), 3)
        self.assertTrue(any(isinstance(c, ft.Tabs) for c in page.controls))
        self.assertTrue(page.overlay, "file picker should be in the overlay")

    def test_default_voices_seeded_into_dropdown(self) -> None:
        page = FakePage()
        flet_app.main(page)
        rows = [c for c in flet_app.library.listing(self.root)]
        self.assertGreaterEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
