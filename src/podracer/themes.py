"""Themes: palettes + generated QSS for the whole app.

A Theme is a named palette plus the role mapping that turns it into a
stylesheet. `apply_theme()` re-skins the running app instantly, so the
status-bar switcher is a real one-click flip. Themes are added one at
a time as plain palette data (see magenta_daydream / grey_moonlight);
the QSS template is shared and role-driven, so a theme only supplies
colors, never styling.

Contrast discipline: body text pairs must reach WCAG AA (>= 4.5:1);
the tests check every theme's text-on-panel and text-on-accent pairs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QPalette

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def _rgb(hex_color: str) -> tuple[int, int, int]:
    if not _HEX_RE.match(hex_color):
        raise ValueError(f"not a hex color: {hex_color!r}")
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def darken(hex_color: str, factor: float = 0.82) -> str:
    """Scale a hex color toward black; keeps hue for pressed states."""
    r, g, b = _rgb(hex_color)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def rgba_of(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a #rrggbb color."""
    r, g, b = (c / 255 for c in _rgb(hex_color))

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_PRESS_FACTORS = (0.55, 0.62, 0.70, 0.78, 0.86, 0.94)


def pressed_color(accent: str, text_on_accent: str) -> str:
    """Darkest shade of `accent` that still hits WCAG AA against its text.

    `darken(accent, 0.55)` assumes light text on a dark accent. Light
    accents carry dark text (that's how they pass AA), and darkening a
    light accent into mid-tones flips the luminance and drops contrast
    to ~2:1 -- the invisible-text-on-selection bug (menu checked state,
    pressed buttons). Walk from the deepest darken up and return the
    darkest shade that still reads; if none does, fall back to the
    accent itself (guaranteed to pass, since the base accent is tested).
    """
    for factor in _PRESS_FACTORS:
        cand = darken(accent, factor)
        if contrast_ratio(cand, text_on_accent) >= 4.5:
            return cand
    return accent


@dataclass(frozen=True)
class Theme:
    name: str
    colors: dict[str, str]                       # the raw palette, as given
    window_gradient: tuple[str, str]             # backdrop sweep (from, to)
    accent: str                                  # primary: buttons, selection
    accent2: str                                 # secondary: focus, links
    panel_bg: str                                # table/input background
    panel_text: str                              # text on panels
    text_on_accent: str = "#ffffff"
    status_bg: str = "rgba(12, 10, 26, 0.35)"    # translucent over the gradient
    status_text: str = "#ffffff"
    header_text: str = "#ffffff"                  # text on the header gradient
    header_gradient: tuple[str, str] = ("#723c70", "#455e89")
    # Derived roles; empty means "compute from accent".
    button_to: str = ""                          # second gradient stop
    button_pressed: str = ""                     # pressed state
    hover_tint: str = ""                         # item hover wash
    alternate_tint: str = ""                     # row striping

    def _role(self, value: str, default: str) -> str:
        return value or default

    def qss(self) -> str:
        from_, to_ = self.window_gradient
        h1, h2 = self.header_gradient
        button_to = resolved_button_to(self)
        pressed = resolved_pressed(self)
        hover = self._role(self.hover_tint, rgba_of(self.accent, 0.12))
        alternate = self._role(self.alternate_tint, rgba_of(self.accent, 0.08))
        return f"""
QMainWindow {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {from_}, stop:1 {to_});
}}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: rgba(255, 255, 255, 0.35); }}

QTreeView, QTableView {{
    background: {self.panel_bg};
    alternate-background-color: {alternate};
    color: {self.panel_text};
    border: none;
    gridline-color: rgba(127, 127, 140, 0.25);
    selection-background-color: {self.accent};
    selection-color: {self.text_on_accent};
}}
QTreeView::item:hover, QTableView::item:hover {{ background: {hover}; }}

QHeaderView::section {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {h1}, stop:1 {h2});
    color: {self.header_text};
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 0.18);
    padding: 5px 8px;
}}

QLineEdit {{
    background: {self.panel_bg};
    color: {self.panel_text};
    border: 1px solid {self.accent2};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {self.accent};
    selection-color: {self.text_on_accent};
}}
QLineEdit:focus {{ border: 1px solid {self.accent}; }}

QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {self.accent}, stop:1 {button_to});
    color: {self.text_on_accent};
    border: 1px solid rgba(255, 255, 255, 0.30);
    border-radius: 6px;
    padding: 4px 12px;
}}
QPushButton:hover {{ background: {rgba_of(self.accent, 0.85)}; }}
QPushButton:pressed {{ background: {pressed}; }}
QPushButton:disabled {{
    background: {rgba_of(self.accent, 0.35)};
    color: {rgba_of(self.text_on_accent, 0.6)};
    border: 1px solid {rgba_of(self.accent, 0.5)};
}}
QPushButton[flat="true"] {{
    background: transparent;
    border: none;
    color: {self.status_text};
    padding: 2px 6px;
    text-align: left;
}}
QPushButton[flat="true"]:hover {{ background: rgba(255, 255, 255, 0.15); }}

QProgressBar {{
    background: rgba(255, 255, 255, 0.25);
    border: none;
    border-radius: 4px;
    color: {self.text_on_accent};
    text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {self.accent}, stop:1 {self.accent2});
    border-radius: 4px;
}}

QStatusBar {{
    background: {self.status_bg};
    color: {self.status_text};
}}
QStatusBar::item {{ border: none; }}

QMenu {{
    background: {self.panel_bg};
    color: {self.panel_text};
    border: 1px solid {self.accent2};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 24px 5px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {self.accent}; color: {self.text_on_accent}; }}
QMenu::item:checked {{ background: {pressed}; color: {self.text_on_accent}; }}

QToolTip {{
    background: {self.panel_bg};
    color: {self.panel_text};
    border: 1px solid {self.accent2};
    padding: 3px 6px;
}}

QScrollBar:vertical {{ background: rgba(255, 255, 255, 0.15); width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.45); border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: rgba(255, 255, 255, 0.15); height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: rgba(255, 255, 255, 0.45); border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""

    def palette(self) -> QPalette:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(self.window_gradient[0]))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(self.status_text))
        pal.setColor(QPalette.ColorRole.Base, QColor(self.panel_bg))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(self.accent))
        pal.setColor(QPalette.ColorRole.Text, QColor(self.panel_text))
        pal.setColor(QPalette.ColorRole.Button, QColor(self.accent))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(self.text_on_accent))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(self.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(self.text_on_accent))
        pal.setColor(QPalette.ColorRole.Link, QColor(self.accent2))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(self.accent2))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.panel_bg))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(self.panel_text))
        return pal


def button_gradient_stop(accent: str, text_on_accent: str) -> str:
    """The gradient's darker stop: the gentle 0.82 darken when it reads.

    Buttons are accent -> this stop, with text on top; the stop must
    hold AA against the same text. The 0.82 darken is fine for dark
    accents (light text); light accents carry dark text, so darkening
    breaks the bottom half -- fall back to the darkest safe shade.
    """
    cand = darken(accent)
    if contrast_ratio(cand, text_on_accent) >= 4.5:
        return cand
    return pressed_color(accent, text_on_accent)


def resolved_pressed(theme: Theme) -> str:
    """The pressed/checked background a theme actually renders with.

    Honors an explicit `button_pressed` override; otherwise the
    polarity-aware `pressed_color`. Kept public so tests guard the same
    value the QSS emits (an override must also hold contrast).
    """
    return theme.button_pressed or pressed_color(
        theme.accent, theme.text_on_accent
    )


def resolved_button_to(theme: Theme) -> str:
    """The gradient's darker stop a theme actually renders with."""
    return theme.button_to or button_gradient_stop(
        theme.accent, theme.text_on_accent
    )


