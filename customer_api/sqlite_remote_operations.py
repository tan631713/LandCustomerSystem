"""SQLite adapters for the full desktop remote-operation API."""

from customer_api.data_source_base import _row_dict
from customer_security import encrypt_record, make_fernet


class SQLiteRemoteOperationMixin:
    def list_recycle_bin(self, user, limit=1000):
        del user
        return [_row_dict(row) for row in self.repository.list_recycle_bin(limit)]

    def restore_recycle_items(self, user, ids):
        self.repository.current_actor = user.username
        return self.repository.restore_recycle_items(ids)

    def purge_recycle_items(self, user, ids=None):
        self.repository.current_actor = user.username
        return self.repository.purge_recycle_items(ids)

    def record_customer_undo(self, user, operation_type, ids, summary):
        self.repository.current_actor = user.username
        return self.repository.record_customer_undo(operation_type, ids, summary)

    def record_insert_undo(self, user, operation_type, ids, summary):
        self.repository.current_actor = user.username
        return self.repository.record_insert_undo(operation_type, ids, summary)

    def list_undo_operations(self, user, limit=100):
        del user
        return [_row_dict(row) for row in self.repository.list_undo_operations(limit)]

    def undo_operation(self, user, operation_id=None):
        self.repository.current_actor = user.username
        return self.repository.undo_operation(operation_id)

    def merge_records(self, user, primary_id, secondary_id, values):
        self.repository.current_actor = user.username
        self.repository.record_customer_undo(
            "合併資料", [primary_id, secondary_id],
            f"合併 ID {primary_id} 與 {secondary_id}",
        )
        return self.repository.merge_customers(
            primary_id, secondary_id,
            encrypt_record(make_fernet(user.data_key), values),
        )

    def refresh_notifications(self, user, today_text):
        self.repository.current_actor = user.username
        self.repository.refresh_notifications(today_text)
        return len(self.repository.list_notifications(include_read=True))

    def list_notifications(self, user, include_read=False, limit=500):
        del user
        return [_row_dict(row) for row in self.repository.list_notifications(include_read, limit)]

    def mark_notifications(self, user, ids, action="read"):
        self.repository.current_actor = user.username
        return self.repository.mark_notifications(ids, action)

    def list_users(self, user):
        del user
        return [_row_dict(row) for row in self.repository.list_users()]

    def create_user(self, user, username, password, role, display_name=None):
        return self.repository.create_user(username, password, role, user.data_key, display_name)

    def update_user(self, user, user_id, **values):
        del user
        return self.repository.update_user(user_id, **values)

    def reset_user_password(self, user, user_id, new_password):
        return self.repository.reset_user_password(user_id, new_password, user.data_key)

    def change_password(self, user, current_password, new_password):
        self.repository.change_user_password(user.username, current_password, new_password, user.data_key)
        return True

    def encrypt_existing_records(self, user):
        updated = self.repository.encrypt_existing_customers(make_fernet(user.data_key))
        return {
            "updated_records": int(updated),
            "updated_owner_rows": int(updated),
            "updated_ownership_rows": int(updated),
        }

    def list_server_backup_targets(self, user):
        del user
        return [_row_dict(row) for row in self.repository.list_backup_targets()]

    def save_server_backup_target(
        self, user, name, directory_path, enabled=True, target_id=None
    ):
        del user
        return self.repository.save_backup_target(
            name, directory_path, enabled=enabled, target_id=target_id
        )

    def delete_server_backup_target(self, user, target_id):
        del user
        return bool(self.repository.delete_backup_target(target_id))

    def update_server_backup_target_result(self, user, target_id, error=None):
        del user
        self.repository.update_backup_target_result(target_id, error)
