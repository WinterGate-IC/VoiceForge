"""Add-on discovery, licence gating and CLI contribution."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voiceforge import extensions, licensing  # noqa: E402


def licence(features):
    return licensing.License(
        product="voiceforge", edition="pro", licensee="T", email="",
        license_id="", issued=None, expires=None,
        features=frozenset(features), max_machines=1, machine=None, raw="")


class TestRegistry(unittest.TestCase):
    def test_without_licence_gated_contributions_are_denied(self):
        with mock.patch.object(licensing, "active_license", lambda **_: None):
            registry = extensions.Registry()
            registry.addon("voiceforge-pro", "1.0", features=("studio",))
            registry.add_cli("studio", lambda parser: None,
                             lambda args, project: 0,
                             help="studio", feature="studio")

            self.assertFalse(registry.allows("studio"))
            self.assertTrue(registry.allows(None))
            self.assertFalse(registry.addons[0].enabled)

    def test_only_covered_features_are_enabled(self):
        with mock.patch.object(licensing, "active_license",
                               lambda **_: licence({"studio"})):
            registry = extensions.Registry()
            registry.addon("voiceforge-pro", "1.0", features=("studio",))
            registry.addon("other", "1.0", features=("batch",))

            self.assertTrue(registry.addons[0].enabled)
            self.assertFalse(registry.addons[1].enabled)
            self.assertTrue(registry.allows("studio"))
            self.assertFalse(registry.allows("batch"))

    def test_hooks_chain_and_skip_unlicensed(self):
        with mock.patch.object(licensing, "active_license",
                               lambda **_: licence({"studio"})):
            registry = extensions.Registry()
            registry.add_hook("render.before", lambda value, ctx: value + 1,
                              feature="studio")
            registry.add_hook("render.before", lambda value, ctx: value + 10,
                              feature="batch")
            registry.add_hook("render.before", lambda value, ctx: value * 2)

            self.assertEqual(registry.run("render.before", 1), 4)

    def test_failing_hook_is_isolated(self):
        def explode(value, ctx):
            raise RuntimeError("boom")

        with mock.patch.object(licensing, "active_license",
                               lambda **_: licence({"*"})):
            registry = extensions.Registry()
            registry.add_hook("render.before", explode)
            registry.add_hook("render.before", lambda value, ctx: value + 1)

            self.assertEqual(registry.run("render.before", 1), 2)
            self.assertTrue(any("boom" in error for error in registry.errors))

    def test_cli_commands_are_added_only_when_licensed(self):
        def make_registry():
            registry = extensions.Registry()
            registry.add_cli(
                "studio",
                lambda sub: sub.add_argument("--fast", action="store_true"),
                lambda args, project: 7,
                help="studio command", feature="studio")
            return registry

        def make_parser(registry):
            parser = argparse.ArgumentParser(prog="vf")
            subparsers = parser.add_subparsers(dest="command", required=True)
            parser._voiceforge_subparsers = subparsers
            registry.apply_cli(parser)
            return parser

        with mock.patch.object(licensing, "active_license", lambda **_: None):
            parser = make_parser(make_registry())
            with self.assertRaises(SystemExit):
                parser.parse_args(["studio"])

        with mock.patch.object(licensing, "active_license",
                               lambda **_: licence({"studio"})):
            parser = make_parser(make_registry())
            args = parser.parse_args(["studio", "--fast"])
            self.assertTrue(args.fast)
            self.assertEqual(args.func(args, None), 7)

    def test_bundled_addon_imports_and_registers(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "demo_addon"
            package.mkdir()
            (package / "__init__.py").write_text(
                "def register(registry):\n"
                "    registry.addon('demo', '2.0', features=('studio',))\n",
                encoding="utf-8",
            )
            module = extensions.Registry._import_path(package)()
            registry = extensions.Registry()
            module.register(registry)

            self.assertEqual(registry.addons[0].name, "demo")
            self.assertEqual(registry.addons[0].version, "2.0")
            sys.modules.pop("voiceforge_addon_demo_addon", None)

    def test_broken_addon_does_not_break_discovery(self):
        def broken():
            raise RuntimeError("missing dependency")

        registry = extensions.Registry()
        with mock.patch.object(registry, "_candidates", lambda: [("broken", broken)]):
            registry.load()

        self.assertEqual(registry.addons, [])
        self.assertTrue(any("missing dependency" in error
                            for error in registry.errors))


if __name__ == "__main__":
    unittest.main()
