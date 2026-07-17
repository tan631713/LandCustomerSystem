"""SQLite tag and assignment workflows."""

from customer_api.data_source_base import _row_dict


class SQLiteTagMixin:
    def list_tags(self, user):
        del user
        return [_row_dict(row) for row in self.repository.list_tags()]

    def save_tag(self, user, name, color="", tag_id=None):
        self.repository.current_actor = user.username
        saved_id = int(self.repository.save_tag(name, color, tag_id))
        self.repository.log_operation(
            "API儲存標籤", f"標籤 ID {saved_id}", str(name or "")
        )
        return saved_id

    def delete_tag(self, user, tag_id):
        self.repository.current_actor = user.username
        deleted = bool(self.repository.delete_tag(int(tag_id)))
        if deleted:
            self.repository.log_operation("API刪除標籤", f"標籤 ID {int(tag_id)}")
        return deleted

    def get_record_tag_ids(self, user, record_id):
        del user
        if self.repository.get_customer(int(record_id)) is None:
            raise KeyError(record_id)
        return {
            int(tag_id)
            for tag_id in self.repository.get_customer_tag_ids(int(record_id))
        }

    def set_record_tags(self, user, record_id, tag_ids):
        record_id = int(record_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        count = int(self.repository.set_customer_tags(record_id, tag_ids))
        self.repository.log_operation(
            "API設定標籤", f"資料 ID {record_id}", f"{count} 個標籤"
        )
        return count

    def set_records_tags(self, user, record_ids, tag_ids, mode="add"):
        self.repository.current_actor = user.username
        count = int(self.repository.set_customers_tags(record_ids, tag_ids, mode))
        self.repository.log_operation(
            "API批量設定標籤", f"處理 {count} 筆資料", f"mode={mode}"
        )
        return count
