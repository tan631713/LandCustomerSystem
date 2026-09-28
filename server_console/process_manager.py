"""Launches and stops home_server_runtime.ps1 as a hidden subprocess.

home_server_runtime.ps1 stays alive for the server's whole lifetime (it
invokes LandCustomerServer.exe in the foreground and blocks on it), so
"is the server running" is judged the same way the spec asks: the ps1
process this console started is still alive, AND 127.0.0.1:8732 accepts a
TCP connection. The diagnostics file's own `process_id` (only populated in
the "already running" fast path -- see the inventory report) is kept as a
fallback so Stop can still act on a server this console did not itself
start (e.g. one left running by 啟動家中伺服器.bat, or a previous console
process that was closed and reopened).
"""

from __future__ import annotations

import queue
import socket
import subprocess
import threading
import time
from pathlib import Path

from server_console.paths import home_server_runtime_script, package_root, support_root

SERVER_PORT = 8732
CREATE_NO_WINDOW = 0x08000000


class ProcessManager:
    def __init__(self):
        self._process: subprocess.Popen | None = None
        self.output_queue: "queue.Queue[str]" = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    # -- starting -----------------------------------------------------
    def start_runtime(self) -> subprocess.Popen:
        root = package_root()
        script = home_server_runtime_script(root)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PackageRoot",
            str(root),
            "-SupportRoot",
            str(support_root(root)),
            "-Mode",
            "Start",
            "-NonInteractive",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._process = process
        self._reader_thread = threading.Thread(
            target=self._pump_output, args=(process,), daemon=True
        )
        self._reader_thread.start()
        return process

    def _pump_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.output_queue.put(line.rstrip("\n"))
        self.output_queue.put(None)  # sentinel: process stream closed

    # -- status ---------------------------------------------------------
    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def exit_code(self) -> int | None:
        return self._process.poll() if self._process else None

    @staticmethod
    def is_port_open(host: str = "127.0.0.1", port: int = SERVER_PORT, timeout: float = 1.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    # -- stopping ---------------------------------------------------------
    def stop(self, *, fallback_pid: int | None = None, wait_seconds: float = 15.0) -> bool:
        target_pid = self.pid if self.is_alive() else fallback_pid
        if target_pid:
            subprocess.run(
                ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
        self._process = None
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if not self.is_port_open(timeout=0.5):
                return True
            time.sleep(0.5)
        return not self.is_port_open(timeout=0.5)
