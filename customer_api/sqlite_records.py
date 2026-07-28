"""SQLite customer-record persistence workflows."""

from pathlib import Path

from customer_api.data_source_base import _decrypt_record, _encrypted_record, _filter_records


class SQLiteRecordMixin:
    def list_records(
        self,
        user,
        *,
        query="",
        filters=None,
        offset=0,
        limit=100,
    ):
        records = [
            _decrypt_record(row, user) for row in self.repository.fetch_all_customer_rows()
        ]
        matched = _filter_records(records, query=query, filters=filters)
        offset = max(0, int(offset))
        limit = max(1, int(limit))
        return {"total": len(matched), "items": matched[offset : offset + limit]}

    def get_record(self, user, record_id):
        row = self.repository.get_customer(int(record_id))
        return None if row is None else _decrypt_record(row, user)

    def save_record(self, user, values, record_id=None):
        if record_id is not None and self.repository.get_customer(int(record_id)) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        saved_id = int(
            self.repository.save_customer(
                _encrypted_record(user, values),
                None if record_id is None else int(record_id),
            )
        )
        self.repository.log_operation(
            "API新增資料" if record_id is None else "API修改資料",
            f"資料 ID {saved_id}",
        )
        return saved_id

    def save_record_with_change_logs(
        self, user, values, record_id, change_logs
    ):
        saved_id = self.save_record(user, values, record_id=record_id)
        normalized_logs = [
            {**dict(item), "record_id": saved_id} for item in change_logs
        ]
        self.add_record_change_logs(user, normalized_logs)
        return saved_id

    def delete_record(self, user, record_id):
        record_id = int(record_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        deleted = bool(self.repository.delete_customers([record_id]))
        if deleted:
            self.repository.log_operation("API刪除資料", f"資料 ID {record_id}")
        return deleted

    def import_records(self, user, items, source_file_name="import.xlsx"):
        items = [dict(item) for item in items]
        update_ids = [
            int(item["record_id"])
            for item in items
            if item.get("record_id") is not None
        ]
        if any(self.repository.get_customer(record_id) is None for record_id in update_ids):
            raise KeyError("records contain missing ids")
        inserted_values = [
            _encrypted_record(user, item["values"])
            for item in items
            if item.get("record_id") is None
        ]
        updated_values = [
            {
                **_encrypted_record(user, item["values"]),
                "id": int(item["record_id"]),
            }
            for item in items
            if item.get("record_id") is not None
        ]
        self.repository.current_actor = user.username
        inserted_count = int(self.repository.insert_customers(inserted_values))
        inserted_ids = [
            int(record_id) for record_id in self.repository.last_inserted_customer_ids
        ]
        updated_count = int(self.repository.update_customers(updated_values))
        self.repository.log_operation(
            "API Excel 匯入",
            f"新增 {inserted_count} 筆，更新 {updated_count} 筆",
            Path(str(source_file_name or "import.xlsx")).name,
        )
        return {
            "batch_id": None,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "inserted_ids": inserted_ids,
            "updated_ids": update_ids,
        }
