"""One console at a time: a fixed loopback-only TCP port doubles as both a
mutex (bind fails if another instance already holds it) and a tiny IPC
channel so a second launch can ask the first to raise its window. This
port is purely internal signalling between two copies of this same
process on 127.0.0.1 -- it is not part of the application's real network
surface and is never the same port as the API (8732) or certificate
service (8733).
"""

from __future__ import annotations

import socket
import threading
from typing import Callable

SINGLE_INSTANCE_PORT = 51987


class SingleInstanceGuard:
    def __init__(self):
        self._listener: socket.socket | None = None

    def acquire(self, on_show_requested: Callable[[], None]) -> bool:
        """Return True if this is the only instance. Otherwise, signal the
        existing instance to show itself and return False."""

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        except OSError:
            listener.close()
            self._signal_existing_instance()
            return False
        listener.listen(4)
        self._listener = listener
        thread = threading.Thread(
            target=self._serve, args=(listener, on_show_requested), daemon=True
        )
        thread.start()
        return True

    @staticmethod
    def _serve(listener: socket.socket, on_show_requested: Callable[[], None]) -> None:
        while True:
            try:
                connection, _address = listener.accept()
            except OSError:
                return
            try:
                connection.recv(16)
            except OSError:
                pass
            finally:
                connection.close()
            on_show_requested()

    @staticmethod
    def _signal_existing_instance() -> None:
        try:
            with socket.create_connection(("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=2) as sock:
                sock.sendall(b"SHOW")
        except OSError:
            pass
