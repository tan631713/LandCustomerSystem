"""Create and import a safe standalone-SQLite migration package.

The package contains an encrypted, transactionally consistent SQLite snapshot.
It never contains a plaintext password or decrypted customer field.  Import is
allowed only into an empty PostgreSQL business database and keeps the existing
server accounts intact.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from backup_postgresql import create_backup
from customer_api.config import ApiSettings
from customer_api.postgres_source import PostgreSQLCustomerDataSource
from migrate_sqlite_to_postgresql import (
    DEVICE_LOCAL_TABLES,
    EXTENDED_SOURCE_TABLES,
    ORPHAN_QUERIES,
    SOURCE_TARGET_COUNT_QUERIES,
    analyze_records,
    apply_migration,
    build_source,
    collect_source_counts,
    read_plain_records,
    verify_postgres,
)


PACKAGE_FORMAT = "LandCustomerSystem standalone migration v1"
PACKAGE_SUFFIX = ".lcs-migration.zip"
DATABASE_MEMBER = "database/customers.db"
MANIFEST_MEMBER = "manifest.json"
ALLOWED_MEMBERS = {DATABASE_MEMBER, MANIFEST_MEMBER}
MAX_PACKAGE_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MINIMUM_POSTGRES_SCHEMA_VERSION = 3

SOURCE_COUNT_TABLES = (
    "users",
    "customers",
    "contact_logs",
    "follow_up_reminders",
    *EXTENDED_SOURCE_TABLES,
    *DEVICE_LOCAL_TABLES,
)

# These tables contain active business records or relationships.  Standalone
# owners/lands left behind after deleting the last test record are not active
# records and are cleaned inside the migration transaction.  Recycle-bin and
# operation-log history are preserved and do not block the first import.
TARGET_MUST_BE_EMPTY = (
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
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _sqlite_integrity_check(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or str(result[0]).lower() != "ok":
        raise ValueError("SQLite 資料庫完整性檢查失敗，未建立或匯入遷移包。")


def _sqlite_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [name for name in ("users", "customers") if name not in table_names]
        if missing:
            raise ValueError(f"單機資料庫缺少必要資料表：{'、'.join(missing)}")
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in SOURCE_COUNT_TABLES
            if table in table_names
        }


def create_sqlite_snapshot(source: Path | str, destination: Path | str) -> Path:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到單機資料庫：{source_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
        with closing(sqlite3.connect(destination_path)) as destination_connection:
            source_connection.backup(destination_connection)
    _sqlite_integrity_check(destination_path)
    return destination_path


def _normalise_destination(source: Path, destination: Path | str | None) -> Path:
    if destination is not None:
        selected = Path(destination).resolve()
        if selected.suffix.lower() == ".zip" and selected.name.lower().endswith(
            PACKAGE_SUFFIX
        ):
            return selected
        if selected.exists() and selected.is_dir():
            root = selected
        elif not selected.suffix:
            root = selected
        else:
            raise ValueError(f"遷移包檔名必須以 {PACKAGE_SUFFIX} 結尾。")
    else:
        root = source.parent
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return (root / f"LandCustomerSystem-{timestamp}{PACKAGE_SUFFIX}").resolve()


def export_migration_package(
    source: Path | str,
    destination: Path | str | None = None,
) -> dict:
    source_path = Path(source).resolve()
    destination_path = _normalise_destination(source_path, destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise FileExistsError(f"遷移包已存在，未覆蓋：{destination_path}")

    with tempfile.TemporaryDirectory(
        prefix=".lcs-migration-export-", dir=destination_path.parent
    ) as temporary:
        temporary_root = Path(temporary)
        snapshot = create_sqlite_snapshot(
            source_path, temporary_root / "database" / "customers.db"
        )
        counts = _sqlite_counts(snapshot)
        attachment_count = int(counts.get("customer_attachments", 0))
        if attachment_count:
            raise ValueError(
                "目前這個安全遷移工具不接受含附件的單機資料庫；"
                "請先保留原檔並使用附件搬移版本。"
            )
        manifest = {
            "format": PACKAGE_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database_name": source_path.name,
            "database_member": DATABASE_MEMBER,
            "database_bytes": snapshot.stat().st_size,
            "database_sha256": sha256_file(snapshot),
            "source_counts": counts,
            "attachments_supported": False,
            "attachment_count": attachment_count,
        }
        temporary_zip = temporary_root / f"migration{PACKAGE_SUFFIX}"
        with zipfile.ZipFile(
            temporary_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.write(snapshot, DATABASE_MEMBER)
            archive.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        inspect_migration_package(temporary_zip)
        temporary_zip.replace(destination_path)

    return {
        "status": "ok",
        "package_path": str(destination_path),
        "package_bytes": destination_path.stat().st_size,
        "package_sha256": sha256_file(destination_path),
        "source_counts": counts,
    }


def _validate_archive_member(info: zipfile.ZipInfo) -> None:
    member = PurePosixPath(info.filename)
    if member.is_absolute() or ".." in member.parts or "\\" in info.filename:
        raise ValueError("遷移包含有不安全的檔案路徑。")
    if info.file_size < 0 or info.file_size > MAX_PACKAGE_MEMBER_BYTES:
        raise ValueError("遷移包中的檔案超過安全大小限制。")
    if info.flag_bits & 0x1:
        raise ValueError("遷移包不可使用未知密碼加密。")


def inspect_migration_package(path: Path | str) -> dict:
    package_path = Path(path).resolve()
    if not package_path.is_file():
        raise FileNotFoundError(f"找不到遷移包：{package_path}")
    if not package_path.name.lower().endswith(PACKAGE_SUFFIX):
        raise ValueError(f"遷移包檔名必須以 {PACKAGE_SUFFIX} 結尾。")
    with zipfile.ZipFile(package_path, "r") as archive:
        infos = archive.infolist()
        for info in infos:
            _validate_archive_member(info)
        names = {info.filename for info in infos if not info.is_dir()}
        if names != ALLOWED_MEMBERS:
            raise ValueError("遷移包內容不完整或含有非預期檔案。")
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"遷移包 ZIP 驗證失敗：{damaged}")
        try:
            manifest = json.loads(archive.read(MANIFEST_MEMBER).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("遷移包清單格式錯誤。") from exc
    if manifest.get("format") != PACKAGE_FORMAT:
        raise ValueError("這不是相容的土地資料系統遷移包。")
    if manifest.get("database_member") != DATABASE_MEMBER:
        raise ValueError("遷移包資料庫位置不正確。")
    if int(manifest.get("attachment_count") or 0):
        raise ValueError("此版本不允許匯入含附件的遷移包。")
    expected_hash = str(manifest.get("database_sha256") or "").upper()
    if len(expected_hash) != 64:
        raise ValueError("遷移包缺少有效的資料庫 SHA-256。")
    return dict(manifest)


def extract_migration_package(
    package: Path | str,
    destination: Path | str,
) -> tuple[dict, Path]:
    package_path = Path(package).resolve()
    destination_root = Path(destination).resolve()
    manifest = inspect_migration_package(package_path)
    database_path = (destination_root / DATABASE_MEMBER).resolve()
    try:
        database_path.relative_to(destination_root)
    except ValueError as exc:
        raise ValueError("遷移包解壓縮位置不安全。") from exc
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        with archive.open(DATABASE_MEMBER, "r") as source, database_path.open("wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
    if database_path.stat().st_size != int(manifest.get("database_bytes") or -1):
        raise ValueError("遷移包資料庫大小與清單不一致。")
    if sha256_file(database_path) != str(manifest["database_sha256"]).upper():
        raise ValueError("遷移包資料庫 SHA-256 不一致，檔案可能已損壞。")
    _sqlite_integrity_check(database_path)
    return manifest, database_path


def _validate_target_is_empty(report: dict) -> None:
    counts = report.get("counts") or {}
    occupied = {
        table: int(counts.get(table) or 0)
        for table in TARGET_MUST_BE_EMPTY
        if int(counts.get(table) or 0) > 0
    }
    if occupied:
        detail = "、".join(f"{table}={count}" for table, count in occupied.items())
        raise ValueError(
            "家中伺服器已有有效正式業務資料，為避免覆蓋或重複匯入，操作已停止："
            + detail
        )


def _prepare_target_for_import(connection) -> dict:
    """Remove only invisible owner/land residue left by deleted test records."""

    removed_owners = int(
        connection.execute(
            """
            WITH deleted AS (
                DELETE FROM owners owner
                WHERE NOT EXISTS (
                    SELECT 1 FROM ownerships ownership
                    WHERE ownership.owner_id = owner.id
                )
                RETURNING id
            )
            SELECT COUNT(*) FROM deleted
            """
        ).fetchone()[0]
    )
    removed_lands = int(
        connection.execute(
            """
            WITH deleted AS (
                DELETE FROM lands land
                WHERE NOT EXISTS (
                    SELECT 1 FROM ownerships ownership
                    WHERE ownership.land_id = land.id
                )
                RETURNING id
            )
            SELECT COUNT(*) FROM deleted
            """
        ).fetchone()[0]
    )
    return {
        "removed_orphan_owners": removed_owners,
        "removed_orphan_lands": removed_lands,
        "recycle_bin_preserved": True,
        "operation_logs_preserved": True,
    }


def _verify_connection_counts(connection, source_counts: dict) -> dict:
    schema_version = int(
        connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    )
    if schema_version < MINIMUM_POSTGRES_SCHEMA_VERSION:
        raise RuntimeError("PostgreSQL 結構版本過舊，遷移已回滾。")

    mirrored = {}
    mismatches = {}
    for source_table, query in SOURCE_TARGET_COUNT_QUERIES.items():
        if source_table == "users":
            continue
        actual = int(connection.execute(query).fetchone()[0])
        expected = int(source_counts.get(source_table) or 0)
        mirrored[source_table] = actual
        if actual != expected:
            mismatches[source_table] = {"expected": expected, "actual": actual}
    orphans = {
        name: int(connection.execute(query).fetchone()[0])
        for name, query in ORPHAN_QUERIES.items()
    }
    orphans = {name: count for name, count in orphans.items() if count}
    if mismatches or orphans:
        raise RuntimeError(
            "遷移後驗證失敗，資料庫交易已回滾："
            + json.dumps(
                {"count_mismatches": mismatches, "orphans": orphans},
                ensure_ascii=False,
            )
        )
    return {
        "schema_version": schema_version,
        "mirrored_source_counts": mirrored,
        "orphan_counts": {},
    }


def _validate_final_report(report: dict, source_counts: dict) -> None:
    if int(report.get("schema_version") or 0) < MINIMUM_POSTGRES_SCHEMA_VERSION:
        raise RuntimeError("遷移後 PostgreSQL 結構版本驗證失敗。")
    mismatches = {}
    mirrored = report.get("mirrored_source_counts") or {}
    for source_table in SOURCE_TARGET_COUNT_QUERIES:
        if source_table == "users":
            continue
        expected = int(source_counts.get(source_table) or 0)
        actual = int(mirrored.get(source_table) or 0)
        if actual != expected:
            mismatches[source_table] = {"expected": expected, "actual": actual}
    orphans = {
        name: int(count)
        for name, count in (report.get("orphan_counts") or {}).items()
        if int(count)
    }
    if mismatches or orphans:
        raise RuntimeError(
            "遷移完成後的第二次驗證失敗："
            + json.dumps(
                {"count_mismatches": mismatches, "orphans": orphans},
                ensure_ascii=False,
            )
        )


def import_migration_package(
    package: Path | str,
    dsn: str,
    *,
    source_username: str,
    source_password: str,
    server_username: str,
    server_password: str,
    backup_creator=create_backup,
) -> dict:
    """Import one package while preserving server users and their passwords."""

    if not str(dsn or "").strip():
        raise ValueError("找不到家中伺服器 PostgreSQL 連線設定。")
    with tempfile.TemporaryDirectory(prefix="lcs-migration-import-") as temporary:
        manifest, database_path = extract_migration_package(package, temporary)
        sqlite_database, repository = build_source(database_path)
        source_counts = collect_source_counts(sqlite_database)
        manifest_counts = {
            str(name): int(value)
            for name, value in (manifest.get("source_counts") or {}).items()
        }
        if source_counts != manifest_counts:
            raise ValueError("遷移包資料筆數與建立時清單不一致，未匯入。")
        if int(source_counts.get("customer_attachments") or 0):
            raise ValueError("此版本不允許匯入含附件的單機資料。")

        source_data_key = repository.authenticate_user(
            str(source_username).strip(), source_password
        )
        if not source_data_key:
            raise ValueError("單機版帳號或密碼錯誤，未匯入任何資料。")
        records = read_plain_records(repository, source_data_key)

        target_source = PostgreSQLCustomerDataSource(
            ApiSettings(backend="postgresql", postgres_dsn=str(dsn))
        )
        server_user = target_source.authenticate(
            str(server_username).strip(), server_password
        )
        if not server_user:
            raise ValueError("家中伺服器帳號或密碼錯誤，未匯入任何資料。")
        if server_user.role != "admin":
            raise PermissionError("遷移必須使用家中伺服器的管理員帳號。")

        initial_report = verify_postgres(dsn)
        _validate_target_is_empty(initial_report)
        backup = backup_creator(label="pre-migration")
        if backup.get("status") != "ok" or not backup.get("backup_path"):
            raise RuntimeError("匯入前 PostgreSQL 備份未完成，遷移已停止。")

        plan = analyze_records(records, server_user.data_key)
        result = apply_migration(
            sqlite_database,
            records,
            source_data_key,
            dsn,
            copy_users=False,
            target_data_key=server_user.data_key,
            before_migration_callback=_prepare_target_for_import,
            verification_callback=lambda connection: _verify_connection_counts(
                connection, source_counts
            ),
        )
        final_report = verify_postgres(dsn)
        _validate_final_report(final_report, source_counts)
    return {
        "status": "ok",
        "package": str(Path(package).resolve()),
        "server_accounts_preserved": True,
        "source_users_copied": False,
        "pre_migration_backup": str(backup["backup_path"]),
        "plan": asdict(plan),
        "result": result,
        "verification": final_report,
    }
