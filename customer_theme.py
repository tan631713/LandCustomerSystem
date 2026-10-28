"""Colour tokens, fonts and the application stylesheet (淺色謄本 / 深色).

Every desktop colour comes from the two token tables below; other modules must
not hard-code hex values (user-defined tag colours and the stand-alone map HTML
are the only exceptions).  The theme is chosen once at start-up: the saved
preference (``ui_theme``) can change at any time, but the tokens stay frozen
until the next launch (``activate_theme``).
"""

from __future__ import annotations

import hashlib
import logging
import sys
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)

LOGGER = logging.getLogger(__name__)

THEME_SETTING_KEY = "ui_theme"
DEFAULT_THEME_KEY = "light"
THEME_OPTIONS = (("light", "淺色"), ("dark", "深色"))

LIGHT = {
    "ground": "#E9EDE8",      # 視窗底色（面板之間的縫）
    "paper": "#FAFBF8",       # 面板、工具列、對話框
    "field": "#FFFFFF",       # 輸入欄位、表單格子
    "ink": "#1C2321",         # 主要文字
    "ink2": "#56625C",        # 次要文字、欄位標籤（在 paper 上對比約 6:1）
    "rule": "#D3DBD5",        # 細格線
    "rule_strong": "#A7B5AB", # 表單外框、表頭底線、按鈕框
    "green": "#2F6B4F",       # 主色：主要按鈕、焦點框、選取
    "green_ink": "#FFFFFF",   # 綠底上的字
    "green_tint": "#DFECE3",  # 選單 hover、土地列被選到時
    "sel": "#D2E6D9",         # 被選取的地主列
    "checked": "#E6EEF6",     # 已勾選列、勾選操作列
    "checked_ink": "#2C4F73",
    "watch": "#F6E1DD",       # 注意名單列
    "overdue": "#F6E9CC",     # 追蹤逾期列
    "note": "#EFEDE0",        # 有備註列
    "mark": "#F5DC7A",        # 搜尋符合
    "seal": "#A3342A",        # 朱紅：刪除、危險、注意名單文字
    "seal_ink": "#FFFFFF",    # 朱紅底上的字
    "amber_ink": "#7A5310",   # 逾期、警示文字
    "auto": "#F1F3EF",        # 自動計算／唯讀格子底色
    "seg1": "#8FA197", "seg2": "#B4C1B9", "seg3": "#D3DCD6",  # 持分條非選取段
    # 對話框裡的狀態色（行程、追蹤、關係圖）
    "info_bg": "#E3ECF6", "info_ink": "#2C4F73",
    "success_bg": "#DDEEE2", "success_ink": "#24563C",
    "muted_bg": "#ECEFEC", "muted_ink": "#56625C",
}
DARK = {
    "ground": "#141917", "paper": "#1C2220", "field": "#232A27",
    "ink": "#E5ECE7", "ink2": "#A3B0A9", "rule": "#323C37", "rule_strong": "#4D5A53",
    "green": "#6DBE93", "green_ink": "#0F1A14", "green_tint": "#20352A", "sel": "#24402F",
    "checked": "#1F3044", "checked_ink": "#A9C9EA", "watch": "#432520", "overdue": "#3E3218",
    "note": "#2F2E24", "mark": "#7A6420", "seal": "#EE8F82", "seal_ink": "#1C2221", "amber_ink": "#E8C47A",
    "auto": "#1F2623", "seg1": "#5E6E66", "seg2": "#46534C", "seg3": "#36413B",
    "info_bg": "#1F3044", "info_ink": "#A9C9EA", "success_bg": "#1E3527", "success_ink": "#9BD3B0",
    "muted_bg": "#2A322E", "muted_ink": "#A3B0A9",
}
THEMES = {"light": LIGHT, "dark": DARK}

# -- fonts --------------------------------------------------------------------

HEADING_FONT_FAMILY = "Noto Serif TC"
FALLBACK_HEADING_FAMILY = "Microsoft JhengHei UI"
UI_FONT_FAMILIES = ("Microsoft JhengHei UI", "Microsoft JhengHei")
BUNDLED_FONT_PARTS = ("assets", "fonts", "NotoSerifTC-Bold.otf")

_heading_family = FALLBACK_HEADING_FAMILY


def _resource_dir():
    # Same rule as customer_ui_qt.get_resource_dir(); duplicated here because
    # customer_ui_qt imports this module.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def bundled_font_path():
    return _resource_dir().joinpath(*BUNDLED_FONT_PARTS)


