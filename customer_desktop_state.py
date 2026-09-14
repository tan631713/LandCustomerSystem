"""Desktop permissions, health checks, form state, and window lifecycle."""

import os
from pathlib import Path

from customer_desktop_api import DesktopApiError
from customer_error_handler import get_error_log_path
from customer_health import SystemHealthCheckService
from customer_quality import inspect_customer_quality
from PySide6.QtWidgets import QInputDialog, QLineEdit


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

    def _verify_current_user_password(self, password):
        """Re-check the given password against the currently logged-in user.

        Local (SQLite) mode has one admin account, checked directly against
        the local password hash. API/server mode has to ask the home
        server instead -- DesktopApiClient.login() is the only endpoint
        that verifies a password, so this reuses it purely to confirm the
        password is correct; the fresh access token it returns simply
        replaces the (still valid) one already in use.
        """
        username = self.current_user.get("username") or self.admin_username
        if self.api_mode:
            client = getattr(self.active_record_repository(), "client", None)
            if client is None:
                return False
            try:
                client.login(username, password)
            except DesktopApiError:
                return False
            return True
        return self.repository.authenticate_user(username, password) is not None

    def _confirm_action_password(self, prompt_text):
        password, accepted = QInputDialog.getText(
            self, "密碼確認", prompt_text, QLineEdit.Password,
        )
        if not accepted:
            return False
        if not password or not self._verify_current_user_password(password):
            self._app_component("QMessageBox").warning(self, "密碼錯誤", "密碼不正確，操作已取消。")
            return False
        return True

    def toggle_privacy_mask_mode(self, enabled):
        # Checkable QAction.toggled has already flipped the checkbox by the
        # time this fires; a declined/failed password confirmation has to
        # flip it back without re-entering this handler (setChecked() would
        # re-emit toggled and recurse), hence the blockSignals() pair below.
        if not self._confirm_action_password("請輸入使用者密碼以確認操作："):
            action = self.privacy_mask_action
            if action is not None:
                action.blockSignals(True)
                action.setChecked(not enabled)
                action.blockSignals(False)
            return
        self.repository.set_setting(self.privacy_mask_setting_key, "1" if enabled else "0")
        self.privacy_mask_enabled = enabled
        self.apply_owner_name_visibility()
        self.apply_external_id_visibility()
        self.apply_external_id_button_availability()
        self.apply_owner_contacts_tab_visibility()
        self.refresh_records(self.selected_record_id)
        self.statusBar().showMessage(
            "已啟用遮罩，地主姓名只顯示姓氏，關係人分頁已隱藏。" if enabled else "已還原正常顯示。",
            3500,
        )

    def apply_owner_contacts_tab_visibility(self):
        tabs = getattr(self, "detail_tabs", None)
        widget = getattr(self, "owner_contacts_widget", None)
        if tabs is None or widget is None:
            return
        index = tabs.indexOf(widget)
        if index != -1:
            tabs.setTabVisible(index, not self.privacy_mask_enabled)

    def show_health_check(self):
        self._show_non_modal_report_dialog(
            "_health_check_dialog",
            self._app_component("HealthCheckDialog"),
            self.build_health_checks(),
            self,
        )

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
        if getattr(self, "splitter_save_timer", None) is not None:
            self.splitter_save_timer.stop()
        if getattr(self, "gc_collect_timer", None) is not None:
            self.gc_collect_timer.stop()
        if hasattr(self, "save_main_splitter_sizes"):
            self.save_main_splitter_sizes()
        self.persist_selection_state()
        self.save_table_preferences()
        super().closeEvent(event)
