"""Preserve deployed customer data while PyInstaller replaces dist/."""

import shutil
import sqlite3
import sys
from pathlib import Path


APP_FOLDER_NAME = "LandCustomerSystem"
STAGING_FOLDER_NAME = ".build-preserved-data"
PRESERVED_DIRECTORY_NAMES = ("backups", "logs", "attachments")


def copy_sqlite_snapshot(source, destination):
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    source_conn = sqlite3.connect(source)
    destination_conn = sqlite3.connect(destination)
    try:
        result = source_conn.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"Source database failed quick_check: {result}")
        source_conn.backup(destination_conn)
        destination_conn.commit()
        result = destination_conn.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"Copied database failed quick_check: {result}")
    finally:
        destination_conn.close()
        source_conn.close()


def save(project_root):
    project_root = Path(project_root).resolve()
    deployed = project_root / "dist" / APP_FOLDER_NAME
    staging = project_root / STAGING_FOLDER_NAME
    deployed_db = deployed / "customers.db"
    deployed_directories = [deployed / name for name in PRESERVED_DIRECTORY_NAMES]

    if staging.exists():
        raise RuntimeError(
            f"Preserved data already exists at {staging}. "
            "Do not rebuild until it has been restored or moved safely."
        )
    if not deployed_db.exists() and not any(path.exists() for path in deployed_directories):
        print("No deployed customer data to preserve.")
        return

    staging.mkdir(parents=True)
    try:
        if deployed_db.exists():
            copy_sqlite_snapshot(deployed_db, staging / "customers.db")
        for deployed_directory in deployed_directories:
            if deployed_directory.exists():
                shutil.copytree(deployed_directory, staging / deployed_directory.name)
    except Exception:
        print(f"Preserved files remain at {staging} for manual recovery.")
        raise
    print(f"Deployed customer data preserved at {staging}")


def restore(project_root):
    project_root = Path(project_root).resolve()
    deployed = project_root / "dist" / APP_FOLDER_NAME
    staging = project_root / STAGING_FOLDER_NAME
    if not staging.exists():
        print("No preserved customer data to restore.")
        return

    deployed.mkdir(parents=True, exist_ok=True)
    staged_db = staging / "customers.db"
    if staged_db.exists():
        copy_sqlite_snapshot(staged_db, deployed / "customers.db")
    for directory_name in PRESERVED_DIRECTORY_NAMES:
        staged_directory = staging / directory_name
        if staged_directory.exists():
            shutil.copytree(
                staged_directory,
                deployed / directory_name,
                dirs_exist_ok=True,
            )
    shutil.rmtree(staging)
    print("Preserved customer data restored to the rebuilt application.")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"save", "restore"}:
        print("Usage: python build_data_guard.py save|restore PROJECT_ROOT")
        return 2
    action = save if sys.argv[1] == "save" else restore
    try:
        action(sys.argv[2])
    except Exception as exc:
        print(f"Data preservation failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
