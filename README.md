# VoiceForge

**Local text to speech with voices you own.**
A WinterGate Intelligence Collective product.

VoiceForge turns any amount of text into audio with voices you create, tune and
keep. Output is **MP3 by default** (WAV, FLAC and OGG are one click away).
Voices, renders and settings stay on your machine. No account, no cloud library,
no telemetry.

---

## Install (Windows)

Open the release zip. Inside it you will find:

| Item | What it is |
|---|---|
| `VoiceForge-1.1.0-windows-x64.zip` | **Main package** — portable app with its own Python runtime. Unzip and double-click `VoiceForge.bat`. No installation needed. |
| `VoiceForge-Setup-1.1.0.exe` | **Installer** — fully offline. It contains the same package, copies it to a folder you choose, creates Desktop and Start Menu shortcuts, records your library folder and adds an uninstaller. |
| `README.md` | This file. |
| `LICENSE` | MIT licence and source/voice notices. |

The installer needs **no Python, no pip and no internet connection**. Run it
from anywhere, including after copying it to another drive or machine.

- **Install now** uses the recommended folders.
- **Auto install** does the same with one click and puts VoiceForge on the
  Desktop.
- **Customise…** lets you choose the program folder, library folder, shortcut
  name and shortcut locations.

Recommended defaults on Windows:

```
Program:  %LOCALAPPDATA%\Programs\VoiceForge
Library:  %USERPROFILE%\Documents\VoiceForge
```

The library is separate from the program folder, so reinstalling or updating
the app never touches your voices, downloads, saved text or undo history.

### Portable edition

Unzip the main package and run `VoiceForge.bat` (or `VoiceForge.pyw`). It keeps
its data beside the app, so the whole folder is self-contained and can live on a
USB drive. Move the folder and the data moves with it.

### Uninstall

Use **Settings → Uninstall** inside the app, **Start Menu → Uninstall
VoiceForge**, or run `uninstall.py` from the program folder. All three show a
warning first and ask separately whether to delete the library. The default is
to keep it.

---

## What it does

- **Script tab** — paste or type, open a saved script, or save the current one
  under a name you choose. Long scripts are split automatically and stitched
  back together.
- **Speak tab** — choose a voice, set delivery, add effects, listen first, pick
  an output format, then download the audio. Nothing is generated until you ask.
- **Voice Library** — create, tune, rename, duplicate, preview and delete
  profiles. A profile is a complete snapshot of every knob.
- **History & Undo** — every change is a snapshot. Undo one step, undo
  everything, jump to any snapshot, or revert a single parameter without
  disturbing the rest.
- **Advanced voice lab** — 18 continuous effects and nine one-click presets for
  echo, bass, width, robot, cathedral, tape and more.
- **Downloads** — MP3 (default), WAV, FLAC or OGG, saved to a folder you can
  choose in Settings.
- **Five dark themes** — Midnight, Obsidian, Forest, Plum and Ember, applied
  live across the launcher, installer and app.
- **Four front-ends** — Native Desktop (primary), Browser, Desktop Window and
  Flet, all sharing one project, voice library and undo history.
- **Help & About** — searchable guides for every part of the app, and an About
  page that names WinterGateIC, AnonCatalyst and the project site. Both work
  offline and both offer **Back to Launcher**.
- **Adaptive speed** — long Edge scripts render in parallel parts, with automatic
  back-off when the machine is busy and a clear live estimate.
- **Crash-safe audio** — every part and the finished file is validated and
  renamed into place, so an interrupted render never leaves a broken download.

---

## Using the native app

### 1. Write or open a script

The **Script** tab is the editor. It does not talk to the voice engine, so you
can keep working while audio renders.

- **Open…** loads a `.txt` file.
- **Save** writes to your text folder. If you leave the name blank, the current
  file name is reused; otherwise a name is suggested from the first words.
- The last explicitly opened or saved file is reopened next time. Unsaved
  editor text is deliberately **not** restored.
- The default text folder is `<library>/texts`; change it in Settings.

### 2. Shape the voice

