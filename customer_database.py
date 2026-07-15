"""SQLite connection, backup, validation, and restore services."""

import os
import secrets
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SQLITE_TIMEOUT_SECONDS = 10
SQLITE_BUSY_TIMEOUT_MS = SQLITE_TIMEOUT_SECONDS * 1000
AUTO_BACKUP_LIMIT = 14
DEFAULT_BACKUP_RETENTION_DAYS = 90
DEFAULT_BACKUP_MAX_COUNT = 30
MINIMUM_BACKUPS_TO_KEEP = 3


@dataclass(frozen=True)
class BackupMaintenanceResult:
    compressed_count: int = 0
    deleted_count: int = 0
    reclaimed_bytes: int = 0
    failed_paths: tuple = ()


class ClosingSQLiteConnection(sqlite3.Connection):
    """Commit or roll back, then always release the SQLite file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class CustomerDatabase:
    def __init__(
        self,
        database_path,
        backup_directory,
        timeout_seconds=SQLITE_TIMEOUT_SECONDS,
        auto_backup_limit=AUTO_BACKUP_LIMIT,
        compress_backups=False,
        backup_retention_days=DEFAULT_BACKUP_RETENTION_DAYS,
        backup_max_count=DEFAULT_BACKUP_MAX_COUNT,
        minimum_backups_to_keep=MINIMUM_BACKUPS_TO_KEEP,
    ):
        self.database_path = Path(database_path)
        self.backup_directory = Path(backup_directory)
        self.timeout_seconds = timeout_seconds
        self.busy_timeout_ms = int(timeout_seconds * 1000)
        self.auto_backup_limit = auto_backup_limit
        self.configure_backup_policy(
            compress_backups=compress_backups,
            retention_days=backup_retention_days,
            max_count=backup_max_count,
            minimum_to_keep=minimum_backups_to_keep,
        )

    def configure_backup_policy(
        self,
        *,
        compress_backups,
        retention_days,
        max_count,
        minimum_to_keep=MINIMUM_BACKUPS_TO_KEEP,
    ):
        self.compress_backups = bool(compress_backups)
        self.backup_retention_days = max(0, int(retention_days))
        self.minimum_backups_to_keep = max(1, int(minimum_to_keep))
        self.backup_max_count = max(self.minimum_backups_to_keep, int(max_count))

    def _open(self, path, **kwargs):
        return sqlite3.connect(
            path,
            timeout=self.timeout_seconds,
            factory=ClosingSQLiteConnection,
            **kwargs,
        )

    def connect(self):
        conn = self._open(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def validate_database_file(self, database_path, require_schema=True):
        database_path = Path(database_path)
        if not database_path.is_file():
            raise ValueError("找不到資料庫檔案。")
        if database_path.stat().st_size < 100:
            raise ValueError("資料庫檔案過小或內容不完整。")

        uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
        try:
            with self._open(uri, uri=True) as conn:
                conn.execute("PRAGMA query_only = ON")
                integrity_result = conn.execute("PRAGMA quick_check").fetchone()
                if not integrity_result or integrity_result[0] != "ok":
                    detail = integrity_result[0] if integrity_result else "unknown error"
                    raise ValueError(f"資料庫完整性檢查失敗：{detail}")

                if not require_schema:
                    return True

                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                missing_tables = {"customers", "users"} - tables
                if missing_tables:
                    raise ValueError(f"缺少必要資料表：{', '.join(sorted(missing_tables))}")

                required_columns = {
                    "customers": {"id", "district", "section", "land_number"},
                    "users": {"id", "username", "password_salt", "password_hash"},
                }
                for table_name, expected_columns in required_columns.items():
                    actual_columns = {
                        row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")
                    }
                    missing_columns = expected_columns - actual_columns
                    if missing_columns:
                        raise ValueError(
                            f"資料表 {table_name} 缺少必要欄位："
                            f"{', '.join(sorted(missing_columns))}"
                        )
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"不是有效的 SQLite 資料庫：{exc}") from exc
        return True

    def backup_database(
        self,
        label="auto",
        source_path=None,
        require_schema=True,
        compress=None,
    ):
        source_path = Path(source_path or self.database_path)
        if not source_path.exists():
            return None
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.backup_directory / f"customers-{label}-{timestamp}.db"
        counter = 1
        while backup_path.exists() or backup_path.with_suffix(".zip").exists():
            backup_path = self.backup_directory / f"customers-{label}-{timestamp}-{counter}.db"
            counter += 1

        try:
            with self._open(source_path) as source_conn, self._open(backup_path) as backup_conn:
                source_conn.backup(backup_conn)
            self.validate_database_file(backup_path, require_schema=require_schema)
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise
        should_compress = self.compress_backups if compress is None else bool(compress)
        if should_compress:
            backup_path = self.compress_backup(backup_path)
        return backup_path

    def list_backup_files(self, *, label=None):
        if not self.backup_directory.exists():
            return []
        label_part = f"{label}-" if label else ""
        paths = [
            *self.backup_directory.glob(f"customers-{label_part}*.db"),
            *self.backup_directory.glob(f"customers-{label_part}*.zip"),
        ]
        return sorted(
            {path for path in paths if path.is_file()},
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def compress_backup(self, database_path, *, remove_source=True):
        database_path = Path(database_path)
        if database_path.suffix.lower() != ".db":
            raise ValueError("只能壓縮 .db 備份檔。")
        self.validate_database_file(database_path)
        archive_path = database_path.with_suffix(".zip")
        temporary_path = archive_path.with_name(
            f".{archive_path.name}.{secrets.token_hex(6)}.tmp"
        )
        try:
            with zipfile.ZipFile(
                temporary_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                archive.write(database_path, arcname=database_path.name)
            self.validate_backup_file(temporary_path, expected_suffix=".zip")
            os.replace(temporary_path, archive_path)
            if remove_source:
                database_path.unlink()
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return archive_path

    def _extract_archive_database(self, archive_path):
        archive_path = Path(archive_path)
        extracted_path = self.database_path.with_name(
            f".{self.database_path.name}.archive-{secrets.token_hex(8)}.db"
        )
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP 備份檔已損壞。")
                members = [info for info in archive.infolist() if not info.is_dir()]
                if len(members) != 1:
                    raise ValueError("ZIP 備份必須只包含一個資料庫檔案。")
                member = members[0]
                member_path = Path(member.filename)
                if member_path.name != member.filename or member_path.suffix.lower() != ".db":
                    raise ValueError("ZIP 備份內的資料庫檔案格式不正確。")
                with archive.open(member, "r") as source, extracted_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
            self.validate_database_file(extracted_path)
        except (OSError, zipfile.BadZipFile) as exc:
            extracted_path.unlink(missing_ok=True)
            raise ValueError(f"無法讀取 ZIP 備份檔：{exc}") from exc
        except Exception:
            extracted_path.unlink(missing_ok=True)
            raise
        return extracted_path

    def validate_backup_file(self, backup_path, *, expected_suffix=None):
        backup_path = Path(backup_path)
        suffix = expected_suffix or backup_path.suffix.lower()
        if suffix == ".db":
            return self.validate_database_file(backup_path)
        if suffix != ".zip":
            raise ValueError("備份檔必須是 .db 或 .zip 格式。")
        extracted_path = self._extract_archive_database(backup_path)
        extracted_path.unlink(missing_ok=True)
        return True

    def restore_database(self, source_path):
        source_path = Path(source_path)
        extracted_path = None
        if source_path.suffix.lower() == ".zip":
            extracted_path = self._extract_archive_database(source_path)
            restore_source_path = extracted_path
        elif source_path.suffix.lower() == ".db":
            self.validate_database_file(source_path)
            restore_source_path = source_path
        else:
            raise ValueError("備份檔必須是 .db 或 .zip 格式。")
        safety_backup_path = self.backup_database("restore-before")
        restore_path = self.database_path.with_name(
            f".{self.database_path.name}.restore-{secrets.token_hex(8)}.tmp"
        )

        try:
            with self._open(restore_source_path) as source_conn, self._open(restore_path) as restore_conn:
                source_conn.backup(restore_conn)
            self.validate_database_file(restore_path)
            os.replace(restore_path, self.database_path)
        except Exception:
            restore_path.unlink(missing_ok=True)
            raise
        finally:
            if extracted_path is not None:
                extracted_path.unlink(missing_ok=True)
        return safety_backup_path

    def prune_auto_backups(self, limit=None):
        limit = self.auto_backup_limit if limit is None else limit
        if not self.backup_directory.exists():
            return
        backups = self.list_backup_files(label="auto")
        for backup_path in backups[limit:]:
            try:
                backup_path.unlink()
            except OSError:
                pass

    def compress_existing_backups(self):
        compressed_count = 0
        reclaimed_bytes = 0
        failed_paths = []
        if not self.backup_directory.exists():
            return BackupMaintenanceResult()
        for backup_path in self.list_backup_files():
            if backup_path.suffix.lower() != ".db":
                continue
            try:
                original_size = backup_path.stat().st_size
                archive_path = self.compress_backup(backup_path)
                reclaimed_bytes += max(0, original_size - archive_path.stat().st_size)
                compressed_count += 1
            except (OSError, ValueError, sqlite3.DatabaseError):
                failed_paths.append(backup_path)
        return BackupMaintenanceResult(
            compressed_count=compressed_count,
            reclaimed_bytes=reclaimed_bytes,
            failed_paths=tuple(failed_paths),
        )

    def prune_backups(self, *, retention_days=None, max_count=None, now=None):
        retention_days = (
            self.backup_retention_days if retention_days is None else max(0, int(retention_days))
        )
        max_count = self.backup_max_count if max_count is None else max(0, int(max_count))
        max_count = max(self.minimum_backups_to_keep, max_count)
        now = now or datetime.now()
        cutoff_timestamp = (
            now.timestamp() - retention_days * 24 * 60 * 60 if retention_days else None
        )
        backups = self.list_backup_files()
        protected = set(backups[: self.minimum_backups_to_keep])
        deleted_count = 0
        reclaimed_bytes = 0
        failed_paths = []
        for index, backup_path in enumerate(backups):
            try:
                stat_result = backup_path.stat()
                expired = bool(
                    cutoff_timestamp is not None
                    and stat_result.st_mtime < cutoff_timestamp
                )
                exceeds_count = index >= max_count
                if backup_path in protected or not (expired or exceeds_count):
                    continue
                self.validate_backup_file(backup_path)
                file_size = stat_result.st_size
                backup_path.unlink()
                reclaimed_bytes += file_size
                deleted_count += 1
            except (OSError, ValueError, sqlite3.DatabaseError):
                failed_paths.append(backup_path)
        return BackupMaintenanceResult(
            deleted_count=deleted_count,
            reclaimed_bytes=reclaimed_bytes,
            failed_paths=tuple(failed_paths),
        )

    def run_backup_maintenance(self, *, compress_existing=None):
        should_compress = (
            self.compress_backups if compress_existing is None else bool(compress_existing)
        )
        compression = self.compress_existing_backups() if should_compress else BackupMaintenanceResult()
        pruning = self.prune_backups()
        return BackupMaintenanceResult(
            compressed_count=compression.compressed_count,
            deleted_count=pruning.deleted_count,
            reclaimed_bytes=compression.reclaimed_bytes + pruning.reclaimed_bytes,
            failed_paths=tuple((*compression.failed_paths, *pruning.failed_paths)),
        )

    def ensure_daily_backup(self):
        if not self.database_path.exists():
            return None
        today = datetime.now().strftime("%Y%m%d")
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        existing = [
            *self.backup_directory.glob(f"customers-auto-{today}-*.db"),
            *self.backup_directory.glob(f"customers-auto-{today}-*.zip"),
        ]
        if existing:
            self.run_backup_maintenance()
            return None
        backup_path = self.backup_database("auto")
        self.run_backup_maintenance()
        return backup_path
