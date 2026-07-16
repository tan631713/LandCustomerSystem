"""Desktop permissions, health checks, form state, and window lifecycle."""

import os
from pathlib import Path

from customer_error_handler import get_error_log_path
from customer_health import SystemHealthCheckService
from customer_quality import inspect_customer_quality


class DesktopStateMixin:
    def is_readonly_mode(self):
        return self.repository.get_setting(self.readonly_setting_key, "0") == "1"

    def ensure_can_modify(self, action_text="這個操作"):
        if self.current_user.get("role") == "viewer":
            self._app_component("QMessageBox").warning(
                self,
                "唯讀權限",
                f"目前帳號是唯讀人員，已阻止「{action_text}」。",
            )
            return False
        if not self.is_readonly_mode():
            return True
        self._app_component("QMessageBox").warning(
            self,
            "唯讀模式",
            f"目前已啟用唯讀模式，已阻止「{action_text}」。請到「設定 > 唯讀模式」關閉後再操作。",
        )
        return False

    def toggle_readonly_mode(self, enabled):
        self.repository.set_setting(self.readonly_setting_key, "1" if enabled else "0")
        self.statusBar().showMessage(
            "已啟用唯讀模式，會阻止新增/修改/刪除。" if enabled else "已關閉唯讀模式。",
            3500,
        )


    def show_health_check(self):
        self._app_component("HealthCheckDialog")(self.build_health_checks(), self).exec()

    def build_health_checks(self):
        if self.api_mode:
            diagnostics_path = (
                Path(os.environ.get("LOCALAPPDATA", self.app_dir))
                / "LandCustomerSystem"
                / "client-network-diagnostics.json"
            )
            return SystemHealthCheckService(
                readonly_mode=self.is_readonly_mode,
                api_client=self.record_repository.client,
                diagnostics_path=diagnostics_path,
            ).build()

        return SystemHealthCheckService(
            readonly_mode=self.is_readonly_mode,
            database=self.database,
            repository=self.repository,
            plain_record=self.get_plain_record_data,
            inspect_quality=inspect_customer_quality,
            quality_rule_keys=lambda: self._app_component("load_quality_rule_keys")(),
            plain_reminder=self.plain_follow_up_reminder,
            error_log_path=get_error_log_path(self.database.database_path.parent),
        ).build()



    def bind_total_formula(self):
        for key in ("area", "declared_value", "numerator", "denominator"):
            self.field_widgets[key].textChanged.connect(self.update_total_declared_value)

    def get_filter_field(self):
        if self.filter_field_combo is None:
            return "all"
        return self.filter_field_combo.currentData() or "all"

    def get_sort_field(self):
        if self.sort_field_combo is None:
            return "rowid"
        return self.sort_field_combo.currentData() or "rowid"

    def get_sort_reverse(self):
        if self.sort_order_combo is None:
            return True
        return (self.sort_order_combo.currentData() or "desc") == "desc"

    def closeEvent(self, event):
        if self.excel_thread is not None and self.excel_thread.isRunning():
            self._app_component("QMessageBox").information(self, "Excel 處理中", "請等待 Excel 工作完成後再關閉程式。")
            event.ignore()
            return
        if self.offsite_backup_thread is not None and self.offsite_backup_thread.isRunning():
            self._app_component("QMessageBox").information(
                self,
                "異地備份處理中",
                "請等待完整備份完成後再關閉程式，避免目的地留下不完整檔案。",
            )
            event.ignore()
            return
        for thread, _worker in list(self.record_searches.values()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(2000):
                self._app_component("QMessageBox").information(self, "搜尋處理中", "請稍候，背景搜尋即將結束。")
                event.ignore()
                return
        self.selection_save_timer.stop()
        self.persist_selection_state()
        self.save_table_preferences()
        super().closeEvent(event)
