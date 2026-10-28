"""Desktop main-window layout, form, table, and menu construction."""

from customer_table_ui import build_customer_table_ui
from customer_owner_contacts import OwnerContactsWidget
from customer_theme import (
    heading_font,
    line_icon,
    set_button_variant,
    set_widget_property,
    token,
)
from customer_version import full_version_text
from PySide6.QtCore import QEvent, QObject, QSettings, QTimer, Qt
from PySide6.QtGui import QFont
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

LAND_SECTION_HEADERS = {
    "land": "土地標示部",
    "owner": "土地所有權部",
}
SAVE_STATE_DIRTY_TEXT = "有未儲存的修改"
SAVE_STATE_SAVED_TEXT = "已儲存"
SAVE_STATE_CLEAR_MS = 3000
FORM_COLUMN_COUNT = 6
LAND_FORM_ROWS = (
    (("urban_plan", 0, 6),),
    (("district", 0, 3), ("section", 3, 3)),
    (("subsection", 0, 3), ("land_number", 3, 3)),
    (
        ("registration_order", 0, 2),
        ("numerator", 2, 2),
        ("denominator", 4, 2),
    ),
    (("area", 0, 2), ("declared_value", 2, 2), ("ping", 4, 2)),
    (("total_declared_value", 0, 6),),
)
OWNER_FORM_ROWS = (
    (("owner_name", 0, 3), ("external_id", 3, 3)),
    (("birth_year", 0, 3), ("age", 3, 3)),
    (("address", 0, 6),),
    (("registration_reason", 0, 3), ("visit_log", 3, 3)),
    (("note", 0, 6),),
)
# birth_year/age deliberately live outside LAND_FIELDS (see
# customer_repository.customer_data_columns): they only need to show up in
# this one form, not in Excel export/import, report templates, the table
# column picker, or migration tooling.  This label map exists purely so
# build_field_container() can find a label for them.
EXTRA_OWNER_FORM_FIELD_LABELS = {
    "birth_year": "出生西元年",
    "age": "年齡",
    # 都市計畫 is a land attribute chosen from the server's plan list (a combo
    # box, never part of self.fields); the container hides itself when the
    # server has no plans -- see UrbanPlanWorkflowMixin.
    "urban_plan": "都市計畫",
}


class _FocusStateFilter(QObject):
    """Mirrors keyboard focus into a ``focused`` property so QSS can draw it."""

    def __init__(self, target, parent=None):
        super().__init__(parent or target)
        self.target = target

    def eventFilter(self, watched, event):
        if event.type() == QEvent.FocusIn:
            set_widget_property(self.target, "focused", True)
        elif event.type() == QEvent.FocusOut:
            set_widget_property(self.target, "focused", False)
        return False


