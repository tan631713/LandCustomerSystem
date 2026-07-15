"""Additional management dialogs for cases, tags, attachments, templates, and health checks."""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from customer_desktop import open_path_or_web_url
from customer_responsive_dialog import ResponsiveDialog as QDialog


def _row_id(table, row_number):
    item = table.item(row_number, 0)
    if item is None:
        return None
    return item.data(Qt.UserRole)


def _set_row_values(table, row_number, values, row_id=None):
    for column_number, value in enumerate(values):
        item = QTableWidgetItem(str(value or ""))
        if column_number == 0 and row_id is not None:
            item.setData(Qt.UserRole, row_id)
        table.setItem(row_number, column_number, item)


class CaseManagementDialog(QDialog):
    def __init__(self, cases, parent=None):
        super().__init__(parent)
        self.cases = [dict(row) for row in cases]
        self.action = None
        self.setWindowTitle("案件管理")
        self.resize(760, 520)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "案件名稱", "狀態", "筆數", "備註"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_current_case)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        self.title_edit = QLineEdit()
        self.status_edit = QLineEdit("進行中")
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(90)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("建立案件後，可把勾選資料加入同一個案件追蹤。"))
        layout.addWidget(self.table, 1)
        form = QGridLayout()
        form.addWidget(QLabel("案件名稱"), 0, 0)
        form.addWidget(self.title_edit, 0, 1)
        form.addWidget(QLabel("狀態"), 1, 0)
        form.addWidget(self.status_edit, 1, 1)
        form.addWidget(QLabel("備註"), 2, 0)
        form.addWidget(self.note_edit, 2, 1)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        new_button = QPushButton("清空")
        new_button.clicked.connect(self.clear_form)
        save_button = QPushButton("新增/更新")
        save_button.clicked.connect(self.request_save)
        delete_button = QPushButton("刪除選取案件")
        delete_button.clicked.connect(self.request_delete)
        view_button = QPushButton("顯示案件資料")
        view_button.clicked.connect(self.request_view)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(new_button)
        buttons.addWidget(view_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.cases))
        for row_number, case in enumerate(self.cases):
            _set_row_values(
                self.table,
                row_number,
                [
                    case.get("id"),
                    case.get("title"),
                    case.get("status"),
                    case.get("customer_count"),
                    case.get("note"),
                ],
                case.get("id"),
            )

    def selected_case_id(self):
        row_number = self.table.currentRow()
        if row_number < 0:
            return None
        return _row_id(self.table, row_number)

    def load_current_case(self):
        case_id = self.selected_case_id()
        if case_id is None:
            return
        for case in self.cases:
            if case.get("id") == case_id:
                self.title_edit.setText(case.get("title") or "")
                self.status_edit.setText(case.get("status") or "進行中")
                self.note_edit.setPlainText(case.get("note") or "")
                return

    def clear_form(self):
        self.table.clearSelection()
        self.title_edit.clear()
        self.status_edit.setText("進行中")
        self.note_edit.clear()

    def values(self):
        return {
            "case_id": self.selected_case_id(),
            "title": self.title_edit.text().strip(),
            "status": self.status_edit.text().strip() or "進行中",
            "note": self.note_edit.toPlainText().strip(),
        }

    def request_save(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "缺少案件名稱", "請輸入案件名稱。")
            return
        self.action = "save"
        self.accept()

    def request_delete(self):
        if self.selected_case_id() is None:
            QMessageBox.warning(self, "未選取案件", "請先選取要刪除的案件。")
            return
        self.action = "delete"
        self.accept()

    def request_view(self):
        if self.selected_case_id() is None:
            QMessageBox.warning(self, "未選取案件", "請先選取要顯示的案件。")
            return
        self.action = "view"
        self.accept()


class CaseSelectDialog(QDialog):
    def __init__(
        self,
        cases,
        selected_count=0,
        parent=None,
        *,
        dialog_title="加入案件",
        action_text="加入",
    ):
        super().__init__(parent)
        self.cases = [dict(row) for row in cases]
        self.setWindowTitle(dialog_title)
        self.resize(420, 180)
        self.case_combo = QComboBox()
        for case in self.cases:
            self.case_combo.addItem(
                f"{case.get('title')} ({case.get('status') or '進行中'})",
                case.get("id"),
            )

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"將對 {selected_count} 筆資料執行「{action_text}」："))
        layout.addWidget(self.case_combo)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        ok_button = QPushButton(action_text)
        ok_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        layout.addLayout(buttons)

    def selected_case_id(self):
        return self.case_combo.currentData()