def load_bundled_fonts():
    """Register the shipped heading font; never raises, returns whether it worked."""

    global _heading_family
    _heading_family = FALLBACK_HEADING_FAMILY
    try:
        path = Path(bundled_font_path())
        if QGuiApplication.instance() is None:
            LOGGER.warning("Heading font not loaded: no QGuiApplication yet")
            return False
        if not path.is_file():
            LOGGER.warning("Heading font file not found: %s", path)
            return False
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            LOGGER.warning("Heading font could not be loaded: %s", path)
            return False
        families = QFontDatabase.applicationFontFamilies(font_id)
        if HEADING_FONT_FAMILY not in families:
            LOGGER.warning("Heading font family missing from %s: %s", path, families)
            return False
        _heading_family = HEADING_FONT_FAMILY
        return True
    except Exception:  # noqa: BLE001 - a missing font must never stop start-up
        LOGGER.exception("Heading font failed to load")
        return False


def heading_font(point_size):
    font = QFont(_heading_family, int(point_size))
    font.setBold(True)
    return font


# -- theme selection ------------------------------------------------------------

_storage = {"get": None, "set": None}
_memory_key = DEFAULT_THEME_KEY
_active_key = DEFAULT_THEME_KEY
_active_tokens = LIGHT


def normalize_theme_key(value):
    text = str(value or "").strip().casefold()
    return text if text in THEMES else DEFAULT_THEME_KEY


def configure_storage(get_setting, set_setting):
    """Wire the saved preference to the application's settings table."""

    _storage["get"] = get_setting
    _storage["set"] = set_setting


def current_theme_key():
    """The saved preference (what the next launch will use)."""

    getter = _storage["get"]
    if getter is None:
        return _memory_key
    try:
        return normalize_theme_key(getter(THEME_SETTING_KEY, DEFAULT_THEME_KEY))
    except Exception:  # noqa: BLE001 - settings storage trouble means "default"
        LOGGER.exception("Could not read the saved theme")
        return DEFAULT_THEME_KEY


def set_theme_key(key):
    """Save the preference; the running window keeps its colours until restart."""

    global _memory_key
    key = normalize_theme_key(key)
    _memory_key = key
    setter = _storage["set"]
    if setter is not None:
        setter(THEME_SETTING_KEY, key)
    return key


def activate_theme(key=None):
    """Freeze the tokens used by token()/qcolor() for this run."""

    global _active_key, _active_tokens
    _active_key = normalize_theme_key(current_theme_key() if key is None else key)
    _active_tokens = THEMES[_active_key]
    return _active_key


def active_theme_key():
    return _active_key


def theme_tokens():
    return dict(_active_tokens)


def token(name):
    return _active_tokens[name]


def qcolor(name):
    return QColor(_active_tokens[name])


def rgba(name, alpha_percent, tokens=None):
    color = QColor((tokens or _active_tokens)[name])
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {round(255 * alpha_percent / 100)})"


# -- small style helpers ----------------------------------------------------------


def repolish(widget):
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_button_variant(button, variant):
    """variant: "primary", "ghost", "danger-text" or "" (default look)."""

    button.setProperty("variant", variant or "")
    repolish(button)


def set_widget_property(widget, name, value):
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    repolish(widget)


def muted_text_style(size_px=12):
    return f"color: {token('ink2')}; font-size: {size_px}px;"


# -- icons (drawn, so no image resources are shipped) ----------------------------


def _icon_pixmap(draw, color, size):
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        draw(painter, float(size))
    finally:
        painter.end()
    return pixmap


def _draw_search(painter, size):
    painter.drawEllipse(QRectF(size * 0.14, size * 0.14, size * 0.50, size * 0.50))
    painter.drawLine(QPointF(size * 0.58, size * 0.58), QPointF(size * 0.86, size * 0.86))


def _draw_plus(painter, size):
    painter.drawLine(QPointF(size * 0.5, size * 0.18), QPointF(size * 0.5, size * 0.82))
    painter.drawLine(QPointF(size * 0.18, size * 0.5), QPointF(size * 0.82, size * 0.5))


def _draw_trash(painter, size):
    painter.drawLine(QPointF(size * 0.16, size * 0.27), QPointF(size * 0.84, size * 0.27))
    painter.drawLine(QPointF(size * 0.38, size * 0.27), QPointF(size * 0.38, size * 0.15))
    painter.drawLine(QPointF(size * 0.38, size * 0.15), QPointF(size * 0.62, size * 0.15))
    painter.drawLine(QPointF(size * 0.62, size * 0.15), QPointF(size * 0.62, size * 0.27))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(size * 0.24, size * 0.27),
                QPointF(size * 0.30, size * 0.86),
                QPointF(size * 0.70, size * 0.86),
                QPointF(size * 0.76, size * 0.27),
            ]
        )
    )
    painter.drawLine(QPointF(size * 0.43, size * 0.42), QPointF(size * 0.44, size * 0.70))
    painter.drawLine(QPointF(size * 0.57, size * 0.42), QPointF(size * 0.56, size * 0.70))


