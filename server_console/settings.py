"""console-settings.json: only the two options the spec allows to persist.

Never store account names, passwords, or anything else here -- the spec is
explicit that this file holds only auto_restart and auto_start_on_login.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from server_console.paths import console_settings_path


@dataclass
class ConsoleSettings:
    auto_restart: bool = True
    auto_start_on_login: bool = False


def load_settings(path: Path | None = None) -> ConsoleSettings:
    path = path or console_settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ConsoleSettings()
    if not isinstance(raw, dict):
        return ConsoleSettings()
    return ConsoleSettings(
        auto_restart=bool(raw.get("auto_restart", True)),
        auto_start_on_login=bool(raw.get("auto_start_on_login", False)),
    )


def save_settings(settings: ConsoleSettings, path: Path | None = None) -> None:
    path = path or console_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
