"""Build every VoiceForge brand asset from the SVG masters.

The SVG files are the source of truth; this script rasterises them with Qt so
the output is reproducible on any machine with PySide6 (no Pillow, no
ImageMagick, no network).

    python tools/make_icon.py

Outputs, all in assets/:

    voiceforge-{16..1024}.png     square app icon
    voiceforge-{16..256}.ico      multi-size Windows icon
    voiceforge-avatar-{n}.png     circular profile picture
    voiceforge-lockup.png         horizontal brand lockup
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ASSETS = ROOT / "assets"

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QGuiApplication, QImage, QPainter, QPen,
)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
AVATAR_SIZES = (64, 128, 256, 512, 1024)


def _app() -> QGuiApplication:
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication([sys.argv[0]])
    return app


def render_svg(svg: Path, size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.read_bytes()))
    if not renderer.isValid():
        raise SystemExit(f"invalid SVG: {svg}")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def save_png(image: QImage, path: Path) -> None:
    if not image.save(str(path), "PNG"):
        raise SystemExit(f"could not write {path}")


def write_ico(path: Path, images: list[tuple[int, Path]]) -> None:
    """Write a multi-size ICO whose entries are PNG payloads."""
    payloads = [(size, png.read_bytes()) for size, png in images]
    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = 6 + 16 * len(payloads)
    entries = bytearray()
    blob = bytearray()
    for size, data in payloads:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0,
                               1, 32, len(data), offset)
        blob += data
        offset += len(data)
    path.write_bytes(header + bytes(entries) + bytes(blob))


def _font(families: list[str], size: int, weight: QFont.Weight,
          spacing: float) -> QFont:
    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def make_lockup(icon: QImage) -> None:
    """Horizontal lockup: tile + wordmark + company attribution."""
    width, height = 1680, 460
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    tile = 340
    painter.drawImage(QRectF(80, 60, tile, tile), icon,
                      QRectF(0, 0, icon.width(), icon.height()))

    x = 500
    painter.setPen(QColor("#ffffff"))
    painter.setFont(_font(["Bahnschrift SemiBold Condensed", "Bahnschrift",
                           "Segoe UI Semibold", "DejaVu Sans"],
                          150, QFont.Weight.DemiBold, 8))
    painter.drawText(x, 220, "VOICEFORGE")

    painter.setPen(QColor("#00ff9d"))
    painter.setFont(_font(["Segoe UI", "DejaVu Sans"], 34,
                          QFont.Weight.Medium, 7))
    painter.drawText(x + 4, 286, "A VOICE YOU OWN")

    painter.setPen(QColor("#8b98a9"))
    painter.setFont(_font(["Segoe UI", "DejaVu Sans"], 24,
                          QFont.Weight.Normal, 4))
    painter.drawText(x + 4, 338, "BY WINTERGATE INTELLIGENCE COLLECTIVE")

    pen = QPen(QColor(0, 255, 157, 90), 2)
    painter.setPen(pen)
    painter.drawLine(x + 4, 368, x + 620, 368)

    painter.end()
    save_png(image, ASSETS / "voiceforge-lockup.png")


def main() -> int:
    _app()
    square_svg = ASSETS / "voiceforge.svg"
    avatar_svg = ASSETS / "voiceforge-avatar.svg"
    for svg in (square_svg, avatar_svg):
        if not svg.exists():
            raise SystemExit(f"missing {svg}")

    icons: list[tuple[int, Path]] = []
    for size in ICON_SIZES:
        target = ASSETS / f"voiceforge-{size}.png"
        save_png(render_svg(square_svg, size), target)
        icons.append((size, target))

    write_ico(ASSETS / "voiceforge.ico",
              [(size, path) for size, path in icons if size in ICO_SIZES])

    for size in AVATAR_SIZES:
        save_png(render_svg(avatar_svg, size),
                 ASSETS / f"voiceforge-avatar-{size}.png")

    make_lockup(render_svg(square_svg, 512))
    print("Brand assets written to", ASSETS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
