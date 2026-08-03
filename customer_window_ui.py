"""Desktop main-window layout, form, table, and menu construction."""

from customer_table_ui import build_customer_table_ui
from customer_owner_contacts import OwnerContactsWidget
from customer_version import full_version_text
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

MAIN_SPLITTER_SETTINGS_KEY = "desktop/main_splitter_sizes"
LAND_LIST_MINIMUM_WIDTH = 540
DETAIL_PANEL_MINIMUM_WIDTH = 460
DEFAULT_SPLITTER_SIZES = (760, 480)

# Modern dark, rounded look for buttons and input fields. Applied once to the
# central widget so it cascades to every QPushButton / QLineEdit /
# QPlainTextEdit / QComboBox underneath, without touching per-widget
# setStyleSheet calls used elsewhere for labels/titles.
CONTROL_STYLESHEET = """
QPushButton {
    background-color: #374151;
    color: #f9fafb;
    border: 1px solid #4b5563;
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #4b5563;
    border-color: #6b7280;
}
QPushButton:pressed {
    background-color: #1f2937;
}
QPushButton:disabled {
    background-color: #1f2937;
    color: #6b7280;
    border-color: #374151;
}

QLineEdit, QPlainTextEdit, QComboBox {
    background-color: #111827;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #365d8d;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QLineEdit:disabled, QComboBox:disabled {
    color: #6b7280;
    background-color: #1f2937;
    border-color: #374151;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: #111827;
    color: #f9fafb;
    border: 1px solid #374151;
    selection-background-color: #365d8d;
    outline: none;
}

QMenu {
    background-color: #1f2937;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #365d8d;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #6b7280;
}
QMenu::separator {
    height: 1px;
    background: #374151;
    margin: 4px 8px;
}
"""

LAND_SECTION_HEADERS = {
    "land": "土地資料",
    "owner": "地主資料",
}
FORM_COLUMN_COUNT = 6
LAND_FORM_ROWS = (
    (("district", 0, 3), ("section", 3, 3)),
    (
        ("registration_order", 0, 2),
        ("numerator", 2, 2),
        ("denominator", 4, 2),
    ),
    (("land_number", 0, 6),),
    (("area", 0, 2), ("declared_value", 2, 2), ("ping", 4, 2)),
    (("total_declared_value", 0, 6),),
)
OWNER_FORM_ROWS = (
    (("owner_name", 0, 3), ("external_id", 3, 3)),
    (("address", 0, 6),),
    (("registration_reason", 0, 3), ("visit_log", 3, 3)),
    (("note", 0, 6),),
)