class TagManagementDialog(QDialog):
    def __init__(self, tags, parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        self.action = None
        self.setWindowTitle("標籤管理")
        self.resize(620, 420)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "標籤", "顏色", "筆數"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_current_tag)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.name_edit = QLineEdit()
        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("#ffcc00，可空白")
        self.color_button = QPushButton("選色")
        self.color_button.clicked.connect(self.choose_color)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        form = QGridLayout()
        form.addWidget(QLabel("標籤名稱"), 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(QLabel("顏色"), 1, 0)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_edit, 1)
        color_row.addWidget(self.color_button)
        form.addLayout(color_row, 1, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_form)
        save_button = QPushButton("新增/更新")
        save_button.clicked.connect(self.request_save)
        delete_button = QPushButton("刪除選取標籤")
        delete_button.clicked.connect(self.request_delete)
        view_button = QPushButton("顯示標籤資料")
        view_button.clicked.connect(self.request_view)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(clear_button)
        buttons.addWidget(view_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.tags))
        for row_number, tag in enumerate(self.tags):
            _set_row_values(
                self.table,
                row_number,
                [tag.get("id"), tag.get("name"), tag.get("color"), tag.get("customer_count")],
                tag.get("id"),
            )
            color = QColor(str(tag.get("color") or ""))
            if color.isValid():
                item = self.table.item(row_number, 1)
                item.setBackground(color)
                item.setForeground(
                    QColor("#111827") if color.lightness() >= 150 else QColor("#f8fafc")
                )

    def choose_color(self):
        initial = QColor(self.color_edit.text().strip())
        color = QColorDialog.getColor(
            initial if initial.isValid() else QColor("#ffcc00"),
            self,
            "選擇標籤顏色",
        )
        if color.isValid():
            self.color_edit.setText(color.name())

    def selected_tag_id(self):
        row_number = self.table.currentRow()
        return None if row_number < 0 else _row_id(self.table, row_number)

    def load_current_tag(self):
        tag_id = self.selected_tag_id()
        for tag in self.tags:
            if tag.get("id") == tag_id:
                self.name_edit.setText(tag.get("name") or "")
                self.color_edit.setText(tag.get("color") or "")
                return

    def clear_form(self):
        self.table.clearSelection()
        self.name_edit.clear()
        self.color_edit.clear()

    def values(self):
        return {
            "tag_id": self.selected_tag_id(),
            "name": self.name_edit.text().strip(),
            "color": self.color_edit.text().strip(),
        }

    def request_save(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "缺少標籤名稱", "請輸入標籤名稱。")
            return
        color_text = self.color_edit.text().strip()
        if color_text and not QColor(color_text).isValid():
            QMessageBox.warning(self, "顏色格式錯誤", "請使用 #RRGGBB 格式，或按「選色」。")
            return
        self.action = "save"
        self.accept()

    def request_delete(self):
        if self.selected_tag_id() is None:
            QMessageBox.warning(self, "未選取標籤", "請先選取要刪除的標籤。")
            return
        self.action = "delete"
        self.accept()

    def request_view(self):
        if self.selected_tag_id() is None:
            QMessageBox.warning(self, "未選取標籤", "請先選取要顯示的標籤。")
            return
        self.action = "view"
        self.accept()


class CustomerTagsDialog(QDialog):
    def __init__(self, tags, selected_tag_ids=None, record_label="", parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        self.selected_tag_ids = set(selected_tag_ids or [])
        self.setWindowTitle("設定資料標籤")
        self.resize(440, 420)
        self.list_widget = QListWidget()
        for tag in self.tags:
            item = QListWidgetItem(tag.get("name") or "")
            item.setData(Qt.UserRole, tag.get("id"))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tag.get("id") in self.selected_tag_ids else Qt.Unchecked)
            color = QColor(str(tag.get("color") or ""))
            if color.isValid():
                item.setBackground(color)
                item.setForeground(
                    QColor("#111827") if color.lightness() >= 150 else QColor("#f8fafc")
                )
            self.list_widget.addItem(item)

        layout = QVBoxLayout(self)
        label = QLabel(record_label or "勾選要套用到此資料的標籤。")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(self.list_widget, 1)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    def selected_ids(self):
        ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids


