"""Entry point for LandCustomerServerConsole.exe."""

from __future__ import annotations

import sys
import tkinter as tk

from server_console.single_instance import SingleInstanceGuard
from server_console.ui_main import ConsoleApp


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    auto_start = "--auto-start" in argv

    guard = SingleInstanceGuard()
    root = tk.Tk()

    def show_existing() -> None:
        root.after(0, app.show_window)

    if not guard.acquire(show_existing):
        # 另一個控制台已在執行；已透過 single_instance 通知它把視窗帶到前景。
        root.destroy()
        return 0

    app = ConsoleApp(root, auto_start=auto_start)

    from server_console.tray import TrayController

    def on_start_stop() -> None:
        if app.process.is_alive() or app.process.is_port_open(timeout=0.5):
            app.stop_server()
        else:
            app.start_server()

    def on_copy_url() -> None:
        app._copy_to_clipboard(app.connection_vars["api_url"].get())

    tray = TrayController(
        root,
        on_open=app.show_window,
        on_start_stop=on_start_stop,
        on_copy_url=on_copy_url,
        on_exit=app.exit_application,
    )
    app.tray = tray
    tray.start()

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
