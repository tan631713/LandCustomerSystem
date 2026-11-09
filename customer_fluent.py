"""Fluent (Windows 11 style) widgets from PySide6-Fluent-Widgets: theme, fonts, .ui support.

The .ui files promote buttons / boxes to Fluent classes (Designer "Promote
to...", header ``qfluentwidgets``); customer_ui_loader registers every Fluent
widget class with QUiLoader through ``fluent_widget_classes()``.

``ui/fluent_theme.json`` holds what the owner may want to change without
touching code: the accent colour for the light and the dark theme and the font
families.  A missing or broken file falls back to the defaults below -- the
program must always open.

Three things are adjusted inside the library (PySide6-Fluent-Widgets 1.11.3, the
version pinned in requirements.txt; ``install_patches`` checks the hooks still
exist and simply skips them otherwise):

* dark theme: Fluent derives its dark accent by forcing full brightness, which
  turns the program's green into mint.  Here the dark accent is the
  ``darkPrimaryColor`` from the JSON file as given (default: the dark theme's
  own green, customer_theme.DARK["green"]), with Fluent's usual lighter / darker steps around it.
* table / list cells: drawn at body-text size instead of one size smaller.
* font size: Fluent sizes its text in fixed pixels (14 px).  Here those sizes
  follow the program's 字體大小 setting (中 = 11 pt replaces 14 px, other sizes
  in proportion), live, like the rest of the window.
"""

from __future__ import annotations

import json
import logging
import re

from customer_theme import THEMES
from customer_ui_loader import render_qss, ui_path

LOGGER = logging.getLogger(__name__)

FLUENT_THEME_FILE = "fluent_theme.json"
FLUENT_WIDGETS_STYLESHEET_FILE = "fluent_widgets.qss"
# The accent colours default to the theme tables' green (customer_theme).
DEFAULT_FLUENT_THEME = {
    "primaryColor": THEMES["light"]["green"],
    "darkPrimaryColor": THEMES["dark"]["green"],
    "fontFamilies": ["Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI"],
}
# Fluent's own body text size; the program's base point size replaces it.
FLUENT_BASE_PIXEL_SIZE = 14
DEFAULT_POINT_SIZE = 11

_state = {
    "dark_primary": DEFAULT_FLUENT_THEME["darkPrimaryColor"],
    "point_size": DEFAULT_POINT_SIZE,
    "patched": False,
}


def fluent_available():
    try:
        import qfluentwidgets  # noqa: F401
    except Exception:  # pragma: no cover - the package is in requirements.txt
        return False
    return True


def _valid_color(value):
    from PySide6.QtGui import QColor

    return isinstance(value, str) and QColor(value).isValid()


def load_fluent_theme(path=None):
    """``ui/fluent_theme.json`` merged over the defaults; bad values are ignored."""

    settings = {key: (list(value) if isinstance(value, list) else value)
                for key, value in DEFAULT_FLUENT_THEME.items()}
    path = path or ui_path(FLUENT_THEME_FILE)
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as exc:
        LOGGER.warning("%s 無法讀取，改用預設 Fluent 外觀：%s", path, exc)
        return settings
    if not isinstance(data, dict):
        LOGGER.warning("%s 格式不對（應為 { ... }），改用預設 Fluent 外觀", path)
        return settings
    for key in ("primaryColor", "darkPrimaryColor"):
        if key in data:
            if _valid_color(data[key]):
                settings[key] = data[key]
            else:
                LOGGER.warning("%s 的 %s 不是顏色：%r，改用預設", path, key, data[key])
    families = data.get("fontFamilies")
    if isinstance(families, str):
        families = [families]
    if isinstance(families, list):
        families = [name for name in families if isinstance(name, str) and name.strip()]
        if families:
            settings["fontFamilies"] = families
    return settings


# -- library hooks ------------------------------------------------------------

_PIXEL_FONT = re.compile(r"(font(?:-size)?\s*:\s*)(\d+(?:\.\d+)?)px")


def _scaled_point_size(pixel_size):
    return pixel_size * _state["point_size"] / FLUENT_BASE_PIXEL_SIZE


