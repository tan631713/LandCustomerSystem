"""Desktop customer-management workflows independent from the main window module."""

import sqlite3

from customer_desktop_api import DesktopApiError
from customer_desktop import open_path_or_web_url
from customer_fields import LAND_FIELDS
from customer_security import decrypt_value, encrypt_record, encrypt_value
from PySide6.QtWidgets import QDialog


class ManagementWorkflowMixin:
    def add_selected_records_to_field_visit(self):
        if not getattr(self, "api_mode", False):
            self._app_component("QMessageBox").information(
                self,
                "需要連線伺服器",
                "今日行程由網路伺服器統一管理，請使用公司筆電客戶端連線後操作。",
            )
            return
        if not self.ensure_can_modify("加入今日行程"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(
                self,
                "未選取資料",
                "請先選取或勾選要加入今日行程的資料。",
            )
            return
        dialog = self._app_component("FieldVisitScheduleDialog")(
            len(record_ids), self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        repository = self.active_record_repository()
        try:
            result = repository.add_customers_to_field_visit(
                record_ids,
                visit_date=dialog.selected_date(),
                title=dialog.title(),
                priority=dialog.priority(),
            )
        except (DesktopApiError, ValueError) as exc:
            self._app_component("QMessageBox").critical(
                self, "加入行程失敗", str(exc)
            )
            return
        added = int(result.get("added_count") or 0)
        existing = int(result.get("existing_count") or 0)
        message = f"已加入 {added} 筆資料到 {result.get('visit_date')} 的行程。"
        if added and int(result.get("priority") or 0) > 0:
            message += "\n本次新增資料已設為優先拜訪。"
        if existing:
            message += f"\n另有 {existing} 筆原本已在該行程內。"
        self._app_component("QMessageBox").information(
            self, "加入行程完成", message
        )

    def manage_cases(self):
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        dialog = self._app_component("CaseManagementDialog")(cases, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if dialog.action == "view":
            self.filter_management_records("case_names", values.get("title"))
            return
        if not self.ensure_can_modify("案件管理"):
            return
        try:
            if dialog.action == "save":
                case_id = repository.save_case(
                    values["title"],
                    values["status"],
                    values["note"],
                    values["case_id"],
                )
                if not self.api_mode:
                    self._log_operation("案件管理", f"儲存案件 {case_id}", values["title"])
            elif dialog.action == "delete":
                if self._app_component("QMessageBox").question(self, "刪除案件", "確定刪除選取案件？案件關聯會一起移除。") != self._app_component("QMessageBox").Yes:
                    return
                repository.delete_case(values["case_id"])
                if not self.api_mode:
                    self._log_operation("案件管理", f"刪除案件 {values['case_id']}", "")
        except (sqlite3.IntegrityError, ValueError, DesktopApiError) as exc:
            self._app_component("QMessageBox").warning(self, "案件管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def assign_checked_records_to_case(self):
        if not self.ensure_can_modify("加入案件"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取或勾選要加入案件的資料。")
            return
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if not cases:
            self._app_component("QMessageBox").information(self, "尚無案件", "請先建立案件。")
            self.manage_cases()
            return
        dialog = self._app_component("CaseSelectDialog")(cases, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            added = repository.add_customers_to_case(
                dialog.selected_case_id(), record_ids
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "加入案件失敗", str(exc))
            return
        if not self.api_mode:
            self._log_operation("加入案件", f"加入 {added} 筆資料", f"case_id={dialog.selected_case_id()}")
        self.refresh_records(self.selected_record_id)
        self._app_component("QMessageBox").information(self, "完成", f"已加入 {added} 筆資料到案件。")

    def remove_selected_records_from_case(self):
        if not self.ensure_can_modify("從案件移除資料"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取或勾選要從案件移除的資料。")
            return
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if not cases:
            self._app_component("QMessageBox").information(self, "尚無案件", "目前沒有可移除的案件。")
            return
        dialog = self._app_component("CaseSelectDialog")(
            cases,
            len(record_ids),
            self,
            dialog_title="從案件移除資料",
            action_text="移除",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            removed = repository.remove_customers_from_case(
                dialog.selected_case_id(),
                record_ids,
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "移出案件失敗", str(exc))
            return
        if not self.api_mode:
            self._log_operation(
                "移出案件",
                f"移除 {removed} 筆資料",
                f"case_id={dialog.selected_case_id()}",
            )
        self.refresh_records(self.selected_record_id)
        self._app_component("QMessageBox").information(self, "完成", f"已從案件移除 {removed} 筆資料。")

    def batch_edit_customer_tags(self):
        if not self.ensure_can_modify("批量設定標籤"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取或勾選要設定標籤的資料。")
            return
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if not tags:
            self._app_component("QMessageBox").information(self, "尚無標籤", "請先建立標籤。")
            self.manage_tags()
            return
        dialog = self._app_component("BatchCustomerTagsDialog")(tags, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            processed = repository.set_customers_tags(
                record_ids,
                dialog.selected_ids(),
                dialog.mode(),
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "設定失敗", str(exc))
            return
        if not self.api_mode:
            self._log_operation(
                "批量設定標籤",
                f"處理 {processed} 筆資料",
                f"mode={dialog.mode()} / tags={dialog.selected_ids()}",
            )
        self.refresh_records(self.selected_record_id)
        self._app_component("QMessageBox").information(self, "完成", f"已更新 {processed} 筆資料的標籤。")

    def batch_edit_custom_values(self):
        if not self.ensure_can_modify("批量設定自訂欄位"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取或勾選要設定自訂欄位的資料。")
            return
        repository = self.active_record_repository()
        fields = repository.list_custom_fields()
        if not fields:
            self._app_component("QMessageBox").information(self, "尚無自訂欄位", "請先建立自訂欄位。")
            self.manage_custom_fields()
            return
        dialog = self._app_component("BatchCustomerCustomValuesDialog")(fields, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_values()
        processed = repository.set_customers_custom_values(record_ids, values)
        self._log_operation(
            "批量設定自訂欄位",
            f"處理 {processed} 筆資料",
            f"fields={sorted(values)}",
        )
        self.refresh_records(self.selected_record_id)
        self._app_component("QMessageBox").information(self, "完成", f"已更新 {processed} 筆資料的自訂欄位。")

    def manage_tags(self):
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        dialog = self._app_component("TagManagementDialog")(tags, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if dialog.action == "view":
            self.filter_management_records("tag_names", values.get("name"))
            return
        if not self.ensure_can_modify("標籤管理"):
            return
        try:
            if dialog.action == "save":
                tag_id = repository.save_tag(
                    values["name"], values["color"], values["tag_id"]
                )
                if not self.api_mode:
                    self._log_operation("標籤管理", f"儲存標籤 {tag_id}", values["name"])
            elif dialog.action == "delete":
                if self._app_component("QMessageBox").question(self, "刪除標籤", "確定刪除選取標籤？") != self._app_component("QMessageBox").Yes:
                    return
                repository.delete_tag(values["tag_id"])
                if not self.api_mode:
                    self._log_operation("標籤管理", f"刪除標籤 {values['tag_id']}", "")
        except (sqlite3.IntegrityError, ValueError, DesktopApiError) as exc:
            self._app_component("QMessageBox").warning(self, "標籤管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def edit_customer_tags(self):
        if not self.ensure_can_modify("設定標籤"):
            return
        _row, plain_data = self.selected_record_plain_data()
        if plain_data is None:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取一筆資料。")
            return
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
            selected_tag_ids = repository.get_customer_tag_ids(
                self.selected_record_id
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if not tags:
            self._app_component("QMessageBox").information(self, "尚無標籤", "請先建立標籤。")
            self.manage_tags()
            return
        dialog = self._app_component("CustomerTagsDialog")(
            tags,
            selected_tag_ids,
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            count = repository.set_customer_tags(
                self.selected_record_id, dialog.selected_ids()
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "設定失敗", str(exc))
            return
        if not self.api_mode:
            self._log_operation(
                "設定標籤",
                self.record_label(self.selected_record_id, plain_data),
                f"{count} 個標籤",
            )
        self.refresh_records(self.selected_record_id)

    def manage_attachments(self):
        repository = self.active_record_repository()
        try:
            _row, plain_data = self.selected_record_plain_data()
            attachments = (
                repository.list_customer_attachments(self.selected_record_id)
                if plain_data is not None
                else []
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if plain_data is None:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取一筆資料。")
            return
        open_attachment = None
        if self.api_mode:
            def open_attachment(attachment):
                try:
                    if str(attachment.get("status") or "").casefold() == "external":
                        target = str(attachment.get("file_path") or "")
                    else:
                        target = repository.download_customer_attachment(
                            attachment.get("id")
                        )
                except (DesktopApiError, OSError, ValueError) as exc:
                    self._app_component("QMessageBox").warning(
                        self, "附件開啟失敗", str(exc)
                    )
                    return False
                return open_path_or_web_url(target, self, item_label="附件")

        dialog = self._app_component("AttachmentDialog")(
            attachments,
            self.record_label(self.selected_record_id, plain_data),
            self,
            open_attachment=open_attachment,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("附件管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "add":
                if values.get("managed"):
                    attachment_id = repository.import_managed_attachment(
                        self.selected_record_id,
                        values["file_path"],
                        self.attachments_dir,
                        values["description"],
                    )
                else:
                    attachment_id = repository.add_customer_attachment(
                        self.selected_record_id,
                        values["file_path"],
                        values["description"],
                    )
                if not self.api_mode:
                    self._log_operation("新增附件", self.record_label(self.selected_record_id, plain_data), values["file_path"])
                saved_as = "系統納管附件" if values.get("managed") else "外部連結"
                self._app_component("QMessageBox").information(self, "完成", f"已新增附件 ID {attachment_id}（{saved_as}）。")
            elif dialog.action == "delete":
                repository.delete_customer_attachment(
                    values["attachment_id"], self.attachments_dir
                )
                if not self.api_mode:
                    self._log_operation("刪除附件", self.record_label(self.selected_record_id, plain_data), str(values["attachment_id"]))
        except (ValueError, DesktopApiError) as exc:
            self._app_component("QMessageBox").warning(self, "附件管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def manage_custom_fields(self):
        repository = self.active_record_repository()
        dialog = self._app_component("CustomFieldManagementDialog")(
            repository.list_custom_fields(), self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("自訂欄位管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "save":
                field_id = repository.save_custom_field(
                    values["label"],
                    values["field_key"],
                    values["field_id"],
                )
                self._log_operation("自訂欄位管理", f"儲存欄位 {field_id}", values["label"])
            elif dialog.action == "delete":
                if self._app_component("QMessageBox").question(self, "刪除自訂欄位", "確定刪除選取欄位與所有填寫值？") != self._app_component("QMessageBox").Yes:
                    return
                repository.delete_custom_field(values["field_id"])
                self._log_operation("自訂欄位管理", f"刪除欄位 {values['field_id']}", "")
        except (sqlite3.IntegrityError, ValueError, DesktopApiError) as exc:
            self._app_component("QMessageBox").warning(self, "自訂欄位失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def edit_customer_custom_values(self):
        if not self.ensure_can_modify("設定自訂欄位"):
            return
        _row, plain_data = self.selected_record_plain_data()
        if plain_data is None:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取一筆資料。")
            return
        repository = self.active_record_repository()
        fields = repository.list_custom_fields()
        if not fields:
            self._app_component("QMessageBox").information(self, "尚無自訂欄位", "請先建立自訂欄位。")
            self.manage_custom_fields()
            return
        dialog = self._app_component("CustomerCustomValuesDialog")(
            fields,
            repository.get_customer_custom_values(self.selected_record_id),
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        count = repository.set_customer_custom_values(
            self.selected_record_id,
            dialog.result_values(),
        )
        self._log_operation("設定自訂欄位", self.record_label(self.selected_record_id, plain_data), f"{count} 個欄位")
        self.refresh_records(self.selected_record_id)

    def manage_text_templates(self):
        repository = self.active_record_repository()
        dialog = self._app_component("TextTemplateDialog")(
            repository.list_text_templates(), self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("快速範本管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "save":
                template_id = repository.save_text_template(
                    values["title"],
                    values["content"],
                    values["template_type"],
                    values["template_id"],
                )
                self._log_operation("快速範本管理", f"儲存範本 {template_id}", values["title"])
            elif dialog.action == "delete":
                repository.delete_text_template(values["template_id"])
                self._log_operation("快速範本管理", f"刪除範本 {values['template_id']}", "")
        except (ValueError, DesktopApiError) as exc:
            self._app_component("QMessageBox").warning(self, "快速範本失敗", str(exc))

    def apply_text_template(self):
        if not self.ensure_can_modify("套用快速範本"):
            return
        templates = self.active_record_repository().list_text_templates()
        if not templates:
            self._app_component("QMessageBox").information(self, "尚無範本", "請先建立快速範本。")
            self.manage_text_templates()
            return
        dialog = self._app_component("ApplyTemplateDialog")(templates, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        template = values.get("template")
        if not template:
            return
        target = values.get("target_field")
        current_text = self.get_field_text(target)
        addition = template.get("content") or ""
        separator = "\n" if current_text else ""
        self.set_field_text(target, f"{current_text}{separator}{addition}")
        self.statusBar().showMessage("已套用快速範本，請記得儲存資料。", 3500)

    def plain_contact_logs(self, customer_id):
        logs = []
        for row in self.active_record_repository().list_contact_logs(customer_id):
            log = dict(row)
            log["note"] = decrypt_value(self.fernet, log.get("note") or "")
            logs.append(log)
        return logs

    def manage_contact_logs(self):
        repository = self.active_record_repository()
        try:
            _row, plain_data = self.selected_record_plain_data()
            logs = (
                self.plain_contact_logs(self.selected_record_id)
                if plain_data is not None
                else []
            )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "讀取失敗", str(exc))
            return
        if plain_data is None:
            self._app_component("QMessageBox").warning(self, "未選取資料", "請先選取一筆資料。")
            return
        dialog = self._app_component("ContactLogDialog")(
            logs,
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("聯絡紀錄"):
            return
        values = dialog.values()
        try:
            if dialog.action == "add":
                note = encrypt_value(self.fernet, values.get("note") or "")
                repository.add_contact_log(
                    self.selected_record_id,
                    values.get("contact_date"),
                    values.get("method"),
                    values.get("result"),
                    values.get("next_follow_up"),
                    note,
                )
                if values.get("next_follow_up") and not self.api_mode:
                    existing = repository.get_follow_up_reminder(
                        self.selected_record_id
                    )
                    repository.save_follow_up_reminder(
                        self.selected_record_id,
                        values.get("next_follow_up"),
                        existing["status"] if existing is not None else "未處理",
                        existing["note"]
                        if existing is not None
                        else encrypt_value(self.fernet, ""),
                    )
                if not self.api_mode:
                    self._log_operation(
                        "新增聯絡紀錄",
                        self.record_label(self.selected_record_id, plain_data),
                        values.get("method") or "",
                    )
            elif dialog.action == "delete":
                repository.delete_contact_log(values["log_id"])
                if not self.api_mode:
                    self._log_operation(
                        "刪除聯絡紀錄",
                        self.record_label(self.selected_record_id, plain_data),
                        str(values["log_id"]),
                    )
        except DesktopApiError as exc:
            self._app_component("QMessageBox").critical(self, "操作失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def merged_plain_record(self, primary, secondary, secondary_id):
        merged = dict(primary)
        for key, _label in LAND_FIELDS:
            primary_value = str(primary.get(key) or "").strip()
            secondary_value = str(secondary.get(key) or "").strip()
            if key in {"note", "visit_log"} and primary_value and secondary_value and primary_value != secondary_value:
                merged[key] = f"{primary_value}\n--- 合併自 ID {secondary_id} ---\n{secondary_value}"
            elif not primary_value and secondary_value:
                merged[key] = secondary.get(key)
        merged["name"] = merged.get("owner_name") or ""
        return self.normalize_record_data(merged)

    def merge_checked_records(self):
        if not self.ensure_can_modify("合併資料"):
            return
        ids = sorted(self.checked_record_ids)
        if len(ids) != 2:
            self._app_component("QMessageBox").warning(self, "勾選數量不正確", "請剛好勾選兩筆資料再合併。")
            return
        repository = self.active_record_repository()
        rows = repository.fetch_customers_by_ids(ids)
        if len(rows) != 2:
            self._app_component("QMessageBox").warning(self, "資料不存在", "勾選資料已不存在，請重新整理後再試。")
            return
        primary_row, secondary_row = rows
        primary_plain = self.get_plain_record_data(primary_row)
        secondary_plain = self.get_plain_record_data(secondary_row)
        merged_plain = self.merged_plain_record(primary_plain, secondary_plain, secondary_row["id"])
        label_by_key = {key: label for key, label in LAND_FIELDS}
        preview_lines = []
        for key, _label in LAND_FIELDS:
            old_value = str(primary_plain.get(key) or "")
            new_value = str(merged_plain.get(key) or "")
            if old_value != new_value:
                preview_lines.append(f"{label_by_key.get(key, key)}: {old_value or '(空白)'} -> {new_value or '(空白)'}")
        if not preview_lines:
            preview_lines.append("主資料欄位沒有變更；仍會轉移案件、標籤、附件、自訂欄位與聯絡紀錄。")
        dialog = self._app_component("MergeRecordsDialog")(
            self.record_label(primary_row["id"], primary_plain),
            self.record_label(secondary_row["id"], secondary_plain),
            preview_lines,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.api_mode:
            self.create_safety_backup("merge")
            repository.record_customer_undo(
                "合併資料",
                ids,
                f"合併 ID {primary_row['id']} 與 {secondary_row['id']}",
            )
        change_logs = self.build_record_change_logs(
            primary_row["id"],
            primary_plain,
            merged_plain,
            "合併資料",
        )
        repository.merge_customers(
            primary_row["id"],
            secondary_row["id"],
            encrypt_record(self.fernet, merged_plain),
        )
        if change_logs:
            repository.add_record_change_logs(change_logs)
        self.checked_record_ids.discard(secondary_row["id"])
        self.checked_record_ids.add(primary_row["id"])
        self._log_operation("合併資料", f"保留 ID {primary_row['id']}", f"刪除 ID {secondary_row['id']}")
        self.refresh_records(primary_row["id"])
        self._app_component("QMessageBox").information(self, "合併完成", f"已保留 ID {primary_row['id']}，並合併/刪除 ID {secondary_row['id']}。")
