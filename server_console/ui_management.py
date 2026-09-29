"""管理 tab: three equal cards side by side (建立第一個管理員 / 管理員密碼恢復 /
匯入遷移包), forms inline, per 伺服器控制台_畫面規格.md.

Passwords live only in Tk variables that are cleared the moment the payload is
built; nothing here logs them.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from server_console import admin_client, migration_client
from server_console.last_import import load_last_import_text, save_last_import
from server_console.paths import package_root
from server_console.ui_theme import (
    BORDER, BROWN, CARD_BG, GRAY_BG, PRIMARY, TEXT, TEXT_MUTED, TEXT_SECONDARY, px, scaled_font,
)
from server_console.ui_widgets import (
    Box, CanvasButton, Dropdown, Label, PageScroller, RoundedEntry, RoundedFrame, ellipsize,
)

MIN_PASSWORD_LENGTH = 10
PLACEHOLDER_NO_ADMIN = "（沒有可選的管理員）"


def pending_migration_package() -> Path | None:
    matches = sorted(package_root().glob(f"*{migration_client.PACKAGE_SUFFIX}"))
    return matches[0] if matches else None


class _Field:
    """label (12px, above) + entry (34px, radius 6)."""

    def __init__(self, parent, label, *, secret=False, placeholder="", hint=""):
        self.frame = Box(parent)
        Label(self.frame, label, 12, color=TEXT_SECONDARY).pack(fill="x", pady=(0, 3))
        self.var = tk.StringVar()
        self.input = RoundedEntry(self.frame, self.var, secret=secret, placeholder=placeholder)
        self.input.pack(fill="x")
        self.entry = self.input.entry
        if hint:
            Label(self.frame, hint, 12, color=TEXT_MUTED, wraplength=260).pack(fill="x", pady=(3, 0))

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def get(self):
        return self.var.get()

    def clear(self):
        self.var.set("")


class _Card(RoundedFrame):
    def __init__(self, parent, title, description):
        super().__init__(parent, fill=CARD_BG, border=BORDER, radius=10)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        Label(self, title, 15, "bold").grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        self.description = Label(self, description, 12, color=TEXT_SECONDARY, wraplength=240)
        self.description.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.body = Box(self)
        self.body.grid(row=2, column=0, sticky="nsew", padx=16)
        self.footer = Box(self)
        self.footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(10, 14))
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event):
        self.description.set_wrap_px(max(px(120), event.width - 2 * px(16)))


class _Notice(RoundedFrame):
    """Grey rounded note ("資料庫已有帳號，此功能停用。")."""

    def __init__(self, parent):
        super().__init__(parent, fill=GRAY_BG, border=None, radius=8)
        self.label = Label(self, "", 13, color=TEXT_SECONDARY, wraplength=240)
        self.label.pack(fill="x", padx=12, pady=12)
        self.bind("<Configure>", lambda event: self.label.set_wrap_px(max(px(80), event.width - 2 * px(12))), add="+")

    def set_text(self, text):
        self.label.configure(text=text)


class ManagementTab:
    def __init__(self, parent, app):
        self.app = app
        self.scroller = PageScroller(parent, background=CARD_BG)
        self.scroller.pack(fill="both", expand=True)
        content = self.scroller.content
        content.configure(bg=CARD_BG)
        for column in range(3):
            content.grid_columnconfigure(column, weight=1, uniform="cards")
        content.grid_rowconfigure(0, weight=1)
        self._build_bootstrap(content)
        self._build_recover(content)
        self._build_import(content)
        self._last_signature = None

    # ------------------------------------------------------------------ cards
    def _build_bootstrap(self, content):
        self.bootstrap_card = _Card(
            content, "建立第一個管理員",
            "僅在資料庫沒有任何帳號時可用。若要匯入遷移包，請先匯入，不要建立管理員。",
        )
        self.bootstrap_card.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self.bootstrap_username = _Field(
            self.bootstrap_card.body, "管理員帳號", placeholder="例如 chen.office",
            hint="建議不要使用 admin 等容易猜到的名稱",
        )
        self.bootstrap_password = _Field(
            self.bootstrap_card.body, "密碼（至少 10 個字元）", secret=True
        )
        self.bootstrap_confirm = _Field(self.bootstrap_card.body, "再次輸入密碼", secret=True)
        self.bootstrap_fields = (self.bootstrap_username, self.bootstrap_password, self.bootstrap_confirm)
        self.bootstrap_notice = _Notice(self.bootstrap_card.body)
        self.bootstrap_button = CanvasButton(
            self.bootstrap_card.footer, "建立管理員", self._submit_bootstrap, "primary", backdrop=CARD_BG
        )
        self.bootstrap_button.pack(fill="x")

    def _build_recover(self, content):
        self.recover_card = _Card(
            content, "管理員密碼恢復",
            "驗證用帳號必須是目前可登入的其他帳號。失敗時原密碼與正式資料都不會修改。",
        )
        self.recover_card.grid(row=0, column=1, sticky="nsew", padx=6, pady=12)
        body = self.recover_card.body
        picker = Box(body)
        picker.pack(fill="x", pady=(0, 8))
        Label(picker, "要重設的管理員帳號", 12, color=TEXT_SECONDARY).pack(fill="x", pady=(0, 3))
        self.recover_target = Dropdown(picker, [PLACEHOLDER_NO_ADMIN])
        self.recover_target.pack(fill="x")
        self.recover_verify_user = _Field(body, "驗證用帳號")
        self.recover_verify_password = _Field(body, "該帳號密碼", secret=True)
        self.recover_new = _Field(body, "新密碼（至少 10 個字元）", secret=True)
        self.recover_confirm = _Field(body, "再次輸入新密碼", secret=True)
        for field in (self.recover_verify_user, self.recover_verify_password, self.recover_new, self.recover_confirm):
            field.pack(fill="x", pady=(0, 8))
        self.recover_button = CanvasButton(
            self.recover_card.footer, "執行恢復", self._submit_recover, "dark", backdrop=CARD_BG
        )
        self.recover_button.pack(fill="x")

    def _build_import(self, content):
        self.import_card = _Card(
            content, "匯入遷移包",
            "從單機版或舊主機匯出的遷移包。匯入前會先建立安全備份，完成後自動重新啟動。",
        )
        self.import_card.grid(row=0, column=2, sticky="nsew", padx=(6, 12), pady=12)
        body = self.import_card.body
        self.selected_package: Path | None = None
        self.file_box = tk.Canvas(body, height=px(44), bg=CARD_BG, highlightthickness=0, bd=0)
        self.file_box.pack(fill="x")
        self.file_box.bind("<Configure>", lambda _e: self._draw_file_box())
        CanvasButton(body, "選擇檔案…", self._choose_file, "gray", height=34, font_size=13,
                     backdrop=CARD_BG).pack(anchor="w", pady=(10, 0))
        self.last_import_label = Label(body, "上次匯入：—", 12, color=TEXT_SECONDARY)
        self.last_import_label.pack(fill="x", pady=(12, 0))
        self.import_button = CanvasButton(
            self.import_card.footer, "匯入並重新啟動", self._submit_import, "dark", backdrop=CARD_BG
        )
        self.import_button.pack(fill="x")
        self.refresh_last_import()

    def _draw_file_box(self):
        canvas = self.file_box
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 4 or height <= 4:
            return
        font = scaled_font(13)
        canvas.create_rectangle(2, 2, width - 2, height - 2, outline="#9AA1A9", dash=(px(5), px(4)))
        text = self.selected_package.name if self.selected_package else "尚未選擇"
        max_chars = max(6, (width - 2 * px(12)) // max(1, font.measure("0")))
        canvas.create_text(
            px(12), height // 2, anchor="w", text=ellipsize(text, max_chars), font=font,
            fill=TEXT if self.selected_package else TEXT_MUTED,
        )

    # ------------------------------------------------------------------ state
    def refresh(self, *, account_count, admins, busy):
        """Called by the app whenever account/admin info or busy state changes."""

        pending = pending_migration_package()
        signature = (account_count, tuple(admins or ()), busy, pending)
        if signature == self._last_signature:
            return
        self._last_signature = signature

        for field in self.bootstrap_fields:
            field.frame.pack_forget()
        self.bootstrap_notice.pack_forget()
        if pending is not None:
            self._bootstrap_state("disabled", f"偵測到待匯入的遷移包（{pending.name}），請先匯入遷移包。")
        elif account_count == 0:
            self._bootstrap_state("ready", "")
        elif account_count is None:
            self._bootstrap_state("disabled", "尚未取得帳號資料，請確認 PostgreSQL 服務正在執行。")
        else:
            self._bootstrap_state("disabled", "資料庫已有帳號，此功能停用。")
        self.bootstrap_button.set_enabled(account_count == 0 and pending is None and not busy)

        values = list(admins) if admins else [PLACEHOLDER_NO_ADMIN]
        self.recover_target.configure_values(values)
        if self.recover_target.get() not in values:
            self.recover_target.set(values[0])
        self.recover_button.set_enabled(bool(admins) and not busy)
        self.import_button.set_enabled(not busy)

    def _bootstrap_state(self, mode, note):
        ready = mode == "ready"
        self.bootstrap_card.set_colors(border=PRIMARY if ready else BORDER)
        if ready:
            for field in self.bootstrap_fields:
                field.pack(fill="x", pady=(0, 8))
        else:
            self.bootstrap_notice.set_text(note)
            self.bootstrap_notice.pack(fill="x", pady=(4, 0))

    def refresh_last_import(self):
        self.last_import_label.configure(text=f"上次匯入：{load_last_import_text()}")

    # ---------------------------------------------------------------- actions
    @staticmethod
    def _too_short(password):
        return len(password) < MIN_PASSWORD_LENGTH

    def _submit_bootstrap(self):
        username = self.bootstrap_username.get().strip()
        password, confirm = self.bootstrap_password.get(), self.bootstrap_confirm.get()
        if not username:
            messagebox.showerror("建立第一個管理員", "請輸入管理員帳號。")
            return
        if self._too_short(password):
            messagebox.showerror("建立第一個管理員", "密碼至少需要 10 個字元。")
            return
        if password != confirm:
            messagebox.showerror("建立第一個管理員", "兩次輸入的密碼不一致。")
            return
        for field in self.bootstrap_fields:
            field.clear()
        self.app.run_management_action(
            lambda: admin_client.bootstrap_first_admin(username, password),
            title="建立第一個管理員", success_title="建立完成",
        )

    def _submit_recover(self):
        target = self.recover_target.get()
        verify_user = self.recover_verify_user.get().strip()
        verify_password = self.recover_verify_password.get()
        new_password, confirm = self.recover_new.get(), self.recover_confirm.get()
        if target == PLACEHOLDER_NO_ADMIN:
            messagebox.showerror("管理員密碼恢復", "目前沒有可以重設的管理員。")
            return
        if not verify_user or not verify_password:
            messagebox.showerror("管理員密碼恢復", "驗證用帳號與密碼皆為必填。")
            return
        if self._too_short(new_password):
            messagebox.showerror("管理員密碼恢復", "新密碼至少需要 10 個字元。")
            return
        if new_password != confirm:
            messagebox.showerror("管理員密碼恢復", "兩次輸入的新密碼不一致。")
            return
        for field in (self.recover_verify_user, self.recover_verify_password, self.recover_new, self.recover_confirm):
            field.clear()
        self.app.run_management_action(
            lambda: admin_client.recover_admin_password(target, verify_user, verify_password, new_password),
            title="管理員密碼恢復", success_title="密碼已重設",
        )

    def _choose_file(self):
        chosen = filedialog.askopenfilename(
            title="選擇遷移包",
            filetypes=[("Land Customer System 遷移包", f"*{migration_client.PACKAGE_SUFFIX}")],
        )
        if chosen:
            self.selected_package = Path(chosen)
            self._draw_file_box()

    def _submit_import(self):
        package = self.selected_package
        if package is None:
            messagebox.showerror("匯入遷移包", "請先選擇遷移包檔案。")
            return
        error = migration_client.validate_package_file(package)
        if error:
            messagebox.showerror("匯入遷移包", error)
            return
        if not messagebox.askyesno(
            "匯入遷移包", "將以遷移包內容建立正式資料，匯入前會先建立安全備份，完成後會自動重新啟動伺服器，確定要匯入嗎？"
        ):
            return
        credentials = ImportCredentialsDialog(self.app.root, self.app.account_count)
        self.app.root.wait_window(credentials)
        if credentials.result is None:
            return
        source_user, source_password, server_user, server_password = credentials.result
        credentials.result = None

        def action():
            return admin_client.import_migration_package(
                str(package), source_user, source_password, server_user, server_password
            )

        def after(result):
            if result.get("status") == "ok":
                save_last_import(package.name)
                self.refresh_last_import()

        self.app.run_management_action(action, title="匯入遷移包", success_title="匯入完成", on_done=after)


class ImportCredentialsDialog(tk.Toplevel):
    """Asks for the four values migration-import needs. With zero accounts only
    the standalone admin account is needed (it becomes the server admin)."""

    def __init__(self, master, account_count):
        super().__init__(master)
        self.withdraw()
        self.result = None
        self.title("匯入遷移包 · 帳號驗證")
        self.configure(bg=CARD_BG)
        self.resizable(False, False)
        self.transient(master)
        empty = account_count == 0
        intro = (
            "資料庫目前沒有任何帳號。請輸入單機版的管理員帳號與密碼；匯入後這個帳號會成為伺服器的管理員，單機版其他帳號也會一併帶入。"
            if empty else
            "請輸入單機版帳號密碼（用來解開遷移包），以及家中伺服器管理員的帳號密碼（用來授權匯入）。"
            if account_count else
            "請輸入單機版帳號密碼。若伺服器資料庫已經有帳號，還需要填家中伺服器管理員的帳號密碼；資料庫完全空白則不用。"
        )
        Label(self, intro, 13, color=TEXT_SECONDARY, wraplength=380, bg=CARD_BG).pack(
            fill="x", padx=20, pady=(18, 8)
        )
        self.source_user = _Field(self, "單機版帳號")
        self.source_password = _Field(self, "單機版密碼", secret=True)
        self.source_user.pack(fill="x", padx=20, pady=(0, 8))
        self.source_password.pack(fill="x", padx=20, pady=(0, 8))
        self.server_fields = ()
        if not empty:
            self.server_user = _Field(self, "家中伺服器管理員帳號")
            self.server_password = _Field(self, "家中伺服器管理員密碼", secret=True)
            self.server_fields = (self.server_user, self.server_password)
            for field in self.server_fields:
                field.pack(fill="x", padx=20, pady=(0, 8))
        buttons = Box(self, bg=CARD_BG)
        buttons.pack(fill="x", padx=20, pady=(6, 18))
        CanvasButton(buttons, "開始匯入", self._accept, "primary", height=40, backdrop=CARD_BG).pack(side="right")
        CanvasButton(buttons, "取消", self.destroy, "gray", height=40, backdrop=CARD_BG).pack(side="right", padx=(0, 8))
        self._center(master)
        self.deiconify()
        self.after(150, self._grab)

    def _center(self, master):
        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 3)
        self.geometry(f"+{x}+{y}")

    def _grab(self):
        try:
            self.grab_set()
            self.source_user.entry.focus_set()
        except tk.TclError:
            pass

    def _accept(self):
        source_user = self.source_user.get().strip()
        source_password = self.source_password.get()
        server_user = self.server_user.get().strip() if self.server_fields else ""
        server_password = self.server_password.get() if self.server_fields else ""
        if not source_user or not source_password:
            messagebox.showerror("匯入遷移包", "單機版帳號與密碼皆為必填。", parent=self)
            return
        self.result = (source_user, source_password, server_user, server_password)
        for field in (self.source_user, self.source_password, *self.server_fields):
            field.clear()
        self.destroy()
