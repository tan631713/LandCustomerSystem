"""Desktop record table and action-menu construction."""

from customer_models import (
    CHECK_COLUMN,
    LandTreeProxyModel,
    NODE_KIND_ROLE,
    RecordTableModel,
    TAGS_ROLE,
)
from customer_tag_display import safe_tag_qcolor, tag_text_qcolor
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
)


def apply_land_tree_visual_style(tree, row_height=28):
    """Apply a uniform structural colour while preserving semantic model colours."""

    row_height = max(20, int(row_height))
    tree.setAlternatingRowColors(False)
    tree.setStyleSheet(
        "QTreeView { background-color: #2d2d2d; alternate-background-color: #2d2d2d; }"
        "QTreeView::item {"
        f" min-height: {row_height}px;"
        " border-bottom: 1px solid #374151;"
        " }"
        "QTreeView::item:selected { background-color: #365d8d; color: #ffffff; }"
    )


class _TreeVerticalHeaderAdapter:
    """Compatibility shim for the old table row-height setting."""

    def __init__(self, tree):
        self.tree = tree
        self.default_size = 28

    def setVisible(self, _visible):
        return None

    def setDefaultSectionSize(self, size):
        self.default_size = max(20, int(size))
        apply_land_tree_visual_style(self.tree, self.default_size)


class LandTreeView(QTreeView):
    """QTreeView with the narrow QTableView compatibility used elsewhere."""

    def __init__(self, parent=None):
        self._tag_delegate = None
        self._tag_column = None
        super().__init__(parent)
        self._vertical_header_adapter = _TreeVerticalHeaderAdapter(self)

    def setModel(self, model):
        super().setModel(model)
        self._reinstall_tag_delegate()

    def configure_tag_delegate(self, delegate, column):
        self._tag_delegate = delegate
        self._tag_column = int(column)
        self._reinstall_tag_delegate()

    def _reinstall_tag_delegate(self):
        if self._tag_delegate is not None and self._tag_column is not None:
            self.setItemDelegateForColumn(self._tag_column, self._tag_delegate)

    def horizontalHeader(self):
        return self.header()

    def verticalHeader(self):
        return self._vertical_header_adapter


