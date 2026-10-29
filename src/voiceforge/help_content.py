"""Help guides, About copy and the "Back to Launcher" helper.

Qt-free on purpose: the native app and the launcher both import this module,
and the CLI/tests can read the guides without a display. `help_dialogs.py`
turns these strings into widgets.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import branding


@dataclass(frozen=True)
class Guide:
    key: str
    title: str
    summary: str
    tags: tuple[str, ...]
    body: str


GUIDES: tuple[Guide, ...] = (
    Guide(
        key="start",
        title="Start here: your first voice render",
        summary="The shortest path from a blank window to a finished audio file.",
        tags=("first", "beginner", "quick", "render", "start"),
        body="""
<h2>Your first render</h2>
<ol>
  <li>Open <b>VoiceForge.bat</b> (Windows) or <b>run.sh</b> (Linux), then pick
      <b>Native (recommended)</b>.</li>
  <li>On the <b>Script</b> tab, paste or type what you want spoken. Long text
      is fine - it is split and stitched automatically.</li>
  <li>Switch to <b>Speak</b>. Pick a voice with <b>Male…</b>, <b>Female…</b>,
      <b>Andrew</b> or <b>Ava</b>, or type any Edge voice name in the voice
      box.</li>
  <li>Choose a <b>File type</b> under Download: MP3 is the safe default.</li>
  <li>Press <b>Preview</b> to hear the first lines, or <b>Generate</b> to make
      the full file. The finished file appears in <b>downloads</b> and its
      folder, name, size and length are shown when the bar clears.</li>
</ol>
<p>Nothing is uploaded except the text Edge needs to speak. There is no
account and no telemetry.</p>
""",
    ),
    Guide(
        key="launcher",
        title="Launcher, shells and what to pick",
        summary="Native, Browser, Window and Flet - and how they share one library.",
        tags=("launcher", "native", "browser", "gradio", "flet", "window", "pywebview"),
        body="""
<h2>Four shells, one core</h2>
<p>Every front-end uses the same voices, settings, text files and undo
history, so it is safe to switch whenever you like.</p>
<ul>
  <li><b>Native</b> - PySide6 desktop app. Best choice: fastest, has the
      built-in player, Script/Speak tabs and the Advanced voice lab.</li>
  <li><b>Browser</b> - opens the Gradio interface in your default browser.</li>
  <li><b>Window</b> - the same Gradio interface inside a native window
      (pywebview).</li>
  <li><b>Flet</b> - an alternative Flutter-rendered interface.</li>
</ul>
<p>If a card says a package is missing, press <b>Install</b> on that card. The
native app and launcher work with only PySide6 installed; the alternates add
their own packages.</p>
<p>The <b>Settings…</b> button in the launcher is the same Settings dialog the
native app uses. Use <b>Help</b> and <b>About</b> here at any time.</p>
""",
    ),
    Guide(
        key="voices",
        title="Voices: quick picks, Edge names and your library",
        summary="How to choose a voice, make one your own, and keep it.",
        tags=("voice", "edge", "andrew", "ava", "library", "clone", "male", "female"),
        body="""
<h2>Choosing a voice</h2>
<p>The Speak tab has a <b>voice type box</b>, not a locked dropdown. The
quick buttons set common voices instantly:</p>
<ul>
  <li><b>Male…</b> / <b>Female…</b> open a filtered picker.</li>
  <li><b>Andrew</b> and <b>Ava</b> are the tested multilingual defaults
      (Andrew is the app default).</li>
  <li><b>More voices…</b> opens the full catalogue.</li>
</ul>
<p>You can also type any name from Microsoft's Edge catalogue, for example
<code>en-GB-SoniaNeural</code>. Press <b>Refresh voice list</b> to fetch the
current catalogue; the cached copy is used when offline.</p>
<h2>Your Voice Library</h2>
<p>The <b>Voice Library</b> tab saves voices you tuned yourself. A saved voice
remembers the engine settings, the Advanced voice-lab knobs and the effect
chain. Built-in profiles are ordinary profiles too - edit one and it is
upgraded in place, never silently reset. Deleting a profile never deletes the
audio of a reference recording unless you ask it to.</p>
<p><b>Clone</b> voices use a reference recording and run locally after the
model is installed. They are slower and stay sequential, because the model is
large; Edge voices are the fast, network-backed option.</p>
""",
    ),
    Guide(
        key="script-speak",
        title="Script vs Speak: writing and shaping",
        summary="What each tab is for, and why your text is not auto-restored.",
        tags=("script", "speak", "editor", "tabs", "text", "save"),
        body="""
