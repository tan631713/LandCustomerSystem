"""Create and maintain compressed PostgreSQL + attachment backups."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from customer_api.config import ApiSettings
from customer_api.data_sources import create_data_source
from customer_api.local_postgres import load_postgres_dsn


BACKUP_PREFIX = "land-customer-postgresql-"
MINIMUM_BACKUPS_TO_KEEP = 3


def default_backup_directory() -> Path:
    configured = os.environ.get("CUSTOMER_API_POSTGRES_BACKUP_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return (root / "LandCustomerSystem" / "postgres-backups").resolve()


def find_postgresql_tool(name: str) -> Path:
    executable_name = f"{name}.exe" if os.name == "nt" else name
    discovered = shutil.which(executable_name) or shutil.which(name)
    if discovered:
        return Path(discovered).resolve()
    if os.name == "nt":
        base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
        candidates = sorted(base.glob(f"*/bin/{executable_name}"), reverse=True)
        if candidates:
            return candidates[0].resolve()
    raise FileNotFoundError(f"找不到 PostgreSQL 工具：{executable_name}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def list_backups(directory: Path | str | None = None) -> list[Path]:
    root = Path(directory or default_backup_directory()).resolve()
    if not root.exists():
        return []
    return sorted(root.glob(f"{BACKUP_PREFIX}*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)


def backup_status(directory: Path | str | None = None) -> dict:
    root = Path(directory or default_backup_directory()).resolve()
    backups = list_backups(root)
    return {
        "status": "ok" if backups else "warning",
        "backup_directory": str(root),
        "backup_count": len(backups),
        "latest_backup": str(backups[0]) if backups else "",
        "latest_backup_at": (
            datetime.fromtimestamp(backups[0].stat().st_mtime, timezone.utc).isoformat()
            if backups
            else ""
        ),
        "total_bytes": sum(path.stat().st_size for path in backups),
    }


def _pg_dump_command(tool: Path, connection: dict, output_path: Path) -> list[str]:
    command = [str(tool), "--format=custom", "--compress=9", "--no-password", "--file", str(output_path)]
    options = (
        ("host", "--host"),
        ("port", "--port"),
        ("user", "--username"),
        ("dbname", "--dbname"),
    )
    for key, flag in options:
        value = str(connection.get(key) or "").strip()
        if value:
            command.extend([flag, value])
    return command


def _run_pg_dump(output_path: Path, dsn: str) -> dict:
    connection = conninfo_to_dict(dsn)
    pg_dump = find_postgresql_tool("pg_dump")
    environment = os.environ.copy()
    password = str(connection.get("password") or "")
    if password:
        environment["PGPASSWORD"] = password
    completed = subprocess.run(
        _pg_dump_command(pg_dump, connection, output_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=30 * 60,
        check=False,
    )
    environment.pop("PGPASSWORD", None)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "pg_dump 執行失敗"
        raise RuntimeError(message)
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("PostgreSQL 備份檔未正確建立")

    pg_restore = find_postgresql_tool("pg_restore")
    verified = subprocess.run(
        [str(pg_restore), "--list", str(output_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10 * 60,
        check=False,
    )
    if verified.returncode != 0 or not verified.stdout.strip():
        raise RuntimeError(verified.stderr.strip() or "PostgreSQL 備份驗證失敗")
    return {
        "database_dump_bytes": output_path.stat().st_size,
        "database_dump_sha256": sha256_file(output_path),
        "database_object_count": sum(1 for line in verified.stdout.splitlines() if line and not line.startswith(";")),
        "pg_dump": str(pg_dump),
    }


def _add_attachments(archive: zipfile.ZipFile, attachment_directory: Path) -> tuple[int, int]:
    if not attachment_directory.exists():
        return 0, 0
    root = attachment_directory.resolve()
    count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        archive.write(resolved, Path("attachments") / relative)
        count += 1
        total_bytes += resolved.stat().st_size
    return count, total_bytes


def prune_backups(
    directory: Path | str | None = None,
    *,
    retention_days: int = 90,
    max_count: int = 30,
    now: datetime | None = None,
) -> list[Path]:
    backups = list_backups(directory)
    keep_count = max(MINIMUM_BACKUPS_TO_KEEP, int(max_count))
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max(0, int(retention_days)))
    deleted = []
    for index, path in enumerate(backups):
        if index < MINIMUM_BACKUPS_TO_KEEP:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        over_count = index >= keep_count
        over_age = bool(retention_days) and modified < cutoff
        if over_count or over_age:
            path.unlink()
            deleted.append(path)
    return deleted


def create_backup(
    *,
    label: str = "auto",
    directory: Path | str | None = None,
    retention_days: int = 90,
    max_count: int = 30,
) -> dict:
    os.environ["CUSTOMER_API_BACKEND"] = "postgresql"
    settings = ApiSettings.from_env()
    source = create_data_source(settings)
    health = source.health()
    if health.get("status") != "ok" or health.get("backend") != "postgresql":
        raise RuntimeError("PostgreSQL 健康檢查未通過，未建立備份")
    dsn = settings.postgres_dsn or load_postgres_dsn()
    if not dsn:
        raise ValueError("找不到受 Windows 保護的 PostgreSQL 連線設定")

    root = Path(directory or default_backup_directory()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    safe_label = "".join(character for character in label.lower() if character.isalnum() or character in "-_") or "manual"
    destination = root / f"{BACKUP_PREFIX}{safe_label}-{now.astimezone().strftime('%Y%m%d-%H%M%S')}.zip"
    temporary_root = Path(tempfile.mkdtemp(prefix=".staging-", dir=root)).resolve()
    try:
        dump_path = temporary_root / "database.dump"
        dump_report = _run_pg_dump(dump_path, dsn)
        manifest = {
            "format": "LandCustomerSystem PostgreSQL backup v1",
            "created_at": now.isoformat(),
            "backend": "postgresql",
            "schema_version": health.get("schema_version"),
            "record_count": health.get("record_count"),
            **dump_report,
        }
        temporary_zip = temporary_root / "backup.zip"
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(dump_path, "database.dump", compress_type=zipfile.ZIP_STORED)
            attachment_count, attachment_bytes = _add_attachments(archive, settings.attachment_directory)
            manifest["attachment_count"] = attachment_count
            manifest["attachment_bytes"] = attachment_bytes
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(temporary_zip, "r") as archive:
            if archive.testzip() is not None or "database.dump" not in archive.namelist():
                raise RuntimeError("ZIP 備份驗證失敗")
        temporary_zip.replace(destination)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    deleted = prune_backups(root, retention_days=retention_days, max_count=max_count, now=now)
    return {
        "status": "ok",
        "backup_path": str(destination),
        "backup_bytes": destination.stat().st_size,
        "record_count": health.get("record_count"),
        "attachment_count": manifest["attachment_count"],
        "deleted_old_backups": [str(path) for path in deleted],
    }


def backup_is_due(directory: Path | str | None, hours: int) -> bool:
    backups = list_backups(directory)
    if not backups:
        return True
    latest = datetime.fromtimestamp(backups[0].stat().st_mtime, timezone.utc)
    return latest < datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="備份土地資料系統 PostgreSQL 與附件")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--label", default="manual")
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--max-count", type=int, default=30)
    parser.add_argument("--if-due-hours", type=int, default=0)
    parser.add_argument("--status", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.status:
        print(json.dumps(backup_status(args.directory), ensure_ascii=False, indent=2))
        return 0
    if args.if_due_hours and not backup_is_due(args.directory, args.if_due_hours):
        report = backup_status(args.directory)
        report["skipped"] = True
        report["reason"] = f"最近 {args.if_due_hours} 小時已有備份"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    report = create_backup(
        label=args.label,
        directory=args.directory,
        retention_days=args.retention_days,
        max_count=args.max_count,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
