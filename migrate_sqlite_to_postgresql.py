"""Audit and migrate the current encrypted SQLite data into PostgreSQL.

The default mode is read-only and only prints a migration plan.  Writing to
PostgreSQL requires both ``--apply`` and ``--confirm MIGRATE`` so an accidental
command cannot replace the production source of truth.
"""

import argparse
import getpass
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from customer_database import CustomerDatabase
from customer_api.local_postgres import load_postgres_dsn
from customer_domain import normalize_match_text
from customer_fields import LAND_FIELDS
from customer_postgres_keys import land_key_for, owner_key_for
from customer_repository import CustomerRepository
from customer_security import ENCRYPTED_FIELDS, decrypt_value, encrypt_value, make_fernet


PROJECT_DIR = Path(__file__).resolve().parent
POSTGRES_SCHEMA_PATH = PROJECT_DIR / "postgres" / "schema.sql"

EXTENDED_SOURCE_TABLES = (
    "cases",
    "case_customers",
    "case_tasks",
    "tags",
    "customer_tags",
    "custom_fields",
    "customer_custom_values",
    "customer_attachments",
    "customer_locations",
    "duplicate_reviews",
    "record_change_logs",
    "text_templates",
    "recycle_bin",
    "undo_operations",
    "notifications",
    "import_profiles",
    "report_templates",
    "watchlist",
    "operation_logs",
)

DEVICE_LOCAL_TABLES = ("app_settings", "backup_targets")

TARGET_TABLES = (
    "users",
    "owners",
    "lands",
    "ownerships",
    "contact_logs",
    "follow_up_reminders",
    "projects",
    "project_ownerships",
    "project_tasks",
    "tags",
    "ownership_tags",
    "custom_fields",
    "ownership_custom_values",
    "attachments",
    "ownership_locations",
    "duplicate_reviews",
    "record_change_logs",
    "text_templates",
    "recycle_bin",
    "undo_operations",
    "notifications",
    "import_profiles",
    "report_templates",
    "watchlist",
    "operation_logs",
)

SOURCE_TARGET_COUNT_QUERIES = {
    "users": "SELECT COUNT(*) FROM users",
    "customers": "SELECT COUNT(*) FROM ownerships",
    "contact_logs": (
        "SELECT COUNT(*) FROM contact_logs "
        "WHERE legacy_contact_log_id IS NOT NULL"
    ),
    "follow_up_reminders": "SELECT COUNT(*) FROM follow_up_reminders",
    "cases": "SELECT COUNT(*) FROM projects WHERE legacy_case_id IS NOT NULL",
    "case_customers": "SELECT COUNT(*) FROM project_ownerships",
    "case_tasks": (
        "SELECT COUNT(*) FROM project_tasks WHERE legacy_task_id IS NOT NULL"
    ),
    "tags": "SELECT COUNT(*) FROM tags WHERE legacy_tag_id IS NOT NULL",
    "customer_tags": "SELECT COUNT(*) FROM ownership_tags",
    "custom_fields": (
        "SELECT COUNT(*) FROM custom_fields WHERE legacy_field_id IS NOT NULL"
    ),
    "customer_custom_values": "SELECT COUNT(*) FROM ownership_custom_values",
    "customer_attachments": (
        "SELECT COUNT(*) FROM attachments WHERE legacy_attachment_id IS NOT NULL"
    ),
    "customer_locations": "SELECT COUNT(*) FROM ownership_locations",
    "duplicate_reviews": "SELECT COUNT(*) FROM duplicate_reviews",
    "record_change_logs": (
        "SELECT COUNT(*) FROM record_change_logs "
        "WHERE legacy_change_log_id IS NOT NULL"
    ),
    "text_templates": (
        "SELECT COUNT(*) FROM text_templates WHERE legacy_template_id IS NOT NULL"
    ),
    "recycle_bin": (
        "SELECT COUNT(*) FROM recycle_bin WHERE legacy_recycle_id IS NOT NULL"
    ),
    "undo_operations": (
        "SELECT COUNT(*) FROM undo_operations WHERE legacy_undo_id IS NOT NULL"
    ),
    "notifications": (
        "SELECT COUNT(*) FROM notifications WHERE legacy_notification_id IS NOT NULL"
    ),
    "import_profiles": (
        "SELECT COUNT(*) FROM import_profiles WHERE legacy_profile_id IS NOT NULL"
    ),
    "report_templates": (
        "SELECT COUNT(*) FROM report_templates "
        "WHERE legacy_report_template_id IS NOT NULL"
    ),
    "watchlist": (
        "SELECT COUNT(*) FROM watchlist WHERE legacy_watchlist_id IS NOT NULL"
    ),
    "operation_logs": (
        "SELECT COUNT(*) FROM operation_logs "
        "WHERE legacy_operation_log_id IS NOT NULL"
    ),
}

