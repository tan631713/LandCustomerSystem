"""Small local GUI for the one-time PostgreSQL application setup."""

from __future__ import annotations

import json
import sys

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from setup_local_postgresql import REPORT_PATH, setup_database


def write_report(payload):
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    password, accepted = QInputDialog.getText(
        None,
        "設定本機 PostgreSQL",
        "請輸入安裝 PostgreSQL 時設定的管理密碼：",
        QLineEdit.EchoMode.Password,
    )
    if not accepted:
        return 1
    if not password:
        QMessageBox.warning(None, "未完成", "未輸入密碼，沒有進行任何變更。")
        return 1
    try:
        result = setup_database(password)
    except Exception as exc:
        failure = {"status": "error", "message": str(exc)}
        write_report(failure)
        QMessageBox.critical(
            None,
            "設定失敗",
            f"無法建立本機 PostgreSQL 專案資料庫。\n\n{exc}",
        )
        return 1
    finally:
        password = ""
    write_report(result)
    QMessageBox.information(
        None,
        "設定完成",
        "本機 PostgreSQL 專案資料庫已建立，連線資料已由 Windows 加密保存。",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
