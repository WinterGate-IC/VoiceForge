"""VoiceForge GUI - a local desktop app for building and using your own voices.

Run:  VoiceForge.bat web      (or:  python app.py)

Everything is local except the edge engine, which calls Microsoft's public
neural-voice endpoint over HTTPS and needs no API key.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# Must happen before the first httpx import inside Gradio.
from voiceforge import env as vf_env  # noqa: E402

vf_env.sanitize()

import gradio as gr  # noqa: E402

from voiceforge import branding, library, paths, seed, styles, themes  # noqa: E402
from voiceforge.preferences import Preferences  # noqa: E402
from voiceforge.effects import CHAINS  # noqa: E402
from voiceforge.project import Project  # noqa: E402
from voiceforge.render import (  # noqa: E402
    FORMAT_LABELS, normalize_format, output_dir, render_text)
from voiceforge.settings import PARAMS  # noqa: E402

DATA = paths.data_root(__file__)
NONE = "(no library voice)"
CACHE = DATA / ".cache" / "edge_voices.json"
FALLBACK_VOICES = [
    "en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural",
    "en-US-EmmaMultilingualNeural", "en-US-BrianMultilingualNeural",
    "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural",
]

SLIDER_NAMES = ("rate", "pitch", "volume", "speed", "temperature",
                "top_k", "top_p", "repetition_penalty")


# ------------------------------------------------------------- small utils
def _pct(value: float) -> str:
    return f"{int(value):+d}%"


def _hz(value: float) -> str:
    return f"{int(value):+d}Hz"


def _num(text: str, cast=int):
    m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", str(text or "0"))
    try:
        return cast(m.group(1)) if m else cast(0)
    except (TypeError, ValueError):
        return cast(0)


def _project() -> Project:
    return Project.load(DATA)


def edge_voice_choices() -> list[str]:
    """Cached so the app opens instantly and works offline after the first run."""
    if CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if cached:
                return cached
        except (json.JSONDecodeError, OSError):
            pass
    try:
        from voiceforge.engines import list_voices

        names = sorted(r["short"] for r in list_voices() if r["short"])
        if names:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(names, indent=2), encoding="utf-8")
            return names
    except Exception:
        pass
    return FALLBACK_VOICES


def lib_choices() -> list[str]:
    return [NONE] + [r["name"] for r in library.listing(DATA)]


def lib_rows() -> list[list[str]]:
    return [[r["name"], r["kind"], r["rate"], r["pitch"], r["volume"],
             r["audio"], r["notes"]] for r in library.listing(DATA)]


def hist_rows() -> list[list[str]]:
    return [[r["index"], ">" if r["current"] else "", r["label"], r["old"],
             r["new"], r["at"]] for r in _project().history.describe()]


def _widgets(settings: dict) -> tuple:
    """Settings dict -> the eight slider values, in SLIDER_NAMES order."""
    return (
        _num(settings.get("rate"), int),
        _num(settings.get("pitch"), int),
        _num(settings.get("volume"), int),
        float(settings.get("speed", 1.0) or 1.0),
        float(settings.get("temperature", 0.75) or 0.75),
        int(settings.get("top_k", 50) or 50),
        float(settings.get("top_p", 0.85) or 0.85),
        float(settings.get("repetition_penalty", 5.0) or 5.0),
    )


def _sync_seven(project: Project) -> tuple:
    """History-table + status + all sliders, the standard undo output set."""
    return (hist_rows(), "", *_widgets(project.settings))


# ------------------------------------------------------------- callbacks
def on_pick_style(style_name: str):
    """Style -> sliders + effect dropdown. Purely a convenience; nothing is saved."""
    project = _project()
    merged = dict(project.settings)
    try:
        st = styles.get(style_name)
    except styles.StyleError as exc:
        return (*_widgets(merged), project.settings.get("effect", "none"), f"**{exc}**")
    merged.update(st.params)
    return (*_widgets(merged), st.effect,
            f"Style **{st.name}** loaded into the sliders - {st.description}")


def on_pick_voice(name: str):
    """Library voice -> sliders + effect. Still not saved until you generate."""
    project = _project()
    if not name or name == NONE:
        return (*_widgets(project.settings), project.settings.get("effect", "none"),
                "No library voice selected - sliders unchanged.")
    try:
        prof = library.load(DATA, name)
    except library.LibraryError as exc:
        return (*_widgets(project.settings), project.settings.get("effect", "none"),
                f"**{exc}**")

    merged = dict(project.settings)
    merged.update(prof.settings)
    note = f"Loaded **{prof.name}** ({prof.kind})."
    if library.audio_in(DATA, prof.name):
        note += " Has a recording, so Generate will use the clone engine."
    return (*_widgets(merged), merged.get("effect", "none"), note)


def generate(text, style_name, lib_voice, edge_voice, rate, pitch, volume,
             effect, speed, temp, top_k, top_p, rep, output_format="mp3"):
    text = (text or "").strip()
    if not text:
        return None, "**Nothing to speak.** Paste a script first."

    project = _project()
    values = _slider_values(rate, pitch, volume, effect, speed, temp,
                            top_k, top_p, rep, edge_voice)

    reference = ""
    if lib_voice and lib_voice != NONE and library.audio_in(DATA, lib_voice):
        reference = lib_voice
    values["reference"] = reference

    project.apply_settings(values, label="generate")
    try:
        path, engine = render_text(project, text,
                                   output_format=normalize_format(output_format))
    except Exception as exc:  # engine, network, param or effect problems
        return None, f"**Could not render:** {exc}"

    kb = path.stat().st_size / 1024
    try:
        shown = path.relative_to(DATA)
    except ValueError:
        shown = path
    return str(path), (f"Rendered with **{engine}** + effect `{values['effect']}` "
                       f"&nbsp; `{shown}` &nbsp; {kb:.0f} KB")


def _slider_values(rate, pitch, volume, effect, speed, temp, top_k, top_p,
                   rep, edge_voice=None) -> dict:
    """The live widget values, in the same shape the project stores."""
    values = {
        "rate": _pct(rate), "pitch": _hz(pitch), "volume": _pct(volume),
        "effect": effect or "none",
        "speed": float(speed), "temperature": float(temp),
        "top_k": int(top_k), "top_p": float(top_p),
        "repetition_penalty": float(rep),
    }
    if edge_voice:
        values["voice"] = edge_voice
    return values


def _upload_root() -> Path:
    """Gradio's upload folder. Recordings must come from inside it."""
    configured = os.environ.get("GRADIO_TEMP_DIR")
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "gradio"
    return Path(os.path.realpath(root))


