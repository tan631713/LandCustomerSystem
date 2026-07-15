"""Qt table model for customer records."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

TABLE_COLUMNS = ()
TABLE_BATCH_SIZE = 200
ROW_COLOR_CHECKED = QColor("#1e3a5f")
ROW_COLOR_WATCHLIST = QColor("#5b2230")
ROW_COLOR_OVERDUE = QColor("#7c2d12")
ROW_COLOR_NOTE = QColor("#564113")
ROW_TEXT_COLOR = QColor("#f8fafc")
SEARCH_HIGHLIGHT_COLOR = QColor("#6b4f1d")

CENTER_ALIGNED_FIELDS = {
    "district",
    "section",
    "registration_order",
    "land_number",
    "area",
    "numerator",
    "denominator",
    "ping",
    "owner_name",
    "external_id",
    "address",
    "registration_reason",
    "attachment_count",
    "next_follow_up",
    "follow_up_status",
}
RIGHT_ALIGNED_FIELDS = {"declared_value", "total_declared_value"}


def configure_table_model(**dependencies):
    globals().update(dependencies)


class RecordTableModel(QAbstractTableModel):
    def __init__(self, checked_changed_callback, parent=None):
        super().__init__(parent)
        self.checked_changed_callback = checked_changed_callback
        self.all_rows = []
        self.rows = []
        self.batch_size = TABLE_BATCH_SIZE
        self.page_loader = None
        self.total_count = 0

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(TABLE_COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = TABLE_COLUMNS[index.column()][0]
        value = row["display"].get(key, "")

        if key == "checked":
            if role == Qt.CheckStateRole:
                return Qt.Checked if row["checked"] else Qt.Unchecked
            if role == Qt.DisplayRole:
                return ""
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
            return None

        if role == Qt.DisplayRole:
            return value
        if role == Qt.BackgroundRole:
            if key == "tag_names":
                tag_color = QColor(str(row.get("tag_color") or ""))
                if tag_color.isValid():
                    return tag_color
            if row.get("background") is None and key in row.get("highlighted_fields", set()):
                return SEARCH_HIGHLIGHT_COLOR
            return row.get("background")
        if role == Qt.ForegroundRole:
            if key == "tag_names":
                tag_color = QColor(str(row.get("tag_color") or ""))
                if tag_color.isValid():
                    return QColor("#111827") if tag_color.lightness() >= 150 else ROW_TEXT_COLOR
            if row.get("background") is not None:
                return ROW_TEXT_COLOR
        if role == Qt.FontRole and key in row.get("highlighted_fields", set()):
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.TextAlignmentRole:
            if key in CENTER_ALIGNED_FIELDS:
                return int(Qt.AlignCenter)
            if key in RIGHT_ALIGNED_FIELDS:
                return int(Qt.AlignVCenter | Qt.AlignRight)
            if key == "rowid":
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
        key = TABLE_COLUMNS[index.column()][0]
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if key == "checked":
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        key = TABLE_COLUMNS[index.column()][0]
        if key != "checked" or role != Qt.CheckStateRole:
            return False

        checked = value == Qt.Checked
        row = self.rows[index.row()]
        if row["checked"] == checked:
            return True

        row["checked"] = checked
        if checked:
            row["background"] = ROW_COLOR_CHECKED
        elif row.get("is_watchlist"):
            row["background"] = ROW_COLOR_WATCHLIST
        elif row.get("is_overdue"):
            row["background"] = ROW_COLOR_OVERDUE
        elif row.get("has_note"):
            row["background"] = ROW_COLOR_NOTE
        else:
            row["background"] = None
        self.checked_changed_callback(row["id"], checked)
        left_index = self.index(index.row(), 0)
        right_index = self.index(index.row(), self.columnCount() - 1)
        self.dataChanged.emit(left_index, right_index, [Qt.CheckStateRole, Qt.BackgroundRole])
        return True

    def set_rows(self, rows):
        self.beginResetModel()
        self.all_rows = rows
        self.rows = rows[: self.batch_size]
        self.page_loader = None
        self.total_count = len(rows)
        self.endResetModel()

    def set_paged_rows(self, rows, total_count, page_loader):
        self.beginResetModel()
        self.all_rows = list(rows)
        self.rows = self.all_rows
        self.page_loader = page_loader
        self.total_count = max(len(self.rows), int(total_count))
        self.endResetModel()

    def canFetchMore(self, parent=QModelIndex()):
        if parent.isValid():
            return False
        return len(self.rows) < self.total_count

    def fetchMore(self, parent=QModelIndex()):
        if parent.isValid() or not self.canFetchMore():
            return
        start = len(self.rows)
        if self.page_loader is not None:
            next_rows = list(self.page_loader(start, self.batch_size))
            if not next_rows:
                self.total_count = start
                return
            end = start + len(next_rows)
        else:
            end = min(start + self.batch_size, len(self.all_rows))
        self.beginInsertRows(QModelIndex(), start, end - 1)
        if self.page_loader is not None:
            self.rows.extend(next_rows)
        else:
            self.rows.extend(self.all_rows[start:end])
        self.endInsertRows()

    def load_all(self):
        while self.canFetchMore():
            self.fetchMore()
        return self.all_rows

    def ensure_row_loaded(self, row_number):
        while row_number >= len(self.rows) and self.canFetchMore():
            self.fetchMore()

    def row_for_record_id(self, record_id):
        searched_count = 0
        while True:
            for index in range(searched_count, len(self.all_rows)):
                if self.all_rows[index]["id"] == record_id:
                    self.ensure_row_loaded(index)
                    return index
            searched_count = len(self.all_rows)
            if not self.canFetchMore():
                break
            self.fetchMore()
        return -1

    def row_record(self, row_number):
        if 0 <= row_number < len(self.rows):
            return self.rows[row_number]
        return None

    def update_checked_state(self, record_id, checked):
        row_number = self.row_for_record_id(record_id)
        if row_number < 0:
            return
        row = self.rows[row_number]
        row["checked"] = checked
        if checked:
            row["background"] = ROW_COLOR_CHECKED
        elif row.get("is_watchlist"):
            row["background"] = ROW_COLOR_WATCHLIST
        elif row.get("is_overdue"):
            row["background"] = ROW_COLOR_OVERDUE
        elif row.get("has_note"):
            row["background"] = ROW_COLOR_NOTE
        else:
            row["background"] = None
        left_index = self.index(row_number, 0)
        right_index = self.index(row_number, self.columnCount() - 1)
        self.dataChanged.emit(left_index, right_index, [Qt.CheckStateRole, Qt.BackgroundRole])
