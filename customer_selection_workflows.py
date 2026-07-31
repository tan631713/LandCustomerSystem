"""Desktop table selection and checked-record workflows."""

from customer_preferences import encode_table_preferences
from PySide6.QtCore import QTimer


class SelectionWorkflowMixin:
    def set_checked_record_id(self, record_id, checked):
        """Single checked-ID update shared by checkbox and context actions."""

        record_id = int(record_id)
        already_checked = record_id in self.checked_record_ids
        if checked:
            self.checked_record_ids.add(record_id)
        else:
            self.checked_record_ids.discard(record_id)
        return already_checked != bool(checked)

    def selected_or_checked_record_ids(self):
        ids = set(self.checked_record_ids)
        ids.update(self.selected_table_record_ids())
        return sorted(ids)

    def selected_table_record_ids(self):
        if self.table_view is None or self.table_view.selectionModel() is None:
            return []
        record_ids = set()
        seen_nodes = set()
        for proxy_index in self.table_view.selectionModel().selectedIndexes():
            if not proxy_index.isValid():
                continue
            source_index = self.source_table_index(proxy_index)
            node = self.table_model.node_for_index(source_index)
            if node is None:
                continue
            node_key = (
                node.kind,
                node.group.state_id,
                None if node.record is None else int(node.record["id"]),
            )
            if node_key in seen_nodes:
                continue
            seen_nodes.add(node_key)
            record_ids.update(self.table_model.record_ids_for_index(source_index))
        if not record_ids and self.selected_record_id is not None:
            record_ids.add(self.selected_record_id)
        return sorted(record_ids)

    def current_result_record_ids(self):
        if self.table_model is None:
            return []
        return [row["id"] for row in self.table_model.load_all()]

    def update_checked_records(self, record_ids, checked, action_label):
        ids = sorted({int(record_id) for record_id in record_ids})
        if not ids:
            self._app_component("QMessageBox").information(self, "沒有資料", "目前沒有可處理的資料。")
            return 0
        changed = 0
        for record_id in ids:
            if self.set_checked_record_id(record_id, checked):
                changed += 1
            self.table_model.update_checked_state(record_id, record_id in self.checked_record_ids)
        if changed:
            self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"{action_label}：{changed} 筆，已勾選 {len(self.checked_record_ids)} 筆")
        return changed

    def check_selected_rows(self):
        ids = self.selected_table_record_ids()
        if not ids:
            self._app_component("QMessageBox").information(self, "尚未選取", "請先在表格中選取一列或多列。")
            return
        self.update_checked_records(ids, True, "勾選選取列")

    def uncheck_selected_rows(self):
        ids = self.selected_table_record_ids()
        if not ids:
            self._app_component("QMessageBox").information(self, "尚未選取", "請先在表格中選取一列或多列。")
            return
        self.update_checked_records(ids, False, "取消選取列勾選")

    def check_visible_records(self):
        self.update_checked_records(self.current_result_record_ids(), True, "勾選目前搜尋結果")

    def uncheck_visible_records(self):
        self.update_checked_records(self.current_result_record_ids(), False, "取消目前搜尋結果勾選")

    def invert_visible_checked_records(self):
        ids = self.current_result_record_ids()
        if not ids:
            self._app_component("QMessageBox").information(self, "沒有資料", "目前搜尋結果沒有可反轉的資料。")
            return
        changed = 0
        for record_id in ids:
            if record_id in self.checked_record_ids:
                self.checked_record_ids.discard(record_id)
            else:
                self.checked_record_ids.add(record_id)
            changed += 1
            self.table_model.update_checked_state(record_id, record_id in self.checked_record_ids)
        if changed:
            self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"已反轉目前搜尋結果 {changed} 筆，已勾選 {len(self.checked_record_ids)} 筆")

    def clear_checked_selection(self):
        count = len(self.checked_record_ids)
        if not count:
            self.update_selection_status("目前沒有已勾選資料")
            return
        ids = sorted(self.checked_record_ids)
        self.checked_record_ids.clear()
        for record_id in ids:
            self.table_model.update_checked_state(record_id, False)
        self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"已取消全部勾選：{count} 筆")

    def update_selection_status(self, message=None):
        if self.table_view is None or self.table_model is None:
            return
        if message:
            self.statusBar().showMessage(message, 3500)
            return
        selected_land_ids = set()
        selected_ownership_ids = set()
        for proxy_index in self.table_view.selectionModel().selectedIndexes():
            if not proxy_index.isValid() or proxy_index.column() != 0:
                continue
            source_index = self.source_table_index(proxy_index)
            node = self.table_model.node_for_index(source_index)
            if node is None:
                continue
            if node.kind == "land":
                selected_land_ids.add(node.group.state_id)
            else:
                selected_ownership_ids.add(int(node.record["id"]))
        checked_count = len(self.checked_record_ids)
        if selected_land_ids or selected_ownership_ids or checked_count:
            self.statusBar().showMessage(
                f"已選取土地 {len(selected_land_ids)} 筆／"
                f"持分 {len(selected_ownership_ids)} 筆；"
                f"已勾選持分 {checked_count} 筆",
                2500,
            )

    def selected_record_plain_data(self):
        if self.selected_record_id is None:
            return None, None
        row = self.active_record_repository().get_customer(self.selected_record_id)
        if row is None:
            return None, None
        return row, self.get_plain_record_data(row)

    def filter_management_records(self, field_key, value):
        value = str(value or "").strip()
        if not value:
            return
        self.advanced_search_criteria = {}
        self.repository.set_setting(self.advanced_search_setting_key, encode_table_preferences({}))
        self.search_input.setText(value)
        index = self.filter_field_combo.findData(field_key)
        self.filter_field_combo.blockSignals(True)
        try:
            self.filter_field_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.filter_field_combo.blockSignals(False)
        self.refresh_records_for_search()
        self.statusBar().showMessage(f"已顯示「{value}」相關資料。", 3500)

    def on_checked_state_changed(self, record_id, checked):
        self.set_checked_record_id(record_id, checked)
        self.schedule_selection_state_save()
        self.update_selection_status()
        # A native checkbox click must remain an in-place model update.  A
        # whole-query refresh here destroys the mouse interaction lifecycle
        # and can reset tree expansion/selection state.

    def toggle_checked_only(self, enabled):
        self.show_checked_only = enabled
        self.refresh_records_for_search()
        message = "目前僅顯示勾選資料" if enabled else "已顯示全部符合條件的資料"
        self.statusBar().showMessage(message, 2500)

    def eventFilter(self, watched, event):
        return super().eventFilter(watched, event)