class BatchCustomerTagsDialog(QDialog):
    def __init__(self, tags, selected_count=0, parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        self.setWindowTitle("批量設定標籤")
        self.resize(460, 480)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("加入所選標籤（保留原有）", "add")
        self.mode_combo.addItem("移除所選標籤", "remove")
        self.mode_combo.addItem("完全取代原有標籤", "replace")
        self.list_widget = QListWidget()
        for tag in self.tags:
            item = QListWidgetItem(tag.get("name") or "")
            item.setData(Qt.UserRole, tag.get("id"))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            color = QColor(str(tag.get("color") or ""))
            if color.isValid():
                item.setBackground(color)
                item.setForeground(
                    QColor("#111827") if color.lightness() >= 150 else QColor("#f8fafc")
                )
            self.list_widget.addItem(item)

        layout = QVBoxLayout(self)
        title = QLabel(f"將處理 {selected_count} 筆選取或勾選資料。")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(QLabel("處理方式"))
        layout.addWidget(self.mode_combo)
        layout.addWidget(QLabel("選擇標籤"))
        layout.addWidget(self.list_widget, 1)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("套用")
        apply_button.clicked.connect(self.request_apply)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def selected_ids(self):
        return [
            self.list_widget.item(index).data(Qt.UserRole)
            for index in range(self.list_widget.count())
            if self.list_widget.item(index).checkState() == Qt.Checked
        ]

    def mode(self):
        return self.mode_combo.currentData() or "add"

    def request_apply(self):
        if not self.selected_ids() and self.mode() != "replace":
            QMessageBox.warning(self, "未選取標籤", "請至少選取一個要加入或移除的標籤。")
            return
        self.accept()


class AttachmentDialog(QDialog):
    def __init__(self, attachments, record_label="", parent=None):
        super().__init__(parent)
        self.attachments = [dict(row) for row in attachments]
        self.action = None
        self.setWindowTitle("附件管理")
        self.resize(780, 470)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "檔案路徑", "說明", "保存方式", "建立時間"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.open_selected_file)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.path_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.managed_checkbox = QCheckBox("複製到系統附件庫（建議，會隨完整備份保存）")
        self.managed_checkbox.setChecked(True)

        layout = QVBoxLayout(self)
        title = QLabel(record_label or "附件可由系統完整納管，也可只連結外部檔案。")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("檔案"))
        row.addWidget(self.path_edit, 1)
        browse_button = QPushButton("瀏覽")
        browse_button.clicked.connect(self.browse_file)
        row.addWidget(browse_button)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("說明"))
        row2.addWidget(self.description_edit, 1)
        layout.addLayout(row2)
        layout.addWidget(self.managed_checkbox)
        buttons = QHBoxLayout()
        add_button = QPushButton("新增附件")
        add_button.clicked.connect(self.request_add)
        delete_button = QPushButton("刪除選取附件")
        delete_button.clicked.connect(self.request_delete)
        open_button = QPushButton("開啟選取檔案")
        open_button.clicked.connect(self.open_selected_file)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(add_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.attachments))
        for row_number, attachment in enumerate(self.attachments):
            _set_row_values(
                self.table,
                row_number,
                [
                    attachment.get("id"),
                    attachment.get("file_path"),
                    attachment.get("description"),
                    "外部連結"
                    if attachment.get("status") == "external"
                    else "系統納管",
                    attachment.get("created_at"),
                ],
                attachment.get("id"),
            )

    def selected_attachment_id(self):
        row_number = self.table.currentRow()
        return None if row_number < 0 else _row_id(self.table, row_number)

    def selected_file_path(self):
        row_number = self.table.currentRow()
        item = self.table.item(row_number, 1) if row_number >= 0 else None
        return "" if item is None else item.text()

    def browse_file(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(self, "選取附件")
        if file_path:
            self.path_edit.setText(file_path)

    def values(self):
        return {
            "attachment_id": self.selected_attachment_id(),
            "file_path": self.path_edit.text().strip(),
            "description": self.description_edit.text().strip(),
            "managed": self.managed_checkbox.isChecked(),
        }

    def request_add(self):
        if not self.path_edit.text().strip():
            QMessageBox.warning(self, "缺少檔案", "請先選取或貼上檔案路徑。")
            return
        self.action = "add"
        self.accept()

    def request_delete(self):
        if self.selected_attachment_id() is None:
            QMessageBox.warning(self, "未選取附件", "請先選取要刪除的附件。")
            return
        self.action = "delete"
        self.accept()

    def open_selected_file(self, *_args):
        file_path = self.selected_file_path()
        if not file_path:
            QMessageBox.information(self, "未選取附件", "請先選取要開啟的附件。")
            return
        open_path_or_web_url(file_path, self, item_label="附件")


class CustomFieldManagementDialog(QDialog):
    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.action = None
        self.setWindowTitle("自訂欄位管理")
        self.resize(620, 420)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "欄位代碼", "欄位名稱"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_current_field)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("可空白，系統會自動產生")
        self.label_edit = QLineEdit()

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        form = QGridLayout()
        form.addWidget(QLabel("欄位名稱"), 0, 0)
        form.addWidget(self.label_edit, 0, 1)
        form.addWidget(QLabel("欄位代碼"), 1, 0)
        form.addWidget(self.key_edit, 1, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_form)
        save_button = QPushButton("新增/更新")
        save_button.clicked.connect(self.request_save)
        delete_button = QPushButton("刪除選取欄位")
        delete_button.clicked.connect(self.request_delete)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.fields))
        for row_number, field in enumerate(self.fields):
            _set_row_values(
                self.table,
                row_number,
                [field.get("id"), field.get("field_key"), field.get("label")],
                field.get("id"),
            )

    def selected_field_id(self):
        row_number = self.table.currentRow()
        return None if row_number < 0 else _row_id(self.table, row_number)

    def load_current_field(self):
        field_id = self.selected_field_id()
        for field in self.fields:
            if field.get("id") == field_id:
                self.key_edit.setText(field.get("field_key") or "")
                self.label_edit.setText(field.get("label") or "")
                return

    def clear_form(self):
        self.table.clearSelection()
        self.key_edit.clear()
        self.label_edit.clear()

    def values(self):
        return {
            "field_id": self.selected_field_id(),
            "field_key": self.key_edit.text().strip(),
            "label": self.label_edit.text().strip(),
        }

    def request_save(self):
        if not self.label_edit.text().strip():
            QMessageBox.warning(self, "缺少欄位名稱", "請輸入欄位名稱。")
            return
        self.action = "save"
        self.accept()

    def request_delete(self):
        if self.selected_field_id() is None:
            QMessageBox.warning(self, "未選取欄位", "請先選取要刪除的欄位。")
            return
        self.action = "delete"
        self.accept()


