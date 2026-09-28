"""Drives the existing --import-migration-package CLI flag from the console.

customer_migration_package.import_migration_package() needs four values
that start_api_server.py's existing interactive flow collects with
input()/getpass.getpass(): source_username, source_password,
server_username, server_password. Rather than restart
home_server_runtime.ps1 -NonInteractive (which cannot answer those
prompts and, since this session's ps1 change, refuses to try -- see the
inventory report), the console calls the exe directly and feeds the four
answers through stdin in the exact order the existing prompts expect.
subprocess.run's `input=` sends them all at once, so there is no pipe
deadlock to worry about.

The existing code path is not changed at all: this only automates typing
into the same prompts a person would answer by hand.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from server_console.paths import package_root, server_executable
from server_console.process_manager import CREATE_NO_WINDOW

PACKAGE_SUFFIX = ".lcs-migration.zip"


def validate_package_file(path: Path) -> str | None:
    """Return an error message, or None if the file looks importable."""

    if path.suffix != ".zip" or not path.name.lower().endswith(PACKAGE_SUFFIX):
        return f"遷移包必須使用 {PACKAGE_SUFFIX} 副檔名。"
    try:
        with path.open("rb") as stream:
            stream.read(4)
    except OSError as exc:
        return f"無法讀取此檔案：{exc}"
    return None


def stage_package_copy(source: Path) -> Path:
    """Copy the selected file next to the exe, matching the ps1's own
    *.lcs-migration.zip detection rule, so a failed console attempt still
    leaves a file the old bat flow could pick up if asked to."""

    destination = package_root() / source.name
    if destination.resolve() != source.resolve():
        shutil.copy2(source, destination)
    return destination


def _extract_json(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except (json.JSONDecodeError, ValueError):
        return None


def import_migration_package(
    staged_path: Path,
    *,
    source_username: str,
    source_password: str,
    server_username: str,
    server_password: str,
) -> dict:
    exe = server_executable(package_root())
    stdin_text = "\n".join(
        [source_username, source_password, server_username, server_password, ""]
    )
    try:
        result = subprocess.run(
            [str(exe), "--postgres", "--import-migration-package", str(staged_path)],
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "匯入逾時，請檢查診斷檔與伺服器狀態。"}
    except OSError as exc:
        return {"status": "error", "message": f"無法執行 LandCustomerServer.exe：{exc}"}

    parsed = _extract_json(result.stderr or "") or _extract_json(result.stdout or "")
    if parsed is None:
        return {"status": "error", "message": "匯入工具沒有回覆可解析的結果，請查看日誌分頁。"}
    return parsed


def cleanup_staged_copy(staged_path: Path) -> None:
    try:
        staged_path.unlink(missing_ok=True)
    except OSError:
        pass
