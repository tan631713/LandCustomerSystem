"""Advanced-search state and reusable saved-search workflows."""

from customer_dialogs import AdvancedSearchDialog, SavedSearchDialog
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

ADVANCED_SEARCH_SETTING_KEY = "advanced_search"
SAVED_SEARCHES_SETTING_KEY = "saved_searches"
SET_SETTING = None
ENCODE_PREFERENCES = None


def configure_search_presets(**dependencies):
    globals().update(dependencies)


class SearchPresetMixin:
    def get_active_advanced_search_count(self):
        return len(
            [
                key
                for key, value in self.advanced_search_criteria.items()
                if str(value or "").strip()
            ]
        )

    def get_current_search_state(self):
        return {
            "keyword": self.search_input.text().strip() if self.search_input is not None else "",
            "filter_field": self.get_filter_field(),
            "sort_field": self.get_sort_field(),
            "sort_order": (
                self.sort_order_combo.currentData()
                if self.sort_order_combo is not None
                else "desc"
            ),
            "advanced": dict(self.advanced_search_criteria),
        }

    def apply_search_state(self, criteria):
        if self.search_input is not None:
            self.search_input.setText(str(criteria.get("keyword") or ""))
        filter_field = criteria.get("filter_field", "all")
        if self.filter_field_combo is not None:
            index = self.filter_field_combo.findData(filter_field)
            self.filter_field_combo.setCurrentIndex(index if index >= 0 else 0)
        sort_field = criteria.get("sort_field", "rowid")
        if self.sort_field_combo is not None:
            index = self.sort_field_combo.findData(sort_field)
            self.sort_field_combo.setCurrentIndex(index if index >= 0 else 0)
        sort_order = criteria.get("sort_order", "desc")
        if self.sort_order_combo is not None:
            index = self.sort_order_combo.findData(sort_order)
            self.sort_order_combo.setCurrentIndex(index if index >= 0 else 0)
        self.advanced_search_criteria = (
            dict(criteria.get("advanced"))
            if isinstance(criteria.get("advanced"), dict)
            else {}
        )
        SET_SETTING(
            ADVANCED_SEARCH_SETTING_KEY,
            ENCODE_PREFERENCES(self.advanced_search_criteria),
        )
        self.refresh_records()

    def persist_saved_searches(self):
        SET_SETTING(
            SAVED_SEARCHES_SETTING_KEY,
            ENCODE_PREFERENCES(self.saved_searches),
        )

    def save_current_search(self):
        name, accepted = QInputDialog.getText(self, "儲存常用條件", "請輸入條件名稱：")
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "名稱空白", "請輸入條件名稱。")
            return
        criteria = self.get_current_search_state()
        replaced = False
        for item in self.saved_searches:
            if item["name"] == name:
                item["criteria"] = criteria
                replaced = True
                break
        if not replaced:
            self.saved_searches.append({"name": name, "criteria": criteria})
        self.persist_saved_searches()
        QMessageBox.information(self, "已儲存", f"常用搜尋條件「{name}」已儲存。")

    def open_saved_searches(self):
        dialog = SavedSearchDialog(self.saved_searches, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_criteria is not None:
            self.saved_searches = dialog.saved_searches
            self.persist_saved_searches()
            self.apply_search_state(dialog.selected_criteria)
            return
        if dialog.saved_searches != self.saved_searches:
            self.saved_searches = dialog.saved_searches
            self.persist_saved_searches()

    def open_advanced_search(self):
        dialog = AdvancedSearchDialog(self.advanced_search_criteria, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.advanced_search_criteria = dialog.criteria()
        if self.search_input is not None:
            self.search_input.clear()
        if self.filter_field_combo is not None:
            all_fields_index = self.filter_field_combo.findData("all")
            self.filter_field_combo.blockSignals(True)
            try:
                self.filter_field_combo.setCurrentIndex(
                    all_fields_index if all_fields_index >= 0 else 0
                )
            finally:
                self.filter_field_combo.blockSignals(False)
        SET_SETTING(
            ADVANCED_SEARCH_SETTING_KEY,
            ENCODE_PREFERENCES(self.advanced_search_criteria),
        )
        self.refresh_records()
        condition_count = self.get_active_advanced_search_count()
        if condition_count:
            self.statusBar().showMessage(
                f"已套用 {condition_count} 個進階條件（同欄任一符合、不同欄位全部符合）。",
                4000,
            )
        else:
            self.statusBar().showMessage("已清除進階搜尋條件。", 3000)

    def clear_search(self):
        self.search_input.clear()
        self.advanced_search_criteria = {}
        SET_SETTING(ADVANCED_SEARCH_SETTING_KEY, "")
        if self.filter_field_combo is not None:
            self.filter_field_combo.setCurrentIndex(0)
        if self.sort_field_combo is not None:
            self.sort_field_combo.setCurrentIndex(0)
        if self.sort_order_combo is not None:
            self.sort_order_combo.setCurrentIndex(0)
        self.refresh_records()