<h2>Script</h2>
<p>The <b>Script</b> tab is for writing and editing. It shows how many parts
the text will become and roughly how long the result will be. Use
<b>Save text…</b> to name a prompt; <b>Open text…</b> reopens a saved file.
Only a text you explicitly opened or saved is reopened next launch - unsaved
editor text is never restored behind your back.</p>
<h2>Speak</h2>
<p>The <b>Speak</b> tab is for the voice itself: delivery, Advanced voice
lab, effects, preview/generate and the result. It is deliberately separate so
you can rewrite on Script without losing your place on Speak.</p>
<h2>History &amp; Undo</h2>
<p>Every settings change is an undo step. Open <b>History &amp; Undo</b> to
jump back to any snapshot, or revert a single parameter without losing the
rest of your work.</p>
""",
    ),
    Guide(
        key="output",
        title="Preview, formats, downloads and playback",
        summary="Where finished audio goes, what each format is for, and what is saved.",
        tags=("preview", "mp3", "wav", "flac", "ogg", "download", "play", "format"),
        body="""
<h2>Preview is not a download</h2>
<p><b>Preview</b> renders only the first short section (about 320 characters)
to a private cache and plays it immediately. It does not touch your downloads
folder and does not add an undo step. Use it to test a voice or effect cheaply.</p>
<h2>Generate</h2>
<p><b>Generate</b> renders the whole script as <b>one finished file</b>.
Temporary parts live in a hidden cache, are stitched with a short pause, and
are deleted. When it finishes, the progress bar clears and a result card shows
the folder, filename, size and exact length, with <b>Open file</b> and
<b>Open folder</b> buttons.</p>
<h2>Formats</h2>
<ul>
  <li><b>MP3</b> - recommended: small, plays everywhere.</li>
  <li><b>WAV</b> - lossless, largest; best for editing elsewhere.</li>
  <li><b>FLAC</b> - lossless and smaller than WAV.</li>
  <li><b>OGG Vorbis</b> - smallest lossy option.</li>
</ul>
<p>Files are written to <b>downloads</b> in your data folder unless you chose
another folder in <b>Settings → Files &amp; downloads</b>. A name is never
overwritten: each render gets a timestamp.</p>
""",
    ),
    Guide(
        key="speed",
        title="Long books and adaptive speed",
        summary="Why parallel parts help Edge and when VoiceForge deliberately slows down.",
        tags=("slow", "speed", "performance", "parallel", "long", "book", "cpu", "memory", "eta"),
        body="""
<h2>Why long renders took so long</h2>
<p>A long script is many independent Edge requests. Older builds did them one
at a time. VoiceForge now starts a few at once - Edge is waiting on the
network, so this shortens the wait without pushing your CPU.</p>
<h2>It watches the machine</h2>
<p>Under <b>Settings → Performance</b> the default is <b>Adapt automatically</b>.
VoiceForge samples CPU, memory and free disk while it works:</p>
<ul>
  <li>If CPU or memory gets hot, or free memory gets low, it drops to fewer
      parts - all the way to one if needed.</li>
  <li>If a part fails, it slows down as well as retrying that part.</li>
  <li>After a few healthy parts it steps back up, so a temporary hiccup does
      not slow the whole book.</li>
</ul>
<p>Choose a fixed number if you prefer. The local clone engine always stays
sequential. The progress panel shows live part counts, active requests,
current workers, characters per second and a revised estimate.</p>
<p>For very long books, a smaller <b>Characters per part</b> under
<b>Long text</b> (for example 1,200) makes progress smoother and failures
cheaper.</p>
""",
    ),
    Guide(
        key="effects",
        title="Effects and the Advanced voice lab",
        summary="Echo, hall, bass, radio, telephone and 18 fine controls.",
        tags=("effect", "echo", "bass", "hall", "robot", "hacker", "scary", "advanced"),
        body="""
