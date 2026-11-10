"""Loads the Qt Designer files under ``ui/``: .ui layouts and .qss style templates.

The ``ui`` folder sits next to this module when running from source and inside
``sys._MEIPASS`` in the PyInstaller build (build_exe.bat ships it with
``--add-data "ui;ui"``).  A .ui file is loaded at run time with QUiLoader, so it
can be edited in pyside6-designer without regenerating any Python code; the
code then looks its widgets up by objectName, and a missing name stops start-up
with a message saying which file and which names to restore.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from string import Template

LOGGER = logging.getLogger(__name__)

UI_DIR_NAME = "ui"


class UiLoadError(RuntimeError):
    """A .ui file is missing, unreadable, or lacks a widget the program needs."""


def resource_dir():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def ui_dir():
    return resource_dir() / UI_DIR_NAME


def ui_path(name):
    return ui_dir() / name


def object_names(root):
    """Every objectName under ``root`` (widgets and layouts), ``root`` included."""

    from PySide6.QtCore import QObject

    names = {root.objectName()}
    names.update(child.objectName() for child in root.findChildren(QObject))
    names.discard("")
    return names


def missing_object_names(root, required_names):
    present = object_names(root)
    return [name for name in required_names if name not in present]


_fluent_classes = None


def fluent_widget_classes():
    """The Fluent widget classes, looked up once (see customer_fluent)."""

    global _fluent_classes
    if _fluent_classes is None:
        from customer_fluent import fluent_widget_classes as find_classes

        _fluent_classes = find_classes()
    return _fluent_classes


def fluent_classes_used_in(path):
    """The Fluent classes named in a .ui file's <widget class="..."> tags."""

    classes = fluent_widget_classes()
    if not classes:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    used = set(re.findall(r'<widget\s+class="(\w+)"', text))
    return [widget_class for widget_class in classes if widget_class.__name__ in used]


