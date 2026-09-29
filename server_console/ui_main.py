"""Main window: header, status card, toolbar, info panels, log/management tabs."""

from __future__ import annotations

import datetime
import os
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from server_console import backup_client
from server_console.diagnostics import STARTUP_STAGES, DiagnosticsReader
from server_console.process_manager import ProcessManager
from server_console.settings import ConsoleSettings, load_settings, save_settings
from server_console.state import (
    AUTO_RESTART_MAX_ATTEMPTS,
    AUTO_RESTART_WINDOW_SECONDS,
    compute_display_state,
)

try:
    from server_console.logging_setup import build_logger
except Exception:  # pragma: no cover - logging must never block the UI
    build_logger = None

CONSOLE_VERSION = "v1.9.4"
FONT_FAMILY = "Microsoft JhengHei UI"
BG = "white"
PANEL_BG = "#f5f6f7"
BORDER = "#e0e0e0"
MUTED = "#757575"
TEXT = "#212121"

STATUS_DOT_COLORS = {
    "not_started": "#757575",
    "starting": "#1565c0",
    "running": "#2e7d32",
    "error": "#c62828",
    "stopping": "#757575",
}
STATUS_LABELS = {
    "not_started": "未啟動",
    "starting": "啟動中",
    "running": "運作中",
    "error": "錯誤",
    "stopping": "停止中",
}
STAGE_ORDER = [key for key, _label in STARTUP_STAGES]

# Maps a REAL ps1 diagnostics `stage` value to "how many of the 7 visual
# steps are reached (inclusive)". home_server_runtime.ps1 does not emit a
# distinct stage for the inline recovery/migration check (index 4,
# "遷移與帳號恢復") or for https certificate creation (folded into the
# final "啟動 HTTPS 伺服器" row) -- see diagnostics.py's STARTUP_STAGES
# comment. Reaching 'https' therefore means both index 3 (database) and
# index 4 (migration_recovery) are done.
REACHED_INDEX_BY_STAGE = {
    "prerequisites": 0,
    "netbird": 1,
    "windows_services": 2,
    "pre_upgrade_backup": 2,
    "database": 3,
    "https": 4,
    "backup": 5,
    "server": 6,
}

LOG_LEVEL_LABELS = {"info": "一般", "warning": "警告", "error": "錯誤"}
LOG_LEVEL_COLORS = {"info": TEXT, "warning": "#b28900", "error": "#c62828"}