def magenta_daydream() -> Theme:
    """Magenta Daydream: cherry-rose -> pacific-cyan sweep.

    Palette as given by the user; panel colors adjusted for contrast
    (near-white panels carry dark plum text; cyan is used for
    borders/links, not body text).
    """
    return Theme(
        name="Magenta Daydream",
        colors={
            "cherry-rose": "#b7094c",
            "dark-raspberry": "#a01a58",
            "royal-plum": "#892b64",
            "velvet-purple": "#723c70",
            "dusty-grape": "#5c4d7d",
            "dusk-blue": "#455e89",
            "rich-cerulean": "#2e6f95",
            "cerulean": "#1780a1",
            "pacific-cyan": "#0091ad",
        },
        window_gradient=("#b7094c", "#0091ad"),
        accent="#b7094c",
        accent2="#1780a1",
        panel_bg="#fdf6fa",
        panel_text="#2b1420",
        header_gradient=("#723c70", "#455e89"),
        button_to="#a01a58",           # dark-raspberry, the original pair
        button_pressed="#892b64",      # royal-plum
    )


def grey_moonlight() -> Theme:
    """Grey Moonlight: onyx -> graphite monochrome sweep.

    Palette as given by the user; panel text added for contrast (the
    palette has no light color), white-tinted hovers/rows so the dark
    surfaces stay readable.
    """
    return Theme(
        name="Grey Moonlight",
        colors={
            "onyx": "#131316",
            "shadow-grey": "#1c1c21",
            "shadow-grey-2": "#26262c",
            "graphite": "#2f3037",
            "gunmetal": "#393a41",
            "charcoal": "#4b4c52",
            "charcoal-2": "#5b5c62",
            "dim-grey": "#6a6b70",
        },
        window_gradient=("#131316", "#2f3037"),
        accent="#5b5c62",              # charcoal-2: white text clears AA
        accent2="#6a6b70",             # dim-grey
        panel_bg="#1c1c21",            # shadow-grey
        panel_text="#e9e9ee",          # derived: no light color in palette
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#e9e9ee",
        header_gradient=("#26262c", "#393a41"),
        hover_tint="rgba(255, 255, 255, 0.08)",
        alternate_tint="rgba(255, 255, 255, 0.04)",
    )


