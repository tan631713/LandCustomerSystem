"""SQLite project and record-assignment workflows."""

from customer_api.data_source_base import _row_dict


class SQLiteProjectMixin:
    def list_projects(self, user):
        del user
        return [_row_dict(row) for row in self.repository.list_cases()]

    def save_project(self, user, title, status="進行中", note="", project_id=None):
        if project_id is not None and not any(
            int(row["id"]) == int(project_id) for row in self.repository.list_cases()
        ):
            raise KeyError(project_id)
        self.repository.current_actor = user.username
        saved_id = int(
            self.repository.save_case(title, status, note, project_id)
        )
        self.repository.log_operation(
            "API儲存案件", f"案件 ID {saved_id}", str(title or "")
        )
        return saved_id

    def delete_project(self, user, project_id):
        self.repository.current_actor = user.username
        deleted = bool(self.repository.delete_case(int(project_id)))
        if deleted:
            self.repository.log_operation(
                "API刪除案件", f"案件 ID {int(project_id)}"
            )
        return deleted

    def _require_sqlite_project_records(self, project_id, record_ids):
        project_id = int(project_id)
        ids = sorted({int(record_id) for record_id in record_ids})
        if not any(
            int(row["id"]) == project_id for row in self.repository.list_cases()
        ):
            raise KeyError(project_id)
        if any(self.repository.get_customer(record_id) is None for record_id in ids):
            raise KeyError("records contain missing ids")
        return project_id, ids

    def add_records_to_project(self, user, project_id, record_ids):
        project_id, ids = self._require_sqlite_project_records(project_id, record_ids)
        self.repository.current_actor = user.username
        processed = int(self.repository.add_customers_to_case(project_id, ids))
        self.repository.log_operation(
            "API加入案件", f"案件 ID {project_id}", f"新增 {processed} 筆資料"
        )
        return processed

    def remove_records_from_project(self, user, project_id, record_ids):
        project_id, ids = self._require_sqlite_project_records(project_id, record_ids)
        self.repository.current_actor = user.username
        processed = int(self.repository.remove_customers_from_case(project_id, ids))
        self.repository.log_operation(
            "API移出案件", f"案件 ID {project_id}", f"移除 {processed} 筆資料"
        )
        return processed