def _draw_chevron(painter, size):
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(size * 0.25, size * 0.38),
                QPointF(size * 0.50, size * 0.64),
                QPointF(size * 0.75, size * 0.38),
            ]
        )
    )


def _draw_tick(painter, size):
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(size * 0.22, size * 0.52),
                QPointF(size * 0.42, size * 0.72),
                QPointF(size * 0.78, size * 0.28),
            ]
        )
    )


def _draw_dash(painter, size):
    painter.drawLine(QPointF(size * 0.26, size * 0.5), QPointF(size * 0.74, size * 0.5))


_ICON_DRAWERS = {
    "search": _draw_search,
    "plus": _draw_plus,
    "trash": _draw_trash,
    "chevron": _draw_chevron,
    "tick": _draw_tick,
    "dash": _draw_dash,
}


def style_image_urls(tokens):
    """PNG files for the QSS ::down-arrow and ::indicator rules (QSS cannot draw them).

    Written once per colour set under the temp folder.  Returns {} when they
    cannot be written: the stylesheet then simply omits those image rules.
    """

    wanted = {
        "arrow": ("chevron", tokens["ink2"], 10),
        "tick": ("tick", tokens["green_ink"], 12),
        "dash": ("dash", tokens["green"], 12),
    }
    if QGuiApplication.instance() is None:
        return {}
    try:
        folder = Path(tempfile.gettempdir()) / "LandCustomerSystem-theme"
        folder.mkdir(parents=True, exist_ok=True)
        urls = {}
        for name, (kind, color, size) in wanted.items():
            digest = hashlib.sha1(f"{kind}{color}{size}".encode()).hexdigest()[:8]
            path = folder / f"{name}-{digest}.png"
            if not path.is_file():
                if not _icon_pixmap(_ICON_DRAWERS[kind], color, size).save(str(path), "PNG"):
                    return {}
            urls[name] = path.as_posix()
        return urls
    except OSError:
        LOGGER.exception("Could not write the stylesheet images")
        return {}


def line_icon(kind, color_name="ink2", size=16):
    """A small stroke icon in one of the theme colours (or any #RRGGBB)."""

    color = _active_tokens.get(color_name, color_name)
    return QIcon(_icon_pixmap(_ICON_DRAWERS[kind], color, size))


# -- application stylesheet -----------------------------------------------------

