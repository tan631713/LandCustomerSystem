"""Qt hierarchical model for land parents and ownership child records."""

from __future__ import annotations

from dataclasses import dataclass

from customer_land_tree import LandGroup, group_land_records, ownership_area
from customer_domain import format_number_text
from customer_tag_display import normalize_tag_items, safe_tag_qcolor, tag_names
from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap

TABLE_COLUMNS = ()
TABLE_BATCH_SIZE = 100
CHECK_COLUMN = 0
ROW_COLOR_CHECKED = QColor("#1e3a5f")
ROW_COLOR_WATCHLIST = QColor("#5b2230")
ROW_COLOR_OVERDUE = QColor("#7c2d12")
ROW_COLOR_NOTE = QColor("#564113")
ROW_TEXT_COLOR = QColor("#f8fafc")
SEARCH_HIGHLIGHT_COLOR = QColor("#6b4f1d")

NODE_KIND_ROLE = Qt.UserRole + 1
NODE_DATA_ROLE = Qt.UserRole + 2
TAGS_ROLE = Qt.UserRole + 3
TAG_DATA_CHANGED_ROLES = [
    Qt.DisplayRole,
    Qt.CheckStateRole,
    Qt.BackgroundRole,
    Qt.ForegroundRole,
    Qt.FontRole,
    Qt.DecorationRole,
    Qt.ToolTipRole,
    Qt.TextAlignmentRole,
    NODE_DATA_ROLE,
    TAGS_ROLE,
]

CENTER_ALIGNED_FIELDS = {
    "district",
    "section",
    "registration_order",
    "land_number",
    "area",
    "owner_count",
    "ownership_count",
    "numerator",
    "denominator",
    "share",
    "ownership_area",
    "ping",
    "owner_name",
    "external_id",
    "address",
    "registration_reason",
    "attachment_count",
    "next_follow_up",
    "follow_up_status",
    "customer_status",
}
RIGHT_ALIGNED_FIELDS = {"declared_value", "total_declared_value"}


def configure_table_model(**dependencies):
    globals().update(dependencies)


@dataclass(slots=True)
class _TreeNode:
    kind: str
    parent: "_TreeNode | None" = None
    group: LandGroup | None = None
    record: dict | None = None
    row: int = 0