ORPHAN_QUERIES = {
    "project_ownerships_project": (
        "SELECT COUNT(*) FROM project_ownerships x LEFT JOIN projects p "
        "ON p.id=x.project_id WHERE p.id IS NULL"
    ),
    "project_ownerships_ownership": (
        "SELECT COUNT(*) FROM project_ownerships x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE o.id IS NULL"
    ),
    "project_tasks": (
        "SELECT COUNT(*) FROM project_tasks x LEFT JOIN projects p "
        "ON p.id=x.project_id WHERE p.id IS NULL"
    ),
    "ownership_tags_ownership": (
        "SELECT COUNT(*) FROM ownership_tags x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE o.id IS NULL"
    ),
    "ownership_tags_tag": (
        "SELECT COUNT(*) FROM ownership_tags x LEFT JOIN tags t "
        "ON t.id=x.tag_id WHERE t.id IS NULL"
    ),
    "ownership_custom_values_ownership": (
        "SELECT COUNT(*) FROM ownership_custom_values x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE o.id IS NULL"
    ),
    "ownership_custom_values_field": (
        "SELECT COUNT(*) FROM ownership_custom_values x LEFT JOIN custom_fields f "
        "ON f.id=x.field_id WHERE f.id IS NULL"
    ),
    "attachments": (
        "SELECT COUNT(*) FROM attachments x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE x.legacy_attachment_id IS NOT NULL "
        "AND o.id IS NULL"
    ),
    "ownership_locations": (
        "SELECT COUNT(*) FROM ownership_locations x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE o.id IS NULL"
    ),
    "duplicate_reviews_left": (
        "SELECT COUNT(*) FROM duplicate_reviews x LEFT JOIN ownerships o "
        "ON o.id=x.left_ownership_id WHERE o.id IS NULL"
    ),
    "duplicate_reviews_right": (
        "SELECT COUNT(*) FROM duplicate_reviews x LEFT JOIN ownerships o "
        "ON o.id=x.right_ownership_id WHERE o.id IS NULL"
    ),
    "record_change_logs": (
        "SELECT COUNT(*) FROM record_change_logs x LEFT JOIN ownerships o "
        "ON o.id=x.ownership_id WHERE o.id IS NULL"
    ),
}


def verify_postgres(dsn):
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        counts = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in TARGET_TABLES
        }
        mirrored_source_counts = {
            source_table: int(connection.execute(query).fetchone()[0])
            for source_table, query in SOURCE_TARGET_COUNT_QUERIES.items()
        }
        orphan_counts = {
            name: int(connection.execute(query).fetchone()[0])
            for name, query in ORPHAN_QUERIES.items()
        }
        schema_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
    return {
        "schema_version": schema_version,
        "counts": counts,
        "mirrored_source_counts": mirrored_source_counts,
        "orphan_counts": orphan_counts,
    }


@dataclass(frozen=True)
class MigrationPlan:
    source_records: int
    owners: int
    lands: int
    ownerships: int
    owners_with_identity: int
    owners_without_identity: int
    incomplete_land_keys: int


def analyze_records(records, data_key):
    records = list(records)
    owner_keys = set()
    land_keys = set()
    owners_with_identity = set()
    incomplete_land_keys = 0
    for record in records:
        owner_key = owner_key_for(record, data_key)
        owner_keys.add(owner_key)
        if normalize_match_text(record.get("external_id")):
            owners_with_identity.add(owner_key)
        land_keys.add(land_key_for(record))
        if not all(
            normalize_match_text(record.get(key))
            for key in ("district", "section", "land_number")
        ):
            incomplete_land_keys += 1
    return MigrationPlan(
        source_records=len(records),
        owners=len(owner_keys),
        lands=len(land_keys),
        ownerships=len(records),
        owners_with_identity=len(owners_with_identity),
        owners_without_identity=len(owner_keys - owners_with_identity),
        incomplete_land_keys=incomplete_land_keys,
    )


