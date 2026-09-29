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