def _scale_qss_fonts(qss):
    return _PIXEL_FONT.sub(
        lambda match: f"{match.group(1)}{_scaled_point_size(float(match.group(2))):.1f}pt", qss
    )


def _dark_theme_color(member):
    """Fluent's dark-theme steps, around darkPrimaryColor instead of full brightness."""

    from PySide6.QtGui import QColor
    from qfluentwidgets.common.style_sheet import ThemeColor

    h, s, v, _alpha = QColor(_state["dark_primary"]).getHsvF()
    if member == ThemeColor.DARK_1:
        v *= 0.9
    elif member == ThemeColor.DARK_2:
        s *= 0.977
        v *= 0.82
    elif member == ThemeColor.DARK_3:
        s *= 0.95
        v *= 0.7
    elif member == ThemeColor.LIGHT_1:
        s *= 0.92
        v *= 1.05
    elif member == ThemeColor.LIGHT_2:
        s *= 0.78
        v *= 1.08
    elif member == ThemeColor.LIGHT_3:
        s *= 0.65
        v *= 1.1
    return QColor.fromHsvF(max(h, 0.0), min(s, 1.0), min(v, 1.0))


def install_patches():
    """Hook dark accent + font sizes into the library once; returns True when hooked."""

    if _state["patched"]:
        return True
    try:
        from qfluentwidgets.common import font as fluent_font
        from qfluentwidgets.common import style_sheet
        from qfluentwidgets.common.config import isDarkTheme
        from qfluentwidgets.components.widgets.table_view import TableItemDelegate

        original_cell_style = TableItemDelegate.initStyleOption
        original_color = style_sheet.ThemeColor.color
        original_render = style_sheet.renderQss
        original_get_font = fluent_font.getFont
    except (ImportError, AttributeError) as exc:  # pragma: no cover - other library version
        LOGGER.warning("Fluent 套件版本不同，深色主色與字體大小沿用套件預設：%s", exc)
        return False
    from PySide6.QtCore import Qt

    def color(self):
        if isDarkTheme():
            return _dark_theme_color(self)
        return original_color(self)

    def render_qss(qss):
        return _scale_qss_fonts(original_render(qss))

    def get_font(fontSize=14, weight=None):
        font = original_get_font(fontSize) if weight is None else original_get_font(fontSize, weight)
        font.setPointSizeF(_scaled_point_size(fontSize))
        return font

    def cell_style(self, option, index):
        # Fluent draws table / list cells one size below body text (13 px);
        # use the body size, like the rest of the window.
        original_cell_style(self, option, index)
        if index.data(Qt.FontRole) is None:
            option.font = get_font(FLUENT_BASE_PIXEL_SIZE)

    style_sheet.ThemeColor.color = color
    style_sheet.renderQss = render_qss
    TableItemDelegate.initStyleOption = cell_style
    # Modules that did "from ..common.font import getFont" keep their own name.
    import sys

    for name, module in list(sys.modules.items()):
        if name.startswith("qfluentwidgets") and getattr(module, "getFont", None) is original_get_font:
            module.getFont = get_font
    _state["patched"] = True
    return True


# -- applying -----------------------------------------------------------------


def apply_fluent_theme(theme_key="light", point_size=None, settings=None):
    """Theme mode, accent and fonts for every Fluent widget (call after QApplication exists)."""

    if not fluent_available():
        return False
    import qfluentwidgets

    settings = settings or load_fluent_theme()
    _state["dark_primary"] = settings["darkPrimaryColor"]
    if point_size:
        _state["point_size"] = point_size
    install_patches()
    qfluentwidgets.setFontFamilies(list(settings["fontFamilies"]))
    qfluentwidgets.setThemeColor(settings["primaryColor"])
    qfluentwidgets.setTheme(
        qfluentwidgets.Theme.DARK if theme_key == "dark" else qfluentwidgets.Theme.LIGHT
    )
    return True


