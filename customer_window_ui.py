"""Desktop main-window layout, form, table, and menu construction."""

from customer_table_ui import build_customer_table_ui
from customer_owner_contacts import OwnerContactsWidget
from customer_ui_loader import find_child, load_ui, put_in_slot, render_qss
from customer_theme import (
    heading_font,
    line_icon,
    set_widget_property,
    theme_tokens,
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
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox as FluentComboBox

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
# The main window's fixed layout -- toolbar, splitter, and the 基本資料 grid with
# one fieldCell_<key> / fieldLabel_<key> / field_<key> trio per form field -- is
# ui/main_window.ui (edit it in pyside6-designer).  Where each cell sits is read
# back from that grid, so moving cells in Designer needs no code change.
MAIN_WINDOW_UI_FILE = "main_window.ui"
DETAIL_FORM_STYLESHEET_FILE = "detail_form.qss"
MAIN_WINDOW_STATIC_OBJECT_NAMES = (
    "appGround",
    "toolbarFrame",
    "searchGroup",
    "searchFilterCombo",
    "searchDivider",
    "searchDivider_2",
    "searchInput",
    "searchButton",
    "toolbarSortLabel",
    "sortFieldCombo",
    "sortOrderCombo",
    "clearSearchButton",
    "dataButton",
    "toolsButton",
    "settingsButton",
    "newRecordButton",
    "contentGround",
    "mainSplitter",
    "listFrame",
    "listLayout",
    "formFrame",
    "formLayout",
    "landHeaderSlot",
    "detailTabs",
    "basicPage",
    "basicDataScrollArea",
    "basicDataForm",
    "basicDataFormLayout",
    "landSectionHeaderRow",
    "landSectionHeader",
    "landSectionNote",
    "ownerSectionHeaderRow",
    "ownerSectionHeader",
    "ownerSectionNote",
    "autoCalculationBadge",
    "autoCalculationBadge_age",
    "managementSummaryHeader",
    "managementSummaryLabel",
    "deleteRecordButton",
    "saveStateLabel",
    "clearFormButton",
    "saveRecordButton",
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
AUTO_CALCULATED_FORM_KEYS = ("total_declared_value", "age")


def form_field_keys(land_fields):
    """Every key that has a cell in the 基本資料 grid."""

    return tuple(dict(land_fields)) + tuple(
        key for key in EXTRA_OWNER_FORM_FIELD_LABELS if key not in dict(land_fields)
    )


def main_window_object_names(land_fields):
    """The objectNames create_layout() needs to find in ui/main_window.ui."""

    names = list(MAIN_WINDOW_STATIC_OBJECT_NAMES)
    for key in form_field_keys(land_fields):
        names.extend((f"fieldCell_{key}", f"fieldLabel_{key}", f"field_{key}"))
    return names


# Built-in copy of ui/detail_form.qss, used when that file is missing or broken.
DETAIL_FORM_STYLESHEET = """
QWidget#basicDataForm {
    background-color: transparent;
    border: none;
}
QWidget#basicDataForm QWidget[formField="true"] {
    background-color: $field;
    border: none;
    border-right: 1px solid $rule;
    border-bottom: 1px solid $rule;
}
QWidget#basicDataForm QWidget[formField="true"][firstRow="true"] {
    border-top: 1px solid $rule_strong;
}
QWidget#basicDataForm QWidget[formField="true"][firstCol="true"] {
    border-left: 1px solid $rule_strong;
}
QWidget#basicDataForm QWidget[formField="true"][lastCol="true"] {
    border-right: 1px solid $rule_strong;
}
QWidget#basicDataForm QWidget[formField="true"][lastRow="true"] {
    border-bottom: 1px solid $rule_strong;
}
QWidget#basicDataForm QWidget[formField="true"][autoCell="true"] {
    background-color: $auto;
}
QWidget#basicDataForm QWidget[formField="true"][focused="true"] {
    border: 2px solid $green;
}
QWidget#basicDataForm QLabel {
    background-color: transparent;
    border: none;
    color: $ink2;
}
QWidget#basicDataForm QLabel#landSectionHeader,
QWidget#basicDataForm QLabel#ownerSectionHeader {
    color: $ink;
}
QWidget#basicDataForm QLabel#landSectionNote,
QWidget#basicDataForm QLabel#ownerSectionNote,
QWidget#basicDataForm QLabel#autoCalculationBadge,
QWidget#basicDataForm QLabel#autoCalculationBadge_age {
    font-size: 12px;
}
QWidget#basicDataForm QLineEdit,
QWidget#basicDataForm QPlainTextEdit,
QWidget#basicDataForm QComboBox {
    background-color: transparent;
    color: $ink;
    border: none;
    border-radius: 0px;
    padding: 2px 0px 0px 0px;
    min-height: 26px;
}
QWidget#basicDataForm QLineEdit:focus,
QWidget#basicDataForm QPlainTextEdit:focus,
QWidget#basicDataForm QComboBox:focus {
    border: none;
    padding: 2px 0px 0px 0px;
}
QWidget#basicDataForm QLineEdit:disabled,
QWidget#basicDataForm QPlainTextEdit:disabled,
QWidget#basicDataForm QComboBox:disabled,
QWidget#basicDataForm QLineEdit[readOnly="true"] {
    background-color: transparent;
    color: $ink2;
}
"""


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
        land_fields = getattr(self, "land_fields", ())
        central = load_ui(
            MAIN_WINDOW_UI_FILE,
            required_names=main_window_object_names(land_fields),
        )
        self.main_window_ui = central
        self.setCentralWidget(central)

        def ui(name, cls=None):
            return find_child(central, name, cls)

        search_group = ui("searchGroup", QFrame)
        self.search_group = search_group

        self.filter_field_combo = ui("searchFilterCombo", FluentComboBox)
        for key, label in self.filterable_fields:
            self.filter_field_combo.addItem(label, userData=key)
        self.filter_field_combo.setCurrentIndex(0)
        self.filter_field_combo.currentIndexChanged.connect(
            lambda _index: self.refresh_records_for_search()
        )
        self.search_input = ui("searchInput", QLineEdit)
        self.search_input.returnPressed.connect(self.refresh_records_for_search)
        self.search_input.installEventFilter(_FocusStateFilter(search_group, search_group))

        search_button = ui("searchButton", QPushButton)
        search_button.setIcon(line_icon("search", "ink2", 16))
        search_button.clicked.connect(
            lambda _checked=False: self.refresh_records_for_search()
        )

        self.sort_field_combo = ui("sortFieldCombo", FluentComboBox)
        for key, label in self.sortable_fields:
            self.sort_field_combo.addItem(label, userData=key)
        self.sort_field_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())

        self.sort_order_combo = ui("sortOrderCombo", FluentComboBox)
        self.sort_order_combo.addItem("新到舊", userData="desc")
        self.sort_order_combo.addItem("舊到新", userData="asc")
        self.sort_order_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())

        clear_button = ui("clearSearchButton", QPushButton)
        clear_button.clicked.connect(self.clear_search)

        self.data_button = ui("dataButton", QPushButton)
        self.data_button.clicked.connect(self.show_data_menu)
        self.tools_button = ui("toolsButton", QPushButton)
        self.tools_button.clicked.connect(self.show_tools_menu)
        self.settings_button = ui("settingsButton", QPushButton)
        self.settings_button.clicked.connect(self.show_settings_menu)
        for button in (self.data_button, self.tools_button, self.settings_button):
            button.setIcon(line_icon("chevron", "ink2", 14))

        new_button = ui("newRecordButton", QPushButton)
        new_button.setIcon(line_icon("plus", "green_ink", 16))
        new_button.clicked.connect(self.new_record)
        self.new_record_button = new_button

        # The theme paints QWidget#appGround; Designer needs unique names, so
        # the content area is called contentGround in the .ui file.
        ui("contentGround", QWidget).setObjectName("appGround")

        self.main_splitter = ui("mainSplitter", QSplitter)
        self.list_frame = ui("listFrame", QFrame)
        list_layout = ui("listLayout", QVBoxLayout)
        self.form_frame = ui("formFrame", QFrame)
        form_layout = ui("formLayout", QVBoxLayout)
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
        self._put_in_slot(form_layout, ui("landHeaderSlot", QWidget), self.land_header)
        self.create_form(form_layout)
        self._restore_main_tab_order()
        QTimer.singleShot(0, self.restore_main_splitter_sizes)

    @staticmethod
    def _put_in_slot(layout, slot, widget):
        """Move ``widget`` (already added to ``layout``) to where ``slot`` sits."""

        layout.removeWidget(widget)
        put_in_slot(slot, widget)

    def _restore_main_tab_order(self):
        """Tab moves toolbar -> list -> land header -> detail tabs, as before.

        Widgets built in code after the .ui file was loaded join the end of the
        focus chain; chain each area's widgets back after the toolbar.
        """

        blocks = [
            block
            for block in (
                self.list_frame,
                getattr(self, "land_header", None),
                getattr(self, "detail_tabs", None),
            )
            if block is not None
        ]
        ordered = {id(block): [] for block in blocks}
        current = self.nextInFocusChain()
        guard = 0
        while current is not self and guard < 10000:
            guard += 1
            # setTabOrder() ignores NoFocus widgets, so only chain focusable ones.
            for block in blocks:
                if current.focusPolicy() != Qt.NoFocus and (
                    current is block or block.isAncestorOf(current)
                ):
                    ordered[id(block)].append(current)
                    break
            current = current.nextInFocusChain()
        previous = self.new_record_button
        for block in blocks:
            for widget in ordered[id(block)]:
                QWidget.setTabOrder(previous, widget)
                previous = widget

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
        central = self.main_window_ui

        def ui(name, cls=None):
            return find_child(central, name, cls)

        self.detail_tabs = ui("detailTabs", QTabWidget)
        self.basic_data_scroll_area = ui("basicDataScrollArea", QScrollArea)
        self.management_summary_header = ui("managementSummaryHeader", QLabel)
        self._style_section_title(self.management_summary_header)
        self.management_summary_label = ui("managementSummaryLabel", QLabel)
        form_widget = ui("basicDataForm", QWidget)
        form_widget.setAttribute(Qt.WA_StyledBackground, True)
        form_widget.setStyleSheet(
            render_qss(
                DETAIL_FORM_STYLESHEET_FILE, DETAIL_FORM_STYLESHEET, theme_tokens()
            )
        )
        form_layout = ui("basicDataFormLayout", QGridLayout)
        self.basic_data_form_layout = form_layout
        self.form_field_containers = {}
        self.form_cell_positions = {}
        self.form_loading_depth = 0
        field_labels = dict(self.land_fields)
        field_labels.update(EXTRA_OWNER_FORM_FIELD_LABELS)

        def setup_field(key):
            container = ui(f"fieldCell_{key}", QWidget)
            container.setAttribute(Qt.WA_StyledBackground, True)
            label_widget = ui(f"fieldLabel_{key}", QLabel)
            label_widget.setText(field_labels.get(key, key))
            # Colour: ui/detail_form.qss.  Point size is set in
            # apply_form_field_fonts() so it follows the font-size setting.
            if key in AUTO_CALCULATED_FORM_KEYS:
                badge_name = (
                    "autoCalculationBadge"
                    if key == "total_declared_value"
                    else f"autoCalculationBadge_{key}"
                )
                auto_badge = ui(badge_name, QLabel)
                if key == "total_declared_value":
                    self.auto_calculation_badge = auto_badge

            if key == "urban_plan":
                widget = ui(f"field_{key}", FluentComboBox)
                widget.activated.connect(lambda _index: self.mark_form_dirty())
                self.urban_plan_form_combo = widget
            elif key == "note":
                widget = ui(f"field_{key}", QPlainTextEdit)
                widget.textChanged.connect(self._on_form_text_changed)
                self.fields[key] = widget
            elif key == "age":
                # Purely a live display of birth_year -> age: never part of
                # self.fields, so it never gets read by get_form_data() or
                # written to the database. See update_age_field().
                widget = ui(f"field_{key}", QLineEdit)
                self.age_display_widget = widget
            else:
                widget = ui(f"field_{key}", QLineEdit)
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
            self.form_field_containers[key] = container

        for section_key in LAND_SECTION_HEADERS:
            self._style_section_title(ui(f"{section_key}SectionHeader", QLabel))
            note_label = ui(f"{section_key}SectionNote", QLabel)
            setattr(self, f"{section_key}_section_note_label", note_label)

        # Row by row, as the cells sit in the grid, so self.fields keeps the
        # on-screen order.
        for key, section_key, _row, column, column_span in self._form_grid_cells(
            central, form_field_keys(self.land_fields)
        ):
            setup_field(key)
            self.form_cell_positions[key] = (section_key, column, column_span)

        self.bind_total_formula()
        self.refresh_form_cell_borders()
        self.apply_form_field_fonts()

        delete_button = ui("deleteRecordButton", QPushButton)
        delete_button.setIcon(line_icon("trash", "seal", 16))
        delete_button.clicked.connect(self.delete_record)

        self.save_state_label = ui("saveStateLabel", QLabel)

        ui("clearFormButton", QPushButton).clicked.connect(self.new_record)
        ui("saveRecordButton", QPushButton).clicked.connect(self.save_record)

        self.owner_contacts_widget = OwnerContactsWidget(
            self.active_record_repository,
            current_role=self.current_user.get("role", "viewer"),
            parent=self.detail_tabs,
        )
        self.detail_tabs.addTab(self.owner_contacts_widget, "關係人")
        self.refresh_land_header()

    # -- form helpers -------------------------------------------------------------

    def _form_grid_cells(self, root=None, keys=None):
        """(key, section, row, column, column span) for each cell, in grid order.

        The section is "owner" for cells below the 土地所有權部 header row and
        "land" otherwise.
        """

        layout = self.basic_data_form_layout
        root = root or self.main_window_ui
        if keys is None:
            containers = self.form_field_containers
        else:
            containers = {
                key: find_child(root, f"fieldCell_{key}", QWidget) for key in keys
            }
        owner_header = root.findChild(QWidget, "ownerSectionHeaderRow")
        owner_index = layout.indexOf(owner_header) if owner_header is not None else -1
        owner_row = layout.getItemPosition(owner_index)[0] if owner_index >= 0 else None
        cells = []
        for key, container in containers.items():
            index = layout.indexOf(container)
            if index < 0:
                continue
            row, column, _row_span, column_span = layout.getItemPosition(index)
            section_key = (
                "owner" if owner_row is not None and row > owner_row else "land"
            )
            cells.append((key, section_key, row, column, column_span))
        cells.sort(key=lambda cell: (cell[2], cell[3]))
        return cells

    @staticmethod
    def _style_section_title(label):
        # Colour: ui/theme.qss / ui/detail_form.qss; the heading font stays
        # here because QSS cannot set its letter spacing.
        font = heading_font(13)
        font.setLetterSpacing(QFont.PercentageSpacing, 108)
        label.setFont(font)
        return label

    @classmethod
    def _section_title_label(cls, text, object_name):
        label = QLabel(text)
        label.setObjectName(object_name)
        return cls._style_section_title(label)

    def apply_form_field_fonts(self):
        """Grid inputs are one point above the base font, their labels one below."""

        base = self.font().pointSize()
        if base <= 0:
            return
        for key, container in getattr(self, "form_field_containers", {}).items():
            for widget_type in (QLineEdit, QPlainTextEdit, QComboBox, FluentComboBox):
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
        if not containers:
            return
        cells = self._form_grid_cells()
        column_count = self.basic_data_form_layout.columnCount() or FORM_COLUMN_COUNT
        for section_key in LAND_SECTION_HEADERS:
            section_cells = [cell for cell in cells if cell[1] == section_key]
            visible_rows = sorted(
                {
                    row
                    for key, _section, row, _column, _span in section_cells
                    if not containers[key].isHidden()
                }
            )
            if not visible_rows:
                continue
            first_row, last_row = visible_rows[0], visible_rows[-1]
            for key, _section, row, column, span in section_cells:
                container = containers[key]
                set_widget_property(container, "firstRow", row == first_row)
                set_widget_property(container, "lastRow", row == last_row)
                set_widget_property(container, "firstCol", column == 0)
                set_widget_property(
                    container, "lastCol", column + span >= column_count
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