class DesktopWindowMixin:
    def create_layout(self):
        central = QWidget()
        central.setObjectName("appGround")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("toolbarFrame")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(16, 10, 16, 10)
        toolbar.setSpacing(8)
        root.addWidget(toolbar_frame)

        search_group = QFrame()
        search_group.setObjectName("searchGroup")
        search_group.setMaximumWidth(600)
        search_group.setFixedHeight(38)
        self.search_group = search_group
        group_layout = QHBoxLayout(search_group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(0)

        self.filter_field_combo = QComboBox()
        self.filter_field_combo.setObjectName("searchFilterCombo")
        for key, label in self.filterable_fields:
            self.filter_field_combo.addItem(label, key)
        self.filter_field_combo.setCurrentIndex(0)
        self.filter_field_combo.currentIndexChanged.connect(
            lambda _index: self.refresh_records_for_search()
        )
        group_layout.addWidget(self.filter_field_combo)
        group_layout.addWidget(self._search_divider())

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("地號、姓名、地址或電話")
        self.search_input.returnPressed.connect(self.refresh_records_for_search)
        self.search_input.setMinimumWidth(120)
        self.search_input.installEventFilter(_FocusStateFilter(search_group, search_group))
        group_layout.addWidget(self.search_input, 1)
        group_layout.addWidget(self._search_divider())

        search_button = QPushButton("搜尋")
        search_button.setObjectName("searchButton")
        search_button.setIcon(line_icon("search", "ink2", 16))
        search_button.clicked.connect(
            lambda _checked=False: self.refresh_records_for_search()
        )
        group_layout.addWidget(search_button)
        toolbar.addWidget(search_group, 100)

        sort_label = QLabel("排序")
        sort_label.setObjectName("toolbarSortLabel")
        sort_label.setStyleSheet(f"color: {token('ink2')};")
        toolbar.addWidget(sort_label)
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
        set_button_variant(clear_button, "ghost")
        clear_button.clicked.connect(self.clear_search)
        toolbar.addWidget(clear_button)

        toolbar.addStretch(1)

        self.data_button = QPushButton("資料")
        self.data_button.clicked.connect(self.show_data_menu)
        self.tools_button = QPushButton("工具")
        self.tools_button.clicked.connect(self.show_tools_menu)
        self.settings_button = QPushButton("設定")
        self.settings_button.clicked.connect(self.show_settings_menu)
        for button in (self.data_button, self.tools_button, self.settings_button):
            set_button_variant(button, "ghost")
            button.setLayoutDirection(Qt.RightToLeft)
            button.setIcon(line_icon("chevron", "ink2", 14))
            toolbar.addWidget(button)

        new_button = QPushButton("新增資料")
        new_button.setObjectName("newRecordButton")
        set_button_variant(new_button, "primary")
        new_button.setIcon(line_icon("plus", "green_ink", 16))
        new_button.clicked.connect(self.new_record)
        toolbar.addWidget(new_button)
        self.new_record_button = new_button

        content = QWidget()
        content.setObjectName("appGround")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(8)
        root.addWidget(content, 1)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        content_layout.addWidget(self.main_splitter, 1)

        self.list_frame = QFrame()
        self.list_frame.setObjectName("listFrame")
        self.list_frame.setMinimumWidth(LAND_LIST_MINIMUM_WIDTH)
        self.list_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        list_layout = QVBoxLayout(self.list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        self.main_splitter.addWidget(self.list_frame)

        self.form_frame = QFrame()
        self.form_frame.setObjectName("formFrame")
        self.form_frame.setMinimumWidth(DETAIL_PANEL_MINIMUM_WIDTH)
        self.form_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form_layout = QVBoxLayout(self.form_frame)
        form_layout.setContentsMargins(18, 14, 18, 14)
        form_layout.setSpacing(10)
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
        self.create_land_header(form_layout)
        self.create_form(form_layout)
        QTimer.singleShot(0, self.restore_main_splitter_sizes)

    @staticmethod
    def _search_divider():
        divider = QFrame()
        divider.setObjectName("searchDivider")
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background-color: {token('rule')}; border: none;")
        return divider

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

        self.management_summary_header = self._section_title_label(
            "管理摘要", "managementSummaryHeader"
        )
        self.management_summary_label = QLabel("尚未選取資料")
        self.management_summary_label.setObjectName("managementSummaryLabel")
        self.management_summary_label.setWordWrap(True)
        self.management_summary_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.management_summary_label.setStyleSheet(
            f"background-color: {token('ground')}; color: {token('ink')}; border: none; "
            "border-radius: 6px; padding: 10px 14px; font-size: 13px;"
        )
        self.management_summary_label.setToolTip(
            "顯示案件、標籤、附件、自訂欄位、最近聯絡與追蹤狀態。"
        )
        form_widget = QWidget()
        form_widget.setObjectName("basicDataForm")
        form_widget.setAttribute(Qt.WA_StyledBackground, True)
        form_widget.setMinimumWidth(0)
        form_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        form_widget.setStyleSheet(
            f"""
            QWidget#basicDataForm {{
                background-color: transparent;
                border: none;
            }}
            QWidget#basicDataForm QWidget[formField="true"] {{
                background-color: {token('field')};
                border: none;
                border-right: 1px solid {token('rule')};
                border-bottom: 1px solid {token('rule')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][firstRow="true"] {{
                border-top: 1px solid {token('rule_strong')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][firstCol="true"] {{
                border-left: 1px solid {token('rule_strong')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][lastCol="true"] {{
                border-right: 1px solid {token('rule_strong')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][lastRow="true"] {{
                border-bottom: 1px solid {token('rule_strong')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][autoCell="true"] {{
                background-color: {token('auto')};
            }}
            QWidget#basicDataForm QWidget[formField="true"][focused="true"] {{
                border: 2px solid {token('green')};
            }}
            QWidget#basicDataForm QLabel {{
                background-color: transparent;
                border: none;
            }}
            QWidget#basicDataForm QLineEdit,
            QWidget#basicDataForm QPlainTextEdit,
            QWidget#basicDataForm QComboBox {{
                background-color: transparent;
                color: {token('ink')};
                border: none;
                border-radius: 0px;
                padding: 2px 0px 0px 0px;
                min-height: 26px;
            }}
            QWidget#basicDataForm QLineEdit:focus,
            QWidget#basicDataForm QPlainTextEdit:focus,
            QWidget#basicDataForm QComboBox:focus {{
                border: none;
                padding: 2px 0px 0px 0px;
            }}
            QWidget#basicDataForm QLineEdit:disabled,
            QWidget#basicDataForm QPlainTextEdit:disabled,
            QWidget#basicDataForm QComboBox:disabled,
            QWidget#basicDataForm QLineEdit[readOnly="true"] {{
                background-color: transparent;
                color: {token('ink2')};
            }}
            """
        )
        form_layout = QGridLayout(form_widget)
        form_layout.setSizeConstraint(QLayout.SetMinimumSize)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(0)
        form_layout.setVerticalSpacing(0)
        self.basic_data_form_layout = form_layout
        self.form_field_containers = {}
        self.form_cell_positions = {}
        self.form_loading_depth = 0
        field_labels = dict(self.land_fields)
        field_labels.update(EXTRA_OWNER_FORM_FIELD_LABELS)

        def build_field_container(key):
            label = field_labels.get(key, key)
            container = QWidget(form_widget)
            container.setObjectName(f"fieldCell_{key}")
            container.setAttribute(Qt.WA_StyledBackground, True)
            container.setProperty("formField", True)
            container.setProperty("autoCell", key in ("total_declared_value", "age"))
            container.setMinimumWidth(0)
            container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            cell_layout = QVBoxLayout(container)
            # QSS padding does not move a plain QWidget's layout, so the
            # cell's inner padding is set here (the focus frame changes only
            # the painted border, never the content position).
            cell_layout.setContentsMargins(10, 7, 10, 6)
            cell_layout.setSpacing(2)

            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(8)
            label_widget = QLabel(label)
            label_widget.setObjectName(f"fieldLabel_{key}")
            # Point size is set in apply_form_field_fonts() so it follows the
            # font-size setting.
            label_widget.setStyleSheet(f"color: {token('ink2')};")
            label_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            label_row.addWidget(label_widget)
            label_row.addStretch(1)

            if key in ("total_declared_value", "age"):
                auto_badge = QLabel("自動計算")
                auto_badge.setObjectName("autoCalculationBadge")
                auto_badge.setStyleSheet(
                    f"color: {token('ink2')}; font-size: 12px;"
                )
                label_row.addWidget(auto_badge)
                if key == "total_declared_value":
                    self.auto_calculation_badge = auto_badge
            cell_layout.addLayout(label_row)

            if key == "urban_plan":
                widget = QComboBox()
                widget.setObjectName("urbanPlanFormCombo")
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                widget.setToolTip("這塊土地屬於哪個都市計畫；同一塊土地的所有地主資料會一起更動。")
                widget.activated.connect(lambda _index: self.mark_form_dirty())
                self.urban_plan_form_combo = widget
            elif key == "note":
                widget = QPlainTextEdit()
                widget.setPlaceholderText("尚未填寫")
                widget.setMinimumWidth(0)
                widget.setFixedHeight(92)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                widget.textChanged.connect(self._on_form_text_changed)
                self.fields[key] = widget
            elif key == "age":
                # Purely a live display of birth_year -> age: never part of
                # self.fields, so it never gets read by get_form_data() or
                # written to the database. See update_age_field().
                widget = QLineEdit()
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                widget.setReadOnly(True)
                widget.setPlaceholderText("由出生西元年計算")
                self.age_display_widget = widget
            else:
                widget = QLineEdit()
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                if key == "total_declared_value":
                    widget.setReadOnly(True)
                if key == "birth_year":
                    widget.setPlaceholderText("例如 1965")
                    widget.setMaxLength(4)
                widget.textEdited.connect(self._on_form_text_edited)
                self.fields[key] = widget
                self.field_widgets[key] = widget
                if key == "declared_value":
                    widget.editingFinished.connect(self.format_declared_value)
                if key == "external_id":
                    widget.textEdited.connect(self.on_external_id_edited)
                    widget.installEventFilter(self)
                if key == "birth_year":
                    widget.textChanged.connect(self.update_age_field)
            widget.installEventFilter(_FocusStateFilter(container, container))
            cell_layout.addWidget(widget)
            self.form_field_containers[key] = container
            return container

        def add_section_header(row, section_key, note_text, *, spacer_before=False):
            if spacer_before:
                form_layout.setRowMinimumHeight(row, 18)
                row += 1
            header = QWidget(form_widget)
            header.setObjectName(f"{section_key}SectionHeaderRow")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 6)
            header_layout.setSpacing(10)
            section_label = self._section_title_label(
                LAND_SECTION_HEADERS[section_key], f"{section_key}SectionHeader"
            )
            header_layout.addWidget(section_label)
            note_label = QLabel(note_text)
            note_label.setObjectName(f"{section_key}SectionNote")
            note_label.setStyleSheet(f"color: {token('ink2')}; font-size: 12px;")
            note_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            header_layout.addWidget(note_label, 1)
            setattr(self, f"{section_key}_section_note_label", note_label)
            form_layout.addWidget(header, row, 0, 1, FORM_COLUMN_COUNT)
            return row + 1

        def add_field_rows(row, rows, section_key):
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
                    self.form_cell_positions[key] = (section_key, column, column_span)
                row += 1
            return row

        row = add_section_header(0, "land", "同一筆土地的所有地主一起更動")
        row = add_field_rows(row, LAND_FORM_ROWS, "land")
        row = add_section_header(
            row, "owner", "新增一位地主／一筆持分", spacer_before=True
        )
        add_field_rows(row, OWNER_FORM_ROWS, "owner")

        for column in range(FORM_COLUMN_COUNT):
            form_layout.setColumnStretch(column, 1)
        self.basic_data_scroll_area.setWidget(form_widget)
        basic_layout.addWidget(self.basic_data_scroll_area, 1)
        basic_layout.addWidget(self.management_summary_header)
        basic_layout.addWidget(self.management_summary_label)
        self.bind_total_formula()
        self.refresh_form_cell_borders()
        self.apply_form_field_fonts()

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        delete_button = QPushButton("刪除")
        delete_button.setObjectName("deleteRecordButton")
        set_button_variant(delete_button, "danger-text")
        delete_button.setIcon(line_icon("trash", "seal", 16))
        delete_button.clicked.connect(self.delete_record)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)

        self.save_state_label = QLabel("")
        self.save_state_label.setObjectName("saveStateLabel")
        self.save_state_label.setStyleSheet(
            f"color: {token('ink2')}; font-size: 13px;"
        )
        button_row.addWidget(self.save_state_label)

        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.new_record)
        button_row.addWidget(clear_button)

        save_button = QPushButton("儲存")
        save_button.setObjectName("saveRecordButton")
        set_button_variant(save_button, "primary")
        save_button.setMinimumWidth(88)
        save_button.clicked.connect(self.save_record)
        button_row.addWidget(save_button)

        basic_layout.addLayout(button_row)

        self.detail_tabs.addTab(basic_page, "基本資料")
        self.owner_contacts_widget = OwnerContactsWidget(
            self.active_record_repository,
            current_role=self.current_user.get("role", "viewer"),
            parent=self.detail_tabs,
        )
        self.detail_tabs.addTab(self.owner_contacts_widget, "關係人")
        parent_layout.addWidget(self.detail_tabs, 1)
        self.refresh_land_header()

    # -- form helpers -------------------------------------------------------------

    @staticmethod
    def _section_title_label(text, object_name):
        label = QLabel(text)
        label.setObjectName(object_name)
        font = heading_font(13)
        font.setLetterSpacing(QFont.PercentageSpacing, 108)
        label.setFont(font)
        label.setStyleSheet(f"color: {token('ink')};")
        return label

    def apply_form_field_fonts(self):
        """Grid inputs are one point above the base font, their labels one below."""

        base = self.font().pointSize()
        if base <= 0:
            return
        for key, container in getattr(self, "form_field_containers", {}).items():
            for widget_type in (QLineEdit, QPlainTextEdit, QComboBox):
                for widget in container.findChildren(widget_type):
                    font = QFont(widget.font())
                    font.setPointSize(base + 1)
                    widget.setFont(font)
            label = container.findChild(QLabel, f"fieldLabel_{key}")
            if label is not None:
                label_font = QFont(label.font())
                label_font.setPointSize(max(8, base - 1))
                label.setFont(label_font)

    def refresh_form_cell_borders(self):
        """Mark the outer cells of each section so QSS can draw the 謄本 frame."""

        containers = getattr(self, "form_field_containers", {})
        for section_key, rows in (("land", LAND_FORM_ROWS), ("owner", OWNER_FORM_ROWS)):
            visible_rows = [
                index
                for index, row_fields in enumerate(rows)
                if any(
                    key in containers and not containers[key].isHidden()
                    for key, _column, _span in row_fields
                )
            ]
            if not visible_rows:
                continue
            first_row, last_row = visible_rows[0], visible_rows[-1]
            for index, row_fields in enumerate(rows):
                for key, column, span in row_fields:
                    container = containers.get(key)
                    if container is None:
                        continue
                    set_widget_property(container, "firstRow", index == first_row)
                    set_widget_property(container, "lastRow", index == last_row)
                    set_widget_property(container, "firstCol", column == 0)
                    set_widget_property(
                        container, "lastCol", column + span >= FORM_COLUMN_COUNT
                    )

    # -- save state ---------------------------------------------------------------

    def _on_form_text_edited(self, _text=""):
        self.mark_form_dirty()

    def _on_form_text_changed(self):
        # QPlainTextEdit has no textEdited(): ignore the changes made while a
        # record is being loaded into the form.
        if self.form_loading_depth == 0:
            self.mark_form_dirty()

    def mark_form_dirty(self):
        label = getattr(self, "save_state_label", None)
        if label is None:
            return
        self._saved_state_record_id = None
        label.setText(SAVE_STATE_DIRTY_TEXT)

    def mark_form_saved(self):
        label = getattr(self, "save_state_label", None)
        if label is None:
            return
        self._saved_state_record_id = self.selected_record_id
        label.setText(SAVE_STATE_SAVED_TEXT)
        QTimer.singleShot(SAVE_STATE_CLEAR_MS, self._clear_saved_state_text)

    def _clear_saved_state_text(self):
        label = getattr(self, "save_state_label", None)
        if label is not None and label.text() == SAVE_STATE_SAVED_TEXT:
            label.setText("")

    def clear_save_state(self, *, keep_saved_for=None):
        """Empty the label; a fresh 已儲存 for ``keep_saved_for`` is left alone."""

        label = getattr(self, "save_state_label", None)
        if label is None:
            return
        if (
            keep_saved_for is not None
            and label.text() == SAVE_STATE_SAVED_TEXT
            and getattr(self, "_saved_state_record_id", None) == keep_saved_for
        ):
            return
        self._saved_state_record_id = None
        label.setText("")

    def refresh_owner_section_note(self):
        label = getattr(self, "owner_section_note_label", None)
        if label is None:
            return
        widget = self.field_widgets.get("owner_name")
        name = widget.text().strip() if widget is not None else ""
        if self.selected_record_id is None or not name:
            label.setText("新增一位地主／一筆持分")
        else:
            label.setText(f"目前地主：{name}")

    def after_record_loaded(self):
        self.clear_save_state(keep_saved_for=self.selected_record_id)
        self.refresh_owner_section_note()
        self.refresh_land_header()
        # The land row's share bar marks the selected owner's segment.
        if getattr(self, "table_view", None) is not None:
            self.table_view.viewport().update()

    def after_new_record(self):
        self.clear_save_state()
        self.refresh_owner_section_note()
        self.refresh_land_header(new_record=True)

    # -- status bar -----------------------------------------------------------------

    def create_status_bar_content(self):
        from customer_productivity import ROLE_LABELS
        from customer_version import (
            desktop_client_version_label,
            version_label,
        )

        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        info = QWidget()
        info.setObjectName("statusInfo")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(8, 0, 0, 0)
        info_layout.setSpacing(14)

        connection = QWidget()
        connection_layout = QHBoxLayout(connection)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.setSpacing(6)
        if self.api_mode:
            dot = QLabel()
            dot.setObjectName("statusConnectionDot")
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background-color: {token('green')}; border-radius: 4px;"
            )
            connection_layout.addWidget(dot)
        self.status_connection_label = QLabel(
            "已連線家中主機（PostgreSQL 正式版）" if self.api_mode else "單機版（本機資料庫）"
        )
        self.status_connection_label.setObjectName("statusConnectionLabel")
        connection_layout.addWidget(self.status_connection_label)
        info_layout.addWidget(connection)

        role = self.current_user.get("role", "viewer")
        self.status_user_label = QLabel(f"登入：{ROLE_LABELS.get(role, role)}")
        self.status_user_label.setObjectName("statusUserLabel")
        info_layout.addWidget(self.status_user_label)

        self.status_mask_label = QLabel("")
        self.status_mask_label.setObjectName("statusMaskLabel")
        info_layout.addWidget(self.status_mask_label)
        self.refresh_status_bar_content()
        bar.addWidget(info)

        version = desktop_client_version_label() if self.api_mode else version_label()
        self.status_version_label = QLabel(f"土地資料系統 {version}")
        self.status_version_label.setObjectName("statusVersionLabel")
        bar.addPermanentWidget(self.status_version_label)

    def refresh_status_bar_content(self):
        label = getattr(self, "status_mask_label", None)
        if label is not None:
            label.setText(
                "身分證遮罩：開啟" if self.privacy_mask_enabled else "身分證遮罩：關閉"
            )

    def show_settings_menu(self):
        if self.settings_menu is None or self.settings_button is None:
            return
        position = self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft())
        self.settings_menu.exec(position)

    def show_about(self):
        self._app_component("QMessageBox").information(self, "關於系統", full_version_text())

    def show_help(self):
        self._show_non_modal_report_dialog(
            "_help_dialog", self._app_component("HelpDialog"), self
        )

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