def set_font_point_size(point_size):
    """Re-size Fluent text after the 字體大小 setting changed."""

    old = _state["point_size"]
    if not point_size or point_size == old or not fluent_available():
        _state["point_size"] = point_size or old
        return
    _state["point_size"] = point_size
    from PySide6.QtGui import QFont
    from qfluentwidgets.common.style_sheet import styleSheetManager, updateStyleSheet

    updateStyleSheet()
    # Widgets that got a font from getFont() (labels, menus) keep it explicitly.
    # Only the library's own list of live Fluent widgets is walked: going over
    # QApplication.allWidgets() can reach half-destroyed widgets and crash.
    for widget, _source in list(styleSheetManager.items()):
        try:
            font = QFont(widget.font())
            if font.pointSizeF() > 0 and font.resolveMask():
                font.setPointSizeF(font.pointSizeF() * point_size / old)
                widget.setFont(font)
        except RuntimeError:  # deleted while we were looping
            continue


def fluent_widget_classes():
    """Every QWidget subclass qfluentwidgets exports, for QUiLoader / Designer."""

    if not fluent_available():
        return []
    import inspect

    import qfluentwidgets
    from PySide6.QtWidgets import QWidget

    classes = []
    for name in sorted(getattr(qfluentwidgets, "__all__", None) or dir(qfluentwidgets)):
        value = getattr(qfluentwidgets, name, None)
        if inspect.isclass(value) and issubclass(value, QWidget) and value.__name__ == name:
            classes.append(value)
    # The program's own Fluent-styled widgets (Designer header: customer_fluent).
    classes.append(dialog_button_box_class())
    return classes


def set_custom_style(widget, light_qss, dark_qss=None):
    """Extra QSS for one Fluent widget, applied after the library's own sheet.

    The library sets a style sheet on each Fluent widget, and a widget's own
    sheet always beats the window / application sheet, so look changes for a
    Fluent widget have to go through here.
    """

    from qfluentwidgets import setCustomStyleSheet

    setCustomStyleSheet(widget, light_qss, light_qss if dark_qss is None else dark_qss)


# Built-in copy of ui/fluent_widgets.qss, used when that file is missing or broken.
FLUENT_WIDGETS_STYLESHEET = """
/* 工具列：搜尋框是一個外框（searchGroup）裡並排的欄位選單、輸入框、搜尋按鈕 */
QFrame#searchGroup ComboBox, QFrame#searchGroup ComboBox:hover,
QFrame#searchGroup ComboBox:pressed, QFrame#searchGroup ComboBox:focus {
    background-color: $auto;
    border: none;
    border-radius: 0px;
    min-height: 34px;
}
QFrame#searchGroup LineEdit, QFrame#searchGroup LineEdit:hover,
QFrame#searchGroup LineEdit:focus {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    min-height: 34px;
}
QFrame#searchGroup TransparentPushButton {
    border-radius: 0px;
    min-height: 34px;
}

/* 右側「基本資料」謄本格線：格子由 detail_form.qss 畫，欄位本身透明、無框 */
QWidget#basicDataForm LineEdit, QWidget#basicDataForm LineEdit:hover,
QWidget#basicDataForm LineEdit:focus, QWidget#basicDataForm LineEdit:disabled,
QWidget#basicDataForm PlainTextEdit, QWidget#basicDataForm PlainTextEdit:hover,
QWidget#basicDataForm PlainTextEdit:focus,
QWidget#basicDataForm ComboBox, QWidget#basicDataForm ComboBox:hover,
QWidget#basicDataForm ComboBox:pressed, QWidget#basicDataForm ComboBox:disabled {
    background-color: transparent;
    color: $ink;
    border: none;
    border-radius: 0px;
    padding: 2px 0px 0px 0px;
    min-height: 26px;
}
QWidget#basicDataForm LineEdit[readOnly="true"] {
    color: $ink2;
}

/* 刪除類按鈕用朱紅 */
TransparentPushButton#deleteRecordButton {
    color: $seal;
}
TransparentPushButton#deleteRecordButton:hover {
    background-color: $seal_hover;
}
PrimaryPushButton#deleteUrbanPlanConfirm {
    background-color: $seal;
    color: $seal_ink;
    border: 1px solid $seal;
}
PrimaryPushButton#deleteUrbanPlanConfirm:hover {
    background-color: $seal;
    border-color: $seal_ink;
}

/* 主視窗批量列（勾選後出現）：按鈕文字用勾選列的藍色 */
QFrame#batchBar PushButton, QFrame#batchBar TransparentPushButton {
    color: $checked_ink;
}
"""


