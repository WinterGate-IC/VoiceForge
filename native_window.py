"""VoiceForge Window - the Gradio UI inside a real desktop window.

This is the "best of both" option: the full web interface, but no browser
chrome, no address bar and no tab that can wander off. pywebview uses the
OS-native webview (WebView2 on Windows, WebKitGTK on Linux), so nothing is
downloaded at runtime.

    python native_window.py
    python native_window.py --self-test   # open, then close itself

Everything here is a launcher around app.py; the interfaces are identical.
"""

from __future__ import annotations

import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from voiceforge import env as vf_env  # noqa: E402

vf_env.sanitize()

from voiceforge import branding  # noqa: E402


def free_port(preferred: int = 7860) -> int:
    """Prefer the familiar port, fall back to any free one."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError("no free local port")


def wait_until_up(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    return False


def main() -> int:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Run:  pip install pywebview",
              file=sys.stderr)
        return 1

    import app as gradio_app

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"VoiceForge Window starting on {url}")

    blocks = gradio_app.build()
    blocks.launch(prevent_thread_lock=True, inbrowser=False,
                  server_name="127.0.0.1", server_port=port, show_error=True,
                  theme=gradio_app.dark_theme(gradio_app.SCHEME),
                  css=gradio_app.DARK_CSS,
                  favicon_path=branding.icon_png(256))

    if not wait_until_up(url):
        print("error: the local UI did not come up in time", file=sys.stderr)
        try:
            blocks.close()
        except Exception:
            pass
        return 1

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        "VoiceForge", url, width=1400, height=920, min_size=(1040, 700),
        text_select=True,
        background_color=gradio_app.themes.get(gradio_app.SCHEME)["WINDOW"],
    )
    self_test = "--self-test" in sys.argv

    def close_soon() -> None:
        # Runs in pywebview's own thread once the page has loaded.
        time.sleep(2.0)
        try:
            window.destroy()
        except Exception:
            pass

    try:
        if self_test:
            webview.start(close_soon)
        else:
            webview.start()
    finally:
        try:
            blocks.close()
        except Exception:
            pass
        del window
    if self_test:
        print("self-test: window opened and closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