def _uploaded_sample(value: object) -> Path | None:
    """Accept only a file Gradio uploaded, never a path typed by a request.

    The audio component is local, but its value arrives over HTTP. Without this
    check a crafted API call could name any readable file on the machine and
    have it copied into the library (CWE-22).
    """
    if not value:
        return None
    candidate = Path(os.path.realpath(os.fspath(value)))
    root = _upload_root()
    if not str(candidate).startswith(str(root) + os.sep):
        raise ValueError("the recording must be uploaded through this page")
    if not candidate.is_file():
        raise ValueError("the recording is missing")
    return candidate


def do_create(name, notes, sample, edge_voice, rate, pitch, volume, effect,
              speed, temp, top_k, top_p, rep):
    if not name or not name.strip():
        return lib_rows(), gr.update(), "**Give the voice a name first.**"
    try:
        # Sliders are the source of truth here: without this the new profile
        # would silently save whatever the last render happened to use.
        project = _project()
        project.apply_settings(
            _slider_values(rate, pitch, volume, effect, speed, temp,
                           top_k, top_p, rep, edge_voice),
            label="create voice")
        prof = library.create(DATA, name, dict(project.settings),
                              notes=notes or "", overwrite=True)
        if sample:
            library.attach_sample(DATA, prof.name, _uploaded_sample(sample),
                                  source_root=_upload_root())
    except Exception as exc:
        return lib_rows(), gr.update(), f"**Could not create:** {exc}"
    kind = "cloned" if library.audio_in(DATA, prof.name) else "designed"
    return (lib_rows(), gr.update(choices=lib_choices(), value=prof.name),
            f"Saved **{prof.name}** ({kind}).")


def do_attach(name, sample):
    if not name or name == NONE:
        return lib_rows(), "**Pick or type a voice name.**"
    if not sample:
        return lib_rows(), "**Choose or record a sample first.**"
    try:
        dest = library.attach_sample(DATA, name, _uploaded_sample(sample),
                                     source_root=_upload_root())
    except Exception as exc:
        return lib_rows(), f"**Could not attach:** {exc}"
    return lib_rows(), (f"Attached `{dest.name}` to **{library.slug(name)}** - "
                        f"it is now cloneable.")


