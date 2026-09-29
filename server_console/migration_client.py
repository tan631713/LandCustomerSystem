"""Client-side checks for a migration package before anything is sent to the
server. The actual import is admin_client.import_migration_package(), which
calls the exe's migration-import subcommand (one JSON in, one JSON out).
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_SUFFIX = ".lcs-migration.zip"


def validate_package_file(path: Path) -> str | None:
    """Return an error message, or None if the file looks importable."""

    if not path.name.lower().endswith(PACKAGE_SUFFIX):
        return f"遷移包必須使用 {PACKAGE_SUFFIX} 副檔名。"
    try:
        with path.open("rb") as stream:
            stream.read(4)
    except OSError as exc:
        return f"無法讀取此檔案：{exc}"
    return None
