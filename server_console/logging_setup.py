"""console-YYYYMMDD.log under %LOCALAPPDATA%\\LandCustomerSystem\\logs, 30-day
retention. Never receives password text -- callers only ever pass the
already-redacted status/log lines shown in the UI.
"""

from __future__ import annotations

import datetime
import logging
import logging.handlers
from pathlib import Path

from server_console.paths import console_log_directory


def _prune_old_logs(directory: Path, keep_days: int = 30) -> None:
    cutoff = datetime.datetime.now().timestamp() - keep_days * 86400
    try:
        for entry in directory.glob("console-*.log"):
            if entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
    except OSError:
        pass


def build_logger() -> logging.Logger:
    directory = console_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    _prune_old_logs(directory)
    today = datetime.date.today().strftime("%Y%m%d")
    log_path = directory / f"console-{today}.log"

    logger = logging.getLogger("server_console")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger
