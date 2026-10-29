"""The proxy scrubber: a dead ALL_PROXY must never reach the app or its kids."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env  # noqa: E402


class TestEnv(unittest.TestCase):
    def test_sanitize_removes_every_proxy_case(self) -> None:
        stale = {
            "ALL_PROXY": "socks5://127.0.0.1:9050",
            "all_proxy": "socks5://127.0.0.1:9050",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
        }
        with mock.patch.dict(os.environ, stale, clear=False):
            env.sanitize()
            for key in stale:
                self.assertNotIn(key, os.environ)
            self.assertEqual(os.environ["NO_PROXY"], "*")
            self.assertEqual(os.environ["no_proxy"], "*")

    def test_clean_env_sets_project_paths(self) -> None:
        with mock.patch.dict(os.environ, {"ALL_PROXY": "socks5://x:1"},
                             clear=False):
            child = env.clean_env(ROOT)
        self.assertNotIn("ALL_PROXY", child)
        self.assertEqual(child["VOICEFORGE_HOME"], str(ROOT))
        self.assertTrue(child["PYTHONPATH"].startswith(str(ROOT / "src")))

    def test_clean_env_does_not_mutate_the_parent(self) -> None:
        with mock.patch.dict(os.environ, {"ALL_PROXY": "socks5://x:1"},
                             clear=False):
            env.clean_env(ROOT)
            self.assertEqual(os.environ["ALL_PROXY"], "socks5://x:1")


if __name__ == "__main__":
    unittest.main()
