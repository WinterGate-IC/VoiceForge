"""Qt rendering of the five dark schemes.

`themes.py` owns the colours; this module turns one of them into a QPalette
and a stylesheet. Every Qt surface - launcher, native app, settings dialog and
installer - calls `apply()`, so they are guaranteed to match.

The module-level colour names (``qt_theme.TEXT_MUTED`` and friends) always
describe the scheme that was applied last. Widgets built after `apply()` can
read them directly; widgets that want to follow a live scheme change should
use an object name (``muted``, ``hint``, ``pill``...) and let the stylesheet
do the work.
"""

from __future__ import annotations

from . import themes as _themes

SCHEMES = _themes.THEME_KEYS
DEFAULT_SCHEME = _themes.DEFAULT_THEME

# Populated from the default scheme, refreshed by apply().
WINDOW = ""
PANEL = ""
FIELD = ""
RAISED = ""
RAISED_HOVER = ""
BORDER = ""
BORDER_HOVER = ""
TEXT = ""
TEXT_MUTED = ""
TEXT_DISABLED = ""
ACCENT = ""
ACCENT_STRONG = ""
ACCENT_HOVER = ""
ACCENT_SOFT = ""
SELECTION = ""
DANGER = ""
DANGER_BG = ""
OK = ""
WARN = ""
PILL_BG = ""
PILL_TEXT = ""
SHADOW = ""

_current = DEFAULT_SCHEME


def _sync(name: str) -> dict[str, str]:
    """Publish `name`'s colours as module attributes and return the palette."""
    global _current
    palette = _themes.get(name)
    _current = name if name in _themes.THEMES else DEFAULT_SCHEME
    for key, value in palette.items():
        if key.isupper():
            globals()[key] = value
    return palette


_sync(DEFAULT_SCHEME)


def current() -> str:
    """The scheme most recently applied (or the default before any apply)."""
    return _current


def colors(name: str | None = None) -> dict[str, str]:
    return _themes.get(name or _current)


