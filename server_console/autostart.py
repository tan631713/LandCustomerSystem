"""Per-user "start on login" toggle via HKCU Run (no admin rights needed to
write it, even though the console process itself runs elevated once
started). Reversible: turning the setting off removes the value.
"""

from __future__ import annotations

import sys
import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "LandCustomerServerConsole"


def _console_command() -> str:
    if getattr(sys, "frozen", False):
        exe = sys.executable
    else:
        exe = sys.executable  # dev run: best effort, not the packaged path
    return f'"{exe}" --auto-start'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _console_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
