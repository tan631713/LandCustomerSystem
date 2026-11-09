"""Additional management dialogs for cases, tags, attachments, templates, and health checks."""

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDateEdit,
    QFileDialog,
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
    QWidget,
)

from qfluentwidgets import CheckBox as FluentCheckBox
from qfluentwidgets import ComboBox as FluentComboBox
from qfluentwidgets import LineEdit as FluentLineEdit
from customer_desktop import open_path_or_web_url
from customer_responsive_dialog import ResponsiveDialog as QDialog
from customer_ui_loader import chain_tab_order, find_child, install_ui, size_like_unparented
from customer_tag_display import tag_text_qcolor


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


class CaseSelectDialog(QDialog):
    # Layout: ui/dialogs/case_select_dialog.ui (title and 加入 text vary by caller).
    ui_file = "dialogs/case_select_dialog.ui"
    ui_object_names = ("promptLabel", "caseCombo", "cancelButton", "okButton")

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
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.setWindowTitle(dialog_title)
        self.case_combo = find_child(content, "caseCombo", FluentComboBox)
        for case in self.cases:
            self.case_combo.addItem(
                f"{case.get('title')} ({case.get('status') or '進行中'})",
                userData=case.get("id"),
            )

        find_child(content, "promptLabel", QLabel).setText(
            f"將對 {selected_count} 筆資料執行「{action_text}」："
        )
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        ok_button = find_child(content, "okButton", QPushButton)
        ok_button.setText(action_text)
        ok_button.clicked.connect(self.accept)

    def selected_case_id(self):
        return self.case_combo.currentData()


class FieldVisitScheduleDialog(QDialog):
    # Layout: ui/dialogs/field_visit_schedule_dialog.ui.
    ui_file = "dialogs/field_visit_schedule_dialog.ui"
    ui_object_names = (
        "promptLabel",
        "dateEdit",
        "titleEdit",
        "priorityCheckBox",
        "cancelButton",
        "submitButton",
    )

    def __init__(self, selected_count=0, parent=None):
        super().__init__(parent)
        content = install_ui(self, self.ui_file, self.ui_object_names)

        self.date_edit = find_child(content, "dateEdit", QDateEdit)
        self.date_edit.setDate(QDate.currentDate())
        self.title_edit = find_child(content, "titleEdit", QLineEdit)
        self.priority_checkbox = find_child(content, "priorityCheckBox", QCheckBox)

        find_child(content, "promptLabel", QLabel).setText(
            f"將 {int(selected_count)} 筆已選資料加入拜訪行程："
        )
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "submitButton", QPushButton).clicked.connect(self.accept)

    def selected_date(self):
        return self.date_edit.date().toString("yyyy-MM-dd")

    def title(self):
        return self.title_edit.text().strip() or "今日拜訪行程"

    def priority(self):
        return 100 if self.priority_checkbox.isChecked() else 0


class TagManagementDialog(QDialog):
    # Layout: ui/dialogs/tag_management_dialog.ui.
    ui_file = "dialogs/tag_management_dialog.ui"
    ui_object_names = (
        "tagsTable",
        "nameEdit",
        "colorEdit",
        "colorButton",
        "newButton",
        "viewButton",
        "deleteButton",
        "closeButton",
        "saveButton",
    )

    def __init__(self, tags, parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        self.action = None
        self.current_tag_id = None
        self.selected_tag = None
        self.edit_mode = False
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "tagsTable", QTableWidget)
        self.table.itemSelectionChanged.connect(self.load_current_tag)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.name_edit = find_child(content, "nameEdit", QLineEdit)
        self.color_edit = find_child(content, "colorEdit", QLineEdit)
        self.color_button = find_child(content, "colorButton", QPushButton)
        self.color_button.clicked.connect(self.choose_color)

        self.new_button = find_child(content, "newButton", QPushButton)
        self.new_button.clicked.connect(self.begin_new_tag)
        self.save_button = find_child(content, "saveButton", QPushButton)
        self.save_button.clicked.connect(self.request_save)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.request_delete)
        find_child(content, "viewButton", QPushButton).clicked.connect(self.request_view)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)
        self.load_rows()

    def load_rows(self):
        previous = self.table.blockSignals(True)
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
                    tag_text_qcolor(color.name())
                )
        self.table.blockSignals(previous)
        self.begin_new_tag()

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
        if not self.edit_mode:
            return None
        return self.current_tag_id

    def load_current_tag(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.current_tag_id = None
            self.selected_tag = None
            self.edit_mode = False
            self.save_button.setText("新增標籤")
            return
        row_number = selected_rows[0].row()
        tag_id = _row_id(self.table, row_number)
        for tag in self.tags:
            if tag.get("id") == tag_id:
                self.current_tag_id = tag_id
                self.selected_tag = dict(tag)
                self.edit_mode = True
                self.name_edit.setText(tag.get("name") or "")
                self.color_edit.setText(tag.get("color") or "")
                self.save_button.setText("儲存修改")
                return
        self.current_tag_id = None
        self.selected_tag = None
        self.edit_mode = False
        self.save_button.setText("新增標籤")

    def begin_new_tag(self):
        previous = self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(previous)
        self.current_tag_id = None
        self.selected_tag = None
        self.edit_mode = False
        self.name_edit.clear()
        self.color_edit.clear()
        self.save_button.setText("新增標籤")

    def clear_form(self):
        self.begin_new_tag()

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
        self.action = (
            "update"
            if self.edit_mode and self.current_tag_id is not None
            else "create"
        )
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
    # Layout: ui/dialogs/customer_tags_dialog.ui.
    ui_file = "dialogs/customer_tags_dialog.ui"
    ui_object_names = ("promptLabel", "tagsList", "cancelButton", "saveButton")

    def __init__(self, tags, selected_tag_ids=None, record_label="", parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        self.selected_tag_ids = set(selected_tag_ids or [])
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.list_widget = find_child(content, "tagsList", QListWidget)
        for tag in self.tags:
            item = QListWidgetItem(tag.get("name") or "")
            item.setData(Qt.UserRole, tag.get("id"))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tag.get("id") in self.selected_tag_ids else Qt.Unchecked)
            color = QColor(str(tag.get("color") or ""))
            if color.isValid():
                item.setBackground(color)
                item.setForeground(
                    tag_text_qcolor(color.name())
                )
            self.list_widget.addItem(item)

        if record_label:
            find_child(content, "promptLabel", QLabel).setText(record_label)
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "saveButton", QPushButton).clicked.connect(self.accept)

    def selected_ids(self):
        ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids


