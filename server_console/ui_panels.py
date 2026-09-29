"""The main window's cards, each drawn on a single canvas.

Every native window costs several milliseconds to create on this project's
target laptops, so instead of one Label per text the panels draw their text as
canvas items and lay them out by hand (`_relayout`, run on every size change).
Numbers are the spec's (伺服器控制台_畫面規格.md) in design pixels.
"""

from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk

from server_console.ui_theme import (
    BORDER, BROWN, BROWN_BG, BUTTON_BORDER, CARD_BG, FONT_MONO, GREEN, PRIMARY, RED, STATUS_PALETTE, TEXT,
    TEXT_MUTED, TEXT_SECONDARY, blend, px, scaled_font,
)
from server_console.ui_widgets import (
    CanvasButton, CanvasCheck, Panel, circle_photo, ellipsize, fit_text,
)

_STEP_STYLES = {
    # status: (circle fill, circle ring, digit colour, label, label colour)
    "done": (GREEN, None, "#FFFFFF", "完成", GREEN),
    "running": (PRIMARY, None, "#FFFFFF", "進行中", PRIMARY),
    "failed": (RED, None, "#FFFFFF", "失敗", RED),
    "skipped": (CARD_BG, BROWN, BROWN, "略過", BROWN),
}
_STEP_PENDING = (CARD_BG, BUTTON_BORDER, TEXT_MUTED, "未執行", TEXT_MUTED)