<h2>Effect chains</h2>
<p>On <b>Speak</b>, the effect list applies a finished chain to the stitched
file: room, hall, cathedral, cave, echo, scary echo, telephone, radio,
loudspeaker, lo-fi, robot, alien, chipmunk, giant, whisper, underwater and
more. The built-in style presets (Scary, Propaganda, Hacker, Anonymous, Scary
Echo, Halloween) set a voice, delivery and chain together.</p>
<h2>Advanced</h2>
<p>The <b>Advanced</b> button opens the voice lab. It has 18 parameters -
bass, treble, punch, width, echo time/feedback/mix, reverb, chorus, drive,
ring modulation, tremolo, vibrato, flutter and bit-crush - plus named presets.
Changes are real audio processing, not labels. <b>Revert this parameter</b>
undoes one knob; the whole lab is one undo step when you save a voice.</p>
<p>Heavy chains take longer on a long file. Preview first to audition them.</p>
""",
    ),
    Guide(
        key="troubleshooting",
        title="Troubleshooting: no audio, no network, broken files",
        summary="Friendly fixes for the problems people actually hit.",
        tags=("error", "problem", "no audio", "edge", "proxy", "vpn", "corrupt", "space"),
        body="""
<h2>“Edge returned no audio”</h2>
<p>This comes from Microsoft's service, not from your speakers. VoiceForge
retries automatically and then explains the likely cause. Try, in order:</p>
<ol>
  <li>Pick <b>Andrew</b> or <b>Ava</b> - they are verified working voices.</li>
  <li>Press <b>Refresh voice list</b>, then choose a voice again. Microsoft
      retires and renames catalogue entries.</li>
  <li>Check a VPN, proxy or firewall. Edge needs HTTPS access to
      <code>speech.platform.bing.com</code>. A dead system proxy is the most
      common cause on a machine that otherwise browses fine.</li>
  <li>Wait a minute and retry; the service occasionally refuses bursts.</li>
</ol>
<p>The error names the voice and never leaves a blank MP3 behind.</p>
<h2>No internet?</h2>
<p>Use a local clone voice. The installer and the app itself need no network;
only Edge voices do.</p>
<h2>A render failed halfway</h2>
<p>Parts and the final file are written to hidden temporary names, checked,
then renamed into place. A corrupt or empty part is deleted and rendered once
more. A full disk is detected before stitching, with a message saying how much
space is needed. Your downloads folder only ever receives complete files.</p>
<h2>Still stuck?</h2>
<p>Open <b>Settings → Uninstall</b> to see where the program and library live.
The README next to the app lists the command-line diagnostics, and the log is
in the data folder's <code>.cache</code>.</p>
""",
    ),
    Guide(
        key="settings",
        title="Settings, folders, backup and uninstall",
        summary="Themes, data folders, long-text tuning, performance and removal.",
        tags=("settings", "theme", "folder", "backup", "uninstall", "data"),
        body="""
<h2>Everything is in one dialog</h2>
<ul>
  <li><b>Appearance</b> - five genuinely dark schemes; the whole app recolours
      live as you click.</li>
  <li><b>Files &amp; downloads</b> - voices, downloads and text folders, plus
      the default output format. Folders can live on another drive. Existing
      files are never overwritten.</li>
  <li><b>Behaviour</b> - default shell, launcher closing, delete confirmation,
      autoplay, start maximised, hints and player volume.</li>
  <li><b>Long text</b> - characters per part and the pause between parts.</li>
  <li><b>Performance</b> - adaptive speed or a fixed number of parts, with a
      live reading of this machine.</li>
  <li><b>Uninstall</b> - removes the installed program and shortcuts, and asks
      whether to keep your library. It cannot be undone, so it warns first.</li>
</ul>
<h2>Backups</h2>
<p>Copy your data folder (by default <code>Documents\\VoiceForge</code> on
Windows) to keep voices, downloads, saved scripts and settings. The program
folder can be replaced or reinstalled without touching it.</p>
""",
    ),
    Guide(
        key="about",
        title="About VoiceForge and WinterGateIC",
        summary="Who made it, what it stands for, and how to reach us.",
        tags=("about", "wintergate", "wintergateic", "wic", "anoncatalyst", "credits", "version"),
        body=f"""
