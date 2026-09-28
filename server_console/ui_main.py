"""Main window: status bar, toolbar, info panels, log/management tabs."""

from __future__ import annotations

import os
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from server_console import backup_client
from server_console.diagnostics import STARTUP_STAGES, DiagnosticsReader
from server_console.process_manager import CREATE_NO_WINDOW, ProcessManager
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

STATUS_COLORS = {
    "not_started": "#e0e0e0",
    "starting": "#e3f2fd",
    "running": "#e8f5e9",
    "error": "#ffebee",
    "stopping": "#e0e0e0",
}
STATUS_TEXT_COLORS = {
    "not_started": "#616161",
    "starting": "#1565c0",
    "running": "#2e7d32",
    "error": "#c62828",
    "stopping": "#616161",
}
STATUS_LABELS = {
    "not_started": "未啟動",
    "starting": "啟動中",
    "running": "運作中",
    "error": "錯誤",
    "stopping": "停止中",
}
STAGE_LABELS = {key: label for key, label in STARTUP_STAGES}
STAGE_ORDER = [key for key, _label in STARTUP_STAGES]


class ConsoleApp:
    def __init__(self, root: tk.Tk, *, auto_start: bool = False):
        self.root = root
        self.root.title("家中伺服器控制台")
        self.root.geometry("1000x680")
        self.root.minsize(820, 560)

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
    def _build_widgets(self) -> None:
        self.status_frame = tk.Frame(self.root, height=56)
        self.status_frame.pack(fill="x")
        self.status_label = tk.Label(
            self.status_frame, text="未啟動", font=("Microsoft JhengHei UI", 16, "bold"),
            anchor="w", padx=16,
        )
        self.status_label.pack(side="left", fill="both", expand=True)
        self.reason_label = tk.Label(
            self.status_frame, text="", font=("Microsoft JhengHei UI", 10), anchor="e", padx=16,
        )
        self.reason_label.pack(side="right")

        toolbar = tk.Frame(self.root)
        toolbar.pack(fill="x", padx=8, pady=4)
        self.start_button = ttk.Button(toolbar, text="啟動", command=self.start_server)
        self.stop_button = ttk.Button(toolbar, text="停止", command=self.stop_server)
        self.restart_button = ttk.Button(toolbar, text="重啟", command=self.restart_server)
        self.backup_button = ttk.Button(toolbar, text="立即備份", command=self.backup_now)
        self.open_backup_button = ttk.Button(
            toolbar, text="開啟備份資料夾", command=self.open_backup_folder
        )
        self.open_mobile_button = ttk.Button(
            toolbar, text="開啟手機網頁", command=self.open_mobile_page
        )
        for button in (
            self.start_button, self.stop_button, self.restart_button,
            self.backup_button, self.open_backup_button, self.open_mobile_button,
        ):
            button.pack(side="left", padx=4)

        info = tk.Frame(self.root)
        info.pack(fill="x", padx=8, pady=4)
        info.columnconfigure(0, weight=1)
        info.columnconfigure(1, weight=1)

        steps_frame = ttk.LabelFrame(info, text="啟動步驟")
        steps_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.step_labels: dict[str, tk.Label] = {}
        for key, label in STARTUP_STAGES:
            row = tk.Frame(steps_frame)
            row.pack(fill="x", padx=8, pady=2, anchor="w")
            dot = tk.Label(row, text="○", width=2, fg="#9e9e9e")
            dot.pack(side="left")
            text = tk.Label(row, text=label)
            text.pack(side="left")
            self.step_labels[key] = dot

        right_frame = tk.Frame(info)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right_frame.columnconfigure(0, weight=1)

        connection_frame = ttk.LabelFrame(right_frame, text="連線資訊")
        connection_frame.pack(fill="x", pady=(0, 4))
        self.connection_vars = {
            "api_url": tk.StringVar(value="—"),
            "certificate_url": tk.StringVar(value="—"),
            "certificate_sha256": tk.StringVar(value="—"),
            "netbird_ip": tk.StringVar(value="—"),
        }
        for key, caption in (
            ("api_url", "手機網址"),
            ("certificate_url", "iPhone 憑證網址"),
            ("certificate_sha256", "公開 CA SHA-256"),
            ("netbird_ip", "NetBird IP"),
        ):
            row = tk.Frame(connection_frame)
            row.pack(fill="x", padx=6, pady=1)
            tk.Label(row, text=caption, width=12, anchor="w").pack(side="left")
            entry = tk.Entry(row, textvariable=self.connection_vars[key], state="readonly")
            entry.pack(side="left", fill="x", expand=True)
            ttk.Button(
                row, text="複製", width=5,
                command=lambda k=key: self._copy_to_clipboard(self.connection_vars[k].get()),
            ).pack(side="left", padx=2)

        qr_frame = tk.Frame(connection_frame)
        qr_frame.pack(fill="x", padx=6, pady=(2, 6))
        self.qr_label = tk.Label(qr_frame, text="（伺服器運作中才會顯示手機網址 QR Code）")
        self.qr_label.pack(side="left")

        system_frame = ttk.LabelFrame(right_frame, text="系統狀態")
        system_frame.pack(fill="x")
        self.system_vars = {
            key: tk.StringVar(value="—")
            for key in (
                "postgresql_service", "database_status", "schema_version",
                "record_count", "backup_summary",
            )
        }
        for key, caption in (
            ("postgresql_service", "PostgreSQL 服務"),
            ("database_status", "資料庫狀態"),
            ("schema_version", "結構版本"),
            ("record_count", "資料筆數"),
            ("backup_summary", "最後備份"),
        ):
            row = tk.Frame(system_frame)
            row.pack(fill="x", padx=6, pady=1)
            tk.Label(row, text=caption, width=12, anchor="w").pack(side="left")
            tk.Label(row, textvariable=self.system_vars[key], anchor="w").pack(side="left")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=4)

        log_tab = tk.Frame(notebook)
        notebook.add(log_tab, text="日誌")
        log_toolbar = tk.Frame(log_tab)
        log_toolbar.pack(fill="x")
        ttk.Checkbutton(
            log_toolbar, text="只看錯誤", variable=self._errors_only,
            command=self._render_log,
        ).pack(side="left")
        ttk.Button(log_toolbar, text="複製全部", command=self._copy_all_logs).pack(
            side="left", padx=4
        )
        ttk.Button(log_toolbar, text="開啟日誌資料夾", command=self._open_log_folder).pack(
            side="left"
        )
        self.log_text = tk.Text(log_tab, wrap="word", state="disabled")
        self.log_text.tag_configure("warning", foreground="#f9a825")
        self.log_text.tag_configure("error", foreground="#c62828")
        self.log_text.pack(fill="both", expand=True)

        from server_console.ui_dialogs import build_management_tab

        management_tab = tk.Frame(notebook)
        notebook.add(management_tab, text="管理")
        build_management_tab(management_tab, self)

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
        self.log_text.configure(state="normal")
        tag = level if level in ("warning", "error") else None
        if tag:
            self.log_text.insert("end", line + "\n", tag)
        else:
            self.log_text.insert("end", line + "\n")
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
        self._update_system_status(diagnostics)
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
        label = STATUS_LABELS.get(status, status)
        self.status_label.configure(
            text=label,
            bg=STATUS_COLORS.get(status, "#e0e0e0"),
            fg=STATUS_TEXT_COLORS.get(status, "#212121"),
        )
        self.status_frame.configure(bg=STATUS_COLORS.get(status, "#e0e0e0"))
        self.reason_label.configure(text=reason, bg=STATUS_COLORS.get(status, "#e0e0e0"))

    def _update_steps(self, diagnostics: dict, display) -> None:
        current_stage = diagnostics.get("stage") or ""
        failed = display.status == "error"
        reached_index = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
        signature = (display.status, reached_index, failed)
        if getattr(self, "_applied_steps_signature", None) == signature:
            return
        self._applied_steps_signature = signature
        for index, key in enumerate(STAGE_ORDER):
            dot = self.step_labels[key]
            if display.status == "running":
                dot.configure(text="●", fg="#2e7d32")
            elif index < reached_index:
                dot.configure(text="●", fg="#2e7d32")
            elif index == reached_index:
                if failed:
                    dot.configure(text="✕", fg="#c62828")
                else:
                    dot.configure(text="●", fg="#1565c0")
            else:
                dot.configure(text="○", fg="#9e9e9e")

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
            self.qr_image = None
            self.qr_label.configure(image="", text="（伺服器運作中才會顯示手機網址 QR Code）")
            return
        try:
            from server_console.qrcode_widget import qr_photo_image

            self.qr_image = qr_photo_image(url)
            self.qr_label.configure(image=self.qr_image, text="")
        except Exception:
            pass

    def _update_system_status(self, diagnostics: dict) -> None:
        service = diagnostics.get("postgresql_service") or "—"
        status = diagnostics.get("postgresql_status") or ""
        self._set_var_if_changed(
            self.system_vars["postgresql_service"],
            f"{service}（{status}）" if status else service,
        )
        self._set_var_if_changed(
            self.system_vars["database_status"], diagnostics.get("database_status") or "—"
        )
        self._set_var_if_changed(
            self.system_vars["schema_version"], str(diagnostics.get("schema_version") or "—")
        )
        account_count = diagnostics.get("account_count")
        record_count = diagnostics.get("record_count")
        parts = []
        if record_count is not None:
            parts.append(f"{record_count} 筆地主")
        if account_count is not None:
            parts.append(f"{account_count} 個帳號")
        self._set_var_if_changed(self.system_vars["record_count"], "、".join(parts) if parts else "—")
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
        self.start_button.configure(state="disabled" if running_like else "normal")
        self.stop_button.configure(state="normal" if running_like else "disabled")
        self.restart_button.configure(state="normal" if status == "running" else "disabled")
        self.backup_button.configure(state="normal" if status == "running" else "disabled")
        self.open_mobile_button.configure(state="normal" if status == "running" else "disabled")

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
