"""Database abstraction used by the mobile API.

The desktop application can keep using its mature SQLite repository while the
API presents one stable interface.  The PostgreSQL implementation exposes the
same records after the normalized migration has been applied.
"""

from __future__ import annotations

import json
import hashlib
import mimetypes
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from customer_api.config import ApiSettings
from customer_api.types import AuthenticatedUser
from customer_database import CustomerDatabase
from customer_domain import (
    mask_identity_text,
    normalize_match_text,
    normalize_search_text,
    split_search_terms,
)
from customer_fields import LAND_FIELDS
from customer_postgres_keys import land_key_for, owner_key_for
from customer_repository import CustomerRepository
from customer_security import (
    ENCRYPTED_FIELDS,
    decrypt_value,
    derive_encryption_key,
    encrypt_record,
    make_fernet,
    verify_password,
)


RECORD_SEARCH_FIELDS = (
    "district",
    "section",
    "registration_order",
    "land_number",
    "owner_name",
    "external_id",
    "address",
    "registration_reason",
    "note",
    "visit_log",
)


class CustomerDataSource(Protocol):
    backend_name: str

    def health(self) -> dict: ...

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None: ...

    def list_records(
        self,
        user: AuthenticatedUser,
        *,
        query: str = "",
        filters: dict | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict: ...

    def get_record(self, user: AuthenticatedUser, record_id: int) -> dict | None: ...

    def save_record(
        self,
        user: AuthenticatedUser,
        values: dict,
        record_id: int | None = None,
    ) -> int: ...

    def delete_record(self, user: AuthenticatedUser, record_id: int) -> bool: ...

    def import_records(
        self,
        user: AuthenticatedUser,
        items: list[dict],
        source_file_name: str = "import.xlsx",
    ) -> dict: ...

    def list_contact_logs(self, user: AuthenticatedUser, record_id: int) -> list[dict]: ...

    def add_contact_log(self, user: AuthenticatedUser, record_id: int, values: dict) -> int: ...

    def delete_contact_log(
        self, user: AuthenticatedUser, record_id: int, log_id: int
    ) -> bool: ...

    def get_follow_up(
        self, user: AuthenticatedUser, record_id: int
    ) -> dict | None: ...

    def save_follow_up(self, user: AuthenticatedUser, record_id: int, values: dict) -> None: ...

    def delete_follow_up(self, user: AuthenticatedUser, record_id: int) -> bool: ...

    def list_follow_ups(self, user: AuthenticatedUser, limit: int = 500) -> list[dict]: ...

    def list_projects(self, user: AuthenticatedUser) -> list[dict]: ...

    def save_project(
        self,
        user: AuthenticatedUser,
        title: str,
        status: str = "進行中",
        note: str = "",
        project_id: int | None = None,
    ) -> int: ...

    def delete_project(self, user: AuthenticatedUser, project_id: int) -> bool: ...

    def add_records_to_project(
        self,
        user: AuthenticatedUser,
        project_id: int,
        record_ids: list[int],
    ) -> int: ...

    def remove_records_from_project(
        self,
        user: AuthenticatedUser,
        project_id: int,
        record_ids: list[int],
    ) -> int: ...

    def list_tags(self, user: AuthenticatedUser) -> list[dict]: ...

    def save_tag(
        self,
        user: AuthenticatedUser,
        name: str,
        color: str = "",
        tag_id: int | None = None,
    ) -> int: ...

    def delete_tag(self, user: AuthenticatedUser, tag_id: int) -> bool: ...

    def get_record_tag_ids(
        self, user: AuthenticatedUser, record_id: int
    ) -> set[int]: ...

    def set_record_tags(
        self, user: AuthenticatedUser, record_id: int, tag_ids: list[int]
    ) -> int: ...

    def set_records_tags(
        self,
        user: AuthenticatedUser,
        record_ids: list[int],
        tag_ids: list[int],
        mode: str = "add",
    ) -> int: ...

    def list_attachments(
        self, user: AuthenticatedUser, record_id: int
    ) -> list[dict]: ...

    def get_attachment(
        self, user: AuthenticatedUser, record_id: int, attachment_id: int
    ) -> dict | None: ...

    def add_external_attachment(
        self,
        user: AuthenticatedUser,
        record_id: int,
        file_path: str,
        description: str = "",
    ) -> int: ...

    def import_managed_attachment(
        self,
        user: AuthenticatedUser,
        record_id: int,
        source_path: str | Path,
        original_name: str,
        description: str = "",
        media_type: str = "",
    ) -> int: ...

    def delete_attachment(
        self, user: AuthenticatedUser, record_id: int, attachment_id: int
    ) -> bool: ...


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row):
    return {str(key): _json_value(value) for key, value in dict(row).items()}