<h2>{branding.APP_NAME} {branding.VERSION}</h2>
<p><b>{branding.PRODUCT_TAGLINE}</b></p>
<p>VoiceForge is built by <b>{branding.COMPANY}</b>
(<b>{branding.COMPANY_SHORT}</b>), owner <b>{branding.OWNER}</b>.<br>
{branding.WEBSITE}</p>
<p><i>“{branding.TAGLINE}”</i></p>
<p>It is a local-first text-to-speech studio: write a script, choose or build
a voice, shape it with real effects, preview it, and keep one clean audio file
you own. No account, no subscription and no telemetry. Edge voices send the
text you ask it to speak to Microsoft; everything else - the library, undo
history, scripts and renders - stays on your machine.</p>
<p>The installer and the app are fully offline. Only Edge voices need an
internet connection; clone voices run locally.</p>
<p>Built with PySide6/Qt, edge-tts, soundfile, NumPy, Gradio, Flet and
pywebview. Thanks to those projects and their communities.</p>
<p>{branding.COPYRIGHT}</p>
""",
    ),
)


def guide_titles() -> list[str]:
    return [guide.title for guide in GUIDES]


def find_guides(query: str = "") -> list[Guide]:
    """Guides matching a search, best-effort and case-insensitive."""
    text = (query or "").strip().casefold()
    if not text:
        return list(GUIDES)
    words = [word for word in text.split() if word]
    found: list[tuple[int, Guide]] = []
    for guide in GUIDES:
        haystack = " ".join(
            (guide.title, guide.summary, " ".join(guide.tags),
             guide.body.replace("<", " ").replace(">", " "))
        ).casefold()
        score = sum(3 if word in guide.title.casefold() else
                    2 if word in " ".join(guide.tags).casefold() else
                    1 if word in haystack else 0
                    for word in words)
        if score:
            found.append((score, guide))
    found.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
    return [guide for _score, guide in found]


def about_html() -> str:
    return next(g.body for g in GUIDES if g.key == "about")


def about_plain_text() -> str:
    """A small plain-text summary for the CLI and headless checks."""
    return (
        f"{branding.APP_NAME} {branding.VERSION}\n"
        f"{branding.PRODUCT_TAGLINE}\n\n"
        f"Built by {branding.COMPANY} ({branding.COMPANY_SHORT}).\n"
        f"Owner: {branding.OWNER}\n"
        f"{branding.WEBSITE}\n\n"
        f"“{branding.TAGLINE}”\n\n"
        f"{branding.DESCRIPTION}\n"
        f"{branding.COPYRIGHT}\n"
    )


# --------------------------------------------------------- launcher hand-off
def find_launcher() -> Path | None:
    """Locate launcher.py in this checkout or installed copy."""
    candidates: list[Path] = []
    home = os.environ.get("VOICEFORGE_HOME")
    if home:
        candidates.append(Path(home).expanduser() / "launcher.py")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "launcher.py")
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "launcher.py")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _python_command() -> str:
    """Prefer pythonw on Windows so handing back does not flash a console."""
    executable = Path(sys.executable)
    if sys.platform.startswith("win"):
        windowed = executable.with_name("pythonw.exe")
        if windowed.is_file():
            return str(windowed)
    return str(executable)


def start_launcher() -> tuple[bool, str]:
    """Start launcher.py detached, sharing this session's data folder."""
    script = find_launcher()
    if script is None:
        return False, ("Could not find launcher.py next to the app. Start the "
                       "launcher the same way you normally open VoiceForge.")
    env = dict(os.environ)
    try:
        from . import paths

        data = env.get(paths.ENV_DATA) or str(paths.data_root(script))
        env[paths.ENV_DATA] = data
    except Exception:
        data = env.get("VOICEFORGE_DATA", "")
    env["VOICEFORGE_HOME"] = str(script.parent)

    options: dict = {
        "cwd": str(script.parent),
        "env": env,
        "close_fds": True,
    }
    if sys.platform.startswith("win"):
        options["creationflags"] = getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        subprocess.Popen([_python_command(), str(script)], **options)
    except Exception as exc:
        return False, f"Could not start the launcher: {exc}"
    return True, data
