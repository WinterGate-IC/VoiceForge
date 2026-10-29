"""Licence verification: signature, expiry, product and machine binding."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import licensing  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BEFORE_EXPIRY = dt.date(2019, 6, 1)
AFTER_EXPIRY = dt.date(2026, 10, 28)


def token(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").strip()


class TestParsing(unittest.TestCase):
    def test_valid_signature_parses(self):
        licence = licensing.parse_token(token("expired.license"), today=BEFORE_EXPIRY)
        self.assertEqual(licence.product, "voiceforge")
        self.assertEqual(licence.licensee, "Test Fixture")
        self.assertEqual(licence.features, {"studio"})
        self.assertTrue(licence.allows("studio"))
        self.assertTrue(licence.allows("*"))
        self.assertFalse(licence.allows("batch"))

    def test_expired_token_is_rejected(self):
        with self.assertRaisesRegex(licensing.LicenseError, "expired"):
            licensing.parse_token(token("expired.license"), today=AFTER_EXPIRY)

    def test_allow_expired_is_opt_in(self):
        licence = licensing.parse_token(
            token("expired.license"), today=AFTER_EXPIRY, allow_expired=True)
        self.assertTrue(licence.expired())

    def test_tampered_payload_fails_signature(self):
        prefix, payload, signature = token("expired.license").split(".")
        tampered = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB")
        with self.assertRaisesRegex(licensing.LicenseError, "signature"):
            licensing.parse_token(f"{prefix}.{tampered}.{signature}", today=BEFORE_EXPIRY)

    def test_wrong_product_is_rejected(self):
        with self.assertRaisesRegex(licensing.LicenseError, "not a voiceforge licence|not 'voiceforge'"):
            licensing.parse_token(token("other-product.license"), today=BEFORE_EXPIRY)

    def test_machine_binding(self):
        bound = token("expired-bound.license")
        licence = licensing.parse_token(
            bound, machine="test-machine-0001", today=BEFORE_EXPIRY)
        self.assertEqual(licence.machine, "test-machine-0001")
        with self.assertRaisesRegex(licensing.LicenseError, "different machine"):
            licensing.parse_token(
                bound, machine="some-other-machine", today=BEFORE_EXPIRY)
        # Omitting the machine must fail closed, not skip the binding check.
        with self.assertRaisesRegex(licensing.LicenseError, "different machine"):
            licensing.parse_token(bound, today=BEFORE_EXPIRY)

    def test_malformed_tokens_are_rejected(self):
        for value in ("", "nope", "VF1.aaa", "VF1.aaa.bbb.ccc", "XX1.aaa.bbb"):
            with self.subTest(value=value):
                with self.assertRaises(licensing.LicenseError):
                    licensing.parse_token(value)


class TestGating(unittest.TestCase):
    def _licence(self, features):
        return licensing.License(
            product="voiceforge", edition="pro", licensee="T", email="",
            license_id="", issued=None, expires=None,
            features=frozenset(features), max_machines=1, machine=None, raw="")

    def test_require_without_licence(self):
        with mock.patch.object(licensing, "active_license", lambda **_: None):
            with self.assertRaisesRegex(licensing.LicenseError, "needs a valid licence"):
                licensing.require("studio")
            self.assertFalse(licensing.allows("studio"))

    def test_require_with_licence(self):
        licence = self._licence({"studio"})
        with mock.patch.object(licensing, "active_license", lambda **_: licence):
            self.assertIs(licensing.require("studio"), licence)
            with self.assertRaisesRegex(licensing.LicenseError, "does not include"):
                licensing.require("batch")

    def test_licensed_decorator_blocks_before_running(self):
        calls = []

        @licensing.licensed("studio")
        def work(value):
            calls.append(value)
            return value * 2

        with mock.patch.object(licensing, "active_license", lambda **_: None):
            with self.assertRaises(licensing.LicenseError):
                work(1)
            self.assertEqual(calls, [])

        with mock.patch.object(licensing, "active_license",
                               lambda **_: self._licence({"studio"})):
            self.assertEqual(work(2), 4)
            self.assertEqual(calls, [2])

    def test_install_and_revoke(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "license.key"
            fake = licensing.License(
                product="voiceforge", edition="pro", licensee="T", email="",
                license_id="", issued=None, expires=None,
                features=frozenset({"*"}), max_machines=1, machine=None,
                raw="VF1.fake.sig")
            with mock.patch.object(licensing, "default_license_path", lambda: target), \
                    mock.patch.dict("os.environ", {"VOICEFORGE_LICENSE": ""}), \
                    mock.patch.object(licensing, "parse_token", lambda *a, **k: fake):
                written = licensing.install_license("anything")
                self.assertEqual(written, target)
                self.assertEqual(target.read_text(encoding="utf-8").strip(),
                                 "VF1.fake.sig")
                self.assertTrue(licensing.revoke_license())
                self.assertFalse(target.exists())
                self.assertFalse(licensing.revoke_license())

    def test_describe_status_without_licence(self):
        with mock.patch.object(licensing, "active_license", lambda **_: None):
            status = licensing.describe_status()
            self.assertFalse(status["licensed"])
            self.assertEqual(status["edition"], "community")
            self.assertTrue(status["machine"])

    def test_machine_id_is_stable(self):
        first = licensing.machine_id()
        self.assertEqual(first, licensing.machine_id())
        self.assertEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main()
