"""Desktop main-window layout, form, table, and menu construction."""

from customer_table_ui import build_customer_table_ui
from customer_version import full_version_text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class DesktopWindowMixin:
    def create_layout(self):
        central = QWidget()
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
        self.search_input.returnPressed.connect(self.refresh_records)
        self.search_input.setMinimumWidth(300)
        toolbar.addWidget(self.search_input)

        search_button = QPushButton("搜尋")
        search_button.clicked.connect(lambda _checked=False: self.refresh_records())
        toolbar.addWidget(search_button)

        toolbar.addWidget(QLabel("篩選"))
        self.filter_field_combo = QComboBox()
        for key, label in self.filterable_fields:
            self.filter_field_combo.addItem(label, key)
        self.filter_field_combo.setCurrentIndex(0)
        self.filter_field_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
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

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        list_frame = QFrame()
        list_frame.setObjectName("listFrame")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(list_frame)

        form_frame = QFrame()
        form_frame.setObjectName("formFrame")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(18, 14, 18, 18)
        form_layout.setSpacing(12)
        splitter.addWidget(form_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.create_table(list_layout)
        self.create_form(form_layout)

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
        title = QLabel("土地資料")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #f9fafb; padding-bottom: 4px;")
        parent_layout.addWidget(title)

        self.management_summary_label = QLabel("尚未選取資料")
        self.management_summary_label.setWordWrap(True)
        self.management_summary_label.setStyleSheet(
            "background: #1f2937; color: #dbeafe; border: 1px solid #374151; "
            "border-radius: 5px; padding: 8px;"
        )
        self.management_summary_label.setToolTip(
            "顯示案件、標籤、附件、自訂欄位、最近聯絡與追蹤狀態。"
        )
        parent_layout.addWidget(self.management_summary_label)

        form_widget = QWidget()
        form_layout = QGridLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

        for index, (key, label) in enumerate(self.land_fields, start=0):
            row = index
            label_widget = QLabel(label)
            label_widget.setStyleSheet("color: #d1d5db; padding-right: 6px;")
            form_layout.addWidget(label_widget, row, 0)
            if key == "note":
                widget = QPlainTextEdit()
                widget.setFixedHeight(88)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.fields[key] = widget
            else:
                widget = QLineEdit()
                if key == "total_declared_value":
                    widget.setReadOnly(True)
                self.fields[key] = widget
                self.field_widgets[key] = widget
                if key == "declared_value":
                    widget.editingFinished.connect(self.format_declared_value)
                if key == "external_id":
                    widget.textEdited.connect(self.on_external_id_edited)
                    widget.installEventFilter(self)
            form_layout.addWidget(widget, row, 1)

        form_layout.setColumnStretch(1, 1)
        parent_layout.addWidget(form_widget)
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

        parent_layout.addLayout(button_row)
        parent_layout.addStretch(1)

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
