"""Calls LandCustomerServer.exe's local subcommands (admin-list, admin-bootstrap,
admin-recover, migration-import).

Passwords go in only via stdin JSON, never argv, and nothing here ever
logs the payload. Every reply is one JSON object {"status", "message", ...}.
"""

from __future__ import annotations

import json
import subprocess

from server_console.paths import server_command
from server_console.process_manager import CREATE_NO_WINDOW


def _parse_reply(text: str) -> dict:
    text = (text or "").strip()
    for candidate in (text, text.splitlines()[-1] if text else ""):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"status": "error", "message": "子命令沒有回覆可解析的結果，請查看日誌分頁。"}


def _run_subcommand(subcommand: str, payload: dict | None, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            [*server_command(), subcommand],
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "操作逾時，未確認是否完成，請檢查伺服器狀態。"}
    except OSError as exc:
        return {"status": "error", "message": f"無法執行伺服器程式：{exc}"}
    return _parse_reply(result.stdout or result.stderr)


def list_admins() -> dict:
    """{"status", "account_count", "admins": [...]} — read-only."""

    return _run_subcommand("admin-list", None, timeout=30)


def bootstrap_first_admin(username: str, password: str) -> dict:
    return _run_subcommand("admin-bootstrap", {"username": username, "password": password})


def recover_admin_password(
    target_username: str, verify_username: str, verify_password: str, new_password: str
) -> dict:
    return _run_subcommand(
        "admin-recover",
        {
            "target_username": target_username,
            "verify_username": verify_username,
            "verify_password": verify_password,
            "new_password": new_password,
        },
    )


def import_migration_package(
    package: str,
    source_username: str,
    source_password: str,
    server_username: str = "",
    server_password: str = "",
) -> dict:
    return _run_subcommand(
        "migration-import",
        {
            "package": package,
            "source_username": source_username,
            "source_password": source_password,
            "server_username": server_username,
            "server_password": server_password,
        },
        timeout=900,
    )