def do_use(name):
    if not name or name == NONE:
        return (*_widgets(_project().settings), _project().settings.get("effect", "none"),
                "**Pick a voice.**")
    try:
        prof = library.load(DATA, name)
    except library.LibraryError as exc:
        return (*_widgets(_project().settings), _project().settings.get("effect", "none"),
                f"**{exc}**")
    project = _project()
    pairs = [f"{k}={v}" for k, v in prof.settings.items() if k in PARAMS]
    if pairs:
        project.set_many(pairs)
    has_audio = library.audio_in(DATA, prof.name) is not None
    project.set_many([f"reference={prof.name if has_audio else ''}"])
    return (*_widgets(project.settings), project.settings.get("effect", "none"),
            f"Active voice: **{prof.name}** ({prof.kind}).")


def do_rename(old, new):
    if not old or old == NONE or not new:
        return lib_rows(), gr.update(), "**Need a current name and a new name.**"
    try:
        prof = library.rename(DATA, old, new)
    except Exception as exc:
        return lib_rows(), gr.update(), f"**Rename failed:** {exc}"
    project = _project()
    if project.settings.get("reference") == library.slug(old):
        project.set_many([f"reference={prof.name}"])
    return (lib_rows(), gr.update(choices=lib_choices(), value=prof.name),
            f"Renamed to **{prof.name}**.")


def do_delete(name):
    if not name or name == NONE:
        return lib_rows(), gr.update(), "**Pick a voice to delete.**"
    project = _project()
    if project.settings.get("reference") == library.slug(name):
        project.apply_settings({"reference": ""}, label="delete voice")
    gone = library.delete(DATA, name)
    return (lib_rows(), gr.update(choices=lib_choices(), value=NONE),
            f"Deleted **{library.slug(name)}**." if gone else "No such voice.")


def do_restore():
    created = seed.restore(DATA)
    message = (f"Restored **{len(created)}** default voice(s): "
               f"{', '.join(created)}." if created
               else "Every default voice is already present.")
    return lib_rows(), gr.update(choices=lib_choices(), value=NONE), message


def _after(message: str):
    project = _project()
    return (hist_rows(), message, *_widgets(project.settings))


def do_undo(steps: int):
    project = _project()
    try:
        cursor = project.history.undo(steps=steps)
        project.save()
    except ValueError as exc:
        return _after(f"**{exc}**")
    return _after(f"Stepped back {steps}. Now at snapshot {cursor}.")


def do_redo(steps: int):
    project = _project()
    try:
        cursor = project.history.redo(steps=steps)
        project.save()
    except ValueError as exc:
        return _after(f"**{exc}**")
    return _after(f"Stepped forward {steps}. Now at snapshot {cursor}.")


def do_undo_all():
    project = _project()
    project.history.undo_to(0)
    project.save()
    return _after("Back to the initial state.")


def do_jump(index):
    project = _project()
    try:
        cursor = project.history.undo_to(int(index))
        project.save()
    except (ValueError, TypeError) as exc:
        return _after(f"**{exc}**")
    return _after(f"Jumped to snapshot {cursor}.")


def do_revert_param(name):
    project = _project()
    try:
        value = project.history.undo_param(name)
        project.save()
    except Exception as exc:
        return _after(f"**{exc}**")
    return _after(f"Reverted **{name}** to `{value}`.")


def do_reset():
    _project().reset_all()
    return _after("All settings reset to defaults.")


def reveal_output():
    d = output_dir(_project())
    try:
        os.startfile(str(d))  # noqa: S606 - Windows shell open
    except Exception:
        pass
    return f"Opened `{d}`"


