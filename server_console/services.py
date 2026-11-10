"""Live Windows-side facts the diagnostics file cannot give while the server is
stopped: the PostgreSQL service state and who owns port 8732.

Everything here shells out to built-in Windows tools (sc.exe, netstat.exe)
or reads the service registry key; nothing touches PostgreSQL itself.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
import winreg

from server_console.process_manager import CREATE_NO_WINDOW

_SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"
_STATE_PATTERN = re.compile(r"\b(RUNNING|STOPPED|START_PENDING|STOP_PENDING|PAUSED|PAUSE_PENDING|CONTINUE_PENDING)\b")
_STATE_LABELS = {
    "RUNNING": "Running", "STOPPED": "Stopped", "START_PENDING": "Starting",
    "STOP_PENDING": "Stopping", "PAUSED": "Paused",
    "PAUSE_PENDING": "Pausing", "CONTINUE_PENDING": "Resuming",
}


def find_postgresql_service_name() -> str | None:
    """First installed Windows service whose name starts with 'postgresql'
    (same rule home_server_runtime.ps1 uses: Get-Service -Name 'postgresql*')."""

    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SERVICES_KEY) as services:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(services, index)
                except OSError:
                    break
                index += 1
                if name.lower().startswith("postgresql"):
                    names.append(name)
    except OSError:
        return None
    return sorted(names)[0] if names else None


def query_service_state(name: str) -> str | None:
    try:
        result = subprocess.run(
            ["sc.exe", "query", name], capture_output=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("mbcs", errors="replace")
    match = _STATE_PATTERN.search(text)
    return _STATE_LABELS.get(match.group(1)) if match else None


def port_owner_pid(port: int = 8732) -> int | None:
    try:
        result = subprocess.run(
            ["netstat.exe", "-ano", "-p", "tcp"], capture_output=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("mbcs", errors="replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


class PostgresServiceMonitor:
    """Polls the PostgreSQL service in a background thread so the Tk loop
    never waits on sc.exe. `snapshot()` is None until the first check ends."""

    def __init__(self, interval_seconds: float = 5.0):
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._snapshot: tuple[str | None, str | None] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        name = None
        while True:
            name = name or find_postgresql_service_name()
            state = query_service_state(name) if name else None
            with self._lock:
                self._snapshot = (name, state)
            time.sleep(self._interval)

    def snapshot(self) -> tuple[str | None, str | None] | None:
        with self._lock:
            return self._snapshot


class PortMonitor:
    """Probes the API port in a background thread. A closed port on Windows
    makes connect() wait out the whole timeout (~0.5 s), which froze the Tk
    loop for half of every polling second when the server was stopped.
    `is_open()` is None until the first probe ends."""

    def __init__(self, probe, interval_seconds: float = 1.0):
        self._probe = probe
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._value: bool | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            value = bool(self._probe())
            with self._lock:
                self._value = value
            time.sleep(self._interval)

    def is_open(self) -> bool | None:
        with self._lock:
            return self._value
