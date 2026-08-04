"""SQLite contact-log and follow-up workflows."""

from customer_api.data_source_base import _decrypt_record, _row_dict


class SQLiteCollaborationMixin:
    def list_contact_logs(self, user, record_id):
        del user
        return [
            _row_dict(row) for row in self.repository.list_contact_logs(int(record_id))
        ]

    def add_contact_log(
        self,
        user,
        record_id,
        values,
        idempotency_key=None,
        request_hash=None,
    ):
        del idempotency_key, request_hash
        if self.repository.get_customer(int(record_id)) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        log_id = int(
            self.repository.add_contact_log(
                int(record_id),
                contact_date=values.get("contact_date"),
                method=values.get("method"),
                result=values.get("result"),
                next_follow_up=values.get("next_follow_up"),
                note=values.get("note"),
            )
        )
        self.repository.log_operation(
            "API新增聯絡紀錄",
            f"資料 ID {int(record_id)}",
            f"聯絡紀錄 ID {log_id}",
        )
        return log_id

    def delete_contact_log(self, user, record_id, log_id):
        record_id = int(record_id)
        log_id = int(log_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        rows = self.repository.list_contact_logs(record_id)
        if not any(int(row["id"]) == log_id for row in rows):
            return False
        self.repository.current_actor = user.username
        deleted = bool(self.repository.delete_contact_log(log_id))
        if deleted:
            self.repository.log_operation(
                "API刪除聯絡紀錄",
                f"資料 ID {record_id}",
                f"聯絡紀錄 ID {log_id}",
            )
        return deleted

    def get_follow_up(self, user, record_id):
        del user
        row = self.repository.get_follow_up_reminder(int(record_id))
        return _row_dict(row) if row is not None else None

    def save_follow_up(self, user, record_id, values):
        if self.repository.get_customer(int(record_id)) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        self.repository.save_follow_up_reminder(
            int(record_id),
            due_date=values.get("due_date"),
            status=values.get("status") or "未處理",
            note=values.get("note"),
        )
        self.repository.log_operation(
            "API設定追蹤提醒",
            f"資料 ID {int(record_id)}",
            str(values.get("due_date") or "未設定日期"),
        )

    def delete_follow_up(self, user, record_id):
        record_id = int(record_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        deleted = bool(self.repository.delete_follow_up_reminder(record_id))
        if deleted:
            self.repository.log_operation(
                "API清除追蹤提醒", f"資料 ID {record_id}"
            )
        return deleted

    def list_follow_ups(self, user, limit=500):
        items = []
        for row in self.repository.list_follow_up_reminders(limit=int(limit)):
            item = _decrypt_record(row, user)
            item["next_follow_up"] = item.get("due_date") or ""
            item["follow_up_status"] = item.get("status") or ""
            items.append(item)
        return items

    def list_contact_logs_by_date(self, user, target_date, mine_only=False):
        del mine_only
        items = []
        for row in self.repository.list_contact_logs_by_date(str(target_date)):
            item = _decrypt_record(row, user)
            item["note"] = item.pop("log_note", "") or ""
            item["created_by_name"] = ""
            items.append(item)
        return items
