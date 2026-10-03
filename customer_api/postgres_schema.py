"""Idempotently apply the bundled PostgreSQL schema on server startup."""

import re
from pathlib import Path


POSTGRES_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "postgres" / "schema.sql"

# Every table whose ``id`` column is backed by a PostgreSQL identity sequence.
# Migration packages and restored backups can leave a sequence behind the
# largest stored id.  Keeping this list explicit makes the repair auditable and
# prevents any database-provided identifier from being interpolated as SQL.
IDENTITY_TABLES = (
    "users",
    "owners",
    "lands",
    "ownerships",
    "contact_logs",
    "follow_up_reminders",
    "projects",
    "import_batches",
    "import_data",
    "attachments",
    "audit_logs",
    "project_tasks",
    "tags",
    "custom_fields",
    "record_change_logs",
    "text_templates",
    "recycle_bin",
    "undo_operations",
    "notifications",
    "import_profiles",
    "report_templates",
    "watchlist",
    "operation_logs",
    "server_backup_targets",
    "field_visit_routes",
    "field_visit_route_items",
    "field_visit_status_history",
    "contacts",
    "owner_contact_relations",
    "urban_plans",
)
IDENTITY_PRIMARY_KEY_CONSTRAINTS = frozenset(
    f"{table_name}_pkey" for table_name in IDENTITY_TABLES
)
_DOLLAR_QUOTE_START = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _row_value(row, index: int, key: str):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _quoted_relation(relation_name: str) -> str:
    parts = [part.strip().strip('"') for part in str(relation_name).split(".")]
    if not parts or any(not part.replace("_", "").isalnum() for part in parts):
        raise RuntimeError("PostgreSQL identity sequence name is invalid")
    return ".".join(f'"{part}"' for part in parts)


def split_postgres_statements(source_text: str) -> list[str]:
    """Split SQL only on statement terminators outside PostgreSQL syntax.

    A plain ``str.split(";")`` corrupts line comments containing a semicolon
    and would also break quoted values or future dollar-quoted function bodies.
    Keeping the tokenizer here avoids adding a runtime parser dependency to the
    portable home-server package.
    """

    source = str(source_text or "")
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    quote = ""
    dollar_quote = ""
    line_comment = False
    block_comment_depth = 0

    while index < len(source):
        if line_comment:
            character = source[index]
            buffer.append(character)
            index += 1
            if character in "\r\n":
                line_comment = False
            continue

        if block_comment_depth:
            if source.startswith("/*", index):
                buffer.append("/*")
                block_comment_depth += 1
                index += 2
            elif source.startswith("*/", index):
                buffer.append("*/")
                block_comment_depth -= 1
                index += 2
            else:
                buffer.append(source[index])
                index += 1
            continue

        if dollar_quote:
            if source.startswith(dollar_quote, index):
                buffer.append(dollar_quote)
                index += len(dollar_quote)
                dollar_quote = ""
            else:
                buffer.append(source[index])
                index += 1
            continue

        if quote:
            character = source[index]
            buffer.append(character)
            index += 1
            if character == quote:
                if index < len(source) and source[index] == quote:
                    buffer.append(source[index])
                    index += 1
                else:
                    quote = ""
            continue

        if source.startswith("--", index):
            buffer.append("--")
            line_comment = True
            index += 2
            continue
        if source.startswith("/*", index):
            buffer.append("/*")
            block_comment_depth = 1
            index += 2
            continue

        character = source[index]
        if character in {"'", '"'}:
            quote = character
            buffer.append(character)
            index += 1
            continue
        if character == "$":
            match = _DOLLAR_QUOTE_START.match(source, index)
            if match:
                dollar_quote = match.group(0)
                buffer.append(dollar_quote)
                index = match.end()
                continue
        if character == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(character)
        index += 1

    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def repair_postgres_identity_sequences(conn, table_names=IDENTITY_TABLES) -> dict[str, int]:
    """Advance known identity sequences without ever moving one backwards."""

    repaired = {}
    for table_name in table_names:
        if table_name not in IDENTITY_TABLES:
            raise ValueError(f"Unsupported PostgreSQL identity table: {table_name}")
        max_row = conn.execute(
            f'SELECT COALESCE(MAX(id), 0) AS max_id FROM "{table_name}"'
        ).fetchone()
        sequence_row = conn.execute(
            "SELECT pg_get_serial_sequence(%s, 'id') AS sequence_name",
            (f"public.{table_name}",),
        ).fetchone()
        sequence_name = str(_row_value(sequence_row, 0, "sequence_name") or "")
        if not sequence_name:
            continue
        state_row = conn.execute(
            "SELECT last_value, is_called FROM " + _quoted_relation(sequence_name)
        ).fetchone()
        max_id = int(_row_value(max_row, 0, "max_id") or 0)
        last_value = int(_row_value(state_row, 0, "last_value") or 0)
        was_called = bool(_row_value(state_row, 1, "is_called"))
        target = max(1, max_id, last_value)
        is_called = bool(max_id > 0 or was_called)
        conn.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence_name, target, is_called),
        )
        repaired[table_name] = target
    return repaired


def ensure_postgres_schema(dsn: str, schema_path: Path | str | None = None) -> int:
    """Apply all safe CREATE/ALTER migrations and return the schema version."""

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "尚未安裝 PostgreSQL 驅動，請安裝 requirements-server.txt"
        ) from exc

    source = Path(schema_path or POSTGRES_SCHEMA_PATH).resolve()
    statements = split_postgres_statements(source.read_text(encoding="utf-8"))
    with psycopg.connect(str(dsn), connect_timeout=5) as conn:
        for statement in statements:
            conn.execute(statement)
        repair_postgres_identity_sequences(conn)
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
    return int(row[0])
