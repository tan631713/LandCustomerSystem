"""Environment-based configuration for the self-hosted API."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from customer_api.local_postgres import load_postgres_dsn


PROJECT_DIR = Path(__file__).resolve().parent.parent


def _positive_int(value, default, *, minimum=1, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    return min(parsed, maximum) if maximum is not None else parsed


@dataclass(frozen=True)
class ApiSettings:
    backend: str = "sqlite"
    sqlite_database_path: Path = PROJECT_DIR / "customers.db"
    backup_directory: Path = PROJECT_DIR / "backups"
    attachment_directory: Path = PROJECT_DIR / "attachments"
    schema_path: Path = PROJECT_DIR / "schema.sql"
    seed_path: Path = PROJECT_DIR / "seed.sql"
    postgres_dsn: str = field(default="", repr=False)
    session_ttl_seconds: int = 8 * 60 * 60
    max_page_size: int = 500
    max_attachment_size_bytes: int = 50 * 1024 * 1024

    def __post_init__(self):
        backend = str(self.backend).strip().lower()
        if backend not in {"sqlite", "postgresql"}:
            raise ValueError("CUSTOMER_API_BACKEND 必須是 sqlite 或 postgresql")
        if backend == "postgresql" and not str(self.postgres_dsn).strip():
            raise ValueError("使用 PostgreSQL 時必須設定 CUSTOMER_API_DATABASE_URL")
        object.__setattr__(self, "backend", backend)
        for name in (
            "sqlite_database_path",
            "backup_directory",
            "attachment_directory",
            "schema_path",
            "seed_path",
        ):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())

    @classmethod
    def from_env(cls, base_directory=None):
        base = Path(base_directory or PROJECT_DIR).resolve()
        dsn = os.environ.get("CUSTOMER_API_DATABASE_URL", "").strip()
        configured_backend = os.environ.get("CUSTOMER_API_BACKEND", "").strip().lower()
        backend = configured_backend or ("postgresql" if dsn else "sqlite")
        if backend == "postgresql" and not dsn:
            dsn = load_postgres_dsn()
        return cls(
            backend=backend,
            sqlite_database_path=Path(
                os.environ.get("CUSTOMER_API_SQLITE_PATH", base / "customers.db")
            ),
            backup_directory=Path(
                os.environ.get("CUSTOMER_API_BACKUP_DIR", base / "backups")
            ),
            attachment_directory=Path(
                os.environ.get("CUSTOMER_API_ATTACHMENT_DIR", base / "attachments")
            ),
            schema_path=Path(
                os.environ.get("CUSTOMER_API_SCHEMA_PATH", base / "schema.sql")
            ),
            seed_path=Path(
                os.environ.get("CUSTOMER_API_SEED_PATH", base / "seed.sql")
            ),
            postgres_dsn=dsn,
            session_ttl_seconds=_positive_int(
                os.environ.get("CUSTOMER_API_SESSION_SECONDS"),
                8 * 60 * 60,
                minimum=15 * 60,
                maximum=7 * 24 * 60 * 60,
            ),
            max_page_size=_positive_int(
                os.environ.get("CUSTOMER_API_MAX_PAGE_SIZE"),
                500,
                minimum=20,
                maximum=2000,
            ),
            max_attachment_size_bytes=_positive_int(
                os.environ.get("CUSTOMER_API_MAX_ATTACHMENT_BYTES"),
                50 * 1024 * 1024,
                minimum=1024 * 1024,
                maximum=500 * 1024 * 1024,
            ),
        )
