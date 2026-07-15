"""Versioned, idempotent SQLite schema migrations."""


LATEST_SCHEMA_VERSION = 7


def get_columns(conn, table_name):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


class MigrationRunner:
    def __init__(self, land_fields):
        self.land_fields = tuple(land_fields)
        self.migrations = (
            (1, "customer columns and indexes", self._migration_001_customer_schema),
            (2, "application support tables", self._migration_002_support_tables),
            (3, "remove obsolete customer indexes", self._migration_003_remove_obsolete_indexes),
            (4, "change logs and follow up reminders", self._migration_004_tracking_tables),
            (5, "case tags attachments custom fields templates contact logs", self._migration_005_management_tables),
            (6, "productivity safety accounts workflow reports maps", self._migration_006_productivity_tables),
            (7, "normalize legacy contact logs", self._migration_007_normalize_contact_logs),
        )

    @staticmethod
    def current_version(conn):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0])

    @staticmethod
    def _ensure_history_table(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def run(self, conn):
        self._ensure_history_table(conn)
        current = self.current_version(conn)
        applied = []
        for version, name, migration in self.migrations:
            if version <= current:
                continue
            # Migration 6 creates a trigger and therefore uses executescript; SQLite
            # commits an active savepoint before executescript runs.  Every statement
            # in this migration is idempotent, so it can safely resume after a failure.
            if version == 6:
                migration(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name),
                )
                applied.append(version)
                current = version
                continue
            savepoint = f"migration_{version}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                migration(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name),
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            applied.append(version)
            current = version
        return applied

    def _migration_001_customer_schema(self, conn):
        columns = get_columns(conn, "customers")
        for key, _label in self.land_fields:
            if key not in columns:
                conn.execute(f"ALTER TABLE customers ADD COLUMN {key} TEXT")
                columns.add(key)
        if "name" not in columns:
            conn.execute("ALTER TABLE customers ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            columns.add("name")
        missing_timestamps = [
            column for column in ("created_at", "updated_at") if column not in columns
        ]
        for timestamp_column in missing_timestamps:
            conn.execute(f"ALTER TABLE customers ADD COLUMN {timestamp_column} TEXT")
            columns.add(timestamp_column)
        for timestamp_column in missing_timestamps:
            conn.execute(
                f"UPDATE customers SET {timestamp_column} = CURRENT_TIMESTAMP "
                f"WHERE {timestamp_column} IS NULL"
            )
        if "owner_name" in columns and "name" in columns:
            conn.execute(
                """
                UPDATE customers SET owner_name = name
                WHERE (owner_name IS NULL OR owner_name = '')
                  AND name IS NOT NULL AND name <> ''
                """
            )
        for legacy_column in ("customer_code", "company"):
            if legacy_column in columns:
                conn.execute(
                    f"""
                    UPDATE customers SET external_id = {legacy_column}
                    WHERE (external_id IS NULL OR external_id = '')
                      AND {legacy_column} IS NOT NULL AND {legacy_column} <> ''
                    """
                )
        for column in ("district", "section", "land_number", "owner_name", "external_id"):
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_customers_{column} ON customers({column})"
            )

    @staticmethod
    def _migration_002_support_tables(conn):
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
        if "encryption_salt" not in get_columns(conn, "users"):
            conn.execute("ALTER TABLE users ADD COLUMN encryption_salt TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
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

    @staticmethod
    def _migration_003_remove_obsolete_indexes(conn):
        obsolete_indexes = (
            "idx_customers_owner_name",
            "idx_customers_external_id",
            "idx_customers_name",
            "idx_customers_customer_code",
            "idx_customers_email",
            "idx_customers_phone",
        )
        for index_name in obsolete_indexes:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")

    @staticmethod
    def _migration_004_tracking_tables(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS record_change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                field_key TEXT NOT NULL,
                field_label TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )

    @staticmethod
    def _migration_005_management_tables(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '進行中',
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS case_customers (
                case_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(case_id, customer_id),
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_case_customers_customer_id
            ON case_customers(customer_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_tags (
                customer_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(customer_id, tag_id),
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_customer_tags_tag_id
            ON customer_tags(tag_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_customer_attachments_customer_id
            ON customer_attachments(customer_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_custom_values (
                customer_id INTEGER NOT NULL,
                field_id INTEGER NOT NULL,
                value TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(customer_id, field_id),
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
                FOREIGN KEY(field_id) REFERENCES custom_fields(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS text_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_type TEXT NOT NULL DEFAULT 'note',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                contact_date TEXT,
                method TEXT,
                result TEXT,
                next_follow_up TEXT,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_logs_customer_id
            ON contact_logs(customer_id, id DESC)
            """
        )
        conn.execute("DROP TRIGGER IF EXISTS trg_cases_updated_at")
        conn.execute(
            """
            CREATE TRIGGER trg_cases_updated_at
            AFTER UPDATE ON cases
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
                UPDATE cases
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END
            """
        )
        conn.execute("DROP TRIGGER IF EXISTS trg_text_templates_updated_at")
        conn.execute(
            """
            CREATE TRIGGER trg_text_templates_updated_at
            AFTER UPDATE ON text_templates
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
                UPDATE text_templates
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_record_change_logs_customer_id
            ON record_change_logs(customer_id, id DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS follow_up_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL UNIQUE,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT '未處理',
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_follow_up_reminders_due_date
            ON follow_up_reminders(due_date)
            """
        )
        conn.execute("DROP TRIGGER IF EXISTS trg_follow_up_reminders_updated_at")
        conn.execute(
            """
            CREATE TRIGGER trg_follow_up_reminders_updated_at
            AFTER UPDATE ON follow_up_reminders
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
                UPDATE follow_up_reminders
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END
            """
        )

    @staticmethod
    def _migration_007_normalize_contact_logs(conn):
        columns = get_columns(conn, "contact_logs")
        canonical_columns = {
            "id",
            "customer_id",
            "contact_date",
            "method",
            "result",
            "next_follow_up",
            "note",
            "created_at",
        }
        if canonical_columns <= columns and not ({"subject", "content"} & columns):
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_contact_logs_customer_id
                ON contact_logs(customer_id, id DESC)
                """
            )
            return

        legacy_table = "contact_logs_legacy_v7"
        conn.execute(f"DROP TABLE IF EXISTS {legacy_table}")
        conn.execute(f"ALTER TABLE contact_logs RENAME TO {legacy_table}")
        conn.execute(
            """
            CREATE TABLE contact_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                contact_date TEXT,
                method TEXT,
                result TEXT,
                next_follow_up TEXT,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )

        def first_available(*names, fallback="NULL"):
            available = [name for name in names if name in columns]
            if not available:
                return fallback
            if len(available) == 1:
                return available[0]
            return f"COALESCE({', '.join(available)})"

        id_expression = first_available("id", fallback="NULL")
        customer_expression = first_available("customer_id", fallback="NULL")
        date_expression = first_available("contact_date")
        method_expression = first_available("method")
        result_expression = first_available("result", "subject")
        follow_up_expression = first_available("next_follow_up")
        note_expression = first_available("note", "content")
        created_expression = first_available(
            "created_at", "contact_date", fallback="CURRENT_TIMESTAMP"
        )
        conn.execute(
            f"""
            INSERT INTO contact_logs (
                id, customer_id, contact_date, method, result,
                next_follow_up, note, created_at
            )
            SELECT
                {id_expression}, {customer_expression}, {date_expression},
                {method_expression}, {result_expression}, {follow_up_expression},
                {note_expression}, COALESCE({created_expression}, CURRENT_TIMESTAMP)
            FROM {legacy_table}
            """
        )
        conn.execute(f"DROP TABLE {legacy_table}")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_logs_customer_id
            ON contact_logs(customer_id, id DESC)
            """
        )

    @staticmethod
    def _migration_006_productivity_tables(conn):
        """Add the v1.1 safety, collaboration, workflow, and reporting layer."""

        def add_column(table_name, column_name, definition):
            if column_name not in get_columns(conn, table_name):
                conn.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )

        add_column("users", "display_name", "TEXT")
        add_column("users", "role", "TEXT NOT NULL DEFAULT 'admin'")
        add_column("users", "active", "INTEGER NOT NULL DEFAULT 1")
        add_column("users", "wrapped_data_key", "TEXT")
        add_column("users", "last_login_at", "TEXT")
        add_column("operation_logs", "actor_username", "TEXT")

        add_column("cases", "assigned_to", "TEXT")
        add_column("cases", "due_date", "TEXT")
        add_column("cases", "priority", "TEXT NOT NULL DEFAULT '一般'")
        add_column("cases", "next_action", "TEXT")
        add_column("cases", "archived_at", "TEXT")

        add_column("customer_attachments", "storage_path", "TEXT")
        add_column("customer_attachments", "original_name", "TEXT")
        add_column("customer_attachments", "sha256", "TEXT")
        add_column("customer_attachments", "size_bytes", "INTEGER")
        add_column("customer_attachments", "status", "TEXT NOT NULL DEFAULT 'external'")
        add_column("customer_attachments", "version", "INTEGER NOT NULL DEFAULT 1")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL DEFAULT 'customer',
                original_id INTEGER,
                display_label TEXT,
                payload_json TEXT NOT NULL,
                deleted_by TEXT,
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_recycle_bin_deleted_at
            ON recycle_bin(deleted_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS undo_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                actor_username TEXT,
                status TEXT NOT NULL DEFAULT 'available',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                undone_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_undo_operations_status
            ON undo_operations(status, id DESC);

            CREATE TABLE IF NOT EXISTS case_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                assignee TEXT,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT '待處理',
                priority TEXT NOT NULL DEFAULT '一般',
                checklist TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_case_tasks_due_date
            ON case_tasks(status, due_date);

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_key TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                severity TEXT NOT NULL DEFAULT '提醒',
                related_type TEXT,
                related_id INTEGER,
                read_at TEXT,
                dismissed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_unread
            ON notifications(read_at, dismissed_at, id DESC);

            CREATE TABLE IF NOT EXISTS import_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                mapping_json TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS report_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                header_text TEXT,
                footer_text TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backup_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                directory_path TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_success_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_locations (
                customer_id INTEGER PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS duplicate_reviews (
                left_customer_id INTEGER NOT NULL,
                right_customer_id INTEGER NOT NULL,
                decision TEXT NOT NULL DEFAULT 'ignored',
                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(left_customer_id, right_customer_id)
            );

            DROP TRIGGER IF EXISTS trg_case_tasks_updated_at;
            CREATE TRIGGER trg_case_tasks_updated_at
            AFTER UPDATE ON case_tasks
            FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
            BEGIN
                UPDATE case_tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
            END;
            """
        )
