"""Idempotently apply the bundled PostgreSQL schema on server startup."""

from pathlib import Path


POSTGRES_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "postgres" / "schema.sql"


def ensure_postgres_schema(dsn: str, schema_path: Path | str | None = None) -> int:
    """Apply all safe CREATE/ALTER migrations and return the schema version."""

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "尚未安裝 PostgreSQL 驅動，請安裝 requirements-server.txt"
        ) from exc

    source = Path(schema_path or POSTGRES_SCHEMA_PATH).resolve()
    statements = [
        statement.strip()
        for statement in source.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]
    with psycopg.connect(str(dsn), connect_timeout=5) as conn:
        for statement in statements:
            conn.execute(statement)
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
    return int(row[0])
