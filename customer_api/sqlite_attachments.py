"""SQLite external and managed attachment workflows."""

from pathlib import Path

from customer_api.data_source_base import _row_dict


class SQLiteAttachmentMixin:
    def list_attachments(self, user, record_id):
        del user
        if self.repository.get_customer(int(record_id)) is None:
            raise KeyError(record_id)
        return [
            _row_dict(row)
            for row in self.repository.list_customer_attachments(int(record_id))
        ]

    def get_attachment(self, user, record_id, attachment_id):
        rows = self.list_attachments(user, record_id)
        return next(
            (row for row in rows if int(row["id"]) == int(attachment_id)), None
        )

    def add_external_attachment(self, user, record_id, file_path, description=""):
        record_id = int(record_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        attachment_id = int(
            self.repository.add_customer_attachment(
                record_id, file_path, description
            )
        )
        self.repository.log_operation(
            "API新增外部附件",
            f"資料 ID {record_id}",
            f"附件 ID {attachment_id}",
        )
        return attachment_id

    def import_managed_attachment(
        self,
        user,
        record_id,
        source_path,
        original_name,
        description="",
        media_type="",
    ):
        del media_type
        record_id = int(record_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        self.repository.current_actor = user.username
        attachment_id = int(
            self.repository.import_managed_attachment(
                record_id,
                source_path,
                self.settings.attachment_directory,
                description,
            )
        )
        safe_name = Path(str(original_name or "attachment")).name or "attachment"
        with self.repository.database.connect() as conn:
            conn.execute(
                "UPDATE customer_attachments SET original_name = ? WHERE id = ?",
                (safe_name, attachment_id),
            )
        self.repository.log_operation(
            "API上傳納管附件",
            f"資料 ID {record_id}",
            f"附件 ID {attachment_id}",
        )
        return attachment_id

    def delete_attachment(self, user, record_id, attachment_id):
        record_id = int(record_id)
        attachment_id = int(attachment_id)
        if self.repository.get_customer(record_id) is None:
            raise KeyError(record_id)
        if self.get_attachment(user, record_id, attachment_id) is None:
            return False
        self.repository.current_actor = user.username
        deleted = bool(
            self.repository.delete_customer_attachment(
                attachment_id, self.settings.attachment_directory
            )
        )
        if deleted:
            self.repository.log_operation(
                "API刪除附件",
                f"資料 ID {record_id}",
                f"附件 ID {attachment_id}",
            )
        return deleted