class ConsoleApp:
    def __init__(self, root: tk.Tk, *, auto_start: bool = False):
        self.root = root
        self.root.title("Land Customer System 伺服器控制台")
        self.root.geometry("1160x760")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)

        self.process = ProcessManager()
        self.diagnostics = DiagnosticsReader()
        self.settings: ConsoleSettings = load_settings()
        self.logger = build_logger() if build_logger else None

        self._is_stopping = False
        self._starting_at: float | None = None
        self._user_requested_stop = False
        self._restart_timestamps: list[float] = []
        self._shown_tray_hint = False
        self._last_status = "not_started"
        self._log_lines: list[tuple[str, str]] = []  # (level, text)
        self._errors_only = tk.BooleanVar(value=False)
        self.tray = None

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        self._poll()

        if auto_start:
            self.root.after(500, self.start_server)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _card(self, parent: tk.Widget, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(
            card, text=title, bg=BG, fg=TEXT, font=(FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(8, 4))
        return card

    def _button(self, parent, text, command, style) -> tk.Button:
        palette = {
            "filled_green": dict(bg="#2e7d32", fg="white", active="#256428", border=None),
            "outline_red": dict(bg="white", fg="#c62828", active="#ffebee", border="#c62828"),
            "outline_gray": dict(bg="white", fg="#424242", active="#f0f0f0", border="#bdbdbd"),
            "outline_blue": dict(bg="white", fg="#1565c0", active="#e3f2fd", border="#1565c0"),
        }[style]
        button = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            font=(FONT_FAMILY, 10), padx=14, pady=6, cursor="hand2",
            bg=palette["bg"], fg=palette["fg"],
            activebackground=palette["active"], activeforeground=palette["fg"],
            disabledforeground="#bdbdbd",
        )
        if palette["border"]:
            button.configure(highlightthickness=1, highlightbackground=palette["border"], highlightcolor=palette["border"])
        button._enabled_bg = palette["bg"]
        button._enabled_fg = palette["fg"]
        return button

    @staticmethod
    def _set_button_enabled(button: tk.Button, enabled: bool) -> None:
        if enabled:
            button.configure(state="normal", bg=button._enabled_bg, fg=button._enabled_fg)
        else:
            button.configure(state="disabled", bg="#eeeeee", fg="#bdbdbd")

    def _build_widgets(self) -> None:
        self._build_header()
        self._build_status_card()
        self._build_toolbar()
        self._build_info_panels()
        self._build_tabs()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x")
        tk.Frame(header, bg=BORDER, height=1).pack(fill="x", side="bottom")
        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x", padx=16, pady=12)

        left = tk.Frame(title_row, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="🗄", bg=BG, fg="#1565c0", font=(FONT_FAMILY, 16)).pack(side="left")
        tk.Label(
            left, text="Land Customer System 伺服器控制台", bg=BG, fg=TEXT,
            font=(FONT_FAMILY, 13, "bold"),
        ).pack(side="left", padx=(8, 8))
        tk.Label(
            left, text=f"{CONSOLE_VERSION} · 家中伺服器", bg=BG, fg=MUTED, font=(FONT_FAMILY, 10),
        ).pack(side="left")

        self.auto_restart_var = tk.BooleanVar(value=self.settings.auto_restart)
        tk.Checkbutton(
            title_row, text="意外停止時自動重啟", variable=self.auto_restart_var,
            command=self._on_auto_restart_toggle, bg=BG, activebackground=BG,
            font=(FONT_FAMILY, 10), fg=TEXT,
        ).pack(side="right")

    def _build_status_card(self) -> None:
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="x", padx=16, pady=(4, 6))
        card = tk.Frame(outer, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=BG)
        inner.pack(fill="x", padx=20, pady=12)

        top_row = tk.Frame(inner, bg=BG)
        top_row.pack(fill="x", anchor="w")
        self.status_dot = tk.Canvas(top_row, width=16, height=16, bg=BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 10))
        self._status_dot_shape = self.status_dot.create_oval(2, 2, 14, 14, fill="#757575", outline="")
        self.status_label = tk.Label(
            top_row, text="未啟動", font=(FONT_FAMILY, 20, "bold"), bg=BG, fg=TEXT,
        )
        self.status_label.pack(side="left")

        self.reason_label = tk.Label(
            inner, text="", font=(FONT_FAMILY, 10), fg=MUTED, bg=BG, anchor="w", justify="left",
        )
        self.reason_label.pack(fill="x", anchor="w", pady=(6, 0))

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 8))

        self.start_button = self._button(bar, "▶  啟動", self.start_server, "filled_green")
        self.start_button.pack(side="left")
        self.stop_button = self._button(bar, "■  停止", self.stop_server, "outline_red")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.restart_button = self._button(bar, "↻  重啟", self.restart_server, "outline_gray")
        self.restart_button.pack(side="left", padx=(8, 0))

        tk.Frame(bar, bg=BORDER, width=1).pack(side="left", fill="y", padx=12, pady=2)

        self.backup_button = self._button(bar, "立即備份", self.backup_now, "outline_gray")
        self.backup_button.pack(side="left")
        self.open_backup_button = self._button(
            bar, "開啟備份資料夾", self.open_backup_folder, "outline_gray"
        )
        self.open_backup_button.pack(side="left", padx=(8, 0))

        self.open_mobile_button = self._button(
            bar, "開啟手機網頁", self.open_mobile_page, "outline_blue"
        )
        self.open_mobile_button.pack(side="right")

    def _build_info_panels(self) -> None:
        info = tk.Frame(self.root, bg=BG)
        info.pack(fill="x", padx=16, pady=(0, 8))
        info.columnconfigure(0, weight=1)
        info.columnconfigure(1, weight=1)

        steps_card = self._card(info, "啟動步驟")
        steps_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        steps_body = tk.Frame(steps_card, bg=BG)
        steps_body.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.step_circles: dict[str, tuple[tk.Canvas, int, int]] = {}
        self.step_status_labels: dict[str, tk.Label] = {}
        for index, (key, label) in enumerate(STARTUP_STAGES, start=1):
            row = tk.Frame(steps_body, bg=BG)
            row.pack(fill="x", pady=2)
            circle = tk.Canvas(row, width=20, height=20, bg=BG, highlightthickness=0)
            circle.pack(side="left")
            oval = circle.create_oval(2, 2, 18, 18, outline="#bdbdbd", width=1.5, fill="")
            number_text = circle.create_text(
                10, 10, text=str(index), font=(FONT_FAMILY, 8), fill=MUTED
            )
            tk.Label(row, text=label, bg=BG, fg=TEXT, font=(FONT_FAMILY, 10)).pack(
                side="left", padx=(8, 0)
            )
            status_text = tk.Label(
                row, text="未執行", bg=BG, fg=MUTED, font=(FONT_FAMILY, 9)
            )
            status_text.pack(side="right")
            self.step_circles[key] = (circle, oval, number_text)
            self.step_status_labels[key] = status_text

        right_column = tk.Frame(info, bg=BG)
        right_column.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        connection_card = self._card(right_column, "連線資訊")
        connection_card.pack(fill="x", pady=(0, 6))
        connection_body = tk.Frame(connection_card, bg=BG)
        connection_body.pack(fill="x", padx=16, pady=(0, 10))
        connection_left = tk.Frame(connection_body, bg=BG)
        connection_left.pack(side="left", fill="both", expand=True)
        self.connection_vars = {
            "api_url": tk.StringVar(value="—"),
            "certificate_url": tk.StringVar(value="—"),
            "certificate_sha256": tk.StringVar(value="—"),
            "netbird_ip": tk.StringVar(value="—"),
        }
        for key, caption in (
            ("api_url", "手機網址"),
            ("certificate_url", "iPhone 憑證"),
            ("certificate_sha256", "CA 指紋"),
            ("netbird_ip", "NetBird IP"),
        ):
            row = tk.Frame(connection_left, bg=BG)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=caption, width=10, anchor="w", bg=BG, fg=MUTED, font=(FONT_FAMILY, 9)).pack(
                side="left"
            )
            tk.Label(
                row, textvariable=self.connection_vars[key], anchor="w", bg=BG, fg=TEXT,
                font=(FONT_FAMILY, 10),
            ).pack(side="left", fill="x", expand=True)
            self._button(
                row, "⧉ 複製", lambda k=key: self._copy_to_clipboard(self.connection_vars[k].get()),
                "outline_gray",
            ).pack(side="right")

        qr_column = tk.Frame(connection_body, bg=BG)
        qr_column.pack(side="right", padx=(16, 0))
        self.qr_label = tk.Label(qr_column, bg=BG, fg=MUTED, font=(FONT_FAMILY, 9), justify="center")
        self.qr_label.pack()
        self._render_qr_placeholder()
        tk.Label(qr_column, text="手機掃描開啟", bg=BG, fg=MUTED, font=(FONT_FAMILY, 9)).pack(pady=(4, 0))

        system_card = self._card(right_column, "系統狀態")
        system_card.pack(fill="x")
        system_body = tk.Frame(system_card, bg=BG)
        system_body.pack(fill="x", padx=16, pady=(0, 10))
        self.system_vars = {
            key: tk.StringVar(value="—")
            for key in (
                "postgresql_service", "postgresql_status", "database_status",
                "account_count", "record_count", "backup_summary",
            )
        }
        self.system_value_labels: dict[str, tk.Label] = {}
        grid_rows = (
            (("postgresql_service", "PostgreSQL 服務"), ("postgresql_status", "服務狀態"), ("database_status", "資料庫")),
            (("account_count", "帳號數"), ("record_count", "資料筆數"), ("backup_summary", "最後備份")),
        )
        for row_index, row_fields in enumerate(grid_rows):
            for col_index, (key, caption) in enumerate(row_fields):
                cell = tk.Frame(system_body, bg=BG)
                cell.grid(row=row_index, column=col_index, sticky="w", padx=(0 if col_index == 0 else 24, 0), pady=(0 if row_index == 0 else 10, 0))
                tk.Label(cell, text=caption, bg=BG, fg=MUTED, font=(FONT_FAMILY, 9)).pack(anchor="w")
                value_label = tk.Label(
                    cell, textvariable=self.system_vars[key], bg=BG, fg=TEXT,
                    font=(FONT_FAMILY, 11, "bold"),
                )
                value_label.pack(anchor="w")
                self.system_value_labels[key] = value_label

    def _render_qr_placeholder(self) -> None:
        self.qr_image = None
        self.qr_label.configure(image="", text="尚未產生\nQR Code", width=12)

    def _build_tabs(self) -> None:
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        tab_bar = tk.Frame(container, bg=BG)
        tab_bar.pack(fill="x")
        tk.Frame(container, bg=BORDER, height=1).pack(fill="x")

        self._tab_buttons: dict[str, tk.Label] = {}

        def make_tab(key, text):
            label = tk.Label(
                tab_bar, text=text, bg=BG, fg=TEXT, font=(FONT_FAMILY, 10, "bold"),
                padx=4, pady=8, cursor="hand2",
            )
            label.pack(side="left", padx=(0, 20))
            label.bind("<Button-1>", lambda _event, k=key: self._show_tab(k))
            self._tab_buttons[key] = label

        make_tab("log", "日誌")
        make_tab("management", "管理")

        log_controls = tk.Frame(tab_bar, bg=BG)
        log_controls.pack(side="right")
        self._log_controls = log_controls
        tk.Checkbutton(
            log_controls, text="只看錯誤", variable=self._errors_only, command=self._render_log,
            bg=BG, font=(FONT_FAMILY, 9),
        ).pack(side="left")
        self._button(log_controls, "複製全部", self._copy_all_logs, "outline_gray").pack(
            side="left", padx=(8, 0)
        )
        self._button(log_controls, "開啟日誌資料夾", self._open_log_folder, "outline_gray").pack(
            side="left", padx=(8, 0)
        )

        self._tab_pages: dict[str, tk.Frame] = {}
        pages_area = tk.Frame(container, bg=BG)
        pages_area.pack(fill="both", expand=True, pady=(8, 0))

        log_page = tk.Frame(pages_area, bg=BG)
        self.log_text = tk.Text(
            log_page, wrap="word", state="disabled", bg=BG, fg=TEXT,
            font=("Consolas", 10), relief="flat", highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.log_text.tag_configure("warning", foreground=LOG_LEVEL_COLORS["warning"])
        self.log_text.tag_configure("error", foreground=LOG_LEVEL_COLORS["error"])
        self.log_text.tag_configure("timestamp", foreground=MUTED)
        self.log_text.pack(fill="both", expand=True)
        self._tab_pages["log"] = log_page

        management_page = tk.Frame(pages_area, bg=BG)
        # 三個管理卡片疊起來可能比視窗矮，用 Canvas 包一層讓它可以滾動，
        # 不會在較小的視窗上被直接切掉、完全看不到下面的內容。
        management_canvas = tk.Canvas(management_page, bg=BG, highlightthickness=0)
        management_scrollbar = ttk.Scrollbar(
            management_page, orient="vertical", command=management_canvas.yview
        )
        management_canvas.configure(yscrollcommand=management_scrollbar.set)
        management_canvas.pack(side="left", fill="both", expand=True)
        management_scrollbar.pack(side="right", fill="y")
        management_content = tk.Frame(management_canvas, bg=BG)
        management_window = management_canvas.create_window(
            (0, 0), window=management_content, anchor="nw"
        )

        def _sync_management_scroll_region(_event=None):
            management_canvas.configure(scrollregion=management_canvas.bbox("all"))

        def _sync_management_width(event):
            management_canvas.itemconfigure(management_window, width=event.width)

        management_content.bind("<Configure>", _sync_management_scroll_region)
        management_canvas.bind("<Configure>", _sync_management_width)

        def _on_mousewheel(event):
            management_canvas.yview_scroll(int(-event.delta / 40), "units")

        management_canvas.bind("<Enter>", lambda _e: management_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        management_canvas.bind("<Leave>", lambda _e: management_canvas.unbind_all("<MouseWheel>"))

        from server_console.ui_dialogs import build_management_tab

        build_management_tab(management_content, self)
        self._tab_pages["management"] = management_page

        self._show_tab("log")

    def _show_tab(self, key: str) -> None:
        for name, page in self._tab_pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, label in self._tab_buttons.items():
            label.configure(fg=TEXT if name == key else MUTED)
        if hasattr(self, "_log_controls"):
            if key == "log":
                self._log_controls.pack(side="right")
            else:
                self._log_controls.pack_forget()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _on_auto_restart_toggle(self) -> None:
        self.settings.auto_restart = self.auto_restart_var.get()
        save_settings(self.settings)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def _classify_line(self, line: str) -> str:
        if line.startswith("INFO:"):
            return "info"
        if "WARNING" in line:
            return "warning"
        if "ERROR" in line or "Traceback" in line:
            return "error"
        return "info"

    def append_log(self, line: str) -> None:
        level = self._classify_line(line)
        self._log_lines.append((level, line))
        if self.logger:
            self.logger.info(line)
        if not self._errors_only.get() or level == "error":
            self._append_log_widget(level, line)

    def _append_log_widget(self, level: str, line: str) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        tag = level if level in ("warning", "error") else ""
        self.log_text.insert("end", f"{timestamp}  ", "timestamp")
        self.log_text.insert("end", f"{LOG_LEVEL_LABELS.get(level, level):<4}", tag)
        self.log_text.insert("end", f"  {line}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _render_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        for level, line in self._log_lines:
            if not self._errors_only.get() or level == "error":
                self._append_log_widget(level, line)

    def _copy_all_logs(self) -> None:
        self._copy_to_clipboard("\n".join(line for _level, line in self._log_lines))

    def _open_log_folder(self) -> None:
        from server_console.paths import console_log_directory

        self._open_folder(console_log_directory())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def start_server(self) -> None:
        if self.process.is_alive() or self.process.is_port_open(timeout=0.5):
            messagebox.showinfo("家中伺服器控制台", "伺服器可能已在執行，或有其他程式占用 8732。")
            return
        self._user_requested_stop = False
        self._starting_at = time.monotonic()
        self.append_log("[控制台] 正在啟動家中伺服器...")
        self.process.start_runtime()

    def stop_server(self, *, ask_confirm: bool = True) -> None:
        if ask_confirm:
            confirmed = messagebox.askyesno(
                "停止家中伺服器", "停止後手機與公司筆電會斷線，確定要停止嗎？"
            )
            if not confirmed:
                return
        self._user_requested_stop = True
        self._is_stopping = True
        self.append_log("[控制台] 正在停止家中伺服器...")
        diagnostics = self.diagnostics.last_known
        fallback_pid = diagnostics.get("process_id")
        self.root.after(50, lambda: self._finish_stop(fallback_pid))

    def _finish_stop(self, fallback_pid) -> None:
        self.process.stop(fallback_pid=fallback_pid)
        self._is_stopping = False
        self.append_log("[控制台] 家中伺服器已停止。")

    def restart_server(self) -> None:
        self.stop_server(ask_confirm=False)
        self.root.after(500, self.start_server)

    def backup_now(self) -> None:
        self.append_log("[控制台] 正在建立立即備份...")
        result = backup_client.backup_now()
        if result.get("status") == "ok":
            self.append_log("[控制台] 立即備份完成。")
            messagebox.showinfo("立即備份", "備份已完成。")
        else:
            message = result.get("message") or "備份失敗，請查看日誌。"
            self.append_log(f"[控制台] 立即備份失敗：{message}")
            messagebox.showerror("立即備份失敗", message)
        self._refresh_backup_status()

    def open_backup_folder(self) -> None:
        from server_console.paths import backup_directory

        self._open_folder(backup_directory())

    def open_mobile_page(self) -> None:
        url = self.connection_vars["api_url"].get()
        if url and url != "—":
            webbrowser.open(url)
        else:
            messagebox.showinfo("開啟手機網頁", "尚未取得手機網址，請先確認伺服器已啟動。")

    def run_management_action(self, action) -> dict:
        """Stop -> run `action()` -> restart, always, regardless of outcome.

        `action` is a zero-argument callable returning the subcommand's
        {"status", "message"} dict. Used by all three 管理 dialogs so the
        shared "先停止、完成後自動重新啟動" rule lives in one place.
        """

        was_running = self.process.is_alive() or ProcessManager.is_port_open(timeout=0.5)
        if was_running:
            self.append_log("[控制台] 執行管理功能前先停止伺服器...")
            self.stop_server(ask_confirm=False)
        try:
            result = action()
        finally:
            self.append_log("[控制台] 管理功能執行完畢，重新啟動伺服器...")
            self.start_server()
        return result

    def _copy_to_clipboard(self, value: str) -> None:
        if not value or value == "—":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def _open_folder(self, path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))  # noqa: S606 - opening a local folder, not a downloaded file

    def _refresh_backup_status(self) -> None:
        result = backup_client.backup_status()
        if result.get("status") in ("ok", "warning"):
            count = result.get("backup_count")
            latest = result.get("latest_backup_at") or ""
            self.system_vars["backup_summary"].set(
                f"{latest or '—'}（共 {count if count is not None else '—'} 份）"
            )

    # ------------------------------------------------------------------
    # Periodic polling
    # ------------------------------------------------------------------
    def _poll(self) -> None:
        try:
            self._drain_process_output()
            self._update_state()
        finally:
            self.root.after(1000, self._poll)

    def _drain_process_output(self) -> None:
        while True:
            try:
                line = self.process.output_queue.get_nowait()
            except Exception:
                break
            if line is None:
                continue
            self.append_log(line)

    def _update_state(self) -> None:
        diagnostics = self.diagnostics.read()
        process_alive = self.process.is_alive()
        port_open = ProcessManager.is_port_open(timeout=0.5)
        startup_elapsed = (
            time.monotonic() - self._starting_at if self._starting_at is not None else None
        )
        display = compute_display_state(
            diagnostics,
            process_alive=process_alive,
            port_open=port_open,
            is_stopping=self._is_stopping,
            startup_elapsed_seconds=startup_elapsed,
        )
        if display.status == "running":
            self._starting_at = None

        self._apply_status(display.status, display.reason)
        self._update_steps(diagnostics, display)
        self._update_connection_info(diagnostics)
        self._update_system_status(diagnostics, display.status)
        self._update_buttons(display.status)
        self._handle_unexpected_stop(display.status)
        self._last_status = display.status
        if self.tray:
            self.tray.set_status(display.status)

    def _set_var_if_changed(self, var: tk.StringVar, value: str) -> None:
        # StringVar.set() 每次都會經過 Tcl 的 globalsetvar／trace，即使值沒變
        # 也可能觸發一次重繪；每秒都對十幾個變數這樣做，畫面會像在閃爍。
        # 值不變就整個跳過。
        if var.get() != value:
            var.set(value)

    def _apply_status(self, status: str, reason: str) -> None:
        signature = (status, reason)
        if getattr(self, "_applied_status_signature", None) == signature:
            return
        self._applied_status_signature = signature
        self.status_dot.itemconfigure(
            self._status_dot_shape, fill=STATUS_DOT_COLORS.get(status, "#757575")
        )
        self.status_label.configure(text=STATUS_LABELS.get(status, status))
        self.reason_label.configure(text=reason)

    def _update_steps(self, diagnostics: dict, display) -> None:
        current_stage = diagnostics.get("stage") or ""
        failed = display.status == "error"
        reached_index = (
            len(STAGE_ORDER) - 1
            if display.status == "running"
            else REACHED_INDEX_BY_STAGE.get(current_stage, -1)
        )
        signature = (display.status, reached_index, failed)
        if getattr(self, "_applied_steps_signature", None) == signature:
            return
        self._applied_steps_signature = signature
        for index, key in enumerate(STAGE_ORDER):
            circle, oval, number_text = self.step_circles[key]
            status_label = self.step_status_labels[key]
            if index < reached_index or (index == reached_index and display.status == "running"):
                circle.itemconfigure(oval, outline="#2e7d32", fill="#2e7d32")
                circle.itemconfigure(number_text, fill="white")
                status_label.configure(text="完成", fg="#2e7d32")
            elif index == reached_index:
                if failed:
                    circle.itemconfigure(oval, outline="#c62828", fill="#c62828")
                    circle.itemconfigure(number_text, fill="white")
                    status_label.configure(text="失敗", fg="#c62828")
                else:
                    circle.itemconfigure(oval, outline="#1565c0", fill="white")
                    circle.itemconfigure(number_text, fill="#1565c0")
                    status_label.configure(text="進行中", fg="#1565c0")
            else:
                circle.itemconfigure(oval, outline="#bdbdbd", fill="")
                circle.itemconfigure(number_text, fill=MUTED)
                status_label.configure(text="未執行", fg=MUTED)

    def _update_connection_info(self, diagnostics: dict) -> None:
        self._set_var_if_changed(self.connection_vars["api_url"], diagnostics.get("api_url") or "—")
        self._set_var_if_changed(
            self.connection_vars["certificate_url"], diagnostics.get("certificate_url") or "—"
        )
        self._set_var_if_changed(
            self.connection_vars["certificate_sha256"], diagnostics.get("certificate_sha256") or "—"
        )
        netbird_ip = diagnostics.get("netbird_ip") or ""
        self._set_var_if_changed(
            self.connection_vars["netbird_ip"],
            netbird_ip or "NetBird 未連線，手機與筆電無法連入",
        )
        self._update_qr(diagnostics.get("api_url") or "")

    def _update_qr(self, url: str) -> None:
        if url == getattr(self, "_last_qr_url", None):
            return
        self._last_qr_url = url
        if not url:
            self._render_qr_placeholder()
            return
        try:
            from server_console.qrcode_widget import qr_photo_image

            self.qr_image = qr_photo_image(url)
            self.qr_label.configure(image=self.qr_image, text="", width=0)
        except Exception:
            pass

    def _update_system_status(self, diagnostics: dict, status: str) -> None:
        service = diagnostics.get("postgresql_service") or "—"
        pg_status = diagnostics.get("postgresql_status") or ""
        self._set_var_if_changed(self.system_vars["postgresql_service"], service)
        if pg_status:
            note = "" if status == "running" else "（伺服器已停）"
            self._set_var_if_changed(self.system_vars["postgresql_status"], f"{pg_status}{note}")
            self.system_value_labels["postgresql_status"].configure(
                fg="#2e7d32" if pg_status.lower() == "running" else TEXT
            )
        else:
            self._set_var_if_changed(self.system_vars["postgresql_status"], "—")
            self.system_value_labels["postgresql_status"].configure(fg=TEXT)
        self._set_var_if_changed(
            self.system_vars["database_status"], diagnostics.get("database_status") or "—"
        )
        account_count = diagnostics.get("account_count")
        self._set_var_if_changed(
            self.system_vars["account_count"],
            str(account_count) if account_count is not None else "—",
        )
        record_count = diagnostics.get("record_count")
        self._set_var_if_changed(
            self.system_vars["record_count"],
            str(record_count) if record_count is not None else "—",
        )
        latest_at = diagnostics.get("latest_backup_at")
        backup_count = diagnostics.get("backup_count")
        if latest_at is not None:
            self._set_var_if_changed(
                self.system_vars["backup_summary"],
                f"{latest_at or '—'}（共 {backup_count if backup_count is not None else '—'} 份）",
            )

    def _update_buttons(self, status: str) -> None:
        if getattr(self, "_applied_buttons_status", None) == status:
            return
        self._applied_buttons_status = status
        running_like = status in ("starting", "running")
        self._set_button_enabled(self.start_button, not running_like)
        self._set_button_enabled(self.stop_button, running_like)
        self._set_button_enabled(self.restart_button, status == "running")
        self._set_button_enabled(self.backup_button, status == "running")
        self._set_button_enabled(self.open_mobile_button, status == "running")

    # ------------------------------------------------------------------
    # Auto-restart on unexpected stop
    # ------------------------------------------------------------------
    def _handle_unexpected_stop(self, status: str) -> None:
        was_running = self._last_status == "running"
        stopped_unexpectedly = (
            was_running and status in ("error", "not_started") and not self._user_requested_stop
        )
        if not stopped_unexpectedly:
            return
        if self.tray:
            self.tray.notify("家中伺服器控制台", "伺服器意外停止。")
        if not self.settings.auto_restart:
            return
        now = time.monotonic()
        self._restart_timestamps = [
            timestamp for timestamp in self._restart_timestamps
            if now - timestamp < AUTO_RESTART_WINDOW_SECONDS
        ]
        if len(self._restart_timestamps) >= AUTO_RESTART_MAX_ATTEMPTS:
            self.append_log("[控制台] 10 分鐘內已自動重啟 3 次，停止重試。")
            if self.tray:
                self.tray.notify("家中伺服器控制台", "自動重啟已達上限，請手動檢查。")
            return
        self._restart_timestamps.append(now)
        self.append_log("[控制台] 偵測到伺服器意外停止，將自動重新啟動。")
        self.root.after(1000, self.start_server)

    # ------------------------------------------------------------------
    # Window close -> tray
    # ------------------------------------------------------------------
    def _on_close_button(self) -> None:
        self.root.withdraw()
        if not self._shown_tray_hint:
            self._shown_tray_hint = True
            if self.tray:
                self.tray.notify(
                    "家中伺服器控制台",
                    "控制台已縮到系統匣，伺服器仍在背景執行。點兩下圖示可再打開。",
                )

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_application(self) -> None:
        if self.process.is_alive() or ProcessManager.is_port_open(timeout=0.5):
            stop_server_too = messagebox.askyesno(
                "結束控制台", "是否同時停止家中伺服器？選「否」會保留伺服器繼續執行。"
            )
            if stop_server_too:
                self.stop_server(ask_confirm=False)
        if self.tray:
            self.tray.stop()
        self.root.after(200, self.root.destroy)
