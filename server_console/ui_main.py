"""Main window, laid out per 伺服器控制台_畫面規格.md (plain tkinter, see ui_theme.py)."""

from __future__ import annotations

import datetime
import os
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from server_console import admin_client, backup_client
from server_console.diagnostics import DiagnosticsReader
from server_console.process_manager import ProcessManager
from server_console.services import PortMonitor, PostgresServiceMonitor, port_owner_pid
from server_console.settings import ConsoleSettings, load_settings, save_settings
from server_console.state import (
    AUTO_RESTART_MAX_ATTEMPTS,
    AUTO_RESTART_WINDOW_SECONDS,
    STEP_COUNT,
    compute_display_state,
    step_log_line,
)
from server_console.ui_icons import icon
from server_console.ui_management import ManagementTab
from server_console.ui_theme import (
    BORDER, BROWN, CARD_BG, FONT_MONO, GREEN, LOG_BG, PRIMARY, RED, TEXT, TEXT_MUTED, TEXT_SECONDARY, WINDOW_BG,
    init_scale, px, scaled_font,
)
from server_console.ui_panels import ConnectionPanel, StatusBar, StepsPanel, SystemPanel, TabBar, TitleBar
from server_console.ui_widgets import Box, CanvasButton, CanvasCheck, PageScroller, RoundedFrame

try:
    from server_console.logging_setup import build_logger
except Exception:  # pragma: no cover - logging must never block the UI
    build_logger = None

CONSOLE_VERSION = "v1.9.4"
_PS1_STEP_HEADER = re.compile(r"^\[\d+/\d+\]")
_SERVER_PID = re.compile(r"Started server process \[(\d+)\]")

LEVEL_LABELS = {"info": "一般", "warning": "警告", "error": "錯誤"}
LEVEL_COLORS = {"info": TEXT_SECONDARY, "warning": BROWN, "error": RED}
RUNNING_STATUSES = ("running", "no_accounts")


