"""The 管理 tab: admin 密碼恢復, 匯入遷移包, 建立第一個管理員.

Shared rules from the spec, applied by every dialog here:
- password fields are masked with a 顯示 toggle
- a new password must be entered twice and be at least 10 characters,
  checked client-side before anything is sent
- every password Tk variable is cleared immediately after building the
  stdin payload, whether the call succeeds or fails
- the result is always shown as a Chinese message box
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from server_console import admin_client, migration_client
from server_console.paths import package_root


def build_management_tab(parent: tk.Frame, app) -> None:
    tk.Label(
        parent,
        text="以下三個功能只在這台家中主機本機執行，不經過網路；密碼只會經由標準輸入傳給程式，"
        "不會出現在畫面以外的地方。",
        wraplength=700, justify="left", anchor="w",
    ).pack(fill="x", padx=8, pady=8)

    recover_frame = ttk.LabelFrame(parent, text="admin 密碼恢復")
    recover_frame.pack(fill="x", padx=8, pady=4)
    tk.Label(
        recover_frame,
        text="驗證用帳號必須是目前可登入的其他帳號。", anchor="w",
    ).pack(fill="x", padx=8, pady=(4, 0))
    ttk.Button(
        recover_frame, text="開始密碼恢復...",
        command=lambda: AdminRecoverDialog(app),
    ).pack(anchor="w", padx=8, pady=8)

    migration_frame = ttk.LabelFrame(parent, text="匯入遷移包")
    migration_frame.pack(fill="x", padx=8, pady=4)
    ttk.Button(
        migration_frame, text="選擇遷移包並匯入...",
        command=lambda: MigrationImportDialog(app),
    ).pack(anchor="w", padx=8, pady=8)

    bootstrap_frame = ttk.LabelFrame(parent, text="建立第一個管理員")
    bootstrap_frame.pack(fill="x", padx=8, pady=4)
    bootstrap_reason = tk.Label(bootstrap_frame, text="", fg="#c62828", anchor="w")
    bootstrap_reason.pack(fill="x", padx=8)
    bootstrap_button = ttk.Button(
        bootstrap_frame, text="建立第一個管理員 (admin)...",
        command=lambda: AdminBootstrapDialog(app),
    )
    bootstrap_button.pack(anchor="w", padx=8, pady=8)

    def refresh() -> None:
        diagnostics = app.diagnostics.last_known
        account_count = diagnostics.get("account_count")
        pending_migration = _find_pending_migration_package() is not None
        if pending_migration:
            bootstrap_button.configure(state="disabled")
            bootstrap_reason.configure(text="偵測到待匯入的遷移包，請先匯入遷移包。")
        elif account_count == 0:
            bootstrap_button.configure(state="normal")
            bootstrap_reason.configure(text="資料庫尚無帳號。")
        else:
            bootstrap_button.configure(state="disabled")
            bootstrap_reason.configure(
                text="資料庫已經有帳號，此功能只在帳號數為 0 時可用。"
            )
        parent.after(2000, refresh)

    refresh()


def _find_pending_migration_package() -> Path | None:
    matches = list(package_root().glob(f"*{migration_client.PACKAGE_SUFFIX}"))
    return matches[0] if matches else None


class _PasswordRow:
    """A password Entry + 顯示 checkbox, sharing one StringVar."""

    def __init__(self, parent: tk.Widget, label: str):
        self.var = tk.StringVar()
        self._show = tk.BooleanVar(value=False)
        row = tk.Frame(parent)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text=label, width=16, anchor="w").pack(side="left")
        self.entry = tk.Entry(row, textvariable=self.var, show="*")
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(
            row, text="顯示", variable=self._show, command=self._toggle
        ).pack(side="left", padx=4)

    def _toggle(self) -> None:
        self.entry.configure(show="" if self._show.get() else "*")

    def get(self) -> str:
        return self.var.get()

    def clear(self) -> None:
        self.var.set("")


class _ManagementDialog(tk.Toplevel):
    def __init__(self, app, title: str):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

    def _clear_and_close(self, password_rows: list[_PasswordRow]) -> None:
        for row in password_rows:
            row.clear()
        self.destroy()


class AdminRecoverDialog(_ManagementDialog):
    def __init__(self, app):
        super().__init__(app, "admin 密碼恢復")
        tk.Label(
            self, text="驗證用帳號必須是目前可登入的其他帳號。",
            wraplength=380, justify="left",
        ).pack(fill="x", padx=8, pady=(8, 0))

        username_row = tk.Frame(self)
        username_row.pack(fill="x", padx=8, pady=4)
        tk.Label(username_row, text="驗證用帳號", width=16, anchor="w").pack(side="left")
        self.username_var = tk.StringVar()
        tk.Entry(username_row, textvariable=self.username_var).pack(
            side="left", fill="x", expand=True
        )

        self.verify_password = _PasswordRow(self, "該帳號密碼")
        self.new_password_1 = _PasswordRow(self, "新 admin 密碼")
        self.new_password_2 = _PasswordRow(self, "再輸入一次")

        ttk.Button(self, text="送出", command=self._submit).pack(pady=8)

    def _submit(self) -> None:
        username = self.username_var.get().strip()
        password = self.verify_password.get()
        new_password_1 = self.new_password_1.get()
        new_password_2 = self.new_password_2.get()
        rows = [self.verify_password, self.new_password_1, self.new_password_2]

        if not username or not password:
            messagebox.showerror("admin 密碼恢復", "驗證帳號與密碼皆為必填。")
            return
        if len(new_password_1) < 10:
            messagebox.showerror("admin 密碼恢復", "新的 admin 密碼至少需要 10 個字元。")
            return
        if new_password_1 != new_password_2:
            messagebox.showerror("admin 密碼恢復", "兩次輸入的新密碼不一致。")
            return

        def action():
            return admin_client.recover_admin_password(username, password, new_password_1)

        for row in rows:
            row.clear()
        self.destroy()
        result = self.app.run_management_action(action)
        if result.get("status") == "ok":
            messagebox.showinfo("admin 密碼恢復", result.get("message") or "已完成。")
        else:
            messagebox.showerror("admin 密碼恢復失敗", result.get("message") or "發生錯誤。")


class AdminBootstrapDialog(_ManagementDialog):
    def __init__(self, app):
        super().__init__(app, "建立第一個管理員")
        tk.Label(
            self, text="帳號固定為 admin，僅在資料庫沒有任何帳號時可用。",
            wraplength=380, justify="left",
        ).pack(fill="x", padx=8, pady=(8, 0))

        username_row = tk.Frame(self)
        username_row.pack(fill="x", padx=8, pady=4)
        tk.Label(username_row, text="帳號", width=16, anchor="w").pack(side="left")
        tk.Entry(username_row, textvariable=tk.StringVar(value="admin"), state="disabled").pack(
            side="left", fill="x", expand=True
        )

        self.password_1 = _PasswordRow(self, "密碼")
        self.password_2 = _PasswordRow(self, "再輸入一次")

        ttk.Button(self, text="建立", command=self._submit).pack(pady=8)

    def _submit(self) -> None:
        password_1 = self.password_1.get()
        password_2 = self.password_2.get()
        rows = [self.password_1, self.password_2]

        if len(password_1) < 10:
            messagebox.showerror("建立第一個管理員", "密碼至少需要 10 個字元。")
            return
        if password_1 != password_2:
            messagebox.showerror("建立第一個管理員", "兩次輸入的密碼不一致。")
            return

        def action():
            return admin_client.bootstrap_first_admin(password_1)

        for row in rows:
            row.clear()
        self.destroy()
        result = self.app.run_management_action(action)
        if result.get("status") == "ok":
            messagebox.showinfo("建立第一個管理員", result.get("message") or "已完成。")
        else:
            messagebox.showerror("建立失敗", result.get("message") or "發生錯誤。")


class MigrationImportDialog(_ManagementDialog):
    def __init__(self, app):
        super().__init__(app, "匯入遷移包")
        tk.Label(
            self,
            text="將以遷移包內容建立正式資料，匯入前會先建立安全備份。",
            wraplength=420, justify="left",
        ).pack(fill="x", padx=8, pady=(8, 0))

        path_row = tk.Frame(self)
        path_row.pack(fill="x", padx=8, pady=4)
        self.path_var = tk.StringVar()
        tk.Entry(path_row, textvariable=self.path_var, state="readonly", width=40).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(path_row, text="選擇檔案...", command=self._choose_file).pack(
            side="left", padx=4
        )

        tk.Label(
            self, text="單機版帳密（要匯出的來源帳號）", anchor="w"
        ).pack(fill="x", padx=8, pady=(8, 0))
        source_row = tk.Frame(self)
        source_row.pack(fill="x", padx=8, pady=2)
        tk.Label(source_row, text="帳號", width=16, anchor="w").pack(side="left")
        self.source_username_var = tk.StringVar(value="User")
        tk.Entry(source_row, textvariable=self.source_username_var).pack(
            side="left", fill="x", expand=True
        )
        self.source_password = _PasswordRow(self, "密碼")

        tk.Label(
            self, text="家中伺服器 admin 帳密", anchor="w"
        ).pack(fill="x", padx=8, pady=(8, 0))
        server_row = tk.Frame(self)
        server_row.pack(fill="x", padx=8, pady=2)
        tk.Label(server_row, text="帳號", width=16, anchor="w").pack(side="left")
        self.server_username_var = tk.StringVar(value="admin")
        tk.Entry(server_row, textvariable=self.server_username_var).pack(
            side="left", fill="x", expand=True
        )
        self.server_password = _PasswordRow(self, "密碼")

        ttk.Button(self, text="匯入", command=self._submit).pack(pady=8)

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇遷移包",
            filetypes=[("Land Customer System 遷移包", f"*{migration_client.PACKAGE_SUFFIX}")],
        )
        if selected:
            self.path_var.set(selected)

    def _submit(self) -> None:
        path_text = self.path_var.get().strip()
        rows = [self.source_password, self.server_password]
        if not path_text:
            messagebox.showerror("匯入遷移包", "請先選擇遷移包檔案。")
            return
        source_path = Path(path_text)
        error = migration_client.validate_package_file(source_path)
        if error:
            messagebox.showerror("匯入遷移包", error)
            return
        confirmed = messagebox.askyesno(
            "匯入遷移包", "將以遷移包內容建立正式資料，匯入前會先建立安全備份，確定要匯入嗎？"
        )
        if not confirmed:
            return

        source_username = self.source_username_var.get().strip() or "User"
        source_password = self.source_password.get()
        server_username = self.server_username_var.get().strip() or "admin"
        server_password = self.server_password.get()

        def action():
            staged_path = migration_client.stage_package_copy(source_path)
            try:
                return migration_client.import_migration_package(
                    staged_path,
                    source_username=source_username,
                    source_password=source_password,
                    server_username=server_username,
                    server_password=server_password,
                )
            finally:
                migration_client.cleanup_staged_copy(staged_path)

        for row in rows:
            row.clear()
        self.destroy()
        result = self.app.run_management_action(action)
        if result.get("status") == "ok":
            messagebox.showinfo("匯入遷移包", "單機資料已匯入並通過驗證。")
        else:
            messagebox.showerror("匯入失敗", result.get("message") or "發生錯誤。")