class DesktopWindowMixin:
    def create_layout(self):
        central = QWidget()
        self.setStyleSheet(CONTROL_STYLESHEET)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        root.addLayout(toolbar)

        toolbar.addWidget(QLabel("搜尋"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入關鍵字")
        self.search_input.returnPressed.connect(self.refresh_records_for_search)
        self.search_input.setMinimumWidth(300)
        toolbar.addWidget(self.search_input)

        search_button = QPushButton("搜尋")
        search_button.clicked.connect(
            lambda _checked=False: self.refresh_records_for_search()
        )
        toolbar.addWidget(search_button)

        toolbar.addWidget(QLabel("篩選"))
        self.filter_field_combo = QComboBox()
        for key, label in self.filterable_fields:
            self.filter_field_combo.addItem(label, key)
        self.filter_field_combo.setCurrentIndex(0)
        self.filter_field_combo.currentIndexChanged.connect(
            lambda _index: self.refresh_records_for_search()
        )
        toolbar.addWidget(self.filter_field_combo)

        toolbar.addWidget(QLabel("排序"))
        self.sort_field_combo = QComboBox()
        for key, label in self.sortable_fields:
            self.sort_field_combo.addItem(label, key)
        self.sort_field_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
        toolbar.addWidget(self.sort_field_combo)

        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItem("新到舊", "desc")
        self.sort_order_combo.addItem("舊到新", "asc")
        self.sort_order_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
        toolbar.addWidget(self.sort_order_combo)

        clear_button = QPushButton("清除")
        clear_button.clicked.connect(self.clear_search)
        toolbar.addWidget(clear_button)

        self.data_button = QPushButton("資料")
        self.data_button.clicked.connect(self.show_data_menu)
        toolbar.addWidget(self.data_button)

        self.tools_button = QPushButton("工具")
        self.tools_button.clicked.connect(self.show_tools_menu)
        toolbar.addWidget(self.tools_button)

        self.settings_button = QPushButton("設定")
        self.settings_button.clicked.connect(self.show_settings_menu)
        toolbar.addWidget(self.settings_button)

        toolbar.addStretch(1)

        new_button = QPushButton("新增資料")
        new_button.clicked.connect(self.new_record)
        toolbar.addWidget(new_button)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        root.addWidget(self.main_splitter, 1)

        self.list_frame = QFrame()
        self.list_frame.setObjectName("listFrame")
        self.list_frame.setMinimumWidth(LAND_LIST_MINIMUM_WIDTH)
        self.list_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        list_layout = QVBoxLayout(self.list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.main_splitter.addWidget(self.list_frame)

        self.form_frame = QFrame()
        self.form_frame.setObjectName("formFrame")
        self.form_frame.setMinimumWidth(DETAIL_PANEL_MINIMUM_WIDTH)
        self.form_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form_layout = QVBoxLayout(self.form_frame)
        form_layout.setContentsMargins(18, 14, 18, 18)
        form_layout.setSpacing(12)
        self.main_splitter.addWidget(self.form_frame)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes(list(DEFAULT_SPLITTER_SIZES))

        self.layout_settings = getattr(self, "layout_settings", None) or QSettings(
            "LandCustomerSystem",
            "DesktopClient",
        )
        self.splitter_save_timer = QTimer(self)
        self.splitter_save_timer.setSingleShot(True)
        self.splitter_save_timer.setInterval(250)
        self.splitter_save_timer.timeout.connect(self.save_main_splitter_sizes)
        self.main_splitter.splitterMoved.connect(
            lambda _position, _index: self.splitter_save_timer.start()
        )

        self.create_table(list_layout)
        self.create_form(form_layout)
        QTimer.singleShot(0, self.restore_main_splitter_sizes)

    @staticmethod
    def _valid_splitter_sizes(value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            sizes = [int(item) for item in value]
        except (TypeError, ValueError):
            return None
        if any(size <= 0 for size in sizes):
            return None
        return [
            max(LAND_LIST_MINIMUM_WIDTH, sizes[0]),
            max(DETAIL_PANEL_MINIMUM_WIDTH, sizes[1]),
        ]

    def restore_main_splitter_sizes(self):
        if getattr(self, "main_splitter", None) is None:
            return False
        saved = self._valid_splitter_sizes(
            self.layout_settings.value(MAIN_SPLITTER_SETTINGS_KEY)
        )
        self.main_splitter.setSizes(saved or list(DEFAULT_SPLITTER_SIZES))
        return bool(saved)

    def save_main_splitter_sizes(self):
        if getattr(self, "main_splitter", None) is None:
            return False
        sizes = self._valid_splitter_sizes(self.main_splitter.sizes())
        if sizes is None:
            return False
        self.layout_settings.setValue(MAIN_SPLITTER_SETTINGS_KEY, sizes)
        self.layout_settings.sync()
        return True

    def create_table(self, parent_layout):
        build_customer_table_ui(
            self,
            parent_layout,
            self.table_columns,
            self.table_widths,
        )

    def configure_api_mode_ui(self):
        unavailable_text = (
            "這項操作會直接取代或搬移整套伺服器資料，為避免遠端誤操作，"
            "只允許在家中主機執行"
        )
        self.data_button.setEnabled(True)
        self.data_button.setToolTip("遠端資料可批量新增、匯入與匯出")
        for button in (self.tools_button, self.settings_button):
            button.setEnabled(True)
            button.setToolTip("可使用的遠端工具已開放；灰色項目仍僅限家中主機")
        for action in getattr(self, "api_preview_supported_data_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_preview_unavailable_data_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        for action in getattr(self, "api_supported_tool_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_unavailable_tool_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        for action in getattr(self, "api_supported_settings_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_unavailable_settings_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        if self.current_user.get("role") != "admin":
            for action in getattr(self, "api_admin_only_settings_actions", ()):
                action.setEnabled(False)
                action.setStatusTip("此功能僅限管理員使用。")
        for action in getattr(self, "api_preview_unavailable_context_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        self.statusBar().showMessage(
            "PostgreSQL 正式版：通知、工作流程、回收桶、復原、合併、帳號密碼與伺服器備份均已連線。"
        )

    # Keep the old method name for extensions created during the preview stage.
    configure_api_preview_ui = configure_api_mode_ui


    def create_form(self, parent_layout):
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setMinimumWidth(0)
        self.detail_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        basic_page = QWidget()
        basic_page.setMinimumWidth(0)
        basic_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(12)

        self.basic_data_scroll_area = QScrollArea(basic_page)
        self.basic_data_scroll_area.setObjectName("basicDataScrollArea")
        self.basic_data_scroll_area.setWidgetResizable(True)
        self.basic_data_scroll_area.setFrameShape(QFrame.NoFrame)
        self.basic_data_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.basic_data_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self.basic_data_scroll_area.setStyleSheet(
            "QScrollArea#basicDataScrollArea { background: transparent; border: none; }"
            "QScrollArea#basicDataScrollArea > QWidget > QWidget { background: transparent; }"
        )

        self.management_summary_label = QLabel("尚未選取資料")
        self.management_summary_label.setWordWrap(True)
        self.management_summary_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.management_summary_label.setStyleSheet(
            "background: #1f2937; color: #dbeafe; border: 1px solid #374151; "
            "border-radius: 5px; padding: 8px;"
        )
        self.management_summary_label.setToolTip(
            "顯示案件、標籤、附件、自訂欄位、最近聯絡與追蹤狀態。"
        )
        form_widget = QWidget()
        form_widget.setObjectName("basicDataForm")
        form_widget.setMinimumWidth(0)
        form_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        form_widget.setStyleSheet(
            """
            QWidget#basicDataForm {
                background-color: #111827;
                border: 1px solid #1f2937;
                border-radius: 14px;
            }
            QWidget#basicDataForm QWidget[formField="true"],
            QWidget#basicDataForm QLabel {
                background-color: transparent;
                border: none;
            }
            QWidget#basicDataForm QLineEdit,
            QWidget#basicDataForm QPlainTextEdit,
            QWidget#basicDataForm QComboBox {
                background-color: #2b3648;
                color: #f9fafb;
                border: 1px solid #56637a;
                border-radius: 10px;
                padding: 7px 10px;
                min-height: 34px;
            }
            QWidget#basicDataForm QLineEdit:focus,
            QWidget#basicDataForm QPlainTextEdit:focus,
            QWidget#basicDataForm QComboBox:focus {
                border-color: #60a5fa;
                background-color: #313d52;
            }
            QWidget#basicDataForm QLineEdit:disabled,
            QWidget#basicDataForm QPlainTextEdit:disabled,
            QWidget#basicDataForm QComboBox:disabled {
                color: #94a3b8;
                background-color: #1b2330;
                border-color: #3d4759;
            }
            """
        )
        form_layout = QGridLayout(form_widget)
        form_layout.setSizeConstraint(QLayout.SetMinimumSize)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)
        self.basic_data_form_layout = form_layout
        self.form_field_containers = {}
        field_labels = dict(self.land_fields)

        def build_field_container(key):
            label = field_labels.get(key, key)
            container = QWidget(form_widget)
            container.setObjectName(f"fieldCell_{key}")
            container.setProperty("formField", True)
            container.setMinimumWidth(0)
            container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            cell_layout = QVBoxLayout(container)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(5)

            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(8)
            label_widget = QLabel(label)
            label_widget.setObjectName(f"fieldLabel_{key}")
            label_widget.setStyleSheet(
                "color: #a9bfdc; font-size: 13px; padding-left: 2px;"
            )
            label_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            label_row.addWidget(label_widget)
            label_row.addStretch(1)

            if key == "total_declared_value":
                auto_badge = QLabel("自動計算")
                auto_badge.setObjectName("autoCalculationBadge")
                auto_badge.setStyleSheet(
                    "background-color: #4b5563; color: #e5e7eb; "
                    "border-radius: 9px; padding: 2px 9px; font-size: 11px;"
                )
                label_row.addWidget(auto_badge)
                self.auto_calculation_badge = auto_badge
            cell_layout.addLayout(label_row)

            if key == "note":
                widget = QPlainTextEdit()
                widget.setPlaceholderText("尚未填寫")
                widget.setMinimumWidth(0)
                widget.setFixedHeight(92)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.fields[key] = widget
            else:
                widget = QLineEdit()
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                if key == "total_declared_value":
                    widget.setReadOnly(True)
                    widget.setStyleSheet(
                        "background-color: #232d3d; border: 1px dashed #6b7a94; "
                        "color: #b9c4d6; font-style: italic; border-radius: 10px; "
                        "padding: 7px 10px; min-height: 34px;"
                    )
                self.fields[key] = widget
                self.field_widgets[key] = widget
                if key == "declared_value":
                    widget.editingFinished.connect(self.format_declared_value)
                if key == "external_id":
                    widget.textEdited.connect(self.on_external_id_edited)
                    widget.installEventFilter(self)
            cell_layout.addWidget(widget)
            self.form_field_containers[key] = container
            return container

        def add_section_header(row, section_key, *, divider=False):
            if divider:
                divider_widget = QFrame(form_widget)
                divider_widget.setObjectName(f"{section_key}SectionDivider")
                divider_widget.setFrameShape(QFrame.HLine)
                divider_widget.setStyleSheet(
                    "background-color: #374151; max-height: 1px; border: none;"
                )
                form_layout.addWidget(
                    divider_widget,
                    row,
                    0,
                    1,
                    FORM_COLUMN_COUNT,
                )
                row += 1
            section_label = QLabel(LAND_SECTION_HEADERS[section_key])
            section_label.setObjectName(f"{section_key}SectionHeader")
            section_label.setStyleSheet(
                "color: #8ab4f8; font-size: 16px; font-weight: 600; "
                "padding: 3px 4px 5px 4px;"
            )
            form_layout.addWidget(
                section_label,
                row,
                0,
                1,
                FORM_COLUMN_COUNT,
            )
            return row + 1

        used_keys = set()

        def add_field_rows(row, rows):
            for row_fields in rows:
                for key, column, column_span in row_fields:
                    if key not in field_labels:
                        continue
                    form_layout.addWidget(
                        build_field_container(key),
                        row,
                        column,
                        1,
                        column_span,
                    )
                    used_keys.add(key)
                row += 1
            return row

        row = add_section_header(0, "land")
        row = add_field_rows(row, LAND_FORM_ROWS)
        row = add_section_header(row, "owner", divider=True)
        row = add_field_rows(row, OWNER_FORM_ROWS)

        for key, _label in self.land_fields:
            if key in used_keys:
                continue
            form_layout.addWidget(
                build_field_container(key),
                row,
                0,
                1,
                FORM_COLUMN_COUNT,
            )
            row += 1

        for column in range(FORM_COLUMN_COUNT):
            form_layout.setColumnStretch(column, 1)
        self.basic_data_scroll_area.setWidget(form_widget)
        basic_layout.addWidget(self.basic_data_scroll_area, 1)
        basic_layout.addWidget(self.management_summary_label)
        self.bind_total_formula()

        button_row = QHBoxLayout()
        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.save_record)
        button_row.addWidget(save_button)

        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.new_record)
        button_row.addWidget(clear_button)

        button_row.addStretch(1)

        delete_button = QPushButton("刪除")
        delete_button.clicked.connect(self.delete_record)
        button_row.addWidget(delete_button)

        basic_layout.addLayout(button_row)

        self.detail_tabs.addTab(basic_page, "基本資料")
        self.owner_contacts_widget = OwnerContactsWidget(
            self.active_record_repository,
            current_role=self.current_user.get("role", "viewer"),
            parent=self.detail_tabs,
        )
        self.detail_tabs.addTab(self.owner_contacts_widget, "關係人")
        parent_layout.addWidget(self.detail_tabs, 1)

    def show_settings_menu(self):
        if self.settings_menu is None or self.settings_button is None:
            return
        position = self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft())
        self.settings_menu.exec(position)

    def show_about(self):
        self._app_component("QMessageBox").information(self, "關於系統", full_version_text())

    def show_help(self):
        self._app_component("HelpDialog")(self).exec()

    def show_data_menu(self):
        if self.data_menu is None or self.data_button is None:
            return
        position = self.data_button.mapToGlobal(self.data_button.rect().bottomLeft())
        self.data_menu.exec(position)

    def show_tools_menu(self):
        if self.tools_menu is None or self.tools_button is None:
            return
        position = self.tools_button.mapToGlobal(self.tools_button.rect().bottomLeft())
        self.tools_menu.exec(position)