def zen_garden() -> Theme:
    """Zen Garden: sage -> pale-sage sweep, cream panels, sand accent.

    Palette as given by the user. Sand is a light warm color, so the
    accent carries dark text (white on sand fails AA); panel text is
    derived dark-warm; the header gradient is sage -> sand with dark
    text for the same reason.
    """
    return Theme(
        name="Zen Garden",
        colors={
            "sage": "#8fa28a",
            "pale-sage": "#c7d3c0",
            "cream": "#f7f4ed",
            "sand": "#c8a96b",
        },
        window_gradient=("#8fa28a", "#c7d3c0"),
        accent="#c8a96b",               # sand: dark text clears AA
        accent2="#8fa28a",              # sage
        panel_bg="#f7f4ed",             # cream
        panel_text="#3a382f",           # derived dark-warm
        text_on_accent="#33302a",       # derived dark-warm
        status_bg="rgba(255, 255, 255, 0.35)",
        status_text="#33302a",
        header_gradient=("#8fa28a", "#c8a96b"),
        header_text="#33302a",
    )


def bubblegum_haze() -> Theme:
    """Bubblegum Haze: coral -> mint pastel sweep, lime panels.

    Palette as given by the user. Like Zen Garden this is a light
    pastel set: the accent carries dark text (white on coral fails
    AA), the focus color is a derived deeper coral so borders stay
    visible on the pale lime panels.
    """
    return Theme(
        name="Bubblegum Haze",
        colors={
            "coral": "#ff9d9d",
            "peach": "#ffc5aa",
            "lime": "#eef8cd",
            "mint": "#bbf1d2",
        },
        window_gradient=("#ff9d9d", "#bbf1d2"),
        accent="#ff9d9d",               # coral: dark text clears AA
        accent2="#cc7e7e",              # derived deeper coral for focus
        panel_bg="#eef8cd",             # pale lime
        panel_text="#383d2e",           # derived dark-warm olive
        text_on_accent="#40262a",       # derived dark-warm
        status_bg="rgba(255, 255, 255, 0.35)",
        status_text="#40262a",
        header_gradient=("#ffc5aa", "#bbf1d2"),
        header_text="#40262a",
    )


def hide_and_seek() -> Theme:
    """Ikea Hide and Seek: IKEA-style steel blue on warm off-whites.

    Palette as given by the user. The palette's deepest blue is too
    light for white text (2.5:1), so the accent is a derived deeper
    steel (#5d7279, white text 5.1:1) — the IKEA signature. Headers
    stay on the raw blues with dark text.
    """
    return Theme(
        name="Ikea Hide and Seek",
        colors={
            "steel-blue": "#89a8b2",
            "pale-blue-grey": "#b3c8cf",
            "warm-grey": "#e5e1da",
            "cream": "#f1f0e8",
        },
        window_gradient=("#89a8b2", "#b3c8cf"),
        accent="#5d7279",               # derived deeper steel: white text
        accent2="#89a8b2",              # steel-blue focus borders
        panel_bg="#f1f0e8",             # IKEA off-white
        panel_text="#2f3233",           # derived dark warm-grey
        text_on_accent="#ffffff",
        status_bg="rgba(255, 255, 255, 0.35)",
        status_text="#2f3233",
        header_gradient=("#89a8b2", "#b3c8cf"),
        header_text="#2f3233",
        alternate_tint="rgba(229, 225, 218, 0.8)",   # warm-grey row stripes
    )


def lipstick_hyperfemme() -> Theme:
    """Lipstick Hyperfemme: hot pink -> lavender sweep, blush panels.

    Palette as given by the user. Hot pink is light, so the accent
    carries dark plum text (white fails AA); lavender keeps the focus
    and header roles.
    """
    return Theme(
        name="Lipstick Hyperfemme",
        colors={
            "lipstick-pink": "#ff78c4",
            "lavender": "#e1aeff",
            "blush": "#ffbdf7",
            "pale-pink": "#ffecec",
        },
        window_gradient=("#ff78c4", "#e1aeff"),
        accent="#ff78c4",               # hot pink: dark text clears AA
        accent2="#e1aeff",              # lavender
        panel_bg="#ffecec",             # pale pink
        panel_text="#3a1f33",           # derived dark plum
        text_on_accent="#3a1f33",
        status_bg="rgba(255, 255, 255, 0.35)",
        status_text="#3a1f33",
        header_gradient=("#ff78c4", "#e1aeff"),
        header_text="#3a1f33",
    )


def butch_cassidy() -> Theme:
    """Butch Cassidy: dark charcoal-plum with a rosewood accent.

    Palette as given by the user. Rosewood is dark enough for white
    text (6.4:1); pale sage-grey carries focus/links; the header
    gradient runs dark plum -> rosewood with white text.
    """
    return Theme(
        name="Butch Cassidy",
        colors={
            "charcoal": "#37353e",
            "dark-plum": "#44444e",
            "rosewood": "#715a5a",
            "pale-sage": "#d3dad9",
        },
        window_gradient=("#37353e", "#44444e"),
        accent="#715a5a",               # rosewood: white text clears AA
        accent2="#d3dad9",              # pale sage-grey
        panel_bg="#44444e",             # dark-plum
        panel_text="#e8e6e2",           # derived warm light grey
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#e8e6e2",
        header_gradient=("#44444e", "#715a5a"),
        header_text="#ffffff",
        hover_tint="rgba(113, 90, 90, 0.35)",      # rosewood wash
        alternate_tint="rgba(255, 255, 255, 0.04)",
    )


