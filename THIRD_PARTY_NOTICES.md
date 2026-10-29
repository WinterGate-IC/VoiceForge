# Third-party notices

VoiceForge's own source code is licensed under the MIT Licence. See
[`LICENSE`](LICENSE).

The Windows releases bundle the libraries below. They are used unmodified and
keep their own licences. Full licence texts for the GNU licences are in
[`licenses/`](licenses/). Every bundled Python package also ships its own
licence files under `runtime/Lib/site-packages/<package>.dist-info/licenses/`.

## Core runtime

| Component | Version | Licence | Project |
|---|---|---|---|
| edge-tts | 7.3.1 | LGPL-3.0 | <https://github.com/rany2/edge-tts> |
| NumPy | 2.5.4 | BSD-3-Clause | <https://numpy.org/> |
| soundfile | 0.14.0 | BSD-3-Clause | <https://python-soundfile.readthedocs.io/> |
| libsndfile (bundled native library) | via soundfile wheel | LGPL-2.1-or-later | <https://libsndfile.github.io/libsndfile/> |
| Python runtime | 3.13 | PSF-2.0 | <https://www.python.org/> |

## Front-ends bundled in the standard release

| Component | Version | Licence | Project |
|---|---|---|---|
| Qt for Python (PySide6, Shiboken6, Qt libraries) | 6.12.0 | LGPL-3.0-only (also offered under GPL and commercial terms) | <https://pypi.org/project/PySide6/> |
| pywebview | 6.2.1 | BSD-3-Clause | <https://pywebview.flowrl.com/> |
| Flet | 0.28.3 | Apache-2.0 | <https://flet.dev/> |
| Gradio | 6.30.0 | Apache-2.0 | <https://www.gradio.app/> |
| Pillow | 12.3.0 | MIT-CMU (HPND) | <https://python-pillow.org/> |
| pandas | 3.1.0 | BSD-3-Clause | <https://pandas.pydata.org/> |

The release also includes the transitive dependencies of these packages
(aiohttp, httpx, pydantic, uvicorn/starlette, typer, rich and others). Their
licence files travel with them in the package's `dist-info` folders.

## Build tooling (not part of the application runtime)

| Component | Version | Licence |
|---|---|---|
| PyInstaller | 6.22.3 | GPL-2.0-or-later with the PyInstaller bootloader exception, which permits distributing bundled applications under their own licence |

## Optional, not part of the standard release

| Component | Licence | Notes |
|---|---|---|
| coqui-tts | MPL-2.0 | XTTS v2 voice cloning engine |
| XTTS v2 model weights | CPML | Non-commercial; download and acceptance happen separately |
| PyTorch | BSD-3-Clause | Required only by the clone engine |

## Microsoft Edge voices

The default engine calls Microsoft's public Edge read-aloud service. The voices
are provided by Microsoft and remain subject to Microsoft's terms of use. No
voice model files are redistributed with VoiceForge; only the open-source
`edge-tts` client is bundled, and the text you synthesize is sent to that
service.

## LGPL compliance

edge-tts, libsndfile and PySide6/Qt are distributed under the GNU Lesser
General Public Licence. They are kept as separate, unmodified modules and
shared libraries inside the application folder.

VoiceForge's complete source, build script and packaging metadata are published
in this repository. You may rebuild the application against your own builds of
these libraries by installing different versions and running:

```powershell
.venv\Scripts\python.exe tools\build_release.py
```

Source code for the LGPL components is available from the upstream projects
linked above (PyPI publishes the corresponding source distributions).