class ConsoleApp:
    def __init__(self, root: tk.Tk, *, auto_start: bool = False):
        self.root = root
        init_scale(root)
        root.title("Land Customer System 伺服器控制台")
        root.geometry(f"{px(1040)}x{px(860)}")
        root.minsize(px(820), px(560))
        root.configure(bg=WINDOW_BG)

        self.process = ProcessManager()
        self.diagnostics = DiagnosticsReader()
        self.settings: ConsoleSettings = load_settings()
        self.logger = build_logger() if build_logger else None
        self.services = PostgresServiceMonitor()
        self.services.start()
        self.port_monitor = PortMonitor(lambda: ProcessManager.is_port_open(timeout=0.5))
        self.port_monitor.start()

        self._is_stopping = False
        self._busy = False
        self._starting_at: float | None = None
        self._started_wall: datetime.datetime | None = None
        self._user_requested_stop = False
        self._restart_timestamps: list[float] = []
        self._shown_tray_hint = False
        self._last_status = "not_started"
        self._last_display = None
        self._server_pid: int | None = None
        self._pid_lookup_running = False
        self._step_snapshot: dict[int, str] | None = None
        self._log_lines: list[tuple[str, str, str]] = []  # (time, level, text)
        self._errors_only = tk.BooleanVar(value=False)
        self._signatures: dict[str, object] = {}
        self._connection_values: dict[str, str] = {}
        self.admin_info: dict = {"account_count": None, "admins": []}
        self._admin_refreshing = False
        self._admin_refreshed_at = 0.0
        self.backup_info: dict = {}
        self._backup_refreshing = False
        self._backup_refreshed_at = 0.0
        self.tray = None

        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        root.bind_all("<MouseWheel>", self._on_mousewheel)
        self._poll()
        self.root.after(800, lambda: self.refresh_admin_info(force=True))
        self.refresh_backup_info(force=True)

        if auto_start:
            self.root.after(500, self.start_server)

    # ================================================================ layout
    def _build(self) -> None:
        self.page = PageScroller(self.root, background=WINDOW_BG)
        self.page.pack(fill="both", expand=True)
        content = self.page.content
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self.auto_restart_var = tk.BooleanVar(value=self.settings.auto_restart)
        TitleBar(
            content, icon("server", PRIMARY, 24), "Land Customer System 伺服器控制台",
            f"{CONSOLE_VERSION} · 家中伺服器", self.auto_restart_var, self._on_auto_restart_toggle,
        ).grid(row=0, column=0, sticky="ew")
        body = Box(content, bg=WINDOW_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(16, 20))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)
        self._build_status_bar(body)
        self._build_toolbar(body)
        self._build_info(body)
        self._build_tabs(body)

    def _build_status_bar(self, body) -> None:
        self.status_bar = StatusBar(
            body, lambda: self._show_tab("management"), lambda: self._show_tab("management")
        )
        self.status_bar.grid(row=0, column=0, sticky="ew")

    def _build_toolbar(self, body) -> None:
        bar = Box(body, bg=WINDOW_BG)
        bar.grid(row=1, column=0, sticky="ew", pady=12)
        bar.grid_columnconfigure(6, weight=1)
        self.start_button = CanvasButton(
            bar, "啟動", self._on_start_clicked, "green", "play", width=87, texts=("重新啟動",)
        )
        self.stop_button = CanvasButton(bar, "停止", self.stop_server, "red", "stop", width=87)
        self.restart_button = CanvasButton(bar, "重啟", self.restart_server, "gray", "restart", width=87)
        self.start_button.grid(row=0, column=0)
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.restart_button.grid(row=0, column=2, padx=(8, 0))
        Box(bar, bg=BORDER, width=1, height=28).grid(row=0, column=3, padx=16)
        self.backup_button = CanvasButton(bar, "立即備份", self.backup_now, "gray", texts=("備份中…",))
        self.open_backup_button = CanvasButton(bar, "開啟備份資料夾", self.open_backup_folder, "gray")
        self.backup_button.grid(row=0, column=4)
        self.open_backup_button.grid(row=0, column=5, padx=(8, 0))
        self.open_mobile_button = CanvasButton(bar, "開啟手機網頁", self.open_mobile_page, "blue")
        self.open_mobile_button.grid(row=0, column=7, sticky="e")

    def _build_info(self, body) -> None:
        info = Box(body, bg=WINDOW_BG)
        info.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
        info.grid_columnconfigure(0, minsize=320)
        info.grid_columnconfigure(1, weight=1)
        info.grid_rowconfigure(0, weight=1)

        self.steps_panel = StepsPanel(info, STEP_COUNT)
        self.steps_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        right = Box(info, bg=WINDOW_BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        self.connection_panel = ConnectionPanel(right, self._copy_connection)
        self.connection_panel.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.connection_panel.set_qr("")
        self.copy_buttons = self.connection_panel.copy_buttons
        self.system_panel = SystemPanel(right)
        self.system_panel.grid(row=1, column=0, sticky="ew")

    def _build_tabs(self, body) -> None:
        card = RoundedFrame(body, fill=CARD_BG, border=BORDER, radius=10)
        card.grid(row=3, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        self.tab_bar = TabBar(card, (("log", "日誌"), ("management", "管理")), self._show_tab)
        self.tab_bar.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        self.tab_bar.add_tool(
            CanvasCheck(self.tab_bar, "只看錯誤", self._errors_only, command=self._render_log, bg=CARD_BG), 0
        )
        self.tab_bar.add_tool(
            CanvasButton(self.tab_bar, "複製全部", self._copy_all_logs, "gray", height=32, font_size=12,
                         backdrop=CARD_BG), 12
        )
        self.tab_bar.add_tool(
            CanvasButton(self.tab_bar, "開啟日誌資料夾", self._open_log_folder, "gray", height=32, font_size=12,
                         backdrop=CARD_BG), 8
        )

        holder = Box(card, bg=CARD_BG)
        holder.grid(row=1, column=0, sticky="nsew", padx=1, pady=(0, 1))
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.log_frame = RoundedFrame(holder, fill=LOG_BG, border=None, radius=8)
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_frame, height=1, width=1, bg=LOG_BG, fg=TEXT_SECONDARY,
            font=scaled_font(12.5, family=FONT_MONO), wrap="word", relief="flat", bd=0, highlightthickness=0,
            padx=px(20), pady=px(8), tabs=(px(72), px(121)), spacing1=px(3), spacing3=px(3),
            state="disabled", cursor="arrow",
        )
        log_scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(px(3), 0), pady=px(4))
        log_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, px(3)), pady=px(4))
        self.log_text.tag_configure("row_warning", background="#FDF3DC")
        self.log_text.tag_configure("row_error", background="#FCEBEA")
        self.log_text.tag_configure("time", foreground=TEXT_MUTED)
        for level, color in LEVEL_COLORS.items():
            self.log_text.tag_configure(f"level_{level}", foreground=color)
        self.log_text.tag_configure("text_error", foreground=RED)

        self._pages: dict[str, tk.Widget] = {"log": self.log_frame}
        self.management_holder = Box(holder, bg=CARD_BG)
        self.management: ManagementTab | None = None  # built after the window is shown (see below)
        self._pages["management"] = self.management_holder
        self._current_tab = None
        self._show_tab("log")
        # after_idle: 先讓 Tk 把已建好的畫面畫出來，再過一下下才建管理分頁
        self.root.after_idle(lambda: self.root.after(100, self._ensure_management))

    def _ensure_management(self) -> ManagementTab:
        """The 管理 tab has ~40 native windows; building them after the first paint
        (or the moment the tab is needed) keeps the window from waiting on them."""

        if self.management is None:
            self.management = ManagementTab(self.management_holder, self)
        return self.management

    # ============================================================== tab handling
    def _show_tab(self, key: str) -> None:
        if key == self._current_tab:
            return
        self._current_tab = key
        if key == "management":
            self._ensure_management()
        for name, page in self._pages.items():
            if name == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_forget()
        self.tab_bar.set_active(key)
        self.tab_bar.set_tools_visible(key == "log")
        if key != "log":
            self.refresh_admin_info(force=True)

    def _on_mousewheel(self, event) -> None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        node = widget
        while node is not None:
            if node is self.log_text:
                return
            node = getattr(node, "master", None)
        if self._current_tab == "management" and self.management and self.management.scroller.contains(widget):
            if self.management.scroller.is_scrollable():
                self.management.scroller.scroll(event.delta)
                return
        self.page.scroll(event.delta)

    def _on_auto_restart_toggle(self) -> None:
        self.settings.auto_restart = self.auto_restart_var.get()
        save_settings(self.settings)

    # ================================================================== logging
    @staticmethod
    def _classify_line(line: str) -> str:
        if line.startswith("INFO:"):
            return "info"
        if "WARNING" in line or line.startswith("警告"):
            return "warning"
        if "ERROR" in line or "Traceback" in line:
            return "error"
        return "info"

    def append_log(self, text: str, level: str | None = None) -> None:
        level = level or self._classify_line(text)
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_lines.append((stamp, level, text))
        if self.logger:
            self.logger.info(text)
        if not self._errors_only.get() or level == "error":
            self._write_log_row(stamp, level, text)

    def _write_log_row(self, stamp: str, level: str, text: str) -> None:
        inner = self.log_text
        self.log_text.configure(state="normal")
        row = f"row_{level}" if level in ("warning", "error") else ""
        tags = (row,) if row else ()
        inner.insert("end", f"{stamp}\t", ("time",) + tags)
        inner.insert("end", f"{LEVEL_LABELS.get(level, level)}\t", (f"level_{level}",) + tags)
        inner.insert("end", f"{text}\n", (("text_error",) if level == "error" else ()) + tags)
        inner.see("end")
        self.log_text.configure(state="disabled")

    def _render_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        for stamp, level, text in self._log_lines:
            if not self._errors_only.get() or level == "error":
                self._write_log_row(stamp, level, text)

    def _copy_all_logs(self) -> None:
        self._copy_text("\n".join(f"{stamp}  {LEVEL_LABELS.get(level, level)}  {text}" for stamp, level, text in self._log_lines))

    def _open_log_folder(self) -> None:
        from server_console.paths import console_log_directory

        self._open_folder(console_log_directory())

    # ============================================================== small helpers
    def _copy_text(self, value: str) -> None:
        if value:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)

    def _open_folder(self, path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))  # noqa: S606 - opening a local folder, not a downloaded file

    def _run_job(self, work, done) -> None:
        """Run blocking `work()` off the Tk thread; call `done(result)` back on it."""

        box: dict = {}

        def target():
            try:
                box["value"] = work()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user by `done`
                box["value"] = {"status": "error", "message": str(exc)}

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        def check():
            if thread.is_alive():
                self.root.after(100, check)
            else:
                done(box.get("value"))

        self.root.after(100, check)

    @property
    def account_count(self):
        return self.admin_info.get("account_count")

    # ================================================================= actions
    def _on_start_clicked(self) -> None:
        if self._last_display is not None and self._last_display.status == "error" and self.process.is_alive():
            self.restart_server()
        else:
            self.start_server()

    def start_server(self) -> None:
        if self.process.is_alive() or ProcessManager.is_port_open(timeout=0.5):
            owner = port_owner_pid()
            hint = f"占用程式 PID：{owner}。" if owner else ""
            messagebox.showinfo("家中伺服器控制台", f"伺服器可能已在執行，或有其他程式占用 8732。{hint}")
            return
        self._user_requested_stop = False
        self._starting_at = time.monotonic()
        self._started_wall = datetime.datetime.now().astimezone()
        self._server_pid = None
        self.append_log("[控制台] 正在啟動家中伺服器...")
        self.process.start_runtime()

    def stop_server(self, *, ask_confirm: bool = True, then=None) -> None:
        if ask_confirm and not messagebox.askyesno(
            "停止家中伺服器", "停止後手機與公司筆電會斷線，確定要停止嗎？"
        ):
            return
        self._user_requested_stop = True
        self._is_stopping = True
        self.append_log("[控制台] 正在停止家中伺服器...")
        fallback_pid = self.diagnostics.last_known.get("process_id")

        def done(_result):
            self._is_stopping = False
            self.append_log("[控制台] 家中伺服器已停止。")
            if then:
                then()

        self._run_job(lambda: {"stopped": self.process.stop(fallback_pid=fallback_pid)}, done)

    def restart_server(self) -> None:
        self.stop_server(ask_confirm=False, then=self.start_server)

    def backup_now(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.backup_button.set_label("備份中…")
        self.append_log("[控制台] 正在建立立即備份...")

        def done(result):
            self._busy = False
            self.backup_button.set_label("立即備份")
            result = result or {}
            if result.get("status") == "ok":
                self.append_log("[控制台] 立即備份完成。")
                messagebox.showinfo("立即備份", "備份已完成。")
            else:
                message = result.get("message") or "備份失敗，請查看日誌。"
                self.append_log(f"[控制台] 立即備份失敗：{message}", "error")
                messagebox.showerror("立即備份失敗", message)
            self.refresh_backup_info(force=True)

        self._run_job(backup_client.backup_now, done)

    def open_backup_folder(self) -> None:
        from server_console.paths import backup_directory

        self._open_folder(backup_directory())

    def open_mobile_page(self) -> None:
        url = self._connection_values.get("api_url", "")
        if url:
            webbrowser.open(url)

    def run_management_action(self, action, *, title, success_title, on_done=None) -> None:
        """Stop the server (if running) -> run `action()` -> start it again, always,
        regardless of outcome. Runs off the Tk thread so the window stays alive."""

        if self._busy:
            return
        self._busy = True
        was_running = self.process.is_alive() or ProcessManager.is_port_open(timeout=0.5)
        fallback_pid = self.diagnostics.last_known.get("process_id")
        if was_running:
            self._user_requested_stop = True
            self._is_stopping = True
            self.append_log(f"[控制台] 執行「{title}」前先停止伺服器...")
        else:
            self.append_log(f"[控制台] 執行「{title}」...")

        def work():
            if was_running:
                self.process.stop(fallback_pid=fallback_pid)
            return action()

        def done(result):
            self._busy = False
            self._is_stopping = False
            result = result or {"status": "error", "message": "沒有取得結果。"}
            ok = result.get("status") == "ok"
            message = result.get("message") or ("已完成。" if ok else "發生錯誤。")
            self.append_log(f"[控制台] {title}{'完成' if ok else '失敗'}：{message}", "info" if ok else "error")
            if on_done:
                on_done(result)
            self.refresh_admin_info(force=True)
            self.append_log("[控制台] 管理功能執行完畢，重新啟動伺服器...")
            self._user_requested_stop = False
            self.start_server()
            (messagebox.showinfo if ok else messagebox.showerror)(success_title if ok else f"{title}失敗", message)

        self._run_job(work, done)

    # ============================================================ data refresh
    def refresh_admin_info(self, force: bool = False) -> None:
        if self._admin_refreshing or self._busy:
            return
        if not force and time.monotonic() - self._admin_refreshed_at < 60:
            return
        self._admin_refreshing = True

        def done(result):
            self._admin_refreshing = False
            self._admin_refreshed_at = time.monotonic()
            if isinstance(result, dict) and result.get("status") == "ok":
                self.admin_info = {
                    "account_count": result.get("account_count"),
                    "admins": list(result.get("admins") or []),
                }

        self._run_job(admin_client.list_admins, done)

    def refresh_backup_info(self, force: bool = False) -> None:
        if self._backup_refreshing:
            return
        if not force and time.monotonic() - self._backup_refreshed_at < 30:
            return
        self._backup_refreshing = True

        def done(result):
            self._backup_refreshing = False
            self._backup_refreshed_at = time.monotonic()
            if isinstance(result, dict) and result.get("status") in ("ok", "warning"):
                self.backup_info = result

        self._run_job(backup_client.backup_status, done)

    # =============================================================== polling
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
            except Exception:  # noqa: BLE001 - queue.Empty
                break
            if line is None or not line.strip():
                continue
            if _PS1_STEP_HEADER.match(line):
                continue  # 步驟燈號由診斷檔的 steps 產生，避免日誌重複
            match = _SERVER_PID.search(line)
            if match:
                self._server_pid = int(match.group(1))
            self.append_log(line)

    def _update_state(self) -> None:
        diagnostics = self.diagnostics.read()
        process_alive = self.process.is_alive()
        port_open = bool(self.port_monitor.is_open())
        startup_elapsed = time.monotonic() - self._starting_at if self._starting_at is not None else None
        display = compute_display_state(
            diagnostics, process_alive=process_alive, port_open=port_open,
            is_stopping=self._is_stopping, startup_elapsed_seconds=startup_elapsed,
            started_at=self._started_wall,
        )
        if display.status in RUNNING_STATUSES:
            self._starting_at = None
            if self._server_pid is None and not self._pid_lookup_running:
                self._pid_lookup_running = True

                def found(result):
                    self._pid_lookup_running = False
                    if isinstance(result, dict) and result.get("pid"):
                        self._server_pid = result["pid"]

                self._run_job(lambda: {"pid": port_owner_pid()}, found)
        else:
            self._server_pid = None

        previous = self._last_status
        self._render_status(display)
        self._log_step_transitions(display)
        self._render_steps(display)
        self._render_connection(diagnostics, display)
        self._render_system(diagnostics, display)
        self._render_buttons(display, process_alive)
        if self.management is not None:
            self.management.refresh(
                account_count=self._effective_account_count(diagnostics, display),
                admins=self.admin_info.get("admins"), busy=self._busy,
            )
        if display.status == "no_accounts" and previous != "no_accounts":
            self.append_log("資料庫尚無帳號：請建立第一個管理員，或匯入遷移包。", "warning")
            self._show_tab("management")
        self._handle_unexpected_stop(display.status)
        if not self._busy:
            self.refresh_admin_info()
            self.refresh_backup_info()
        self._last_status = display.status
        self._last_display = display
        if self.tray:
            self.tray.set_status(display.status)

    def _effective_account_count(self, diagnostics, display):
        if display.status in RUNNING_STATUSES and diagnostics.get("account_count") is not None:
            return diagnostics.get("account_count")
        return self.admin_info.get("account_count")

    # ============================================================== rendering
    def _changed(self, name: str, signature) -> bool:
        if self._signatures.get(name) == signature:
            return False
        self._signatures[name] = signature
        return True

    def _render_status(self, display) -> None:
        pid_text = f"PID {self._server_pid} · :8732" if self._server_pid else ""
        if not self._changed("status", (display.status, display.title, display.reason, pid_text)):
            return
        self.status_bar.set_state(display.status, display.title, display.reason, pid_text)

    def _render_steps(self, display) -> None:
        signature = tuple((step.status, step.name, step.reason) for step in display.steps)
        if not self._changed("steps", signature):
            return
        self.steps_panel.set_rows(display.steps)

    def _log_step_transitions(self, display) -> None:
        current = {step.n: step.status for step in display.steps}
        if display.status in ("not_started", "stopping"):
            self._step_snapshot = dict(current)
            return
        if self._step_snapshot is None:
            self._step_snapshot = dict(current)
            return
        for step in display.steps:
            if self._step_snapshot.get(step.n) != step.status:
                if step.n == STEP_COUNT and step.status == "done":
                    continue
                entry = step_log_line(step)
                if entry:
                    self.append_log(entry[1], entry[0])
        self._step_snapshot = dict(current)

    def _render_connection(self, diagnostics, display) -> None:
        running = display.status in RUNNING_STATUSES
        values = {
            key: (str(diagnostics.get(key) or "") if running else "")
            for key in ("api_url", "certificate_url", "certificate_sha256", "netbird_ip")
        }
        self._connection_values = values
        if not self._changed("connection", (running, tuple(values.items()))):
            return
        self.connection_panel.set_values(values)
        self.connection_panel.set_qr(values["api_url"] if running else "")

    def _render_system(self, diagnostics, display) -> None:
        running = display.status in RUNNING_STATUSES
        snapshot = self.services.snapshot()
        if snapshot is None:
            service = diagnostics.get("postgresql_service") or "—"
            state = diagnostics.get("postgresql_status") or ""
        else:
            service, state = snapshot
        installed = snapshot is None or service is not None
        backup_text = "—"
        if self.backup_info.get("latest_backup_at"):
            try:
                moment = datetime.datetime.fromisoformat(self.backup_info["latest_backup_at"]).astimezone()
                backup_text = f"{moment:%Y-%m-%d %H:%M} · 共 {self.backup_info.get('backup_count', 0)} 份"
            except ValueError:
                backup_text = "—"
        account_count = diagnostics.get("account_count") if running else None
        record_count = diagnostics.get("record_count") if running else None
        database = diagnostics.get("database_status") if running else None
        signature = (
            service, state, installed, running, backup_text, account_count, record_count, database,
        )
        if not self._changed("system", signature):
            return
        panel = self.system_panel
        panel.set_value("service", (service or "未安裝") if installed else "未安裝", TEXT if installed else RED)
        if not installed or not state:
            panel.set_value("service_state", "—")
        else:
            note = "（伺服器已停）" if state == "Running" and not running else ""
            panel.set_value("service_state", f"{state}{note}", GREEN if state == "Running" else RED)
        panel.set_value(
            "database", ("正常" if database == "ok" else str(database)) if database else "—",
            GREEN if database == "ok" else TEXT,
        )
        if account_count is None:
            panel.set_value("accounts", "—")
        elif account_count == 0:
            panel.set_value("accounts", "0（需要建立）", BROWN)
        else:
            panel.set_value("accounts", str(account_count))
        panel.set_value("records", "—" if record_count is None else str(record_count))
        panel.set_value("backup", backup_text)

    def _render_buttons(self, display, process_alive: bool) -> None:
        status = display.status
        busy = self._busy
        stuck = status == "error" and process_alive
        signature = (status, busy, stuck)
        if not self._changed("buttons", signature):
            return
        self.start_button.set_label("重新啟動" if stuck else "啟動")
        self.start_button.set_enabled(not busy and status in ("not_started", "error"))
        running = status in RUNNING_STATUSES
        self.stop_button.set_enabled(not busy and running)
        self.restart_button.set_enabled(not busy and running)
        self.open_mobile_button.set_enabled(running)
        self.backup_button.set_enabled(not busy and status != "stopping")
        self.open_backup_button.set_enabled(True)

    def _copy_connection(self, key: str) -> None:
        value = self._connection_values.get(key, "")
        if not value:
            return
        self._copy_text(value)
        button = self.copy_buttons[key]
        button.set_label("已複製")
        self.root.after(2000, lambda: button.set_label("複製"))

    # ====================================================== auto-restart on stop
    def _handle_unexpected_stop(self, status: str) -> None:
        was_running = self._last_status in RUNNING_STATUSES
        stopped_unexpectedly = was_running and status in ("error", "not_started") and not self._user_requested_stop
        if not stopped_unexpectedly:
            return
        if self.tray:
            self.tray.notify("家中伺服器控制台", "伺服器意外停止。")
        if not self.settings.auto_restart:
            return
        now = time.monotonic()
        self._restart_timestamps = [t for t in self._restart_timestamps if now - t < AUTO_RESTART_WINDOW_SECONDS]
        if len(self._restart_timestamps) >= AUTO_RESTART_MAX_ATTEMPTS:
            self.append_log("[控制台] 10 分鐘內已自動重啟 3 次，停止重試。", "error")
            if self.tray:
                self.tray.notify("家中伺服器控制台", "自動重啟已達上限，請手動檢查。")
            return
        self._restart_timestamps.append(now)
        self.append_log("[控制台] 偵測到伺服器意外停止，將自動重新啟動。", "warning")
        self.root.after(1000, self.start_server)

    # =========================================================== window / tray
    def _on_close_button(self) -> None:
        self.root.withdraw()
        if not self._shown_tray_hint:
            self._shown_tray_hint = True
            if self.tray:
                self.tray.notify(
                    "家中伺服器控制台", "控制台已縮到系統匣，伺服器仍在背景執行。點兩下圖示可再打開。"
                )

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_application(self) -> None:
        def finish():
            if self.tray:
                self.tray.stop()
            self.root.after(200, self.root.destroy)

        if self.process.is_alive() or ProcessManager.is_port_open(timeout=0.5):
            if messagebox.askyesno("結束控制台", "是否同時停止家中伺服器？選「否」會保留伺服器繼續執行。"):
                self.stop_server(ask_confirm=False, then=finish)
                return
        finish()
