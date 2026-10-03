"""Qt widget for the 都市計畫 view: plan → 地段 → 小段 → 地號 → 地主."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from customer_urban_plan_tree import default_expanded_keys

LEVEL_ROLE = Qt.UserRole + 20
COLUMN_TITLES = ("名稱", "地主數", "持分數", "面積 ㎡")
NUMBER_COLUMN_WIDTH = 86

# Structural colours: same family as the land tree (#2d2d2d) with the plan and
# section rows set off a little so the hierarchy reads at a glance.
PLAN_BACKGROUND = QColor("#34404f")
SECTION_BACKGROUND = QColor("#2f3743")
LEVEL_LABEL_COLOR = QColor("#8b98ab")
OWNER_TEXT_COLOR = QColor("#cbd5e1")
EMPTY_TEXT_COLOR = QColor("#8b98ab")


def plan_tree_style(row_height=28):
    row_height = max(20, int(row_height))
    return (
        "QTreeWidget { background-color: #2d2d2d; alternate-background-color: #2d2d2d; }"
        "QTreeWidget::item {"
        f" min-height: {row_height}px;"
        " border-bottom: 1px solid #374151;"
        " }"
        "QTreeWidget::item:selected { background-color: #365d8d; color: #ffffff; }"
    )


class PlanTreeItem(QTreeWidgetItem):
    """One row; `node` is the PlanTreeNode it shows."""

    def __init__(self, node):
        super().__init__()
        self.node = node


class PlanRowDelegate(QStyledItemDelegate):
    """Draws the small grey level caption (都市計畫 / 地段 / …) after the name."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        caption = index.data(LEVEL_ROLE)
        if not caption:
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        advance = opt.fontMetrics.horizontalAdvance(opt.text)
        left = text_rect.left() + advance + 12
        if left >= option.rect.right() - 6:
            return
        font = QFont(opt.font)
        font.setBold(False)
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.82))
        painter.save()
        try:
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setFont(font)
            painter.setPen(LEVEL_LABEL_COLOR)
            area = QRect(left, option.rect.top(), option.rect.right() - left - 4, option.rect.height())
            painter.drawText(area, int(Qt.AlignVCenter | Qt.AlignLeft), str(caption))
        finally:
            painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), 24))


