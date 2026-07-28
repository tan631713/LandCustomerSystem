"""Guided audit and parallel SQLite-to-PostgreSQL migration."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from customer_api.local_postgres import load_postgres_dsn
from migrate_sqlite_to_postgresql import (
    DEVICE_LOCAL_TABLES,
    ORPHAN_QUERIES,
    SOURCE_TARGET_COUNT_QUERIES,
    TARGET_TABLES,
    analyze_records,
    apply_migration,
    build_source,
    collect_source_counts,
    read_plain_records,
    verify_postgres,
)


PROJECT_DIR = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_DIR / "postgres-migration-report.json"


def write_report(payload):
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def audit_text(plan):
    return "\n".join(
        (
            f"SQLite 原始持分：{plan.source_records} 筆",
            f"預計地主：{plan.owners} 人",
            f"預計土地：{plan.lands} 筆",
            f"預計持分：{plan.ownerships} 筆",
            f"有身分證地主：{plan.owners_with_identity} 人",
            f"無身分證地主：{plan.owners_without_identity} 人",
            f"地區／地段／地號不完整：{plan.incomplete_land_keys} 筆",
        )
    )


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    username, accepted = QInputDialog.getText(
        None,
        "PostgreSQL 移轉檢查",
        "請輸入土地資料系統帳號：",
        QLineEdit.EchoMode.Normal,
        "admin",
    )
    if not accepted:
        return 1
    password, accepted = QInputDialog.getText(
        None,
        "PostgreSQL 移轉檢查",
        f"請輸入 {username.strip() or 'admin'} 的土地資料系統登入密碼：",
        QLineEdit.EchoMode.Password,
    )
    if not accepted or not password:
        return 1

    try:
        sqlite_database, repository = build_source(PROJECT_DIR / "customers.db")
        data_key = repository.authenticate_user(username.strip() or "admin", password)
        if not data_key:
            raise ValueError("土地資料系統帳號或密碼不正確")
        records = read_plain_records(repository, data_key)
        plan = analyze_records(records, data_key)
        source_counts = collect_source_counts(sqlite_database)
    except Exception as exc:
        write_report({"status": "error", "stage": "audit", "message": str(exc)})
        QMessageBox.critical(None, "檢查失敗", str(exc))
        return 1
    finally:
        password = ""

    audit = {
        "status": "audit_ok",
        "plan": asdict(plan),
        "source_counts": source_counts,
        "device_local_tables_excluded": list(DEVICE_LOCAL_TABLES),
    }
    write_report(audit)
    decision = QMessageBox.question(
        None,
        "只讀檢查完成",
        audit_text(plan)
        + "\n\n是否建立安全備份後，寫入新的本機 PostgreSQL 做平行驗證？"
        + "\n原本 SQLite 不會刪除或停用。",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if decision != QMessageBox.StandardButton.Yes:
        QMessageBox.information(
            None, "未執行移轉", "只讀檢查已完成，PostgreSQL 尚未寫入資料。"
        )
        return 0

    try:
        dsn = load_postgres_dsn()
        if not dsn:
            raise ValueError("找不到受 Windows 保護的 PostgreSQL 連線設定")
        backup_path = sqlite_database.backup_database(
            label="pre-postgresql", compress=True
        )
        result = apply_migration(sqlite_database, records, data_key, dsn)
        verification = verify_postgres(dsn)
        if verification["counts"]["ownerships"] != plan.ownerships:
            raise ValueError("PostgreSQL 持分筆數與 SQLite 不一致")
        mismatches = {
            table: {
                "sqlite": source_counts[table],
                "postgresql": verification["mirrored_source_counts"].get(table),
            }
            for table in SOURCE_TARGET_COUNT_QUERIES
            if source_counts[table]
            != verification["mirrored_source_counts"].get(table)
        }
        orphans = {
            name: count
            for name, count in verification["orphan_counts"].items()
            if count
        }
        if verification["schema_version"] < 2:
            raise ValueError("PostgreSQL schema version did not reach version 2")
        if mismatches:
            raise ValueError(
                "PostgreSQL row-count verification failed: "
                + json.dumps(mismatches, ensure_ascii=False)
            )
        if orphans:
            raise ValueError(
                "PostgreSQL relationship verification failed: "
                + json.dumps(orphans, ensure_ascii=False)
            )
        completed = {
            "status": "ok",
            "mode": "parallel_validation",
            "plan": asdict(plan),
            "result": result,
            "source_counts": source_counts,
            "verification": verification,
            "device_local_tables_excluded": list(DEVICE_LOCAL_TABLES),
            "sqlite_backup": str(backup_path),
            "sqlite_kept_as_source": True,
        }
        write_report(completed)
    except Exception as exc:
        failure = {
            "status": "error",
            "stage": "migration",
            "plan": asdict(plan),
            "source_counts": source_counts,
            "message": str(exc),
            "sqlite_kept_as_source": True,
        }
        write_report(failure)
        QMessageBox.critical(
            None,
            "移轉失敗",
            f"PostgreSQL 平行移轉未完成；原本 SQLite 未受影響。\n\n{exc}",
        )
        return 1

    QMessageBox.information(
        None,
        "平行移轉完成",
        audit_text(plan)
        + f"\n\nPostgreSQL 持分核對：{verification['counts']['ownerships']} 筆"
        + "\n原本 SQLite 仍保留為正式資料來源。",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
