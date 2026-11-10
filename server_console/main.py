"""Entry point for LandCustomerServerConsole.exe."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from server_console.single_instance import SingleInstanceGuard
from server_console.ui_theme import FONT_UI, TEXT_SECONDARY, WINDOW_BG, init_scale, px


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    auto_start = "--auto-start" in argv

    guard = SingleInstanceGuard()
    try:
        # 先宣告 DPI 感知，Tk 才會用實際螢幕解析度（畫面才不會被系統放大而模糊）。
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.withdraw()
    running_app: list = []

    def show_existing() -> None:
        if running_app:
            root.after(0, running_app[0].show_window)

    if not guard.acquire(show_existing):
        # 另一個控制台已在執行；已透過 single_instance 通知它把視窗帶到前景。
        root.destroy()
        return 0

    # 先讓視窗立刻出現，再載入其餘的（較慢的）模組並建立畫面。
    init_scale(root)
    root.title("Land Customer System 伺服器控制台")
    root.geometry(f"{px(1040)}x{px(860)}")
    root.configure(bg=WINDOW_BG)
    loading = tk.Label(
        root, text="正在載入伺服器控制台…", bg=WINDOW_BG, fg=TEXT_SECONDARY, font=(FONT_UI, -px(16)),
    )
    loading.place(relx=0.5, rely=0.5, anchor="center")
    root.deiconify()
    root.update()

    from server_console.ui_main import ConsoleApp

    app = ConsoleApp(root, auto_start=auto_start)
    running_app.append(app)
    loading.destroy()

    from server_console.tray import TrayController

    def on_start_stop() -> None:
        if app.process.is_alive() or app.process.is_port_open(timeout=0.5):
            app.stop_server()
        else:
            app.start_server()

    def on_copy_url() -> None:
        app._copy_text(app._connection_values.get("api_url", ""))

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