def fluent_widgets_stylesheet(tokens=None):
    from customer_theme import rgba, theme_tokens

    values = dict(tokens or theme_tokens())
    values["ink_hover"] = rgba("ink", 4, values)
    values["seal_hover"] = rgba("seal", 8, values)
    return render_qss(FLUENT_WIDGETS_STYLESHEET_FILE, FLUENT_WIDGETS_STYLESHEET, values)


def style_fluent_widgets(root):
    """Add ui/fluent_widgets.qss to every Fluent widget under ``root`` (root included)."""

    classes = set(fluent_widget_classes())
    if not classes:
        return 0
    from PySide6.QtWidgets import QWidget

    widgets = [widget for widget in [root, *root.findChildren(QWidget)] if type(widget) in classes]
    if widgets:
        rules = _qss_rules(fluent_widgets_stylesheet())
        for widget in widgets:
            if isinstance(widget, dialog_button_box_class()):
                widget.use_fluent_buttons()
                continue
            # Only the rules that apply to this widget: Qt parses every
            # widget's own style sheet separately, and giving all of them the
            # whole file costs a lot of memory in a big window.
            qss = _rules_for(widget, rules)
            if qss:
                set_custom_style(widget, qss)
            keep_inner_buttons_out_of_tab_order(widget)
            keep_selection_highlight_in_sync(widget)
    return len(widgets)


_PSEUDO_OR_ATTRIBUTE = re.compile(r"(::?[\w-]+(\([^)]*\))?|\[[^\]]*\])")
_rules_cache = {}


def _qss_rules(qss):
    """[(selectors, body)] of a style sheet, comments removed."""

    if qss not in _rules_cache:
        text = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
        _rules_cache[qss] = [
            ([part.strip() for part in head.split(",") if part.strip()], body.strip())
            for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)
        ]
    return _rules_cache[qss]


def _compound_matches(widget, compound):
    """``LineEdit``, ``QFrame#searchGroup``, ``PushButton:hover`` against one widget."""

    match = re.fullmatch(r"([A-Za-z_]\w*)?(?:#([\w-]+))?", _PSEUDO_OR_ATTRIBUTE.sub("", compound))
    if match is None:
        return True  # something this matcher does not know: let Qt decide
    class_name, object_name = match.groups()
    if object_name and widget.objectName() != object_name:
        return False
    if class_name and class_name not in {cls.__name__ for cls in type(widget).__mro__}:
        return False
    return True


def _selector_applies(widget, selector):
    parts = selector.split()
    if not parts or not _compound_matches(widget, parts[-1]):
        return False
    ancestor = widget.parentWidget()
    for compound in reversed(parts[:-1]):
        while ancestor is not None and not _compound_matches(ancestor, compound):
            ancestor = ancestor.parentWidget()
        if ancestor is None:
            return False
        ancestor = ancestor.parentWidget()
    return True


def _rules_for(widget, rules):
    chunks = []
    for selectors, body in rules:
        matching = [selector for selector in selectors if _selector_applies(widget, selector)]
        if matching:
            chunks.append(f"{', '.join(matching)} {{ {body} }}")
    return "\n".join(chunks)


def keep_inner_buttons_out_of_tab_order(widget):
    """Tab skips the eye button of a password box, spin-box arrows, scroll-bar arrows.

    Fluent builds these as real buttons inside the field, which would add extra
    Tab stops; they still work with the mouse.
    """

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton

    if isinstance(widget, QAbstractButton):
        return
    for button in widget.findChildren(QAbstractButton):
        button.setFocusPolicy(Qt.NoFocus)


