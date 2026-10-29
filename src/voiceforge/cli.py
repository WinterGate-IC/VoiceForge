"""VoiceForge command line interface."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import library
from . import presets as presets_mod
from . import seed as seed_mod
from . import styles as styles_mod
from .engines import EngineError, get_engine, list_voices
from .project import Project, find_root
from .render import FORMAT_LABELS, normalize_format, output_dir as _output_dir
from .render import render_text as _render
from .render import slug as _slug
from .settings import PARAMS, ParamError, defaults, spec

VOICE_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".ogg")


# ---------------------------------------------------------------- helpers
def _engines_status(project: Project, reference: str = "") -> list[tuple[str, bool, str]]:
    rows = []
    for name in ("edge", "clone"):
        ok, reason = get_engine(name, project.root).available(reference)
        rows.append((name, ok, reason))
    return rows


def _read_text_arg(parts: list[str]) -> str:
    text = " ".join(parts).strip()
    if text == "-":
        text = sys.stdin.read().strip()
    if not text:
        raise ValueError("no text to speak (pass it as an argument, or '-' for stdin)")
    return text


# ---------------------------------------------------------------- commands
def cmd_set(args: argparse.Namespace, project: Project) -> int:
    if not args.pairs:
        raise ValueError("nothing to set. Example: vf set rate=+10% pitch=-20Hz")
    for row in project.set_many(args.pairs):
        if row["noop"]:
            print(f"  {row['param']}: already {spec(row['param']).fmt(row['new'])}")
        else:
            print(f"  {row['param']}: {spec(row['param']).fmt(row['old'])} -> "
                  f"{spec(row['param']).fmt(row['new'])}")
    print(f"saved ({project.history.length - 1} change(s) in history)")
    return 0


def cmd_get(args: argparse.Namespace, project: Project) -> int:
    settings = project.settings
    dflt = defaults()
    if args.json:
        print(json.dumps(settings, indent=2))
        return 0

    print(f"project: {project.root}")
    print(f"engine:  {project.active_engine()}   "
          f"({'reference voice set' if settings.get('reference') else 'no reference voice'})")
    print()
    width = max(len(n) for n in PARAMS)
    for name, sp in PARAMS.items():
        if not args.all and sp.engines == ("clone",) and name not in ("reference",):
            continue
        mark = "*" if settings.get(name) != dflt.get(name) else " "
        print(f" {mark} {name.ljust(width)}  {sp.fmt(settings.get(name)):<12} {sp.help}")
    print("\n * = changed from default")
    return 0


def cmd_history(args: argparse.Namespace, project: Project) -> int:
    rows = project.history.describe()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        marker = "->" if row["current"] else "  "
        if row["index"] == 0:
            print(f" {marker} [{row['index']:>2}] {row['label']}")
        else:
            print(f" {marker} [{row['index']:>2}] {row['label']}: "
                  f"{row['old']} -> {row['new']}   ({row['at']})")
    return 0


def cmd_undo(args: argparse.Namespace, project: Project) -> int:
    if args.param:
        name = args.param.strip().lower().replace("-", "_")
        spec(name)
        value = project.history.undo_param(name)
        project.save()
        print(f"reverted {name} to {spec(name).fmt(value)}")
        return 0

    if args.to is not None:
        cursor = project.history.undo_to(args.to)
        project.save()
        print(f"jumped to snapshot {cursor}")
        return 0

    cursor = project.history.undo(steps=args.steps)
    project.save()
    print(f"undid {args.steps} step(s), now at snapshot {cursor}")
    return 0


def cmd_redo(args: argparse.Namespace, project: Project) -> int:
    cursor = project.history.redo(steps=args.steps)
    project.save()
    print(f"redid {args.steps} step(s), now at snapshot {cursor}")
    return 0


def cmd_reset(args: argparse.Namespace, project: Project) -> int:
    if args.param:
        name = args.param.strip().lower().replace("-", "_")
        value = project.reset_param(name)
        print(f"{name} reset to default {spec(name).fmt(value)}")
        return 0
    project.reset_all()
    print("all settings reset to defaults (history cleared)")
    return 0


def cmd_preset(args: argparse.Namespace, project: Project) -> int:
    if args.action == "save":
        p = presets_mod.save(project.root, args.name, project.settings)
        print(f"saved preset {args.name!r} -> {p.relative_to(project.root)}")
    elif args.action == "load":
        values = presets_mod.load(project.root, args.name)
        for row in project.set_many([f"{k}={v}" for k, v in values.items()]):
            if not row["noop"]:
                print(f"  {row['param']}: {spec(row['param']).fmt(row['old'])} -> "
                      f"{spec(row['param']).fmt(row['new'])}")
        print(f"loaded preset {args.name!r}")
    elif args.action == "delete":
        print("deleted" if presets_mod.delete(project.root, args.name) else "no such preset")
    else:
        rows = presets_mod.listing(project.root)
        if not rows:
            print("no presets saved yet (vf preset save <name>)")
        for name, p in rows:
            print(f"  {name:<24} {p.name}")
    return 0


def cmd_voices(args: argparse.Namespace, project: Project) -> int:
    rows = list_voices()
    if args.lang:
        rows = [r for r in rows if r["locale"].lower().startswith(args.lang.lower())]
    if args.gender:
        rows = [r for r in rows if r["gender"].lower() == args.gender.lower()]
    if args.query:
        q = args.query.lower()
        rows = [r for r in rows if q in r["short"].lower() or q in r["name"].lower()]
    total = len(rows)
    for r in rows[: args.limit]:
        print(f"  {r['short']:<44} {r['gender']:<7} {r['locale']}")
    if total > args.limit:
        print(f"\n  ... {total - args.limit} more (raise --limit, or filter with --lang/--query)")
    print(f"\n  {total} voice(s). Set one with:  vf set voice=<short-name>")
    return 0


def cmd_style(args: argparse.Namespace, project: Project) -> int:
    if args.action == "list":
        active = project.settings.get("effect", "none")
        for st in styles_mod.listing():
            mark = "*" if st.effect == active else " "
            params = ", ".join(f"{k}={v}" for k, v in st.params.items()) or "no param changes"
            print(f" {mark} {st.name:<15} [{st.effect:<11}] {st.description}")
            print(f"   {'':<15}  {params}")
        print("\n * = effect chain currently active.   vf style apply <name>")
        return 0

    st = styles_mod.get(args.name)
    rows = project.set_many(styles_mod.as_pairs(st), label=f"style {st.name}")
    for row in rows:
        if not row["noop"]:
            print(f"  {row['param']}: {spec(row['param']).fmt(row['old'])} -> "
                  f"{spec(row['param']).fmt(row['new'])}")
    if not any(not r["noop"] for r in rows):
        print("  (already at this style)")
    print(f"style {st.name!r} applied - {st.description}")
    return 0


def cmd_voice(args: argparse.Namespace, project: Project) -> int:
    action = args.action

    if action == "list":
        rows = library.listing(project.root)
        if not rows:
            print("library is empty. Build one from your current settings:\n"
                  "  vf voice create my-voice\n"
                  "  vf voice add my-voice my-recording.mp3   (makes it cloneable)")
            return 0
        active = project.settings.get("reference", "")
        print(f"  {'NAME':<22} {'KIND':<9} {'RATE':>6} {'PITCH':>7} {'SAMPLE':<22} NOTES")
        for r in rows:
            mark = "*" if r["name"] == active else " "
            print(f" {mark}{r['name']:<22} {r['kind']:<9} {r['rate']:>6} {r['pitch']:>7} "
                  f"{r['audio']:<22} {r['notes']}")
        print("\n * = currently active.   vf voice use <name>")
        return 0

    if action == "create":
        prof = library.create(project.root, args.name, project.settings,
                              notes=args.notes or "", overwrite=args.overwrite)
        print(f"created voice {prof.name!r} ({prof.kind}) from current settings")
        if args.sample:
            dest = library.attach_sample(project.root, prof.name, Path(args.sample))
            print(f"attached reference audio -> {dest.relative_to(project.root)}")
            print(f"voice {prof.name!r} is now cloneable (engine: clone)")
        else:
            print("add a recording of your own voice to make it cloneable:\n"
                  f"  vf voice add {prof.name} path\\to\\sample.mp3")

    elif action == "add":
        if not args.file:
            raise ValueError("usage: vf voice add <name> <sample.mp3>")
        dest = library.attach_sample(project.root, args.name, Path(args.file))
        print(f"attached {dest.name} to voice {library.slug(args.name)!r}")
        print(f"activate it with:  vf set reference={library.slug(args.name)}")

    elif action == "use":
        prof = library.load(project.root, args.name)
        pairs = [f"{k}={v}" for k, v in prof.settings.items() if k in PARAMS]
        if pairs:
            for row in project.set_many(pairs):
                if not row["noop"]:
                    print(f"  {row['param']}: {spec(row['param']).fmt(row['old'])} -> "
                          f"{spec(row['param']).fmt(row['new'])}")
        has_audio = library.audio_in(project.root, prof.name) is not None
        project.set_many([f"reference={prof.name if has_audio else ''}"])
        print(f"active voice: {prof.name} ({'cloned' if has_audio else 'designed'})")
        if has_audio:
            ok, reason = get_engine("clone", project.root).available(prof.name)
            if not ok:
                print(f"  note: {reason}")

    elif action == "update":
        prof = library.update(project.root, args.name, project.settings, notes=args.notes)
        print(f"voice {prof.name!r} re-saved from current settings")

    elif action == "show":
        prof = library.load(project.root, args.name)
        audio = library.audio_in(project.root, prof.name)
        print(f"name:    {prof.name}")
        print(f"kind:    {prof.kind}")
        print(f"sample:  {audio.name if audio else '(none - designed voice)'}")
        print(f"created: {prof.created}")
        print(f"updated: {prof.updated}")
        if prof.notes:
            print(f"notes:   {prof.notes}")
        print("\nsettings:")
        for k, v in prof.settings.items():
            if k in PARAMS:
                print(f"  {k:<20} {spec(k).fmt(v)}")

    elif action == "rename":
        if not args.to:
            raise ValueError("usage: vf voice rename <old-name> --to <new-name>")
        prof = library.rename(project.root, args.name, args.to)
        if project.settings.get("reference") == library.slug(args.name):
            project.set_many([f"reference={prof.name}"])
        print(f"renamed to {prof.name!r}")

    elif action == "seed":
        created = seed_mod.restore(project.root)
        if created:
            print(f"restored {len(created)} default voice(s): {', '.join(created)}")
        else:
            print("every default voice is already in the library")

    elif action == "delete":
        if project.settings.get("reference") == library.slug(args.name):
            project.reset_param("reference")
        print("deleted" if library.delete(project.root, args.name) else "no such voice")

    return 0


def cmd_say(args: argparse.Namespace, project: Project) -> int:
    text = _read_text_arg(args.text)
    overrides = {"voice": args.edge_voice} if args.edge_voice else {}
    path, engine = _render(project, text, args.out, args.engine, overrides,
                           profile=args.voice,
                           output_format=normalize_format(args.format))
    _report(path, project, engine)
    if args.open:
        os.startfile(str(path))  # noqa: S606 - Windows shell open
    return 0


def cmd_file(args: argparse.Namespace, project: Project) -> int:
    src = Path(args.path).expanduser()
    if not src.exists():
        raise ValueError(f"no such file: {src}")
    content = src.read_text(encoding="utf-8", errors="replace")
    chunks = [c.strip() for c in re.split(r"\n\s*\n", content) if c.strip()]
    if not chunks:
        raise ValueError("file contains no text")

    outdir = Path(args.outdir).expanduser() if args.outdir else _output_dir(project)
    if not outdir.is_absolute():
        outdir = project.root / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    prefix = args.prefix or _slug(src.stem, 24)
    print(f"{len(chunks)} chunk(s) from {src.name}")
    total_bytes = 0
    for i, chunk in enumerate(chunks, start=1):
        path, _engine = _render(project, chunk, outdir / f"{prefix}-{i:02d}",
                                args.engine, {}, profile=args.voice,
                                output_format=normalize_format(args.format))
        total_bytes += path.stat().st_size
        print(f"  {i:02d}  {path.name:<40} {path.stat().st_size / 1024:>8.1f} KB  "
              f"{chunk[:48]!r}")
    print(f"\n{len(chunks)} file(s), {total_bytes / 1048576:.2f} MB -> {outdir}")
    return 0


def cmd_demo(args: argparse.Namespace, project: Project) -> int:
    text = ("This is VoiceForge. Every setting you change is tracked, so you can undo "
            "one knob, undo everything, or jump straight back to a saved preset.")
    path, engine = _render(project, text, None, args.engine, {},
                           profile=args.voice,
                           output_format=normalize_format(args.format))
    _report(path, project, engine)
    return 0


def _report(path: Path, project: Project, engine: str) -> None:
    size = path.stat().st_size / 1024
    try:
        shown = path.relative_to(project.root)
    except ValueError:
        shown = path
    print(f"wrote {shown}  ({size:.1f} KB, {engine} engine)")


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vf", description="VoiceForge - a custom voice you can actually tune.")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=func)
        return sp

    s = add("set", cmd_set, "change one or more settings")
    s.add_argument("pairs", nargs="*", help="name=value, e.g. rate=+10% pitch=-20Hz")

    s = add("get", cmd_get, "show current settings")
    s.add_argument("--all", action="store_true", help="include clone-engine parameters")
    s.add_argument("--json", action="store_true")

    s = add("history", cmd_history, "list every change and where you are")
    s.add_argument("--json", action="store_true")

    s = add("undo", cmd_undo, "step back one change, N changes, or to a snapshot")
    s.add_argument("--steps", type=int, default=1)
    s.add_argument("--to", type=int, default=None, help="jump to snapshot index")
    s.add_argument("--param", default=None, help="revert only this parameter")

    s = add("redo", cmd_redo, "step forward again")
    s.add_argument("--steps", type=int, default=1)

    s = add("reset", cmd_reset, "restore defaults (one param, or everything)")
    s.add_argument("--param", default=None)

    s = add("preset", cmd_preset, "save / load / list named presets")
    s.add_argument("action", choices=["save", "load", "list", "delete"])
    s.add_argument("name", nargs="?", default="")

    s = add("voices", cmd_voices, "list available edge voices")
    s.add_argument("--lang", default=None, help="locale prefix, e.g. en, en-GB, de")
    s.add_argument("--gender", default=None, choices=["Male", "Female"])
    s.add_argument("--query", default=None)
    s.add_argument("--limit", type=int, default=40)

    s = add("style", cmd_style, "apply a signature style (scary, hacker, ...)")
    s.add_argument("action", choices=["list", "apply"])
    s.add_argument("name", nargs="?", default="")

    s = add("voice", cmd_voice, "build, edit and manage your voice library")
    s.add_argument("action",
                   choices=["create", "add", "use", "update", "rename",
                            "show", "list", "delete", "seed"])
    s.add_argument("name", nargs="?", default="")
    s.add_argument("file", nargs="?", default="", help="sample audio (for `add`)")
    s.add_argument("--sample", default=None, help="attach a recording while creating")
    s.add_argument("--notes", default=None)
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--to", default=None, help="new name (for `rename`)")

    s = add("say", cmd_say, "render text to an audio download")
    s.add_argument("text", nargs="+")
    s.add_argument("--out", default=None)
    s.add_argument("--format", choices=list(FORMAT_LABELS), default=None,
                   help="download format (default: your preference, MP3)")
    s.add_argument("--engine", choices=["edge", "clone"], default=None)
    s.add_argument("--voice", default=None, help="library voice to use for this clip")
    s.add_argument("--edge-voice", default=None,
                   help="raw edge voice short name for this clip")
    s.add_argument("--open", action="store_true", help="open the file when finished")

    s = add("file", cmd_file, "render a text file, one download per paragraph")
    s.add_argument("path")
    s.add_argument("--outdir", default=None)
    s.add_argument("--prefix", default=None)
    s.add_argument("--format", choices=list(FORMAT_LABELS), default=None,
                   help="download format (default: your preference, MP3)")
    s.add_argument("--engine", choices=["edge", "clone"], default=None)
    s.add_argument("--voice", default=None, help="library voice to use")

    s = add("demo", cmd_demo, "render a short sample with current settings")
    s.add_argument("--format", choices=list(FORMAT_LABELS), default=None,
                   help="download format (default: your preference, MP3)")
    s.add_argument("--engine", choices=["edge", "clone"], default=None)
    s.add_argument("--voice", default=None, help="library voice to use")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = Project.load(find_root())
    seed_mod.ensure_defaults(project.root)
    try:
        return args.func(args, project)
    except (ParamError, ValueError, EngineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