def load_ui(name, parent=None, required_names=()):
    """Build the widget tree described by ``ui/<name>``.

    Raises UiLoadError when the file is missing or broken, or when any of
    ``required_names`` is not an objectName in it.
    """

    from PySide6.QtCore import QDir, QFile, QIODevice
    from PySide6.QtUiTools import QUiLoader

    path = ui_path(name)
    if not path.is_file():
        raise UiLoadError(
            f"找不到介面檔：{path}\n"
            f"請確認 {UI_DIR_NAME} 資料夾與程式放在一起；改壞時可從備份還原這個檔案。"
        )
    loader = QUiLoader()
    loader.setWorkingDirectory(QDir(str(path.parent)))
    for widget_class in fluent_classes_used_in(path):
        # Widgets promoted to a Fluent class in Designer (header qfluentwidgets).
        # Only the classes this file uses: PySide keeps every registration, so
        # registering all of them on each load gets slower and slower.
        loader.registerCustomWidget(widget_class)
    ui_file = QFile(str(path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise UiLoadError(f"介面檔無法開啟：{path}\n{ui_file.errorString()}")
    try:
        widget = loader.load(ui_file, parent)
    finally:
        ui_file.close()
    if widget is None:
        raise UiLoadError(
            f"介面檔格式有誤，無法載入：{path}\n{loader.errorString()}\n"
            "請用 pyside6-designer 重新開啟並儲存，或從備份還原。"
        )
    missing = missing_object_names(widget, required_names)
    if missing:
        widget.setParent(None)
        widget.deleteLater()
        raise UiLoadError(
            f"介面檔 {path.name} 少了程式需要的元件（objectName）：\n"
            + "、".join(missing)
            + "\n這些元件在 Qt Designer 裡不能改名或刪除；請改回原名，或從備份還原這個檔案。"
        )
    if fluent_widget_classes():
        from customer_fluent import style_fluent_widgets

        style_fluent_widgets(widget)
    return widget


def find_child(root, object_name, cls=None):
    """``root.findChild`` that raises UiLoadError instead of returning None."""

    from PySide6.QtCore import QObject

    child = root.findChild(cls or QObject, object_name)
    if child is None:
        raise UiLoadError(
            f"介面檔缺少元件 {object_name}"
            + (f"（類型應為 {cls.__name__}）" if cls is not None else "")
            + "；請改回原名或從備份還原 .ui 檔。"
        )
    return child


DIALOG_SIZE_PROPERTY = "dialogSize"
QWIDGETSIZE_MAX = 16777215


def install_ui(host, name, required_names=(), layout=None):
    """Load ``ui/<name>`` and make it the whole content of the dialog ``host``.

    The .ui root is a plain QWidget (so the dialog class keeps its own Python
    subclass); its windowTitle, minimumSize and maximumSize become the
    dialog's, and an optional ``dialogSize`` dynamic property is the size the
    dialog opens at.  ``layout`` is the host's own layout when the .ui is only
    part of the dialog (the rest is added by code); by default the .ui fills
    the dialog.  Returns the loaded root widget.
    """

    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QVBoxLayout

    content = load_ui(name, required_names=required_names)
    if layout is None:
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    layout.addWidget(content)
    if content.windowTitle():
        host.setWindowTitle(content.windowTitle())
    host.setMinimumSize(content.minimumSize())
    host.setMaximumSize(content.maximumSize())
    content.setMinimumSize(0, 0)
    content.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
    size = content.property(DIALOG_SIZE_PROPERTY)
    if isinstance(size, QSize) and size.isValid():
        host.resize(size)
    return content



UNPARENTED_WIDGET_SIZE = (640, 480)


def size_like_unparented(view):
    """Give a table from a .ui file the 640x480 Qt gives a widget made without a parent.

    The hand-built dialogs created their tables that way and called
    resizeRowsToContents() before the first layout, so row heights were
    measured with columns stretched to that width.  A .ui table starts at
    100x30, where long cells wrap and rows come out taller; call this before
    filling such a table to keep its rows as they were.  The dialog's layout
    resizes the table afterwards as usual.
    """

    from PySide6.QtCore import QCoreApplication, QSize
    from PySide6.QtGui import QResizeEvent

    old_size = view.size()
    view.resize(*UNPARENTED_WIDGET_SIZE)
    # A hidden widget gets its resize event only when shown, and item views
    # lay out their headers and items later still; do both now, at this size.
    QCoreApplication.sendEvent(view, QResizeEvent(view.size(), old_size))
    view.updateGeometries()
    for header in (getattr(view, "horizontalHeader", None), getattr(view, "verticalHeader", None)):
        if header is not None:
            header = header()
            QCoreApplication.sendEvent(header, QResizeEvent(header.size(), QSize()))
            header.resizeSections()
    view.doItemsLayout()
    return view


def put_in_slot(slot, widget):
    """Replace the empty placeholder ``slot`` with ``widget``.

    ``widget`` takes the slot's place in its layout (grid cell or box index,
    stretch and alignment, via QLayout.replaceWidget) and in the Tab order.
    The emptied slot stays behind as a hidden, layout-less child: deleting it
    from Python (deleteLater / setParent(None)) can make PySide drop the
    wrappers of unrelated widgets loaded from the same .ui file.
    """

    layout = slot.parentWidget().layout() if slot.parentWidget() else None
    if layout is None:
        raise UiLoadError(f"佔位元件 {slot.objectName()} 不在任何版面（layout）裡")
    _take_tab_position(slot, widget)
    # replaceWidget() searches nested layouts and hands back the slot's old
    # layout item, which is ours to drop.
    if layout.replaceWidget(slot, widget) is None:
        raise UiLoadError(f"佔位元件 {slot.objectName()} 不在任何版面（layout）裡")
    slot.hide()
    return widget


def chain_tab_order(widgets, after=None):
    """Make Tab visit ``widgets`` in the given order (NoFocus ones are skipped).

    For widgets built in code after a .ui file was loaded: they join the end
    of the focus chain, so chain them in among the .ui widgets explicitly.
    ``after`` is a widget that comes before them (a container is fine: it is
    made focusable just long enough to anchor on), so that the chain also
    starts in the right place and not merely in the right cyclic order.
    """

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    focusable = [widget for widget in widgets if widget.focusPolicy() != Qt.NoFocus]
    anchor_policy = None
    if after is not None:
        anchor_policy = after.focusPolicy()
        if anchor_policy == Qt.NoFocus:
            after.setFocusPolicy(Qt.TabFocus)
        focusable.insert(0, after)
    for first, second in zip(focusable, focusable[1:]):
        QWidget.setTabOrder(first, second)
    if anchor_policy is not None:
        after.setFocusPolicy(anchor_policy)


def _take_tab_position(slot, widget):
    """Move ``widget`` (and its focusable children) to where ``slot`` sits in Tab order.

    setTabOrder() ignores a NoFocus anchor and does not carry a widget's
    children along, so the empty slot is made focusable just long enough to
    anchor on, and each focusable widget is chained after the previous one.
    """

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    window = slot.window()
    movers = []
    current = window.nextInFocusChain()
    guard = 0
    while current is not window and guard < 10000:
        guard += 1
        if (current is widget or widget.isAncestorOf(current)) and (
            current.focusPolicy() != Qt.NoFocus
        ):
            movers.append(current)
        current = current.nextInFocusChain()
    slot.setFocusPolicy(Qt.TabFocus)
    previous = slot
    for mover in movers:
        QWidget.setTabOrder(previous, mover)
        previous = mover
    slot.setFocusPolicy(Qt.NoFocus)


def render_qss(name, fallback, values):
    """``ui/<name>`` with its ``$token`` placeholders filled in from ``values``.

    Falls back to the built-in ``fallback`` template when the file is missing,
    unreadable or uses an unknown placeholder, so a broken edit only costs the
    customised look, never start-up.
    """

    path = ui_path(name)
    try:
        return Template(path.read_text(encoding="utf-8")).substitute(values)
    except FileNotFoundError:
        LOGGER.warning("Stylesheet %s not found; using the built-in style", path)
    except (OSError, UnicodeDecodeError, KeyError, ValueError):
        LOGGER.exception("Stylesheet %s could not be used; using the built-in style", path)
    return Template(fallback).substitute(values)