class BatchCustomerTagsDialog(QDialog):
    # Layout: ui/dialogs/batch_customer_tags_dialog.ui.
    ui_file = "dialogs/batch_customer_tags_dialog.ui"
    ui_object_names = ("titleLabel", "modeCombo", "tagsList", "cancelButton", "applyButton")

    def __init__(self, tags, selected_count=0, parent=None):
        super().__init__(parent)
        self.tags = [dict(row) for row in tags]
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.mode_combo = find_child(content, "modeCombo", FluentComboBox)
        self.mode_combo.addItem("加入所選標籤（保留原有）", userData="add")
        self.mode_combo.addItem("移除所選標籤", userData="remove")
        self.mode_combo.addItem("完全取代原有標籤", userData="replace")
        self.list_widget = find_child(content, "tagsList", QListWidget)
        for tag in self.tags:
            item = QListWidgetItem(tag.get("name") or "")
            item.setData(Qt.UserRole, tag.get("id"))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            color = QColor(str(tag.get("color") or ""))
            if color.isValid():
                item.setBackground(color)
                item.setForeground(
                    tag_text_qcolor(color.name())
                )
            self.list_widget.addItem(item)

        find_child(content, "titleLabel", QLabel).setText(
            f"將處理 {selected_count} 筆選取或勾選資料。"
        )
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "applyButton", QPushButton).clicked.connect(self.request_apply)

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
    # Layout: ui/dialogs/attachment_dialog.ui.
    ui_file = "dialogs/attachment_dialog.ui"
    ui_object_names = (
        "titleLabel",
        "attachmentsTable",
        "pathEdit",
        "browseButton",
        "descriptionEdit",
        "managedCheckBox",
        "openButton",
        "deleteButton",
        "closeButton",
        "addButton",
    )

    def __init__(
        self, attachments, record_label="", parent=None, *, open_attachment=None
    ):
        super().__init__(parent)
        self.attachments = [dict(row) for row in attachments]
        self.open_attachment = open_attachment
        self.action = None
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "attachmentsTable", QTableWidget)
        self.table.itemDoubleClicked.connect(self.open_selected_file)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.path_edit = find_child(content, "pathEdit", QLineEdit)
        self.description_edit = find_child(content, "descriptionEdit", QLineEdit)
        self.managed_checkbox = find_child(content, "managedCheckBox", QCheckBox)

        if record_label:
            find_child(content, "titleLabel", QLabel).setText(record_label)
        find_child(content, "browseButton", QPushButton).clicked.connect(self.browse_file)
        find_child(content, "addButton", QPushButton).clicked.connect(self.request_add)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.request_delete)
        find_child(content, "openButton", QPushButton).clicked.connect(self.open_selected_file)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)
        self.load_rows()

    def load_rows(self):
        self.table.setRowCount(len(self.attachments))
        for row_number, attachment in enumerate(self.attachments):
            display_path = (
                attachment.get("original_name")
                if attachment.get("status") != "external"
                else attachment.get("file_path")
            ) or attachment.get("file_path")
            _set_row_values(
                self.table,
                row_number,
                [
                    attachment.get("id"),
                    display_path,
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
        attachment = self.selected_attachment()
        return "" if attachment is None else str(attachment.get("file_path") or "")

    def selected_attachment(self):
        attachment_id = self.selected_attachment_id()
        if attachment_id is None:
            return None
        return next(
            (
                attachment
                for attachment in self.attachments
                if int(attachment.get("id")) == int(attachment_id)
            ),
            None,
        )

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
        attachment = self.selected_attachment()
        if attachment is None:
            QMessageBox.information(self, "未選取附件", "請先選取要開啟的附件。")
            return
        if self.open_attachment is not None:
            self.open_attachment(dict(attachment))
            return
        file_path = str(attachment.get("file_path") or "")
        if not file_path:
            QMessageBox.warning(self, "附件資料不完整", "這個附件沒有可開啟的路徑。")
            return
        open_path_or_web_url(file_path, self, item_label="附件")


class CustomFieldManagementDialog(QDialog):
    # Layout: ui/dialogs/custom_field_management_dialog.ui.
    ui_file = "dialogs/custom_field_management_dialog.ui"
    ui_object_names = (
        "fieldsTable",
        "labelEdit",
        "keyEdit",
        "clearButton",
        "deleteButton",
        "closeButton",
        "saveButton",
    )

    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.action = None
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "fieldsTable", QTableWidget)
        self.table.itemSelectionChanged.connect(self.load_current_field)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.key_edit = find_child(content, "keyEdit", QLineEdit)
        self.label_edit = find_child(content, "labelEdit", QLineEdit)

        find_child(content, "clearButton", QPushButton).clicked.connect(self.clear_form)
        find_child(content, "saveButton", QPushButton).clicked.connect(self.request_save)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.request_delete)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)
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
    # Layout: ui/dialogs/customer_custom_values_dialog.ui; one row per custom
    # field (they come from the database) is added to customFieldsContainer.
    ui_file = "dialogs/customer_custom_values_dialog.ui"
    ui_object_names = ("titleLabel", "customFieldsContainer", "cancelButton", "saveButton")

    def __init__(self, fields, values=None, record_label="", parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.values = dict(values or {})
        self.edits = {}
        content = install_ui(self, self.ui_file, self.ui_object_names)
        if record_label:
            find_child(content, "titleLabel", QLabel).setText(record_label)
        fields_container = find_child(content, "customFieldsContainer", QWidget)
        form = fields_container.layout()
        for row_number, field in enumerate(self.fields):
            edit = FluentLineEdit()
            edit.setText(str(self.values.get(field.get("id")) or ""))
            self.edits[field.get("id")] = edit
            form.addWidget(QLabel(field.get("label") or field.get("field_key")), row_number, 0)
            form.addWidget(edit, row_number, 1)
        cancel_button = find_child(content, "cancelButton", QPushButton)
        cancel_button.clicked.connect(self.reject)
        save_button = find_child(content, "saveButton", QPushButton)
        save_button.clicked.connect(self.accept)
        chain_tab_order([*self.edits.values(), cancel_button, save_button], after=fields_container)

    def result_values(self):
        return {
            field_id: edit.text().strip()
            for field_id, edit in self.edits.items()
        }


class BatchCustomerCustomValuesDialog(QDialog):
    # Layout: ui/dialogs/batch_customer_custom_values_dialog.ui; one check box
    # and box per custom field is added to customFieldsContainer here.
    ui_file = "dialogs/batch_customer_custom_values_dialog.ui"
    ui_object_names = ("titleLabel", "customFieldsContainer", "cancelButton", "applyButton")

    def __init__(self, fields, selected_count=0, parent=None):
        super().__init__(parent)
        self.fields = [dict(row) for row in fields]
        self.rows = {}
        content = install_ui(self, self.ui_file, self.ui_object_names)
        find_child(content, "titleLabel", QLabel).setText(
            f"將處理 {selected_count} 筆資料。只會修改已勾選的欄位；勾選後留空代表清除該欄位。"
        )
        fields_container = find_child(content, "customFieldsContainer", QWidget)
        form = fields_container.layout()
        for row_number, field in enumerate(self.fields):
            checkbox = FluentCheckBox(field.get("label") or field.get("field_key"))
            edit = FluentLineEdit()
            edit.setEnabled(False)
            checkbox.toggled.connect(edit.setEnabled)
            field_id = field.get("id")
            self.rows[field_id] = (checkbox, edit)
            form.addWidget(checkbox, row_number, 0)
            form.addWidget(edit, row_number, 1)
        cancel_button = find_child(content, "cancelButton", QPushButton)
        cancel_button.clicked.connect(self.reject)
        apply_button = find_child(content, "applyButton", QPushButton)
        apply_button.clicked.connect(self.request_apply)
        chain_tab_order([
            *(widget for pair in self.rows.values() for widget in pair),
            cancel_button,
            apply_button,
        ], after=fields_container)

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

    # Layout: ui/dialogs/text_template_dialog.ui.
    ui_file = "dialogs/text_template_dialog.ui"
    ui_object_names = (
        "templatesTable",
        "typeCombo",
        "titleEdit",
        "contentEdit",
        "clearButton",
        "deleteButton",
        "closeButton",
        "saveButton",
    )

    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.templates = [dict(row) for row in templates]
        self.action = None
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "templatesTable", QTableWidget)
        self.table.itemSelectionChanged.connect(self.load_current_template)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.type_combo = find_child(content, "typeCombo", FluentComboBox)
        for value, label in self.TEMPLATE_TYPES:
            self.type_combo.addItem(label, userData=value)
        self.title_edit = find_child(content, "titleEdit", QLineEdit)
        self.content_edit = find_child(content, "contentEdit", QPlainTextEdit)

        find_child(content, "clearButton", QPushButton).clicked.connect(self.clear_form)
        find_child(content, "saveButton", QPushButton).clicked.connect(self.request_save)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.request_delete)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)
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
    # Layout: ui/dialogs/apply_template_dialog.ui.
    ui_file = "dialogs/apply_template_dialog.ui"
    ui_object_names = ("targetCombo", "templateCombo", "cancelButton", "applyButton")

    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.templates = [dict(row) for row in templates]
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.target_combo = find_child(content, "targetCombo", FluentComboBox)
        self.target_combo.addItem("備註", userData="note")
        self.target_combo.addItem("出訪記錄", userData="visit_log")
        self.template_combo = find_child(content, "templateCombo", FluentComboBox)
        for template in self.templates:
            target = "備註" if template.get("template_type") == "note" else "出訪記錄"
            self.template_combo.addItem(
                f"[{target}] {template.get('title')}", userData=template.get("id")
            )

        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "applyButton", QPushButton).clicked.connect(self.accept)

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
    # Layout: ui/dialogs/contact_log_dialog.ui.
    ui_file = "dialogs/contact_log_dialog.ui"
    ui_object_names = (
        "titleLabel",
        "logsTable",
        "dateEdit",
        "methodEdit",
        "resultEdit",
        "nextEdit",
        "noteEdit",
        "deleteButton",
        "closeButton",
        "addButton",
    )

    def __init__(self, logs, record_label="", parent=None):
        super().__init__(parent)
        self.logs = [dict(row) for row in logs]
        self.action = None
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "logsTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.date_edit = find_child(content, "dateEdit", QLineEdit)
        self.method_edit = find_child(content, "methodEdit", QLineEdit)
        self.result_edit = find_child(content, "resultEdit", QLineEdit)
        self.next_edit = find_child(content, "nextEdit", QLineEdit)
        self.note_edit = find_child(content, "noteEdit", QPlainTextEdit)

        if record_label:
            find_child(content, "titleLabel", QLabel).setText(record_label)
        find_child(content, "addButton", QPushButton).clicked.connect(self.request_add)
        find_child(content, "deleteButton", QPushButton).clicked.connect(self.request_delete)
        find_child(content, "closeButton", QPushButton).clicked.connect(self.reject)
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
    # Layout: ui/dialogs/merge_records_dialog.ui.
    ui_file = "dialogs/merge_records_dialog.ui"
    ui_object_names = (
        "primaryLabel",
        "secondaryLabel",
        "previewEdit",
        "cancelButton",
        "mergeButton",
    )

    def __init__(self, primary_label, secondary_label, preview_lines, parent=None):
        super().__init__(parent)
        content = install_ui(self, self.ui_file, self.ui_object_names)
        find_child(content, "primaryLabel", QLabel).setText(f"保留：{primary_label}")
        find_child(content, "secondaryLabel", QLabel).setText(
            f"合併後刪除：{secondary_label}"
        )
        self.preview = find_child(content, "previewEdit", QPlainTextEdit)
        self.preview.setPlainText("\n".join(preview_lines))
        find_child(content, "cancelButton", QPushButton).clicked.connect(self.reject)
        find_child(content, "mergeButton", QPushButton).clicked.connect(self.accept)


class HealthCheckDialog(QDialog):
    # Layout: ui/dialogs/health_check_dialog.ui.
    ui_file = "dialogs/health_check_dialog.ui"
    ui_object_names = ("checksTable", "closeButton")

    def __init__(self, checks, parent=None):
        super().__init__(parent)
        self.checks = list(checks)
        content = install_ui(self, self.ui_file, self.ui_object_names)
        self.table = find_child(content, "checksTable", QTableWidget)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        find_child(content, "closeButton", QPushButton).clicked.connect(self.accept)
        size_like_unparented(self.table)
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
