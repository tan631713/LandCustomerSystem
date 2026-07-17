"""Desktop settings, backup, watchlist, and display workflows."""

from pathlib import Path

from customer_backup_status import format_storage_size
from customer_desktop import open_local_path
from customer_messages import (
    backup_management_failure_message,
    restore_confirmation_message,
    restore_failure_message,
    restore_success_message,
    startup_backup_notice,
)
from customer_repository import normalize_watch_name
from PySide6.QtWidgets import QApplication, QDialog


class SettingsWorkflowMixin:
    def configure_server_connection(self):
        if not self.api_mode:
            return None
        return self._app_component("change_server_connection")(self)

    def open_backup_folder(self):
        if self.api_mode:
            try:
                report = self.active_record_repository().server_backup_status()
            except Exception as exc:
                self._app_component("QMessageBox").critical(self, "無法取得備份位置", str(exc))
                return False
            self._app_component("QMessageBox").information(
                self,
                "家中伺服器備份位置",
                "備份資料夾位於家中伺服器，無法直接在公司筆電開啟。\n\n"
                f"伺服器路徑：{report.get('backup_directory') or '未設定'}",
            )
            return True
        backup_directory = self.database.backup_directory
        try:
            backup_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._app_component("QMessageBox").critical(self, "無法建立備份資料夾", str(exc))
            return False
        return open_local_path(backup_directory, self, item_label="備份資料夾")

    def manage_backups(self):
        policy = self._app_component("load_backup_policy")()
        dialog = self._app_component("BackupManagementDialog")(parent=self, **policy)
        if dialog.exec() != QDialog.Accepted:
            return None

        policy = dialog.selected_policy()
        if self.api_mode:
            try:
                self._app_component("save_backup_policy")(policy)
                result = self.active_record_repository().maintain_server_backups(
                    policy["retention_days"], policy["max_count"]
                )
            except Exception as exc:
                self.refresh_backup_status(show_warning=True)
                self._app_component("QMessageBox").critical(
                    self, "備份管理失敗", backup_management_failure_message(exc)
                )
                return None
            detail = (
                f"家中伺服器目前保留 {result.get('backup_count', 0)} 份 ZIP 備份，"
                f"本次清除 {result.get('deleted_count', 0)} 份舊備份。"
            )
            self._log_operation("備份管理", "整理伺服器備份", detail)
            self.refresh_backup_status()
            self._app_component("QMessageBox").information(self, "備份管理完成", detail)
            return result
        try:
            self._app_component("save_backup_policy")(policy)
            self.database.configure_backup_policy(**policy)
            if dialog.requested_action == "compress":
                result = self.database.compress_existing_backups()
                action_text = "壓縮"
            elif dialog.requested_action == "clean":
                result = self.database.prune_backups()
                action_text = "清理"
            else:
                result = self.database.run_backup_maintenance()
                action_text = "維護"
        except Exception as exc:
            self.refresh_backup_status(show_warning=True)
            self._app_component("QMessageBox").critical(self, "備份管理失敗", backup_management_failure_message(exc))
            return None

        detail = (
            f"已壓縮 {result.compressed_count} 份、刪除 {result.deleted_count} 份，"
            f"釋放 {format_storage_size(result.reclaimed_bytes)}。"
        )
        if result.failed_paths:
            detail += f"\n另有 {len(result.failed_paths)} 份無法處理，已保留原檔。"
        try:
            self._log_operation("備份管理", action_text, detail)
        except Exception as exc:
            detail += f"\n操作已完成，但操作記錄未寫入：{exc}"
        self.refresh_backup_status()
        self._app_component("QMessageBox").information(self, "備份管理完成", detail)
        return result

    def apply_saved_font_size(self):
        app = QApplication.instance()
        if app is None:
            return
        self._app_component("apply_font_size")(app, self.current_font_size_key)
        self.update_table_metrics()

    def update_table_metrics(self):
        if self.table_view is None:
            return
        point_size = self._app_component("get_font_size_option")(self.current_font_size_key)[2]
        row_height = max(28, point_size + 18)
        self.table_view.verticalHeader().setDefaultSectionSize(row_height)

    def change_font_size(self):
        dialog = self._app_component("FontSizeDialog")(self.current_font_size_key, self)
        if dialog.exec() != QDialog.Accepted:
            return
        selected_key = dialog.selected_font_size_key()
        if selected_key == self.current_font_size_key:
            return
        self.current_font_size_key = selected_key
        self._app_component("set_setting")("font_size", selected_key)
        self.apply_saved_font_size()

    def manage_watchlist(self):
        if not self.ensure_can_modify("注意名單管理"):
            return
        repository = self.active_record_repository() if self.api_mode else None
        dialog = self._app_component("WatchlistDialog")(
            self, repository=repository
        )
        if dialog.exec() == QDialog.Accepted:
            self.refresh_watchlist_cache()
            self.refresh_records(self.selected_record_id)

    def refresh_watchlist_cache(self):
        repository = (
            self.active_record_repository()
            if self.api_mode and hasattr(self, "active_record_repository")
            else getattr(self, "record_repository", None)
            if self.api_mode
            else None
        )
        rows = (
            repository.get_watchlist_entries()
            if repository is not None
            and hasattr(repository, "get_watchlist_entries")
            else self._app_component("get_watchlist_entries")()
            if not self.api_mode
            else []
        )
        self.watchlist_names = {
            normalize_watch_name(row["name"])
            for row in rows
        }

    def show_operation_logs(self):
        rows = (
            self.active_record_repository().get_operation_logs()
            if self.api_mode
            else None
        )
        dialog = self._app_component("OperationLogDialog")(self, rows=rows)
        dialog.exec()

    def show_startup_backup_notice(self):
        self._app_component("QMessageBox").information(
            self,
            "自動備份提醒",
            startup_backup_notice(self.startup_backup_path),
        )

    def confirm_watchlist_match(self, owner_name):
        if self.api_mode:
            repository = (
                self.active_record_repository()
                if hasattr(self, "active_record_repository")
                else getattr(self, "record_repository", None)
            )
            match = (
                repository.find_watchlist_match(owner_name)
                if repository is not None
                and hasattr(repository, "find_watchlist_match")
                else None
            )
        else:
            match = self._app_component("find_watchlist_match")(owner_name)
        if match is None:
            return True

        note_text = match["note"] or "無"
        message = (
            f"姓名「{match['name']}」已在注意名單中。\n"
            f"備註：{note_text}\n\n"
            "仍要繼續儲存這筆資料嗎？"
        )
        reply = self._app_component("QMessageBox").question(self, "注意名單提醒", message)
        return reply == self._app_component("QMessageBox").Yes

    def restore_backup(self):
        if not self.ensure_can_modify("還原備份"):
            return
        if self.api_mode:
            if not self.ensure_admin("還原家中伺服器備份"):
                return
            repository = self.active_record_repository()
            try:
                backups = repository.list_server_backups()
            except Exception as exc:
                self._app_component("QMessageBox").critical(
                    self, "讀取伺服器備份失敗", str(exc)
                )
                return
            if not any(row.get("status") == "ok" for row in backups):
                self._app_component("QMessageBox").information(
                    self, "沒有可還原備份", "家中伺服器目前沒有通過驗證的備份。"
                )
                return
            dialog = self._app_component("ServerBackupRestoreDialog")(backups, self)
            if dialog.exec() != QDialog.Accepted:
                return
            try:
                result = repository.restore_server_backup(
                    dialog.selected_backup_name(), dialog.confirmation()
                )
            except Exception as exc:
                self._app_component("QMessageBox").critical(
                    self, "伺服器還原失敗", str(exc)
                )
                return
            self._app_component("QMessageBox").information(
                self,
                "伺服器還原完成",
                "PostgreSQL 正式資料與附件已還原。所有登入已失效，桌面程式將關閉，"
                "請重新開啟並登入。\n\n"
                f"還原檔：{result.get('restored_backup') or ''}\n"
                f"還原前安全備份：{result.get('safety_backup') or ''}",
            )
            self.close()
            return
        backup_directory = self.database.backup_directory
        try:
            backup_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._app_component("QMessageBox").critical(self, "無法開啟備份資料夾", str(exc))
            return
        file_path, _selected_filter = self._app_component("QFileDialog").getOpenFileName(
            self,
            "選擇要還原的備份檔",
            str(backup_directory),
            "備份檔案 (*.zip *.db);;ZIP 壓縮備份 (*.zip);;資料庫備份 (*.db);;所有檔案 (*.*)",
        )
        if not file_path:
            return

        reply = self._app_component("QMessageBox").question(
            self,
            "確認還原",
            restore_confirmation_message(),
        )
        if reply != self._app_component("QMessageBox").Yes:
            return

        try:
            backup_path = self.database.restore_database(file_path)
        except Exception as exc:
            self._app_component("QMessageBox").critical(self, "還原失敗", restore_failure_message(exc))
            return

        self._app_component("QMessageBox").information(
            self,
            "還原完成",
            restore_success_message(backup_path),
        )
        self._log_operation("還原備份", Path(file_path).name, str(backup_path) if backup_path else "")
        self.close()
