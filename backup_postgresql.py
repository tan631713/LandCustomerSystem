"""Create and maintain compressed PostgreSQL + attachment backups."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
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
RESTORE_CONFIRMATION = "還原家中伺服器"


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


def resolve_backup_file(
    backup_name: str, directory: Path | str | None = None
) -> Path:
    root = Path(directory or default_backup_directory()).resolve()
    name = str(backup_name or "").strip()
    if not name or Path(name).name != name:
        raise ValueError("備份名稱格式不正確")
    if not name.startswith(BACKUP_PREFIX) or not name.lower().endswith(".zip"):
        raise ValueError("不是土地資料系統 PostgreSQL 備份")
    selected = (root / name).resolve()
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise ValueError("備份路徑超出伺服器備份資料夾") from exc
    if not selected.is_file():
        raise FileNotFoundError(f"找不到伺服器備份：{name}")
    return selected


def _backup_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
        if "database.dump" not in names or "manifest.json" not in names:
            raise ValueError("備份缺少 database.dump 或 manifest.json")
        if archive.testzip() is not None:
            raise ValueError("ZIP 備份內容已損壞")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if manifest.get("format") != "LandCustomerSystem PostgreSQL backup v1":
        raise ValueError("不支援的 PostgreSQL 備份格式")
    return dict(manifest)


def backup_inventory(directory: Path | str | None = None) -> list[dict]:
    items = []
    for path in list_backups(directory):
        try:
            manifest = _backup_manifest(path)
            status = "ok"
            error = ""
        except Exception as exc:
            manifest = {}
            status = "error"
            error = str(exc)
        items.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
                "created_at": str(manifest.get("created_at") or ""),
                "record_count": int(manifest.get("record_count") or 0),
                "attachment_count": int(manifest.get("attachment_count") or 0),
                "schema_version": int(manifest.get("schema_version") or 0),
                "status": status,
                "error": error,
            }
        )
    return items


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


def _pg_restore_command(tool: Path, connection: dict, dump_path: Path) -> list[str]:
    command = [
        str(tool),
        "--clean",
        "--if-exists",
        "--single-transaction",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        "--no-password",
    ]
    for key, flag in (
        ("host", "--host"),
        ("port", "--port"),
        ("user", "--username"),
        ("dbname", "--dbname"),
    ):
        value = str(connection.get(key) or "").strip()
        if value:
            command.extend([flag, value])
    command.append(str(dump_path))
    return command


def _run_pg_restore(dump_path: Path, dsn: str) -> None:
    connection = conninfo_to_dict(dsn)
    pg_restore = find_postgresql_tool("pg_restore")
    environment = os.environ.copy()
    password = str(connection.get("password") or "")
    if password:
        environment["PGPASSWORD"] = password
    completed = subprocess.run(
        _pg_restore_command(pg_restore, connection, dump_path),
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
        message = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "pg_restore 執行失敗"
        )
        raise RuntimeError(message)


def _extract_restore_archive(path: Path, temporary_root: Path) -> tuple[Path, Path, dict]:
    dump_path = temporary_root / "database.dump"
    attachment_root = temporary_root / "attachments"
    attachment_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as archive:
        manifest = _backup_manifest(path)
        with archive.open("database.dump", "r") as source, dump_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        for info in archive.infolist():
            pure = Path(info.filename.replace("/", os.sep))
            parts = pure.parts
            if not parts or parts[0] != "attachments":
                continue
            if pure.is_absolute() or ".." in parts:
                raise ValueError("附件備份包含不安全路徑")
            file_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(file_mode):
                raise ValueError("附件備份不可包含符號連結")
            relative = Path(*parts[1:])
            destination = (attachment_root / relative).resolve()
            try:
                destination.relative_to(attachment_root.resolve())
            except ValueError as exc:
                raise ValueError("附件備份路徑超出還原暫存區") from exc
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    expected_hash = str(manifest.get("database_dump_sha256") or "").upper()
    if not expected_hash or sha256_file(dump_path) != expected_hash:
        raise ValueError("資料庫備份 SHA-256 驗證失敗")
    return dump_path, attachment_root, manifest


def _replace_attachments(restored_root: Path, attachment_directory: Path) -> None:
    destination = attachment_directory.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".restore-attachments-", dir=destination.parent)
    ).resolve()
    replacement = staging / "new"
    previous = staging / "previous"
    shutil.copytree(restored_root, replacement)
    moved_previous = False
    try:
        if destination.exists():
            destination.replace(previous)
            moved_previous = True
        replacement.replace(destination)
    except Exception:
        if moved_previous and previous.exists() and not destination.exists():
            previous.replace(destination)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore_backup(
    backup_name: str,
    *,
    confirmation: str,
    directory: Path | str | None = None,
) -> dict:
    if str(confirmation or "").strip() != RESTORE_CONFIRMATION:
        raise ValueError(f"請完整輸入確認文字：{RESTORE_CONFIRMATION}")
    selected = resolve_backup_file(backup_name, directory)
    safety = create_backup(label="pre-restore", directory=directory)
    settings = ApiSettings.from_env()
    dsn = settings.postgres_dsn or load_postgres_dsn()
    if not dsn:
        raise ValueError("找不到受 Windows 保護的 PostgreSQL 連線設定")
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".restore-", dir=selected.parent)
    ).resolve()
    try:
        dump_path, attachment_root, manifest = _extract_restore_archive(
            selected, temporary_root
        )
        _run_pg_restore(dump_path, dsn)
        from customer_api.postgres_schema import ensure_postgres_schema

        schema_version = ensure_postgres_schema(dsn)
        _replace_attachments(attachment_root, settings.attachment_directory)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return {
        "status": "ok",
        "restored_backup": selected.name,
        "restored_record_count": int(manifest.get("record_count") or 0),
        "restored_attachment_count": int(manifest.get("attachment_count") or 0),
        "schema_version": int(schema_version),
        "safety_backup": str(safety.get("backup_path") or ""),
        "session_reset": True,
    }


def validate_backup_target_path(
    directory_path: Path | str, *, backup_directory: Path | str | None = None
) -> Path:
    raw = str(directory_path or "").strip()
    if not raw:
        raise ValueError("異地備份資料夾不可空白")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("請輸入家中主機上的完整路徑，例如 E:\\土地備份")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise ValueError("家中主機找不到這個資料夾，請先建立或掛載 NAS")
    if resolved == Path(backup_directory or default_backup_directory()).resolve():
        raise ValueError("異地目的地不可與家中主備份資料夾相同")
    return resolved


def sync_backup_targets(
    targets: list[dict],
    *,
    directory: Path | str | None = None,
    retention_days: int = 90,
    max_count: int = 30,
) -> dict:
    enabled = [dict(target) for target in targets if bool(target.get("enabled"))]
    if not enabled:
        raise ValueError("尚未設定啟用的異地備份目的地")
    backup = create_backup(
        label="offsite",
        directory=directory,
        retention_days=retention_days,
        max_count=max_count,
    )
    source = Path(backup["backup_path"]).resolve()
    source_hash = sha256_file(source)
    results = []
    for target in enabled:
        try:
            root = validate_backup_target_path(
                target.get("directory_path"), backup_directory=directory
            )
            destination = root / source.name
            temporary = root / f".{source.name}.tmp"
            shutil.copy2(source, temporary)
            if sha256_file(temporary) != source_hash:
                raise OSError("複製後 SHA-256 驗證不一致")
            temporary.replace(destination)
            results.append(
                {
                    "id": int(target["id"]),
                    "name": str(target.get("name") or ""),
                    "status": "success",
                    "destination": str(destination),
                    "error": "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": int(target["id"]),
                    "name": str(target.get("name") or ""),
                    "status": "error",
                    "destination": "",
                    "error": str(exc),
                }
            )
    return {**backup, "source_sha256": source_hash, "results": results}


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
