"""Read home-server-diagnostics.json the way the spec asks for.

home_server_runtime.ps1 rewrites this file often (Save-Diagnostics runs on
every stage change). A GUI poll can land mid-write and see a truncated or
empty file. Rather than block the Tk mainloop with a sleep-and-retry loop,
DiagnosticsReader just keeps the last good parse and lets the *next*
periodic poll (driven by the caller, typically every ~1s) pick up a fresh
read -- which is what the spec's "1 秒後重試" means in a GUI context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server_console.paths import diagnostics_path

# The 7 canonical startup stages, in display order. home_server_runtime.ps1's
# own "[n/M]" text is not reliable (see the inventory report: the [4/8]
# pre_upgrade_backup stage is conditional and the denominator is inconsistent
# with the final "[7/7]"), so the console drives the 7-step list from this
# fixed, machine-readable list of `stage` values instead of parsing text.
STARTUP_STAGES = (
    ("prerequisites", "檢查必要軟體"),
    ("netbird", "檢查 NetBird 私人 VPN"),
    ("windows_services", "檢查 PostgreSQL 服務與防火牆"),
    ("database", "檢查 PostgreSQL 專案資料庫"),
    ("https", "建立 HTTPS 憑證"),
    ("backup", "檢查每日備份"),
    ("server", "啟動 HTTPS 伺服器"),
)


class DiagnosticsReader:
    def __init__(self, path: Path | None = None):
        self.path = path or diagnostics_path()
        self._last_good: dict[str, Any] = {}
        self.last_error: str = ""

    def read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
            parsed = json.loads(raw)
        except FileNotFoundError:
            self.last_error = "尚未產生診斷檔。"
            return self._last_good
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.last_error = f"診斷檔暫時無法讀取（{exc}），顯示上一次結果。"
            return self._last_good
        if not isinstance(parsed, dict):
            self.last_error = "診斷檔格式不正確，顯示上一次結果。"
            return self._last_good
        self.last_error = ""
        self._last_good = parsed
        return parsed

    @property
    def last_known(self) -> dict[str, Any]:
        return self._last_good
