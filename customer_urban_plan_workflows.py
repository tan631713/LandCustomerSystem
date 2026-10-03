"""Desktop 都市計畫 workflows: view switching, 輸入到, management, batch assignment."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
)

from customer_land_details import LandDetailsDialog
from customer_land_tree import group_land_records
from customer_urban_plan_dialogs import (
    DeleteUrbanPlanDialog,
    SetUrbanPlanDialog,
    UrbanPlanManagementDialog,
)
from customer_urban_plan_tree import (
    LEVEL_LABELS,
    UNASSIGNED_PLAN_ID,
    UNASSIGNED_PLAN_NAME,
    build_plan_tree,
    default_expanded_keys,
)
from customer_urban_plan_view import UrbanPlanTreeView

VIEW_SETTING_KEY = "urban_plan_view"
INPUT_SETTING_KEY = "urban_plan_input"
LEGACY_VIEW = "legacy"
ALL_VIEW = "all"
HINT_STYLE = "color: #8b98ab; font-size: 12px;"
UNSUPPORTED_TEXT = "家中伺服器還不支援都市計畫，請先把伺服器更新到新版。"


def view_mode_text(mode):
    kind, plan_id = mode
    if kind == "plan":
        return f"plan:{int(plan_id)}"
    return kind


def parse_view_mode(text):
    text = str(text or "").strip()
    if text.startswith("plan:"):
        try:
            return ("plan", max(0, int(text[5:])))
        except ValueError:
            return (LEGACY_VIEW, None)
    if text == ALL_VIEW:
        return (ALL_VIEW, None)
    return (LEGACY_VIEW, None)


class UrbanPlanWorkflowMixin:
    # -- construction ---------------------------------------------------------

    def init_urban_plan_state(self):
        self.urban_plans = []
        self.urban_plan_unassigned = {}
        self.urban_plans_supported = False
        self.urban_plan_mode = (LEGACY_VIEW, None)
        self.urban_plan_input_id = UNASSIGNED_PLAN_ID
        self.urban_plan_view = None
        self.urban_plan_tree = None
        self.table_stack = None
        self.plan_view_combo = None
        self.plan_input_combo = None
        self.urban_plan_form_combo = None
        self.expand_all_button = None
        self.collapse_all_button = None
        self.plan_hint_label = None
        self._urban_plan_rows = None
        self._urban_plan_stale = True

    def build_urban_plan_row(self, parent_layout):
        """Row 2 of the list: 檢視, 輸入到 and the expand/collapse buttons."""

        row = QHBoxLayout()
        row.setSpacing(6)
        self.plan_view_label = QLabel("檢視")
        self.plan_view_combo = QComboBox()
        self.plan_view_combo.setObjectName("planViewCombo")
        self.plan_view_combo.setMinimumWidth(140)
        self.plan_view_combo.setToolTip("選擇其中一個都市計畫時，清單只會顯示那個都市計畫。")
        self.plan_input_label = QLabel("輸入到")
        self.plan_input_combo = QComboBox()
        self.plan_input_combo.setObjectName("planInputCombo")
        self.plan_input_combo.setMinimumWidth(140)
        self.plan_input_combo.setToolTip("新增資料與匯入 Excel 時，預設歸入這個都市計畫。")
        self.expand_all_button = QPushButton("全部展開")
        self.expand_all_button.clicked.connect(self.expand_all_land_groups)
        self.collapse_all_button = QPushButton("全部收合")
        self.collapse_all_button.clicked.connect(self.collapse_all_land_groups)
        self.plan_hint_label = QLabel("")
        self.plan_hint_label.setObjectName("planHintLabel")
        self.plan_hint_label.setStyleSheet(HINT_STYLE)
        # The hint is a nicety: it must never make the row wider than the list
        # pane (that squeezes the selectors); it clips instead.
        self.plan_hint_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.plan_hint_label.setMinimumWidth(0)
        for widget in (
            self.plan_view_label,
            self.plan_view_combo,
            self.plan_input_label,
            self.plan_input_combo,
        ):
            row.addWidget(widget)
        row.addSpacing(6)
        row.addWidget(self.expand_all_button)
        row.addWidget(self.collapse_all_button)
        row.addSpacing(8)
        row.addWidget(self.plan_hint_label, 1)
        parent_layout.addLayout(row)
        self.plan_view_combo.currentIndexChanged.connect(self.on_plan_view_combo_changed)
        self.plan_input_combo.currentIndexChanged.connect(self.on_plan_input_combo_changed)

    def build_urban_plan_stack(self, parent_layout):
        """The list area: the land tree (舊) or the plan tree, one at a time."""

        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table_view)
        view = UrbanPlanTreeView()
        view.checked_ids_provider = lambda: self.checked_record_ids
        view.nodeSelected.connect(self.on_plan_node_selected)
        view.nodeActivated.connect(self.on_plan_node_activated)
        view.checkRequested.connect(self.on_plan_check_requested)
        view.customContextMenuRequested.connect(self.show_plan_menu)
        self.urban_plan_view = view
        self.table_stack.addWidget(view)
        parent_layout.addWidget(self.table_stack, 1)

    # -- availability and settings -----------------------------------------------

    def urban_plans_available(self):
        return bool(self.api_mode and self.urban_plans_supported)

    def plan_view_active(self):
        return (
            self.urban_plans_available()
            and self.urban_plan_view is not None
            and self.urban_plan_mode[0] != LEGACY_VIEW
        )

    def plan_filter_value(self):
        kind, plan_id = self.urban_plan_mode
        return int(plan_id) if kind == "plan" else None

    def plan_name(self, plan_id):
        if not plan_id:
            return UNASSIGNED_PLAN_NAME
        for plan in self.urban_plans:
            if int(plan.get("plan_id") or 0) == int(plan_id):
                return str(plan.get("name") or "")
        return ""

    def init_urban_plans(self):
        """Ask the server for the plan list once; hide the controls if it can't."""

        self.urban_plans_supported = False
        if self.api_mode:
            try:
                data = self.active_record_repository().list_urban_plans(refresh=True)
                self.urban_plans = [dict(item) for item in data.get("items") or []]
                self.urban_plan_unassigned = dict(data.get("unassigned") or {})
                self.urban_plans_supported = True
            except Exception:  # noqa: BLE001 - an older server simply has no plans
                self.urban_plans = []
        mode = parse_view_mode(self.repository.get_setting(VIEW_SETTING_KEY, LEGACY_VIEW))
        try:
            self.urban_plan_input_id = max(
                0, int(self.repository.get_setting(INPUT_SETTING_KEY, "0") or 0)
            )
        except (TypeError, ValueError):
            self.urban_plan_input_id = UNASSIGNED_PLAN_ID
        self.urban_plan_mode = self._valid_view_mode(mode)
        self.apply_urban_plan_availability()

    def _valid_view_mode(self, mode):
        if not self.urban_plans_available():
            return (LEGACY_VIEW, None)
        if mode[0] == "plan" and mode[1] and not self.plan_name(mode[1]):
            return (ALL_VIEW, None)
        return mode

    def apply_urban_plan_availability(self):
        available = self.urban_plans_available()
        for widget in (
            self.plan_view_label,
            self.plan_view_combo,
            self.plan_input_label,
            self.plan_input_combo,
        ):
            if widget is not None:
                widget.setVisible(available)
        if self.urban_plan_input_id and not self.plan_name(self.urban_plan_input_id):
            self.urban_plan_input_id = UNASSIGNED_PLAN_ID
        self.populate_urban_plan_combos()
        container = getattr(self, "form_field_containers", {}).get("urban_plan")
        if container is not None:
            container.setVisible(available)
        self.apply_plan_view_mode_to_widgets()

    def populate_urban_plan_combos(self):
        combos = (self.plan_view_combo, self.plan_input_combo, self.urban_plan_form_combo)
        for combo in combos:
            if combo is not None:
                combo.blockSignals(True)
        try:
            if self.plan_view_combo is not None:
                self.plan_view_combo.clear()
                self.plan_view_combo.addItem("依土地（舊）", LEGACY_VIEW)
                self.plan_view_combo.addItem("全部都市計畫", ALL_VIEW)
                for plan in self.urban_plans:
                    self.plan_view_combo.addItem(
                        str(plan.get("name") or ""), f"plan:{int(plan['plan_id'])}"
                    )
                self.plan_view_combo.addItem(UNASSIGNED_PLAN_NAME, f"plan:{UNASSIGNED_PLAN_ID}")
                index = self.plan_view_combo.findData(view_mode_text(self.urban_plan_mode))
                self.plan_view_combo.setCurrentIndex(max(0, index))
            if self.plan_input_combo is not None:
                self.plan_input_combo.clear()
                self.plan_input_combo.addItem("不指定（未分類）", UNASSIGNED_PLAN_ID)
                for plan in self.urban_plans:
                    self.plan_input_combo.addItem(
                        str(plan.get("name") or ""), int(plan["plan_id"])
                    )
                index = self.plan_input_combo.findData(self.urban_plan_input_id)
                self.plan_input_combo.setCurrentIndex(max(0, index))
            if self.urban_plan_form_combo is not None:
                keep = self.urban_plan_form_value()
                self.urban_plan_form_combo.clear()
                self.urban_plan_form_combo.addItem(UNASSIGNED_PLAN_NAME, UNASSIGNED_PLAN_ID)
                for plan in self.urban_plans:
                    self.urban_plan_form_combo.addItem(
                        str(plan.get("name") or ""), int(plan["plan_id"])
                    )
                self.set_urban_plan_form_value(keep)
        finally:
            for combo in combos:
                if combo is not None:
                    combo.blockSignals(False)

    def apply_plan_view_mode_to_widgets(self):
        """Stack page, page controls and hint text for the current mode."""

        active = self.plan_view_active()
        if self.table_stack is not None:
            self.table_stack.setCurrentIndex(1 if active else 0)
        for widget in (
            self.previous_land_page_button,
            self.land_page_label,
            self.next_land_page_button,
        ):
            if widget is not None:
                widget.setVisible(not active)
        if self.plan_hint_label is not None:
            kind, plan_id = self.urban_plan_mode
            if not self.urban_plans_available():
                self.plan_hint_label.setText("")
            elif kind == "plan":
                self.plan_hint_label.setText(f"只顯示「{self.plan_name(plan_id)}」")
            elif kind == ALL_VIEW:
                self.plan_hint_label.setText("勾選上層可整批勾選底下的資料")
            else:
                self.plan_hint_label.setText("選「全部都市計畫」可分類檢視")

    # -- view switching -------------------------------------------------------------

    def on_plan_view_combo_changed(self, _index):
        mode = parse_view_mode(self.plan_view_combo.currentData())
        self.set_plan_view_mode(mode)

    def set_plan_view_mode(self, mode, *, remember=True):
        mode = self._valid_view_mode(mode)
        previous = self.urban_plan_mode
        self.urban_plan_mode = mode
        if remember:
            self.repository.set_setting(VIEW_SETTING_KEY, view_mode_text(mode))
        if self.plan_view_combo is not None:
            index = self.plan_view_combo.findData(view_mode_text(mode))
            if index >= 0 and index != self.plan_view_combo.currentIndex():
                self.plan_view_combo.blockSignals(True)
                self.plan_view_combo.setCurrentIndex(index)
                self.plan_view_combo.blockSignals(False)
        if self.urban_plan_view is not None and mode != previous:
            self.urban_plan_view.expanded_keys = None  # back to the default opening
        self.apply_plan_view_mode_to_widgets()
        if self.plan_view_active():
            self.refresh_urban_plan_view(force=True)
        if mode != previous:
            self.update_land_page_status()

    def on_plan_input_combo_changed(self, _index):
        self.urban_plan_input_id = int(self.plan_input_combo.currentData() or UNASSIGNED_PLAN_ID)
        self.repository.set_setting(INPUT_SETTING_KEY, str(self.urban_plan_input_id))
        if self.selected_record_id is None:
            self.set_urban_plan_form_value(self.urban_plan_input_id)

    # -- the plan view ----------------------------------------------------------------

    def refresh_urban_plan_view(self, rows=None, *, force=False):
        """Rebuild the plan tree from the processed rows (cheap no-op otherwise)."""

        if not self.urban_plans_available() or self.urban_plan_view is None:
            return
        if rows is not None:
            self._urban_plan_rows = rows
            self._urban_plan_stale = True
        if not self.plan_view_active():
            return  # rebuilt when the user switches to it
        if not (self._urban_plan_stale or force):
            return
        source = self._urban_plan_rows
        if source is None:
            source = list(self.table_model.all_rows) if self.table_model is not None else []
        searching = bool(self.land_search_is_active())
        tree = build_plan_tree(
            source,
            self.urban_plans,
            plan_filter=self.plan_filter_value(),
            include_empty_plans=not searching,
        )
        self.urban_plan_tree = tree
        self._urban_plan_stale = False
        self.urban_plan_view.empty_text = (
            "沒有符合搜尋條件的資料" if searching else "這裡還沒有資料"
        )
        if self.urban_plan_view.expanded_keys is None and self.plan_filter_value() is not None:
            self.urban_plan_view.expanded_keys = default_expanded_keys(tree, depth=2)
        self.urban_plan_view.set_tree(
            tree,
            expand_all=searching and bool(source),
            select_record_id=self.selected_record_id,
        )
        self.update_urban_plan_summary()

    def update_urban_plan_summary(self):
        tree = self.urban_plan_tree
        if self.land_count_label is None or tree is None:
            return
        kind, plan_id = self.urban_plan_mode
        head = (
            f"{self.plan_name(plan_id)}"
            if kind == "plan"
            else f"都市計畫 {tree.plan_count:,} 個"
        )
        self.land_count_label.setText(
            f"{head}｜土地 {tree.land_count:,} 筆｜地主 {tree.owner_count:,} 位｜"
            f"持分 {tree.share_count:,} 筆｜面積 {tree.area:,.2f} ㎡"
        )

    def update_urban_plan_view_metrics(self, row_height):
        if self.urban_plan_view is not None:
            self.urban_plan_view.set_row_height(row_height)

    def urban_plan_checks_changed(self):
        if self.plan_view_active():
            self.urban_plan_view.refresh_check_states()

    # -- selection and menus ----------------------------------------------------------

    def on_plan_node_selected(self, node):
        if node.kind == "owner":
            record_id = int(node.record["id"])
            # Keeps the hidden land tree on the same row (it is what a save
            # refreshes against) and loads the form through its usual handler.
            self.select_record_in_table(record_id)
            if self.selected_record_id != record_id:
                self.load_record(record_id)
            return
        if node.kind == "land" and node.land_ids:
            self.selected_land_state_id = node.land_ids[0]
        self.statusBar().showMessage(
            f"已選取{LEVEL_LABELS[node.kind]}：{node.title}｜"
            f"{node.owner_count:,} 位地主／{node.share_count:,} 筆持分",
            3500,
        )

    def on_plan_node_activated(self, node):
        if node.kind == "owner":
            self.load_record(int(node.record["id"]))
            if getattr(self, "detail_tabs", None) is not None:
                self.detail_tabs.setCurrentIndex(0)
        elif node.kind == "land":
            group = self.plan_land_group(node)
            if group is not None:
                self._show_non_modal_dialog(LandDetailsDialog(group, self))
        else:
            item = self.urban_plan_view._items.get(node.key)
            if item is not None:
                item.setExpanded(not item.isExpanded())

    def plan_land_group(self, node):
        land = node if node.kind == "land" else node.parent if node.kind == "owner" else None
        if land is None or not land.children:
            return None
        groups = group_land_records([child.record for child in land.children]).groups
        return groups[0] if groups else None

    def plan_selected_land_group(self):
        node = self.urban_plan_view.current_node() if self.urban_plan_view is not None else None
        return None if node is None else self.plan_land_group(node)

    def on_plan_check_requested(self, record_ids, checked):
        self.update_checked_records(record_ids, checked, "勾選" if checked else "取消勾選")

    def show_plan_menu(self, position):
        view = self.urban_plan_view
        item = view.itemAt(position)
        if item is None:
            return
        view.select_node_for_context_menu(item)
        node = item.node
        if node.kind == "owner":
            if self.selected_record_id != int(node.record["id"]):
                self.on_plan_node_selected(node)
            menu = self.record_menu
        elif node.kind == "land":
            menu = self.land_menu
        else:
            menu = self.build_plan_group_menu(node)
        if menu is not None:
            menu.exec(view.viewport().mapToGlobal(position))

    def build_plan_group_menu(self, node):
        menu = QMenu(self)
        label = f"{LEVEL_LABELS[node.kind]}「{node.title}」"
        check = QAction(f"勾選{label}的全部資料", menu)
        check.triggered.connect(
            lambda: self.update_checked_records(node.record_ids, True, f"勾選{label}")
        )
        uncheck = QAction(f"取消勾選{label}的全部資料", menu)
        uncheck.triggered.connect(
            lambda: self.update_checked_records(node.record_ids, False, f"取消勾選{label}")
        )
        menu.addAction(check)
        menu.addAction(uncheck)
        menu.addSeparator()
        assign = QAction("設定都市計畫…", menu)
        assign.triggered.connect(self.set_urban_plan_for_selection)
        menu.addAction(assign)
        return menu

    # -- management ------------------------------------------------------------------------

    def _plans_require_support(self):
        if self.urban_plans_available():
            return True
        self._app_component("QMessageBox").information(
            self, "不支援都市計畫", UNSUPPORTED_TEXT if self.api_mode else "都市計畫需要連線到家中伺服器。"
        )
        return False

    def reload_urban_plans(self):
        data = self.active_record_repository().list_urban_plans(refresh=True)
        self.urban_plans = [dict(item) for item in data.get("items") or []]
        self.urban_plan_unassigned = dict(data.get("unassigned") or {})
        known = {int(plan["plan_id"]) for plan in self.urban_plans}
        if self.urban_plan_input_id and self.urban_plan_input_id not in known:
            self.urban_plan_input_id = UNASSIGNED_PLAN_ID
            self.repository.set_setting(INPUT_SETTING_KEY, "0")
        self.urban_plan_mode = self._valid_view_mode(self.urban_plan_mode)
        self.populate_urban_plan_combos()
        self.apply_plan_view_mode_to_widgets()

    def manage_urban_plans(self):
        if not self._plans_require_support():
            return
        repository = self.active_record_repository()
        can_edit = (
            self.current_user.get("role") != "viewer" and not self.is_readonly_mode()
        )
        had_plans = bool(self.urban_plans)

        def delete_plan(plan):
            confirm = DeleteUrbanPlanDialog(plan, dialog)
            if confirm.exec() != QDialog.Accepted:
                return False
            result = repository.delete_urban_plan(int(plan["plan_id"]))
            released = int(result.get("released_land_count") or 0)
            self.statusBar().showMessage(
                f"已刪除「{plan.get('name')}」，{released:,} 筆土地回到「未分類」。", 5000
            )
            return True

        dialog = UrbanPlanManagementDialog(
            lambda: repository.list_urban_plans(refresh=True),
            lambda name: repository.save_urban_plan(name),
            lambda plan_id, name: repository.save_urban_plan(name, plan_id),
            delete_plan,
            self,
            can_edit=can_edit,
        )
        self.urban_plan_management_dialog = dialog

        def finished():
            self.urban_plan_management_dialog = None
            if not dialog.changed:
                return
            try:
                self.reload_urban_plans()
            except Exception as exc:  # noqa: BLE001
                self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
                return
            if not had_plans and self.urban_plans and self.urban_plan_mode[0] == LEGACY_VIEW:
                self.set_plan_view_mode((ALL_VIEW, None))
            self.refresh_records(self.selected_record_id)

        self._show_non_modal_dialog(dialog, on_finished=finished)

    def set_urban_plan_for_selection(self):
        if not self._plans_require_support():
            return
        if not self.ensure_can_modify("設定都市計畫"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(
                self, "未選取資料", "請先選取或勾選要設定都市計畫的資料。"
            )
            return
        if not self.urban_plans:
            self._app_component("QMessageBox").information(
                self, "尚無都市計畫", "請先建立都市計畫。"
            )
            self.manage_urban_plans()
            return
        repository = self.active_record_repository()
        land_plans = {}
        for row in repository.fetch_customers_by_ids(record_ids):
            land_id = row.get("land_id")
            if land_id not in (None, ""):
                land_plans[int(land_id)] = int(row.get("urban_plan_id") or 0)
        if not land_plans:
            self._app_component("QMessageBox").warning(self, "沒有土地", "選取的資料沒有對應的土地。")
            return
        dialog = SetUrbanPlanDialog(
            self.urban_plans,
            land_plans,
            len(record_ids),
            self,
            default_plan_id=self.urban_plan_input_id or None,
        )

        def on_accepted():
            tree_state = self.capture_land_tree_view_state()
            try:
                result = repository.set_lands_urban_plan(
                    dialog.land_ids(), dialog.plan_id(), dialog.only_unassigned()
                )
            except Exception as exc:  # noqa: BLE001 - DesktopApiError / ValueError text
                self._app_component("QMessageBox").critical(self, "設定失敗", str(exc))
                return
            updated = int(result.get("updated_count") or 0)
            target = self.plan_name(dialog.plan_id())
            self.refresh_after_management_content_update(tree_state)
            self._app_component("QMessageBox").information(
                self, "完成", f"已將 {updated:,} 筆土地設定為「{target}」。"
            )

        self._show_non_modal_dialog(dialog, on_accepted=on_accepted)

    # -- the record form -------------------------------------------------------------------------

    def urban_plan_form_value(self):
        combo = self.urban_plan_form_combo
        if combo is None:
            return UNASSIGNED_PLAN_ID
        return int(combo.currentData() or UNASSIGNED_PLAN_ID)

    def load_urban_plan_into_form(self, row):
        if self.urban_plan_form_combo is None:
            return
        keys = row.keys() if hasattr(row, "keys") else ()
        self.set_urban_plan_form_value(
            row["urban_plan_id"] if "urban_plan_id" in keys else None,
            row["urban_plan_name"] if "urban_plan_name" in keys else None,
        )

    def set_urban_plan_form_value(self, plan_id, plan_name=None):
        combo = self.urban_plan_form_combo
        if combo is None:
            return
        plan_id = int(plan_id or 0)
        index = combo.findData(plan_id)
        if index < 0 and plan_id:
            # A plan another user created since this window listed them.
            combo.addItem(str(plan_name or f"都市計畫 {plan_id}"), plan_id)
            index = combo.findData(plan_id)
        combo.setCurrentIndex(max(0, index))