# ------------------------------------------------------------- interface
def build() -> gr.Blocks:
    seed.ensure_defaults(DATA)
    project = _project()
    prefs = Preferences.load(DATA)
    start = _widgets(project.settings)
    start_effect = project.settings.get("effect", "none")

    with gr.Blocks(title="VoiceForge", fill_width=True) as app:
        gr.Markdown(
            "# VoiceForge\n"
            "A voice you own. Tune it, save it to your library, and undo any single "
            "change. Downloads are **MP3** by default, with WAV, FLAC and OGG "
            "available.")

        with gr.Tabs():
            with gr.Tab("Speak"):
                with gr.Row():
                    with gr.Column(scale=3):
                        text = gr.Textbox(label="Script", lines=12,
                                          placeholder="Paste your voiceover script here…")

                        with gr.Row():
                            style = gr.Dropdown(
                                choices=["clean"] + [s.name for s in styles.listing()
                                                     if s.name != "clean"],
                                value="clean", label="Style preset (loads the sliders)",
                                scale=1)
                            lib_voice = gr.Dropdown(choices=lib_choices(), value=NONE,
                                                    label="Your voice library", scale=1)

                        edge_voice = gr.Dropdown(
                            choices=edge_voice_choices(),
                            value=project.settings.get("voice") or FALLBACK_VOICES[0],
                            label="Edge voice (used when the selected voice has no recording)",
                            filterable=True)

                        gr.Markdown("**Delivery**")
                        with gr.Row():
                            rate = gr.Slider(-50, 50, start[0], step=5, label="Rate (%)")
                            pitch = gr.Slider(-60, 60, start[1], step=2, label="Pitch (Hz)")
                            volume = gr.Slider(-50, 50, start[2], step=5, label="Volume (%)")

                        with gr.Accordion("Effects & clone-engine tuning", open=False):
                            effect = gr.Dropdown(
                                choices=list(CHAINS), value=start_effect,
                                label="Effect chain (post-processing)")
                            with gr.Row():
                                speed = gr.Slider(0.5, 2.0, start[3], step=0.05, label="Speed")
                                temp = gr.Slider(0.05, 1.5, start[4], step=0.05,
                                                 label="Temperature (expressiveness)")
                            with gr.Row():
                                top_k = gr.Slider(1, 200, start[5], step=1, label="top_k")
                                top_p = gr.Slider(0.1, 1.0, start[6], step=0.05, label="top_p")
                                rep = gr.Slider(1.0, 20.0, start[7], step=0.5,
                                                label="Repetition penalty")

                        with gr.Row():
                            go = gr.Button("Generate", variant="primary", scale=2)
                            reveal = gr.Button("Open downloads folder", scale=1)
                        output_format = gr.Dropdown(
                            choices=[(label, key) for key, label in FORMAT_LABELS.items()],
                            value=normalize_format(prefs["output_format"]),
                            label="Download format",
                            info="MP3 plays everywhere. WAV and FLAC are lossless; "
                                 "OGG is the smallest.")

                    with gr.Column(scale=2):
                        audio = gr.Audio(label="Result", type="filepath", interactive=False)
                        status = gr.Markdown("Ready.")

            with gr.Tab("Voice Library"):
                gr.Markdown(
                    "A **designed** voice is a tuned setting - instant, no downloads. "
                    "Attach a 6–20 s recording of a voice you own and it becomes "
                    "**cloned**, which needs `pip install coqui-tts`.")
                lib_table = gr.Dataframe(
                    headers=["name", "kind", "rate", "pitch", "volume", "sample", "notes"],
                    value=lib_rows(), interactive=False, wrap=True)

                with gr.Row():
                    with gr.Column():
                        vname = gr.Textbox(label="Voice name", placeholder="e.g. narrator-deep")
                        vnotes = gr.Textbox(label="Notes", lines=2,
                                            placeholder="what this voice is for")
                        vsample = gr.Audio(
                            sources=["upload", "microphone"], type="filepath",
                            label="Reference recording - 6 to 20 s, one speaker (optional)")
                        create_btn = gr.Button("Create from current settings",
                                               variant="primary")
                    with gr.Column():
                        attach_btn = gr.Button("Attach recording to an existing voice")
                        use_btn = gr.Button("Activate / load into sliders")
                        with gr.Row():
                            rename_to = gr.Textbox(label="Rename to")
                            rename_btn = gr.Button("Rename")
                        delete_btn = gr.Button("Delete voice", variant="stop")
                        restore_btn = gr.Button("Restore built-in default voices")

                lib_status = gr.Markdown("")

            with gr.Tab("History & Undo"):
                gr.Markdown("Every change is a snapshot. Undo one step, undo everything, "
                            "or revert a single knob without touching the rest.")
                hist_table = gr.Dataframe(
                    headers=["#", "now", "change", "from", "to", "when"],
                    value=hist_rows(), interactive=False, wrap=True)

                with gr.Row():
                    undo1 = gr.Button("Undo 1")
                    undo5 = gr.Button("Undo 5")
                    undoall = gr.Button("Undo all")
                    redo1 = gr.Button("Redo")
                    reset_btn = gr.Button("Reset to defaults", variant="stop")

                with gr.Row():
                    param = gr.Dropdown(choices=list(PARAMS), value="rate",
                                        label="Revert just this parameter", scale=2)
                    revert_btn = gr.Button("Revert parameter", scale=1)
                    jump_to = gr.Number(value=0, precision=0, label="Jump to snapshot",
                                        scale=1)
                    jump_btn = gr.Button("Jump", scale=1)

                hist_status = gr.Markdown("")

        # ------------------------------------------------ wiring
        sliders = [rate, pitch, volume, speed, temp, top_k, top_p, rep]
        tuning = [*sliders, effect]

        style.change(on_pick_style, inputs=[style], outputs=[*tuning, status])
        lib_voice.change(on_pick_voice, inputs=[lib_voice], outputs=[*tuning, status])

        go.click(generate,
                 inputs=[text, style, lib_voice, edge_voice, rate, pitch, volume,
                         effect, speed, temp, top_k, top_p, rep, output_format],
                 outputs=[audio, status])
        reveal.click(reveal_output, outputs=status)

        create_btn.click(
            do_create,
            inputs=[vname, vnotes, vsample, edge_voice, rate, pitch, volume,
                    effect, speed, temp, top_k, top_p, rep],
            outputs=[lib_table, lib_voice, lib_status])
        attach_btn.click(do_attach, inputs=[vname, vsample],
                         outputs=[lib_table, lib_status])
        use_btn.click(do_use, inputs=[lib_voice], outputs=[*tuning, lib_status])
        rename_btn.click(do_rename, inputs=[lib_voice, rename_to],
                         outputs=[lib_table, lib_voice, lib_status])
        delete_btn.click(do_delete, inputs=[lib_voice],
                         outputs=[lib_table, lib_voice, lib_status])
        restore_btn.click(do_restore,
                          outputs=[lib_table, lib_voice, lib_status])

        hist_outputs = [hist_table, hist_status, *sliders]
        undo1.click(lambda: do_undo(1), outputs=hist_outputs)
        undo5.click(lambda: do_undo(5), outputs=hist_outputs)
        undoall.click(do_undo_all, outputs=hist_outputs)
        redo1.click(lambda: do_redo(1), outputs=hist_outputs)
        reset_btn.click(do_reset, outputs=hist_outputs)
        revert_btn.click(do_revert_param, inputs=[param], outputs=hist_outputs)
        jump_btn.click(do_jump, inputs=[jump_to], outputs=hist_outputs)

    return app


