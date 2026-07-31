"""Reusable desktop widgets for owner-related people management."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from customer_domain import mask_identity_text, normalize_taiwan_identity
from customer_owner_contact_types import RELATIONSHIP_TYPES


def _text(value):
    return str(value or "").strip()


def _relation_label(row):
    relationship = _text(row.get("relationship_type"))
    supplement = _text(row.get("relationship_note"))
    return f"{relationship}（{supplement}）" if supplement else relationship


def phone_choices(row):
    choices = []
    if _text(row.get("mobile_phone")):
        choices.append(("手機", _text(row.get("mobile_phone"))))
    if _text(row.get("home_phone")):
        choices.append(("市話", _text(row.get("home_phone"))))
    return choices


def address_choices(row):
    choices = []
    for label, key in (
        ("聯絡地址", "contact_address"),
        ("戶籍地址", "registered_address"),
        ("工作地址", "work_address"),
    ):
        if _text(row.get(key)):
            choices.append((label, _text(row.get(key))))
    return choices


class ContactChoiceTable(QTableWidget):
    """Search-result table shared by linking and duplicate selection."""

    HEADERS = (
        "姓名",
        "手機",
        "市話",
        "戶籍地址",
        "聯絡地址",
        "已關聯地主數",
    )

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def set_contacts(self, rows):
        self.setRowCount(0)
        for row_data in rows:
            row = self.rowCount()
            self.insertRow(row)
            values = (
                row_data.get("name"),
                row_data.get("mobile_phone"),
                row_data.get("home_phone"),
                row_data.get("registered_address"),
                row_data.get("contact_address"),
                row_data.get("owner_count") or 0,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(_text(value))
                if column == 0:
                    item.setData(Qt.UserRole, dict(row_data))
                if column in {3, 4}:
                    item.setToolTip(_text(value))
                self.setItem(row, column, item)
        self.resizeColumnsToContents()
        for column in (3, 4):
            self.setColumnWidth(column, min(self.columnWidth(column), 240))

    def selected_contact(self):
        row = self.currentRow()
        if row < 0 or self.item(row, 0) is None:
            return None
        return dict(self.item(row, 0).data(Qt.UserRole) or {})


class ExistingContactPickerDialog(QDialog):
    def __init__(self, contacts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("選擇既有關係人")
        self.resize(760, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("請選擇要沿用的既有關係人；系統不會自動合併資料。")
        )
        self.table = ContactChoiceTable(self)
        self.table.set_contacts(contacts)
        if self.table.rowCount():
            self.table.selectRow(0)
        self.table.doubleClicked.connect(lambda _index: self.accept())
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.Ok).setText("使用選取資料")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_selected(self):
        if self.table.selected_contact() is None:
            QMessageBox.warning(self, "尚未選取", "請先選取一位既有關係人。")
            return
        self.accept()

    def selected_contact(self):
        return self.table.selected_contact()


class DeactivateRelationDialog(QDialog):
    def __init__(self, contact_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("確認停用關係")
        self.resize(500, 300)
        layout = QVBoxLayout(self)
        message = QLabel(
            (
                f"確定要停用「{_text(contact_name)}」與目前地主的關係嗎？\n\n"
                "資料不會刪除，也不會影響此人與其他地主的關係。"
            ),
            self,
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addWidget(QLabel("停用說明（可留空）", self))
        self.reason_input = QPlainTextEdit(self)
        self.reason_input.setPlaceholderText(
            "例如：資料重複、不再協助地主、電話與地址皆無效"
        )
        self.reason_input.setMaximumHeight(100)
        layout.addWidget(self.reason_input)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.Ok).setText("確認停用")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reason(self):
        return self.reason_input.toPlainText().strip()


class OwnerContactDialog(QDialog):
    """Create/link/edit/read-only dialog with contact and relation separation."""

    def __init__(
        self,
        repository,
        record_id,
        *,
        existing=None,
        next_sort_order=10,
        readonly=False,
        allow_edit=False,
        owner_address="",
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.record_id = int(record_id)
        self.existing = dict(existing or {})
        self.readonly = bool(readonly)
        self.allow_edit = bool(allow_edit)
        self.owner_address = _text(owner_address)
        self.is_edit = bool(existing)
        self._selected_contact = None
        self.edit_requested = False
        self._address_helper_buttons = []
        self._identity_state = {}
        self.setWindowTitle(
            "查看關係人"
            if self.readonly
            else ("編輯關係人" if self.is_edit else "新增關係人")
        )
        self.resize(720, 700)

        layout = QVBoxLayout(self)
        if self.is_edit:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            content = QWidget(scroll)
            content_layout = QVBoxLayout(content)
            self._build_edit_content(content_layout)
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)
        else:
            self.mode_tabs = QTabWidget(self)
            self.mode_tabs.addTab(self._build_new_contact_page(), "建立新關係人")
            self.mode_tabs.addTab(self._build_existing_contact_page(), "選擇既有關係人")
            layout.addWidget(self.mode_tabs, 1)

        buttons = QDialogButtonBox(parent=self)
        if self.readonly:
            if self.allow_edit:
                edit_button = buttons.addButton(
                    "編輯", QDialogButtonBox.AcceptRole
                )
                edit_button.clicked.connect(self._request_edit)
            close_button = buttons.addButton("關閉", QDialogButtonBox.RejectRole)
            close_button.clicked.connect(self.reject)
        else:
            save_button = buttons.addButton("儲存", QDialogButtonBox.AcceptRole)
            cancel_button = buttons.addButton("取消", QDialogButtonBox.RejectRole)
            save_button.clicked.connect(self._validate_and_accept)
            cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        if self.is_edit:
            self._fill_existing(self.existing)
        else:
            self.new_sort_order.setValue(int(next_sort_order))
            self.link_sort_order.setValue(int(next_sort_order))
        if self.readonly:
            self._set_readonly()

    def _request_edit(self):
        self.edit_requested = True
        self.accept()

    def _contact_group(self, prefix, *, title="關係人共用資料"):
        group = QGroupBox(title, self)
        form = QFormLayout(group)
        name = QLineEdit(group)
        external_id = QLineEdit(group)
        external_id.setMaxLength(100)
        mobile = QLineEdit(group)
        home = QLineEdit(group)
        registered_address = QLineEdit(group)
        contact_address = QLineEdit(group)
        work_address = QLineEdit(group)
        identity_note = QLineEdit(group)
        notes = QPlainTextEdit(group)
        notes.setFixedHeight(80)
        form.addRow("姓名 *", name)
        identity_row = QHBoxLayout()
        identity_row.addWidget(external_id, 1)
        identity_button = QPushButton(
            "👁 顯示" if prefix == "edit" else "👁 隱藏", group
        )
        identity_row.addWidget(identity_button)
        form.addRow("身分證字號", identity_row)
        form.addRow("手機", mobile)
        form.addRow("市話", home)
        form.addRow("戶籍地址", registered_address)
        form.addRow("聯絡地址", contact_address)
        form.addRow("工作地址", work_address)
        form.addRow("身分補充", identity_note)
        form.addRow("人員備註", notes)
        helpers = QHBoxLayout()
        owner_address_button = QPushButton("戶籍地址同地主", group)
        owner_address_button.setEnabled(bool(self.owner_address))
        owner_address_button.clicked.connect(
            lambda: registered_address.setText(self.owner_address)
        )
        contact_same_button = QPushButton("聯絡地址同戶籍地址", group)
        contact_same_button.clicked.connect(
            lambda: contact_address.setText(registered_address.text().strip())
        )
        work_same_button = QPushButton("工作地址同聯絡地址", group)
        work_same_button.clicked.connect(
            lambda: work_address.setText(contact_address.text().strip())
        )
        for button in (
            owner_address_button,
            contact_same_button,
            work_same_button,
        ):
            helpers.addWidget(button)
            self._address_helper_buttons.append(button)
        helpers.addStretch(1)
        form.addRow("快速填入", helpers)
        setattr(self, f"{prefix}_name", name)
        setattr(self, f"{prefix}_external_id", external_id)
        setattr(self, f"{prefix}_external_id_button", identity_button)
        setattr(self, f"{prefix}_mobile_phone", mobile)
        setattr(self, f"{prefix}_home_phone", home)
        setattr(self, f"{prefix}_registered_address", registered_address)
        setattr(self, f"{prefix}_contact_address", contact_address)
        setattr(self, f"{prefix}_work_address", work_address)
        setattr(self, f"{prefix}_identity_note", identity_note)
        setattr(self, f"{prefix}_contact_notes", notes)
        self._identity_state[prefix] = {
            "dirty": False,
            "revealed": prefix != "edit",
            "masked": "",
            "pending": "",
        }
        external_id.textEdited.connect(
            lambda text, field_prefix=prefix: self._identity_text_edited(
                field_prefix, text
            )
        )
        identity_button.clicked.connect(
            lambda _checked=False, field_prefix=prefix: self._toggle_identity(
                field_prefix
            )
        )
        return group

    def _set_identity_text(self, prefix, value):
        widget = getattr(self, f"{prefix}_external_id")
        widget.blockSignals(True)
        widget.setText(_text(value))
        widget.blockSignals(False)

    def _identity_text_edited(self, prefix, value):
        normalized = _text(value).upper()
        if normalized != value:
            self._set_identity_text(prefix, normalized)
        state = self._identity_state[prefix]
        state["dirty"] = True
        state["pending"] = normalized

    def _toggle_identity(self, prefix):
        state = self._identity_state[prefix]
        button = getattr(self, f"{prefix}_external_id_button")
        widget = getattr(self, f"{prefix}_external_id")
        if state["revealed"]:
            plain = _text(widget.text()).upper()
            if state["dirty"] or prefix != "edit":
                state["pending"] = plain
            self._set_identity_text(prefix, mask_identity_text(plain))
            state["revealed"] = False
            button.setText("👁 顯示")
            return
        if state["dirty"] or prefix != "edit":
            plain = state["pending"]
        else:
            relation_id = int(self.existing.get("relation_id") or 0)
            try:
                plain = self.repository.reveal_owner_contact_identity(
                    self.record_id, relation_id
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "顯示失敗",
                    f"無法顯示完整身分證字號：{exc}",
                )
                return
        self._set_identity_text(prefix, plain)
        state["revealed"] = True
        button.setText("👁 隱藏")

    def _relation_group(self, prefix, *, title="與目前地主的關係"):
        group = QGroupBox(title, self)
        form = QFormLayout(group)
        relationship = QComboBox(group)
        relationship.addItems(RELATIONSHIP_TYPES)
        supplement = QLineEdit(group)
        supplement.setPlaceholderText("選擇「其他」時必填")
        primary = QCheckBox("設為主要關係人", group)
        sort_order = QSpinBox(group)
        sort_order.setRange(0, 1_000_000)
        relation_notes = QPlainTextEdit(group)
        relation_notes.setFixedHeight(80)
        form.addRow("關係類型 *", relationship)
        form.addRow("關係補充", supplement)
        form.addRow("", primary)
        form.addRow("排序", sort_order)
        form.addRow("關係備註", relation_notes)
        relationship.currentTextChanged.connect(
            lambda value: supplement.setPlaceholderText(
                "必填" if value == "其他" else "可選填"
            )
        )
        setattr(self, f"{prefix}_relationship_type", relationship)
        setattr(self, f"{prefix}_relationship_note", supplement)
        setattr(self, f"{prefix}_is_primary", primary)
        setattr(self, f"{prefix}_sort_order", sort_order)
        setattr(self, f"{prefix}_relation_notes", relation_notes)
        return group

    def _build_new_contact_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self._contact_group("new"))
        content_layout.addWidget(self._relation_group("new"))
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        return page

    def _build_existing_contact_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        search_row = QHBoxLayout()
        self.search_input = QLineEdit(page)
        self.search_input.setPlaceholderText(
            "輸入姓名、手機、市話、戶籍地址或聯絡地址"
        )
        self.search_input.returnPressed.connect(self._search_contacts)
        search_button = QPushButton("搜尋", page)
        search_button.clicked.connect(self._search_contacts)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)
        self.search_table = ContactChoiceTable(page)
        self.search_table.itemSelectionChanged.connect(self._sync_selected_contact)
        layout.addWidget(self.search_table, 1)
        layout.addWidget(self._relation_group("link"))
        return page

    def _build_edit_content(self, layout):
        shared_notice = QLabel(
            "此區資料由多位地主共用。修改後，所有連結到此關係人的地主都會同步更新。",
            self,
        )
        shared_notice.setWordWrap(True)
        shared_notice.setStyleSheet(
            "background:#3b2f16;color:#fde68a;border:1px solid #92400e;"
            "border-radius:5px;padding:8px;"
        )
        layout.addWidget(shared_notice)
        owner_count = int(self.existing.get("owner_count") or 0)
        if owner_count > 1:
            count_label = QLabel(f"目前已連結 {owner_count} 位地主。", self)
            count_label.setStyleSheet("color:#fbbf24;font-weight:600;")
            layout.addWidget(count_label)
        layout.addWidget(self._contact_group("edit"))
        relation_notice = QLabel("此區修改只會影響目前地主。", self)
        relation_notice.setStyleSheet("color:#93c5fd;padding-top:4px;")
        layout.addWidget(relation_notice)
        layout.addWidget(self._relation_group("edit"))
        if self.readonly:
            status = "啟用" if self.existing.get("is_active") else "已停用"
            updated_at = _text(
                self.existing.get("updated_at")
                or self.existing.get("relation_updated_at")
            )
            detail_meta = QLabel(
                f"資料狀態：{status}\n最後更新時間：{updated_at or '無'}",
                self,
            )
            detail_meta.setWordWrap(True)
            layout.addWidget(detail_meta)
        layout.addStretch(1)

    def _search_contacts(self):
        query = self.search_input.text().strip()
        if not query:
            self.search_table.set_contacts([])
            QMessageBox.information(
                self,
                "請輸入搜尋條件",
                "請輸入姓名、手機、市話、戶籍地址或聯絡地址。",
            )
            return
        try:
            rows = self.repository.search_owner_contacts(query, limit=50)
        except Exception as exc:
            QMessageBox.warning(self, "搜尋失敗", f"無法搜尋既有關係人：{exc}")
            return
        self.search_table.set_contacts(rows)
        if not rows:
            QMessageBox.information(self, "沒有結果", "找不到符合條件的關係人。")

    def _sync_selected_contact(self):
        self._selected_contact = self.search_table.selected_contact()

    def _fill_existing(self, values):
        self.edit_name.setText(_text(values.get("name")))
        masked_external_id = _text(values.get("external_id"))
        self._set_identity_text("edit", masked_external_id)
        self._identity_state["edit"].update(
            {
                "dirty": False,
                "revealed": False,
                "masked": masked_external_id,
                "pending": "",
            }
        )
        self.edit_mobile_phone.setText(_text(values.get("mobile_phone")))
        self.edit_home_phone.setText(_text(values.get("home_phone")))
        self.edit_registered_address.setText(
            _text(values.get("registered_address"))
        )
        self.edit_contact_address.setText(_text(values.get("contact_address")))
        self.edit_work_address.setText(_text(values.get("work_address")))
        self.edit_identity_note.setText(_text(values.get("identity_note")))
        self.edit_contact_notes.setPlainText(_text(values.get("contact_notes")))
        relationship = _text(values.get("relationship_type"))
        index = self.edit_relationship_type.findText(relationship)
        if index >= 0:
            self.edit_relationship_type.setCurrentIndex(index)
        self.edit_relationship_note.setText(_text(values.get("relationship_note")))
        self.edit_is_primary.setChecked(bool(values.get("is_primary")))
        self.edit_sort_order.setValue(int(values.get("sort_order") or 0))
        self.edit_relation_notes.setPlainText(_text(values.get("relation_notes")))

    def _set_readonly(self):
        for widget_type in (
            QLineEdit,
            QPlainTextEdit,
            QComboBox,
            QCheckBox,
            QSpinBox,
        ):
            for widget in self.findChildren(widget_type):
                widget.setEnabled(False)
        for button in self._address_helper_buttons:
            button.setEnabled(False)
        for prefix in self._identity_state:
            getattr(self, f"{prefix}_external_id_button").setEnabled(
                bool(self.allow_edit)
            )

    def _contact_values(self, prefix):
        identity_state = self._identity_state[prefix]
        if prefix == "edit" and not identity_state["dirty"]:
            external_id = None
        elif identity_state["revealed"]:
            external_id = getattr(
                self, f"{prefix}_external_id"
            ).text().strip().upper()
        else:
            external_id = _text(identity_state["pending"]).upper()
        return {
            "name": getattr(self, f"{prefix}_name").text().strip(),
            "external_id": external_id,
            "mobile_phone": getattr(self, f"{prefix}_mobile_phone").text().strip(),
            "home_phone": getattr(self, f"{prefix}_home_phone").text().strip(),
            "registered_address": getattr(
                self, f"{prefix}_registered_address"
            ).text().strip(),
            "contact_address": getattr(
                self, f"{prefix}_contact_address"
            ).text().strip(),
            "work_address": getattr(
                self, f"{prefix}_work_address"
            ).text().strip(),
            "identity_note": getattr(
                self, f"{prefix}_identity_note"
            ).text().strip(),
            "notes": getattr(self, f"{prefix}_contact_notes").toPlainText().strip(),
        }

    def _relation_values(self, prefix):
        return {
            "relationship_type": getattr(
                self, f"{prefix}_relationship_type"
            ).currentText(),
            "relationship_note": getattr(
                self, f"{prefix}_relationship_note"
            ).text().strip(),
            "is_primary": getattr(self, f"{prefix}_is_primary").isChecked(),
            "sort_order": getattr(self, f"{prefix}_sort_order").value(),
            "notes": getattr(self, f"{prefix}_relation_notes").toPlainText().strip(),
        }

    def result_values(self):
        if self.is_edit:
            return {
                "mode": "edit",
                "contact": self._contact_values("edit"),
                "relation": self._relation_values("edit"),
                "expected_contact_updated_at": self.existing.get(
                    "contact_updated_at"
                ),
                "expected_relation_updated_at": self.existing.get(
                    "relation_updated_at"
                ),
            }
        if self.mode_tabs.currentIndex() == 1:
            return {
                "mode": "link",
                "contact_id": int((self._selected_contact or {}).get("id") or 0),
                "relation": self._relation_values("link"),
            }
        return {
            "mode": "new",
            "contact": self._contact_values("new"),
            "relation": self._relation_values("new"),
        }

    def _validate_and_accept(self):
        values = self.result_values()
        if values["mode"] == "link":
            if not values["contact_id"]:
                QMessageBox.warning(self, "尚未選取", "請先搜尋並選取既有關係人。")
                return
            relation = values["relation"]
        else:
            if not values["contact"]["name"]:
                QMessageBox.warning(self, "資料不完整", "姓名不可空白。")
                return
            limits = {
                "name": ("姓名", 100),
                "external_id": ("身分證字號", 10),
                "mobile_phone": ("手機", 30),
                "home_phone": ("市話", 30),
                "registered_address": ("戶籍地址", 500),
                "contact_address": ("聯絡地址", 500),
                "work_address": ("工作地址", 500),
                "identity_note": ("身分補充", 300),
                "notes": ("人員備註", 2000),
            }
            for key, (label, maximum) in limits.items():
                if len(values["contact"].get(key) or "") > maximum:
                    QMessageBox.warning(
                        self,
                        "內容過長",
                        f"{label}不可超過 {maximum} 個字。",
                    )
                    return
            try:
                values["contact"]["external_id"] = (
                    None
                    if values["contact"].get("external_id") is None
                    else normalize_taiwan_identity(
                        values["contact"].get("external_id")
                    )
                )
            except ValueError as exc:
                QMessageBox.warning(self, "格式錯誤", str(exc))
                return
            relation = values["relation"]
        if not relation["relationship_type"]:
            QMessageBox.warning(self, "資料不完整", "關係類型不可空白。")
            return
        if (
            relation["relationship_type"] == "其他"
            and not relation["relationship_note"]
        ):
            QMessageBox.warning(
                self, "資料不完整", "選擇「其他」時必須填寫關係補充。"
            )
            return
        if len(relation.get("relationship_note", "")) > 100:
            QMessageBox.warning(
                self, "內容過長", "關係補充不可超過 100 個字。"
            )
            return
        if len(relation.get("notes", "")) > 2000:
            QMessageBox.warning(
                self, "內容過長", "關係備註不可超過 2000 個字。"
            )
            return
        self.accept()


class OwnerContactsWidget(QWidget):
    HEADERS = (
        "主要",
        "姓名",
        "關係",
        "手機",
        "市話",
        "戶籍地址",
        "聯絡地址",
        "身分補充",
        "狀態",
    )

    def __init__(
        self,
        repository_provider,
        *,
        current_role="viewer",
        dialog_factory=OwnerContactDialog,
        parent=None,
    ):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.repository_provider = repository_provider
        self.current_role = _text(current_role).casefold() or "viewer"
        self.dialog_factory = dialog_factory
        self.record_id = None
        self.owner_label = ""
        self.rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.owner_label_widget = QLabel("請先選取地主", self)
        self.owner_label_widget.setStyleSheet("color:#dbeafe;font-weight:600;")
        layout.addWidget(self.owner_label_widget)

        toolbar = QGridLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setHorizontalSpacing(6)
        toolbar.setVerticalSpacing(6)
        self.add_button = QPushButton("新增", self)
        self.edit_button = QPushButton(
            "查看" if self.current_role == "viewer" else "編輯", self
        )
        self.deactivate_button = QPushButton("停用", self)
        self.reactivate_button = QPushButton("重新啟用", self)
        self.copy_phone_button = QPushButton("複製電話", self)
        self.copy_address_button = QPushButton("複製地址", self)
        self.refresh_button = QPushButton("重新整理", self)
        self.show_inactive = QCheckBox("顯示已停用", self)
        toolbar_buttons = (
            self.add_button,
            self.edit_button,
            self.deactivate_button,
            self.reactivate_button,
            self.copy_phone_button,
            self.copy_address_button,
            self.refresh_button,
        )
        for position, button in enumerate(toolbar_buttons):
            row, column = divmod(position, 4)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            toolbar.addWidget(button, row, column)
        self.show_inactive.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        toolbar.addWidget(self.show_inactive, 1, 3)
        for column in range(4):
            toolbar.setColumnStretch(column, 1)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _index: self.view_selected())
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#9ca3af;")
        layout.addWidget(self.status_label)

        self.add_button.clicked.connect(self.add_contact)
        self.edit_button.clicked.connect(self.edit_selected)
        self.deactivate_button.clicked.connect(self.deactivate_selected)
        self.reactivate_button.clicked.connect(self.reactivate_selected)
        self.copy_phone_button.clicked.connect(self.copy_selected_phone)
        self.copy_address_button.clicked.connect(self.copy_selected_address)
        self.refresh_button.clicked.connect(self.refresh)
        self.show_inactive.toggled.connect(lambda _checked: self.refresh())
        self._update_buttons()

    @property
    def can_write(self):
        return self.current_role in {"admin", "editor"}

    def repository(self):
        return (
            self.repository_provider()
            if callable(self.repository_provider)
            else self.repository_provider
        )

    def set_record(self, record_id, owner_label=""):
        self.record_id = int(record_id) if record_id is not None else None
        self.owner_label = _text(owner_label)
        self.owner_label_widget.setText(
            f"目前地主：{self.owner_label or f'ID {self.record_id}'}"
            if self.record_id is not None
            else "請先選取地主"
        )
        self.refresh()

    def clear_owner(self):
        self.record_id = None
        self.owner_label = ""
        self.rows = []
        self.table.setRowCount(0)
        self.owner_label_widget.setText("請先選取地主")
        self.status_label.setText("沒有選取地主，關係人操作已停用。")
        self._update_buttons()

    def refresh(self):
        if self.record_id is None:
            self.clear_owner()
            return
        repository = self.repository()
        if not hasattr(repository, "list_owner_contacts"):
            self.rows = []
            self.table.setRowCount(0)
            self.status_label.setText("此功能需要連線至支援關係人管理的正式伺服器。")
            self._update_buttons()
            return
        try:
            self.rows = list(
                repository.list_owner_contacts(
                    self.record_id,
                    include_inactive=self.show_inactive.isChecked(),
                )
            )
        except Exception as exc:
            self.rows = []
            self.table.setRowCount(0)
            self.status_label.setText(f"關係人載入失敗：{exc}")
            self._update_buttons()
            return
        self._render_rows()
        self.status_label.setText(
            f"已載入 {len(self.rows)} 筆關係人資料。"
            if self.rows
            else "目前尚未建立關係人資料。"
        )

    def _render_rows(self):
        self.table.setRowCount(0)
        for row_data in self.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            active = bool(row_data.get("is_active"))
            values = (
                "★" if row_data.get("is_primary") else "",
                row_data.get("name"),
                _relation_label(row_data),
                row_data.get("mobile_phone"),
                row_data.get("home_phone"),
                row_data.get("registered_address"),
                row_data.get("contact_address"),
                row_data.get("identity_note"),
                "啟用" if active else "已停用",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(_text(value))
                if column == 0:
                    item.setData(Qt.UserRole, dict(row_data))
                if column in {5, 6, 7}:
                    item.setToolTip(_text(value))
                if not active:
                    item.setForeground(QColor("#9ca3af"))
                    item.setBackground(QColor("#2d2d2d"))
                elif row_data.get("is_primary"):
                    item.setBackground(QColor("#374151"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        for column in (5, 6, 7):
            self.table.setColumnWidth(
                column, min(self.table.columnWidth(column), 260)
            )
        self._update_buttons()

    def selected_relation(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            return None
        return dict(self.table.item(row, 0).data(Qt.UserRole) or {})

    def _update_buttons(self):
        has_owner = self.record_id is not None
        selected = self.selected_relation()
        active = bool(selected and selected.get("is_active"))
        self.add_button.setEnabled(has_owner and self.can_write)
        self.refresh_button.setEnabled(has_owner)
        self.edit_button.setEnabled(bool(has_owner and selected))
        self.deactivate_button.setEnabled(
            bool(has_owner and self.can_write and selected and active)
        )
        self.reactivate_button.setEnabled(
            bool(has_owner and self.can_write and selected and not active)
        )
        self.copy_phone_button.setEnabled(
            bool(has_owner and selected and phone_choices(selected))
        )
        self.copy_address_button.setEnabled(
            bool(has_owner and selected and address_choices(selected))
        )

    def _next_sort_order(self):
        values = [int(row.get("sort_order") or 0) for row in self.rows]
        return (max(values) if values else 0) + 10

    def _owner_address(self):
        repository = self.repository()
        if self.record_id is None or not hasattr(repository, "get_customer"):
            return ""
        try:
            record = repository.get_customer(self.record_id) or {}
        except Exception:
            return ""
        return _text(record.get("address"))

    def add_contact(self):
        if not self.can_write or self.record_id is None:
            return
        repository = self.repository()
        dialog = self.dialog_factory(
            repository,
            self.record_id,
            next_sort_order=self._next_sort_order(),
            owner_address=self._owner_address(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_values()
        try:
            if values["mode"] == "link":
                repository.link_owner_contact(
                    self.record_id,
                    {
                        "contact_id": values["contact_id"],
                        "relation": values["relation"],
                    },
                )
            else:
                action = self._duplicate_action(values["contact"])
                if action is None:
                    return
                if isinstance(action, dict):
                    repository.link_owner_contact(
                        self.record_id,
                        {
                            "contact_id": int(action["id"]),
                            "relation": values["relation"],
                        },
                    )
                else:
                    repository.create_owner_contact(
                        self.record_id,
                        {
                            "contact": values["contact"],
                            "relation": values["relation"],
                        },
                    )
        except Exception as exc:
            QMessageBox.warning(self, "新增失敗", f"無法建立關係人：{exc}")
            return
        self.refresh()
        self.status_label.setText("關係人已新增。")

    def _duplicate_action(self, contact):
        repository = self.repository()
        duplicates = repository.find_owner_contact_duplicates(
            name=contact.get("name", ""),
            mobile=contact.get("mobile_phone", ""),
            home_phone=contact.get("home_phone", ""),
            registered_address=contact.get("registered_address", ""),
            contact_address=contact.get("contact_address", ""),
            limit=20,
        )
        if not duplicates:
            return True
        message = QMessageBox(self)
        message.setWindowTitle("發現可能重複的關係人")
        message.setIcon(QMessageBox.Warning)
        preview = "\n\n".join(
            (
                f"{_text(row.get('name'))}\n"
                f"手機：{_text(row.get('mobile_phone')) or '無'}　"
                f"市話：{_text(row.get('home_phone')) or '無'}\n"
                f"聯絡地址：{_text(row.get('contact_address')) or '無'}\n"
                f"判斷：{'、'.join(row.get('duplicate_reasons') or ['姓名相同'])}\n"
                f"已關聯地主：{int(row.get('owner_count') or 0)} 位"
            )
            for row in duplicates[:5]
        )
        message.setText(f"發現可能已存在的關係人：\n\n{preview}")
        use_existing = message.addButton("使用既有資料", QMessageBox.AcceptRole)
        create_anyway = message.addButton("仍建立新資料", QMessageBox.DestructiveRole)
        cancel = message.addButton("取消", QMessageBox.RejectRole)
        message.exec()
        clicked = message.clickedButton()
        if clicked == create_anyway:
            return True
        if clicked != use_existing or clicked == cancel:
            return None
        picker = ExistingContactPickerDialog(duplicates, self)
        if picker.exec() != QDialog.Accepted:
            return None
        return picker.selected_contact()

    def edit_selected(self):
        selected = self.selected_relation()
        if selected is None or self.record_id is None:
            return
        repository = self.repository()
        try:
            existing = repository.get_owner_contact(
                self.record_id, selected["relation_id"]
            )
        except Exception as exc:
            QMessageBox.warning(self, "載入失敗", f"無法載入關係人資料：{exc}")
            return
        self._open_edit_dialog(repository, existing, selected)

    def _open_edit_dialog(self, repository, existing, selected):
        dialog = self.dialog_factory(
            repository,
            self.record_id,
            existing=existing,
            owner_address=self._owner_address(),
            readonly=not self.can_write,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or not self.can_write:
            return
        values = dialog.result_values()
        try:
            repository.update_owner_contact(
                self.record_id,
                selected["relation_id"],
                {
                    "contact": values["contact"],
                    "relation": values["relation"],
                    "expected_contact_updated_at": values.get(
                        "expected_contact_updated_at"
                    ),
                    "expected_relation_updated_at": values.get(
                        "expected_relation_updated_at"
                    ),
                },
            )
        except Exception as exc:
            QMessageBox.warning(self, "儲存失敗", f"無法更新關係人：{exc}")
            return
        self.refresh()
        self.status_label.setText("關係人資料已更新。")

    def view_selected(self):
        selected = self.selected_relation()
        if selected is None or self.record_id is None:
            return
        repository = self.repository()
        try:
            existing = repository.get_owner_contact(
                self.record_id, selected["relation_id"]
            )
        except Exception as exc:
            QMessageBox.warning(self, "載入失敗", f"無法載入關係人資料：{exc}")
            return
        dialog = self.dialog_factory(
            repository,
            self.record_id,
            existing=existing,
            readonly=True,
            allow_edit=self.can_write,
            owner_address=self._owner_address(),
            parent=self,
        )
        result = dialog.exec()
        if (
            self.can_write
            and result == QDialog.Accepted
            and getattr(dialog, "edit_requested", False)
        ):
            self._open_edit_dialog(repository, existing, selected)

    def deactivate_selected(self):
        selected = self.selected_relation()
        if not self.can_write or not selected or not selected.get("is_active"):
            return
        dialog = DeactivateRelationDialog(selected.get("name"), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.repository().deactivate_owner_contact(
                self.record_id,
                selected["relation_id"],
                reason=dialog.reason(),
                expected_relation_updated_at=selected.get(
                    "relation_updated_at"
                ),
            )
        except Exception as exc:
            QMessageBox.warning(self, "停用失敗", f"無法停用關係：{exc}")
            return
        self.refresh()
        self.status_label.setText("關係已停用。")

    def reactivate_selected(self):
        selected = self.selected_relation()
        if not self.can_write or not selected or selected.get("is_active"):
            return
        answer = QMessageBox.question(
            self,
            "確認重新啟用",
            (
                f"確定要重新啟用「{_text(selected.get('name'))}」與目前地主的關係嗎？\n\n"
                "重新啟用後不會自動設為主要關係人。"
            ),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.repository().reactivate_owner_contact(
                self.record_id,
                selected["relation_id"],
                expected_relation_updated_at=selected.get(
                    "relation_updated_at"
                ),
            )
        except Exception as exc:
            QMessageBox.warning(self, "重新啟用失敗", f"無法重新啟用關係：{exc}")
            return
        self.refresh()
        self.status_label.setText("關係已重新啟用。")

    def _copy_choice(self, choices, button, action_prefix):
        if not choices:
            return False
        if len(choices) == 1:
            label, value = choices[0]
        else:
            menu = QMenu(self)
            actions = {}
            for choice_label, choice_value in choices:
                action = menu.addAction(f"{action_prefix}{choice_label}")
                actions[action] = (choice_label, choice_value)
            selected_action = menu.exec(
                button.mapToGlobal(button.rect().bottomLeft())
            )
            if selected_action not in actions:
                return False
            label, value = actions[selected_action]
        QApplication.clipboard().setText(value)
        self.status_label.setText(f"{label}已複製。")
        return True

    def copy_selected_phone(self):
        selected = self.selected_relation()
        if selected is None:
            return False
        return self._copy_choice(
            phone_choices(selected), self.copy_phone_button, "複製"
        )

    def copy_selected_address(self):
        selected = self.selected_relation()
        if selected is None:
            return False
        return self._copy_choice(
            address_choices(selected), self.copy_address_button, "複製"
        )
