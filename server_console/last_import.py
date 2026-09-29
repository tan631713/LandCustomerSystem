"""「上次匯入」：只記錄時間與檔名，不含任何帳號或密碼。"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from server_console.paths import last_import_path


def save_last_import(package_name: str, path: Path | None = None) -> None:
    path = path or last_import_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "package_name": str(package_name),
        "imported_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_last_import_text(path: Path | None = None) -> str:
    path = path or last_import_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        stamp = datetime.datetime.fromisoformat(str(payload["imported_at"]))
        return f"{stamp:%Y-%m-%d %H:%M} · {payload.get('package_name') or ''}".rstrip(" ·")
    except (OSError, ValueError, KeyError, TypeError):
        return "—"