def build_source(database_path):
    database_path = Path(database_path).resolve()
    database = CustomerDatabase(database_path, database_path.parent / "backups")
    repository = CustomerRepository(
        database,
        PROJECT_DIR / "schema.sql",
        PROJECT_DIR / "seed.sql",
        LAND_FIELDS,
    )
    with database.connect() as conn:
        version = repository.migrations.current_version(conn)
    if version < 6:
        raise ValueError("SQLite 資料庫版本過舊，請先用桌面程式完成升級。")
    return database, repository


def read_plain_records(repository, data_key):
    fernet = make_fernet(data_key)
    records = []
    for row in repository.fetch_all_customer_rows():
        record = dict(row)
        for field in ENCRYPTED_FIELDS:
            if field in record:
                record[field] = decrypt_value(fernet, record.get(field))
        records.append(record)
    return records


def collect_source_counts(sqlite_database):
    tables = (
        "users",
        "customers",
        "contact_logs",
        "follow_up_reminders",
        *EXTENDED_SOURCE_TABLES,
        *DEVICE_LOCAL_TABLES,
    )
    with sqlite_database.connect() as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _json_for_postgres(value, fallback):
    text = str(value or "").strip()
    if not text:
        return json.dumps(fallback, ensure_ascii=False)
    try:
        return json.dumps(json.loads(text), ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(text, ensure_ascii=False)


def _optional(value):
    text = str(value or "").strip()
    return text or None


def _read_extended_rows(sqlite_database):
    with sqlite_database.connect() as conn:
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in EXTENDED_SOURCE_TABLES
        }


