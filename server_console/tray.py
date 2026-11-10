"""System tray icon (pystray). Runs in its own background thread; every
callback hops back onto the Tk thread via `root.after(0, ...)` because Tk
widgets are not thread-safe to touch directly from pystray's thread.
"""

from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image, ImageDraw

STATUS_COLORS = {
    "not_started": "#9e9e9e",
    "starting": "#1e88e5",
    "running": "#43a047",
    "no_accounts": "#43a047",
    "error": "#e53935",
    "stopping": "#9e9e9e",
}

STATUS_LABELS = {
    "not_started": "未啟動",
    "starting": "啟動中",
    "running": "運作中",
    "no_accounts": "運作中（資料庫尚無帳號）",
    "error": "錯誤",
    "stopping": "停止中",
}


def _icon_image(color: str) -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 6
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
    return image


class TrayController:
    def __init__(
        self,
        root,
        *,
        on_open: Callable[[], None],
        on_start_stop: Callable[[], None],
        on_copy_url: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.root = root
        self._on_open = on_open
        self._on_start_stop = on_start_stop
        self._on_copy_url = on_copy_url
        self._on_exit = on_exit
        self._status = "not_started"
        self.icon = pystray.Icon(
            "LandCustomerServerConsole",
            icon=_icon_image(STATUS_COLORS["not_started"]),
            title="家中伺服器控制台：未啟動",
            menu=pystray.Menu(
                pystray.MenuItem("開啟控制台", self._call(on_open), default=True),
                pystray.MenuItem("啟動或停止伺服器", self._call(on_start_stop)),
                pystray.MenuItem("複製手機網址", self._call(on_copy_url)),
                pystray.MenuItem("結束", self._call(on_exit)),
            ),
        )

    def _call(self, func: Callable[[], None]):
        def _invoke(icon, item):
            self.root.after(0, func)

        return _invoke

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass

    def set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        label = STATUS_LABELS.get(status, status)
        color = STATUS_COLORS.get(status, "#9e9e9e")
        try:
            self.icon.icon = _icon_image(color)
            self.icon.title = f"家中伺服器控制台：{label}"
        except Exception:
            pass

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass
