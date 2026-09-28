"""Calls LandCustomerServer.exe's admin-recover / admin-bootstrap subcommands.

Passwords go in only via stdin JSON, never argv, never anything the caller
logs. The subprocess call itself must not be echoed anywhere (see
ui_admin.py, which clears the password Tk variables immediately after
building the payload).
"""

from __future__ import annotations

import json
import subprocess

from server_console.paths import package_root, server_executable
from server_console.process_manager import CREATE_NO_WINDOW


def _run_subcommand(subcommand: str, payload: dict) -> dict:
    exe = server_executable(package_root())
    try:
        result = subprocess.run(
            [str(exe), subcommand],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "操作逾時，未確認是否完成，請檢查伺服器狀態。"}
    except OSError as exc:
        return {"status": "error", "message": f"無法執行 LandCustomerServer.exe：{exc}"}

    text = (result.stdout or "").strip() or (result.stderr or "").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {
            "status": "error",
            "message": "子命令沒有回覆可解析的結果，請查看日誌分頁。",
        }


def recover_admin_password(verify_username: str, verify_password: str, new_password: str) -> dict:
    return _run_subcommand(
        "admin-recover",
        {
            "verify_username": verify_username,
            "verify_password": verify_password,
            "new_password": new_password,
        },
    )


def bootstrap_first_admin(password: str) -> dict:
    return _run_subcommand("admin-bootstrap", {"password": password})
