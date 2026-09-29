"""Colours, fonts and scaling taken straight from 伺服器控制台_畫面規格.md.

The console uses plain tkinter (the spec allows it). customtkinter was tried
first, but every one of its widgets is three native windows plus antialiased
shape text, and on a 250 % laptop that made the window take 8-12 s to appear.
Everything below is therefore drawn by ui_widgets.py with one native window
per widget, and all sizes are written in "design pixels" that `px()` scales.
"""

from __future__ import annotations

import tkinter.font as tkfont

FONT_UI = "Microsoft JhengHei UI"
FONT_MONO = "Consolas"

WINDOW_BG = "#EEF0F2"
CARD_BG = "#FFFFFF"
BORDER = "#D5D9DE"
BUTTON_BORDER = "#C3C9D0"
TEXT = "#1C2024"
TEXT_SECONDARY = "#50575F"
TEXT_MUTED = "#6A7078"
PRIMARY = "#1F5FAD"
LOG_BG = "#FAFBFC"

GREEN = "#1E7A46"
GREEN_BG = "#E6F4EC"
BLUE = "#1F5FAD"
BLUE_BG = "#E7EFFA"
RED = "#B42318"
RED_BG = "#FCEBEA"
BROWN = "#8A5A00"
BROWN_BG = "#FDF3DC"
GRAY = "#50575F"
GRAY_BG = "#ECEEF0"

# status -> (text colour, background colour)
STATUS_PALETTE = {
    "running": (GREEN, GREEN_BG),
    "starting": (BLUE, BLUE_BG),
    "error": (RED, RED_BG),
    "no_accounts": (BROWN, BROWN_BG),
    "not_started": (GRAY, GRAY_BG),
    "stopping": (GRAY, GRAY_BG),
}

_scale = 1.0
_font_cache: dict[tuple, tkfont.Font] = {}


def init_scale(root) -> float:
    """Read the display scale (1.0 = 96 dpi) once the process is DPI aware."""

    global _scale
    try:
        _scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:  # noqa: BLE001 - scaling is cosmetic only
        _scale = 1.0
    _font_cache.clear()
    return _scale


def scale() -> float:
    return _scale


def px(value: float) -> int:
    """Design pixels -> screen pixels (never below 1 for a positive value)."""

    if not value:
        return 0
    return max(1, int(round(value * _scale)))


def scaled_font(size: float, weight: str = "normal", family: str = FONT_UI) -> tkfont.Font:
    key = (size, weight, family, _scale)
    if key not in _font_cache:
        _font_cache[key] = tkfont.Font(family=family, size=-px(size), weight=weight)
    return _font_cache[key]


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def blend(foreground: str, background: str, alpha: float) -> str:
    """`foreground` at `alpha` opacity over `background` (Tk has no widget
    opacity, so the spec's "45% 透明度" is done by mixing the colours)."""

    fr, fg, fb = _rgb(foreground)
    br, bg, bb = _rgb(background)
    mixed = (
        round(fr * alpha + br * (1 - alpha)),
        round(fg * alpha + bg * (1 - alpha)),
        round(fb * alpha + bb * (1 - alpha)),
    )
    return "#{:02X}{:02X}{:02X}".format(*mixed)