def build_palette(name: str | None = None):
    """A QPalette for Qt's own drawing: menus, tooltips, disabled text."""
    from PySide6.QtGui import QColor, QPalette

    c = colors(name)
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["WINDOW"],
        QPalette.ColorRole.WindowText: c["TEXT"],
        QPalette.ColorRole.Base: c["FIELD"],
        QPalette.ColorRole.AlternateBase: c["PANEL"],
        QPalette.ColorRole.ToolTipBase: c["RAISED"],
        QPalette.ColorRole.ToolTipText: c["TEXT"],
        QPalette.ColorRole.Text: c["TEXT"],
        QPalette.ColorRole.Button: c["RAISED"],
        QPalette.ColorRole.ButtonText: c["TEXT"],
        QPalette.ColorRole.BrightText: c["DANGER"],
        QPalette.ColorRole.Link: c["ACCENT"],
        QPalette.ColorRole.Highlight: c["SELECTION"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: c["TEXT_DISABLED"],
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role,
                         QColor(c["TEXT_DISABLED"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                     QColor(c["PANEL"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,
                     QColor(c["PANEL"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight,
                     QColor(c["BORDER"]))
    return palette


def stylesheet(name: str | None = None) -> str:
    """The complete Qt stylesheet for one scheme."""
    c = colors(name)
    return f"""
QMainWindow, QDialog {{ background: {c['WINDOW']}; }}
QWidget {{ color: {c['TEXT']}; }}
QWidget#page {{ background: {c['WINDOW']}; }}
QLabel:disabled {{ color: {c['TEXT_DISABLED']}; }}
QLabel#title {{ font-size: 24px; font-weight: 800; letter-spacing: .4px; }}
QLabel#heading {{ font-size: 15px; font-weight: 700; }}
QLabel#subtitle {{ color: {c['TEXT_MUTED']}; }}
QLabel#muted {{ color: {c['TEXT_MUTED']}; }}
QLabel#hint {{ color: {c['TEXT_DISABLED']}; font-size: 11px; }}
QLabel#mutedSmall {{ color: {c['TEXT_MUTED']}; font-size: 11px; }}
QLabel#blurb {{ color: {c['TEXT_MUTED']}; font-size: 12px; }}
QLabel#error {{ color: {c['DANGER']}; }}
QLabel#ok {{ color: {c['OK']}; }}
QLabel#warning {{ color: {c['WARN']}; }}

QToolBar {{
    background: {c['PANEL']}; border: 0; border-bottom: 1px solid {c['BORDER']};
    padding: 4px; spacing: 4px;
}}
QToolBar QToolButton {{
    padding: 6px 10px; border-radius: 6px; color: {c['TEXT']};
}}
QToolBar QToolButton:hover {{ background: {c['RAISED']}; }}
QStatusBar {{
    background: {c['PANEL']}; color: {c['TEXT_MUTED']};
    border-top: 1px solid {c['BORDER']};
}}

QTabWidget::pane {{
    border: 1px solid {c['BORDER']}; border-radius: 8px;
    background: {c['PANEL']}; top: -1px;
}}
QTabBar::tab {{
    background: transparent; color: {c['TEXT_MUTED']};
    padding: 9px 20px; border: 0; margin-right: 2px;
}}
QTabBar::tab:hover {{
    color: {c['TEXT']}; background: {c['PANEL']};
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    color: {c['TEXT']}; background: {c['PANEL']};
    border-bottom: 2px solid {c['ACCENT']};
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}}

QGroupBox {{
    background: {c['PANEL']}; border: 1px solid {c['BORDER']}; border-radius: 8px;
    margin-top: 16px; padding: 12px 10px 10px 10px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {c['TEXT_MUTED']};
}}

QPushButton {{
    background: {c['RAISED']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']};
    border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {c['RAISED_HOVER']}; border-color: {c['BORDER_HOVER']}; }}
QPushButton:pressed {{ background: {c['ACCENT_SOFT']}; }}
QPushButton:disabled {{
    background: {c['PANEL']}; color: {c['TEXT_DISABLED']};
    border-color: {c['BORDER']};
}}
QPushButton:default {{ border-color: {c['ACCENT']}; }}
QPushButton#primary {{
    background: {c['ACCENT_STRONG']}; color: #ffffff; border: none;
    font-weight: 700; padding: 9px 16px; border-radius: 6px;
}}
QPushButton#primary:hover {{ background: {c['ACCENT_HOVER']}; }}
QPushButton#primary:pressed {{ background: {c['ACCENT_HOVER']}; }}
QPushButton#primary:disabled {{
    background: {c['PANEL']}; color: {c['TEXT_DISABLED']};
}}
QPushButton#danger {{ color: {c['DANGER']}; }}
QPushButton#danger:hover {{
    background: {c['DANGER_BG']}; color: #ffffff; border-color: {c['DANGER']};
}}
QPushButton#link {{
    background: transparent; border: none; color: {c['ACCENT']};
    padding: 4px 6px; text-align: left;
}}
QPushButton#link:hover {{ color: {c['ACCENT_HOVER']}; text-decoration: underline; }}

QFrame#card {{
    background: {c['PANEL']}; border: 1px solid {c['BORDER']};
    border-radius: 10px;
}}
QFrame#card:hover {{ border-color: {c['BORDER_HOVER']}; }}
QFrame#card[selected="true"] {{
    border: 2px solid {c['ACCENT']}; background: {c['ACCENT_SOFT']};
}}
QFrame#swatch {{
    border: 2px solid {c['BORDER']}; border-radius: 8px;
}}
QFrame#swatch[selected="true"] {{ border-color: {c['ACCENT']}; }}

QLabel#pill {{
    background: {c['PILL_BG']}; color: {c['PILL_TEXT']}; border-radius: 8px;
    padding: 1px 8px; font-size: 10px; font-weight: 700;
}}
QLabel#badge {{ font-size: 10px; font-weight: 700; color: {c['WARN']}; }}
QLabel#badge[state="ok"] {{ color: {c['OK']}; }}
QLabel#badge[state="error"] {{ color: {c['DANGER']}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {c['FIELD']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']};
    border-radius: 6px; padding: 6px;
    selection-background-color: {c['SELECTION']}; selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c['ACCENT']}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {c['TEXT_DISABLED']}; background: {c['PANEL']};
}}

QComboBox {{
    background: {c['RAISED']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']};
    border-radius: 6px; padding: 4px 10px; min-height: 20px;
}}
QComboBox:hover {{ border-color: {c['BORDER_HOVER']}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {c['PANEL']}; color: {c['TEXT']}; border: 1px solid {c['BORDER']};
    selection-background-color: {c['SELECTION']}; selection-color: #ffffff;
    outline: 0;
}}

QSlider::groove:horizontal {{
    height: 6px; background: {c['BORDER']}; border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {c['ACCENT']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {c['TEXT']}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::handle:horizontal:disabled {{ background: {c['TEXT_DISABLED']}; }}
QSlider::groove:horizontal:disabled {{ background: {c['BORDER']}; }}

QScrollBar:vertical {{ background: {c['WINDOW']}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {c['BORDER']}; min-height: 24px; border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['BORDER_HOVER']}; }}
QScrollBar:horizontal {{ background: {c['WINDOW']}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {c['BORDER']}; min-width: 24px; border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['BORDER_HOVER']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QHeaderView::section {{
    background: {c['PANEL']}; color: {c['TEXT_MUTED']}; border: 0;
    border-bottom: 1px solid {c['BORDER']}; border-right: 1px solid {c['BORDER']};
    padding: 6px;
}}
QTableView, QTableWidget {{
    background: {c['FIELD']}; alternate-background-color: {c['PANEL']};
    gridline-color: {c['BORDER']}; border: 1px solid {c['BORDER']};
    border-radius: 8px;
    selection-background-color: {c['SELECTION']}; selection-color: #ffffff;
}}
QTableCornerButton::section {{ background: {c['PANEL']}; border: 0; }}

QSplitter::handle {{ background: {c['BORDER']}; }}
QSplitter::handle:hover {{ background: {c['BORDER_HOVER']}; }}

QCheckBox {{ spacing: 8px; }}
QRadioButton {{ spacing: 8px; }}
QMenu {{ background: {c['PANEL']}; border: 1px solid {c['BORDER']}; }}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: {c['ACCENT_HOVER']}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {c['BORDER']}; margin: 4px 8px; }}
QToolTip {{
    background: {c['RAISED']}; color: {c['TEXT']}; border: 1px solid {c['BORDER_HOVER']};
    padding: 4px 6px;
}}
QProgressBar {{
    background: {c['FIELD']}; border: 1px solid {c['BORDER']}; border-radius: 6px;
    text-align: center; color: {c['TEXT']}; min-height: 18px;
}}
QProgressBar::chunk {{ background: {c['ACCENT_STRONG']}; border-radius: 5px; }}
QListWidget, QTreeWidget, QListView {{
    background: {c['FIELD']}; border: 1px solid {c['BORDER']}; border-radius: 6px;
    outline: 0;
}}
QListWidget::item, QTreeWidget::item {{ padding: 5px 8px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {c['SELECTION']}; color: #ffffff;
}}
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QDialogButtonBox {{ background: transparent; }}
"""


# The old public name; kept because front-ends import it.
STYLE = stylesheet(DEFAULT_SCHEME)


def apply(app, scheme: str | None = None) -> str:
    """Give the QApplication one of the dark schemes. Returns its name."""
    palette = _sync(scheme or _current)
    name = _current
    app.setStyle("Fusion")
    app.setPalette(build_palette(name))
    app.setStyleSheet(stylesheet(name))
    app.setProperty("voiceforge_theme", name)
    return name
