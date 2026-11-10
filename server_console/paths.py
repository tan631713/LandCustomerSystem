"""Shared filesystem locations.

Mirrors exactly how 啟動家中伺服器.bat resolves -PackageRoot / -SupportRoot,
so the console launches home_server_runtime.ps1 the same way the existing
bat file does. See 啟動家中伺服器.bat for the reference implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def package_root() -> Path:
    if is_frozen():
        # PyInstaller --onefile: sys.executable is the real exe on disk,
        # sitting next to 啟動家中伺服器.bat per the packaging spec.
        return Path(sys.executable).resolve().parent
    # Dev/test run (plain `python -m server_console...`): the repo root is
    # one level above this package.
    return Path(__file__).resolve().parent.parent


def support_root(root: Path | None = None) -> Path:
    root = root or package_root()
    candidate = root / "_server_support"
    if (candidate / "home_server_runtime.ps1").is_file():
        return candidate
    return root


def local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Local"


def diagnostics_path() -> Path:
    return local_app_data() / "LandCustomerSystem" / "home-server-diagnostics.json"


def console_settings_path() -> Path:
    return local_app_data() / "LandCustomerSystem" / "console-settings.json"


def last_import_path() -> Path:
    # console-settings.json 依規格只能存兩個選項，「上次匯入」另存一個只有
    # 時間與檔名（不含任何密碼）的檔案。
    return local_app_data() / "LandCustomerSystem" / "last-import.json"


def console_log_directory() -> Path:
    return local_app_data() / "LandCustomerSystem" / "logs"


def home_server_runtime_script(root: Path | None = None) -> Path:
    # 只有開發（未打包）時才允許用環境變數換成測試用的假 ps1；打包後的
    # 系統管理員 exe 不讀這個變數，避免使用者層級的環境變數被拿來提權。
    override = os.environ.get("LCS_CONSOLE_RUNTIME_SCRIPT")
    if override and not is_frozen():
        return Path(override)
    return support_root(root) / "home_server_runtime.ps1"


def server_executable(root: Path | None = None) -> Path:
    root = root or package_root()
    packaged = root / "LandCustomerServer" / "LandCustomerServer.exe"
    if packaged.is_file() or is_frozen():
        return packaged
    dev_build = root / "dist" / "LandCustomerServer" / "LandCustomerServer.exe"
    return dev_build if dev_build.is_file() else packaged


def server_command(root: Path | None = None) -> list[str]:
    """How to run the server CLI: the packaged exe, or (dev/tests) the source
    launcher, so unit tests and dev runs exercise the current code."""

    root = root or package_root()
    if is_frozen():
        return [str(server_executable(root))]
    return [sys.executable, str(root / "start_api_server.py")]


def backup_directory() -> Path:
    return local_app_data() / "LandCustomerSystem" / "postgres-backups"