def _copy_extended_data(sqlite_database, pg_conn, ownership_ids):
    rows = _read_extended_rows(sqlite_database)
    user_ids = {
        str(row[1]): int(row[0])
        for row in pg_conn.execute("SELECT id, username FROM users").fetchall()
    }
    ownership_links = {
        int(row[0]): (int(row[1]), int(row[2]))
        for row in pg_conn.execute(
            "SELECT id, owner_id, land_id FROM ownerships"
        ).fetchall()
    }

    pg_conn.execute("DELETE FROM project_tasks WHERE legacy_task_id IS NOT NULL")
    pg_conn.execute("DELETE FROM project_ownerships")
    pg_conn.execute("DELETE FROM project_owners")
    pg_conn.execute("DELETE FROM project_lands")
    pg_conn.execute("DELETE FROM ownership_tags")
    pg_conn.execute("DELETE FROM ownership_custom_values")
    pg_conn.execute("DELETE FROM ownership_locations")
    pg_conn.execute("DELETE FROM duplicate_reviews")
    for table, legacy_column in (
        ("attachments", "legacy_attachment_id"),
        ("record_change_logs", "legacy_change_log_id"),
        ("text_templates", "legacy_template_id"),
        ("recycle_bin", "legacy_recycle_id"),
        ("undo_operations", "legacy_undo_id"),
        ("notifications", "legacy_notification_id"),
        ("import_profiles", "legacy_profile_id"),
        ("report_templates", "legacy_report_template_id"),
        ("watchlist", "legacy_watchlist_id"),
        ("operation_logs", "legacy_operation_log_id"),
        ("tags", "legacy_tag_id"),
        ("custom_fields", "legacy_field_id"),
        ("projects", "legacy_case_id"),
    ):
        pg_conn.execute(
            f"DELETE FROM {table} WHERE {legacy_column} IS NOT NULL"
        )

    project_ids = {}
    for row in rows["cases"]:
        assigned_to_text = _optional(row.get("assigned_to"))
        saved = pg_conn.execute(
            """
            INSERT INTO projects (
                legacy_case_id, title, status, assigned_to, assigned_to_text,
                due_date, priority, next_action, note, archived_at,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                row["id"], row["title"], row["status"],
                user_ids.get(assigned_to_text), assigned_to_text,
                _optional(row.get("due_date")), row.get("priority") or "一般",
                _optional(row.get("next_action")), _optional(row.get("note")),
                _optional(row.get("archived_at")), row["created_at"],
                row["updated_at"],
            ),
        ).fetchone()
        project_ids[int(row["id"])] = int(saved[0])

    for row in rows["case_customers"]:
        project_id = project_ids.get(int(row["case_id"]))
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        if project_id is None or ownership_id is None:
            continue
        pg_conn.execute(
            """
            INSERT INTO project_ownerships (project_id, ownership_id, created_at)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (project_id, ownership_id, row["created_at"]),
        )
        owner_id, land_id = ownership_links[ownership_id]
        pg_conn.execute(
            "INSERT INTO project_owners (project_id, owner_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (project_id, owner_id),
        )
        pg_conn.execute(
            "INSERT INTO project_lands (project_id, land_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (project_id, land_id),
        )

    task_ids = {}
    for row in rows["case_tasks"]:
        project_id = project_ids.get(int(row["case_id"]))
        if project_id is None:
            continue
        saved = pg_conn.execute(
            """
            INSERT INTO project_tasks (
                legacy_task_id, project_id, title, assignee, due_date,
                status, priority, checklist, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                row["id"], project_id, row["title"], _optional(row.get("assignee")),
                _optional(row.get("due_date")), row.get("status") or "待處理",
                row.get("priority") or "一般", _optional(row.get("checklist")),
                row["created_at"], row["updated_at"],
            ),
        ).fetchone()
        task_ids[int(row["id"])] = int(saved[0])

    tag_ids = {}
    for row in rows["tags"]:
        saved = pg_conn.execute(
            """
            INSERT INTO tags (legacy_tag_id, name, color, created_at)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (row["id"], row["name"], _optional(row.get("color")), row["created_at"]),
        ).fetchone()
        tag_ids[int(row["id"])] = int(saved[0])
    for row in rows["customer_tags"]:
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        tag_id = tag_ids.get(int(row["tag_id"]))
        if ownership_id is not None and tag_id is not None:
            pg_conn.execute(
                "INSERT INTO ownership_tags (ownership_id, tag_id, created_at) VALUES (%s, %s, %s)",
                (ownership_id, tag_id, row["created_at"]),
            )

    field_ids = {}
    for row in rows["custom_fields"]:
        saved = pg_conn.execute(
            """
            INSERT INTO custom_fields (legacy_field_id, field_key, label, created_at)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (row["id"], row["field_key"], row["label"], row["created_at"]),
        ).fetchone()
        field_ids[int(row["id"])] = int(saved[0])
    for row in rows["customer_custom_values"]:
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        field_id = field_ids.get(int(row["field_id"]))
        if ownership_id is not None and field_id is not None:
            pg_conn.execute(
                """
                INSERT INTO ownership_custom_values (
                    ownership_id, field_id, value, updated_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (ownership_id, field_id, row.get("value"), row["updated_at"]),
            )

    for row in rows["customer_attachments"]:
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        if ownership_id is None:
            continue
        owner_id, land_id = ownership_links[ownership_id]
        original_name = _optional(row.get("original_name")) or Path(
            row["file_path"]
        ).name
        pg_conn.execute(
            """
            INSERT INTO attachments (
                legacy_attachment_id, ownership_id, owner_id, land_id,
                file_path, storage_path, original_name, description, category, size_bytes,
                sha256, status, version, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], ownership_id, owner_id, land_id, row["file_path"],
                _optional(row.get("storage_path")) or row["file_path"], original_name,
                _optional(row.get("description")), _optional(row.get("category")),
                row.get("size_bytes"),
                _optional(row.get("sha256")), row.get("status") or "external",
                int(row.get("version") or 1), row["created_at"],
            ),
        )

    for row in rows["customer_locations"]:
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        if ownership_id is not None:
            pg_conn.execute(
                """
                INSERT INTO ownership_locations (
                    ownership_id, latitude, longitude, source, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    ownership_id, row["latitude"], row["longitude"],
                    row.get("source") or "manual", row["updated_at"],
                ),
            )

    for row in rows["duplicate_reviews"]:
        left_id = ownership_ids.get(int(row["left_customer_id"]))
        right_id = ownership_ids.get(int(row["right_customer_id"]))
        if left_id is None or right_id is None or left_id == right_id:
            continue
        left_id, right_id = sorted((left_id, right_id))
        pg_conn.execute(
            """
            INSERT INTO duplicate_reviews (
                left_ownership_id, right_ownership_id, decision, reviewed_at
            ) VALUES (%s, %s, %s, %s)
            """,
            (left_id, right_id, row.get("decision") or "ignored", row["reviewed_at"]),
        )

    for row in rows["record_change_logs"]:
        ownership_id = ownership_ids.get(int(row["customer_id"]))
        if ownership_id is not None:
            pg_conn.execute(
                """
                INSERT INTO record_change_logs (
                    legacy_change_log_id, ownership_id, action_type, field_key,
                    field_label, old_value, new_value, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["id"], ownership_id, row["action_type"], row["field_key"],
                    row["field_label"], row.get("old_value"), row.get("new_value"),
                    row["created_at"],
                ),
            )

    for row in rows["text_templates"]:
        pg_conn.execute(
            """
            INSERT INTO text_templates (
                legacy_template_id, template_type, title, content,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], row.get("template_type") or "note", row["title"],
                row["content"], row["created_at"], row["updated_at"],
            ),
        )

    for row in rows["recycle_bin"]:
        pg_conn.execute(
            """
            INSERT INTO recycle_bin (
                legacy_recycle_id, entity_type, original_id, display_label,
                payload_json, deleted_by, deleted_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                row["id"], row.get("entity_type") or "customer", row.get("original_id"),
                _optional(row.get("display_label")),
                _json_for_postgres(row.get("payload_json"), {}),
                _optional(row.get("deleted_by")), row["deleted_at"],
            ),
        )

    for row in rows["undo_operations"]:
        pg_conn.execute(
            """
            INSERT INTO undo_operations (
                legacy_undo_id, operation_type, summary, payload_json,
                actor_username, status, created_at, undone_at
            ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                row["id"], row["operation_type"], row["summary"],
                _json_for_postgres(row.get("payload_json"), {}),
                _optional(row.get("actor_username")), row.get("status") or "available",
                row["created_at"], _optional(row.get("undone_at")),
            ),
        )

    for row in rows["notifications"]:
        related_type = _optional(row.get("related_type"))
        legacy_related_id = row.get("related_id")
        related_id = legacy_related_id
        if legacy_related_id is not None:
            if related_type == "customer":
                related_id = ownership_ids.get(int(legacy_related_id))
            elif related_type == "case":
                related_id = project_ids.get(int(legacy_related_id))
            elif related_type == "task":
                related_id = task_ids.get(int(legacy_related_id))
        pg_conn.execute(
            """
            INSERT INTO notifications (
                legacy_notification_id, notification_key, category, title,
                detail, severity, related_type, related_id, legacy_related_id,
                read_at, dismissed_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], row["notification_key"], row["category"], row["title"],
                _optional(row.get("detail")), row.get("severity") or "提醒",
                related_type, related_id, legacy_related_id,
                _optional(row.get("read_at")), _optional(row.get("dismissed_at")),
                row["created_at"],
            ),
        )

    for row in rows["import_profiles"]:
        pg_conn.execute(
            """
            INSERT INTO import_profiles (
                legacy_profile_id, name, mapping_json, is_default,
                created_at, updated_at
            ) VALUES (%s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                row["id"], row["name"],
                _json_for_postgres(row.get("mapping_json"), {}),
                bool(row.get("is_default")), row["created_at"], row["updated_at"],
            ),
        )

    for row in rows["report_templates"]:
        pg_conn.execute(
            """
            INSERT INTO report_templates (
                legacy_report_template_id, name, title, fields_json,
                header_text, footer_text, created_at, updated_at
            ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                row["id"], row["name"], row["title"],
                _json_for_postgres(row.get("fields_json"), []),
                _optional(row.get("header_text")), _optional(row.get("footer_text")),
                row["created_at"], row["updated_at"],
            ),
        )

    for row in rows["watchlist"]:
        pg_conn.execute(
            """
            INSERT INTO watchlist (
                legacy_watchlist_id, name, normalized_name, note,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], row["name"], row["normalized_name"],
                _optional(row.get("note")), row["created_at"], row["updated_at"],
            ),
        )

    for row in rows["operation_logs"]:
        pg_conn.execute(
            """
            INSERT INTO operation_logs (
                legacy_operation_log_id, action_type, summary, detail,
                actor_username, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], row["action_type"], row["summary"],
                _optional(row.get("detail")), _optional(row.get("actor_username")),
                row["created_at"],
            ),
        )

    return {table: len(table_rows) for table, table_rows in rows.items()}


def _copy_users(sqlite_database, pg_conn):
    with sqlite_database.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, role, active, password_salt,
                   password_hash, encryption_salt, wrapped_data_key,
                   created_at, last_login_at
            FROM users ORDER BY id
            """
        ).fetchall()
    for row in rows:
        pg_conn.execute(
            """
            INSERT INTO users (
                id, username, display_name, role, active, password_salt,
                password_hash, encryption_salt, wrapped_data_key,
                created_at, last_login_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                role = EXCLUDED.role,
                active = EXCLUDED.active,
                password_salt = EXCLUDED.password_salt,
                password_hash = EXCLUDED.password_hash,
                encryption_salt = EXCLUDED.encryption_salt,
                wrapped_data_key = EXCLUDED.wrapped_data_key,
                last_login_at = EXCLUDED.last_login_at
            """,
            (
                row["id"], row["username"], row["display_name"],
                row["role"] or "viewer", bool(row["active"]), row["password_salt"],
                row["password_hash"], row["encryption_salt"], row["wrapped_data_key"],
                row["created_at"], row["last_login_at"],
            ),
        )
    pg_conn.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            GREATEST(COALESCE((SELECT MAX(id) FROM users), 1), 1),
            true
        )
        """
    )


def apply_migration(
    sqlite_database,
    records,
    data_key,
    dsn,
    *,
    copy_users=True,
    target_data_key=None,
    before_migration_callback=None,
    verification_callback=None,
):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("請先安裝 requirements-server.txt") from exc

    migration_data_key = bytes(target_data_key or data_key)
    fernet = make_fernet(migration_data_key)
    owner_ids = {}
    land_ids = {}
    ownership_ids = {}
    schema_sql = POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as pg_conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                pg_conn.execute(statement)
        if copy_users:
            _copy_users(sqlite_database, pg_conn)
        preparation = (
            before_migration_callback(pg_conn)
            if before_migration_callback
            else None
        )

        for record in records:
            owner_key = owner_key_for(record, migration_data_key)
            if owner_key not in owner_ids:
                row = pg_conn.execute(
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
                        owner_key,
                        encrypt_value(fernet, record.get("owner_name") or record.get("name")),
                        encrypt_value(fernet, record.get("external_id")),
                        encrypt_value(fernet, record.get("address")),
                    ),
                ).fetchone()
                owner_ids[owner_key] = int(row[0])

            land_key = land_key_for(record)
            if land_key not in land_ids:
                row = pg_conn.execute(
                    """
                    INSERT INTO lands (
                        land_key, district, section, subsection, land_number, area,
                        declared_value
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (land_key) DO UPDATE SET
                        subsection = EXCLUDED.subsection,
                        area = EXCLUDED.area,
                        declared_value = EXCLUDED.declared_value,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        land_key,
                        record.get("district") or "",
                        record.get("section") or "",
                        record.get("subsection") or "",
                        record.get("land_number") or "",
                        record.get("area"),
                        record.get("declared_value"),
                    ),
                ).fetchone()
                land_ids[land_key] = int(row[0])

            legacy_id = int(record["id"])
            row = pg_conn.execute(
                """
                INSERT INTO ownerships (
                    legacy_customer_id, owner_id, land_id, registration_order,
                    numerator, denominator, ping, total_declared_value,
                    registration_reason, note, visit_log, name,
                    owner_name_override, external_id_override, address_override,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s)
                ON CONFLICT (legacy_customer_id) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id,
                    land_id = EXCLUDED.land_id,
                    registration_order = EXCLUDED.registration_order,
                    numerator = EXCLUDED.numerator,
                    denominator = EXCLUDED.denominator,
                    ping = EXCLUDED.ping,
                    total_declared_value = EXCLUDED.total_declared_value,
                    registration_reason = EXCLUDED.registration_reason,
                    note = EXCLUDED.note,
                    visit_log = EXCLUDED.visit_log,
                    name = EXCLUDED.name,
                    owner_name_override = EXCLUDED.owner_name_override,
                    external_id_override = EXCLUDED.external_id_override,
                    address_override = EXCLUDED.address_override,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                (
                    legacy_id,
                    owner_ids[owner_key],
                    land_ids[land_key],
                    record.get("registration_order"),
                    record.get("numerator"),
                    record.get("denominator"),
                    record.get("ping"),
                    record.get("total_declared_value"),
                    record.get("registration_reason"),
                    encrypt_value(fernet, record.get("note")),
                    encrypt_value(fernet, record.get("visit_log")),
                    encrypt_value(fernet, record.get("name") or record.get("owner_name")),
                    encrypt_value(fernet, record.get("owner_name") or record.get("name")),
                    encrypt_value(fernet, record.get("external_id")),
                    encrypt_value(fernet, record.get("address")),
                    record.get("created_at"),
                    record.get("updated_at"),
                ),
            ).fetchone()
            ownership_ids[legacy_id] = int(row[0])

        with sqlite_database.connect() as conn:
            contact_rows = conn.execute(
                "SELECT * FROM contact_logs ORDER BY id"
            ).fetchall()
            follow_up_rows = conn.execute(
                "SELECT * FROM follow_up_reminders ORDER BY id"
            ).fetchall()
        for row in contact_rows:
            ownership_id = ownership_ids.get(int(row["customer_id"]))
            if ownership_id is None:
                continue
            pg_conn.execute(
                """
                INSERT INTO contact_logs (
                    legacy_contact_log_id, ownership_id, contact_date, method,
                    result, next_follow_up, note, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (legacy_contact_log_id) DO UPDATE SET
                    ownership_id = EXCLUDED.ownership_id,
                    contact_date = EXCLUDED.contact_date,
                    method = EXCLUDED.method,
                    result = EXCLUDED.result,
                    next_follow_up = EXCLUDED.next_follow_up,
                    note = EXCLUDED.note
                """,
                (
                    row["id"], ownership_id, row["contact_date"], row["method"],
                    row["result"], row["next_follow_up"], row["note"], row["created_at"],
                ),
            )
        for row in follow_up_rows:
            ownership_id = ownership_ids.get(int(row["customer_id"]))
            if ownership_id is None:
                continue
            pg_conn.execute(
                """
                INSERT INTO follow_up_reminders (
                    ownership_id, due_date, status, note, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (ownership_id) DO UPDATE SET
                    due_date = EXCLUDED.due_date,
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    ownership_id, row["due_date"], row["status"], row["note"],
                    row["created_at"], row["updated_at"],
                ),
            )
        extended_counts = _copy_extended_data(
            sqlite_database, pg_conn, ownership_ids
        )
        pg_conn.execute(
            """
            INSERT INTO audit_logs (actor, action_type, summary, detail)
            VALUES ('migration-tool', 'sqlite_to_postgresql', %s, %s::jsonb)
            """,
            (
                f"Migrated {len(records)} ownership records",
                json.dumps(
                    {
                        "owners": len(owner_ids),
                        "lands": len(land_ids),
                        "ownerships": len(ownership_ids),
                        "extended_source_counts": extended_counts,
                        "device_local_tables_excluded": list(DEVICE_LOCAL_TABLES),
                    }
                ),
            ),
        )
        verification = (
            verification_callback(pg_conn) if verification_callback else None
        )
    result = {
        "owners": len(owner_ids),
        "lands": len(land_ids),
        "ownerships": len(ownership_ids),
        "extended_source_counts": extended_counts,
        "device_local_tables_excluded": list(DEVICE_LOCAL_TABLES),
    }
    if verification is not None:
        result["verification"] = verification
    if preparation is not None:
        result["preparation"] = preparation
    return result


def build_parser():
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 遷移工具")
    parser.add_argument("--source", default=str(PROJECT_DIR / "customers.db"))
    parser.add_argument("--username", default="admin")
    parser.add_argument(
        "--dsn",
        default=(
            os.environ.get("LAND_CUSTOMER_POSTGRES_DSN", "").strip()
            or load_postgres_dsn()
        ),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    sqlite_database, repository = build_source(args.source)
    password = getpass.getpass(f"請輸入 {args.username} 的系統密碼：")
    data_key = repository.authenticate_user(args.username, password)
    if not data_key:
        raise SystemExit("登入失敗，未讀取或修改任何資料。")
    records = read_plain_records(repository, data_key)
    plan = analyze_records(records, data_key)
    output = {"mode": "audit", "plan": asdict(plan)}

    if args.apply:
        if args.confirm != "MIGRATE":
            raise SystemExit("正式遷移必須同時加上 --confirm MIGRATE。")
        if not args.dsn:
            raise SystemExit("請設定 LAND_CUSTOMER_POSTGRES_DSN 或使用 --dsn。")
        output["mode"] = "applied"
        output["result"] = apply_migration(
            sqlite_database, records, data_key, args.dsn
        )

    print(
        json.dumps(output, ensure_ascii=False, indent=2)
        if args.json
        else "\n".join(f"{key}: {value}" for key, value in asdict(plan).items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
