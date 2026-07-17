"""Persistent table layout and row-selection state for the Qt application."""

import json

from customer_dialogs import ColumnVisibilityDialog
from PySide6.QtWidgets import QDialog

TABLE_COLUMNS = ()
TABLE_WIDTHS = {}
TABLE_PREFS_SETTING_KEY = "table_preferences"
CHECKED_RECORDS_SETTING_KEY = "checked_record_ids"
SELECTED_RECORD_SETTING_KEY = "selected_record_id"
GET_SETTING = None
SET_SETTING = None
ENCODE_PREFERENCES = None
DECODE_PREFERENCES = None


def configure_ui_state(**dependencies):
    globals().update(dependencies)


class UiStateMixin:
    def restore_selection_state(self):
        existing_ids = self.data_access.fetch_record_ids()
        saved_checked = DECODE_PREFERENCES(
            GET_SETTING(CHECKED_RECORDS_SETTING_KEY, "[]")
        )
        if isinstance(saved_checked, list):
            self.checked_record_ids = {
                record_id
                for value in saved_checked
                if not isinstance(value, bool)
                for record_id in [self.parse_record_id(value)]
                if record_id in existing_ids
            }

        selected_id = self.parse_record_id(
            GET_SETTING(SELECTED_RECORD_SETTING_KEY, "")
        )
        self.selected_record_id = selected_id if selected_id in existing_ids else None

    @staticmethod
    def parse_record_id(value):
        try:
            record_id = int(value)
        except (TypeError, ValueError):
            return None
        return record_id if record_id > 0 else None

    def persist_selection_state(self):
        snapshot = self.selection_state_snapshot()
        if snapshot == self.persisted_selection_snapshot:
            return False
        self.repository.set_settings(
            {
                CHECKED_RECORDS_SETTING_KEY: json.dumps(
                    sorted(self.checked_record_ids), ensure_ascii=False
                ),
                SELECTED_RECORD_SETTING_KEY: self.selected_record_id or "",
            }
        )
        self.persisted_selection_snapshot = snapshot
        return True

    def selection_state_snapshot(self):
        return tuple(sorted(self.checked_record_ids)), self.selected_record_id

    def schedule_selection_state_save(self):
        if self.selection_state_snapshot() == self.persisted_selection_snapshot:
            self.selection_save_timer.stop()
            return
        self.selection_save_timer.start()

    def default_table_preferences(self):
        return {
            "widths": {key: width for key, width in TABLE_WIDTHS.items()},
            "hidden": [],
            "order": [key for key, _label in TABLE_COLUMNS],
        }

    def load_table_preferences(self):
        preferences = DECODE_PREFERENCES(GET_SETTING(TABLE_PREFS_SETTING_KEY, ""))
        if not isinstance(preferences, dict):
            return self.default_table_preferences()
        default = self.default_table_preferences()
        widths = preferences.get("widths") if isinstance(preferences.get("widths"), dict) else {}
        hidden = preferences.get("hidden") if isinstance(preferences.get("hidden"), list) else []
        order = preferences.get("order") if isinstance(preferences.get("order"), list) else []
        valid_keys = [key for key, _label in TABLE_COLUMNS]
        order = [key for key in order if key in valid_keys]
        for key in valid_keys:
            if key not in order:
                order.append(key)
        return {
            "widths": {**default["widths"], **widths},
            "hidden": [key for key in hidden if key in dict(TABLE_COLUMNS)],
            "order": order,
        }

    def save_table_preferences(self):
        if self.table_view is None or self.saving_table_preferences:
            return
        previous_widths = self.load_table_preferences().get("widths", {})
        preferences = {
            "widths": {
                key: (
                    previous_widths.get(key, TABLE_WIDTHS[key])
                    if self.table_view.columnWidth(index) <= 0
                    else self.table_view.columnWidth(index)
                )
                for index, (key, _label) in enumerate(TABLE_COLUMNS)
            },
            "hidden": [
                key
                for index, (key, _label) in enumerate(TABLE_COLUMNS)
                if self.table_view.isColumnHidden(index)
            ],
            "order": [
                TABLE_COLUMNS[self.table_view.horizontalHeader().logicalIndex(visual_index)][0]
                for visual_index in range(len(TABLE_COLUMNS))
            ],
        }
        SET_SETTING(TABLE_PREFS_SETTING_KEY, ENCODE_PREFERENCES(preferences))

    def apply_table_preferences(self):
        if self.table_view is None:
            return
        preferences = self.load_table_preferences()
        widths = preferences.get("widths", {})
        hidden = set(preferences.get("hidden", []))
        order = preferences.get("order", [])
        header = self.table_view.horizontalHeader()
        self.saving_table_preferences = True
        try:
            for target_visual, key in enumerate(order):
                logical_index = next(
                    (
                        index
                        for index, (column_key, _label) in enumerate(TABLE_COLUMNS)
                        if column_key == key
                    ),
                    None,
                )
                if logical_index is None:
                    continue
                current_visual = header.visualIndex(logical_index)
                if current_visual != target_visual:
                    header.moveSection(current_visual, target_visual)
            for index, (key, _label) in enumerate(TABLE_COLUMNS):
                self.table_view.setColumnHidden(index, key in hidden)
                self.table_view.setColumnWidth(index, int(widths.get(key, TABLE_WIDTHS[key])))
        finally:
            self.saving_table_preferences = False

    def on_table_section_resized(self, _logical_index, _old_size, _new_size):
        if not self.saving_table_preferences:
            self.save_table_preferences()

    def on_table_section_moved(self, _logical_index, _old_visual_index, _new_visual_index):
        if not self.saving_table_preferences:
            self.save_table_preferences()

    def change_column_visibility(self):
        hidden_keys = {
            key
            for index, (key, _label) in enumerate(TABLE_COLUMNS)
            if self.table_view.isColumnHidden(index)
        }
        dialog = ColumnVisibilityDialog(TABLE_COLUMNS[1:], hidden_keys, self)
        if dialog.exec() != QDialog.Accepted:
            return
        new_hidden = set(dialog.hidden_keys())
        self.saving_table_preferences = True
        try:
            self.table_view.setColumnHidden(0, False)
            for index, (key, _label) in enumerate(TABLE_COLUMNS[1:], start=1):
                self.table_view.setColumnHidden(index, key in new_hidden)
        finally:
            self.saving_table_preferences = False
        self.save_table_preferences()