class TagPillDelegate(QStyledItemDelegate):
    """Paint complete tag metadata as readable, individually coloured pills."""

    HORIZONTAL_PADDING = 8
    PILL_SPACING = 5
    VERTICAL_PADDING = 3

    @staticmethod
    def _visible_tags(option, index):
        """Tags to actually draw for this cell.

        A land group's header row shows its aggregated tags as a summary
        while collapsed. Once expanded, its child row(s) directly beneath
        already show those same tags, so the header suppresses its own
        pills to avoid painting the identical tag twice.
        """

        tags = list(index.data(TAGS_ROLE) or [])
        if tags and index.data(NODE_KIND_ROLE) == "land":
            view = option.widget
            # QTreeView tracks expansion against the column-0 index; asking
            # about any other column's index always reports collapsed.
            if isinstance(view, QAbstractItemView) and view.isExpanded(
                index.siblingAtColumn(0)
            ):
                return []
        return tags

    def paint(self, painter, option, index):
        tags = self._visible_tags(option, index)
        if not tags:
            super().paint(painter, option, index)
            return

        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        base.icon = type(base.icon)()
        style = base.widget.style() if base.widget else None
        if style is not None:
            style.drawControl(QStyle.CE_ItemViewItem, base, painter, base.widget)

        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setClipRect(option.rect)
            metrics = option.fontMetrics
            pill_height = min(
                max(metrics.height() + self.VERTICAL_PADDING * 2, 20),
                max(20, option.rect.height() - 4),
            )
            x = option.rect.left() + 6
            y = option.rect.top() + max(2, (option.rect.height() - pill_height) // 2)
            right = option.rect.right() - 5
            for position, tag in enumerate(tags):
                name = str(tag.get("name") or "").strip()
                if not name:
                    continue
                width = metrics.horizontalAdvance(name) + self.HORIZONTAL_PADDING * 2
                if x + width > right:
                    remaining = len(tags) - position
                    overflow = f"+{remaining}"
                    width = metrics.horizontalAdvance(overflow) + self.HORIZONTAL_PADDING * 2
                    if x + width <= right:
                        rect = QRect(x, y, width, pill_height)
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(safe_tag_qcolor("#64748B"))
                        painter.drawRoundedRect(rect, pill_height // 2, pill_height // 2)
                        painter.setPen(tag_text_qcolor("#64748B"))
                        painter.drawText(rect, int(Qt.AlignCenter), overflow)
                    break
                color = safe_tag_qcolor(tag.get("color"))
                rect = QRect(x, y, width, pill_height)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, pill_height // 2, pill_height // 2)
                painter.setPen(tag_text_qcolor(color.name()))
                painter.drawText(rect, int(Qt.AlignCenter), name)
                x += width + self.PILL_SPACING
        finally:
            painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        tags = self._visible_tags(option, index)
        if not tags:
            return base
        metrics = option.fontMetrics
        width = 12 + sum(
            metrics.horizontalAdvance(str(tag.get("name") or ""))
            + self.HORIZONTAL_PADDING * 2
            for tag in tags
        ) + self.PILL_SPACING * max(0, len(tags) - 1)
        height = max(base.height(), metrics.height() + self.VERTICAL_PADDING * 2 + 4)
        return QSize(width, height)


def _build_record_table(self, parent_layout, TABLE_COLUMNS, TABLE_WIDTHS):
    self.table_column_indexes = {
        key: index for index, (key, _label) in enumerate(TABLE_COLUMNS)
    }
    if self.table_column_indexes.get("checked") != CHECK_COLUMN:
        raise RuntimeError("土地清單 checkbox 欄位設定不一致。")
    self.table_model = RecordTableModel(self.on_checked_state_changed, self)
    self.table_proxy_model = LandTreeProxyModel(self)
    self.table_proxy_model.setSourceModel(self.table_model)
    self.table_view = LandTreeView()
    self.table_view.setModel(self.table_proxy_model)
    self.tag_pill_delegate = TagPillDelegate(self.table_view)
    self.table_view.configure_tag_delegate(
        self.tag_pill_delegate,
        self.table_column_indexes["tag_names"],
    )
    self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
    self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
    # Use one structural base colour for every land/ownership row. Semantic
    # colours supplied by the model (checked, overdue, note, tag, search) stay.
    apply_land_tree_visual_style(self.table_view)
    self.table_view.setWordWrap(False)
    self.table_view.setUniformRowHeights(True)
    self.table_view.setAllColumnsShowFocus(True)
    self.table_view.setRootIsDecorated(True)
    self.table_view.setItemsExpandable(True)
    self.table_view.setExpandsOnDoubleClick(False)
    self.table_view.setIndentation(22)
    self.table_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    self.table_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    self.table_view.horizontalHeader().setStretchLastSection(False)
    self.table_view.horizontalHeader().setSectionsMovable(True)
    self.table_view.horizontalHeader().sectionResized.connect(self.on_table_section_resized)
    self.table_view.horizontalHeader().sectionMoved.connect(self.on_table_section_moved)
    self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
    self.table_view.customContextMenuRequested.connect(self.show_record_menu)
    copy_action = QAction("複製", self.table_view)
    copy_action.setShortcut(QKeySequence.Copy)
    copy_action.triggered.connect(self.copy_selected_cells)
    self.table_view.addAction(copy_action)

    self.saving_table_preferences = True
    try:
        for column_index, (key, _label) in enumerate(TABLE_COLUMNS):
            self.table_view.setColumnWidth(column_index, TABLE_WIDTHS[key])

        self.apply_table_preferences()
    finally:
        self.saving_table_preferences = False

    self.table_view.selectionModel().currentRowChanged.connect(self.on_record_select)
    self.table_view.selectionModel().selectionChanged.connect(
        lambda _selected, _deselected: self.update_selection_status()
    )
    self.table_view.doubleClicked.connect(self.on_tree_double_clicked)
    self.table_view.expanded.connect(self.on_land_group_expanded)
    self.table_view.collapsed.connect(self.on_land_group_collapsed)

    parent_layout.addWidget(self.table_view)
    paging = QHBoxLayout()
    self.expand_all_button = QPushButton("全部展開")
    self.expand_all_button.clicked.connect(self.expand_all_land_groups)
    paging.addWidget(self.expand_all_button)
    self.collapse_all_button = QPushButton("全部收合")
    self.collapse_all_button.clicked.connect(self.collapse_all_land_groups)
    paging.addWidget(self.collapse_all_button)
    paging.addStretch(1)
    self.land_count_label = QLabel("土地 0 筆｜地主／所有權資料 0 筆")
    paging.addWidget(self.land_count_label)
    self.previous_land_page_button = QPushButton("上一頁")
    self.previous_land_page_button.clicked.connect(self.previous_land_page)
    paging.addWidget(self.previous_land_page_button)
    self.land_page_label = QLabel("第 1 / 1 頁")
    paging.addWidget(self.land_page_label)
    self.next_land_page_button = QPushButton("下一頁")
    self.next_land_page_button.clicked.connect(self.next_land_page)
    paging.addWidget(self.next_land_page_button)
    parent_layout.addLayout(paging)



def _build_record_menu(self):
    self.record_menu = QMenu(self)
    check_selected_context_action = QAction("勾選目前選取列", self)
    check_selected_context_action.triggered.connect(self.check_selected_rows)
    self.record_menu.addAction(check_selected_context_action)
    uncheck_selected_context_action = QAction("取消選取列勾選", self)
    uncheck_selected_context_action.triggered.connect(self.uncheck_selected_rows)
    self.record_menu.addAction(uncheck_selected_context_action)
    self.record_menu.addSeparator()
    context_field_visit_action = QAction("加入選取／勾選資料到今日行程", self)
    context_field_visit_action.triggered.connect(
        self.add_selected_records_to_field_visit
    )
    context_field_visit_action.setEnabled(bool(getattr(self, "api_mode", False)))
    context_field_visit_action.setStatusTip(
        "需使用公司筆電客戶端連線網路伺服器"
    )
    self.record_menu.addAction(context_field_visit_action)
    self.record_menu.addSeparator()
    context_case_manage_action = QAction("案件管理", self)
    context_case_manage_action.triggered.connect(self.manage_cases)
    self.record_menu.addAction(context_case_manage_action)
    context_assign_case_action = QAction("加入選取／勾選資料到案件", self)
    context_assign_case_action.triggered.connect(self.assign_checked_records_to_case)
    self.record_menu.addAction(context_assign_case_action)
    context_remove_case_action = QAction("從案件移除選取／勾選資料", self)
    context_remove_case_action.triggered.connect(self.remove_selected_records_from_case)
    self.record_menu.addAction(context_remove_case_action)
    self.record_menu.addSeparator()
    context_tags_action = QAction("設定標籤", self)
    context_tags_action.triggered.connect(self.edit_customer_tags)
    self.record_menu.addAction(context_tags_action)
    context_batch_tags_action = QAction("批量設定標籤", self)
    context_batch_tags_action.triggered.connect(self.batch_edit_customer_tags)
    self.record_menu.addAction(context_batch_tags_action)
    context_contact_action = QAction("聯絡紀錄", self)
    context_contact_action.triggered.connect(self.manage_contact_logs)
    self.record_menu.addAction(context_contact_action)
    context_follow_up_action = QAction("設定追蹤提醒", self)
    context_follow_up_action.triggered.connect(self.edit_follow_up_reminder)
    self.record_menu.addAction(context_follow_up_action)
    context_attachment_action = QAction("附件管理", self)
    context_attachment_action.triggered.connect(self.manage_attachments)
    self.record_menu.addAction(context_attachment_action)
    self.record_menu.addSeparator()
    delete_action = QAction("刪除資料", self)
    delete_action.triggered.connect(self.delete_record)
    self.record_menu.addAction(delete_action)

    self.land_menu = QMenu(self)
    open_land_action = QAction("開啟土地詳細資料", self)
    open_land_action.triggered.connect(self.open_selected_land_detail)
    self.land_menu.addAction(open_land_action)
    edit_land_action = QAction("以代表持分編輯土地資料", self)
    edit_land_action.triggered.connect(self.edit_selected_land)
    edit_land_action.setEnabled(
        self.current_user.get("role") in {"admin", "editor"}
        and not self.is_readonly_mode()
    )
    self.land_menu.addAction(edit_land_action)
    self.land_menu.addSeparator()
    check_land_action = QAction("勾選此土地全部地主／持分", self)
    check_land_action.triggered.connect(self.check_selected_rows)
    self.land_menu.addAction(check_land_action)
    uncheck_land_action = QAction("取消勾選此土地全部地主／持分", self)
    uncheck_land_action.triggered.connect(self.uncheck_selected_rows)
    self.land_menu.addAction(uncheck_land_action)

    self.api_preview_context_actions = (
        context_case_manage_action,
        context_assign_case_action,
        context_remove_case_action,
        context_tags_action,
        context_batch_tags_action,
        context_contact_action,
        context_follow_up_action,
        context_attachment_action,
        context_field_visit_action,
    )
    self.api_preview_supported_context_actions = (
        context_case_manage_action,
        context_assign_case_action,
        context_remove_case_action,
        context_tags_action,
        context_batch_tags_action,
        context_contact_action,
        context_follow_up_action,
        context_attachment_action,
        context_field_visit_action,
    )
    self.api_preview_unavailable_context_actions = ()



def _build_data_menu(self):
    self.data_menu = QMenu(self)
    batch_add_action = QAction("同地號批量新增", self)
    batch_add_action.triggered.connect(self.batch_add_shared_land_records)
    self.data_menu.addAction(batch_add_action)
    self.data_menu.addSeparator()
    import_action = QAction("匯入 .xlsx", self)
    import_action.triggered.connect(self.import_xlsx)
    self.data_menu.addAction(import_action)
    import_profiles_action = QAction("Excel 匯入設定檔", self)
    import_profiles_action.triggered.connect(self.manage_import_profiles)
    self.data_menu.addAction(import_profiles_action)
    export_selected_action = QAction("匯出選取資料", self)
    export_selected_action.triggered.connect(self.export_selected_xlsx)
    self.data_menu.addAction(export_selected_action)
    mail_duplicate_tag_action = QAction("設定寄信重複偵測標籤", self)
    mail_duplicate_tag_action.triggered.connect(self.configure_mail_duplicate_tag)
    self.data_menu.addAction(mail_duplicate_tag_action)
    export_selected_word_action = QAction("匯出選取 Word", self)
    export_selected_word_action.triggered.connect(self.export_selected_word)
    self.data_menu.addAction(export_selected_word_action)
    report_templates_action = QAction("報表與列印範本", self)
    report_templates_action.triggered.connect(self.manage_report_templates)
    self.data_menu.addAction(report_templates_action)
    self.data_menu.addSeparator()
    share_mobile_action = QAction("傳送選取資料到手機", self)
    share_mobile_action.triggered.connect(self.share_selected_to_mobile)
    self.data_menu.addAction(share_mobile_action)
    self.api_preview_supported_data_actions = (
        batch_add_action,
        import_action,
        import_profiles_action,
        export_selected_action,
        mail_duplicate_tag_action,
        export_selected_word_action,
        report_templates_action,
        share_mobile_action,
    )
    self.api_preview_unavailable_data_actions = ()



def _build_search_menu(self):
    search_menu = QMenu("搜尋與條件", self.tools_menu)
    self.tools_menu.addMenu(search_menu)
    self.tool_submenus["搜尋與條件"] = search_menu
    save_search_action = QAction("儲存目前搜尋條件", self)
    save_search_action.triggered.connect(self.save_current_search)
    search_menu.addAction(save_search_action)
    load_search_action = QAction("開啟常用條件", self)
    load_search_action.triggered.connect(self.open_saved_searches)
    search_menu.addAction(load_search_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_single_record_menu(self):
    single_record_menu = QMenu("單筆資料工具", self.tools_menu)
    self.tools_menu.addMenu(single_record_menu)
    self.tool_submenus["單筆資料工具"] = single_record_menu
    toggle_external_id_action = QAction("顯示/隱藏身分證", self)
    toggle_external_id_action.triggered.connect(self.toggle_external_id_visibility)
    single_record_menu.addAction(toggle_external_id_action)
    follow_up_action = QAction("設定追蹤提醒", self)
    follow_up_action.triggered.connect(self.edit_follow_up_reminder)
    single_record_menu.addAction(follow_up_action)
    record_history_action = QAction("查看修改歷史", self)
    record_history_action.triggered.connect(self.show_record_history)
    single_record_menu.addAction(record_history_action)
    contact_log_action = QAction("聯絡紀錄", self)
    contact_log_action.triggered.connect(self.manage_contact_logs)
    single_record_menu.addAction(contact_log_action)
    attachment_action = QAction("附件管理", self)
    attachment_action.triggered.connect(self.manage_attachments)
    single_record_menu.addAction(attachment_action)
    customer_tags_action = QAction("設定標籤", self)
    customer_tags_action.triggered.connect(self.edit_customer_tags)
    single_record_menu.addAction(customer_tags_action)
    customer_custom_values_action = QAction("設定自訂欄位", self)
    customer_custom_values_action.triggered.connect(self.edit_customer_custom_values)
    single_record_menu.addAction(customer_custom_values_action)
    apply_template_action = QAction("套用快速範本", self)
    apply_template_action.triggered.connect(self.apply_text_template)
    single_record_menu.addAction(apply_template_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_batch_menu(self):
    batch_menu = QMenu("勾選與批量操作", self.tools_menu)
    self.tools_menu.addMenu(batch_menu)
    self.tool_submenus["勾選與批量操作"] = batch_menu
    self.show_checked_only_action = QAction("僅顯示勾選資料", self)
    self.show_checked_only_action.setCheckable(True)
    self.show_checked_only_action.toggled.connect(self.toggle_checked_only)
    batch_menu.addAction(self.show_checked_only_action)
    batch_menu.addSeparator()
    check_selected_action = QAction("勾選目前選取列", self)
    check_selected_action.triggered.connect(self.check_selected_rows)
    batch_menu.addAction(check_selected_action)
    uncheck_selected_action = QAction("取消選取列勾選", self)
    uncheck_selected_action.triggered.connect(self.uncheck_selected_rows)
    batch_menu.addAction(uncheck_selected_action)
    check_visible_action = QAction("勾選目前搜尋結果", self)
    check_visible_action.triggered.connect(self.check_visible_records)
    batch_menu.addAction(check_visible_action)
    uncheck_visible_action = QAction("取消目前搜尋結果勾選", self)
    uncheck_visible_action.triggered.connect(self.uncheck_visible_records)
    batch_menu.addAction(uncheck_visible_action)
    invert_visible_action = QAction("反轉目前搜尋結果勾選", self)
    invert_visible_action.triggered.connect(self.invert_visible_checked_records)
    batch_menu.addAction(invert_visible_action)
    clear_checked_action = QAction("取消全部勾選", self)
    clear_checked_action.triggered.connect(self.clear_checked_selection)
    batch_menu.addAction(clear_checked_action)
    batch_menu.addSeparator()
    field_visit_action = QAction("加入勾選資料到今日行程", self)
    field_visit_action.triggered.connect(self.add_selected_records_to_field_visit)
    field_visit_action.setEnabled(bool(getattr(self, "api_mode", False)))
    field_visit_action.setStatusTip("需使用公司筆電客戶端連線網路伺服器")
    batch_menu.addAction(field_visit_action)
    batch_menu.addSeparator()
    batch_edit_action = QAction("批次修改勾選資料", self)
    batch_edit_action.triggered.connect(self.batch_edit_checked_records)
    batch_menu.addAction(batch_edit_action)
    merge_action = QAction("合併勾選兩筆資料", self)
    merge_action.triggered.connect(self.merge_checked_records)
    batch_menu.addAction(merge_action)
    assign_case_action = QAction("加入勾選資料到案件", self)
    assign_case_action.triggered.connect(self.assign_checked_records_to_case)
    batch_menu.addAction(assign_case_action)
    remove_case_action = QAction("從案件移除選取資料", self)
    remove_case_action.triggered.connect(self.remove_selected_records_from_case)
    batch_menu.addAction(remove_case_action)
    batch_tags_action = QAction("批量設定標籤", self)
    batch_tags_action.triggered.connect(self.batch_edit_customer_tags)
    batch_menu.addAction(batch_tags_action)
    batch_custom_values_action = QAction("批量設定自訂欄位", self)
    batch_custom_values_action.triggered.connect(self.batch_edit_custom_values)
    batch_menu.addAction(batch_custom_values_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_management_menu(self):
    management_menu = QMenu("案件與分類管理", self.tools_menu)
    self.tools_menu.addMenu(management_menu)
    self.tool_submenus["案件與分類管理"] = management_menu
    case_manage_action = QAction("案件管理", self)
    case_manage_action.triggered.connect(self.manage_cases)
    management_menu.addAction(case_manage_action)
    tag_manage_action = QAction("標籤管理", self)
    tag_manage_action.triggered.connect(self.manage_tags)
    management_menu.addAction(tag_manage_action)
    custom_field_manage_action = QAction("自訂欄位管理", self)
    custom_field_manage_action.triggered.connect(self.manage_custom_fields)
    management_menu.addAction(custom_field_manage_action)
    template_manage_action = QAction("快速範本管理", self)
    template_manage_action.triggered.connect(self.manage_text_templates)
    management_menu.addAction(template_manage_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_report_menu(self):
    report_menu = QMenu("檢查與報表", self.tools_menu)
    self.tools_menu.addMenu(report_menu)
    self.tool_submenus["檢查與報表"] = report_menu
    follow_up_list_action = QAction("追蹤提醒清單", self)
    follow_up_list_action.triggered.connect(self.show_follow_up_list)
    report_menu.addAction(follow_up_list_action)
    visit_calendar_action = QAction("行程月曆", self)
    visit_calendar_action.triggered.connect(self.show_visit_calendar)
    report_menu.addAction(visit_calendar_action)
    health_check_action = QAction("系統健康檢查", self)
    health_check_action.triggered.connect(self.show_health_check)
    report_menu.addAction(health_check_action)
    duplicate_action = QAction("智慧重複資料檢查", self)
    duplicate_action.triggered.connect(self.show_duplicate_finder)
    report_menu.addAction(duplicate_action)
    map_action = QAction("地圖與地號視覺化", self)
    map_action.triggered.connect(self.show_map_visualization)
    report_menu.addAction(map_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_danger_menu(self):
    danger_menu = QMenu("危險操作", self.tools_menu)
    self.tools_menu.addMenu(danger_menu)
    self.tool_submenus["危險操作"] = danger_menu
    delete_checked_action = QAction("刪除已勾選資料", self)
    delete_checked_action.triggered.connect(self.delete_checked_records)
    danger_menu.addAction(delete_checked_action)
    delete_all_action = QAction("刪除全部資料", self)
    delete_all_action.triggered.connect(self.delete_all_records)
    danger_menu.addAction(delete_all_action)
    encrypt_action = QAction("加密既有資料", self)
    encrypt_action.triggered.connect(self.encrypt_existing_records)
    danger_menu.addAction(encrypt_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _build_tools_menu(self):
    self.tools_menu = QMenu(self)

    notification_action = QAction("通知中心", self)
    notification_action.triggered.connect(self.show_notification_center)
    self.tools_menu.addAction(notification_action)
    workflow_action = QAction("案件工作流程與任務看板", self)
    workflow_action.triggered.connect(self.show_workflow_board)
    self.tools_menu.addAction(workflow_action)
    recycle_action = QAction("回收桶", self)
    recycle_action.triggered.connect(self.show_recycle_bin)
    self.tools_menu.addAction(recycle_action)
    undo_action = QAction("復原批次操作", self)
    undo_action.triggered.connect(self.show_undo_operations)
    self.tools_menu.addAction(undo_action)
    self.tools_menu.addSeparator()

    advanced_search_action = QAction("進階搜尋", self)
    advanced_search_action.setStatusTip("開啟多條件搜尋。")
    advanced_search_action.triggered.connect(self.open_advanced_search)
    self.tools_menu.addAction(advanced_search_action)

    data_quality_action = QAction("資料品質檢查", self)
    data_quality_action.setStatusTip("檢查缺漏、數字格式、分母為 0 與疑似重複。")
    data_quality_action.triggered.connect(self.run_data_quality_check)
    self.tools_menu.addAction(data_quality_action)

    dashboard_action = QAction("資料統計儀表板", self)
    dashboard_action.setStatusTip("查看總筆數、面積、現值、地區/地段與追蹤統計。")
    dashboard_action.triggered.connect(self.show_dashboard)
    self.tools_menu.addAction(dashboard_action)
    self.tools_menu.addSeparator()

    actions = {name: value for name, value in locals().items() if name.endswith("_action")}
    for builder in (
        _build_search_menu,
        _build_single_record_menu,
        _build_batch_menu,
        _build_management_menu,
        _build_report_menu,
        _build_danger_menu,
    ):
        actions.update(builder(self))
    return actions


def _build_settings_menu(self):
    self.settings_menu = QMenu(self)
    server_connection_action = QAction("伺服器連線設定", self)
    server_connection_action.triggered.connect(self.configure_server_connection)
    if self.api_mode:
        self.settings_menu.addAction(server_connection_action)
        self.settings_menu.addSeparator()
    watchlist_action = QAction("注意名單管理", self)
    watchlist_action.triggered.connect(self.manage_watchlist)
    self.settings_menu.addAction(watchlist_action)
    operation_log_action = QAction("操作記錄", self)
    operation_log_action.triggered.connect(self.show_operation_logs)
    self.settings_menu.addAction(operation_log_action)
    user_management_action = QAction("使用者與權限", self)
    user_management_action.triggered.connect(self.manage_users)
    self.settings_menu.addAction(user_management_action)
    font_size_action = QAction("字體大小", self)
    font_size_action.triggered.connect(self.change_font_size)
    self.settings_menu.addAction(font_size_action)
    column_visibility_action = QAction("欄位顯示", self)
    column_visibility_action.triggered.connect(self.change_column_visibility)
    self.settings_menu.addAction(column_visibility_action)
    self.readonly_mode_action = QAction("唯讀模式", self)
    self.readonly_mode_action.setCheckable(True)
    self.readonly_mode_action.setChecked(self.is_readonly_mode())
    self.readonly_mode_action.toggled.connect(self.toggle_readonly_mode)
    self.settings_menu.addAction(self.readonly_mode_action)
    change_password_action = QAction("修改密碼", self)
    change_password_action.triggered.connect(self.change_password)
    self.settings_menu.addAction(change_password_action)
    self.settings_menu.addSeparator()
    backup_status_action = QAction("備份狀態", self)
    backup_status_action.triggered.connect(self.show_backup_status)
    self.settings_menu.addAction(backup_status_action)
    backup_management_action = QAction("備份管理", self)
    backup_management_action.triggered.connect(self.manage_backups)
    self.settings_menu.addAction(backup_management_action)
    external_backup_action = QAction("異地完整備份", self)
    external_backup_action.triggered.connect(self.manage_external_backups)
    self.settings_menu.addAction(external_backup_action)
    backup_now_action = QAction("立即備份", self)
    backup_now_action.triggered.connect(self.backup_now)
    self.settings_menu.addAction(backup_now_action)
    restore_backup_action = QAction("還原備份", self)
    restore_backup_action.triggered.connect(self.restore_backup)
    self.settings_menu.addAction(restore_backup_action)
    open_backup_action = QAction("開啟備份資料夾", self)
    open_backup_action.triggered.connect(self.open_backup_folder)
    self.settings_menu.addAction(open_backup_action)
    attachment_check_action = QAction("檢查納管附件", self)
    attachment_check_action.triggered.connect(self.verify_managed_attachments)
    self.settings_menu.addAction(attachment_check_action)
    self.settings_menu.addSeparator()
    help_action = QAction("使用說明", self)
    help_action.triggered.connect(self.show_help)
    self.settings_menu.addAction(help_action)
    about_action = QAction("關於系統", self)
    about_action.triggered.connect(self.show_about)
    self.settings_menu.addAction(about_action)

    return {name: value for name, value in locals().items() if name.endswith("_action")}


def _configure_api_action_groups(self, actions):
    self.api_supported_tool_actions = (
        actions["advanced_search_action"],
        actions["save_search_action"],
        actions["load_search_action"],
        actions["toggle_external_id_action"],
        actions["follow_up_action"],
        actions["record_history_action"],
        actions["contact_log_action"],
        actions["attachment_action"],
        actions["customer_tags_action"],
        actions["customer_custom_values_action"],
        actions["apply_template_action"],
        self.show_checked_only_action,
        actions["check_selected_action"],
        actions["uncheck_selected_action"],
        actions["check_visible_action"],
        actions["uncheck_visible_action"],
        actions["invert_visible_action"],
        actions["clear_checked_action"],
        actions["field_visit_action"],
        actions["batch_edit_action"],
        actions["assign_case_action"],
        actions["remove_case_action"],
        actions["batch_tags_action"],
        actions["batch_custom_values_action"],
        actions["case_manage_action"],
        actions["tag_manage_action"],
        actions["custom_field_manage_action"],
        actions["template_manage_action"],
        actions["data_quality_action"],
        actions["dashboard_action"],
        actions["follow_up_list_action"],
        actions["visit_calendar_action"],
        actions["health_check_action"],
        actions["duplicate_action"],
        actions["map_action"],
        actions["delete_checked_action"],
        actions["delete_all_action"],
        actions["notification_action"],
        actions["workflow_action"],
        actions["recycle_action"],
        actions["undo_action"],
        actions["merge_action"],
        actions["encrypt_action"],
    )
    self.api_unavailable_tool_actions = ()
    self.api_supported_settings_actions = (
        actions["server_connection_action"],
        actions["watchlist_action"],
        actions["operation_log_action"],
        actions["font_size_action"],
        actions["column_visibility_action"],
        self.readonly_mode_action,
        actions["attachment_check_action"],
        actions["help_action"],
        actions["about_action"],
        actions["user_management_action"],
        actions["change_password_action"],
        actions["backup_status_action"],
        actions["backup_management_action"],
        actions["backup_now_action"],
        actions["open_backup_action"],
        actions["external_backup_action"],
        actions["restore_backup_action"],
    )
    self.api_admin_only_settings_actions = (
        actions["user_management_action"],
        actions["backup_management_action"],
        actions["backup_now_action"],
        actions["open_backup_action"],
        actions["external_backup_action"],
        actions["restore_backup_action"],
    )
    self.api_unavailable_settings_actions = ()


def build_customer_table_ui(self, parent_layout, TABLE_COLUMNS, TABLE_WIDTHS):
    _build_record_table(self, parent_layout, TABLE_COLUMNS, TABLE_WIDTHS)
    _build_record_menu(self)
    _build_data_menu(self)
    actions = _build_tools_menu(self)
    actions.update(_build_settings_menu(self))
    _configure_api_action_groups(self, actions)
