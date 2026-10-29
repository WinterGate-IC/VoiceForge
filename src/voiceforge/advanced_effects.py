"""The Advanced voice lab: continuous, undoable sound-design controls.

The Speak tab keeps the quick knobs (rate, pitch, volume, chain). This dialog
opens the rest of the workshop: tone shelves, compression, stereo width,
echo, reverb, chorus, saturation, ring modulation, tremolo, vibrato, tape
flutter and bit-crush.

Nothing here is a special case. Every control writes one registered setting,
so a lab experiment can be previewed, saved into a voice profile, put in a
preset, undone, or rendered from the CLI exactly like a pitch shift.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from .settings import ADVANCED_PARAMS, PARAMS, advanced_defaults


@dataclass(frozen=True)
class Knob:
    key: str
    label: str
    lo: int
    hi: int
    scale: int = 1
    suffix: str = ""
    signed: bool = False


TONE: tuple[Knob, ...] = (
    Knob("bass", "Bass shelf", -18, 18, suffix=" dB", signed=True),
    Knob("treble", "Treble shelf", -16, 16, suffix=" dB", signed=True),
    Knob("punch", "Punch / compression", 0, 100, suffix="%"),
    Knob("width", "Stereo width", 0, 200, suffix="%"),
)

SPACE: tuple[Knob, ...] = (
    Knob("echo_ms", "Echo delay", 40, 1500, suffix=" ms"),
    Knob("echo_feedback", "Echo repeats", 0, 95, scale=100, suffix="%"),
    Knob("echo_mix", "Echo amount", 0, 100, scale=100, suffix="%"),
    Knob("reverb", "Reverb", 0, 100, scale=100, suffix="%"),
    Knob("chorus", "Chorus / double", 0, 100, scale=100, suffix="%"),
)

CHARACTER: tuple[Knob, ...] = (
    Knob("drive", "Saturation", 0, 100, scale=100, suffix="%"),
    Knob("ring", "Ring modulation", 0, 100, scale=100, suffix="%"),
    Knob("ring_rate", "Ring frequency", 20, 2000, suffix=" Hz"),
    Knob("tremolo", "Tremolo depth", 0, 100, scale=100, suffix="%"),
    Knob("tremolo_rate", "Tremolo speed", 5, 140, scale=10, suffix=" Hz"),
    Knob("vibrato", "Vibrato depth", 0, 100, scale=100, suffix="%"),
    Knob("vibrato_rate", "Vibrato speed", 10, 120, scale=10, suffix=" Hz"),
    Knob("flutter", "Tape flutter", 0, 100, scale=100, suffix="%"),
    Knob("crush", "Bit-crush", 0, 12, suffix=" bits"),
)

KNOBS: dict[str, Knob] = {k.key: k for group in (TONE, SPACE, CHARACTER)
                          for k in group}

PRESETS: dict[str, dict] = {
    "Bass boost": {"bass": 12, "treble": -2, "punch": 35, "drive": 0.08},
    "Deep cinema": {
        "bass": 9, "treble": 2, "punch": 65, "width": 130,
        "reverb": 0.18, "drive": 0.15,
    },
    "Cathedral echo": {
        "echo_ms": 520, "echo_feedback": 0.52, "echo_mix": 0.35,
        "reverb": 0.45, "width": 120,
    },
    "Robot": {
        "ring": 0.55, "ring_rate": 110, "crush": 4, "drive": 0.20,
        "width": 70,
    },
    "Haunted": {
        "bass": 6, "echo_ms": 360, "echo_feedback": 0.45, "echo_mix": 0.30,
        "reverb": 0.55, "vibrato": 0.18, "vibrato_rate": 3.0,
    },
    "Wide stage": {
        "width": 175, "chorus": 0.35, "reverb": 0.22, "treble": 3,
    },
    "Alien signal": {
        "ring": 0.45, "ring_rate": 340, "vibrato": 0.55, "vibrato_rate": 8.5,
        "crush": 3, "width": 150,
    },
    "Worn tape": {
        "bass": 3, "treble": -8, "crush": 2, "flutter": 0.45,
        "reverb": 0.12, "punch": 25,
    },
    "Ghost whisper": {
        "reverb": 0.70, "chorus": 0.50, "width": 160, "treble": 2,
        "echo_mix": 0.15,
    },
}


def describe_effects(values: dict | None) -> str:
    """A short, human sentence for the current lab settings."""
    if not values:
        return ""

    def number(key: str, default: float = 0.0) -> float:
        try:
            return float(values.get(key, default))
        except (TypeError, ValueError):
            return default

    parts: list[str] = []
    if number("bass"):
        parts.append(f"Bass {int(round(number('bass'))):+d} dB")
    if number("treble"):
        parts.append(f"Treble {int(round(number('treble'))):+d} dB")
    if number("punch"):
        parts.append(f"Punch {number('punch'):.0f}%")
    if number("width", 100) != 100:
        parts.append(f"Width {number('width', 100):.0f}%")
    if number("echo_mix"):
        parts.append(f"Echo {number('echo_ms', 300):.0f} ms "
                     f"({number('echo_mix') * 100:.0f}%)")
    if number("reverb"):
        parts.append(f"Reverb {number('reverb') * 100:.0f}%")
    if number("chorus"):
        parts.append(f"Chorus {number('chorus') * 100:.0f}%")
    if number("drive"):
        parts.append(f"Drive {number('drive') * 100:.0f}%")
    if number("ring"):
        parts.append(f"Ring {number('ring_rate', 220):.0f} Hz")
    if number("tremolo"):
        parts.append(f"Tremolo {number('tremolo_rate', 5):g} Hz")
    if number("vibrato"):
        parts.append(f"Vibrato {number('vibrato_rate', 5.5):g} Hz")
    if number("flutter"):
        parts.append(f"Flutter {number('flutter') * 100:.0f}%")
    if number("crush"):
        parts.append(f"Crush {number('crush'):.0f}")
    return " · ".join(parts)


def lab_values(settings: dict | None = None) -> dict:
    """Neutral defaults, overlaid with whichever lab keys exist."""
    values = advanced_defaults()
    if settings:
        for key in ADVANCED_PARAMS:
            if key in settings:
                values[key] = settings[key]
    return values


class KnobRow(QWidget):
    """One labelled slider with a live numeric readout."""

    def __init__(self, knob: Knob, value: float, parent=None) -> None:
        super().__init__(parent)
        self.knob = knob
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(knob.lo, knob.hi)
        self.slider.setValue(self._to_slider(value))
        self.slider.setPageStep(max(1, (knob.hi - knob.lo) // 12))
        self.slider.setToolTip(PARAMS[knob.key].help)

        name = QLabel(knob.label)
        name.setMinimumWidth(150)
        name.setToolTip(PARAMS[knob.key].help)
        self.readout = QLabel()
        self.readout.setMinimumWidth(78)
        self.readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(name)
        row.addWidget(self.slider, 1)
        row.addWidget(self.readout)

        self.slider.valueChanged.connect(self._refresh)
        self._refresh(self.slider.value())

    def _to_slider(self, value: float) -> int:
        return int(round(float(value) * self.knob.scale))

    def _refresh(self, raw: int) -> None:
        value = raw / self.knob.scale
        if self.knob.scale == 1:
            text = f"{int(value):+d}" if self.knob.signed else str(int(value))
        else:
            text = f"{value:.2f}".rstrip("0").rstrip(".")
        self.readout.setText(f"{text}{self.knob.suffix}")

    def value(self) -> int | float:
        raw = self.slider.value() / self.knob.scale
        return raw if self.knob.scale != 1 else int(raw)


class AdvancedEffectsDialog(QDialog):
    """Modal voice lab. Read ``values()`` after a successful ``exec()``."""

    def __init__(self, values: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced voice lab")
        self.setModal(True)
        self.resize(820, 680)
        self.apply_and_preview = False
        self._rows: dict[str, KnobRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        title = QLabel("Shape the voice itself")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Every control below is a normal setting: preview it, save it into "
            "a voice, and undo it later. Start from a preset or build your own.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        preset_box = QGroupBox("Start from a preset")
        preset_layout = QGridLayout(preset_box)
        preset_layout.setHorizontalSpacing(8)
        preset_layout.setVerticalSpacing(6)
        for index, name in enumerate(PRESETS):
            button = QPushButton(name)
            button.setMinimumHeight(30)
            button.clicked.connect(
                lambda _checked=False, preset=name: self._apply_preset(preset))
            preset_layout.addWidget(button, index // 5, index % 5)
        layout.addWidget(preset_box)

        tabs = QTabWidget()
        tabs.addTab(self._page(TONE), "Tone & width")
        tabs.addTab(self._page(SPACE), "Space & echo")
        tabs.addTab(self._page(CHARACTER), "Character")
        layout.addWidget(tabs, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("mutedSmall")
        layout.addWidget(self.summary)

        footer = QHBoxLayout()
        reset = QPushButton("Reset all")
        reset.clicked.connect(self._reset)
        footer.addWidget(reset)
        footer.addStretch(1)
        preview = QPushButton("Apply & preview")
        preview.setToolTip(
            "Keep these settings and render a short preview right away.")
        preview.clicked.connect(self._apply_and_preview)
        footer.addWidget(preview)
        apply_button = QPushButton("Apply")
        apply_button.setObjectName("primary")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        footer.addWidget(apply_button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        layout.addLayout(footer)

        self._set_values(lab_values(values))
        self._update_summary()

    # ---- construction --------------------------------------------------
    def _page(self, knobs: tuple[Knob, ...]) -> QScrollArea:
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(12)
        for knob in knobs:
            row = KnobRow(knob, lab_values().get(knob.key, 0))
            row.slider.valueChanged.connect(self._update_summary)
            self._rows[knob.key] = row
            column.addWidget(row)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    # ---- values --------------------------------------------------------
    def _set_values(self, values: dict) -> None:
        for key, row in self._rows.items():
            row.slider.blockSignals(True)
            row.slider.setValue(row._to_slider(values.get(key, row.knob.lo)))
            row.slider.blockSignals(False)

    def values(self) -> dict:
        out: dict = {}
        for key, row in self._rows.items():
            spec = PARAMS[key]
            value = row.value()
            out[key] = int(value) if spec.kind == "int" else round(float(value), 2)
        return out

    def _reset(self) -> None:
        self._set_values(advanced_defaults())
        self._update_summary()

    def _apply_preset(self, name: str) -> None:
        settings = advanced_defaults()
        settings.update(PRESETS.get(name, {}))
        self._set_values(settings)
        self._update_summary()

    def _update_summary(self) -> None:
        text = describe_effects(self.values())
        self.summary.setText(
            f"Active: {text}" if text else
            "Active: none. The voice is untouched by the lab.")

    def _apply_and_preview(self) -> None:
        self.apply_and_preview = True
        self.accept()