The **Speak** tab has four groups:

| Group | What it controls |
|---|---|
| Voice | Your library profile, the Microsoft Edge voice (a type box with autocomplete), and the active engine. |
| Delivery | Rate, pitch and volume sliders. |
| Effects | A named character chain plus **Advanced voice lab**. |
| Listen | **Quick preview**, which speaks a short sentence-aware excerpt with the current settings and autoplays it. Nothing is written to downloads. |
| Download | Output format, file name and the **Generate** button. |

The default Edge voice is the current multilingual male voice,
`en-US-AndrewMultilingualNeural`. The type box accepts any short name (for
example `en-GB-RyanNeural`) and offers autocomplete. Under it, the quick picks
put the choice in front of you instead of hiding it in one fixed default:

- **Male…** opens the picker filtered to male voices.
- **Female…** opens the picker filtered to female voices.
- **Andrew** selects `en-US-AndrewMultilingualNeural` immediately (the default).
- **Ava** selects `en-US-AvaMultilingualNeural` immediately.
- **More voices…** opens the whole catalogue with search plus filters for
  featured, male, female and other/character voices.

Andrew and Ava sit side by side for one-click access, so you are never stuck
with a single fixed voice. The hint also flags a voice that is missing from the
last fetched Microsoft list, with a reminder to refresh it or pick a quick
voice.

The label under the quick picks always shows the current name, gender, accent
and a short description, so it is obvious which voice you will hear.

### 3. Preview, then download

**Quick preview** renders a few seconds to a temporary cache and plays it
immediately. When it sounds right, pick MP3/WAV/FLAC/OGG and press
**Generate**. The file appears in your downloads folder and the built-in player
can open it.

Long scripts are split into sentence-aware chunks. Chunk files are written to
`.cache/render/`, then stitched with a short pause into **one** finished file;
you never see a pile of `part001.mp3…` files in downloads. Abandoned chunks
from older builds are cleaned automatically at startup.

### Live render progress

A progress panel under the player shows exactly where a render is. It is driven
by real events from the renderer — not a decorative animation:

- the bar advances as each part finishes and moves smoothly inside the part that
  is currently rendering;
- the estimate starts from a sensible characters-per-second figure, then learns
  from the parts that have already completed, so it tightens as the script goes
  on;
- the ETA reads like **“About 1 min 12 s remaining · elapsed 0:34”**;
- a detail line names the current part, e.g. **“Part 3 of 7 · 5,412 of 12,900
  characters done”**, and warns when a part is taking longer than estimated;
- live statistics show **parts completed / total**, how many are rendering now,
  the current worker budget and characters per second;
- when VoiceForge slows itself down, a notice explains why, for example
  **“CPU is at 91% - slowing down so the device stays responsive.”**;
- the bar switches to **Stitching…**, then **Applying effects…**, then
  **100%**;
- a failure marks the bar **Stopped** and keeps a friendly error message visible.

Preview uses the same panel, so even a short listen shows its own estimate.

When a render or preview finishes, the progress widgets clear and a **result
card** takes their place. It shows the folder, filename, size, exact length,
sample rate and channel count, with **Open file** and **Open folder** buttons.
There is no need to hunt through a folder or guess which part is the real file.

### Adaptive speed

A long script means many independent Edge requests. VoiceForge starts up to four
at once by default, because Edge parts are network-bound and this shortens the
wait without loading the CPU. It also samples the machine while it works:

- hot CPU, high memory use or low free memory drop the budget automatically,
  all the way to one part at a time if needed;
- a failed part halves the budget and is retried;
- after three healthy parts it steps back up, so one temporary hiccup does not
  slow the rest of a book.

A fixed number of parts can be chosen in **Settings → Performance**; a manual
choice is always honoured. The local clone engine stays sequential because it
holds a large model in memory.

### Crash-safe files

Temporary parts live in a hidden cache and are deleted when the render ends.
Each part is validated before use; a corrupt or empty part is removed and
rendered once more. Free disk space is checked before stitching. The finished
file is written to a hidden temporary name, reopened and checked, then renamed
into place. A crash, a full disk or a half-finished download can never leave a
truncated file in your downloads folder.