def analog_sunrise() -> Theme:
    """Analog Sunrise: sunset orange over deep slate.

    Palette as given by the user. Orange is light, so the accent
    carries dark text (white fails AA); the header runs the actual
    sunrise gradient (orange -> slate) with dark text; the cool slate
    sweep carries the light-grey panels.
    """
    return Theme(
        name="Analog Sunrise",
        colors={
            "sunset-orange": "#fe7743",
            "deep-slate": "#273f4f",
            "slate-blue": "#447d9b",
            "light-grey": "#d7d7d7",
        },
        window_gradient=("#273f4f", "#447d9b"),
        accent="#fe7743",               # sunset orange: dark text
        accent2="#447d9b",              # slate-blue focus
        panel_bg="#d7d7d7",             # light grey
        panel_text="#22282e",           # derived cool dark slate
        text_on_accent="#2b2118",       # derived warm dark
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#e8eaec",          # derived near-white
        header_gradient=("#fe7743", "#6997af"),   # the sunrise (2nd stop lightened: dark text must read on the blue)
        header_text="#2b2118",
    )


def insane_default() -> Theme:
    """Insane Default: deep navy 'default' with a hot-pink accent.

    Palette as given by the user. The joke is the framing: navy and
    slate read as a boring system default until the pink shows up.
    Hot pink is dark enough for white text (5.04:1); ice blue carries
    focus, the header runs slate -> pink.
    """
    return Theme(
        name="Insane Default",
        colors={
            "deep-navy": "#283149",
            "slate-indigo": "#404b69",
            "hot-pink": "#da0463",
            "ice-blue": "#dbedf3",
        },
        window_gradient=("#283149", "#404b69"),
        accent="#da0463",               # hot pink: white text clears AA
        accent2="#dbedf3",              # ice blue
        panel_bg="#404b69",             # slate indigo
        panel_text="#e6eef3",           # derived ice
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#e6eef3",
        header_gradient=("#404b69", "#da0463"),
        header_text="#ffffff",
    )


def frutiger_aero() -> Theme:
    """Frutiger Aero: 2000s glossy aqua — deep teal -> bright cyan
    sweep, icy panels. Light-on-dark headers; white text clears AA on
    the teal accent (5.0:1).
    """
    return Theme(
        name="Frutiger Aero",
        colors={
            "lagoon": "#0e7490",
            "reef": "#0b7a8f",
            "surge": "#0891b2",
            "spray": "#22d3ee",
            "mist": "#eef9ff",
            "abyss": "#0b3a4a",
            "deepwater": "#083344",
        },
        window_gradient=("#0e7490", "#22d3ee"),
        accent="#0b7a8f",               # reef: white text clears AA
        accent2="#0891b2",              # surge: focus/borders
        panel_bg="#eef9ff",             # mist
        panel_text="#0b3a4a",           # abyss
        text_on_accent="#ffffff",
        status_bg="rgba(8, 51, 68, 0.45)",   # deepwater haze over the cyan
        status_text="#eef9ff",               # mist: light clears the teal
        header_gradient=("#0e7490", "#0b5f74"),
        header_text="#ffffff",
        button_to="#0e5f73",            # glossy dark-teal second stop
    )


def aqua() -> Theme:
    """Aqua: classic OS X pinstripe blues with a glossy blue accent."""
    return Theme(
        name="Aqua",
        colors={
            "pinstripe": "#7f9fc9",
            "pale-aqua": "#dfeaf7",
            "aqua-blue": "#2e6db4",
            "cobalt": "#1f4f8f",
            "sky": "#3b7dd8",
            "cloud": "#f4f6f9",
            "navy": "#17263a",
            "ink": "#1c2733",
        },
        window_gradient=("#7f9fc9", "#dfeaf7"),
        accent="#2e6db4",               # aqua blue: white text clears AA
        accent2="#3b7dd8",              # sky: focus/borders
        panel_bg="#f4f6f9",             # cloud
        panel_text="#1c2733",           # ink
        text_on_accent="#ffffff",
        status_bg="rgba(255, 255, 255, 0.45)",
        status_text="#17263a",          # navy
        header_gradient=("#2e6db4", "#1f4f8f"),
        header_text="#ffffff",
        button_to="#1f4f8f",            # glossy blue second stop
    )


