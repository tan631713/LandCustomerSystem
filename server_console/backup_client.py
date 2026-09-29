"""Calls LandCustomerServer.exe's existing --backup / --backup-status flags.

No new backup format or ps1 parameter: "立即備份" reuses create_backup()
directly, exactly as the daily automatic backup step does.
"""

from __future__ import annotations

import json
import subprocess

from server_console.paths import server_command
from server_console.process_manager import CREATE_NO_WINDOW


def _run(arguments: list[str]) -> dict:
    try:
        result = subprocess.run(
            [*server_command(), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "備份逾時，請檢查伺服器與磁碟空間。"}
    except OSError as exc:
        return {"status": "error", "message": f"無法執行伺服器程式：{exc}"}
    text = (result.stdout or "").strip() or (result.stderr or "").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"status": "error", "message": "備份工具沒有回覆可解析的結果。"}


def backup_now(label: str = "console-manual") -> dict:
    return _run(["--postgres", "--backup", "--backup-label", label])


def backup_status() -> dict:
    return _run(["--postgres", "--backup-status"])
