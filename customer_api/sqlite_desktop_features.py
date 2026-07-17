"""SQLite adapters for the complete desktop productivity API."""

from customer_api.data_source_base import _row_dict


class SQLiteDesktopFeatureMixin:
    @staticmethod
    def _dict_rows(rows):
        return [_row_dict(row) for row in rows]

    def list_record_change_logs(self, user, record_id, limit=300):
        del user
        return self._dict_rows(
            self.repository.get_record_change_logs(int(record_id), int(limit))
        )

    def add_record_change_logs(self, user, items):
        del user
        logs = [
            {**dict(item), "customer_id": int(item["record_id"])}
            for item in items
        ]
        return int(self.repository.add_record_change_logs(logs))

    def list_custom_fields(self, user):
        del user
        return self._dict_rows(self.repository.list_custom_fields())

    def save_custom_field(self, user, label, field_key=None, field_id=None):
        del user
        return int(self.repository.save_custom_field(label, field_key, field_id))

    def delete_custom_field(self, user, field_id):
        del user
        return bool(self.repository.delete_custom_field(int(field_id)))

    def get_record_custom_values(self, user, record_id):
        del user
        return {
            int(field_id): value
            for field_id, value in self.repository.get_customer_custom_values(
                int(record_id)
            ).items()
        }

    def set_record_custom_values(self, user, record_id, values):
        del user
        return int(
            self.repository.set_customer_custom_values(int(record_id), values)
        )

    def set_records_custom_values(self, user, record_ids, values):
        del user
        return int(
            self.repository.set_customers_custom_values(record_ids, values)
        )

    def list_text_templates(self, user, template_type=None):
        del user
        return self._dict_rows(
            self.repository.list_text_templates(template_type=template_type)
        )

    def save_text_template(
        self, user, title, content, template_type="note", template_id=None
    ):
        del user
        return int(
            self.repository.save_text_template(
                title, content, template_type, template_id
            )
        )

    def delete_text_template(self, user, template_id):
        del user
        return bool(self.repository.delete_text_template(int(template_id)))

    def list_watchlist(self, user):
        del user
        return self._dict_rows(self.repository.get_watchlist_entries())

    def replace_watchlist(self, user, items):
        del user
        self.repository.replace_watchlist_entries(items)
        return len(self.repository.get_watchlist_entries())

    def list_operation_logs(self, user, limit=300):
        del user
        return self._dict_rows(self.repository.get_operation_logs(int(limit)))

    def add_operation_log(self, user, action_type, summary, detail=""):
        self.repository.current_actor = user.username
        return self.repository.log_operation(action_type, summary, detail)

    def list_record_locations(self, user):
        del user
        return self._dict_rows(self.repository.list_customer_locations())

    def set_record_location(
        self, user, record_id, latitude, longitude, source="manual"
    ):
        del user
        self.repository.set_customer_location(
            int(record_id), latitude, longitude, source
        )
        return int(record_id)

    def ignored_duplicate_pairs(self, user):
        del user
        return sorted(self.repository.ignored_duplicate_pairs())

    def ignore_duplicate_pair(self, user, left_record_id, right_record_id):
        del user
        self.repository.ignore_duplicate_pair(left_record_id, right_record_id)
        return True

    def verify_managed_attachments(self, user):
        del user
        return list(self.repository.verify_managed_attachments())
