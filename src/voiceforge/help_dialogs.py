"""Qt Help and About dialogs, shared by the launcher and native app.

The copy lives in `help_content.py`; this module only presents it. Both
dialogs are readable, searchable and keyboard-friendly, and both offer a
route back to the launcher.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from . import branding, help_content


class AboutDialog(QDialog):
    """Product, company and owner, with a Back to Launcher button."""

    def __init__(self, parent=None,
                 on_back: Callable[[], bool | None] | None = None) -> None:
        super().__init__(parent)
        self._on_back = on_back
        self.back_requested = False

        self.setWindowTitle(f"About {branding.APP_NAME}")
        self.setMinimumSize(680, 600)
        self.resize(760, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 14)
        outer.setSpacing(12)

        header = QHBoxLayout()
        avatar = QLabel()
        image = branding.avatar_path()
        if image is not None:
            pixmap = QPixmap(str(image))
            if not pixmap.isNull():
                avatar.setPixmap(pixmap.scaled(
                    104, 104, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        avatar.setFixedWidth(112)
        header.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel(branding.APP_NAME)
        title.setObjectName("title")
        version = QLabel(f"Version {branding.VERSION}")
        version.setObjectName("heading")
        tagline = QLabel(branding.PRODUCT_TAGLINE)
        tagline.setObjectName("subtitle")
        company = QLabel(f"{branding.COMPANY} ({branding.COMPANY_SHORT})"
                         f"  ·  Owner: {branding.OWNER}")
        company.setWordWrap(True)
        company.setObjectName("muted")
        words.addWidget(title)
        words.addWidget(version)
        words.addWidget(tagline)
        words.addWidget(company)
        words.addStretch(1)
        header.addLayout(words, 1)
        outer.addLayout(header)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(help_content.about_html())
        outer.addWidget(self.browser, 1)

        footer = QHBoxLayout()
        site = QPushButton("Visit wintergate.org")
        site.clicked.connect(self._visit)
        back = QPushButton("Back to Launcher")
        back.setObjectName("primary")
        back.setToolTip("Close this dialog and return to the VoiceForge launcher.")
        back.clicked.connect(self._back)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        footer.addWidget(site)
        footer.addStretch(1)
        footer.addWidget(back)
        footer.addWidget(close)
        outer.addLayout(footer)

    def _visit(self) -> None:
        QDesktopServices.openUrl(QUrl(branding.WEBSITE))

    def _back(self) -> None:
        if self._on_back is not None:
            try:
                if self._on_back() is False:
                    return
            except Exception:
                pass
        self.back_requested = True
        self.accept()


class HelpDialog(QDialog):
    """A searchable list of the written guides."""

    def __init__(self, parent=None, guide: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{branding.APP_NAME} Help & Guides")
        self.setMinimumSize(820, 600)
        self.resize(1060, 720)
        self._guides = list(help_content.GUIDES)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(10)

        title = QLabel("Help & Guides")
        title.setObjectName("title")
        outer.addWidget(title)
        intro = QLabel(
            "Pick a guide on the left, or search for a word such as "
            "“voice”, “slow”, “no audio” or “format”. Everything here works "
            "offline.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the guides…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.count = QLabel("")
        self.count.setObjectName("hint")
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.count)
        outer.addLayout(search_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(250)
        self.list.currentItemChanged.connect(self._show_current)
        split.addWidget(self.list)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        split.addWidget(self.browser)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 720])
        outer.addWidget(split, 1)

        footer = QHBoxLayout()
        about = QPushButton("About VoiceForge…")
        about.clicked.connect(lambda: show_about(self))
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(about)
        footer.addStretch(1)
        footer.addWidget(close)
        outer.addLayout(footer)

        shortcut = QShortcut(QKeySequence.Find, self)
        shortcut.activated.connect(self.search.setFocus)

        self._populate("")
        if guide:
            self._select_key(guide)

    def _populate(self, query: str) -> None:
        self._guides = help_content.find_guides(query)
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self._guides:
            item = QListWidgetItem(entry.title)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            item.setToolTip(entry.summary)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.count.setText(
            f"{len(self._guides)} guide"
            + ("" if len(self._guides) == 1 else "s"))
        if self._guides:
            self.list.setCurrentRow(0)
        else:
            self.browser.setHtml(
                "<h2>No guide matched</h2><p>Try a shorter word, for example "
                "<b>voice</b>, <b>slow</b>, <b>format</b> or <b>uninstall</b>."
                "</p>")

    def _filter(self, text: str) -> None:
        self._populate(text)

    def _select_key(self, key: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentRow(row)
                return

    def _show_current(self, current: QListWidgetItem | None,
                      _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        entry = next((g for g in help_content.GUIDES if g.key == key), None)
        if entry is not None:
            self.browser.setHtml(self._page(entry))

    @staticmethod
    def _page(entry: help_content.Guide) -> str:
        return (
            f"<div>{entry.body}</div>"
            f"<hr><p><i>{entry.summary}</i></p>"
        )


def show_help(parent: QWidget | None = None, guide: str | None = None) -> int:
    dialog = HelpDialog(parent, guide=guide)
    return int(dialog.exec())


def show_about(parent: QWidget | None = None,
               on_back: Callable[[], bool | None] | None = None) -> bool:
    """Show About; returns True when Back to Launcher was pressed."""
    dialog = AboutDialog(parent, on_back=on_back)
    dialog.exec()
    return bool(dialog.back_requested)