def dark_aqua() -> Theme:
    """Dark Aqua: the Aqua blues sunk into a deep-navy night."""
    return Theme(
        name="Dark Aqua",
        colors={
            "midnight": "#152238",
            "steel": "#2b4a6f",
            "aqua-blue": "#2e6db4",
            "cobalt": "#1f4f8f",
            "sky": "#3b7dd8",
            "slate": "#1c2733",
            "ice": "#dbe7f5",
        },
        window_gradient=("#152238", "#2b4a6f"),
        accent="#2e6db4",               # aqua blue: white text clears AA
        accent2="#3b7dd8",              # sky: focus/borders
        panel_bg="#1c2733",             # slate
        panel_text="#dbe7f5",           # ice
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#dbe7f5",
        header_gradient=("#2e6db4", "#1f4f8f"),
        header_text="#ffffff",
        button_to="#1f4f8f",
    )


def just_blues() -> Theme:
    """Just Blues: periwinkle light with a deep-blue accent (palette
    e3e8f8 / c0c5cd / 3e588f / 203562, colorhunt.co)."""
    return Theme(
        name="Just Blues",
        colors={
            "cloud": "#e3e8f8",
            "fog": "#c0c5cd",
            "blue": "#3e588f",
            "navy": "#203562",
        },
        window_gradient=("#c0c5cd", "#e3e8f8"),
        accent="#3e588f",               # blue: white text clears AA
        accent2="#203562",              # navy: focus/borders
        panel_bg="#e3e8f8",             # cloud
        panel_text="#203562",           # navy
        text_on_accent="#ffffff",
        status_bg="rgba(255, 255, 255, 0.45)",
        status_text="#203562",
        header_gradient=("#3e588f", "#203562"),
        header_text="#ffffff",
        button_to="#203562",
    )


def lilac_love() -> Theme:
    """Lilac Love: deep-purple night with a vivid violet accent
    (palette 2d033b / 810ca8 / c147e9 / e5b8f4, colorhunt.co). Dark.
    """
    return Theme(
        name="Lilac Love",
        colors={
            "deep-plum": "#2d033b",
            "vivid-violet": "#810ca8",
            "bright-lilac": "#c147e9",
            "pale-lilac": "#e5b8f4",
        },
        window_gradient=("#2d033b", "#810ca8"),
        accent="#810ca8",               # vivid violet: white clears AA
        accent2="#c147e9",              # bright lilac: focus/borders
        panel_bg="#2d033b",             # deep plum
        panel_text="#e5b8f4",           # pale lilac
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.35)",
        status_text="#e5b8f4",
        header_gradient=("#810ca8", "#2d033b"),
        header_text="#ffffff",
        button_to="#5a0778",            # deeper violet second stop
    )


def minty_forest() -> Theme:
    """Minty Forest: cream panels under a mint -> teal sweep with a
    deep-forest accent (palette 1a312c / 428475 / 89d7b7 / fff4e1,
    colorhunt.co)."""
    return Theme(
        name="Minty Forest",
        colors={
            "forest": "#1a312c",
            "deep-teal": "#2e5c4e",
            "teal": "#428475",
            "mint": "#89d7b7",
            "cream": "#fff4e1",
        },
        window_gradient=("#89d7b7", "#428475"),
        accent="#1a312c",               # forest: white text clears AA
        accent2="#428475",              # teal: focus/borders
        panel_bg="#fff4e1",             # cream
        panel_text="#1a312c",           # forest
        text_on_accent="#ffffff",
        status_bg="rgba(255, 255, 255, 0.45)",
        status_text="#1a312c",
        header_gradient=("#2e5c4e", "#1a312c"),
        header_text="#ffffff",
        button_to="#2e5c4e",            # deep teal second stop
    )


def stoner_shore() -> Theme:
    """Stoner Shore: sea-glass teal over deep slate, salmon surf accent.

    Palette as given by the user. Sea glass is light enough to need
    dark text (white fails AA); the header runs salmon -> sea glass
    with the same deep-sea text; the slate -> teal sweep carries the
    near-white panels.
    """
    return Theme(
        name="Stoner Shore",
        colors={
            "salmon": "#ee8572",
            "slate": "#35495e",
            "teal": "#347474",
            "sea-glass": "#63b7af",
        },
        window_gradient=("#35495e", "#347474"),
        accent="#63b7af",               # sea glass: dark text
        accent2="#ee8572",              # salmon: focus/borders
        panel_bg="#2d3d4e",             # derived deeper slate
        panel_text="#eef3f6",           # derived near-white
        text_on_accent="#173a3d",       # derived deep sea
        status_bg="rgba(16, 27, 38, 0.45)",
        status_text="#eef3f6",
        header_gradient=("#ee8572", "#63b7af"),   # the surf
        header_text="#173a3d",
    )


def carmillas_snack() -> Theme:
    """Carmilla's Snack: blood-red shades, claret to near-black.

    Palette as given (Blood Shades). Every color is a dark red, so
    light text clears AA everywhere; the sweep runs the lightest red
    down to the near-black, and the pale-rose panels keep it warmer
    than pure white.
    """
    return Theme(
        name="Carmilla's Snack",
        colors={
            "claret": "#851a1a",
            "crimson-dark": "#7e0d0e",
            "oxblood": "#710001",
            "wine-dark": "#590001",
            "near-black": "#410001",
        },
        window_gradient=("#851a1a", "#410001"),
        accent="#851a1a",               # claret: white text clears AA
        accent2="#7e0d0e",              # crimson-dark: focus/borders
        panel_bg="#590001",             # wine-dark
        panel_text="#ffd9d9",           # derived pale rose
        text_on_accent="#ffffff",
        status_bg="rgba(20, 0, 0, 0.45)",
        status_text="#ffd9d9",
        header_gradient=("#710001", "#410001"),
        header_text="#ffd9d9",
    )