class TitleBar(tk.Canvas):
    """48px white bar: server icon, name, version and the auto-restart checkbox."""

    def __init__(self, master, icon_photo, title, version_text, variable, on_toggle):
        self._height = px(48)
        super().__init__(master, width=1, height=self._height, bg=CARD_BG, highlightthickness=0, bd=0)
        self._icon_photo = icon_photo
        self.create_image(px(20), self._height // 2, image=icon_photo, anchor="w")
        title_font = scaled_font(16, "bold")
        self.create_text(px(54), self._height // 2, text=title, anchor="w", font=title_font, fill=TEXT)
        self.create_text(
            px(54) + title_font.measure(title) + px(12), self._height // 2, text=version_text, anchor="w",
            font=scaled_font(13), fill=TEXT_SECONDARY,
        )
        self._line = self.create_rectangle(0, 0, 0, 0, width=0, fill=BORDER)
        self.check = CanvasCheck(self, "意外停止時自動重啟", variable, command=on_toggle, bg=CARD_BG)
        self._check_item = self.create_window(0, self._height // 2, anchor="e", window=self.check)
        self.bind("<Configure>", self._relayout, add="+")

    def _relayout(self, event):
        width = event.width
        self.coords(self._line, 0, self._height - max(1, px(1)), width, self._height)
        self.coords(self._check_item, width - px(20), self._height // 2)


class StatusBar(Panel):
    """Big status line. Two lines of text on the left, and on the right either
    the PID (running) or the two "no accounts" shortcut buttons."""

    def __init__(self, master, on_bootstrap, on_import):
        text_color, background = STATUS_PALETTE["not_started"]
        super().__init__(master, fill=background, border=blend(text_color, background, 0.45), radius=10)
        self._dot_item = self.create_image(px(28), 0, anchor="center")
        self._title = self.text(50, 16, "", 22, "bold", text_color, anchor="nw")
        self._reason = self.text(50, 50, "", 14, anchor="nw", width=600)
        self._pid = self.text(0, 0, "", 13, color=TEXT_SECONDARY, anchor="e", family=FONT_MONO)
        self.bootstrap_button = CanvasButton(self, "建立第一個管理員", on_bootstrap, "primary", height=40,
                                             backdrop=BROWN_BG)
        self.import_button = CanvasButton(self, "匯入遷移包", on_import, "brown", height=40, backdrop=BROWN_BG)
        self._bootstrap_item = self.create_window(0, 0, anchor="e", window=self.bootstrap_button, state="hidden")
        self._import_item = self.create_window(0, 0, anchor="e", window=self.import_button, state="hidden")
        self._show_buttons = False
        self._pid_text = ""
        self._dot_color = text_color
        self._status = None
        self.configure(height=px(86))
        self.bind("<Configure>", lambda _e: self._relayout(), add="+")

    def set_state(self, status, title, reason, pid_text):
        text_color, background = STATUS_PALETTE[status]
        self.set_colors(fill=background, border=blend(text_color, background, 0.45))
        self.itemconfigure(self._title, text=title, fill=text_color)
        self.itemconfigure(self._reason, text=reason)
        self._dot_color = text_color
        self._dot_photo = circle_photo(px(16), text_color, None, 0, background)
        self.itemconfigure(self._dot_item, image=self._dot_photo)
        self.bootstrap_button.set_backdrop(background)
        self.import_button.set_backdrop(background)
        self._show_buttons = status == "no_accounts"
        self._pid_text = pid_text if status == "running" else ""
        self.itemconfigure(self._bootstrap_item, state="normal" if self._show_buttons else "hidden")
        self.itemconfigure(self._import_item, state="normal" if self._show_buttons else "hidden")
        self.itemconfigure(self._pid, text=self._pid_text)
        self._relayout()

    def _relayout(self):
        width = self.winfo_width()
        if width <= 1:
            return
        right = width - px(20)
        gap = px(8)
        if self._show_buttons:
            actions_width = self.bootstrap_button.winfo_reqwidth() + gap + self.import_button.winfo_reqwidth()
        elif self._pid_text:
            actions_width = scaled_font(13, family=FONT_MONO).measure(self._pid_text)
        else:
            actions_width = 0
        text_width = width - px(50) - px(20) - (actions_width + px(16) if actions_width else 0)
        self.itemconfigure(self._reason, width=max(px(120), text_width))
        title_height = self.text_height(self._title)
        top = px(16)
        reason_top = top + title_height + px(2)
        height = reason_top + self.text_height(self._reason) + px(16)
        height = max(height, px(60))
        self.coords(self._title, px(50), top)
        self.coords(self._reason, px(50), reason_top)
        self.coords(self._dot_item, px(28), height // 2)
        self.coords(self._import_item, right, height // 2)
        self.coords(self._bootstrap_item, right - self.import_button.winfo_reqwidth() - gap, height // 2)
        self.coords(self._pid, right, height // 2)
        if int(float(self.cget("height"))) != height:
            self.configure(height=height)


class StepsPanel(Panel):
    """啟動步驟: seven numbered rows; failed/skipped rows show their reason below."""

    ROW_TOP = 56
    ROW_HEIGHT = 24
    ROW_GAP = 14

    def __init__(self, master, count):
        super().__init__(master, fill=CARD_BG, border=BORDER, radius=10)
        self.text(18, 28, "啟動步驟", 15, "bold")
        self._rows = []
        for _ in range(count):
            self._rows.append({
                "circle": self.create_image(0, 0, anchor="center"),
                "digit": self.create_text(0, 0, font=scaled_font(12, "bold"), text=""),
                "name": self.text(0, 0, "", 14),
                "status": self.text(0, 0, "", 12, anchor="e"),
                "reason": self.text(0, 0, "", 12, anchor="nw", width=230),
            })
        self._photos = {}
        self._data = []
        self._name_font = scaled_font(14)
        self._status_width = scaled_font(12).measure("進行中")
        self.configure(height=px(self.ROW_TOP + count * (self.ROW_HEIGHT + self.ROW_GAP) + 4))
        self.bind("<Configure>", lambda _e: self._relayout(), add="+")

    def set_rows(self, steps):
        self._data = list(steps)
        for step, row in zip(self._data, self._rows):
            fill, ring, digit_color, label, label_color = _STEP_STYLES.get(step.status, _STEP_PENDING)
            self._photos[step.n] = circle_photo(px(self.ROW_HEIGHT), fill, ring, px(1.5) if ring else 0, CARD_BG)
            self.itemconfigure(row["circle"], image=self._photos[step.n])
            self.itemconfigure(row["digit"], text=str(step.n), fill=digit_color)
            self.itemconfigure(row["name"], text=step.name)
            self.itemconfigure(row["status"], text=label, fill=label_color)
            show_reason = step.status in ("failed", "skipped") and bool(step.reason)
            self.itemconfigure(
                row["reason"], text=step.reason if show_reason else "",
                fill=RED if step.status == "failed" else BROWN, state="normal" if show_reason else "hidden",
            )
        self._relayout()

    def _relayout(self):
        width = self.winfo_width()
        if width <= 1 or not self._data:
            return
        y = px(self.ROW_TOP)
        for step, row in zip(self._data, self._rows):
            center = y + px(self.ROW_HEIGHT) // 2
            self.coords(row["circle"], px(30), center)
            self.coords(row["digit"], px(30), center)
            self.coords(row["name"], px(52), center)
            self.coords(row["status"], width - px(18), center)
            room = width - px(52) - px(18) - self._status_width - px(8)
            self.itemconfigure(row["name"], text=fit_text(self._name_font, step.name, room))
            extra = 0
            if self.itemcget(row["reason"], "state") != "hidden":
                self.itemconfigure(row["reason"], width=max(px(80), width - px(52) - px(18)))
                self.coords(row["reason"], px(52), y + px(self.ROW_HEIGHT) + px(2))
                extra = self.text_height(row["reason"]) + px(4)
            y += px(self.ROW_HEIGHT + self.ROW_GAP) + extra
        wanted = y + px(4)
        if int(float(self.cget("height"))) != wanted:
            self.configure(height=wanted)


class ConnectionPanel(Panel):
    """連線資訊: four value rows with copy buttons, plus the QR code."""

    ROWS = (
        ("api_url", "手機網址"), ("certificate_url", "iPhone 憑證"),
        ("certificate_sha256", "CA 指紋"), ("netbird_ip", "NetBird IP"),
    )
    ROW_TOP = 67
    ROW_PITCH = 42

    def __init__(self, master, on_copy):
        super().__init__(master, fill=CARD_BG, border=BORDER, radius=10)
        self.text(18, 28, "連線資訊", 15, "bold")
        self._captions = {}
        self._value_items = {}
        self._button_items = {}
        self.copy_buttons: dict[str, CanvasButton] = {}
        self._values: dict[str, str] = {}
        for key, caption in self.ROWS:
            self._captions[key] = self.text(18, 0, caption, 13, color=TEXT_SECONDARY)
            self._value_items[key] = self.text(132, 0, "—", 13, family=FONT_MONO)
            button = CanvasButton(
                self, "複製", lambda k=key: on_copy(k), "gray", "copy", height=32, font_size=12,
                backdrop=CARD_BG, texts=("已複製",), width=0,
            )
            self.copy_buttons[key] = button
            self._button_items[key] = self.create_window(0, 0, anchor="e", window=button)
        self._qr_item = self.create_image(0, 0, anchor="nw")
        self._qr_caption = self.text(0, 0, "手機掃描開啟", 12, color=TEXT_SECONDARY, anchor="center")
        self._qr_photos: dict[str, ImageTk.PhotoImage] = {}
        self._wanted_qr = ""
        self._mono_width = max(1, scaled_font(13, family=FONT_MONO).measure("0"))
        self.configure(height=px(226))
        self.bind("<Configure>", lambda _e: self._relayout(), add="+")

    def set_values(self, values: dict[str, str]) -> None:
        self._values = dict(values)
        for key, _caption in self.ROWS:
            self.copy_buttons[key].set_enabled(bool(values.get(key)))
        self._relayout()

    def set_qr(self, url: str) -> None:
        """The QR image (segno + Pillow) is made a moment later so the window can
        appear first; the newest request wins."""

        self._wanted_qr = url or ""
        key = self._wanted_qr or "faded"
        if key in self._qr_photos:
            self.itemconfigure(self._qr_item, image=self._qr_photos[key])
        else:
            self.after(30, self._build_qr)

    def _build_qr(self) -> None:
        from server_console.qrcode_widget import qr_image

        url = self._wanted_qr
        key = url or "faded"
        if key not in self._qr_photos:
            picture = qr_image(url or "https://example.invalid/", faded=not url)
            side = px(125)
            self._qr_photos[key] = ImageTk.PhotoImage(picture.resize((side, side), Image.NEAREST))
        self.itemconfigure(self._qr_item, image=self._qr_photos[key])

    def _relayout(self):
        width = self.winfo_width()
        if width <= 1:
            return
        button_right = width - px(178)
        qr_left = width - px(18) - px(125)
        self.coords(self._qr_item, qr_left, px(24))
        self.coords(self._qr_caption, qr_left + px(62), px(24 + 125 + 20))
        for index, (key, _caption) in enumerate(self.ROWS):
            center = px(self.ROW_TOP + self.ROW_PITCH * index)
            button = self.copy_buttons[key]
            self.coords(self._captions[key], px(18), center)
            self.coords(self._value_items[key], px(132), center)
            self.coords(self._button_items[key], button_right, center)
            full = self._values.get(key, "")
            available = button_right - button.winfo_reqwidth() - px(12) - px(132)
            text = ellipsize(full, max(8, available // self._mono_width)) if full else "—"
            self.itemconfigure(self._value_items[key], text=text)


class SystemPanel(Panel):
    """系統狀態: 3 columns x 2 rows of caption + value."""

    FIELDS = (
        ("service", "PostgreSQL 服務"), ("service_state", "服務狀態"), ("database", "資料庫"),
        ("accounts", "帳號數"), ("records", "資料筆數"), ("backup", "最後備份"),
    )

    def __init__(self, master):
        super().__init__(master, fill=CARD_BG, border=BORDER, radius=10)
        self.text(18, 28, "系統狀態", 15, "bold")
        self._captions = [self.text(0, 0, caption, 12, color=TEXT_SECONDARY) for _key, caption in self.FIELDS]
        self._values = {key: self.text(0, 0, "—", 14) for key, _caption in self.FIELDS}
        self._full: dict[str, str] = {}
        self._font = scaled_font(14)
        self.configure(height=px(156))
        self.bind("<Configure>", lambda _e: self._relayout(), add="+")

    def set_value(self, key: str, text: str, color: str = TEXT) -> None:
        self._full[key] = text
        self.itemconfigure(self._values[key], fill=color)
        self._fit_value(key)

    def _fit_value(self, key: str) -> None:
        width = self.winfo_width()
        text = self._full.get(key, "—")
        if width > 1:
            column_width = (width - px(18)) / 3
            text = fit_text(self._font, text, int(column_width - px(14)))
        self.itemconfigure(self._values[key], text=text)

    def _relayout(self):
        width = self.winfo_width()
        if width <= 1:
            return
        column_width = (width - px(18)) / 3
        for index, (key, _caption) in enumerate(self.FIELDS):
            column, row = index % 3, index // 3
            x = px(18) + column_width * column
            caption_y = px(58 + 52 * row)
            self.coords(self._captions[index], x, caption_y)
            self.coords(self._values[key], x, caption_y + px(21))
            self._fit_value(key)


class TabBar(tk.Canvas):
    """日誌 | 管理 tabs on the left, tool widgets on the right, all one window."""

    def __init__(self, master, tabs, on_select):
        self._tabs = list(tabs)
        self._on_select = on_select
        self._height = px(48)
        self._active = None
        super().__init__(master, width=1, height=self._height, bg=CARD_BG, highlightthickness=0, bd=0)
        self._line = self.create_rectangle(0, 0, 0, 0, width=0, fill=BORDER)
        self._underline = self.create_rectangle(0, 0, 0, 0, width=0, fill=PRIMARY, state="hidden")
        self._cells: dict[str, tuple[int, int]] = {}
        self._texts = {}
        left = px(12)
        for key, label in self._tabs:
            cell_width = px(72)
            self._cells[key] = (left, left + cell_width)
            self._texts[key] = self.create_text(
                left + cell_width // 2, (self._height - px(3)) // 2, text=label, font=scaled_font(14),
                fill=TEXT_SECONDARY,
            )
            left += cell_width + px(8)
        self._tools: list[tuple[int, tk.Widget, int]] = []  # (window item, widget, gap to the tool on its left, design px)
        self.configure(cursor="arrow")
        self.bind("<Configure>", self._relayout, add="+")
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Motion>", self._motion)

    def add_tool(self, widget, gap_before: int) -> int:
        item = self.create_window(0, self._height // 2, anchor="e", window=widget)
        self._tools.append((item, widget, gap_before))
        return item

    def set_tools_visible(self, visible: bool) -> None:
        for item, _widget, _gap in self._tools:
            self.itemconfigure(item, state="normal" if visible else "hidden")

    def set_active(self, key: str) -> None:
        self._active = key
        for name, item in self._texts.items():
            active = name == key
            self.itemconfigure(item, fill=PRIMARY if active else TEXT_SECONDARY,
                               font=scaled_font(14, "bold" if active else "normal"))
        left, right = self._cells[key]
        self.coords(self._underline, left, self._height - px(3), right, self._height)
        self.itemconfigure(self._underline, state="normal")

    def _cell_at(self, x):
        for key, (left, right) in self._cells.items():
            if left <= x < right:
                return key
        return None

    def _motion(self, event):
        self.configure(cursor="hand2" if self._cell_at(event.x) else "arrow")

    def _click(self, event):
        key = self._cell_at(event.x)
        if key and event.y < self._height:
            self._on_select(key)

    def _relayout(self, event):
        width = event.width
        self.coords(self._line, 0, self._height - max(1, px(1)), width, self._height)
        self.tag_raise(self._underline)
        right = width - px(12)
        for item, widget, gap in reversed(self._tools):
            self.coords(item, right, self._height // 2)
            right -= widget.winfo_reqwidth() + px(gap)