class UrbanPlanTreeView(QTreeWidget):
    """The plan tree. It only displays what it is given; the window owns all state.

    * `checkRequested(record_ids, checked)` — the user ticked a row; the
      window updates its shared checked set, then calls `refresh_check_states`.
    * `nodeSelected(node)` — the current row changed by the user's own action.
    """

    checkRequested = Signal(object, bool)
    nodeSelected = Signal(object)
    nodeActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("urbanPlanTree")
        self.setColumnCount(len(COLUMN_TITLES))
        self.setHeaderLabels(list(COLUMN_TITLES))
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAllColumnsShowFocus(True)
        self.setRootIsDecorated(True)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(22)
        self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setItemDelegate(PlanRowDelegate(self))
        self.setStyleSheet(plan_tree_style())
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(COLUMN_TITLES)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            header.resizeSection(column, NUMBER_COLUMN_WIDTH)
            self.headerItem().setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)

        self.checked_ids_provider = lambda: ()
        self.empty_text = "沒有符合條件的資料"
        self.expanded_keys = None  # None until the user (or a default) sets it
        self._items = {}
        self._record_items = {}
        self._syncing = False
        self.itemChanged.connect(self._on_item_changed)
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemCollapsed.connect(self._on_item_collapsed)
        self.currentItemChanged.connect(self._on_current_item_changed)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    # -- building ---------------------------------------------------------

    def set_row_height(self, row_height):
        self.setStyleSheet(plan_tree_style(row_height))

    def set_tree(self, tree, *, expand_all=False, select_record_id=None):
        """Rebuild the rows from a PlanTree, keeping what the user had open."""

        selected_keys = {item.node.key for item in self.selectedItems()}
        current = self.currentItem()
        current_key = None if current is None else current.node.key
        scroll_value = self.verticalScrollBar().value()
        self._syncing = True
        self.setUpdatesEnabled(False)
        try:
            self.clear()
            self._items = {}
            self._record_items = {}
            top_level = [self._build_item(root) for root in tree.roots]
            self.addTopLevelItems(top_level)
            if self.expanded_keys is None:
                self.expanded_keys = default_expanded_keys(tree)
            if expand_all:
                self.expandAll()
            else:
                for key in self.expanded_keys:
                    item = self._items.get(key)
                    if item is not None and item.childCount():
                        item.setExpanded(True)
            self._apply_check_states()
            if select_record_id is not None and int(select_record_id) in self._record_items:
                self._reveal(self._record_items[int(select_record_id)])
                self.setCurrentItem(self._record_items[int(select_record_id)])
            else:
                for key in selected_keys:
                    item = self._items.get(key)
                    if item is not None:
                        item.setSelected(True)
                if current_key in self._items:
                    self.setCurrentItem(self._items[current_key], 0, QItemSelectionModel.NoUpdate)
            self.verticalScrollBar().setValue(scroll_value)
        finally:
            self.setUpdatesEnabled(True)
            self._syncing = False
        self.viewport().update()

    def _build_item(self, node):
        item = PlanTreeItem(node)
        item.setText(0, node.title)
        item.setData(0, LEVEL_ROLE, node.level_label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        if node.kind == "owner":
            item.setText(1, "")
            item.setText(2, node.share_text)
            item.setForeground(0, QBrush(OWNER_TEXT_COLOR))
        else:
            item.setText(1, str(node.owner_count))
            item.setText(2, str(node.share_count))
        item.setText(3, node.area_text)
        for column in range(1, len(COLUMN_TITLES)):
            item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
        if node.kind in ("plan", "section"):
            font = QFont(item.font(0))
            font.setBold(True)
            for column in range(len(COLUMN_TITLES)):
                item.setFont(column, font)
            brush = QBrush(PLAN_BACKGROUND if node.kind == "plan" else SECTION_BACKGROUND)
            for column in range(len(COLUMN_TITLES)):
                item.setBackground(column, brush)
        self._items[node.key] = item
        if node.kind == "owner":
            self._record_items[int(node.record["id"])] = item
        for child in node.children:
            item.addChild(self._build_item(child))
        return item

    # -- checkboxes ---------------------------------------------------------

    def refresh_check_states(self):
        self._syncing = True
        try:
            self._apply_check_states()
        finally:
            self._syncing = False
        self.viewport().update()

    def _apply_check_states(self):
        checked = set(self.checked_ids_provider() or ())
        for item in self._items.values():
            ids = item.node.record_ids
            if not ids:
                state = Qt.Unchecked
            else:
                count = sum(1 for record_id in ids if record_id in checked)
                if count == 0:
                    state = Qt.Unchecked
                elif count == len(ids):
                    state = Qt.Checked
                else:
                    state = Qt.PartiallyChecked
            if item.checkState(0) != state:
                item.setCheckState(0, state)

    def _on_item_changed(self, item, column):
        if self._syncing or column != 0 or not isinstance(item, PlanTreeItem):
            return
        checked = item.checkState(0) == Qt.Checked
        record_ids = list(item.node.record_ids)
        if record_ids:
            self.checkRequested.emit(record_ids, checked)
        self.refresh_check_states()

    # -- expansion ----------------------------------------------------------

    def _on_item_expanded(self, item):
        if not self._syncing and self.expanded_keys is not None and isinstance(item, PlanTreeItem):
            self.expanded_keys.add(item.node.key)

    def _on_item_collapsed(self, item):
        if not self._syncing and self.expanded_keys is not None and isinstance(item, PlanTreeItem):
            self.expanded_keys.discard(item.node.key)

    def expand_everything(self):
        self.expandAll()
        self.expanded_keys = {key for key, item in self._items.items() if item.childCount()}

    def collapse_everything(self):
        self.collapseAll()
        self.expanded_keys = set()

    # -- selection ------------------------------------------------------------

    def _on_current_item_changed(self, current, _previous):
        if self._syncing or not isinstance(current, PlanTreeItem):
            return
        self.nodeSelected.emit(current.node)

    def _on_item_double_clicked(self, item, _column):
        if isinstance(item, PlanTreeItem):
            self.nodeActivated.emit(item.node)

    def current_node(self):
        item = self.currentItem()
        return item.node if isinstance(item, PlanTreeItem) else None

    def node_at(self, position):
        item = self.itemAt(position)
        return item.node if isinstance(item, PlanTreeItem) else None

    def selected_nodes(self):
        return [item.node for item in self.selectedItems() if isinstance(item, PlanTreeItem)]

    def selected_record_ids(self):
        ids = set()
        for node in self.selected_nodes():
            ids.update(node.record_ids)
        return sorted(ids)

    def selected_land_ids(self):
        land_ids = set()
        for node in self.selected_nodes():
            land_ids.update(node.land_ids)
        return sorted(land_ids)

    def select_record(self, record_id):
        """Select an owner row without telling anyone (the form is already showing it)."""

        item = self._record_items.get(int(record_id))
        if item is None:
            return False
        self._syncing = True
        try:
            self._reveal(item)
            self.clearSelection()
            self.setCurrentItem(item)
            item.setSelected(True)
            self.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        finally:
            self._syncing = False
        return True

    def select_node_for_context_menu(self, item):
        """Right-clicking a row outside the selection selects just that row."""

        if item is None or item.isSelected():
            return
        self._syncing = True
        try:
            self.clearSelection()
            self.setCurrentItem(item)
            item.setSelected(True)
        finally:
            self._syncing = False

    def has_record(self, record_id):
        return int(record_id) in self._record_items

    def _reveal(self, item):
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            if self.expanded_keys is not None:
                self.expanded_keys.add(parent.node.key)
            parent = parent.parent()

    # -- painting -------------------------------------------------------------

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.topLevelItemCount():
            return
        painter = QPainter(self.viewport())
        try:
            painter.setPen(EMPTY_TEXT_COLOR)
            painter.drawText(self.viewport().rect(), int(Qt.AlignCenter), self.empty_text)
        finally:
            painter.end()
