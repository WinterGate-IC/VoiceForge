"""VoiceForge Flet - a second native front-end, rendered by Flutter.

Why have two native UIs? Qt is the primary one; this is deliberately an
independent implementation of the same core, which is useful when a Qt
multimedia plugin misbehaves on a particular machine, and it proves the core
is genuinely UI-agnostic.

    python flet_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env as vf_env  # noqa: E402

vf_env.sanitize()

import flet as ft  # noqa: E402

from voiceforge import library, paths, seed, styles, themes  # noqa: E402
from voiceforge.preferences import Preferences  # noqa: E402
from voiceforge.effects import CHAINS  # noqa: E402
from voiceforge.project import Project  # noqa: E402
from voiceforge.render import (  # noqa: E402
    FORMAT_LABELS, normalize_format, output_dir, render_text)
from voiceforge.settings import PARAMS  # noqa: E402
from voiceforge.textsplit import plan as speech_plan  # noqa: E402

DATA = paths.data_root(__file__)
NONE = "(no library voice)"


def _int(value) -> int:
    digits = "".join(ch for ch in str(value) if ch in "+-0123456789")
    try:
        return int(digits)
    except ValueError:
        return 0


def edge_voice_choices() -> list[str]:
    import json

    cache = DATA / ".cache" / "edge_voices.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return ["en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural",
            "en-GB-RyanNeural", "en-GB-SoniaNeural"]


def main(page: ft.Page) -> None:
    page.title = "VoiceForge (Flet)"
    page.theme_mode = ft.ThemeMode.DARK
    scheme = Preferences.load(DATA)["theme"]
    c = themes.get(scheme)
    page.bgcolor = c["WINDOW"]
    page.theme = ft.Theme(color_scheme_seed=c["ACCENT"])
    page.dark_theme = ft.Theme(color_scheme_seed=c["ACCENT"])
    page.padding = 22
    page.window.width = 1360
    page.window.height = 920
    page.window.min_width = 1040
    page.window.min_height = 700

    seed.ensure_defaults(DATA)

    def project() -> Project:
        return Project.load(DATA)

    def note(message: str) -> None:
        status.value = message
        page.update()

    # ------------------------------------------------------------- speak tab
    script = ft.TextField(
        multiline=True, min_lines=14, max_lines=32, height=340,
        label="Script - paste any amount of text",
        hint_text="A line, a chapter, an audiobook. Long text is split "
                  "automatically and stitched back together.",
        on_change=lambda e: update_plan(),
    )
    plan_label = ft.Text("", size=11, color=c["TEXT_MUTED"])

    style = ft.Dropdown(
        label="Style preset", width=240,
        options=[ft.dropdown.Option(s.name) for s in styles.listing()],
        value="clean",
    )
    voice = ft.Dropdown(label="Your voice library", width=240,
                        options=[ft.dropdown.Option(NONE)])
    edge_voice = ft.Dropdown(
        label="Edge voice (used when no recording is attached)",
        options=[ft.dropdown.Option(v) for v in edge_voice_choices()],
        value=edge_voice_choices()[0],
    )

    rate = ft.Slider(min=-50, max=50, divisions=100, value=0, label="{value}%")
    pitch = ft.Slider(min=-60, max=60, divisions=120, value=0, label="{value}Hz")
    volume = ft.Slider(min=-50, max=50, divisions=100, value=0, label="{value}%")
    speed = ft.Slider(min=0.5, max=2.0, divisions=30, value=1.0, label="{value}x")
    temperature = ft.Slider(min=0.05, max=1.5, divisions=29, value=0.75,
                            label="{value}")
    top_k = ft.Slider(min=1, max=200, divisions=199, value=50, label="{value}")
    top_p = ft.Slider(min=0.1, max=1.0, divisions=18, value=0.85, label="{value}")
    repetition = ft.Slider(min=1.0, max=20.0, divisions=38, value=5.0,
                           label="{value}")
    effect = ft.Dropdown(label="Effect chain", width=220,
                         options=[ft.dropdown.Option(c) for c in CHAINS],
                         value="none")
    download_format = ft.Dropdown(
        label="Download format", width=220,
        options=[ft.dropdown.Option(key=key, text=label)
                 for key, label in FORMAT_LABELS.items()],
        value=normalize_format(Preferences.load(DATA)["output_format"]))

    status = ft.Text("Ready. Paste a script, pick a voice, press Generate.",
                     selectable=True)
    result = ft.Text("", selectable=True, size=11, color=c["TEXT_MUTED"])
    play_btn = ft.FilledButton("Play last render", disabled=True)
    open_out = ft.TextButton("Open downloads folder")

    generate_btn = ft.FilledButton("Generate MP3", height=44)

    def update_plan() -> None:
        info = speech_plan(script.value or "")
        plan_label.value = info.describe() if info.characters else ""
        page.update()

    def apply_style(name: str) -> None:
        try:
            st = styles.get(name)
        except styles.StyleError:
            return
        merged = dict(project().settings)
        merged.update(st.params)
        merged["effect"] = st.effect
        load_settings(merged)

    def load_settings(settings: dict) -> None:
        rate.value = _int(settings.get("rate"))
        pitch.value = _int(settings.get("pitch"))
        volume.value = _int(settings.get("volume"))
        speed.value = float(settings.get("speed", 1.0))
        temperature.value = float(settings.get("temperature", 0.75))
        top_k.value = int(settings.get("top_k", 50))
        top_p.value = float(settings.get("top_p", 0.85))
        repetition.value = float(settings.get("repetition_penalty", 5.0))
        chosen = settings.get("effect", "none")
        if chosen in CHAINS:
            effect.value = chosen
        page.update()

    def collect() -> dict:
        values = {
            "rate": f"{int(rate.value):+d}%",
            "pitch": f"{int(pitch.value):+d}Hz",
            "volume": f"{int(volume.value):+d}%",
            "speed": round(float(speed.value), 2),
            "temperature": round(float(temperature.value), 2),
            "top_k": int(top_k.value),
            "top_p": round(float(top_p.value), 2),
            "repetition_penalty": round(float(repetition.value), 1),
            "effect": effect.value or "none",
            "voice": edge_voice.value or "en-US-AndrewMultilingualNeural",
        }
        name = voice.value if voice.value != NONE else ""
        values["reference"] = name if name and library.audio_in(DATA, name) else ""
        return values

    def do_generate(_=None) -> None:
        text = (script.value or "").strip()
        if not text:
            note("Paste a script first.")
            return
        if generate_btn.disabled:
            return
        info = speech_plan(text)
        generate_btn.disabled = True
        note(f"Rendering {info.chunks} part(s)…")
        values = collect()

        def work() -> None:
            try:
                proj = project()
                proj.apply_settings(values, label="generate")
                path, engine = render_text(
                    proj, text,
                    output_format=normalize_format(download_format.value))
                play_btn.data = str(path)
                play_btn.disabled = False
                seconds = 0
                result.value = f"{path}  ·  {path.stat().st_size / 1024:.0f} KB"
                status.value = (f"Rendered with {engine} + {values['effect']}. "
                                "Press Play to open it in your audio player.")
            except Exception as exc:
                status.value = f"Could not render: {exc}"
            finally:
                generate_btn.disabled = False
                refresh_history()
                page.update()

        page.run_thread(work)

    def play_last(_=None) -> None:
        if play_btn.data:
            page.launch_url(Path(play_btn.data).as_uri())

    style.on_change = lambda e: apply_style(style.value)

    # ----------------------------------------------------------- voices tab
    voice_list = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
    new_name = ft.TextField(label="New voice name", width=260)
    new_notes = ft.TextField(label="Notes", width=320)
    sample_path = ft.TextField(
        label="Recording path (optional, 6-20s of your own voice)", expand=True)
    picker = ft.FilePicker()

    def pick_sample(_=None) -> None:
        picker.pick_files(allow_multiple=False,
                          allowed_extensions=["wav", "mp3", "flac", "m4a", "ogg"])

    def picked(event) -> None:
        files = event.files or []
        if files:
            sample_path.value = files[0].path
            page.update()

    picker.on_result = picked

    def refresh_voices() -> None:
        voice_list.controls.clear()
        rows = library.listing(DATA)
        if not rows:
            voice_list.controls.append(ft.Text("No saved voices yet."))
        for row in rows:
            voice_list.controls.append(ft.Row([
                ft.Text(row["name"], weight=ft.FontWeight.BOLD, width=200),
                ft.Text(row["kind"], width=80),
                ft.Text(f'{row["rate"]} {row["pitch"]} {row["volume"]}', width=180),
                ft.Text(row["notes"], expand=True),
                ft.TextButton("Use", on_click=lambda e, n=row["name"]: use_voice(n)),
                ft.TextButton("Delete",
                              on_click=lambda e, n=row["name"]: ask_delete(n)),
            ]))
        options = [ft.dropdown.Option(NONE)] + [
            ft.dropdown.Option(r["name"]) for r in rows]
        voice.options = options
        if voice.value and voice.value != NONE and \
                voice.value not in [r["name"] for r in rows]:
            voice.value = NONE
        if voice.value is None:
            voice.value = NONE
        page.update()

    def use_voice(name: str) -> None:
        prof = library.load(DATA, name)
        merged = dict(project().settings)
        merged.update(prof.settings)
        load_settings(merged)
        voice.value = name
        page.update()
        status.value = f"Loaded {name} ({prof.kind})."

    def ask_delete(name: str) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text(f"Delete {name}?"),
            content=ft.Text("The settings and any attached recording go away."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: page.close(dialog)),
                ft.FilledButton("Delete", on_click=lambda e: do_delete(name, dialog)),
            ],
        )
        page.open(dialog)

    def do_delete(name: str, dialog) -> None:
        library.delete(DATA, name)
        page.close(dialog)
        refresh_voices()
        note(f"Deleted {name}.")

    def create_voice(_=None) -> None:
        name = (new_name.value or "").strip()
        if not name:
            note("Give the voice a name first.")
            return
        # Capture the sliders, not whatever the last render happened to use.
        proj = project()
        proj.apply_settings(collect(), label="create voice")
        proj.save()
        prof = library.create(DATA, name, dict(proj.settings),
                              notes=(new_notes.value or "").strip(),
                              overwrite=True)
        sample = (sample_path.value or "").strip()
        if sample:
            library.attach_sample(DATA, prof.name, Path(sample))
        new_name.value = ""
        new_notes.value = ""
        refresh_voices()
        refresh_history()
        note(f"Saved {prof.name}.")

    def restore_defaults(_=None) -> None:
        created = seed.restore(DATA)
        refresh_voices()
        note(f"Restored {len(created)} default voice(s)." if created
             else "Every default voice is already present.")

    # ---------------------------------------------------------- history tab
    history_list = ft.ListView(spacing=2, expand=True)
    param = ft.Dropdown(label="Parameter", width=200,
                        options=[ft.dropdown.Option(p) for p in PARAMS],
                        value="pitch")
    hist_status = ft.Text("")

    def refresh_history() -> None:
        history_list.controls.clear()
        for row in project().history.describe():
            marker = ">" if row["current"] else " "
            history_list.controls.append(ft.Text(
                f'{marker} {row["index"]:>2}  {row["label"]:<22} '
                f'{row["old"]} -> {row["new"]}'.rstrip(),
                size=12, selectable=True))
        if hasattr(page, "update"):
            try:
                page.update()
            except Exception:
                pass

    def after_history(message: str) -> None:
        refresh_history()
        load_settings(project().settings)
        hist_status.value = message
        page.update()

    def undo_1(_=None) -> None:
        p = project()
        after_history(f"Now at snapshot {p.history.undo(1)}.")
        p.save()

    def undo_5(_=None) -> None:
        p = project()
        after_history(f"Now at snapshot {p.history.undo(5)}.")
        p.save()

    def undo_all(_=None) -> None:
        p = project()
        p.history.undo_to(0)
        p.save()
        after_history("Back to the initial state.")

    def redo_1(_=None) -> None:
        p = project()
        after_history(f"Now at snapshot {p.history.redo(1)}.")
        p.save()

    def revert_param(_=None) -> None:
        p = project()
        value = p.history.undo_param(param.value)
        p.save()
        after_history(f"Reverted {param.value} to {value}.")

    def reset_all(_=None) -> None:
        project().reset_all()
        after_history("All settings reset to defaults.")

    # --------------------------------------------------------------- layout
    def labelled(title: str, control) -> ft.Column:
        return ft.Column([ft.Text(title, size=12,
                                  color=c["TEXT"]), control],
                         spacing=2, tight=True)

    speak_panel = ft.Column([
        ft.Row([ft.Text("Script", size=13), plan_label], spacing=12),
        script,
        ft.Row([labelled("Style", style), labelled("Library voice", voice)],
               spacing=16),
        labelled("Edge voice", edge_voice),
        ft.Row([
            ft.Column([
                ft.Text("Delivery", size=13),
                labelled("Rate", rate), labelled("Pitch", pitch),
                labelled("Volume", volume),
            ], expand=True),
            ft.Column([
                ft.Text("Effects & clone tuning", size=13),
                labelled("Effect", effect), labelled("Speed", speed),
                labelled("Temperature", temperature), labelled("top_k", top_k),
                labelled("top_p", top_p), labelled("Repetition", repetition),
            ], expand=True),
        ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
        labelled("Download format", download_format),
        ft.Row([generate_btn, play_btn, open_out], spacing=12),
        status, result,
    ], spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)

    voices_panel = ft.Column([
        ft.Text("Saved voices", size=16, weight=ft.FontWeight.BOLD),
        voice_list,
        ft.Divider(),
        ft.Row([new_name, new_notes], spacing=10),
        ft.Row([sample_path, ft.FilledButton("Browse…", on_click=pick_sample),
                ft.FilledButton("Create", on_click=create_voice),
                ft.TextButton("Restore defaults", on_click=restore_defaults)],
               spacing=10),
        ft.Text("A recording makes a voice cloneable. Paste a path or use "
                "Browse, then press Create.",
                size=11, color=c["TEXT_MUTED"]),
    ], spacing=8, expand=True)

    history_panel = ft.Column([
        ft.Text("Every change is a snapshot", size=16,
                weight=ft.FontWeight.BOLD),
        history_list,
        ft.Row([
            ft.ElevatedButton("Undo 1", on_click=undo_1),
            ft.ElevatedButton("Undo 5", on_click=undo_5),
            ft.ElevatedButton("Undo all", on_click=undo_all),
            ft.ElevatedButton("Redo", on_click=redo_1),
            ft.ElevatedButton("Reset", on_click=reset_all),
        ]),
        ft.Row([param, ft.FilledButton("Revert parameter",
                                       on_click=revert_param)]),
        hist_status,
    ], spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)

    tabs = ft.Tabs(
        selected_index=0, animation_duration=200, expand=True,
        tabs=[ft.Tab(text="Speak", content=ft.Container(speak_panel, padding=10)),
              ft.Tab(text="Voice Library", content=ft.Container(voices_panel, padding=10)),
              ft.Tab(text="History & Undo", content=ft.Container(history_panel, padding=10))],
    )

    page.overlay.append(picker)
    page.add(
        ft.Text("VoiceForge", size=26, weight=ft.FontWeight.BOLD),
        ft.Text("Flet front-end - the same voices, settings and undo history.",
                size=12, color=c["TEXT"]),
        tabs,
    )

    def format_changed(_=None) -> None:
        fmt = normalize_format(download_format.value)
        generate_btn.text = f"Generate {fmt.upper()}"
        prefs = Preferences.load(DATA)
        if prefs["output_format"] != fmt:
            prefs.update({"output_format": fmt})
            try:
                prefs.save()
            except OSError:
                pass
        page.update()

    generate_btn.on_click = do_generate
    play_btn.on_click = play_last
    open_out.on_click = lambda e: page.launch_url(output_dir(project()).as_uri())
    download_format.on_change = format_changed

    generate_btn.text = f"Generate {normalize_format(download_format.value).upper()}"

    load_settings(project().settings)
    refresh_voices()
    refresh_history()
    update_plan()


if __name__ == "__main__":
    ft.app(main)