class CustomerCustomValuesDialog(QDialog):
    def __init__(self, fields, values=None, record_label="", parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.values = dict(values or {})
        self.edits = {}
        self.setWindowTitle("設定自訂欄位")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        title = QLabel(record_label or "填寫此資料的自訂欄位。")
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QGridLayout()
        for row_number, field in enumerate(self.fields):
            edit = QLineEdit(str(self.values.get(field.get("id")) or ""))
            self.edits[field.get("id")] = edit
            form.addWidget(QLabel(field.get("label") or field.get("field_key")), row_number, 0)
            form.addWidget(edit, row_number, 1)
        layout.addLayout(form, 1)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    def result_values(self):
        return {
            field_id: edit.text().strip()
            for field_id, edit in self.edits.items()
        }


class BatchCustomerCustomValuesDialog(QDialog):
    def __init__(self, fields, selected_count=0, parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.rows = {}
        self.setWindowTitle("批量設定自訂欄位")
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        title = QLabel(
            f"將處理 {selected_count} 筆資料。只會修改已勾選的欄位；勾選後留空代表清除該欄位。"
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QGridLayout()
        for row_number, field in enumerate(self.fields):
            checkbox = QCheckBox(field.get("label") or field.get("field_key"))
            edit = QLineEdit()
            edit.setEnabled(False)
            checkbox.toggled.connect(edit.setEnabled)
            field_id = field.get("id")
            self.rows[field_id] = (checkbox, edit)
            form.addWidget(checkbox, row_number, 0)
            form.addWidget(edit, row_number, 1)
        form.setColumnStretch(1, 1)
        layout.addLayout(form, 1)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("套用")
        apply_button.clicked.connect(self.request_apply)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def result_values(self):
        return {
            field_id: edit.text().strip()
            for field_id, (checkbox, edit) in self.rows.items()
            if checkbox.isChecked()
        }

    def request_apply(self):
        if not self.result_values():
            QMessageBox.warning(self, "未選取欄位", "請至少勾選一個要批量修改的自訂欄位。")
            return
        self.accept()


class TextTemplateDialog(QDialog):
    TEMPLATE_TYPES = (("note", "備註"), ("visit_log", "出訪記錄"))

    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.templates = [dict(row) for row in templates]
        self.action = None
        self.setWindowTitle("快速範本管理")
        self.resize(760, 520)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "用途", "名稱", "內容"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_current_template)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.type_combo = QComboBox()
        for value, label in self.TEMPLATE_TYPES:
            self.type_combo.addItem(label, value)
        self.title_edit = QLineEdit()
        self.content_edit = QPlainTextEdit()

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        form = QGridLayout()
        form.addWidget(QLabel("用途"), 0, 0)
        form.addWidget(self.type_combo, 0, 1)
        form.addWidget(QLabel("名稱"), 1, 0)
        form.addWidget(self.title_edit, 1, 1)
        form.addWidget(QLabel("內容"), 2, 0)
        form.addWidget(self.content_edit, 2, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_form)
        save_button = QPushButton("新增/更新")
        save_button.clicked.connect(self.request_save)
        delete_button = QPushButton("刪除選取範本")
        delete_button.clicked.connect(self.request_delete)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        label_by_type = dict(self.TEMPLATE_TYPES)
        self.table.setRowCount(len(self.templates))
        for row_number, template in enumerate(self.templates):
            _set_row_values(
                self.table,
                row_number,
                [
                    template.get("id"),
                    label_by_type.get(template.get("template_type"), template.get("template_type")),
                    template.get("title"),
                    template.get("content"),
                ],
                template.get("id"),
            )

    def selected_template_id(self):
        row_number = self.table.currentRow()
        return None if row_number < 0 else _row_id(self.table, row_number)

    def load_current_template(self):
        template_id = self.selected_template_id()
        for template in self.templates:
            if template.get("id") == template_id:
                index = self.type_combo.findData(template.get("template_type"))
                self.type_combo.setCurrentIndex(index if index >= 0 else 0)
                self.title_edit.setText(template.get("title") or "")
                self.content_edit.setPlainText(template.get("content") or "")
                return

    def clear_form(self):
        self.table.clearSelection()
        self.type_combo.setCurrentIndex(0)
        self.title_edit.clear()
        self.content_edit.clear()

    def values(self):
        return {
            "template_id": self.selected_template_id(),
            "template_type": self.type_combo.currentData() or "note",
            "title": self.title_edit.text().strip(),
            "content": self.content_edit.toPlainText().strip(),
        }

    def request_save(self):
        if not self.title_edit.text().strip() or not self.content_edit.toPlainText().strip():
            QMessageBox.warning(self, "範本不完整", "請輸入範本名稱與內容。")
            return
        self.action = "save"
        self.accept()

    def request_delete(self):
        if self.selected_template_id() is None:
            QMessageBox.warning(self, "未選取範本", "請先選取要刪除的範本。")
            return
        self.action = "delete"
        self.accept()


class ApplyTemplateDialog(QDialog):
    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.templates = [dict(row) for row in templates]
        self.setWindowTitle("套用快速範本")
        self.resize(520, 200)
        self.target_combo = QComboBox()
        self.target_combo.addItem("備註", "note")
        self.target_combo.addItem("出訪記錄", "visit_log")
        self.template_combo = QComboBox()
        for template in self.templates:
            target = "備註" if template.get("template_type") == "note" else "出訪記錄"
            self.template_combo.addItem(f"[{target}] {template.get('title')}", template.get("id"))

        layout = QVBoxLayout(self)
        form = QGridLayout()
        form.addWidget(QLabel("套用到"), 0, 0)
        form.addWidget(self.target_combo, 0, 1)
        form.addWidget(QLabel("範本"), 1, 0)
        form.addWidget(self.template_combo, 1, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("套用")
        apply_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def selected_template(self):
        template_id = self.template_combo.currentData()
        for template in self.templates:
            if template.get("id") == template_id:
                return template
        return None

    def values(self):
        return {
            "target_field": self.target_combo.currentData() or "note",
            "template": self.selected_template(),
        }


class ContactLogDialog(QDialog):
    def __init__(self, logs, record_label="", parent=None):
        super().__init__(parent)
        self.logs = [dict(row) for row in logs]
        self.action = None
        self.setWindowTitle("聯絡紀錄")
        self.resize(820, 540)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "日期", "方式", "結果", "下次追蹤", "內容"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("YYYY-MM-DD")
        self.method_edit = QLineEdit()
        self.result_edit = QLineEdit()
        self.next_edit = QLineEdit()
        self.next_edit.setPlaceholderText("YYYY-MM-DD，可空白")
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(90)

        layout = QVBoxLayout(self)
        title = QLabel(record_label or "新增或查看此資料的聯絡紀錄。")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self.table, 1)
        form = QGridLayout()
        form.addWidget(QLabel("日期"), 0, 0)
        form.addWidget(self.date_edit, 0, 1)
        form.addWidget(QLabel("方式"), 0, 2)
        form.addWidget(self.method_edit, 0, 3)
        form.addWidget(QLabel("結果"), 1, 0)
        form.addWidget(self.result_edit, 1, 1)
        form.addWidget(QLabel("下次追蹤"), 1, 2)
        form.addWidget(self.next_edit, 1, 3)
        form.addWidget(QLabel("內容"), 2, 0)
        form.addWidget(self.note_edit, 2, 1, 1, 3)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        add_button = QPushButton("新增紀錄")
        add_button.clicked.connect(self.request_add)
        delete_button = QPushButton("刪除選取紀錄")
        delete_button.clicked.connect(self.request_delete)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)
        buttons.addWidget(add_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.logs))
        for row_number, log in enumerate(self.logs):
            _set_row_values(
                self.table,
                row_number,
                [
                    log.get("id"),
                    log.get("contact_date"),
                    log.get("method"),
                    log.get("result"),
                    log.get("next_follow_up"),
                    log.get("note"),
                ],
                log.get("id"),
            )

    def selected_log_id(self):
        row_number = self.table.currentRow()
        return None if row_number < 0 else _row_id(self.table, row_number)

    def values(self):
        return {
            "log_id": self.selected_log_id(),
            "contact_date": self.date_edit.text().strip(),
            "method": self.method_edit.text().strip(),
            "result": self.result_edit.text().strip(),
            "next_follow_up": self.next_edit.text().strip(),
            "note": self.note_edit.toPlainText().strip(),
        }

    def request_add(self):
        if not any(
            text.strip()
            for text in (
                self.date_edit.text(),
                self.method_edit.text(),
                self.result_edit.text(),
                self.next_edit.text(),
                self.note_edit.toPlainText(),
            )
        ):
            QMessageBox.warning(self, "紀錄空白", "請至少填寫一個聯絡紀錄欄位。")
            return
        self.action = "add"
        self.accept()

    def request_delete(self):
        if self.selected_log_id() is None:
            QMessageBox.warning(self, "未選取紀錄", "請先選取要刪除的聯絡紀錄。")
            return
        self.action = "delete"
        self.accept()

    def accept(self):
        if self.action == "add":
            for label, value in (
                ("聯絡日期", self.date_edit.text().strip()),
                ("下次追蹤", self.next_edit.text().strip()),
            ):
                if not value:
                    continue
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    QMessageBox.warning(
                        self,
                        "日期格式錯誤",
                        f"{label}請使用 YYYY-MM-DD，例如 2026-07-20。",
                    )
                    return
        super().accept()