def keep_selection_highlight_in_sync(widget):
    """Fluent tables / lists show the selected rows the code selects, too.

    Fluent's TableWidget and ListWidget paint the selection from a row list
    they refresh only after mouse / keyboard use and their own select calls;
    rows selected through the selection model (selectRow on a filtered list,
    restoring a selection after a refresh, clearing the table) would keep the
    old highlight.  Refresh it whenever the selection or the rows change.
    """

    from PySide6.QtWidgets import QAbstractItemView

    if not isinstance(widget, QAbstractItemView) or not hasattr(widget, "updateSelectedRows"):
        return
    if widget.property("_fluentSelectionSync"):
        return
    widget.setProperty("_fluentSelectionSync", True)

    def refresh(*_args):
        try:
            widget.updateSelectedRows()
        except RuntimeError:  # the widget is being deleted
            pass

    selection_model = widget.selectionModel()
    if selection_model is not None:
        selection_model.selectionChanged.connect(refresh)
    model = widget.model()
    if model is not None:
        for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.layoutChanged):
            signal.connect(refresh)


_dialog_button_box_class = None


def dialog_button_box_class():
    """``DialogButtonBox``: a QDialogButtonBox whose buttons are Fluent buttons.

    In a .ui file it replaces QDialogButtonBox (Designer: promote to
    ``DialogButtonBox``, header ``customer_fluent``).  Its standard buttons
    (OK / 儲存 / 取消 / 關閉…) become Fluent buttons with the same text and role
    after loading -- OK / Save / Yes / Apply as the green primary button -- so
    accepted / rejected, Enter (default button) and Esc work as before, and
    ``button(QDialogButtonBox.Ok)`` returns the Fluent button.  Buttons the
    code adds with ``addButton("文字", role)`` are Fluent buttons too.
    """

    global _dialog_button_box_class
    if _dialog_button_box_class is not None:
        return _dialog_button_box_class

    from PySide6.QtWidgets import QDialogButtonBox
    from qfluentwidgets import PrimaryPushButton, PushButton

    primary = {
        QDialogButtonBox.StandardButton.Ok, QDialogButtonBox.StandardButton.Save,
        QDialogButtonBox.StandardButton.Yes, QDialogButtonBox.StandardButton.Apply,
        QDialogButtonBox.StandardButton.Open,
    }

    class DialogButtonBox(QDialogButtonBox):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._fluent_standard = {}

        def use_fluent_buttons(self):
            """Swap the standard buttons for Fluent ones (keeps text, role, default)."""

            for which in list(self._standard_flags()):
                native = QDialogButtonBox.button(self, which)
                if native is None or which in self._fluent_standard:
                    continue
                role = self.buttonRole(native)
                fluent = (PrimaryPushButton if which in primary else PushButton)(native.text(), self)
                fluent.setObjectName(native.objectName())
                fluent.setDefault(native.isDefault())
                fluent.setAutoDefault(native.autoDefault())
                self.removeButton(native)
                # removeButton() leaves it without a parent; keep it as a hidden
                # child so it is deleted with the row.  Not deleted now:
                # deleting widgets QUiLoader made can make PySide drop
                # unrelated wrappers (see customer_ui_loader).
                native.setParent(self)
                native.hide()
                super().addButton(fluent, role)
                self._fluent_standard[which] = fluent

        def _standard_flags(self):
            flags = self.standardButtons()
            for which in QDialogButtonBox.StandardButton:
                if which.value and flags & which:
                    yield which

        def button(self, which):
            return self._fluent_standard.get(which) or super().button(which)

        def standardButton(self, button):
            for which, fluent in self._fluent_standard.items():
                if fluent is button:
                    return which
            return super().standardButton(button)

        def addButton(self, *args):
            if len(args) == 2 and isinstance(args[0], str):
                text, role = args
                button = (PrimaryPushButton if role == QDialogButtonBox.ButtonRole.AcceptRole
                          else PushButton)(text, self)
                super().addButton(button, role)
                return button
            if len(args) == 1 and isinstance(args[0], QDialogButtonBox.StandardButton):
                result = super().addButton(args[0])
                self.use_fluent_buttons()
                return self.button(args[0]) or result
            return super().addButton(*args)

    DialogButtonBox.__module__ = __name__
    _dialog_button_box_class = DialogButtonBox
    return DialogButtonBox