def sakura_light() -> Theme:
    """Sakura Light: pale sakura pinks with deep-plum text.

    Palette as given (sakuras). A light theme: petal-pink sweep,
    blossom-deep accent. The pinks are all light or medium, so the
    text runs dark plum (white on the darkest pink fails AA at ~3.1);
    the accent clears AA at ~7.7 with the deep plum.
    """
    return Theme(
        name="Sakura Light",
        colors={
            "petal-light": "#efd0e5",
            "petal": "#e6c3db",
            "blossom": "#daabcb",
            "blossom-deep": "#d29ec2",
            "twig": "#be7fab",
        },
        window_gradient=("#efd0e5", "#daabcb"),
        accent="#d29ec2",               # blossom-deep: dark plum text
        accent2="#be7fab",              # twig: focus/borders
        panel_bg="#efd0e5",             # petal-light
        panel_text="#3a1f2e",           # derived plum
        text_on_accent="#2b1420",       # derived deep plum
        status_bg="rgba(190, 127, 171, 0.35)",
        status_text="#3a1f2e",
        header_gradient=("#e6c3db", "#d29ec2"),
        header_text="#2b1420",
    )


def black_velvet() -> Theme:
    """Black Velvet: dark fantasy romance, near-black with plum accents.

    Palette as given (Dark Fantasy Romance). Near-black base and
    maroon sweep, plum accent with white text (10.4:1); the bone-cream
    panels give the text a warm, high-contrast surface (13.2:1).
    """
    return Theme(
        name="Black Velvet",
        colors={
            "bone": "#e7e1d4",
            "ash": "#959090",
            "plum": "#64285d",
            "wine": "#610536",
            "velvet": "#1e1c1c",
        },
        window_gradient=("#1e1c1c", "#610536"),
        accent="#64285d",               # plum: white text clears AA
        accent2="#610536",              # wine: focus/borders
        panel_bg="#1e1c1c",             # velvet
        panel_text="#e7e1d4",           # bone
        text_on_accent="#ffffff",
        status_bg="rgba(0, 0, 0, 0.45)",
        status_text="#e7e1d4",
        header_gradient=("#64285d", "#1e1c1c"),
        header_text="#e7e1d4",
    )


def atom_blue() -> Theme:
    """Atom Blue: Atom One Dark, the editor's blue accent.

    Palette as given (Atom One Dark - Part 1). Dark slate base and
    gutter sweep; the bright blue accent needs dark navy text (white
    fails AA at ~3.3); the syntax-grey foreground carries the panels.
    """
    return Theme(
        name="Atom Blue",
        colors={
            "syntax-fg": "#abb2bf",
            "syntax-bg": "#282c34",
            "gutter": "#636d83",
            "guide": "#f2f4f5",
            "accent-blue": "#528bff",
        },
        window_gradient=("#282c34", "#636d83"),
        accent="#528bff",               # accent blue: dark navy text
        accent2="#636d83",              # gutter: focus/borders
        panel_bg="#282c34",             # syntax-bg
        panel_text="#abb2bf",           # syntax-fg
        text_on_accent="#0b1a38",       # derived dark navy
        status_bg="rgba(11, 26, 56, 0.45)",
        status_text="#abb2bf",
        header_gradient=("#636d83", "#282c34"),
        header_text="#f2f4f5",          # guide: clears the gutter stop
    )


def atom_lilac() -> Theme:
    """Atom Lilac: Atom One Dark with the lilac syntax accent.

    Palette as given (Atom One Dark 2). Same slate base as Atom Blue,
    but the accent is the editor's lilac, which needs deep violet-black
    text (white fails AA at ~3.0).
    """
    return Theme(
        name="Atom Lilac",
        colors={
            "lilac": "#c678dd",
            "syntax-fg": "#abb2bf",
            "comment": "#5c6370",
            "gutter-dark": "#32363e",
            "syntax-bg": "#282c34",
        },
        window_gradient=("#282c34", "#32363e"),
        accent="#c678dd",               # lilac: deep violet text
        accent2="#5c6370",              # comment grey: focus/borders
        panel_bg="#282c34",             # syntax-bg
        panel_text="#abb2bf",           # syntax-fg
        text_on_accent="#1a0f24",       # derived deep violet
        status_bg="rgba(26, 15, 36, 0.45)",
        status_text="#abb2bf",
        header_gradient=("#32363e", "#282c34"),
        header_text="#abb2bf",
    )