### Help and About

**Help → Help & Guides…** (or `F1`) opens searchable written guides: getting
started, the launcher, voices, Script vs Speak, formats and downloads, adaptive
speed, effects, troubleshooting, settings and About. Search for a word such as
`voice`, `slow` or `no audio` and the matching guides are listed.

**Help → About VoiceForge…** shows the version, WinterGate Intelligence
Collective (WIC), owner AnonCatalyst and `https://wintergate.org`, plus a
**Back to Launcher** button. From the launcher, Back to Launcher simply returns
to the launcher window; from the native app it starts the launcher and closes
the current window after confirming any unsaved script.

### Advanced voice lab

Open it from the Effects group. Every value is a normal setting: it is saved in
profiles, included in undo, and honoured by the CLI and renderer.

| Tab | Controls |
|---|---|
| Tone & width | Bass, treble, punch (compression), stereo width |
| Space & echo | Echo delay, feedback and mix; reverb; chorus |
| Character | Drive, ring modulation and rate, tremolo and rate, vibrato and rate, flutter, bit-crush |

Nine presets: **Bass boost**, **Deep cinema**, **Cathedral echo**, **Robot**,
**Haunted**, **Wide stage**, **Alien signal**, **Worn tape**, **Ghost whisper**.
You can apply a preset, tweak individual knobs, and preview before committing.

The fixed character chains are: `none`, `room`, `hall`, `demon`, `masked`,
`telephone`, `broadcast`, `loudspeaker`, `cave`, `cathedral`, `robot`,
`underwater`, `megaphone`, `cinema`, `ghost`, `vintage`, `alien`.

---

## Default voices

A fresh library is seeded with twelve deliberately different characters, each
using a different base voice, delivery and effect mix:

`narrator`, `broadcaster`, `scary-storyteller`, `halloween-host`, `anonymous`,
`hacker`, `propaganda`, `cinema-trailer`, `cave-oracle`, `robot-host`,
`ghost-whisper`, `alien-signal`.

They are ordinary profiles marked as built-ins. Editing one keeps your edit;
deleting one is permanent until you use **Restore defaults**. New versions of
the app only add missing knobs to built-ins, never overwrite your settings.

---

## Output formats

| Format | Notes |
|---|---|
| **MP3** | Default. Small, universal. |
| WAV | Uncompressed PCM, best for editing elsewhere. |
| FLAC | Lossless compressed. |
| OGG | Vorbis, good size/quality trade-off. |

Rendering writes the engine's native container first and transcodes once. If
the installed libsndfile has no MP3 encoder, VoiceForge falls back to WAV
beside the intended file rather than failing the render.

---

## Command line

The native app is not the only way in. Every setting is scriptable.

```bash
VoiceForge.bat native|web|window|flet   # start a front-end
VoiceForge.bat --check                  # dependency report, no GUI
VoiceForge.bat get --all
VoiceForge.bat set rate=+10% pitch=-20Hz
VoiceForge.bat style apply scary-deep
VoiceForge.bat style list
VoiceForge.bat say "Text to read out loud" --out line1.mp3
VoiceForge.bat say "Text" --format flac
VoiceForge.bat file script.txt --prefix chapter-01
VoiceForge.bat voices --lang en-GB
VoiceForge.bat history
VoiceForge.bat undo --steps 3
VoiceForge.bat undo --to 0
VoiceForge.bat undo --param pitch
VoiceForge.bat redo
VoiceForge.bat reset --param rate

VoiceForge.bat voice create narrator-deep --notes "channel voice"
VoiceForge.bat voice use narrator-deep
VoiceForge.bat voice list
VoiceForge.bat voice show narrator-deep
VoiceForge.bat voice update narrator-deep
VoiceForge.bat voice delete narrator-deep

VoiceForge.bat preset save trailer
VoiceForge.bat preset load trailer
```