_STYLESHEET = Template(
    """
QWidget {
    background-color: $paper;
    color: $ink;
    selection-background-color: $sel;
    selection-color: $ink;
}
QMainWindow, QDialog {
    background-color: $paper;
}
QWidget#appGround {
    background-color: $ground;
}
QFrame#toolbarFrame {
    background-color: $paper;
    border: none;
    border-bottom: 1px solid $rule;
}
QFrame#listFrame, QFrame#formFrame {
    background-color: $paper;
    border: 1px solid $rule;
    border-radius: 8px;
}
QFrame#searchGroup {
    background-color: $field;
    border: 1px solid $rule_strong;
    border-radius: 6px;
}
QFrame#searchGroup[focused="true"] {
    border: 2px solid $green;
}
QFrame#searchGroup QComboBox {
    background-color: $auto;
    border: none;
    border-radius: 0px;
    padding: 0px 10px;
    min-height: 34px;
}
QFrame#searchGroup QLineEdit, QFrame#searchGroup QLineEdit:focus {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px 10px;
    min-height: 34px;
}
QFrame#searchGroup QPushButton {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px 14px;
    min-height: 34px;
}
QFrame#searchGroup QPushButton:hover {
    background-color: $ink_hover;
}
QLabel {
    background-color: transparent;
    color: $ink;
}
QToolTip {
    background-color: $paper;
    color: $ink;
    border: 1px solid $rule_strong;
    padding: 4px 6px;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QAbstractSpinBox {
    background-color: $field;
    color: $ink;
    border: 1px solid $rule_strong;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: $sel;
    selection-color: $ink;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {
    border: 2px solid $green;
    padding: 5px 9px;
}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled,
QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {
    background-color: $auto;
    color: $ink2;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}
$arrow_rule
QTreeView::indicator, QTableView::indicator, QListView::indicator,
QTreeWidget::indicator, QTableWidget::indicator {
    width: 14px;
    height: 14px;
    border: 2px solid $ink2;
    border-radius: 4px;
    background-color: $field;
}
QTreeView::indicator:hover, QTableView::indicator:hover, QListView::indicator:hover,
QTreeWidget::indicator:hover, QTableWidget::indicator:hover {
    border-color: $green;
}
QTreeView::indicator:checked, QTableView::indicator:checked, QListView::indicator:checked,
QTreeWidget::indicator:checked, QTableWidget::indicator:checked {
    background-color: $green;
    border-color: $green;
    $tick_image
}
QTreeView::indicator:indeterminate, QTableView::indicator:indeterminate,
QListView::indicator:indeterminate, QTreeWidget::indicator:indeterminate,
QTableWidget::indicator:indeterminate {
    background-color: $green_tint;
    border-color: $green;
    $dash_image
}
QComboBox QAbstractItemView {
    background-color: $field;
    color: $ink;
    border: 1px solid $rule_strong;
    selection-background-color: $green_tint;
    selection-color: $ink;
    outline: none;
}
QPushButton {
    background-color: $paper;
    color: $ink;
    border: 1px solid $rule_strong;
    border-radius: 6px;
    min-height: 30px;
    padding: 0 12px;
}
QPushButton:hover {
    border-color: $ink2;
}
QPushButton:pressed {
    background-color: $auto;
}
QPushButton:disabled {
    background-color: $auto;
    color: $ink2;
    border-color: $rule;
}
QPushButton[variant="primary"] {
    background-color: $green;
    color: $green_ink;
    border: 1px solid $green;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    border-color: $green_ink;
}
QPushButton[variant="primary"]:disabled {
    background-color: $rule_strong;
    color: $paper;
    border-color: $rule_strong;
}
QPushButton[variant="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
}
QPushButton[variant="ghost"]:hover {
    background-color: $ink_hover;
    border-color: transparent;
}
QPushButton[variant="danger-text"] {
    background-color: transparent;
    border: 1px solid transparent;
    color: $seal;
}
QPushButton[variant="danger-text"]:hover {
    background-color: $seal_hover;
    border-color: transparent;
}
QPushButton[variant="danger-text"]:disabled {
    color: $ink2;
}
QMenu {
    background-color: $paper;
    color: $ink;
    border: 1px solid $rule;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 6px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: $green_tint;
    color: $ink;
}
QMenu::item:disabled {
    color: $ink2;
}
QMenu::separator {
    height: 1px;
    background: $rule;
    margin: 4px 8px;
}
QHeaderView::section {
    background-color: $paper;
    color: $ink2;
    border: none;
    border-bottom: 1px solid $rule_strong;
    padding: 6px 8px;
    font-weight: 500;
}
QTreeView, QTableView, QTableWidget, QListView, QListWidget {
    background-color: $paper;
    alternate-background-color: $paper;
    color: $ink;
    border: none;
    gridline-color: $rule;
    outline: none;
}
QTextBrowser {
    background-color: $field;
    color: $ink;
    border: 1px solid $rule;
}
QTreeView::item, QTableView::item, QTableWidget::item, QListView::item {
    border-bottom: 1px solid $rule;
    padding: 2px 4px;
}
QTreeView::item:selected, QTableView::item:selected, QTableWidget::item:selected, QListView::item:selected {
    background-color: $sel;
    color: $ink;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background-color: transparent;
    color: $ink2;
    padding: 10px 4px;
    margin-right: 14px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: $ink;
    font-weight: 600;
    border-bottom: 2px solid $green;
}
QTabBar::tab:hover:!selected {
    color: $ink;
}
QGroupBox {
    border: 1px solid $rule;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: $paper;
    border: none;
    margin: 0px;
}
QScrollBar:vertical {
    width: 12px;
}
QScrollBar:horizontal {
    height: 12px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $rule_strong;
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:hover {
    background: $ink2;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
}
QSplitter::handle {
    background-color: $ground;
    width: 1px;
}
QStatusBar {
    background-color: $paper;
    color: $ink2;
    border-top: 1px solid $rule;
}
QStatusBar QLabel, QStatusBar QPushButton {
    color: $ink2;
}
"""
)


def build_app_stylesheet(tokens=None):
    values = dict(tokens or _active_tokens)
    values["ink_hover"] = rgba("ink", 4, values)
    values["seal_hover"] = rgba("seal", 8, values)
    urls = style_image_urls(values)
    values["arrow_rule"] = (
        f'QComboBox::down-arrow {{ image: url("{urls["arrow"]}"); width: 10px; height: 10px; }}'
        if "arrow" in urls
        else ""
    )
    values["tick_image"] = f'image: url("{urls["tick"]}");' if "tick" in urls else ""
    values["dash_image"] = f'image: url("{urls["dash"]}");' if "dash" in urls else ""
    return _STYLESHEET.substitute(values)