def coffee_shop() -> Theme:
    """Coffee Shop: dark Americano roast, warm espresso sweep.

    Palette as given (Dark Americano). Every shade is a coffee brown,
    so light text clears AA throughout; the sweep runs the espresso
    down to the mocha, and the cream panels keep it readable.
    """
    return Theme(
        name="Coffee Shop",
        colors={
            "espresso": "#382c28",
            "mocha": "#605653",
            "latte": "#88807e",
            "foam": "#afaba9",
            "cream": "#d7d5d4",
        },
        window_gradient=("#382c28", "#605653"),
        accent="#605653",               # mocha: white text clears AA
        accent2="#88807e",              # latte: focus/borders
        panel_bg="#382c28",             # espresso
        panel_text="#d7d5d4",           # cream
        text_on_accent="#ffffff",
        status_bg="rgba(24, 18, 15, 0.45)",
        status_text="#d7d5d4",
        header_gradient=("#605653", "#382c28"),
        header_text="#d7d5d4",
    )


def water_tribe() -> Theme:
    """Water Tribe: ocean-blue light, pale water sweep.

    Palette as given (oceancity). A light theme: near-white water
    panels under a pale sweep, deep ocean-blue accent and text. The
    lightest blues can't carry white text, so body text runs deep
    blue (clears AA on every stop).
    """
    return Theme(
        name="Water Tribe",
        colors={
            "deep-ocean": "#2a4d88",
            "mist": "#d9d9d8",
            "fog": "#b1bbc8",
            "wave": "#7c94b8",
            "foam-white": "#f2f2fa",
        },
        window_gradient=("#f2f2fa", "#b1bbc8"),
        accent="#2a4d88",               # deep ocean: white text clears AA
        accent2="#7c94b8",              # wave: focus/borders
        panel_bg="#f2f2fa",             # foam white
        panel_text="#2a4d88",           # deep ocean
        text_on_accent="#ffffff",
        status_bg="rgba(42, 77, 136, 0.18)",
        status_text="#2a4d88",
        header_gradient=("#d9d9d8", "#bac3ce"),   # 2nd stop lightened: ocean text must read on the gray
        header_text="#2a4d88",
    )


def last_agni_kai() -> Theme:
    """Last Agni Kai: flame to blue flame, ember slate sweep.

    Palette as given (Flame to Blue Flame). The orange is the fighting
    fire, the deep blue the comet-lit sky; the sweep runs ember-slate
    down to the blue, and the cool slate panels keep the flame accent
    loud.
    """
    return Theme(
        name="Last Agni Kai",
        colors={
            "flame": "#e25822",
            "ember": "#b6624d",
            "ash": "#8a6665",
            "slate": "#596478",
            "blue-flame": "#005e88",
        },
        window_gradient=("#8a6665", "#005e88"),
        accent="#e25822",               # flame: dark text clears AA
        accent2="#005e88",              # blue flame: focus/borders
        panel_bg="#596478",             # slate
        panel_text="#f0e8e4",           # derived warm white
        text_on_accent="#2b0e04",       # derived near-black ember
        status_bg="rgba(30, 20, 18, 0.45)",
        status_text="#ffffff",
        header_gradient=("#596478", "#005e88"),
        header_text="#ffffff",
    )


def fire_nation() -> Theme:
    """Fire Nation: blood-red shades over near-black.

    Palette as given (Fire Nation 1). The gold is the imperial trim,
    the reds the banners; the sweep runs crimson down to the charcoal
    so the flame accent stays hot.
    """
    return Theme(
        name="Fire Nation",
        colors={
            "imperial-gold": "#a37404",
            "amber": "#c78826",
            "crimson": "#b20c0c",
            "dark-red": "#781111",
            "charcoal": "#2b2424",
        },
        window_gradient=("#781111", "#2b2424"),
        accent="#b20c0c",               # crimson: white text clears AA
        accent2="#c78826",              # amber: focus/borders
        panel_bg="#2b2424",             # charcoal
        panel_text="#f5e6d8",           # derived warm parchment
        text_on_accent="#ffffff",
        status_bg="rgba(20, 8, 8, 0.5)",
        status_text="#f5e6d8",
        header_gradient=("#781111", "#2b2424"),
        header_text="#f5e6d8",
    )


def earth_kingdom() -> Theme:
    """Earth Kingdom: deep earthen greens, forest sweep.

    Palette as given (Earth Kingdom 1). The pale sage and olive are
    the sunlit leaves, the deep greens the soil; light text clears AA
    on every dark stop.
    """
    return Theme(
        name="Earth Kingdom",
        colors={
            "sage": "#80987c",
            "olive": "#b4ad64",
            "fern": "#7b944f",
            "forest": "#145425",
            "soil": "#0c3808",
        },
        window_gradient=("#145425", "#0c3808"),
        accent="#7b944f",               # fern: dark text clears AA
        accent2="#b4ad64",              # olive: focus/borders
        panel_bg="#0c3808",             # soil
        panel_text="#e2ecd9",           # derived pale sage
        text_on_accent="#0d1f08",       # derived near-black forest
        status_bg="rgba(6, 20, 4, 0.5)",
        status_text="#e2ecd9",
        header_gradient=("#145425", "#0c3808"),
        header_text="#e2ecd9",
    )