class MergeRecordsDialog(QDialog):
    def __init__(self, primary_label, secondary_label, preview_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("合併兩筆資料")
        self.resize(720, 420)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "系統會保留第一筆勾選資料，將第二筆缺少的資訊、標籤、案件、附件、自訂欄位、聯絡紀錄與追蹤提醒合併過來，然後刪除第二筆。"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addWidget(QLabel(f"保留：{primary_label}"))
        layout.addWidget(QLabel(f"合併後刪除：{secondary_label}"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlainText("\n".join(preview_lines))
        layout.addWidget(self.preview, 1)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        merge_button = QPushButton("確認合併")
        merge_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(merge_button)
        layout.addLayout(buttons)


class HealthCheckDialog(QDialog):
    def __init__(self, checks, parent=None):
        super().__init__(parent)
        self.checks = list(checks)
        self.setWindowTitle("系統健康檢查")
        self.resize(760, 480)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["狀態", "項目", "說明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("這裡只做讀取檢查，不會修改資料。"))
        layout.addWidget(self.table, 1)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.checks))
        for row_number, check in enumerate(self.checks):
            _set_row_values(
                self.table,
                row_number,
                [
                    check.get("status", ""),
                    check.get("title", ""),
                    check.get("detail", ""),
                ],
            )
        self.table.resizeRowsToContents()