On Linux/macOS, use `./run.sh` in place of `VoiceForge.bat`.

---

## Styles and presets

A style writes parameters **and** a character chain. Applying one is an ordinary
undoable change, and every value remains editable.

| Style | Chain | Idea |
|---|---|---|
| `clean` | none | untouched |
| `narrator` | room | warm documentary read |
| `broadcast` | broadcast | punchy trailer announcer |
| `scary-deep` | demon | low, slow, unsettling |
| `halloween-echo` | hall | haunted-house boom |
| `anonymous` | masked | pitch-flattened, identity-hiding |
| `hacker` | telephone | band-limited phone-line grit |
| `loudspeaker` | loudspeaker | old PA horn |
| `propaganda` | loudspeaker | slow, overdriven, huge room |
| `cinema` | cinema | deep, wide trailer voice |
| `cave` | cave | prophecy in a stone room |
| `cathedral` | cathedral | enormous stone tail |
| `robot` | robot | metallic machine host |
| `underwater` | underwater | submerged and slow |
| `megaphone` | megaphone | bullhorn address |
| `ghost` | ghost | detuned and far away |
| `vintage` | vintage | worn tape and flutter |
| `alien` | alien | unstable transmission |

Presets are named parameter snapshots independent of styles. Styles are
built-in; presets are yours.

---

## Undo model

Settings are a small dictionary, so every change stores a full snapshot and a
cursor. That makes all operations exact:

| Operation | Meaning |
|---|---|
| `undo` | step back one change |
| `undo --steps N` | step back N changes |
| `undo --to I` | jump to snapshot I (`--to 0` = undo everything) |
| `undo --param P` | revert only P to its value before its last change |
| `redo` | step forward again |

Recording a new change after an undo discards the redo tail, like an editor.
The native History tab exposes the same operations as buttons.

---

## Settings

Open **Settings** from the launcher (or the app toolbar). The launcher also has
**Help** and **About** buttons and a **Help** menu; the native app has both in
its toolbar and its **Help** menu. Inside Settings:

- **Appearance** — five themes with live preview.
- **Files & downloads** — library, downloads and text folders, default output
  format, and relocation reporting. The three folders must be distinct.
- **Behaviour** — default front-end, close launcher after start, confirm
  delete, autoplay after render, hints, start maximised.
- **Long text** — chunk size and the gap between chunks.
- **Performance** — adaptive rendering on/off, a fixed parts-at-a-time choice
  (0 = Auto, 1–8), a live reading of this machine and a plain explanation of the
  safety net. A manual setting is always honoured.
- **Uninstall** — removes an installed copy. It shows a warning first, then asks
  separately whether to keep or permanently delete your library. Portable and
  source copies are told to delete the folder instead, because there is no
  installer record to remove.
- **Restore defaults** — resets preferences without touching voices or renders.

Preferences live in `<library>/preferences.json` and are separate from
`project.json`, so they are not part of undo.

---

## Where things live

Installed (Windows defaults):

```
%LOCALAPPDATA%\Programs\VoiceForge\      program, runtime and shortcuts
%USERPROFILE%\Documents\VoiceForge\      library (voices, downloads, texts, settings)
```

Portable:

```
VoiceForge\                              program + runtime + data
```

The library contains:

```
voices/            one folder per profile (profile.json + optional sample)
downloads/         rendered audio
texts/             scripts you saved
presets/           named setting snapshots
preferences.json   themes, folders and behaviour
project.json       current settings + undo history
.cache/            edge voice list, previews, render scratch, legacy cleanup
```

`install.json` in the program folder records the library folder. The
environment variable `VOICEFORGE_DATA` overrides it.

---

## Requirements

- **Windows 10/11 x64** for the release build. Linux and macOS run from source.
- Internet access for the default Edge engine (Microsoft's public neural voice
  service, no API key). Nothing else needs the network.
- No `ffmpeg`, no `scipy`, no GPU.

The optional XTTS v2 cloning engine is **not** in the standard release. It is a
~2.5 GB install, runs best on a GPU, and its weights are CPML (non-commercial).
Only clone your own voice or a voice you have written permission to use.

