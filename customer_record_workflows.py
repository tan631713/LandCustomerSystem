"""Desktop record editing, selection, and batch-operation workflows."""

import sqlite3
from datetime import date

from customer_analytics import build_dashboard_stats
from customer_desktop_api import DesktopApiError
from customer_display import compact_summary_text, format_attachment_summary
from customer_domain import (
    calculate_ping,
    calculate_total_declared_value,
    format_number_text,
    format_ping_text,
    mask_identity_text,
)
from customer_fields import LAND_FIELDS
from customer_messages import (
    database_save_failure_message,
    password_change_failure_message,
    password_changed_message,
)
from customer_security import (
    ENCRYPTED_FIELDS,
    decrypt_value,
    encrypt_record,
    encrypt_value,
    make_fernet,
)
from PySide6.QtCore import QPoint, QItemSelectionModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QPlainTextEdit


class RecordWorkflowMixin:
    def on_external_id_edited(self, text):
        if self.show_full_external_id:
            self.current_external_id_plain = text

    def get_field_text(self, key):
        widget = self.fields[key]
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        return widget.text().strip()

    def set_field_text(self, key, value):
        widget = self.fields[key]
        text = value or ""
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)

    def update_total_declared_value(self):
        data = {
            "area": self.get_field_text("area"),
            "declared_value": self.get_field_text("declared_value"),
            "numerator": self.get_field_text("numerator"),
            "denominator": self.get_field_text("denominator"),
        }
        self.set_field_text("ping", calculate_ping(data) or "")
        self.set_field_text("total_declared_value", calculate_total_declared_value(data) or "")

    def format_declared_value(self):
        self.set_field_text("declared_value", format_number_text(self.get_field_text("declared_value")))

    def toggle_external_id_visibility(self):
        self.show_full_external_id = not self.show_full_external_id
        if self.external_id_button is not None:
            self.external_id_button.setText("隱藏身分證" if self.show_full_external_id else "顯示身分證")
        self.apply_external_id_visibility()
        self.refresh_records(self.selected_record_id)

    def apply_external_id_visibility(self):
        widget = self.field_widgets.get("external_id")
        if widget is None:
            return
        if self.show_full_external_id:
            widget.setReadOnly(False)
            widget.setText(self.current_external_id_plain)
        else:
            widget.setText(mask_identity_text(self.current_external_id_plain))
            widget.setReadOnly(True)

    def select_record_in_table(self, record_id):
        row_number = self.table_model.row_for_record_id(record_id)
        if row_number < 0:
            return False
        index = self.table_model.index(row_number, 0)
        selection_model = self.table_view.selectionModel()
        selection_model.setCurrentIndex(
            index,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.table_view.scrollTo(index, QAbstractItemView.PositionAtCenter)
        return True

    def on_record_select(self, current, _previous):
        if not current.isValid():
            return
        row = self.table_model.row_record(current.row())
        if row:
            self.load_record(row["id"])

    def on_table_clicked(self, index):
        if not index.isValid() or index.column() != 0:
            return
        row = self.table_model.row_record(index.row())
        if row is None:
            return
        new_state = Qt.Unchecked if row["checked"] else Qt.Checked
        self.table_model.setData(index, new_state, Qt.CheckStateRole)

    def show_record_menu(self, position: QPoint):
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return
        row = self.table_model.row_record(index.row())
        if row is None:
            return
        selected_ids = set(self.selected_table_record_ids())
        if row["id"] not in selected_ids:
            self.select_record_in_table(row["id"])
        self.record_menu.exec(self.table_view.viewport().mapToGlobal(position))

    def load_record(self, record_id):
        row = self.active_record_repository().get_customer(record_id)
        if row is None:
            return

        self.selected_record_id = record_id
        self.schedule_selection_state_save()
        for key in self.fields:
            value = row[key] or ""
            if key in ENCRYPTED_FIELDS:
                value = decrypt_value(self.fernet, value)
            if key == "external_id":
                self.current_external_id_plain = value
            self.set_field_text(key, value)

        self.apply_external_id_visibility()
        self.format_declared_value()
        self.update_total_declared_value()
        self.update_management_summary(row)

    def update_management_summary(self, row=None):
        if self.management_summary_label is None:
            return
        if row is None:
            self.management_summary_label.setText("尚未選取資料")
            return
        parts = []
        for key, label in (
            ("case_names", "案件"),
            ("tag_names", "標籤"),
            ("custom_values", "自訂欄位"),
            ("last_contact", "最近聯絡"),
            ("next_follow_up", "下次追蹤"),
            ("follow_up_status", "追蹤狀態"),
        ):
            value = str(row[key] or "").strip() if key in row.keys() else ""
            if value:
                parts.append(f"{label}：{compact_summary_text(value)}")
        attachment_names = row["attachment_names"] if "attachment_names" in row.keys() else ""
        attachment_count = row["attachment_count"] if "attachment_count" in row.keys() else 0
        attachment_summary = format_attachment_summary(attachment_names, attachment_count)
        if attachment_summary:
            parts.append(f"附件：{attachment_summary}")
        self.management_summary_label.setText(
            " ｜ ".join(parts) if parts else "此筆資料尚未設定案件、標籤、附件、聯絡或追蹤資訊。"
        )

    def new_record(self):
        self.selected_record_id = None
        self.schedule_selection_state_save()
        self.current_external_id_plain = ""
        self.table_view.clearSelection()
        for key in self.fields:
            self.set_field_text(key, "")
        self.apply_external_id_visibility()
        self.update_management_summary()

    def get_form_data(self):
        self.format_declared_value()
        self.update_total_declared_value()
        data = {}
        for key in self.fields:
            value = self.get_field_text(key)
            data[key] = value or None
        if self.show_full_external_id:
            self.current_external_id_plain = data.get("external_id") or ""
        else:
            data["external_id"] = self.current_external_id_plain or None
        data["ping"] = format_ping_text(data.get("ping") or "")
        data["name"] = data.get("owner_name") or ""
        return data

    def get_plain_record_data(self, row):
        data = {}
        for key in [field_key for field_key, _label in LAND_FIELDS]:
            value = row[key] if key in row.keys() else None
            if key in ENCRYPTED_FIELDS:
                value = decrypt_value(self.fernet, value or "")
            data[key] = value or None
        data["name"] = data.get("owner_name") or ""
        return data

    def record_label(self, record_id, data):
        parts = [
            f"ID {record_id}",
            str(data.get("district") or "").strip(),
            str(data.get("section") or "").strip(),
            str(data.get("land_number") or "").strip(),
            str(data.get("owner_name") or "").strip(),
        ]
        return " / ".join(part for part in parts if part)

    def build_record_change_logs(self, record_id, old_plain, new_plain, action_type="修改資料"):
        logs = []
        label_by_key = {key: label for key, label in LAND_FIELDS}
        for key, label in LAND_FIELDS:
            old_value = "" if old_plain.get(key) is None else str(old_plain.get(key))
            new_value = "" if new_plain.get(key) is None else str(new_plain.get(key))
            if old_value == new_value:
                continue
            stored_old = encrypt_value(self.fernet, old_value) if key in ENCRYPTED_FIELDS else old_value
            stored_new = encrypt_value(self.fernet, new_value) if key in ENCRYPTED_FIELDS else new_value
            logs.append(
                {
                    "customer_id": record_id,
                    "action_type": action_type,
                    "field_key": key,
                    "field_label": label_by_key.get(key, key),
                    "old_value": stored_old,
                    "new_value": stored_new,
                }
            )
        return logs

    def plain_record_change_logs(self, record_id):
        logs = []
        for row in self.active_record_repository().get_record_change_logs(record_id):
            log = dict(row)
            if log.get("field_key") in ENCRYPTED_FIELDS:
                log["old_value"] = decrypt_value(self.fernet, log.get("old_value") or "")
                log["new_value"] = decrypt_value(self.fernet, log.get("new_value") or "")
            logs.append(log)
        return logs

    def plain_follow_up_reminder(self, row):
        if row is None:
            return None
        data = dict(row)
        data["note"] = decrypt_value(self.fernet, data.get("note") or "")
        if "owner_name" in data:
            data["owner_name"] = decrypt_value(self.fernet, data.get("owner_name") or "")
        if "external_id" in data:
            data["external_id"] = decrypt_value(self.fernet, data.get("external_id") or "")
        if "address" in data:
            data["address"] = decrypt_value(self.fernet, data.get("address") or "")
        due_date = str(data.get("due_date") or "")
        try:
            data["is_overdue"] = bool(due_date) and date.fromisoformat(due_date) < date.today()
        except ValueError:
            data["is_overdue"] = False
        return data

    def dashboard_stats(self):
        return build_dashboard_stats(
            self.active_record_repository(),
            plain_record=self.get_plain_record_data,
            plain_reminder=self.plain_follow_up_reminder,
        )

    def normalize_record_data(self, data):
        normalized = dict(data)
        if "declared_value" in normalized:
            normalized["declared_value"] = format_number_text(normalized.get("declared_value") or "") or None
        if "ping" in normalized:
            normalized["ping"] = format_ping_text(normalized.get("ping") or "") or None

        if any(key in normalized for key in ("area", "declared_value", "numerator", "denominator")):
            normalized["ping"] = calculate_ping(normalized) or normalized.get("ping")
            normalized["total_declared_value"] = calculate_total_declared_value(normalized)

        if normalized.get("owner_name"):
            normalized["name"] = normalized["owner_name"]
        else:
            normalized["name"] = None
        return normalized

    def build_batch_edit_preview_lines(self, rows, field_key, field_label, new_value):
        preview_lines = []
        for row in rows[:30]:
            plain_data = self.get_plain_record_data(row)
            old_value = str(plain_data.get(field_key) or "")
            preview_lines.append(
                f"ID {row['id']} | {plain_data.get('district') or ''} {plain_data.get('section') or ''} "
                f"{plain_data.get('land_number') or ''} | {field_label}: {old_value or '(空白)'} -> {new_value or '(清空)'}"
            )
        if len(rows) > 30:
            preview_lines.append(f"...其餘 {len(rows) - 30} 筆未展開")
        return preview_lines

    def batch_edit_checked_records(self):
        if not self.ensure_can_modify("批次修改"):
            return
        if not self.checked_record_ids:
            self._app_component("QMessageBox").warning(self, "尚未勾選", "請先勾選要批次修改的資料。")
            return

        dialog = self._app_component("BatchEditDialog")(len(self.checked_record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return

        field_key, new_value = dialog.values()
        if not field_key:
            return
        if field_key == "owner_name" and new_value and not self.confirm_watchlist_match(new_value):
            return

        ids = sorted(self.checked_record_ids)
        repository = self.active_record_repository()
        rows = repository.fetch_customers_by_ids(ids)
        preview_lines = self.build_batch_edit_preview_lines(
            rows,
            field_key,
            dialog.field_combo.currentText(),
            new_value,
        )
        preview_dialog = self._app_component("BatchEditPreviewDialog")(
            dialog.field_combo.currentText(),
            new_value,
            preview_lines,
            self,
        )
        if preview_dialog.exec() != QDialog.Accepted:
            return
        if not self.api_mode:
            self.create_safety_backup("batch-edit")
        repository.record_customer_undo(
            "批次修改",
            ids,
            f"批次修改 {len(ids)} 筆「{dialog.field_combo.currentText()}」",
        )
        updates = []
        change_logs = []
        for row in rows:
            plain_data = self.get_plain_record_data(row)
            old_plain = dict(plain_data)
            plain_data[field_key] = new_value or None
            normalized = self.normalize_record_data(plain_data)
            updates.append({**encrypt_record(self.fernet, normalized), "id": row["id"]})
            change_logs.extend(
                self.build_record_change_logs(
                    row["id"],
                    old_plain,
                    normalized,
                    "批次修改",
                )
            )
        updated_count = repository.update_customers(updates)
        if change_logs:
            repository.add_record_change_logs(change_logs)

        self.refresh_records(self.selected_record_id)
        self._log_operation("批次修改", f"更新 {updated_count} 筆", f"欄位：{dialog.field_combo.currentText()}")
        self._app_component("QMessageBox").information(self, "批次修改完成", f"已更新 {updated_count} 筆資料。")

    def save_record(self):
        if not self.ensure_can_modify("儲存資料"):
            return
        plain_data = self.normalize_record_data(self.get_form_data())
        if not self.confirm_watchlist_match(plain_data.get("owner_name") or ""):
            return
        record_repository = self.active_record_repository()
        is_new_record = self.selected_record_id is None
        old_plain_data = None
        if not is_new_record:
            old_row = record_repository.get_customer(self.selected_record_id)
            if old_row is not None:
                old_plain_data = self.get_plain_record_data(old_row)
        data = encrypt_record(self.fernet, plain_data)

        change_logs = []
        if not is_new_record and old_plain_data is not None:
            change_logs = self.build_record_change_logs(
                self.selected_record_id,
                old_plain_data,
                plain_data,
                "修改資料",
            )

        try:
            save_with_history = getattr(
                record_repository, "save_customer_with_change_logs", None
            )
            if change_logs and callable(save_with_history):
                self.selected_record_id = save_with_history(
                    data,
                    self.selected_record_id,
                    change_logs,
                )
                change_logs = []
            else:
                self.selected_record_id = record_repository.save_customer(
                    data,
                    self.selected_record_id,
                )
        except (sqlite3.IntegrityError, DesktopApiError) as exc:
            self._app_component("QMessageBox").critical(self, "儲存失敗", database_save_failure_message(exc))
            return

        if change_logs:
            record_repository.add_record_change_logs(change_logs)

        self.refresh_records(self.selected_record_id)
        action_type = "新增資料" if is_new_record else "修改資料"
        self._log_operation(action_type, plain_data.get("owner_name") or "未命名資料", plain_data.get("land_number") or "")
        self._app_component("QMessageBox").information(self, "完成", "資料已儲存。")

    def change_password(self):
        dialog = self._app_component("ChangePasswordDialog")(self)
        if dialog.exec() != QDialog.Accepted:
            return

        current_password, new_password, confirm_password = dialog.values()
        policy_error = validate_new_password(new_password)
        if policy_error:
            self._app_component("QMessageBox").warning(self, "密碼太短", policy_error)
            return
        if new_password != confirm_password:
            self._app_component("QMessageBox").warning(self, "密碼不一致", "兩次輸入的新密碼不一致。")
            return
        if current_password == new_password:
            self._app_component("QMessageBox").warning(self, "密碼未變更", "新密碼不能和目前密碼相同。")
            return

        try:
            repository = self.active_record_repository()
            if self.current_user.get("username") == self.admin_username:
                new_encryption_key, backup_path = repository.change_admin_password(
                    current_password, new_password
                )
            else:
                new_encryption_key, backup_path = repository.change_user_password(
                    self.current_user.get("username"),
                    current_password,
                    new_password,
                    self.encryption_key,
                )
        except ValueError as exc:
            self._app_component("QMessageBox").warning(self, "無法修改密碼", str(exc))
            return
        except Exception as exc:
            self._app_component("QMessageBox").critical(self, "修改失敗", password_change_failure_message(exc))
            return

        self.encryption_key = new_encryption_key
        self.fernet = make_fernet(new_encryption_key)
        self.productivity.fernet = self.fernet
        self.refresh_records(self.selected_record_id)
        self._log_operation("修改密碼", "更新登入與解密密碼", str(backup_path) if backup_path else "")
        self._app_component("QMessageBox").information(self, "修改完成", password_changed_message(backup_path))

    def delete_record(self):
        if not self.ensure_can_modify("刪除資料"):
            return
        if self.selected_record_id is None:
            self._app_component("QMessageBox").warning(self, "尚未選取", "請先選取資料。")
            return
        reply = self._app_component("QMessageBox").question(self, "確認刪除", "確定要刪除這筆土地資料嗎？")
        if reply != self._app_component("QMessageBox").Yes:
            return
        try:
            self.active_record_repository().delete_customers([self.selected_record_id])
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "刪除失敗", str(exc))
            return
        self.checked_record_ids.discard(self.selected_record_id)
        self._log_operation("刪除資料", f"ID {self.selected_record_id}", "")
        self.new_record()
        self.refresh_records()

    def delete_checked_records(self):
        if not self.ensure_can_modify("清除勾選資料"):
            return
        if not self.checked_record_ids:
            self._app_component("QMessageBox").warning(self, "尚未勾選", "請先勾選要清除的資料。")
            return
        count = len(self.checked_record_ids)
        reply = self._app_component("QMessageBox").question(self, "確認清除", f"確定要清除已勾選的 {count} 筆資料嗎？")
        if reply != self._app_component("QMessageBox").Yes:
            return
        if not self.api_mode:
            self.create_safety_backup("delete-selected")
        ids = sorted(self.checked_record_ids)
        self.active_record_repository().delete_customers(ids)
        self.checked_record_ids.clear()
        self._log_operation("清除勾選", f"刪除 {count} 筆", "")
        self.new_record()
        self.refresh_records()

    def delete_all_records(self):
        if not self.ensure_can_modify("全部清除"):
            return
        messages = (
            "這會清除全部資料，確定要繼續嗎？",
            "第二次確認：所有土地資料都會被刪除，確定嗎？",
            "最後確認：按「是」後會清空全部資料，無法從系統內復原。確定清除？",
        )
        for message in messages:
            reply = self._app_component("QMessageBox").question(self, "全部清除確認", message)
            if reply != self._app_component("QMessageBox").Yes:
                return
        if not self.api_mode:
            self.create_safety_backup("delete-all")
        self.active_record_repository().delete_all_customers()
        self.checked_record_ids.clear()
        self._log_operation("全部清除", "清空全部資料", "")
        self.new_record()
        self.refresh_records()

    def encrypt_existing_records(self):
        if not self.ensure_can_modify("加密既有資料"):
            return
        reply = self._app_component("QMessageBox").question(
            self,
            "加密既有資料",
            "這會將目前資料庫裡的姓名、身分證、地址、備註、出訪記錄轉為加密儲存。確定要執行嗎？",
        )
        if reply != self._app_component("QMessageBox").Yes:
            return

        if not self.api_mode:
            self.create_safety_backup("encrypt")
        updated = self.active_record_repository().encrypt_existing_customers(self.fernet)

        self.refresh_records(self.selected_record_id)
        self._log_operation("加密資料", f"處理 {updated} 筆", "")
        self._app_component("QMessageBox").information(self, "加密完成", f"已處理 {updated} 筆既有資料。")
