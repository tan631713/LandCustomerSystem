"""Desktop productivity, quality, follow-up, and reporting workflows."""

from datetime import date
from pathlib import Path

from customer_desktop import open_local_path
from customer_desktop_api import DesktopApiError
from customer_fields import LAND_FIELDS
from customer_productivity import (
    OffsiteBackupWorker,
    apply_default_import_profile,
    export_report_with_template,
)
from customer_quality import inspect_customer_quality, quality_issue_signature
from customer_security import encrypt_value
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton


class ProductivityWorkflowMixin:
    def setup_notification_status(self):
        self.notification_status_button = QPushButton("通知 0")
        self.notification_status_button.setFlat(True)
        self.notification_status_button.setToolTip("開啟通知中心")
        self.notification_status_button.clicked.connect(self.show_notification_center)
        self.statusBar().addPermanentWidget(self.notification_status_button)
        self.notification_timer = QTimer(self)
        self.notification_timer.setInterval(60 * 60 * 1000)
        self.notification_timer.timeout.connect(self.refresh_notification_status)
        self.notification_timer.start()
        self.refresh_notification_status()

    def refresh_notification_status(self):
        try:
            repository = self.active_record_repository()
            repository.refresh_notifications(date.today().isoformat())
            count = len(repository.list_notifications())
        except Exception:
            count = 0
        if getattr(self, "notification_status_button", None) is not None:
            self.notification_status_button.setText(f"通知 {count}")
            color = "#fbbf24" if count else "#86efac"
            self.notification_status_button.setStyleSheet(f"color: {color}; padding: 2px 8px;")
        return count

    def setup_offsite_backup(self):
        if getattr(self, "api_mode", False):
            self.offsite_backup_timer = None
            return
        self.offsite_backup_timer = QTimer(self)
        self.offsite_backup_timer.setInterval(6 * 60 * 60 * 1000)
        self.offsite_backup_timer.timeout.connect(self.run_scheduled_offsite_backup)
        self.offsite_backup_timer.start()
        QTimer.singleShot(30_000, self.run_scheduled_offsite_backup)

    def run_scheduled_offsite_backup(self):
        if self.offsite_backup_thread is not None and self.offsite_backup_thread.isRunning():
            return
        targets = [row for row in self.repository.list_backup_targets() if row["enabled"]]
        if not targets:
            return
        if self.repository.get_setting(
            self.productivity.OFFSITE_LAST_SYNC_SETTING, ""
        ) == date.today().isoformat():
            return
        password = self.productivity.load_offsite_backup_password()
        if not password:
            self.statusBar().showMessage(
                "異地備份尚未設定保存的備份密碼，請到「設定 → 異地完整備份」完成一次同步。",
                15000,
            )
            return
        thread = QThread(self)
        worker = OffsiteBackupWorker(self.productivity, password)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.offsite_backup_completed)
        worker.failed.connect(self.offsite_backup_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.offsite_backup_thread_finished)
        self.offsite_backup_thread = thread
        self.offsite_backup_worker = worker
        self.statusBar().showMessage("正在背景建立異地完整備份…")
        thread.start()

    def offsite_backup_completed(self, result):
        archive_path, results = result
        failures = [row for row in results if row[1] != "成功"]
        if results and not failures:
            self.repository.set_setting(
                self.productivity.OFFSITE_LAST_SYNC_SETTING,
                date.today().isoformat(),
            )
            self.statusBar().showMessage(
                f"異地完整備份完成：{Path(archive_path).name}", 15000
            )
            self.repository.log_operation(
                "自動異地備份", "同步完成", str(archive_path)
            )
        else:
            self.statusBar().showMessage(
                f"異地備份有 {len(failures)} 個目的地失敗，稍後會重試。",
                15000,
            )

    def offsite_backup_failed(self, error_text):
        self.statusBar().showMessage(f"異地備份失敗：{error_text}", 15000)
        try:
            self.repository.log_operation("自動異地備份失敗", error_text, "")
        except Exception:
            pass

    def offsite_backup_thread_finished(self):
        self.offsite_backup_thread = None
        self.offsite_backup_worker = None

    def ensure_admin(self, action_text="這個操作"):
        if self.current_user.get("role") == "admin":
            return True
        self._app_component("QMessageBox").warning(
            self,
            "權限不足",
            f"「{action_text}」只允許管理員執行。",
        )
        return False

    def show_recycle_bin(self):
        repository = self.active_record_repository()
        while True:
            dialog = self._app_component("RecycleBinDialog")(repository.list_recycle_bin(), self)
            if dialog.exec() != QDialog.Accepted:
                return
            if dialog.action == "restore":
                if not self.ensure_can_modify("還原回收桶資料"):
                    return
                restored = repository.restore_recycle_items(dialog.selected_ids())
                self._log_operation("回收桶還原", f"還原 {len(restored)} 筆", "")
                self.refresh_records(restored[0] if restored else None)
            elif dialog.action in {"purge", "purge_all"}:
                if not self.ensure_admin("永久清除回收桶"):
                    return
                reply = self._app_component("QMessageBox").question(
                    self,
                    "永久刪除確認",
                    "永久刪除後只能從備份還原，確定繼續嗎？",
                )
                if reply != self._app_component("QMessageBox").Yes:
                    continue
                ids = None if dialog.action == "purge_all" else dialog.selected_ids()
                count = repository.purge_recycle_items(ids, self.attachments_dir)
                self._log_operation("清理回收桶", f"永久刪除 {count} 筆", "")

    def show_undo_operations(self):
        if not self.ensure_can_modify("復原批次操作"):
            return
        repository = self.active_record_repository()
        dialog = self._app_component("UndoOperationsDialog")(repository.list_undo_operations(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        if self._app_component("QMessageBox").question(
            self,
            "確認復原",
            "系統會把所選操作涉及的資料恢復到操作前，確定繼續嗎？",
        ) != self._app_component("QMessageBox").Yes:
            return
        result = repository.undo_operation(dialog.operation_id)
        if result:
            self._log_operation("復原批次操作", result["summary"], "")
            self.checked_record_ids.clear()
            self.new_record()
            self.refresh_records()
            self._app_component("QMessageBox").information(self, "復原完成", result["summary"])

    def manage_users(self):
        if not self.ensure_admin("使用者與權限管理"):
            return
        repository = self.active_record_repository()
        self._app_component("UserManagementDialog")(repository, self.encryption_key, self).exec()
        self._log_operation("使用者管理", "檢視或更新帳號與權限", "")

    def manage_external_backups(self):
        if not self.ensure_admin("異地完整備份"):
            return
        if self.api_mode:
            policy = self._app_component("load_backup_policy")()
            dialog = self._app_component("ServerBackupTargetsDialog")(
                self.active_record_repository(),
                retention_days=policy["retention_days"],
                max_count=policy["max_count"],
                parent=self,
            )
            dialog.exec()
            self.refresh_backup_status()
            return
        dialog = self._app_component("BackupTargetsDialog")(self.repository, self.productivity, self)
        dialog.exec()
        if dialog.restore_succeeded:
            QApplication.quit()
            return
        self.repository.log_operation("異地備份", "開啟異地備份管理", "")
        self.refresh_backup_status()

    def show_workflow_board(self):
        if not self.ensure_can_modify("案件工作流程"):
            return
        repository = self.active_record_repository()
        self._app_component("WorkflowDialog")(repository, self).exec()
        self._log_operation("案件工作流程", "更新案件或任務", "")
        self.refresh_records(self.selected_record_id)
        self.refresh_notification_status()

    def show_notification_center(self):
        self._app_component("NotificationCenterDialog")(self.active_record_repository(), self).exec()
        self.refresh_notification_status()

    def manage_import_profiles(self):
        if not self.ensure_can_modify("Excel 匯入設定檔"):
            return
        self._app_component("ImportProfilesDialog")(self.repository, dict(LAND_FIELDS), self).exec()
        applied = apply_default_import_profile(self.repository)
        self._log_operation("匯入設定檔", f"套用 {applied} 個預設欄名", "")

    def manage_report_templates(self):
        if not self.ensure_can_modify("報表與列印範本"):
            return
        dialog = self._app_component("ReportTemplatesDialog")(self.repository, dict(LAND_FIELDS), self)
        if dialog.exec() != QDialog.Accepted or not dialog.export_template:
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").information(self, "尚未選取", "請先勾選或選取要輸出的資料。")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存範本報表",
            str(self.app_dir / "土地資料報表.docx"),
            "Word 文件 (*.docx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".docx"):
            file_path += ".docx"
        rows = []
        for row in self.active_record_repository().fetch_customers_by_ids(record_ids):
            plain = self.get_plain_record_data(row)
            plain["id"] = row["id"]
            rows.append(plain)
        count = export_report_with_template(
            file_path, rows, dialog.export_template, dict(LAND_FIELDS)
        )
        self._log_operation("範本報表", f"輸出 {count} 筆", file_path)
        self._app_component("QMessageBox").information(self, "報表完成", f"已輸出 {count} 筆資料：\n{file_path}")

    def show_duplicate_finder(self):
        if not self.ensure_can_modify("智慧重複資料檢查"):
            return
        rows = []
        repository = self.active_record_repository()
        for raw_row in repository.fetch_all_customer_rows():
            plain = self.get_plain_record_data(raw_row)
            plain["id"] = raw_row["id"]
            rows.append(plain)
        pairs = self.productivity.find_duplicate_pairs(
            rows, repository.ignored_duplicate_pairs()
        )
        if not pairs:
            self._app_component("QMessageBox").information(self, "檢查完成", "沒有發現尚未確認的高相似資料。")
            return
        dialog = self._app_component("DuplicateFinderDialog")(pairs, self)
        if dialog.exec() != QDialog.Accepted or not dialog.pair:
            return
        left_id, right_id = dialog.pair["left_id"], dialog.pair["right_id"]
        if dialog.action == "ignore":
            repository.ignore_duplicate_pair(left_id, right_id)
            self._log_operation("忽略重複建議", f"ID {left_id} / {right_id}", "")
            return
        self.checked_record_ids = {left_id, right_id}
        self.merge_checked_records()

    def show_map_visualization(self):
        if not self.ensure_can_modify("地圖與地號視覺化"):
            return
        dialog = self._app_component("MapLocationsDialog")(
            self.active_record_repository(), self.fernet, self.selected_record_id, self
        )
        if dialog.exec() != QDialog.Accepted or not dialog.export_requested:
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存土地位置視覺化",
            str(self.app_dir / "土地位置與地號視覺化.html"),
            "HTML 網頁 (*.html)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".html"):
            file_path += ".html"
        count = self.productivity.build_map_html(dialog.rows, file_path)
        self._log_operation("地圖視覺化", f"輸出 {count} 個位置", file_path)
        open_local_path(file_path, self, item_label="土地位置視覺化")

    def verify_managed_attachments(self):
        if not self.ensure_admin("檢查納管附件"):
            return
        results = self.active_record_repository().verify_managed_attachments()
        abnormal = [row for row in results if row["state"] != "正常"]
        detail = "\n".join(
            f"ID {row['id']} {row['name']}：{row['state']}" for row in abnormal[:20]
        )
        message = f"已檢查 {len(results)} 個納管附件；異常 {len(abnormal)} 個。"
        if detail:
            message += "\n\n" + detail
        self._app_component("QMessageBox").information(self, "附件完整性檢查", message)
        self._log_operation("附件完整性檢查", message, "")

    def run_data_quality_check(self):
        selected_rule_keys = self._app_component("load_quality_rule_keys")()
        rules_dialog = self._app_component("DataQualityRulesDialog")(selected_rule_keys, self)
        if rules_dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("已取消資料品質檢查。", 2500)
            return
        selected_rule_keys = rules_dialog.selected_rules()
        self._app_component("save_quality_rule_keys")(selected_rule_keys)

        rows = self.active_record_repository().fetch_all_customer_rows()
        plain_records = []
        for row in rows:
            data = self.get_plain_record_data(row)
            data["id"] = row["id"]
            plain_records.append(data)
        all_issues = inspect_customer_quality(plain_records, enabled_rules=selected_rule_keys)
        ignored_signatures = self._app_component("load_ignored_quality_issue_signatures")()
        issues = [
            issue for issue in all_issues
            if quality_issue_signature(issue) not in ignored_signatures
        ]
        ignored_count = len(all_issues) - len(issues)
        active_count_state = {"value": len(issues)}
        ignored_count_state = {"value": ignored_count}

        def ignore_quality_issue(issue):
            signature = quality_issue_signature(issue)
            if signature not in ignored_signatures:
                ignored_signatures.add(signature)
                active_count_state["value"] = max(0, active_count_state["value"] - 1)
                ignored_count_state["value"] += 1
                self._app_component("save_ignored_quality_issue_signatures")(ignored_signatures)

        def clear_ignored_quality_issues():
            ignored_signatures.clear()
            ignored_count_state["value"] = 0
            self._app_component("save_ignored_quality_issue_signatures")(ignored_signatures)

        self._app_component("DataQualityDialog")(
            issues,
            total_records=len(plain_records),
            parent=self,
            on_issue_activated=self.open_quality_issue_record,
            on_issue_ignored=ignore_quality_issue,
            ignored_count=ignored_count,
            on_clear_ignored=clear_ignored_quality_issues,
        ).exec()
        self.statusBar().showMessage(
            f"資料品質檢查完成：{len(plain_records)} 筆資料，"
            f"{active_count_state['value']} 個未確認提醒，{ignored_count_state['value']} 個已隱藏；"
            f"已啟用 {len(selected_rule_keys)} 項規則。",
            4000,
        )

    def open_quality_issue_record(self, record_id):
        self.refresh_records(record_id)
        self.load_record(record_id)
        self.statusBar().showMessage(f"已載入資料 ID {record_id}，可在右側表單修正。", 4000)

    def show_dashboard(self):
        self._app_component("DashboardDialog")(self.dashboard_stats(), self).exec()

    def show_record_history(self):
        if self.selected_record_id is None:
            self._app_component("QMessageBox").warning(self, "尚未選取", "請先選取要查看歷史的資料。")
            return
        row = self.active_record_repository().get_customer(self.selected_record_id)
        if row is None:
            self._app_component("QMessageBox").warning(self, "找不到資料", "目前選取的資料不存在。")
            return
        plain_data = self.get_plain_record_data(row)
        logs = self.plain_record_change_logs(self.selected_record_id)
        self._app_component("RecordHistoryDialog")(
            logs,
            self.record_label(self.selected_record_id, plain_data),
            self,
        ).exec()

    def edit_follow_up_reminder(self):
        if not self.ensure_can_modify("追蹤提醒"):
            return
        if self.selected_record_id is None:
            self._app_component("QMessageBox").warning(self, "尚未選取", "請先選取要設定追蹤提醒的資料。")
            return
        repository = self.active_record_repository()
        try:
            row = repository.get_customer(self.selected_record_id)
            reminder = self.plain_follow_up_reminder(
                repository.get_follow_up_reminder(self.selected_record_id)
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if row is None:
            self._app_component("QMessageBox").warning(self, "找不到資料", "目前選取的資料不存在。")
            return
        plain_data = self.get_plain_record_data(row)
        dialog = self._app_component("FollowUpReminderDialog")(
            self.record_label(self.selected_record_id, plain_data),
            reminder,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.delete_requested:
            try:
                deleted = repository.delete_follow_up_reminder(
                    self.selected_record_id
                )
            except DesktopApiError as exc:
                self._app_component("QMessageBox").critical(self, "清除失敗", str(exc))
                return
            if deleted and not self.api_mode:
                repository.log_operation(
                    "清除追蹤提醒",
                    self.record_label(self.selected_record_id, plain_data),
                    "",
                )
            self._app_component("QMessageBox").information(self, "已清除", "已清除這筆資料的追蹤提醒。")
            self.refresh_records(self.selected_record_id)
            return
        values = dialog.values()
        encrypted_note = encrypt_value(self.fernet, values.get("note") or "")
        try:
            repository.save_follow_up_reminder(
                self.selected_record_id,
                values.get("due_date"),
                values.get("status"),
                encrypted_note,
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "儲存失敗", str(exc))
            return
        if not self.api_mode:
            repository.log_operation(
                "設定追蹤提醒",
                self.record_label(self.selected_record_id, plain_data),
                f"{values.get('due_date') or '未設定日期'} / {values.get('status')}",
            )
        self.refresh_records(self.selected_record_id)
        self._app_component("QMessageBox").information(self, "已儲存", "追蹤提醒已儲存。")

    def show_follow_up_list(self):
        repository = self.active_record_repository()
        reminders = [
            self.plain_follow_up_reminder(row)
            for row in repository.list_follow_up_reminders()
        ]
        self._app_component("FollowUpListDialog")(reminders, self, on_record_activated=self.open_quality_issue_record).exec()