# ------------------------------------------------------------------- theming
def dark_css(name: str | None = None) -> str:
    c = themes.get(name)
    return f"""
html, body {{ background: {c['WINDOW']} !important; color-scheme: dark; }}
.gradio-container {{ background: {c['WINDOW']} !important; max-width: 1480px; }}
.gradio-container .prose h1 {{ letter-spacing: -0.5px; }}
footer {{ display: none !important; }}
.gradio-container ::-webkit-scrollbar {{ width: 12px; height: 12px; }}
.gradio-container ::-webkit-scrollbar-track {{ background: {c['WINDOW']}; }}
.gradio-container ::-webkit-scrollbar-thumb {{
    background: {c['BORDER']}; border-radius: 6px;
}}
.gradio-container ::-webkit-scrollbar-thumb:hover {{
    background: {c['BORDER_HOVER']};
}}
.gradio-container textarea, .gradio-container input[type="text"] {{
    background: {c['FIELD']} !important; color: {c['TEXT']} !important;
}}
"""


def dark_theme(name: str | None = None):
    """A low-glare Gradio theme built from the shared VoiceForge palette.

    Base.set() raises on unknown keys, and the variable list changes between
    Gradio releases, so the mapping is filtered against this build's own
    attributes instead of trusting a hard-coded list.
    """
    c = themes.get(name)
    theme = gr.themes.Base(primary_hue="blue", secondary_hue="sky",
                           neutral_hue="slate")
    wanted = {
        "body_background_fill": c["WINDOW"],
        "body_background_fill_dark": c["WINDOW"],
        "body_text_color": c["TEXT"],
        "body_text_color_dark": c["TEXT"],
        "body_text_color_subdued": c["TEXT_MUTED"],
        "body_text_color_subdued_dark": c["TEXT_MUTED"],
        "background_fill_primary": c["PANEL"],
        "background_fill_primary_dark": c["PANEL"],
        "background_fill_secondary": c["WINDOW"],
        "background_fill_secondary_dark": c["WINDOW"],
        "block_background_fill": c["PANEL"],
        "block_background_fill_dark": c["PANEL"],
        "block_border_color": c["BORDER"],
        "block_border_color_dark": c["BORDER"],
        "block_label_background_fill": c["PANEL"],
        "block_label_background_fill_dark": c["PANEL"],
        "block_label_text_color": c["TEXT_MUTED"],
        "block_label_text_color_dark": c["TEXT_MUTED"],
        "block_title_text_color": c["TEXT"],
        "block_title_text_color_dark": c["TEXT"],
        "border_color_primary": c["BORDER"],
        "border_color_primary_dark": c["BORDER"],
        "panel_background_fill": c["PANEL"],
        "panel_background_fill_dark": c["PANEL"],
        "input_background_fill": c["FIELD"],
        "input_background_fill_dark": c["FIELD"],
        "input_background_fill_focus": c["FIELD"],
        "input_background_fill_focus_dark": c["FIELD"],
        "input_background_fill_hover": c["RAISED"],
        "input_background_fill_hover_dark": c["RAISED"],
        "input_border_color": c["BORDER"],
        "input_border_color_dark": c["BORDER"],
        "input_border_color_focus": c["ACCENT"],
        "input_border_color_focus_dark": c["ACCENT"],
        "input_placeholder_color": c["TEXT_DISABLED"],
        "input_placeholder_color_dark": c["TEXT_DISABLED"],
        "button_primary_background_fill": c["ACCENT_STRONG"],
        "button_primary_background_fill_dark": c["ACCENT_STRONG"],
        "button_primary_background_fill_hover": c["ACCENT_HOVER"],
        "button_primary_background_fill_hover_dark": c["ACCENT_HOVER"],
        "button_primary_text_color": "#ffffff",
        "button_primary_text_color_dark": "#ffffff",
        "button_secondary_background_fill": c["RAISED"],
        "button_secondary_background_fill_dark": c["RAISED"],
        "button_secondary_background_fill_hover": c["RAISED_HOVER"],
        "button_secondary_background_fill_hover_dark": c["RAISED_HOVER"],
        "button_secondary_text_color": c["TEXT"],
        "button_secondary_text_color_dark": c["TEXT"],
        "table_even_background_fill": c["PANEL"],
        "table_even_background_fill_dark": c["PANEL"],
        "table_odd_background_fill": c["WINDOW"],
        "table_odd_background_fill_dark": c["WINDOW"],
        "table_border_color": c["BORDER"],
        "table_border_color_dark": c["BORDER"],
        "slider_color": c["ACCENT"],
        "slider_color_dark": c["ACCENT"],
        "color_accent": c["ACCENT"],
        "color_accent_soft": c["ACCENT_SOFT"],
        "color_accent_soft_dark": c["ACCENT_SOFT"],
        "link_text_color": c["ACCENT"],
        "link_text_color_dark": c["ACCENT"],
        "link_text_color_hover": c["PILL_TEXT"],
        "link_text_color_hover_dark": c["PILL_TEXT"],
        "checkbox_background_color": c["FIELD"],
        "checkbox_background_color_dark": c["FIELD"],
        "checkbox_border_color": c["BORDER"],
        "checkbox_border_color_dark": c["BORDER"],
        "checkbox_border_color_selected": c["ACCENT_STRONG"],
        "checkbox_border_color_selected_dark": c["ACCENT_STRONG"],
    }
    known = set(theme.__dict__)
    theme.set(**{k: v for k, v in wanted.items() if k in known})
    return theme


SCHEME = Preferences.load(DATA)["theme"]
DARK_CSS = dark_css(SCHEME)


def main() -> None:
    # VOICEFORGE_NO_BROWSER=1 suppresses the automatic tab (used for smoke tests).
    open_browser = os.environ.get("VOICEFORGE_NO_BROWSER") != "1"
    build().launch(inbrowser=open_browser, server_name="127.0.0.1",
                   theme=dark_theme(SCHEME), css=DARK_CSS,
                   favicon_path=branding.icon_png(256))


if __name__ == "__main__":
    main()