def air_nomad() -> Theme:
    """Air Nomad: spring-sky blue, light airy sweep.

    Palette as given (Spring Sky Blue). A light theme: pale sky
    panels under a soft-blue sweep, deep-sky accent with dark text.
    The blues are all light, so body text runs a derived deep navy.
    """
    return Theme(
        name="Air Nomad",
        colors={
            "sky-pale": "#b3edfe",
            "sky-soft": "#9cd0f9",
            "sky": "#aad8ff",
            "sky-deep": "#93c6ef",
            "sky-ink": "#65a7de",
        },
        window_gradient=("#b3edfe", "#93c6ef"),
        accent="#65a7de",               # sky ink: dark navy text clears AA
        accent2="#9cd0f9",              # sky soft: focus/borders
        panel_bg="#b3edfe",             # sky pale
        panel_text="#1a3a5c",           # derived deep navy
        text_on_accent="#0d2b45",       # derived darkest navy
        status_bg="rgba(10, 30, 50, 0.15)",
        status_text="#1a3a5c",
        header_gradient=("#aad8ff", "#93c6ef"),
        header_text="#1a3a5c",
    )


def i_know_kung_fu() -> Theme:
    """I know Kung Fu: green monochrome terminal, Matrix phosphor.

    One hue, no white: phosphor green on black, black on phosphor for
    selection (the inverted-terminal look). Panel, body, accent,
    header, and status all ride the same #00ff41; only the border
    dims to #00b33c.
    """
    return Theme(
        name="I know Kung Fu",
        colors={"phosphor": "#00ff41"},
        window_gradient=("#07140c", "#010402"),
        accent="#00ff41",
        accent2="#00b33c",
        panel_bg="#000000",
        panel_text="#00ff41",
        text_on_accent="#000000",
        status_bg="rgba(0, 0, 0, 0.55)",
        status_text="#00ff41",
        header_gradient=("#003d1f", "#001a0d"),
        header_text="#00ff41",
    )


def my_name_is_neo() -> Theme:
    """My name is Neo: purple monochrome terminal.

    Bright violet phosphor on black (black on violet for selection).
    Body text runs a lighter lavender so the accent stays bright; the
    border dims to violet-500.
    """
    return Theme(
        name="My name is Neo",
        colors={"phosphor-purple": "#c084fc"},
        window_gradient=("#0d0714", "#030104"),
        accent="#c084fc",
        accent2="#8b5cf6",
        panel_bg="#000000",
        panel_text="#d8b4fe",
        text_on_accent="#000000",
        status_bg="rgba(0, 0, 0, 0.55)",
        status_text="#c084fc",
        header_gradient=("#3b0764", "#1a0233"),
        header_text="#c084fc",
    )


def give_me_the_night() -> Theme:
    """Give me the night: charcoal -> plum -> magenta night palette.

    Palette as given (#1a1a1d #3b1c32 #6a1e55 #a64d79). Near-black
    panels carry a derived soft-rose body text (the rose #a64d79 is
    only 3.4:1 on #1a1a1d, too dim for text); the deep magenta is the
    accent with white text; the rose, lightened to #b77093, is the
    border/focus/placeholder color so the placeholder reads.
    """
    return Theme(
        name="Give me the night",
        colors={
            "charcoal": "#1a1a1d",
            "plum": "#3b1c32",
            "magenta": "#6a1e55",
            "rose": "#a64d79",
        },
        window_gradient=("#1a1a1d", "#3b1c32"),
        accent="#6a1e55",
        accent2="#b77093",              # rose lightened: placeholder must read
        panel_bg="#1a1a1d",
        panel_text="#d9a8c3",           # derived soft rose
        text_on_accent="#ffffff",
        status_bg="rgba(26, 26, 29, 0.55)",
        status_text="#d9a8c3",
        header_gradient=("#3b1c32", "#6a1e55"),
        header_text="#ffffff",
    )


THEMES: list[Theme] = [
    magenta_daydream(),
    grey_moonlight(),
    zen_garden(),
    bubblegum_haze(),
    hide_and_seek(),
    lipstick_hyperfemme(),
    butch_cassidy(),
    analog_sunrise(),
    insane_default(),
    frutiger_aero(),
    aqua(),
    dark_aqua(),
    just_blues(),
    lilac_love(),
    minty_forest(),
    stoner_shore(),
    carmillas_snack(),
    sakura_light(),
    black_velvet(),
    atom_blue(),
    atom_lilac(),
    coffee_shop(),
    water_tribe(),
    last_agni_kai(),
    fire_nation(),
    earth_kingdom(),
    air_nomad(),
    i_know_kung_fu(),
    my_name_is_neo(),
    give_me_the_night(),
]


def apply_theme(app, theme: Theme) -> None:
    """Re-skin @app with @theme immediately (no restart)."""
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.qss())


def theme_by_name(name: str) -> Theme:
    for theme in THEMES:
        if theme.name == name:
            return theme
    raise KeyError(name)