---

## Build from source

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe launcher.py
```

or, from bash:

```bash
./run.sh
```

The launcher detects `runtime/`, then `.venv/`, then the current interpreter.

### Tests

```bash
$env:PYTHONPATH="$PWD\src"
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers parameter coercion, undo/redo and snapshots, persistence,
presets, library lifecycle, styles, the advanced voice lab, long-text chunking,
download formats, DSP stability/loudness, atomic/validated audio writes, the
adaptive worker governor, parallel and corrupt-part rendering, Help/About
content, preference validation, the native UI (including progress, result card
and Back to Launcher) and the installer helpers.

### Build the release

```bash
.venv\Scripts\python.exe tools\build_release.py
```

This script (see `tools/build_release.py`):

1. stages the program files;
2. assembles a relocatable Python runtime from the current interpreter and
   virtual environment, so the result needs no Python on the target machine;
3. runs smoke tests (imports, offscreen launcher, offscreen native app);
4. creates the portable **main package zip**;
5. freezes the Qt Setup wizard with PyInstaller and embeds the same package;
6. produces `releases/VoiceForge-<YYYYMMDD-HHMMSS>.zip` containing the main
   package zip, the Setup executable, `README.md` and `LICENSE`.

The Setup executable is self-contained: it works when copied alone to another
device, with no network and no Python installed.

---

## Troubleshooting

**Windows SmartScreen says the publisher is unknown**
The release is not code-signed. Choose **More info → Run anyway**. The
installer is a standard per-user app and needs no administrator rights.

**The default engine fails or times out**
It needs network access to Microsoft's speech endpoint. Check the connection.
A dead environment proxy is cleared automatically by the launcher, installer
and CLI, but a VPN or firewall can still block `speech.platform.bing.com`.

**“Edge returned no audio”**
Microsoft's service refused the request, or the voice is no longer in its
catalogue. VoiceForge retries automatically and then names the voice. Try, in
order: pick **Andrew** or **Ava**; press **Refresh voice list** and choose again;
check a VPN/proxy/firewall; wait a minute and retry. The app never leaves a
blank file behind.

**A render stopped halfway**
Every part and the finished file is validated before it is exposed. A corrupt
part is deleted and rendered once more, parts never appear in downloads, and a
failed render writes nothing. Retry, or choose a smaller **Characters per part**
under **Settings → Long text**.

**“Not enough free space”**
VoiceForge checks the destination disk before stitching and says how much is
needed. Free some space and retry; nothing was written.

**`pip` reports “Missing dependencies for SOCKS support”**
`ALL_PROXY` is set to a dead SOCKS port. VoiceForge's entry points clear it for
their own processes. To fix it globally: `setx ALL_PROXY ""`, then open a new
terminal.

**The voice list is short**
The Edge catalogue is cached in `<library>/.cache/edge_voices.json`. Delete that
file to refresh it.

**MP3 generation leaves a WAV file**
The installed `libsndfile` has no MP3 encoder. VoiceForge keeps the WAV instead
of failing. Install a soundfile build with MP3 support, or choose WAV/FLAC.

**A preview is silent**
Quick preview writes to `<library>/.cache/preview/`. Check the system output
device and volume; the file itself is temporary and is cleaned up on the next
preview.

---

## Privacy

- No account, analytics or telemetry.
- Scripts, voices, settings and audio stay in your library folder.
- With the Edge engine, the text you synthesize is sent to Microsoft's speech
  service. That is how the free neural voices work. The clone engine runs
  locally.

---

## Licence and credits

MIT licence. See `LICENSE`.

VoiceForge is built by **WinterGate Intelligence Collective** —
[wintergate.org](https://wintergate.org). Owner: **AnonCatalyst**.

VoiceForge 1.1.0. A voice you own.

Brand: mint `#00ff9d`, violet `#7b2eda`, blue `#00b8ff`, ice-white on near-black.
Icon and identity are original WIC work.

“Where the shadows end, and the people stand.”
