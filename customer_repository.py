"""Application-level persistence for customers and productivity features."""

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from customer_domain import normalize_match_text, normalize_search_text, split_search_terms
from customer_migrations import LATEST_SCHEMA_VERSION, MigrationRunner
from customer_security import (
    DECRYPTION_ERROR_TEXT,
    decrypt_value,
    derive_encryption_key,
    encrypt_record,
    hash_password,
    make_fernet,
    verify_password,
)


def normalize_watch_name(name):
    text = str(name or "").strip()
    return "".join(text.split()).casefold()


class CustomerRepository:
    DATABASE_SEARCH_FIELDS = {
        "rowid": "id",
        "district": "district",
        "section": "section",
        "registration_order": "registration_order",
        "land_number": "land_number",
        "area": "area",
        "declared_value": "declared_value",
        "numerator": "numerator",
        "denominator": "denominator",
        "ping": "ping",
        "total_declared_value": "total_declared_value",
        "registration_reason": "registration_reason",
    }
    CUSTOMER_PAGE_COLUMNS = """
        customers.id, customers.district, customers.section,
        customers.registration_order, customers.land_number, customers.area,
        customers.declared_value, customers.numerator, customers.denominator,
        customers.ping, customers.total_declared_value, customers.owner_name,
        customers.external_id, customers.address, customers.registration_reason,
        customers.note, customers.visit_log, customers.name,
        customers.created_at, customers.updated_at,
        COALESCE((
            SELECT GROUP_CONCAT(case_title, '、')
            FROM (
                SELECT ca.title AS case_title
                FROM case_customers cc
                JOIN cases ca ON ca.id = cc.case_id
                WHERE cc.customer_id = customers.id
                ORDER BY ca.updated_at DESC, ca.id DESC
            )
        ), '') AS case_names,
        COALESCE((
            SELECT GROUP_CONCAT(tag_name, '、')
            FROM (
                SELECT t.name AS tag_name
                FROM customer_tags ct
                JOIN tags t ON t.id = ct.tag_id
                WHERE ct.customer_id = customers.id
                ORDER BY t.name COLLATE NOCASE, t.id
            )
        ), '') AS tag_names,
        COALESCE((
            SELECT t.color
            FROM customer_tags ct
            JOIN tags t ON t.id = ct.tag_id
            WHERE ct.customer_id = customers.id
              AND COALESCE(t.color, '') <> ''
            ORDER BY t.name COLLATE NOCASE, t.id
            LIMIT 1
        ), '') AS primary_tag_color,
        (
            SELECT COUNT(*)
            FROM customer_attachments attachment
            WHERE attachment.customer_id = customers.id
        ) AS attachment_count,
        COALESCE((
            SELECT GROUP_CONCAT(attachment_text, '；')
            FROM (
                SELECT CASE
                    WHEN COALESCE(attachment.description, '') <> ''
                    THEN attachment.description || '（' || attachment.file_path || '）'
                    ELSE attachment.file_path
                END AS attachment_text
                FROM customer_attachments attachment
                WHERE attachment.customer_id = customers.id
                ORDER BY attachment.id DESC
            )
        ), '') AS attachment_names,
        COALESCE((
            SELECT GROUP_CONCAT(custom_text, '；')
            FROM (
                SELECT cf.label || '：' || ccv.value AS custom_text
                FROM customer_custom_values ccv
                JOIN custom_fields cf ON cf.id = ccv.field_id
                WHERE ccv.customer_id = customers.id
                  AND COALESCE(ccv.value, '') <> ''
                ORDER BY cf.id
            )
        ), '') AS custom_values,
        COALESCE((
            SELECT
                COALESCE(NULLIF(cl.contact_date, ''), '未填日期')
                || CASE WHEN COALESCE(cl.method, '') <> '' THEN ' ' || cl.method ELSE '' END
                || CASE WHEN COALESCE(cl.result, '') <> '' THEN '／' || cl.result ELSE '' END
            FROM contact_logs cl
            WHERE cl.customer_id = customers.id
            ORDER BY COALESCE(NULLIF(cl.contact_date, ''), cl.created_at) DESC, cl.id DESC
            LIMIT 1
        ), '') AS last_contact,
        COALESCE((
            SELECT NULLIF(r.due_date, '')
            FROM follow_up_reminders r
            WHERE r.customer_id = customers.id
        ), (
            SELECT NULLIF(cl.next_follow_up, '')
            FROM contact_logs cl
            WHERE cl.customer_id = customers.id
              AND COALESCE(cl.next_follow_up, '') <> ''
            ORDER BY cl.next_follow_up DESC, cl.id DESC
            LIMIT 1
        ), '') AS next_follow_up,
        COALESCE((
            SELECT r.status
            FROM follow_up_reminders r
            WHERE r.customer_id = customers.id
        ), '') AS follow_up_status
    """

    def __init__(
        self,
        database,
        schema_path,
        seed_path,
        land_fields,
        admin_username="admin",
    ):
        self.database = database
        self.schema_path = schema_path
        self.seed_path = seed_path
        self.land_fields = tuple(land_fields)
        self.customer_data_columns = tuple(key for key, _label in self.land_fields) + ("name",)
        self.admin_username = admin_username
        self.migrations = MigrationRunner(self.land_fields)
        self.data_revision = 0
        self.current_actor = None
        self.last_authenticated_user = None
        self.last_inserted_customer_ids = []

    def touch_customer_data(self):
        self.data_revision += 1

    def fetch_duplicate_candidates(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, district, section, registration_order, land_number,
                       owner_name, external_id
                FROM customers
                """
            ).fetchall()

    def get_customer(self, record_id):
        with self.database.connect() as conn:
            return conn.execute(
                f"SELECT {self.CUSTOMER_PAGE_COLUMNS} FROM customers WHERE customers.id = ?",
                (record_id,),
            ).fetchone()

    def fetch_customers_by_ids(self, record_ids):
        ids = sorted({int(record_id) for record_id in record_ids})
        if not ids:
            return []
        rows = []
        columns = ", ".join(self.customer_data_columns)
        with self.database.connect() as conn:
            for start in range(0, len(ids), 900):
                chunk = ids[start : start + 900]
                placeholders = ", ".join("?" for _ in chunk)
                rows.extend(
                    conn.execute(
                        f"SELECT id, {columns} FROM customers "
                        f"WHERE id IN ({placeholders}) ORDER BY id",
                        chunk,
                    ).fetchall()
                )
        return rows

    def insert_customers(self, records):
        records = list(records)
        if not records:
            self.last_inserted_customer_ids = []
            return 0
        columns = ", ".join(self.customer_data_columns)
        placeholders = ", ".join(f":{key}" for key in self.customer_data_columns)
        inserted_ids = []
        with self.database.connect() as conn:
            for record in records:
                cursor = conn.execute(
                    f"INSERT INTO customers ({columns}) VALUES ({placeholders})",
                    record,
                )
                inserted_ids.append(int(cursor.lastrowid))
        self.last_inserted_customer_ids = inserted_ids
        self.touch_customer_data()
        return len(records)

    def save_customer(self, data, record_id=None):
        values = {key: data.get(key) for key in self.customer_data_columns}
        if record_id is None:
            columns = ", ".join(self.customer_data_columns)
            placeholders = ", ".join(f":{key}" for key in self.customer_data_columns)
            with self.database.connect() as conn:
                cursor = conn.execute(
                    f"INSERT INTO customers ({columns}) VALUES ({placeholders})",
                    values,
                )
                saved_id = cursor.lastrowid
            self.touch_customer_data()
            return saved_id

        assignments = ", ".join(f"{key} = :{key}" for key in self.customer_data_columns)
        with self.database.connect() as conn:
            conn.execute(
                f"UPDATE customers SET {assignments} WHERE id = :id",
                {**values, "id": int(record_id)},
            )
        self.touch_customer_data()
        return int(record_id)

    def update_customers(self, records):
        records = list(records)
        if not records:
            return 0
        assignments = ", ".join(f"{key} = :{key}" for key in self.customer_data_columns)
        values = [
            {**{key: record.get(key) for key in self.customer_data_columns}, "id": record["id"]}
            for record in records
        ]
        with self.database.connect() as conn:
            conn.executemany(
                f"UPDATE customers SET {assignments} WHERE id = :id",
                values,
            )
        self.touch_customer_data()
        return len(values)

    def delete_customers(self, record_ids):
        ids = sorted({int(record_id) for record_id in record_ids})
        if not ids:
            return 0
        deleted_count = 0
        with self.database.connect() as conn:
            for record_id in ids:
                payload = self._customer_snapshot(conn, record_id)
                if not payload:
                    continue
                customer = payload["customer"]
                label = " / ".join(
                    str(customer.get(key) or "")
                    for key in ("district", "section", "land_number")
                ).strip(" / ") or f"ID {record_id}"
                conn.execute(
                    """
                    INSERT INTO recycle_bin (
                        entity_type, original_id, display_label, payload_json, deleted_by
                    ) VALUES ('customer', ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        label,
                        json.dumps(payload, ensure_ascii=False),
                        self.current_actor,
                    ),
                )
                conn.execute("DELETE FROM customers WHERE id = ?", (record_id,))
                deleted_count += 1
        self.touch_customer_data()
        return deleted_count

    def delete_all_customers(self):
        with self.database.connect() as conn:
            ids = [row[0] for row in conn.execute("SELECT id FROM customers ORDER BY id")]
        return self.delete_customers(ids)

    @staticmethod
    def _rows_as_dicts(rows):
        return [dict(row) for row in rows]

    def _customer_snapshot(self, conn, customer_id):
        customer = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (int(customer_id),)
        ).fetchone()
        if customer is None:
            return None
        related_queries = {
            "case_customers": "SELECT * FROM case_customers WHERE customer_id = ?",
            "customer_tags": "SELECT * FROM customer_tags WHERE customer_id = ?",
            "customer_attachments": "SELECT * FROM customer_attachments WHERE customer_id = ?",
            "customer_custom_values": "SELECT * FROM customer_custom_values WHERE customer_id = ?",
            "contact_logs": "SELECT * FROM contact_logs WHERE customer_id = ?",
            "follow_up_reminders": "SELECT * FROM follow_up_reminders WHERE customer_id = ?",
            "record_change_logs": "SELECT * FROM record_change_logs WHERE customer_id = ?",
            "customer_locations": "SELECT * FROM customer_locations WHERE customer_id = ?",
        }
        related = {}
        for table_name, query in related_queries.items():
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            related[table_name] = (
                self._rows_as_dicts(conn.execute(query, (int(customer_id),)).fetchall())
                if exists
                else []
            )
        return {"customer": dict(customer), "related": related}

    @staticmethod
    def _insert_dict(conn, table_name, values, *, replace=False, ignore=False):
        available = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
        filtered = {key: value for key, value in dict(values).items() if key in available}
        if not filtered:
            return
        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE" if ignore else "INSERT"
        columns = ", ".join(filtered)
        placeholders = ", ".join("?" for _ in filtered)
        conn.execute(
            f"{verb} INTO {table_name} ({columns}) VALUES ({placeholders})",
            tuple(filtered.values()),
        )

    def _restore_customer_snapshot(self, conn, snapshot):
        customer = dict(snapshot.get("customer") or {})
        if not customer:
            return None
        original_id = int(customer["id"])
        existing = conn.execute("SELECT 1 FROM customers WHERE id = ?", (original_id,)).fetchone()
        if existing:
            customer.pop("id", None)
        self._insert_dict(conn, "customers", customer)
        restored_id = original_id if not existing else int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        related = dict(snapshot.get("related") or {})
        for table_name, rows in related.items():
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            ).fetchone()
            if not exists:
                continue
            for row in rows:
                values = dict(row)
                if "customer_id" in values:
                    values["customer_id"] = restored_id
                self._insert_dict(
                    conn,
                    table_name,
                    values,
                    replace=table_name in {"customer_locations", "follow_up_reminders"},
                    ignore=table_name in {
                        "case_customers",
                        "customer_tags",
                        "customer_custom_values",
                    },
                )
        return restored_id

    def list_recycle_bin(self, limit=1000):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, entity_type, original_id, display_label, deleted_by, deleted_at
                FROM recycle_bin ORDER BY id DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

    def restore_recycle_items(self, recycle_ids):
        restored_ids = []
        with self.database.connect() as conn:
            for recycle_id in sorted({int(value) for value in recycle_ids}):
                row = conn.execute(
                    "SELECT payload_json FROM recycle_bin WHERE id = ?", (recycle_id,)
                ).fetchone()
                if row is None:
                    continue
                restored_id = self._restore_customer_snapshot(
                    conn, json.loads(row["payload_json"])
                )
                if restored_id is not None:
                    restored_ids.append(restored_id)
                    conn.execute("DELETE FROM recycle_bin WHERE id = ?", (recycle_id,))
        if restored_ids:
            self.touch_customer_data()
        return restored_ids

    def purge_recycle_items(self, recycle_ids=None, storage_root=None):
        managed_paths = []
        with self.database.connect() as conn:
            if recycle_ids is None:
                rows = conn.execute("SELECT payload_json FROM recycle_bin").fetchall()
                cursor = conn.execute("DELETE FROM recycle_bin")
            else:
                ids = sorted({int(value) for value in recycle_ids})
                rows = []
                for value in ids:
                    row = conn.execute(
                        "SELECT payload_json FROM recycle_bin WHERE id = ?", (value,)
                    ).fetchone()
                    if row:
                        rows.append(row)
                cursor = conn.executemany(
                    "DELETE FROM recycle_bin WHERE id = ?", [(value,) for value in ids]
                )
            for row in rows:
                payload = json.loads(row["payload_json"])
                for attachment in payload.get("related", {}).get(
                    "customer_attachments", []
                ):
                    if attachment.get("storage_path"):
                        managed_paths.append(attachment["storage_path"])
        if storage_root is not None:
            root = Path(storage_root).resolve()
            for value in managed_paths:
                candidate = Path(value).resolve()
                if candidate.is_relative_to(root):
                    candidate.unlink(missing_ok=True)
        return max(0, cursor.rowcount)

    def record_customer_undo(self, operation_type, customer_ids, summary):
        snapshots = self.capture_customer_snapshots(customer_ids)
        with self.database.connect() as conn:
            if not snapshots:
                return None
            cursor = conn.execute(
                """
                INSERT INTO undo_operations (
                    operation_type, summary, payload_json, actor_username
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(operation_type),
                    str(summary),
                    json.dumps({"mode": "restore", "snapshots": snapshots}, ensure_ascii=False),
                    self.current_actor,
                ),
            )
            return int(cursor.lastrowid)

    def capture_customer_snapshots(self, customer_ids):
        snapshots = []
        with self.database.connect() as conn:
            for customer_id in sorted({int(value) for value in customer_ids}):
                snapshot = self._customer_snapshot(conn, customer_id)
                if snapshot:
                    snapshots.append(snapshot)
        return snapshots

    def record_composite_undo(
        self, operation_type, snapshots, inserted_customer_ids, summary
    ):
        snapshots = list(snapshots or [])
        inserted_ids = sorted({int(value) for value in inserted_customer_ids})
        if not snapshots and not inserted_ids:
            return None
        payload = {
            "mode": "composite",
            "snapshots": snapshots,
            "inserted_customer_ids": inserted_ids,
        }
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO undo_operations (
                    operation_type, summary, payload_json, actor_username
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(operation_type), str(summary),
                    json.dumps(payload, ensure_ascii=False), self.current_actor,
                ),
            )
        return int(cursor.lastrowid)

    def record_insert_undo(self, operation_type, customer_ids, summary):
        ids = sorted({int(value) for value in customer_ids})
        if not ids:
            return None
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO undo_operations (
                    operation_type, summary, payload_json, actor_username
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(operation_type),
                    str(summary),
                    json.dumps({"mode": "delete_inserted", "customer_ids": ids}),
                    self.current_actor,
                ),
            )
            return int(cursor.lastrowid)

    def list_undo_operations(self, limit=100):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, operation_type, summary, actor_username, status,
                       created_at, undone_at
                FROM undo_operations ORDER BY id DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

    def undo_operation(self, operation_id=None):
        with self.database.connect() as conn:
            if operation_id is None:
                row = conn.execute(
                    """
                    SELECT * FROM undo_operations
                    WHERE status = 'available' ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM undo_operations WHERE id = ? AND status = 'available'",
                    (int(operation_id),),
                ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            mode = payload.get("mode")
            if mode == "restore":
                for snapshot in payload.get("snapshots", []):
                    customer_id = int(snapshot["customer"]["id"])
                    conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
                    self._restore_customer_snapshot(conn, snapshot)
            elif mode == "delete_inserted":
                conn.executemany(
                    "DELETE FROM customers WHERE id = ?",
                    [(int(value),) for value in payload.get("customer_ids", [])],
                )
            elif mode == "composite":
                conn.executemany(
                    "DELETE FROM customers WHERE id = ?",
                    [
                        (int(value),)
                        for value in payload.get("inserted_customer_ids", [])
                    ],
                )
                for snapshot in payload.get("snapshots", []):
                    customer_id = int(snapshot["customer"]["id"])
                    conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
                    self._restore_customer_snapshot(conn, snapshot)
            else:
                raise ValueError("不支援的復原資料格式")
            conn.execute(
                """
                UPDATE undo_operations
                SET status = 'undone', undone_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
        self.touch_customer_data()
        return dict(row)

    def encrypt_existing_customers(self, fernet):
        encrypted_fields = ("owner_name", "external_id", "address", "note", "visit_log", "name")
        updated = 0
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT id, {', '.join(encrypted_fields)} FROM customers"
            ).fetchall()
            for row in rows:
                data = {key: row[key] for key in encrypted_fields}
                encrypted = encrypt_record(fernet, data)
                if encrypted == data:
                    continue
                conn.execute(
                    """
                    UPDATE customers
                    SET owner_name = :owner_name,
                        external_id = :external_id,
                        address = :address,
                        note = :note,
                        visit_log = :visit_log,
                        name = :name
                    WHERE id = :id
                    """,
                    {**encrypted, "id": row["id"]},
                )
                updated += 1
        if updated:
            self.touch_customer_data()
        return updated

    def count_customers(self):
        with self.database.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]

    def fetch_customer_page(self, limit, *, before_id=None):
        limit = max(1, int(limit))
        with self.database.connect() as conn:
            if before_id is not None:
                return conn.execute(
                    f"""
                    SELECT {self.CUSTOMER_PAGE_COLUMNS}
                    FROM customers
                    WHERE id < ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(before_id), limit),
                ).fetchall()
            return conn.execute(
                f"""
                SELECT {self.CUSTOMER_PAGE_COLUMNS}
                FROM customers
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def fetch_all_customer_rows(self):
        with self.database.connect() as conn:
            return conn.execute(
                f"""
                SELECT {self.CUSTOMER_PAGE_COLUMNS}
                FROM customers
                ORDER BY id DESC
                """
            ).fetchall()

    @staticmethod
    def _escape_like(value):
        return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def fetch_search_candidate_rows(self, *, keyword="", filter_field="all", advanced_criteria=None):
        where_clauses = []
        parameters = []
        keyword = str(keyword or "").casefold()
        database_column = self.DATABASE_SEARCH_FIELDS.get(filter_field)
        if keyword and database_column:
            where_clauses.append(f"casefold_text(COALESCE({database_column}, '')) LIKE ? ESCAPE '\\'")
            parameters.append(f"%{self._escape_like(keyword)}%")

        for key, expected in dict(advanced_criteria or {}).items():
            expected_terms = split_search_terms(expected)
            database_column = self.DATABASE_SEARCH_FIELDS.get(key)
            if not expected_terms or not database_column:
                continue
            where_clauses.append(
                "("
                + " OR ".join(
                    f"normalize_match(COALESCE({database_column}, '')) LIKE ? ESCAPE '\\'"
                    for _term in expected_terms
                )
                + ")"
            )
            parameters.extend(
                f"%{self._escape_like(term)}%" for term in expected_terms
            )

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        with self.database.connect() as conn:
            conn.create_function(
                "casefold_text",
                1,
                lambda value: str(value or "").casefold(),
                deterministic=True,
            )
            conn.create_function(
                "normalize_match",
                1,
                normalize_search_text,
                deterministic=True,
            )
            return conn.execute(
                f"""
                SELECT {self.CUSTOMER_PAGE_COLUMNS}
                FROM customers
                {where_sql}
                ORDER BY id DESC
                """,
                parameters,
            ).fetchall()

    @staticmethod
    def get_columns(conn, table_name):
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}

    @staticmethod
    def init_settings_db(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def get_setting(self, setting_key, default=None):
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (setting_key,),
            ).fetchone()
        return default if row is None else row["setting_value"]

    def set_setting(self, setting_key, setting_value):
        self.set_settings({setting_key: setting_value})

    def set_settings(self, settings):
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [(key, str(value)) for key, value in settings.items()],
            )

    def fetch_customer_ids(self):
        with self.database.connect() as conn:
            return {row[0] for row in conn.execute("SELECT id FROM customers")}

    @staticmethod
    def init_watchlist_db(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def init_operation_log_db(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def log_operation(self, action_type, summary, detail=None):
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO operation_logs (
                    action_type, summary, detail, actor_username
                ) VALUES (?, ?, ?, ?)
                """,
                (action_type, summary, detail, self.current_actor),
            )
        return int(cursor.lastrowid)

    def get_operation_logs(self, limit=300):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, action_type, summary, detail, actor_username, created_at
                FROM operation_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def add_record_change_logs(self, logs):
        entries = []
        for log in logs:
            try:
                customer_id = int(log.get("customer_id"))
            except (TypeError, ValueError):
                continue
            field_key = str(log.get("field_key") or "").strip()
            field_label = str(log.get("field_label") or field_key).strip()
            if not customer_id or not field_key:
                continue
            entries.append(
                (
                    customer_id,
                    str(log.get("action_type") or "修改資料"),
                    field_key,
                    field_label,
                    log.get("old_value"),
                    log.get("new_value"),
                )
            )
        if not entries:
            return 0
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO record_change_logs (
                    customer_id, action_type, field_key, field_label, old_value, new_value
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                entries,
            )
            current_keys = [entry[0] for entry in entries]
            if current_keys:
                placeholders = ", ".join("?" for _ in current_keys)
                conn.execute(
                    f"""
                    UPDATE notifications SET dismissed_at = CURRENT_TIMESTAMP
                    WHERE category IN ('追蹤', '案件', '任務')
                      AND notification_key NOT IN ({placeholders})
                      AND dismissed_at IS NULL
                    """,
                    current_keys,
                )
            else:
                conn.execute(
                    """
                    UPDATE notifications SET dismissed_at = CURRENT_TIMESTAMP
                    WHERE category IN ('追蹤', '案件', '任務')
                      AND dismissed_at IS NULL
                    """
                )
        return len(entries)

    def get_record_change_logs(self, customer_id, limit=300):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, customer_id, action_type, field_key, field_label,
                       old_value, new_value, created_at
                FROM record_change_logs
                WHERE customer_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(customer_id), int(limit)),
            ).fetchall()

    def save_follow_up_reminder(self, customer_id, due_date=None, status="未處理", note=None):
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO follow_up_reminders (customer_id, due_date, status, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    due_date = excluded.due_date,
                    status = excluded.status,
                    note = excluded.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(customer_id),
                    str(due_date or "").strip() or None,
                    str(status or "未處理").strip() or "未處理",
                    note,
                ),
            )
        self.touch_customer_data()

    def delete_follow_up_reminder(self, customer_id):
        with self.database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM follow_up_reminders WHERE customer_id = ?",
                (int(customer_id),),
            )
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def get_follow_up_reminder(self, customer_id):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, customer_id, due_date, status, note, created_at, updated_at
                FROM follow_up_reminders
                WHERE customer_id = ?
                """,
                (int(customer_id),),
            ).fetchone()

    def list_follow_up_reminders(self, limit=500):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT r.id AS reminder_id, r.customer_id, r.due_date, r.status, r.note,
                       r.created_at, r.updated_at,
                       c.district, c.section, c.registration_order, c.land_number,
                       c.area, c.declared_value, c.numerator, c.denominator, c.ping,
                       c.total_declared_value, c.owner_name, c.external_id, c.address,
                       c.registration_reason, c.note AS customer_note, c.visit_log
                FROM follow_up_reminders r
                JOIN customers c ON c.id = r.customer_id
                ORDER BY
                    CASE WHEN r.status = '完成' THEN 1 ELSE 0 END ASC,
                    CASE WHEN r.due_date IS NULL OR r.due_date = '' THEN 1 ELSE 0 END ASC,
                    r.due_date ASC,
                    r.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

    def list_cases(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, title, status, note, assigned_to, due_date,
                       priority, next_action, archived_at, created_at, updated_at,
                       (
                           SELECT COUNT(*)
                           FROM case_customers cc
                           WHERE cc.case_id = cases.id
                       ) AS customer_count
                FROM cases
                ORDER BY CASE WHEN archived_at IS NULL THEN 0 ELSE 1 END,
                         updated_at DESC, id DESC
                """
            ).fetchall()

    def save_case(
        self,
        title,
        status="進行中",
        note=None,
        case_id=None,
        *,
        assigned_to=None,
        due_date=None,
        priority="一般",
        next_action=None,
        archived=False,
    ):
        title = str(title or "").strip()
        if not title:
            raise ValueError("案件名稱不可空白")
        status = str(status or "進行中").strip() or "進行中"
        note = str(note or "").strip() or None
        assigned_to = str(assigned_to or "").strip() or None
        due_date = str(due_date or "").strip() or None
        priority = str(priority or "一般").strip() or "一般"
        next_action = str(next_action or "").strip() or None
        archived_at_sql = "CURRENT_TIMESTAMP" if archived else "NULL"
        with self.database.connect() as conn:
            if case_id is None:
                cursor = conn.execute(
                    f"""
                    INSERT INTO cases (
                        title, status, note, assigned_to, due_date, priority,
                        next_action, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, {archived_at_sql})
                    """,
                    (title, status, note, assigned_to, due_date, priority, next_action),
                )
                saved_id = cursor.lastrowid
            else:
                saved_id = int(case_id)
                conn.execute(
                    """
                    UPDATE cases
                    SET title = ?, status = ?, note = ?, assigned_to = ?,
                        due_date = ?, priority = ?, next_action = ?,
                        archived_at = {archived_at_sql},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """.format(archived_at_sql=archived_at_sql),
                    (
                        title, status, note, assigned_to, due_date, priority,
                        next_action, saved_id,
                    ),
                )
        self.touch_customer_data()
        return saved_id

    def archive_case(self, case_id, archived=True):
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE cases
                SET archived_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if archived else 0, int(case_id)),
            )
        return cursor.rowcount

    def list_case_tasks(self, case_id=None, include_completed=True):
        where = []
        parameters = []
        if case_id is not None:
            where.append("task.case_id = ?")
            parameters.append(int(case_id))
        if not include_completed:
            where.append("task.status <> '完成'")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with self.database.connect() as conn:
            return conn.execute(
                f"""
                SELECT task.*, cases.title AS case_title
                FROM case_tasks task
                JOIN cases ON cases.id = task.case_id
                {where_sql}
                ORDER BY CASE WHEN task.status = '完成' THEN 1 ELSE 0 END,
                         CASE task.priority WHEN '緊急' THEN 0 WHEN '高' THEN 1 ELSE 2 END,
                         COALESCE(task.due_date, '9999-12-31'), task.id DESC
                """,
                parameters,
            ).fetchall()

    def save_case_task(
        self,
        case_id,
        title,
        *,
        assignee=None,
        due_date=None,
        status="待處理",
        priority="一般",
        checklist=None,
        task_id=None,
    ):
        title = str(title or "").strip()
        if not title:
            raise ValueError("任務名稱不可空白")
        values = (
            int(case_id), title, str(assignee or "").strip() or None,
            str(due_date or "").strip() or None, str(status or "待處理"),
            str(priority or "一般"), str(checklist or "").strip() or None,
        )
        with self.database.connect() as conn:
            if task_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO case_tasks (
                        case_id, title, assignee, due_date, status, priority, checklist
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE case_tasks
                SET case_id=?, title=?, assignee=?, due_date=?, status=?,
                    priority=?, checklist=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (*values, int(task_id)),
            )
            return int(task_id)

    def delete_case_task(self, task_id):
        with self.database.connect() as conn:
            return conn.execute(
                "DELETE FROM case_tasks WHERE id = ?", (int(task_id),)
            ).rowcount

    def delete_case(self, case_id):
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM cases WHERE id = ?", (int(case_id),))
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def add_customers_to_case(self, case_id, customer_ids):
        ids = sorted({int(record_id) for record_id in customer_ids})
        if not ids:
            return 0
        with self.database.connect() as conn:
            cursor = conn.executemany(
                "INSERT OR IGNORE INTO case_customers (case_id, customer_id) VALUES (?, ?)",
                [(int(case_id), record_id) for record_id in ids],
            )
        self.touch_customer_data()
        return cursor.rowcount

    def remove_customers_from_case(self, case_id, customer_ids):
        ids = sorted({int(record_id) for record_id in customer_ids})
        if not ids:
            return 0
        with self.database.connect() as conn:
            cursor = conn.executemany(
                "DELETE FROM case_customers WHERE case_id = ? AND customer_id = ?",
                [(int(case_id), record_id) for record_id in ids],
            )
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def list_case_members(self, case_id):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT c.*
                FROM case_customers cc
                JOIN customers c ON c.id = cc.customer_id
                WHERE cc.case_id = ?
                ORDER BY c.id DESC
                """,
                (int(case_id),),
            ).fetchall()

    def list_tags(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT t.id, t.name, t.color, t.created_at,
                       COUNT(ct.customer_id) AS customer_count
                FROM tags t
                LEFT JOIN customer_tags ct ON ct.tag_id = t.id
                GROUP BY t.id
                ORDER BY t.name COLLATE NOCASE, t.id
                """
            ).fetchall()

    def save_tag(self, name, color="", tag_id=None):
        name = str(name or "").strip()
        if not name:
            raise ValueError("標籤名稱不可空白")
        color = str(color or "").strip()
        with self.database.connect() as conn:
            if tag_id is None:
                cursor = conn.execute(
                    "INSERT INTO tags (name, color) VALUES (?, ?)",
                    (name, color),
                )
                saved_id = cursor.lastrowid
            else:
                saved_id = int(tag_id)
                conn.execute(
                    "UPDATE tags SET name = ?, color = ? WHERE id = ?",
                    (name, color, saved_id),
                )
        self.touch_customer_data()
        return saved_id

    def delete_tag(self, tag_id):
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM tags WHERE id = ?", (int(tag_id),))
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def get_customer_tag_ids(self, customer_id):
        with self.database.connect() as conn:
            return {
                row["tag_id"]
                for row in conn.execute(
                    "SELECT tag_id FROM customer_tags WHERE customer_id = ?",
                    (int(customer_id),),
                )
            }

    def set_customer_tags(self, customer_id, tag_ids):
        ids = sorted({int(tag_id) for tag_id in tag_ids})
        with self.database.connect() as conn:
            conn.execute("DELETE FROM customer_tags WHERE customer_id = ?", (int(customer_id),))
            conn.executemany(
                "INSERT OR IGNORE INTO customer_tags (customer_id, tag_id) VALUES (?, ?)",
                [(int(customer_id), tag_id) for tag_id in ids],
            )
        self.touch_customer_data()
        return len(ids)

    def set_customers_tags(self, customer_ids, tag_ids, mode="add"):
        customer_ids = sorted({int(customer_id) for customer_id in customer_ids})
        tag_ids = sorted({int(tag_id) for tag_id in tag_ids})
        if not customer_ids:
            return 0
        mode = str(mode or "add")
        if mode not in {"add", "remove", "replace"}:
            raise ValueError("不支援的標籤批量模式")
        with self.database.connect() as conn:
            if mode == "replace":
                conn.executemany(
                    "DELETE FROM customer_tags WHERE customer_id = ?",
                    [(customer_id,) for customer_id in customer_ids],
                )
            if mode in {"add", "replace"} and tag_ids:
                conn.executemany(
                    "INSERT OR IGNORE INTO customer_tags (customer_id, tag_id) VALUES (?, ?)",
                    [
                        (customer_id, tag_id)
                        for customer_id in customer_ids
                        for tag_id in tag_ids
                    ],
                )
            elif mode == "remove" and tag_ids:
                conn.executemany(
                    "DELETE FROM customer_tags WHERE customer_id = ? AND tag_id = ?",
                    [
                        (customer_id, tag_id)
                        for customer_id in customer_ids
                        for tag_id in tag_ids
                    ],
                )
        self.touch_customer_data()
        return len(customer_ids)

    def list_customer_attachments(self, customer_id):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, customer_id, file_path, description, category, storage_path,
                       original_name, sha256, size_bytes, status, version, created_by,
                       created_at
                FROM customer_attachments
                WHERE customer_id = ?
                ORDER BY id DESC
                """,
                (int(customer_id),),
            ).fetchall()

    def add_customer_attachment(
        self,
        customer_id,
        file_path,
        description="",
        category="",
        created_by=None,
    ):
        file_path = str(file_path or "").strip()
        if not file_path:
            raise ValueError("附件路徑不可空白")
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO customer_attachments (
                    customer_id, file_path, description, category, created_by
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(customer_id),
                    file_path,
                    str(description or "").strip() or None,
                    str(category or "").strip() or None,
                    int(created_by) if created_by is not None else None,
                ),
            )
        self.touch_customer_data()
        return cursor.lastrowid

    def import_managed_attachment(
        self,
        customer_id,
        source_path,
        storage_root,
        description="",
        category="",
        created_by=None,
    ):
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"找不到附件檔案：{source}")
        customer_directory = Path(storage_root) / str(int(customer_id))
        customer_directory.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix[:20]
        destination = customer_directory / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(source, destination)
        digest = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        try:
            with self.database.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO customer_attachments (
                        customer_id, file_path, description, category, storage_path,
                        original_name, sha256, size_bytes, status, version, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'managed', 1, ?)
                    """,
                    (
                        int(customer_id),
                        str(destination),
                        str(description or "").strip() or None,
                        str(category or "").strip() or None,
                        str(destination),
                        source.name,
                        digest.hexdigest(),
                        destination.stat().st_size,
                        int(created_by) if created_by is not None else None,
                    ),
                )
                attachment_id = int(cursor.lastrowid)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        self.touch_customer_data()
        return attachment_id

    def update_customer_attachment_metadata(
        self, attachment_id, description="", category=""
    ):
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE customer_attachments
                SET description = ?, category = ?, version = version + 1
                WHERE id = ?
                """,
                (
                    str(description or "").strip() or None,
                    str(category or "").strip() or None,
                    int(attachment_id),
                ),
            )
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def verify_managed_attachments(self):
        results = []
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, storage_path, original_name, sha256, size_bytes
                FROM customer_attachments WHERE status = 'managed'
                ORDER BY id
                """
            ).fetchall()
            for row in rows:
                path = Path(row["storage_path"] or "")
                state = "正常"
                current_hash = ""
                if not path.is_file():
                    state = "遺失"
                else:
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    current_hash = digest.hexdigest()
                    if row["sha256"] and current_hash != row["sha256"]:
                        state = "內容已變更"
                conn.execute(
                    "UPDATE customer_attachments SET status = ? WHERE id = ?",
                    ("managed" if state == "正常" else state, row["id"]),
                )
                results.append(
                    {
                        "id": row["id"],
                        "name": row["original_name"] or path.name,
                        "path": str(path),
                        "state": state,
                        "sha256": current_hash or row["sha256"],
                    }
                )
        return results

    def delete_customer_attachment(self, attachment_id, storage_root=None):
        managed_path = None
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT storage_path, status FROM customer_attachments WHERE id = ?",
                (int(attachment_id),),
            ).fetchone()
            if row and row["storage_path"]:
                managed_path = row["storage_path"]
            cursor = conn.execute(
                "DELETE FROM customer_attachments WHERE id = ?",
                (int(attachment_id),),
            )
        if managed_path and storage_root is not None:
            root = Path(storage_root).resolve()
            candidate = Path(managed_path).resolve()
            if candidate.is_relative_to(root):
                candidate.unlink(missing_ok=True)
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    @staticmethod
    def normalize_custom_field_key(label, field_key=None):
        source = str(field_key or label or "").strip().casefold()
        cleaned = "".join(character if character.isalnum() else "_" for character in source)
        cleaned = "_".join(part for part in cleaned.split("_") if part)
        if not cleaned:
            cleaned = "custom"
        if not (cleaned[0].isalpha() or cleaned[0] == "_"):
            cleaned = f"field_{cleaned}"
        return cleaned[:64]

    def list_custom_fields(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, field_key, label, created_at
                FROM custom_fields
                ORDER BY id
                """
            ).fetchall()

    def save_custom_field(self, label, field_key=None, field_id=None):
        label = str(label or "").strip()
        if not label:
            raise ValueError("欄位名稱不可空白")
        normalized_key = self.normalize_custom_field_key(label, field_key)
        with self.database.connect() as conn:
            if field_id is None:
                cursor = conn.execute(
                    "INSERT INTO custom_fields (field_key, label) VALUES (?, ?)",
                    (normalized_key, label),
                )
                saved_id = cursor.lastrowid
            else:
                saved_id = int(field_id)
                conn.execute(
                    "UPDATE custom_fields SET field_key = ?, label = ? WHERE id = ?",
                    (normalized_key, label, saved_id),
                )
        self.touch_customer_data()
        return saved_id

    def delete_custom_field(self, field_id):
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM custom_fields WHERE id = ?", (int(field_id),))
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def get_customer_custom_values(self, customer_id):
        with self.database.connect() as conn:
            return {
                row["field_id"]: row["value"]
                for row in conn.execute(
                    """
                    SELECT field_id, value
                    FROM customer_custom_values
                    WHERE customer_id = ?
                    """,
                    (int(customer_id),),
                )
            }

    def set_customer_custom_values(self, customer_id, values_by_field_id):
        entries = []
        for field_id, value in dict(values_by_field_id or {}).items():
            text = str(value or "").strip()
            if text:
                entries.append((int(customer_id), int(field_id), text))
        with self.database.connect() as conn:
            conn.execute(
                "DELETE FROM customer_custom_values WHERE customer_id = ?",
                (int(customer_id),),
            )
            conn.executemany(
                """
                INSERT INTO customer_custom_values (customer_id, field_id, value)
                VALUES (?, ?, ?)
                """,
                entries,
            )
        self.touch_customer_data()
        return len(entries)

    def set_customers_custom_values(self, customer_ids, values_by_field_id):
        customer_ids = sorted({int(customer_id) for customer_id in customer_ids})
        values = {
            int(field_id): str(value or "").strip()
            for field_id, value in dict(values_by_field_id or {}).items()
        }
        if not customer_ids or not values:
            return 0
        with self.database.connect() as conn:
            for customer_id in customer_ids:
                for field_id, value in values.items():
                    if value:
                        conn.execute(
                            """
                            INSERT INTO customer_custom_values (customer_id, field_id, value, updated_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(customer_id, field_id) DO UPDATE SET
                                value = excluded.value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (customer_id, field_id, value),
                        )
                    else:
                        conn.execute(
                            "DELETE FROM customer_custom_values WHERE customer_id = ? AND field_id = ?",
                            (customer_id, field_id),
                        )
        self.touch_customer_data()
        return len(customer_ids)

    def list_text_templates(self, template_type=None):
        parameters = []
        where_sql = ""
        if template_type:
            where_sql = "WHERE template_type = ?"
            parameters.append(str(template_type))
        with self.database.connect() as conn:
            return conn.execute(
                f"""
                SELECT id, template_type, title, content, created_at, updated_at
                FROM text_templates
                {where_sql}
                ORDER BY template_type, title COLLATE NOCASE, id
                """,
                parameters,
            ).fetchall()

    def save_text_template(self, title, content, template_type="note", template_id=None):
        title = str(title or "").strip()
        content = str(content or "").strip()
        template_type = str(template_type or "note").strip() or "note"
        if not title:
            raise ValueError("範本名稱不可空白")
        if not content:
            raise ValueError("範本內容不可空白")
        with self.database.connect() as conn:
            if template_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO text_templates (template_type, title, content)
                    VALUES (?, ?, ?)
                    """,
                    (template_type, title, content),
                )
                saved_id = cursor.lastrowid
            else:
                saved_id = int(template_id)
                conn.execute(
                    """
                    UPDATE text_templates
                    SET template_type = ?, title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (template_type, title, content, saved_id),
                )
        return saved_id

    def delete_text_template(self, template_id):
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM text_templates WHERE id = ?", (int(template_id),))
        return cursor.rowcount

    def list_contact_logs(self, customer_id):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, customer_id, contact_date, method, result,
                       next_follow_up, note, created_at
                FROM contact_logs
                WHERE customer_id = ?
                ORDER BY COALESCE(contact_date, created_at) DESC, id DESC
                """,
                (int(customer_id),),
            ).fetchall()

    def add_contact_log(
        self,
        customer_id,
        contact_date=None,
        method=None,
        result=None,
        next_follow_up=None,
        note=None,
    ):
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO contact_logs (
                    customer_id, contact_date, method, result, next_follow_up, note
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(customer_id),
                    str(contact_date or "").strip() or None,
                    str(method or "").strip() or None,
                    str(result or "").strip() or None,
                    str(next_follow_up or "").strip() or None,
                    note,
                ),
            )
        self.touch_customer_data()
        return cursor.lastrowid

    def delete_contact_log(self, log_id):
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM contact_logs WHERE id = ?", (int(log_id),))
        if cursor.rowcount:
            self.touch_customer_data()
        return cursor.rowcount

    def merge_customers(self, primary_id, secondary_id, merged_record):
        primary_id = int(primary_id)
        secondary_id = int(secondary_id)
        if primary_id == secondary_id:
            raise ValueError("不能合併同一筆資料")
        assignments = ", ".join(f"{key} = :{key}" for key in self.customer_data_columns)
        values = {key: merged_record.get(key) for key in self.customer_data_columns}
        with self.database.connect() as conn:
            conn.execute(
                f"UPDATE customers SET {assignments} WHERE id = :id",
                {**values, "id": primary_id},
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO case_customers (case_id, customer_id)
                SELECT case_id, ? FROM case_customers WHERE customer_id = ?
                """,
                (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO customer_tags (customer_id, tag_id)
                SELECT ?, tag_id FROM customer_tags WHERE customer_id = ?
                """,
                (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO customer_custom_values (customer_id, field_id, value)
                SELECT ?, field_id, value
                FROM customer_custom_values
                WHERE customer_id = ?
                """,
                (primary_id, secondary_id),
            )
            conn.execute(
                "UPDATE customer_attachments SET customer_id = ? WHERE customer_id = ?",
                (primary_id, secondary_id),
            )
            conn.execute(
                "UPDATE contact_logs SET customer_id = ? WHERE customer_id = ?",
                (primary_id, secondary_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO follow_up_reminders (
                    customer_id, due_date, status, note, created_at, updated_at
                )
                SELECT ?, due_date, status, note, created_at, updated_at
                FROM follow_up_reminders
                WHERE customer_id = ?
                """,
                (primary_id, secondary_id),
            )
            conn.execute(
                "UPDATE record_change_logs SET customer_id = ? WHERE customer_id = ?",
                (primary_id, secondary_id),
            )
            conn.execute("DELETE FROM customers WHERE id = ?", (secondary_id,))
        self.touch_customer_data()
        return primary_id

    def management_table_counts(self):
        table_names = (
            "cases",
            "case_customers",
            "tags",
            "customer_tags",
            "customer_attachments",
            "custom_fields",
            "customer_custom_values",
            "text_templates",
            "contact_logs",
            "follow_up_reminders",
        )
        with self.database.connect() as conn:
            return {
                table_name: conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                for table_name in table_names
            }

    def refresh_notifications(self, today_text):
        """Materialize due reminders and workflow deadlines into one inbox."""
        with self.database.connect() as conn:
            reminders = conn.execute(
                """
                SELECT r.customer_id, r.due_date, r.status, c.district, c.section,
                       c.land_number
                FROM follow_up_reminders r
                JOIN customers c ON c.id = r.customer_id
                WHERE COALESCE(r.status, '') <> '完成'
                  AND COALESCE(r.due_date, '') <> '' AND r.due_date <= ?
                """,
                (today_text,),
            ).fetchall()
            cases = conn.execute(
                """
                SELECT id, title, due_date, status FROM cases
                WHERE archived_at IS NULL AND COALESCE(status, '') <> '完成'
                  AND COALESCE(due_date, '') <> '' AND due_date <= ?
                """,
                (today_text,),
            ).fetchall()
            tasks = conn.execute(
                """
                SELECT task.id, task.title, task.due_date, task.status,
                       cases.title AS case_title
                FROM case_tasks task JOIN cases ON cases.id = task.case_id
                WHERE COALESCE(task.status, '') <> '完成'
                  AND COALESCE(task.due_date, '') <> '' AND task.due_date <= ?
                """,
                (today_text,),
            ).fetchall()
            entries = []
            for row in reminders:
                label = " ".join(
                    str(row[key] or "") for key in ("district", "section", "land_number")
                ).strip()
                entries.append(
                    (
                        f"follow-up:{row['customer_id']}:{row['due_date']}",
                        "追蹤", f"追蹤到期：{label or '土地資料'}",
                        f"到期日 {row['due_date']}／{row['status']}",
                        "逾期" if row["due_date"] < today_text else "今日",
                        "customer", row["customer_id"],
                    )
                )
            for row in cases:
                entries.append(
                    (
                        f"case:{row['id']}:{row['due_date']}", "案件",
                        f"案件到期：{row['title']}", f"到期日 {row['due_date']}",
                        "逾期" if row["due_date"] < today_text else "今日",
                        "case", row["id"],
                    )
                )
            for row in tasks:
                entries.append(
                    (
                        f"task:{row['id']}:{row['due_date']}", "任務",
                        f"任務到期：{row['title']}",
                        f"案件 {row['case_title']}／到期日 {row['due_date']}",
                        "逾期" if row["due_date"] < today_text else "今日",
                        "task", row["id"],
                    )
                )
            conn.executemany(
                """
                INSERT INTO notifications (
                    notification_key, category, title, detail, severity,
                    related_type, related_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notification_key) DO UPDATE SET
                    category=excluded.category, title=excluded.title,
                    detail=excluded.detail, severity=excluded.severity
                """,
                entries,
            )
        return len(entries)

    def list_notifications(self, include_read=False, limit=500):
        where_sql = "WHERE dismissed_at IS NULL" if include_read else (
            "WHERE dismissed_at IS NULL AND read_at IS NULL"
        )
        with self.database.connect() as conn:
            return conn.execute(
                f"""
                SELECT * FROM notifications {where_sql}
                ORDER BY CASE severity WHEN '逾期' THEN 0 ELSE 1 END, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

    def mark_notifications(self, notification_ids, action="read"):
        ids = sorted({int(value) for value in notification_ids})
        if not ids:
            return 0
        column = "dismissed_at" if action == "dismiss" else "read_at"
        with self.database.connect() as conn:
            cursor = conn.executemany(
                f"UPDATE notifications SET {column} = CURRENT_TIMESTAMP WHERE id = ?",
                [(value,) for value in ids],
            )
        return cursor.rowcount

    def list_import_profiles(self):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM import_profiles ORDER BY is_default DESC, name"
            ).fetchall()

    def save_import_profile(self, name, mapping, *, profile_id=None, is_default=False):
        name = str(name or "").strip()
        if not name:
            raise ValueError("設定檔名稱不可空白")
        mapping = {str(key).strip(): str(value).strip() for key, value in dict(mapping).items() if str(key).strip() and str(value).strip()}
        if not mapping:
            raise ValueError("至少需要一個欄位對應")
        with self.database.connect() as conn:
            if is_default:
                conn.execute("UPDATE import_profiles SET is_default = 0")
            if profile_id is None:
                cursor = conn.execute(
                    "INSERT INTO import_profiles (name, mapping_json, is_default) VALUES (?, ?, ?)",
                    (name, json.dumps(mapping, ensure_ascii=False), 1 if is_default else 0),
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE import_profiles SET name=?, mapping_json=?, is_default=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (name, json.dumps(mapping, ensure_ascii=False), 1 if is_default else 0, int(profile_id)),
            )
            return int(profile_id)

    def delete_import_profile(self, profile_id):
        with self.database.connect() as conn:
            return conn.execute("DELETE FROM import_profiles WHERE id = ?", (int(profile_id),)).rowcount

    def list_report_templates(self):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM report_templates ORDER BY name").fetchall()

    def save_report_template(
        self, name, title, fields, *, header_text="", footer_text="", template_id=None
    ):
        name = str(name or "").strip()
        title = str(title or "").strip()
        fields = [str(value) for value in fields if str(value).strip()]
        if not name or not title or not fields:
            raise ValueError("範本名稱、報表標題與至少一個欄位都必須填寫")
        with self.database.connect() as conn:
            if template_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO report_templates (
                        name, title, fields_json, header_text, footer_text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, title, json.dumps(fields, ensure_ascii=False), header_text, footer_text),
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE report_templates SET name=?, title=?, fields_json=?,
                    header_text=?, footer_text=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (name, title, json.dumps(fields, ensure_ascii=False), header_text, footer_text, int(template_id)),
            )
            return int(template_id)

    def delete_report_template(self, template_id):
        with self.database.connect() as conn:
            return conn.execute("DELETE FROM report_templates WHERE id = ?", (int(template_id),)).rowcount

    def list_backup_targets(self):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM backup_targets ORDER BY enabled DESC, name").fetchall()

    def save_backup_target(self, name, directory_path, *, enabled=True, target_id=None):
        name = str(name or "").strip()
        directory_path = str(directory_path or "").strip()
        if not name or not directory_path:
            raise ValueError("名稱與目的資料夾不可空白")
        with self.database.connect() as conn:
            if target_id is None:
                cursor = conn.execute(
                    "INSERT INTO backup_targets (name, directory_path, enabled) VALUES (?, ?, ?)",
                    (name, directory_path, 1 if enabled else 0),
                )
                return int(cursor.lastrowid)
            conn.execute(
                "UPDATE backup_targets SET name=?, directory_path=?, enabled=? WHERE id=?",
                (name, directory_path, 1 if enabled else 0, int(target_id)),
            )
            return int(target_id)

    def delete_backup_target(self, target_id):
        with self.database.connect() as conn:
            return conn.execute("DELETE FROM backup_targets WHERE id = ?", (int(target_id),)).rowcount

    def update_backup_target_result(self, target_id, error=None):
        with self.database.connect() as conn:
            if error:
                conn.execute(
                    "UPDATE backup_targets SET last_error=? WHERE id=?",
                    (str(error), int(target_id)),
                )
            else:
                conn.execute(
                    """
                    UPDATE backup_targets SET last_success_at=CURRENT_TIMESTAMP,
                        last_error=NULL WHERE id=?
                    """,
                    (int(target_id),),
                )

    def set_customer_location(self, customer_id, latitude, longitude, source="manual"):
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("經緯度超出有效範圍")
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO customer_locations (customer_id, latitude, longitude, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET latitude=excluded.latitude,
                    longitude=excluded.longitude, source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (int(customer_id), latitude, longitude, str(source or "manual")),
            )

    def list_customer_locations(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT location.*, c.district, c.section, c.land_number,
                       c.owner_name, c.address
                FROM customer_locations location
                JOIN customers c ON c.id = location.customer_id
                ORDER BY c.district, c.section, c.land_number
                """
            ).fetchall()

    def ignore_duplicate_pair(self, left_id, right_id):
        left_id, right_id = sorted((int(left_id), int(right_id)))
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO duplicate_reviews (
                    left_customer_id, right_customer_id, decision, reviewed_at
                ) VALUES (?, ?, 'ignored', CURRENT_TIMESTAMP)
                """,
                (left_id, right_id),
            )

    def ignored_duplicate_pairs(self):
        with self.database.connect() as conn:
            return {
                (row[0], row[1])
                for row in conn.execute(
                    "SELECT left_customer_id, right_customer_id FROM duplicate_reviews WHERE decision='ignored'"
                )
            }

    def get_watchlist_entries(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, name, note
                FROM watchlist
                ORDER BY name COLLATE NOCASE, id ASC
                """
            ).fetchall()

    def replace_watchlist_entries(self, entries):
        cleaned_entries = []
        seen_names = set()
        for item in entries:
            name = str(item.get("name") or "").strip()
            note = str(item.get("note") or "").strip()
            normalized_name = normalize_watch_name(name)
            if not normalized_name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            cleaned_entries.append((name, normalized_name, note or None))

        with self.database.connect() as conn:
            conn.execute("DELETE FROM watchlist")
            conn.executemany(
                "INSERT INTO watchlist (name, normalized_name, note) VALUES (?, ?, ?)",
                cleaned_entries,
            )

    def find_watchlist_match(self, name):
        normalized_name = normalize_watch_name(name)
        if not normalized_name:
            return None
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT id, name, note FROM watchlist WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()

    def init_auth_db(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                encryption_salt TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        if "encryption_salt" not in self.get_columns(conn, "users"):
            conn.execute("ALTER TABLE users ADD COLUMN encryption_salt TEXT")

    def has_admin_user(self):
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ?",
                (self.admin_username,),
            ).fetchone()
        return row is not None

    def create_admin_user(self, password):
        salt_hex, digest_hex = hash_password(password)
        encryption_salt_hex = os.urandom(16).hex()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, encryption_salt)
                VALUES (?, ?, ?, ?)
                """,
                (self.admin_username, salt_hex, digest_hex, encryption_salt_hex),
            )

    def authenticate_user(self, username, password):
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, role, active,
                       password_salt, password_hash, encryption_salt,
                       wrapped_data_key
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        if (
            row is None
            or not row["active"]
            or not verify_password(password, row["password_salt"], row["password_hash"])
        ):
            return None

        encryption_salt_hex = row["encryption_salt"]
        if not encryption_salt_hex:
            encryption_salt_hex = os.urandom(16).hex()
            with self.database.connect() as conn:
                conn.execute(
                    "UPDATE users SET encryption_salt = ? WHERE id = ?",
                    (encryption_salt_hex, row["id"]),
                )
        wrapping_key = derive_encryption_key(password, encryption_salt_hex)
        if row["wrapped_data_key"]:
            try:
                data_key = make_fernet(wrapping_key).decrypt(
                    row["wrapped_data_key"].encode("ascii")
                )
            except Exception:
                return None
        else:
            data_key = wrapping_key
        self.last_authenticated_user = {
            "id": int(row["id"]),
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "role": row["role"] or "viewer",
        }
        self.current_actor = row["username"]
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
        return data_key

    def list_users(self):
        with self.database.connect() as conn:
            return conn.execute(
                """
                SELECT id, username, display_name, role, active, created_at, last_login_at
                FROM users ORDER BY CASE WHEN username = ? THEN 0 ELSE 1 END, username
                """,
                (self.admin_username,),
            ).fetchall()

    def create_user(self, username, password, role, data_key, display_name=None):
        username = str(username or "").strip()
        if not username or any(character.isspace() for character in username):
            raise ValueError("帳號不可空白或包含空白字元")
        if role not in {"admin", "editor", "viewer"}:
            raise ValueError("權限角色不正確")
        password_salt, password_hash = hash_password(password)
        encryption_salt = os.urandom(16).hex()
        wrapping_key = derive_encryption_key(password, encryption_salt)
        wrapped_data_key = make_fernet(wrapping_key).encrypt(bytes(data_key)).decode("ascii")
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, display_name, role, active, password_salt,
                    password_hash, encryption_salt, wrapped_data_key
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    username, str(display_name or "").strip() or username, role,
                    password_salt, password_hash, encryption_salt, wrapped_data_key,
                ),
            )
        return int(cursor.lastrowid)

    def update_user(self, user_id, *, display_name=None, role=None, active=None):
        user_id = int(user_id)
        with self.database.connect() as conn:
            row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("找不到使用者")
            if row["username"] == self.admin_username and active is False:
                raise ValueError("不可停用主要 admin 帳號")
            if row["username"] == self.admin_username and role not in (None, "admin"):
                raise ValueError("不可移除主要 admin 帳號的管理員權限")
            fields = []
            values = []
            if display_name is not None:
                fields.append("display_name = ?")
                values.append(str(display_name).strip() or row["username"])
            if role is not None:
                if role not in {"admin", "editor", "viewer"}:
                    raise ValueError("權限角色不正確")
                fields.append("role = ?")
                values.append(role)
            if active is not None:
                fields.append("active = ?")
                values.append(1 if active else 0)
            if fields:
                conn.execute(
                    f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
                    (*values, user_id),
                )
        return user_id

    def reset_user_password(self, user_id, new_password, data_key):
        password_salt, password_hash = hash_password(new_password)
        encryption_salt = os.urandom(16).hex()
        wrapping_key = derive_encryption_key(new_password, encryption_salt)
        wrapped = make_fernet(wrapping_key).encrypt(bytes(data_key)).decode("ascii")
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET password_salt=?, password_hash=?, encryption_salt=?, wrapped_data_key=?
                WHERE id=?
                """,
                (password_salt, password_hash, encryption_salt, wrapped, int(user_id)),
            )
        return cursor.rowcount

    def change_user_password(self, username, current_password, new_password, data_key):
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, password_salt, password_hash
                FROM users WHERE username = ? AND active = 1
                """,
                (str(username),),
            ).fetchone()
            if row is None:
                raise ValueError("找不到目前登入帳號。")
            if not verify_password(
                current_password, row["password_salt"], row["password_hash"]
            ):
                raise ValueError("目前密碼錯誤。")
        backup_path = self.database.backup_database("password")
        self.reset_user_password(row["id"], new_password, data_key)
        return data_key, backup_path

    def change_admin_password(self, current_password, new_password):
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, password_salt, password_hash, encryption_salt,
                       wrapped_data_key
                FROM users
                WHERE username = ?
                """,
                (self.admin_username,),
            ).fetchone()
            if row is None:
                raise ValueError("找不到 admin 帳號。")
            if not verify_password(current_password, row["password_salt"], row["password_hash"]):
                raise ValueError("目前密碼錯誤。")

            current_wrapping_key = derive_encryption_key(
                current_password, row["encryption_salt"]
            )
            if row["wrapped_data_key"]:
                current_data_key = make_fernet(current_wrapping_key).decrypt(
                    row["wrapped_data_key"].encode("ascii")
                )
            else:
                current_data_key = current_wrapping_key
            backup_path = self.database.backup_database("password")
            new_password_salt, new_password_hash = hash_password(new_password)
            new_encryption_salt = os.urandom(16).hex()
            new_wrapping_key = derive_encryption_key(new_password, new_encryption_salt)
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            has_wrapped_settings = conn.execute(
                """
                SELECT 1 FROM app_settings
                WHERE setting_key = 'offsite_backup_password_encrypted'
                  AND COALESCE(setting_value, '') <> ''
                """
            ).fetchone() is not None

            if row["wrapped_data_key"] or user_count > 1 or has_wrapped_settings:
                wrapped_data_key = make_fernet(new_wrapping_key).encrypt(
                    current_data_key
                ).decode("ascii")
                conn.execute(
                    """
                    UPDATE users
                    SET password_salt=?, password_hash=?, encryption_salt=?, wrapped_data_key=?
                    WHERE id=?
                    """,
                    (
                        new_password_salt, new_password_hash, new_encryption_salt,
                        wrapped_data_key, row["id"],
                    ),
                )
                return current_data_key, backup_path

            old_fernet = make_fernet(current_data_key)
            new_encryption_key = new_wrapping_key
            new_fernet = make_fernet(new_encryption_key)

            records = conn.execute(
                "SELECT id, owner_name, external_id, address, note, visit_log, name FROM customers"
            ).fetchall()
            for record in records:
                plain_data = {
                    key: decrypt_value(old_fernet, record[key])
                    for key in ("owner_name", "external_id", "address", "note", "visit_log", "name")
                }
                if DECRYPTION_ERROR_TEXT in plain_data.values():
                    raise ValueError("有資料無法用目前密碼解密，無法修改密碼。")
                rotated = encrypt_record(new_fernet, plain_data)
                conn.execute(
                    """
                    UPDATE customers
                    SET owner_name = :owner_name,
                        external_id = :external_id,
                        address = :address,
                        note = :note,
                        visit_log = :visit_log,
                        name = :name
                    WHERE id = :id
                    """,
                    {**rotated, "id": record["id"]},
                )

            conn.execute(
                """
                UPDATE users
                SET password_salt = ?, password_hash = ?, encryption_salt = ?,
                    wrapped_data_key = NULL
                WHERE id = ?
                """,
                (new_password_salt, new_password_hash, new_encryption_salt, row["id"]),
            )
        self.touch_customer_data()
        return new_encryption_key, backup_path

    def migrate_db(self, conn):
        return self.migrations.run(conn)

    def init_db(self):
        first_run = not self.database.database_path.exists()
        if not first_run:
            with self.database.connect() as conn:
                current_version = self.migrations.current_version(conn)
            if current_version < LATEST_SCHEMA_VERSION:
                self.database.backup_database("pre-migration", require_schema=False)
        with self.database.connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self.migrate_db(conn)
            if first_run and self.seed_path.exists():
                conn.executescript(self.seed_path.read_text(encoding="utf-8"))