def _decrypt_record(row, user):
    values = _row_dict(row)
    fernet = make_fernet(user.data_key)
    for field in ENCRYPTED_FIELDS:
        if field in values:
            values[field] = decrypt_value(fernet, values.get(field))
    if user.role == "viewer":
        values["external_id"] = mask_identity_text(values.get("external_id"))
    return values


def _filter_records(records, *, query="", filters=None):
    query = normalize_match_text(query)
    normalized_filters = {}
    for key, value in dict(filters or {}).items():
        terms = split_search_terms(value)
        if terms:
            normalized_filters[key] = terms
    matched = []
    for record in records:
        if query and not any(
            query in normalize_match_text(record.get(field)) for field in RECORD_SEARCH_FIELDS
        ):
            continue
        if any(
            not any(term in normalize_search_text(record.get(key)) for term in terms)
            for key, terms in normalized_filters.items()
        ):
            continue
        matched.append(record)
    return matched


def _encrypted_record(user, values):
    plain = {key: values.get(key) for key, _label in LAND_FIELDS}
    plain["name"] = plain.get("owner_name") or None
    return encrypt_record(make_fernet(user.data_key), plain)


class SQLiteCustomerDataSource:
    backend_name = "sqlite"

    def __init__(self, settings: ApiSettings):
        self.settings = settings
        self.database = CustomerDatabase(
            settings.sqlite_database_path,
            settings.backup_directory,
        )
        self.repository = CustomerRepository(
            self.database,
            settings.schema_path,
            settings.seed_path,
            LAND_FIELDS,
        )
        self.repository.init_db()

    def health(self):
        with self.database.connect() as conn:
            schema_version = self.repository.migrations.current_version(conn)
            record_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        return {
            "status": "ok",
            "backend": self.backend_name,
            "schema_version": int(schema_version),
            "record_count": int(record_count),
        }

    def authenticate(self, username, password):
        data_key = self.repository.authenticate_user(str(username), str(password))
        user = self.repository.last_authenticated_user
        if not data_key or not user:
            return None
        return AuthenticatedUser(
            id=int(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"]),
            role=str(user["role"]),
            data_key=bytes(data_key),
        )

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

    def list_contact_logs(self, user, record_id):
        del user
        return [
            _row_dict(row) for row in self.repository.list_contact_logs(int(record_id))
        ]

    def add_contact_log(self, user, record_id, values):
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


class PostgreSQLCustomerDataSource:
    backend_name = "postgresql"
    CONNECT_TIMEOUT_SECONDS = 5

    RECORD_SELECT = """
        SELECT ownership.id,
               land.district, land.section, ownership.registration_order,
               land.land_number, land.area, land.declared_value,
               ownership.numerator, ownership.denominator, ownership.ping,
               ownership.total_declared_value,
               owner.owner_name, owner.external_id, owner.address,
               ownership.registration_reason, ownership.note,
               ownership.visit_log, owner.owner_name AS name,
               ownership.created_at, ownership.updated_at,
               COALESCE((
                   SELECT STRING_AGG(project.title, '、' ORDER BY project.updated_at DESC, project.id DESC)
                   FROM project_ownerships membership
                   JOIN projects project ON project.id = membership.project_id
                   WHERE membership.ownership_id = ownership.id
               ), '') AS case_names,
               COALESCE((
                   SELECT STRING_AGG(tag.name, '、' ORDER BY tag.name, tag.id)
                   FROM ownership_tags link
                   JOIN tags tag ON tag.id = link.tag_id
                   WHERE link.ownership_id = ownership.id
               ), '') AS tag_names,
               COALESCE((
                   SELECT tag.color
                   FROM ownership_tags link
                   JOIN tags tag ON tag.id = link.tag_id
                   WHERE link.ownership_id = ownership.id
                     AND COALESCE(tag.color, '') <> ''
                   ORDER BY tag.name, tag.id
                   LIMIT 1
               ), '') AS primary_tag_color,
               (
                   SELECT COUNT(*)::integer
                   FROM attachments attachment
                   WHERE attachment.ownership_id = ownership.id
               ) AS attachment_count,
               COALESCE((
                   SELECT STRING_AGG(
                       CASE
                           WHEN COALESCE(attachment.description, '') <> ''
                           THEN attachment.description || '（' || COALESCE(attachment.file_path, attachment.original_name) || '）'
                           ELSE COALESCE(attachment.file_path, attachment.original_name)
                       END,
                       '；' ORDER BY attachment.created_at DESC, attachment.id DESC
                   )
                   FROM attachments attachment
                   WHERE attachment.ownership_id = ownership.id
               ), '') AS attachment_names,
               COALESCE((
                   SELECT STRING_AGG(
                       field.label || '：' || COALESCE(custom_value.value, ''),
                       '；' ORDER BY field.id
                   )
                   FROM ownership_custom_values custom_value
                   JOIN custom_fields field ON field.id = custom_value.field_id
                   WHERE custom_value.ownership_id = ownership.id
               ), '') AS custom_values,
               COALESCE((
                   SELECT CONCAT_WS('／', NULLIF(log.method, ''), NULLIF(log.result, ''))
                   FROM contact_logs log
                   WHERE log.ownership_id = ownership.id
                   ORDER BY COALESCE(log.contact_date, log.created_at::date) DESC, log.id DESC
                   LIMIT 1
               ), '') AS last_contact,
               COALESCE(reminder.due_date::text, '') AS next_follow_up,
               COALESCE(reminder.status, '') AS follow_up_status
        FROM ownerships ownership
        JOIN owners owner ON owner.id = ownership.owner_id
        JOIN lands land ON land.id = ownership.land_id
        LEFT JOIN follow_up_reminders reminder ON reminder.ownership_id = ownership.id
    """

    def __init__(self, settings: ApiSettings):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "尚未安裝 PostgreSQL 驅動，請安裝 requirements-server.txt"
            ) from exc
        self.settings = settings
        self.dsn = settings.postgres_dsn
        self._psycopg = psycopg
        self._dict_row = dict_row

    def _connect(self):
        return self._psycopg.connect(
            self.dsn,
            row_factory=self._dict_row,
            connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
        )

    def health(self):
        with self._connect() as conn:
            schema_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            count_row = conn.execute("SELECT COUNT(*) AS count FROM ownerships").fetchone()
        return {
            "status": "ok",
            "backend": self.backend_name,
            "schema_version": int(schema_row["version"]),
            "record_count": int(count_row["count"]),
        }

    def authenticate(self, username, password):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, role, active,
                       password_salt, password_hash, encryption_salt, wrapped_data_key
                FROM users WHERE username = %s
                """,
                (str(username),),
            ).fetchone()
            if (
                row is None
                or not row["active"]
                or not verify_password(password, row["password_salt"], row["password_hash"])
            ):
                return None
            wrapping_key = derive_encryption_key(password, row["encryption_salt"])
            if row["wrapped_data_key"]:
                try:
                    data_key = make_fernet(wrapping_key).decrypt(
                        row["wrapped_data_key"].encode("ascii")
                    )
                except Exception:
                    return None
            else:
                data_key = wrapping_key
            conn.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s",
                (row["id"],),
            )
        return AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or row["username"]),
            role=str(row["role"] or "viewer"),
            data_key=bytes(data_key),
        )

    def list_records(
        self,
        user,
        *,
        query="",
        filters=None,
        offset=0,
        limit=100,
    ):
        with self._connect() as conn:
            rows = conn.execute(self.RECORD_SELECT + " ORDER BY ownership.id DESC").fetchall()
        records = [_decrypt_record(row, user) for row in rows]
        matched = _filter_records(records, query=query, filters=filters)
        offset = max(0, int(offset))
        limit = max(1, int(limit))
        return {"total": len(matched), "items": matched[offset : offset + limit]}

    def get_record(self, user, record_id):
        with self._connect() as conn:
            row = conn.execute(
                self.RECORD_SELECT + " WHERE ownership.id = %s",
                (int(record_id),),
            ).fetchone()
        return None if row is None else _decrypt_record(row, user)

    def _save_owner_and_land(self, conn, user, values):
        encrypted = _encrypted_record(user, values)
        owner_row = conn.execute(
            """
            INSERT INTO owners (owner_key, owner_name, external_id, address)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_key) DO UPDATE SET
                owner_name = EXCLUDED.owner_name,
                external_id = EXCLUDED.external_id,
                address = EXCLUDED.address,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                owner_key_for(values, user.data_key),
                encrypted["owner_name"],
                encrypted.get("external_id"),
                encrypted.get("address"),
            ),
        ).fetchone()
        land_row = conn.execute(
            """
            INSERT INTO lands (
                land_key, district, section, land_number, area, declared_value
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (land_key) DO UPDATE SET
                district = EXCLUDED.district,
                section = EXCLUDED.section,
                land_number = EXCLUDED.land_number,
                area = EXCLUDED.area,
                declared_value = EXCLUDED.declared_value,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                land_key_for(values),
                values.get("district") or "",
                values.get("section") or "",
                values.get("land_number") or "",
                values.get("area"),
                values.get("declared_value"),
            ),
        ).fetchone()
        return int(owner_row["id"]), int(land_row["id"]), encrypted

    def _save_record_with_conn(
        self, conn, user, values, record_id=None, *, write_audit=True
    ):
        if record_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
        owner_id, land_id, encrypted = self._save_owner_and_land(
            conn, user, values
        )
        if record_id is None:
            row = conn.execute(
                """
                INSERT INTO ownerships (
                    owner_id, land_id, registration_order, numerator,
                    denominator, ping, total_declared_value,
                    registration_reason, note, visit_log, name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"),
                ),
            ).fetchone()
            saved_id = int(row["id"])
            action_type = "api_create_record"
            summary = f"Created ownership {saved_id}"
        else:
            saved_id = int(record_id)
            conn.execute(
                """
                UPDATE ownerships SET
                    owner_id = %s, land_id = %s, registration_order = %s,
                    numerator = %s, denominator = %s, ping = %s,
                    total_declared_value = %s, registration_reason = %s,
                    note = %s, visit_log = %s, name = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    owner_id, land_id, values.get("registration_order"),
                    values.get("numerator"), values.get("denominator"),
                    values.get("ping"), values.get("total_declared_value"),
                    values.get("registration_reason"), encrypted.get("note"),
                    encrypted.get("visit_log"), encrypted.get("name"), saved_id,
                ),
            )
            action_type = "api_update_record"
            summary = f"Updated ownership {saved_id}"
        if write_audit:
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'ownership', %s, %s)
                """,
                (user.id, user.username, action_type, saved_id, summary),
            )
        return saved_id

    def save_record(self, user, values, record_id=None):
        with self._connect() as conn:
            return self._save_record_with_conn(conn, user, values, record_id)

    def import_records(self, user, items, source_file_name="import.xlsx"):
        items = [dict(item) for item in items]
        safe_name = Path(str(source_file_name or "import.xlsx")).name or "import.xlsx"
        inserted_ids = []
        updated_ids = []
        with self._connect() as conn:
            update_ids = sorted(
                {
                    int(item["record_id"])
                    for item in items
                    if item.get("record_id") is not None
                }
            )
            self._require_ids(conn, "ownerships", update_ids)
            batch_row = conn.execute(
                """
                INSERT INTO import_batches (
                    source_file_name, total_rows, success_rows,
                    duplicate_rows, failed_rows, imported_by
                ) VALUES (%s, %s, 0, 0, 0, %s)
                RETURNING id
                """,
                (safe_name, len(items), user.id),
            ).fetchone()
            batch_id = int(batch_row["id"])
            for row_number, item in enumerate(items, start=1):
                record_id = item.get("record_id")
                values = dict(item["values"])
                saved_id = self._save_record_with_conn(
                    conn,
                    user,
                    values,
                    None if record_id is None else int(record_id),
                    write_audit=False,
                )
                if record_id is None:
                    inserted_ids.append(saved_id)
                else:
                    updated_ids.append(saved_id)
                protected_values = _encrypted_record(user, values)
                conn.execute(
                    """
                    INSERT INTO import_data (
                        batch_id, row_number, raw_values, processing_status
                    ) VALUES (%s, %s, %s::jsonb, 'success')
                    """,
                    (
                        batch_id,
                        row_number,
                        json.dumps(
                            {
                                "record_id": saved_id,
                                "mode": "insert" if record_id is None else "update",
                                "values": protected_values,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                )
            conn.execute(
                """
                UPDATE import_batches
                SET success_rows = %s
                WHERE id = %s
                """,
                (len(items), batch_id),
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id,
                    summary, detail
                ) VALUES (%s, %s, 'api_import_records', 'import_batch', %s, %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    batch_id,
                    f"Imported {len(inserted_ids)} and updated {len(updated_ids)} records",
                    json.dumps(
                        {
                            "source_file_name": safe_name,
                            "inserted_ids": inserted_ids,
                            "updated_ids": updated_ids,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        return {
            "batch_id": batch_id,
            "inserted_count": len(inserted_ids),
            "updated_count": len(updated_ids),
            "inserted_ids": inserted_ids,
            "updated_ids": updated_ids,
        }

    def delete_record(self, user, record_id):
        record_id = int(record_id)
        with self._connect() as conn:
            row = conn.execute(
                self.RECORD_SELECT + " WHERE ownership.id = %s",
                (record_id,),
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            snapshot = {
                "record": _row_dict(row),
                "contact_logs": [
                    _row_dict(item)
                    for item in conn.execute(
                        "SELECT * FROM contact_logs WHERE ownership_id = %s ORDER BY id",
                        (record_id,),
                    ).fetchall()
                ],
                "follow_up": _row_dict(
                    conn.execute(
                        "SELECT * FROM follow_up_reminders WHERE ownership_id = %s",
                        (record_id,),
                    ).fetchone()
                    or {}
                ),
            }
            label = " / ".join(
                str(row.get(key) or "")
                for key in ("district", "section", "land_number")
            ).strip(" / ") or f"ID {record_id}"
            conn.execute(
                """
                INSERT INTO recycle_bin (
                    entity_type, original_id, display_label, payload_json, deleted_by
                ) VALUES ('ownership', %s, %s, %s::jsonb, %s)
                """,
                (
                    record_id,
                    label,
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    user.username,
                ),
            )
            conn.execute("DELETE FROM ownerships WHERE id = %s", (record_id,))
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_delete_record', 'ownership', %s, %s)
                """,
                (user.id, user.username, record_id, f"Deleted ownership {record_id}"),
            )
        return True

    def list_contact_logs(self, user, record_id):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, contact_date, method,
                       result, next_follow_up, note, created_at
                FROM contact_logs WHERE ownership_id = %s
                ORDER BY COALESCE(contact_date, created_at::date) DESC, id DESC
                """,
                (int(record_id),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def add_contact_log(self, user, record_id, values):
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            row = conn.execute(
                """
                INSERT INTO contact_logs (
                    ownership_id, contact_date, method, result, next_follow_up,
                    note, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    int(record_id),
                    values.get("contact_date") or None,
                    values.get("method") or None,
                    values.get("result") or None,
                    values.get("next_follow_up") or None,
                    values.get("note") or None,
                    user.id,
                ),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_create_contact_log', 'contact_log', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    int(row["id"]),
                    f"Created contact log for ownership {int(record_id)}",
                ),
            )
        return int(row["id"])

    def delete_contact_log(self, user, record_id, log_id):
        record_id = int(record_id)
        log_id = int(log_id)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (record_id,)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            deleted = conn.execute(
                """
                DELETE FROM contact_logs
                WHERE id = %s AND ownership_id = %s
                RETURNING id
                """,
                (log_id, record_id),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_contact_log', 'contact_log', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        log_id,
                        f"Deleted contact log from ownership {record_id}",
                    ),
                )
        return bool(deleted)

    def get_follow_up(self, user, record_id):
        del user
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, due_date, status, note,
                       created_at, updated_at
                FROM follow_up_reminders
                WHERE ownership_id = %s
                """,
                (int(record_id),),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def save_follow_up(self, user, record_id, values):
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (int(record_id),)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            conn.execute(
                """
                INSERT INTO follow_up_reminders (ownership_id, due_date, status, note)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ownership_id) DO UPDATE SET
                    due_date = EXCLUDED.due_date,
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(record_id),
                    values.get("due_date") or None,
                    values.get("status") or "未處理",
                    values.get("note") or None,
                ),
            )
            reminder = conn.execute(
                "SELECT id FROM follow_up_reminders WHERE ownership_id = %s",
                (int(record_id),),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_save_follow_up', 'follow_up', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    int(reminder["id"]),
                    f"Saved follow-up for ownership {int(record_id)}",
                ),
            )

    def delete_follow_up(self, user, record_id):
        record_id = int(record_id)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM ownerships WHERE id = %s", (record_id,)
            ).fetchone()
            if not exists:
                raise KeyError(record_id)
            deleted = conn.execute(
                """
                DELETE FROM follow_up_reminders
                WHERE ownership_id = %s
                RETURNING id
                """,
                (record_id,),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_follow_up', 'follow_up', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        int(deleted["id"]),
                        f"Deleted follow-up from ownership {record_id}",
                    ),
                )
        return bool(deleted)

    def list_follow_ups(self, user, limit=500):
        sql = self.RECORD_SELECT + """
            WHERE reminder.id IS NOT NULL
            ORDER BY CASE WHEN reminder.status = '完成' THEN 1 ELSE 0 END,
                     reminder.due_date NULLS LAST, reminder.id DESC
            LIMIT %s
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (int(limit),)).fetchall()
            reminder_rows = conn.execute(
                """
                SELECT ownership_id, due_date, status, note
                FROM follow_up_reminders
                WHERE ownership_id = ANY(%s)
                """,
                ([int(row["id"]) for row in rows],),
            ).fetchall() if rows else []
        reminders = {
            int(row["ownership_id"]): _row_dict(row) for row in reminder_rows
        }
        items = []
        for row in rows:
            item = _decrypt_record(row, user)
            reminder = reminders.get(int(item["id"]), {})
            item["due_date"] = reminder.get("due_date") or ""
            item["status"] = reminder.get("status") or ""
            item["note"] = reminder.get("note") or ""
            items.append(item)
        return items

    def list_projects(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT project.id, project.title, project.status, project.note,
                       project.assigned_to_text AS assigned_to,
                       project.due_date, project.priority, project.next_action,
                       project.archived_at, project.created_at, project.updated_at,
                       COUNT(membership.ownership_id)::integer AS customer_count
                FROM projects project
                LEFT JOIN project_ownerships membership
                  ON membership.project_id = project.id
                GROUP BY project.id
                ORDER BY CASE WHEN project.archived_at IS NULL THEN 0 ELSE 1 END,
                         project.updated_at DESC, project.id DESC
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_project(self, user, title, status="進行中", note="", project_id=None):
        title = str(title or "").strip()
        status = str(status or "進行中").strip() or "進行中"
        note = str(note or "").strip() or None
        if not title:
            raise ValueError("案件名稱不可空白")
        with self._connect() as conn:
            if project_id is None:
                row = conn.execute(
                    """
                    INSERT INTO projects (title, status, note)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (title, status, note),
                ).fetchone()
                action_type = "api_create_project"
            else:
                row = conn.execute(
                    """
                    UPDATE projects
                    SET title = %s, status = %s, note = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id
                    """,
                    (title, status, note, int(project_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(project_id)
                action_type = "api_update_project"
            saved_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'project', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    action_type,
                    saved_id,
                    f"Saved project {title}",
                ),
            )
        return saved_id

    def delete_project(self, user, project_id):
        project_id = int(project_id)
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM projects WHERE id = %s RETURNING title",
                (project_id,),
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_project', 'project', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        project_id,
                        f"Deleted project {deleted['title']}",
                    ),
                )
        return bool(deleted)

    @staticmethod
    def _sync_project_dimension_links(conn, project_id):
        project_id = int(project_id)
        conn.execute(
            "DELETE FROM project_owners WHERE project_id = %s", (project_id,)
        )
        conn.execute(
            """
            INSERT INTO project_owners (project_id, owner_id)
            SELECT %s, ownership.owner_id
            FROM project_ownerships membership
            JOIN ownerships ownership ON ownership.id = membership.ownership_id
            WHERE membership.project_id = %s
            GROUP BY ownership.owner_id
            """,
            (project_id, project_id),
        )
        conn.execute(
            "DELETE FROM project_lands WHERE project_id = %s", (project_id,)
        )
        conn.execute(
            """
            INSERT INTO project_lands (project_id, land_id)
            SELECT %s, ownership.land_id
            FROM project_ownerships membership
            JOIN ownerships ownership ON ownership.id = membership.ownership_id
            WHERE membership.project_id = %s
            GROUP BY ownership.land_id
            """,
            (project_id, project_id),
        )

    def _update_project_records(self, user, project_id, record_ids, mode):
        project_id = int(project_id)
        record_ids = self._normalize_ids(record_ids)
        if not record_ids:
            return 0
        with self._connect() as conn:
            self._require_ids(conn, "projects", [project_id])
            self._require_ids(conn, "ownerships", record_ids)
            if mode == "add":
                changed = conn.execute(
                    """
                    INSERT INTO project_ownerships (project_id, ownership_id)
                    SELECT %s, record_id
                    FROM UNNEST(%s::bigint[]) AS input(record_id)
                    ON CONFLICT DO NOTHING
                    RETURNING ownership_id
                    """,
                    (project_id, record_ids),
                ).fetchall()
                action_type = "api_add_project_records"
            elif mode == "remove":
                changed = conn.execute(
                    """
                    DELETE FROM project_ownerships
                    WHERE project_id = %s AND ownership_id = ANY(%s)
                    RETURNING ownership_id
                    """,
                    (project_id, record_ids),
                ).fetchall()
                action_type = "api_remove_project_records"
            else:
                raise ValueError("不支援的案件資料操作")
            self._sync_project_dimension_links(conn, project_id)
            conn.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (project_id,),
            )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id,
                    summary, detail
                ) VALUES (%s, %s, %s, 'project', %s, %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    action_type,
                    project_id,
                    f"Updated {len(changed)} project records",
                    json.dumps({"record_ids": record_ids}, ensure_ascii=False),
                ),
            )
        return len(changed)

    def add_records_to_project(self, user, project_id, record_ids):
        return self._update_project_records(
            user, project_id, record_ids, "add"
        )

    def remove_records_from_project(self, user, project_id, record_ids):
        return self._update_project_records(
            user, project_id, record_ids, "remove"
        )

    def list_tags(self, user):
        del user
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag.id, tag.name, tag.color, tag.created_at,
                       COUNT(link.ownership_id)::integer AS customer_count
                FROM tags tag
                LEFT JOIN ownership_tags link ON link.tag_id = tag.id
                GROUP BY tag.id
                ORDER BY LOWER(tag.name), tag.id
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_tag(self, user, name, color="", tag_id=None):
        name = str(name or "").strip()
        color = str(color or "").strip()
        if not name:
            raise ValueError("標籤名稱不可空白")
        with self._connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM tags
                WHERE name = %s AND (%s::bigint IS NULL OR id <> %s::bigint)
                """,
                (name, tag_id, tag_id),
            ).fetchone()
            if duplicate:
                raise ValueError("已有相同名稱的標籤")
            if tag_id is None:
                row = conn.execute(
                    "INSERT INTO tags (name, color) VALUES (%s, %s) RETURNING id",
                    (name, color or None),
                ).fetchone()
                action_type = "api_create_tag"
            else:
                row = conn.execute(
                    """
                    UPDATE tags SET name = %s, color = %s
                    WHERE id = %s RETURNING id
                    """,
                    (name, color or None, int(tag_id)),
                ).fetchone()
                if row is None:
                    raise KeyError(tag_id)
                action_type = "api_update_tag"
            saved_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, %s, 'tag', %s, %s)
                """,
                (user.id, user.username, action_type, saved_id, f"Saved tag {name}"),
            )
        return saved_id

    def delete_tag(self, user, tag_id):
        tag_id = int(tag_id)
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM tags WHERE id = %s RETURNING name", (tag_id,)
            ).fetchone()
            if deleted:
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_tag', 'tag', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        tag_id,
                        f"Deleted tag {deleted['name']}",
                    ),
                )
        return bool(deleted)

    @staticmethod
    def _normalize_ids(values):
        return sorted({int(value) for value in values})

    @staticmethod
    def _require_ids(conn, table, ids):
        if not ids:
            return
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE id = ANY(%s)", (ids,)
        ).fetchall()
        if len(rows) != len(ids):
            raise KeyError(f"{table} contains missing ids")

    def get_record_tag_ids(self, user, record_id):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                "SELECT tag_id FROM ownership_tags WHERE ownership_id = %s",
                (record_id,),
            ).fetchall()
        return {int(row["tag_id"]) for row in rows}

    def set_record_tags(self, user, record_id, tag_ids):
        record_id = int(record_id)
        tag_ids = self._normalize_ids(tag_ids)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            self._require_ids(conn, "tags", tag_ids)
            conn.execute(
                "DELETE FROM ownership_tags WHERE ownership_id = %s", (record_id,)
            )
            if tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO ownership_tags (ownership_id, tag_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """,
                        [(record_id, tag_id) for tag_id in tag_ids],
                    )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_set_record_tags', 'ownership', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    record_id,
                    f"Set {len(tag_ids)} tags on ownership {record_id}",
                ),
            )
        return len(tag_ids)

    def set_records_tags(self, user, record_ids, tag_ids, mode="add"):
        record_ids = self._normalize_ids(record_ids)
        tag_ids = self._normalize_ids(tag_ids)
        mode = str(mode or "add")
        if mode not in {"add", "remove", "replace"}:
            raise ValueError("不支援的標籤批量模式")
        if not record_ids:
            return 0
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", record_ids)
            self._require_ids(conn, "tags", tag_ids)
            if mode == "replace":
                conn.execute(
                    "DELETE FROM ownership_tags WHERE ownership_id = ANY(%s)",
                    (record_ids,),
                )
            if mode in {"add", "replace"} and tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO ownership_tags (ownership_id, tag_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """,
                        [
                            (record_id, tag_id)
                            for record_id in record_ids
                            for tag_id in tag_ids
                        ],
                    )
            elif mode == "remove" and tag_ids:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        DELETE FROM ownership_tags
                        WHERE ownership_id = %s AND tag_id = %s
                        """,
                        [
                            (record_id, tag_id)
                            for record_id in record_ids
                            for tag_id in tag_ids
                        ],
                    )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, summary, detail
                ) VALUES (%s, %s, 'api_set_records_tags', 'ownership', %s, %s::jsonb)
                """,
                (
                    user.id,
                    user.username,
                    f"Updated tags on {len(record_ids)} ownerships",
                    json.dumps(
                        {"mode": mode, "record_ids": record_ids, "tag_ids": tag_ids}
                    ),
                ),
            )
        return len(record_ids)

    def list_attachments(self, user, record_id):
        del user
        record_id = int(record_id)
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            rows = conn.execute(
                """
                SELECT id, ownership_id AS customer_id, file_path, description,
                       storage_path, original_name, media_type, sha256, size_bytes,
                       status, version, created_at
                FROM attachments
                WHERE ownership_id = %s
                ORDER BY id DESC
                """,
                (record_id,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def get_attachment(self, user, record_id, attachment_id):
        rows = self.list_attachments(user, record_id)
        return next(
            (row for row in rows if int(row["id"]) == int(attachment_id)), None
        )

    @staticmethod
    def _record_attachment_links(conn, record_id):
        row = conn.execute(
            "SELECT owner_id, land_id FROM ownerships WHERE id = %s",
            (int(record_id),),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return int(row["owner_id"]), int(row["land_id"])

    def add_external_attachment(self, user, record_id, file_path, description=""):
        record_id = int(record_id)
        file_path = str(file_path or "").strip()
        if not file_path:
            raise ValueError("附件路徑不可空白")
        original_name = Path(file_path).name or "attachment"
        media_type = mimetypes.guess_type(original_name)[0]
        with self._connect() as conn:
            owner_id, land_id = self._record_attachment_links(conn, record_id)
            row = conn.execute(
                """
                INSERT INTO attachments (
                    ownership_id, owner_id, land_id, file_path, storage_path,
                    original_name, description, media_type, status, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'external', %s)
                RETURNING id
                """,
                (
                    record_id,
                    owner_id,
                    land_id,
                    file_path,
                    file_path,
                    original_name,
                    str(description or "").strip() or None,
                    media_type,
                    user.id,
                ),
            ).fetchone()
            attachment_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO audit_logs (
                    user_id, actor, action_type, entity_type, entity_id, summary
                ) VALUES (%s, %s, 'api_create_external_attachment', 'attachment', %s, %s)
                """,
                (
                    user.id,
                    user.username,
                    attachment_id,
                    f"Created external attachment for ownership {record_id}",
                ),
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
        record_id = int(record_id)
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"找不到附件檔案：{source}")
        safe_name = Path(str(original_name or source.name)).name or "attachment"
        suffix = Path(safe_name).suffix[:20]
        storage_root = self.settings.attachment_directory.resolve()
        customer_directory = storage_root / str(record_id)
        customer_directory.mkdir(parents=True, exist_ok=True)
        destination = customer_directory / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(source, destination)
        digest = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        try:
            with self._connect() as conn:
                owner_id, land_id = self._record_attachment_links(conn, record_id)
                row = conn.execute(
                    """
                    INSERT INTO attachments (
                        ownership_id, owner_id, land_id, file_path, storage_path,
                        original_name, description, media_type, size_bytes,
                        sha256, status, version, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              'managed', 1, %s)
                    RETURNING id
                    """,
                    (
                        record_id,
                        owner_id,
                        land_id,
                        str(destination),
                        str(destination),
                        safe_name,
                        str(description or "").strip() or None,
                        str(media_type or "").strip()
                        or mimetypes.guess_type(safe_name)[0],
                        destination.stat().st_size,
                        digest.hexdigest(),
                        user.id,
                    ),
                ).fetchone()
                attachment_id = int(row["id"])
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_upload_attachment', 'attachment', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        attachment_id,
                        f"Uploaded attachment for ownership {record_id}",
                    ),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return attachment_id

    def delete_attachment(self, user, record_id, attachment_id):
        record_id = int(record_id)
        attachment_id = int(attachment_id)
        storage_path = ""
        status = ""
        with self._connect() as conn:
            self._require_ids(conn, "ownerships", [record_id])
            deleted = conn.execute(
                """
                DELETE FROM attachments
                WHERE id = %s AND ownership_id = %s
                RETURNING storage_path, status
                """,
                (attachment_id, record_id),
            ).fetchone()
            if deleted:
                storage_path = str(deleted.get("storage_path") or "")
                status = str(deleted.get("status") or "")
                conn.execute(
                    """
                    INSERT INTO audit_logs (
                        user_id, actor, action_type, entity_type, entity_id, summary
                    ) VALUES (%s, %s, 'api_delete_attachment', 'attachment', %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        attachment_id,
                        f"Deleted attachment from ownership {record_id}",
                    ),
                )
        if deleted and storage_path and status != "external":
            root = self.settings.attachment_directory.resolve()
            candidate = Path(storage_path).resolve()
            if candidate.is_relative_to(root):
                candidate.unlink(missing_ok=True)
        return bool(deleted)


def create_data_source(settings: ApiSettings) -> CustomerDataSource:
    if settings.backend == "postgresql":
        return PostgreSQLCustomerDataSource(settings)
    return SQLiteCustomerDataSource(settings)