class LandTreeProxyModel(QSortFilterProxyModel):
    """Stable proxy boundary for the tree view.

    Filtering and hierarchy-aware sorting happen in the background record
    processor.  The proxy deliberately preserves that order and supplies the
    usual source/proxy mapping needed by selection and future delegates.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(False)
        self.setRecursiveFilteringEnabled(True)


class RecordTableModel(QAbstractItemModel):
    """Tree model retaining the legacy flat-row API for batch workflows."""

    def __init__(self, checked_changed_callback, parent=None):
        super().__init__(parent)
        self.checked_changed_callback = checked_changed_callback
        self.all_rows = []
        self.rows = []
        self.groups: list[LandGroup] = []
        self.page_size = max(1, int(TABLE_BATCH_SIZE or 100))
        self.batch_size = self.page_size
        self.current_page = 0
        self.total_count = 0
        self.ownership_total_count = 0
        self.page_ownership_count = 0
        self.page_loader = None
        self._legacy_total_count = None
        self._background_preview_pending = False
        self._root_nodes: list[_TreeNode] = []
        self._record_nodes: dict[int, _TreeNode] = {}

    @property
    def page_count(self):
        if not self.total_count:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size

    def _page_groups(self):
        start = self.current_page * self.page_size
        return self.groups[start : start + self.page_size]

    def _rebuild_nodes(self):
        self._root_nodes = []
        self._record_nodes = {}
        visible_rows = []
        for land_row, group in enumerate(self._page_groups()):
            parent = _TreeNode("land", group=group, row=land_row)
            self._root_nodes.append(parent)
            for child_row, record in enumerate(group.records):
                child = _TreeNode(
                    "ownership",
                    parent=parent,
                    group=group,
                    record=record,
                    row=child_row,
                )
                self._record_nodes[int(record["id"])] = child
                visible_rows.append(record)
        self.rows = visible_rows
        self.page_ownership_count = len(visible_rows)

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self._root_nodes)
        node = parent.internalPointer()
        if node is not None and node.kind == "land":
            return len(node.group.records)
        return 0

    def columnCount(self, _parent=QModelIndex()):
        return len(TABLE_COLUMNS)

    def index(self, row, column, parent=QModelIndex()):
        if row < 0 or column < 0 or column >= self.columnCount():
            return QModelIndex()
        if not parent.isValid():
            if row >= len(self._root_nodes):
                return QModelIndex()
            return self.createIndex(row, column, self._root_nodes[row])
        parent_node = parent.internalPointer()
        if parent_node is None or parent_node.kind != "land":
            return QModelIndex()
        if row >= len(parent_node.group.records):
            return QModelIndex()
        record_id = int(parent_node.group.records[row]["id"])
        child = self._record_nodes.get(record_id)
        return (
            self.createIndex(row, column, child)
            if child is not None
            else QModelIndex()
        )

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if node is None or node.kind != "ownership" or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    @staticmethod
    def _group_display(group, key):
        record = group.representative
        raw = record.get("raw") or {}
        if key == "checked":
            return ""
        if key == "rowid":
            return str(group.land_id or "")
        if key == "full_land_number":
            return group.full_land_number
        if key == "owner_count":
            return str(group.owner_count)
        if key == "ownership_count":
            return str(group.ownership_count)
        if key == "land_use":
            return group.land_use or "未設定"
        if key == "status_summary":
            return group.status_summary
        if key == "tag_names":
            return tag_names(group.tags)
        if key == "owner_name":
            return f"{group.owner_count} 位地主／{group.ownership_count} 筆持分"
        if key in {
            "district",
            "section",
            "land_number",
            "area",
            "declared_value",
        }:
            return record.get("display", {}).get(key, raw.get(key, ""))
        return ""

    @staticmethod
    def _child_display(record, key):
        display = record.get("display") or {}
        raw = record.get("raw") or {}
        if key == "full_land_number":
            return ""
        if key in {"owner_count", "ownership_count", "land_use", "status_summary"}:
            return ""
        if key == "share":
            numerator = str(raw.get("numerator") or "").strip()
            denominator = str(raw.get("denominator") or "").strip()
            return f"{numerator}/{denominator}" if numerator or denominator else ""
        if key == "ownership_area":
            value = ownership_area(record)
            return "" if value is None else f"{value:,.2f} ㎡"
        if key == "phone":
            return str(raw.get("phone") or "")
        if key == "customer_status":
            return str(raw.get("customer_status") or raw.get("follow_up_status") or "")
        if key == "note_summary":
            note = str(raw.get("note") or "").strip().replace("\n", " ")
            return note if len(note) <= 40 else note[:39] + "…"
        if key == "tag_names":
            return tag_names(
                record.get("tags")
                or (record.get("raw") or {}).get("tag_items")
                or []
            )
        return display.get(key, "")

    @staticmethod
    def _node_tags(node):
        if node.kind == "land":
            return [dict(item) for item in node.group.tags]
        return normalize_tag_items(
            node.record.get("tags")
            or (node.record.get("raw") or {}).get("tag_items")
            or [],
            names=(
                (node.record.get("raw") or {}).get("tag_names")
                or (node.record.get("display") or {}).get("tag_names")
            ),
            primary_color=node.record.get("tag_color"),
        )

    @staticmethod
    def _parent_check_state(group):
        checked = sum(bool(record.get("checked")) for record in group.records)
        if checked == 0:
            return Qt.Unchecked
        if checked == len(group.records):
            return Qt.Checked
        return Qt.PartiallyChecked

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if node is None:
            return None
        key = TABLE_COLUMNS[index.column()][0]
        if role == NODE_KIND_ROLE:
            return node.kind
        if role == NODE_DATA_ROLE:
            if node.kind == "land":
                return {
                    "land_id": node.group.land_id,
                    "state_id": node.group.state_id,
                    "record_ids": node.group.record_ids,
                }
            return {
                "land_id": node.group.land_id,
                "owner_id": node.record.get("owner_id"),
                "ownership_id": node.record.get("ownership_id") or node.record["id"],
                "record_id": node.record["id"],
            }
        if key == "tag_names":
            tags = self._node_tags(node)
            if role == TAGS_ROLE:
                return tags
            if role == Qt.DecorationRole:
                if not tags:
                    return None
                pixmap = QPixmap(10, 10)
                pixmap.fill(safe_tag_qcolor(tags[0].get("color")))
                return QIcon(pixmap)
        if index.column() == CHECK_COLUMN:
            if role == Qt.CheckStateRole:
                if node.kind == "land":
                    return self._parent_check_state(node.group)
                return Qt.Checked if node.record.get("checked") else Qt.Unchecked
            if role == Qt.DisplayRole:
                return ""
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
            return None

        value = (
            self._group_display(node.group, key)
            if node.kind == "land"
            else self._child_display(node.record, key)
        )
        if role == Qt.DisplayRole:
            return value
        if role == Qt.ToolTipRole:
            if node.kind == "land":
                return (
                    f"{node.group.full_land_number}\n"
                    f"土地面積：{format_number_text(node.group.area or '') or '未設定'} ㎡\n"
                    f"地主：{node.group.owner_count} 位\n"
                    f"所有權資料：{node.group.ownership_count} 筆\n"
                    f"地目／使用分區：{node.group.land_use or '未設定'}\n"
                    f"狀態：{node.group.status_summary or '無'}"
                )
            if key in {"address", "note_summary", "note"}:
                return str(
                    (node.record.get("raw") or {}).get(
                        "note" if key in {"note_summary", "note"} else key,
                        "",
                    )
                    or ""
                )
        if role == Qt.BackgroundRole:
            if node.kind == "land":
                if node.group.ownership_count == 1:
                    record = node.group.representative
                    return record.get("background") or QColor("#243244")
                return QColor("#243244")
            if (
                node.record.get("background") is None
                and key in node.record.get("highlighted_fields", set())
            ):
                return SEARCH_HIGHLIGHT_COLOR
            return node.record.get("background")
        if role == Qt.ForegroundRole:
            if node.kind == "land":
                return QColor("#f8fafc")
            if node.record.get("background") is not None:
                return ROW_TEXT_COLOR
        if role == Qt.FontRole:
            if node.kind == "land":
                font = QFont()
                font.setBold(True)
                return font
            if key in node.record.get("highlighted_fields", set()):
                font = QFont()
                font.setBold(True)
                return font
        if role == Qt.TextAlignmentRole:
            if key in CENTER_ALIGNED_FIELDS:
                return int(Qt.AlignCenter)
            if key in RIGHT_ALIGNED_FIELDS:
                return int(Qt.AlignVCenter | Qt.AlignRight)
            if key in {"rowid", "full_land_number"}:
                return int(Qt.AlignVCenter | Qt.AlignLeft)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return TABLE_COLUMNS[section][1]
        return str(section + 1)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == CHECK_COLUMN:
            flags |= Qt.ItemIsUserCheckable
            if index.internalPointer().kind == "land":
                flags |= Qt.ItemIsAutoTristate
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if (
            not index.isValid()
            or index.column() != CHECK_COLUMN
            or role != Qt.CheckStateRole
        ):
            return False
        return self.set_node_checked(index, self._checked_value(value))

    @staticmethod
    def _checked_value(value):
        """Normalize Qt enum and native item-delegate integer check states."""

        if value == Qt.Checked:
            return True
        enum_value = getattr(value, "value", value)
        try:
            return int(enum_value) == int(Qt.Checked.value)
        except (TypeError, ValueError):
            return False

    def set_node_checked(self, index, checked):
        """Apply the established land-parent or ownership-child semantics."""

        if not index.isValid() or index.column() != CHECK_COLUMN:
            return False
        node = index.internalPointer()
        if node is None:
            return False
        target = bool(checked)
        records = node.group.records if node.kind == "land" else [node.record]
        changed = []
        for record in records:
            if bool(record.get("checked")) == target:
                continue
            self._set_record_checked(record, target)
            changed.append(int(record["id"]))
        for record_id in changed:
            self.checked_changed_callback(record_id, target)
        if changed:
            left = self.index(node.row, CHECK_COLUMN, self.parent(index))
            right = self.index(node.row, self.columnCount() - 1, self.parent(index))
            self.dataChanged.emit(
                left,
                right,
                [Qt.CheckStateRole, Qt.BackgroundRole],
            )
            if node.kind == "ownership":
                parent_index = self.parent(index)
                self.dataChanged.emit(
                    parent_index.siblingAtColumn(CHECK_COLUMN),
                    parent_index.siblingAtColumn(self.columnCount() - 1),
                    [Qt.CheckStateRole],
                )
        return True

    @staticmethod
    def _set_record_checked(record, checked):
        record["checked"] = bool(checked)
        if checked:
            record["background"] = ROW_COLOR_CHECKED
        elif record.get("is_watchlist"):
            record["background"] = ROW_COLOR_WATCHLIST
        elif record.get("is_overdue"):
            record["background"] = ROW_COLOR_OVERDUE
        elif record.get("has_note"):
            record["background"] = ROW_COLOR_NOTE
        else:
            record["background"] = None

    def set_rows(self, rows):
        self.beginResetModel()
        source = list(rows)
        self.all_rows = source
        self.groups = list(
            getattr(rows, "groups", None) or group_land_records(source).groups
        )
        self.total_count = len(self.groups)
        self.ownership_total_count = len(self.all_rows)
        self.current_page = min(self.current_page, self.page_count - 1)
        self.page_loader = None
        self._legacy_total_count = None
        self._background_preview_pending = False
        self._rebuild_nodes()
        self.endResetModel()

    def update_rows_in_place(self, rows):
        """Replace record contents without resetting an unchanged tree.

        A reset is still required when a land group, ownership membership,
        or page structure changes.  Content-only edits keep the existing
        QModelIndex objects, expansion, selection, and scroll state.  A save
        may change a value used by the current sort; that must not turn a
        harmless edit into a model reset, so the existing visual order is
        retained until the user explicitly sorts or performs a full refresh.
        """

        source = list(rows)
        refreshed_groups = list(
            getattr(rows, "groups", None) or group_land_records(source).groups
        )
        if len(refreshed_groups) != len(self.groups):
            return False
        refreshed_by_state_id = {
            group.state_id: group for group in refreshed_groups
        }
        if len(refreshed_by_state_id) != len(refreshed_groups):
            return False
        if set(refreshed_by_state_id) != {
            group.state_id for group in self.groups
        }:
            return False

        ordered_groups = []
        for existing_group in self.groups:
            refreshed_group = refreshed_by_state_id[existing_group.state_id]
            refreshed_records = {
                int(record["id"]): record for record in refreshed_group.records
            }
            if len(refreshed_records) != len(refreshed_group.records):
                return False
            if set(refreshed_records) != set(existing_group.record_ids):
                return False
            refreshed_group.records = [
                refreshed_records[record_id]
                for record_id in existing_group.record_ids
            ]
            ordered_groups.append(refreshed_group)

        ordered_rows = [
            record for group in ordered_groups for record in group.records
        ]
        self.all_rows = ordered_rows
        self.groups = ordered_groups
        self.total_count = len(ordered_groups)
        self.ownership_total_count = len(ordered_rows)
        self.page_loader = None
        self._legacy_total_count = None
        self._background_preview_pending = False

        visible_groups = self._page_groups()
        visible_rows = []
        old_record_nodes = dict(self._record_nodes)
        self._record_nodes = {}
        for local_row, group in enumerate(visible_groups):
            parent_node = self._root_nodes[local_row]
            parent_node.group = group
            for child_row, record in enumerate(group.records):
                record_id = int(record["id"])
                child_node = old_record_nodes[record_id]
                child_node.parent = parent_node
                child_node.group = group
                child_node.record = record
                child_node.row = child_row
                self._record_nodes[record_id] = child_node
                visible_rows.append(record)

        self.rows = visible_rows
        self.page_ownership_count = len(visible_rows)
        if not self._root_nodes or not self.columnCount():
            return True

        last_column = self.columnCount() - 1
        for parent_row, parent_node in enumerate(self._root_nodes):
            parent_left = self.index(parent_row, 0)
            parent_right = self.index(parent_row, last_column)
            self.dataChanged.emit(
                parent_left,
                parent_right,
                TAG_DATA_CHANGED_ROLES,
            )
            if not parent_node.group.records:
                continue
            child_left = self.index(0, 0, parent_left)
            child_right = self.index(
                len(parent_node.group.records) - 1,
                last_column,
                parent_left,
            )
            self.dataChanged.emit(
                child_left,
                child_right,
                TAG_DATA_CHANGED_ROLES,
            )
        return True

    def set_paged_rows(self, rows, _total_count, _page_loader):
        # Kept only for old component integrations.  The production search
        # controller no longer calls this path; its paging is land-group based.
        self.set_rows(rows)
        self._legacy_total_count = max(len(rows), int(_total_count or 0))
        self.page_loader = _page_loader

    def set_page(self, page):
        page = max(0, min(int(page), self.page_count - 1))
        if page == self.current_page:
            return False
        self.beginResetModel()
        self.current_page = page
        self._rebuild_nodes()
        self.endResetModel()
        return True

    def next_page(self):
        return self.set_page(self.current_page + 1)

    def previous_page(self):
        return self.set_page(self.current_page - 1)

    def canFetchMore(self, parent=QModelIndex()):
        if not parent.isValid() and self._background_preview_pending:
            return True
        return bool(
            not parent.isValid()
            and self.page_loader is not None
            and self._legacy_total_count is not None
            and len(self.all_rows) < self._legacy_total_count
        )

    def fetchMore(self, parent=QModelIndex()):
        if not parent.isValid() and self._background_preview_pending:
            return None
        if not self.canFetchMore(parent):
            return None
        loader = self.page_loader
        total = self._legacy_total_count
        offset = len(self.all_rows)
        loaded = list(loader(offset, self.batch_size) or [])
        if not loaded:
            self._legacy_total_count = len(self.all_rows)
            return None
        combined = list(self.all_rows) + loaded
        self.set_rows(combined)
        self.page_loader = loader
        self._legacy_total_count = total
        return None

    def load_all(self):
        while self.canFetchMore():
            self.fetchMore()
        return self.all_rows

    def ensure_row_loaded(self, _row_number):
        return None

    def row_for_record_id(self, record_id):
        wanted = int(record_id)
        while True:
            for index, row in enumerate(self.all_rows):
                if int(row["id"]) == wanted:
                    return index
            if not self.canFetchMore():
                break
            self.fetchMore()
        return -1

    def row_record(self, row_number):
        if 0 <= row_number < len(self.rows):
            return self.rows[row_number]
        return None

    def node_for_index(self, index):
        return index.internalPointer() if index.isValid() else None

    def group_for_index(self, index):
        node = self.node_for_index(index)
        return None if node is None else node.group

    def record_for_index(self, index):
        node = self.node_for_index(index)
        return node.record if node is not None and node.kind == "ownership" else None

    def record_ids_for_index(self, index):
        node = self.node_for_index(index)
        if node is None:
            return []
        if node.kind == "land":
            return node.group.record_ids
        return [int(node.record["id"])]

    def index_for_group_state_id(self, state_id):
        for row, node in enumerate(self._root_nodes):
            if node.group.state_id == state_id:
                return self.index(row, 0)
        return QModelIndex()

    def index_for_record_id(self, record_id):
        wanted = int(record_id)
        group_index = -1
        for index, group in enumerate(self.groups):
            if wanted in group.record_ids:
                group_index = index
                break
        if group_index < 0:
            return QModelIndex()
        page = group_index // self.page_size
        if page != self.current_page:
            self.set_page(page)
        child = self._record_nodes.get(wanted)
        if child is None:
            return QModelIndex()
        parent_index = self.index(child.parent.row, 0)
        return self.index(child.row, 0, parent_index)

    def update_checked_state(self, record_id, checked):
        wanted = int(record_id)
        for row in self.all_rows:
            if int(row["id"]) == wanted:
                self._set_record_checked(row, checked)
                break
        child = self._record_nodes.get(wanted)
        if child is None:
            return
        parent_index = self.index(child.parent.row, 0)
        left = self.index(child.row, 0, parent_index)
        right = self.index(child.row, self.columnCount() - 1, parent_index)
        self.dataChanged.emit(
            left,
            right,
            [Qt.CheckStateRole, Qt.BackgroundRole],
        )
        self.dataChanged.emit(
            parent_index,
            parent_index.siblingAtColumn(self.columnCount() - 1),
            [Qt.CheckStateRole],
        )
