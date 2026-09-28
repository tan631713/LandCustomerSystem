"""Shared filesystem locations.

Mirrors exactly how 啟動家中伺服器.bat resolves -PackageRoot / -SupportRoot,
so the console launches home_server_runtime.ps1 the same way the existing
bat file does. See 啟動家中伺服器.bat for the reference implementation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
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


def console_log_directory() -> Path:
    return local_app_data() / "LandCustomerSystem" / "logs"


def home_server_runtime_script(root: Path | None = None) -> Path:
    return support_root(root) / "home_server_runtime.ps1"


def server_executable(root: Path | None = None) -> Path:
    root = root or package_root()
    return root / "LandCustomerServer" / "LandCustomerServer.exe"


def backup_directory() -> Path:
    return local_app_data() / "LandCustomerSystem" / "postgres-backups"
