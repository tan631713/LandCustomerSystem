"""Backup health inspection and Qt controls for manual backups."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from customer_responsive_dialog import ResponsiveDialog as QDialog

from customer_messages import (
    backup_failure_message,
    backup_status_guidance,
    backup_status_warning_message,
    backup_success_message,
    safety_backup_failure_message,
)


@dataclass(frozen=True)
class BackupStatus:
    database_healthy: bool
    database_message: str
    backup_count: int
    latest_backup_path: object = None
    latest_backup_time: datetime = None
    backup_stale: bool = False
    compressed_count: int = 0
    total_bytes: int = 0

    @property
    def healthy(self):
        return self.database_healthy and self.backup_count > 0 and not self.backup_stale

    @property
    def short_text(self):
        if not self.database_healthy:
            return "資料庫異常"
        if self.backup_count == 0:
            return "尚無備份"
        if self.backup_stale:
            return "備份過久"
        return f"備份正常（{self.latest_backup_time.strftime('%m/%d %H:%M')}）"


def inspect_backup_status(database, *, stale_days=7, now=None):
    now = now or datetime.now()
    try:
        database.validate_database_file(database.database_path)
        database_healthy = True
        database_message = "完整性檢查正常"
    except (OSError, ValueError) as exc:
        database_healthy = False
        database_message = str(exc)

    backup_directory = database.backup_directory
    backups = []
    if backup_directory.exists():
        backups = database.list_backup_files()
    latest_path = backups[0] if backups else None
    latest_time = (
        datetime.fromtimestamp(latest_path.stat().st_mtime)
        if latest_path is not None
        else None
    )
    stale = bool(latest_time and latest_time < now - timedelta(days=stale_days))
    return BackupStatus(
        database_healthy=database_healthy,
        database_message=database_message,
        backup_count=len(backups),
        latest_backup_path=latest_path,
        latest_backup_time=latest_time,
        backup_stale=stale,
        compressed_count=sum(path.suffix.lower() == ".zip" for path in backups),
        total_bytes=sum(path.stat().st_size for path in backups),
    )


def format_storage_size(size_bytes):
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


class BackupStatusDialog(QDialog):
    def __init__(self, status, backup_directory, parent=None):
        super().__init__(parent)
        self.setWindowTitle("備份狀態")
        # Deliberately non-modal -- see show_backup_status() below.
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        rows = [
            ("資料庫狀態", "正常" if status.database_healthy else "異常"),
            ("完整性檢查", status.database_message),
            ("備份檔案數量", str(status.backup_count)),
            ("ZIP 壓縮備份", str(status.compressed_count)),
            ("備份佔用空間", format_storage_size(status.total_bytes)),
            (
                "最近備份時間",
                status.latest_backup_time.strftime("%Y-%m-%d %H:%M:%S")
                if status.latest_backup_time
                else "尚無備份",
            ),
            (
                "最近備份檔案",
                str(status.latest_backup_path) if status.latest_backup_path else "—",
            ),
            ("備份資料夾", str(backup_directory)),
            ("建議處理", backup_status_guidance(status)),
        ]
        for row_index, (label, value) in enumerate(rows):
            label_widget = QLabel(label)
            label_widget.setStyleSheet("font-weight: 600;")
            value_widget = QLabel(value)
            value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_widget.setWordWrap(True)
            grid.addWidget(label_widget, row_index, 0)
            grid.addWidget(value_widget, row_index, 1)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BackupManagementDialog(QDialog):
    def __init__(self, *, compress_backups, retention_days, max_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("備份管理")
        self.setModal(True)
        self.setMinimumWidth(540)
        self.requested_action = "save"

        layout = QVBoxLayout(self)
        description = QLabel(
            "系統每 6 小時檢查一次，跨日會建立每日備份並依下列規則整理。"
            "無論設定為何，最新 3 份備份都不會被自動刪除。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.compress_checkbox = QCheckBox("新備份使用 ZIP，並自動壓縮既有 .db 備份")
        self.compress_checkbox.setChecked(bool(compress_backups))
        form.addRow("壓縮", self.compress_checkbox)

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 3650)
        self.retention_days_spin.setSuffix(" 天")
        self.retention_days_spin.setSpecialValueText("不依天數清除")
        self.retention_days_spin.setValue(int(retention_days))
        form.addRow("保留期限", self.retention_days_spin)

        self.max_count_spin = QSpinBox()
        self.max_count_spin.setRange(3, 9999)
        self.max_count_spin.setSuffix(" 份")
        self.max_count_spin.setValue(max(3, int(max_count)))
        form.addRow("最多保留", self.max_count_spin)
        layout.addLayout(form)

        hint = QLabel("立即清理只會刪除系統在 backups 資料夾中建立的 customers-*.db / *.zip。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("儲存並執行")
        compress_button = buttons.addButton("立即壓縮既有備份", QDialogButtonBox.ActionRole)
        clean_button = buttons.addButton("立即清理舊備份", QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        compress_button.clicked.connect(lambda: self._accept_action("compress"))
        clean_button.clicked.connect(lambda: self._accept_action("clean"))
        layout.addWidget(buttons)

    def _accept_action(self, action):
        self.requested_action = action
        self.accept()

    def selected_policy(self):
        return {
            "compress_backups": self.compress_checkbox.isChecked(),
            "retention_days": self.retention_days_spin.value(),
            "max_count": self.max_count_spin.value(),
        }


class ServerBackupTargetsDialog(QDialog):
    """Manage paths that are resolved and written by the home server."""

    def __init__(
        self,
        repository,
        *,
        retention_days=90,
        max_count=30,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.retention_days = int(retention_days)
        self.max_count = int(max_count)
        self.rows = []
        self.setWindowTitle("家中伺服器異地備份")
        self.resize(900, 560)

        layout = QVBoxLayout(self)
        note = QLabel(
            "此處路徑是家中伺服器上的資料夾，不是公司筆電。可輸入外接硬碟 "
            "E:\\土地備份，或家中主機已掛載的 NAS 路徑。同步後會驗證 SHA-256。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "名稱", "家中主機路徑", "啟用", "最後成功", "錯誤"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.load_selected)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：家中外接硬碟")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(r"例如 E:\土地備份 或 \\NAS\土地備份")
        self.enabled_checkbox = QCheckBox("啟用")
        self.enabled_checkbox.setChecked(True)
        form.addRow("名稱", self.name_edit)
        form.addRow("家中主機路徑", self.path_edit)
        form.addRow("狀態", self.enabled_checkbox)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        new_button = QPushButton("清空新增")
        save_button = QPushButton("新增／更新")
        delete_button = QPushButton("刪除")
        sync_button = QPushButton("立即建立並同步")
        close_button = QPushButton("關閉")
        new_button.clicked.connect(self.clear_form)
        save_button.clicked.connect(self.save_target)
        delete_button.clicked.connect(self.delete_target)
        sync_button.clicked.connect(self.sync_targets)
        close_button.clicked.connect(self.accept)
        for button in (new_button, save_button, delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(sync_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.refresh()

    def selected_row(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_server_backup_targets()]
        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            values = (
                row.get("id"),
                row.get("name"),
                row.get("directory_path"),
                "是" if row.get("enabled") else "否",
                row.get("last_success_at") or "",
                row.get("last_error") or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value or "")))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def clear_form(self):
        self.table.clearSelection()
        self.name_edit.clear()
        self.path_edit.clear()
        self.enabled_checkbox.setChecked(True)

    def load_selected(self):
        row = self.selected_row()
        if row is None:
            return
        self.name_edit.setText(str(row.get("name") or ""))
        self.path_edit.setText(str(row.get("directory_path") or ""))
        self.enabled_checkbox.setChecked(bool(row.get("enabled")))

    def save_target(self):
        selected = self.selected_row()
        try:
            self.repository.save_server_backup_target(
                self.name_edit.text(),
                self.path_edit.text(),
                enabled=self.enabled_checkbox.isChecked(),
                target_id=selected.get("id") if selected else None,
            )
        except Exception as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc))
            return
        self.refresh()
        self.clear_form()

    def delete_target(self):
        selected = self.selected_row()
        if selected is None:
            QMessageBox.information(self, "尚未選取", "請先選取要刪除的目的地。")
            return
        if QMessageBox.question(
            self,
            "刪除異地目的地",
            f"確定刪除「{selected.get('name') or ''}」？已備份的檔案不會被刪除。",
        ) != QMessageBox.Yes:
            return
        self.repository.delete_server_backup_target(selected["id"])
        self.refresh()
        self.clear_form()

    def sync_targets(self):
        try:
            result = self.repository.sync_server_backup_targets(
                self.retention_days, self.max_count
            )
        except Exception as exc:
            QMessageBox.critical(self, "異地備份失敗", str(exc))
            return
        lines = []
        for item in result.get("results") or []:
            if item.get("status") == "success":
                lines.append(f"{item.get('name')}：成功 → {item.get('destination')}")
            else:
                lines.append(f"{item.get('name')}：失敗（{item.get('error')}）")
        QMessageBox.information(
            self,
            "異地備份完成",
            f"家中主備份：{result.get('backup_path') or ''}\n\n"
            + ("\n".join(lines) or "沒有啟用的目的地。"),
        )
        self.refresh()


class ServerBackupRestoreDialog(QDialog):
    CONFIRMATION_TEXT = "還原家中伺服器"

    def __init__(self, backups, parent=None):
        super().__init__(parent)
        self.rows = [dict(row) for row in backups if row.get("status") == "ok"]
        self.setWindowTitle("還原家中伺服器備份")
        self.resize(820, 480)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "還原會取代家中伺服器的 PostgreSQL 正式資料與納管附件。系統會先自動建立"
            "還原前安全備份，完成後所有裝置必須重新登入。"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.table = QTableWidget(len(self.rows), 5)
        self.table.setHorizontalHeaderLabels(
            ["備份檔", "建立時間", "資料筆數", "附件數", "大小"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row_index, row in enumerate(self.rows):
            values = (
                row.get("name"),
                row.get("created_at") or row.get("modified_at") or "",
                row.get("record_count") or 0,
                row.get("attachment_count") or 0,
                format_storage_size(row.get("bytes") or 0),
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        layout.addWidget(self.table)
        self.confirmation_edit = QLineEdit()
        self.confirmation_edit.setPlaceholderText(
            f"請完整輸入：{self.CONFIRMATION_TEXT}"
        )
        layout.addWidget(self.confirmation_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.restore_button = buttons.button(QDialogButtonBox.Ok)
        self.restore_button.setText("開始還原")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.table.itemSelectionChanged.connect(self.update_restore_button)
        self.confirmation_edit.textChanged.connect(self.update_restore_button)
        layout.addWidget(buttons)
        if self.rows:
            self.table.selectRow(0)
        self.update_restore_button()

    def update_restore_button(self):
        self.restore_button.setEnabled(
            self.table.currentRow() >= 0
            and self.confirmation_edit.text().strip() == self.CONFIRMATION_TEXT
        )

    def selected_backup_name(self):
        index = self.table.currentRow()
        return str(self.rows[index].get("name") or "") if 0 <= index < len(self.rows) else ""

    def confirmation(self):
        return self.confirmation_edit.text().strip()


class BackupStatusMixin:
    BACKUP_STALE_DAYS = 7
    BACKUP_MAINTENANCE_INTERVAL_MS = 6 * 60 * 60 * 1000

    def setup_backup_status(self):
        self.backup_status_button = QPushButton("檢查備份中…")
        self.backup_status_button.setFlat(True)
        self.backup_status_button.setToolTip("查看資料庫與備份狀態")
        self.backup_status_button.clicked.connect(self.show_backup_status)
        self.statusBar().addPermanentWidget(self.backup_status_button)
        self.refresh_backup_status(show_warning=True)
        self.backup_maintenance_timer = QTimer(self)
        self.backup_maintenance_timer.setInterval(self.BACKUP_MAINTENANCE_INTERVAL_MS)
        self.backup_maintenance_timer.timeout.connect(self.run_scheduled_backup_maintenance)
        self.backup_maintenance_timer.start()

    def run_scheduled_backup_maintenance(self):
        if getattr(self, "api_mode", False):
            return self.refresh_backup_status(show_warning=True)
        try:
            self.database.ensure_daily_backup()
        except Exception as exc:
            self.statusBar().showMessage(f"備份定時維護失敗：{exc}", 15000)
            try:
                self.repository.log_operation("備份定時維護失敗", str(exc), "")
            except Exception:
                pass
            self.refresh_backup_status(show_warning=True)
            return None
        return self.refresh_backup_status()

    def refresh_backup_status(self, show_warning=False):
        if getattr(self, "api_mode", False):
            try:
                report = self.active_record_repository().server_backup_status()
            except Exception as exc:
                report = {
                    "status": "warning",
                    "backup_count": 0,
                    "backup_directory": "家中伺服器",
                    "database": {"status": "error"},
                    "error": str(exc),
                }
            latest_text = str(report.get("latest_backup") or "")
            latest_at = str(report.get("latest_backup_at") or "")
            latest_time = None
            if latest_at:
                try:
                    latest_time = datetime.fromisoformat(latest_at).astimezone().replace(tzinfo=None)
                except ValueError:
                    latest_time = None
            database_report = dict(report.get("database") or {})
            database_healthy = database_report.get("status") == "ok"
            stale = bool(
                latest_time
                and latest_time < datetime.now() - timedelta(days=self.BACKUP_STALE_DAYS)
            )
            self.remote_backup_directory = str(report.get("backup_directory") or "")
            status = BackupStatus(
                database_healthy=database_healthy,
                database_message=(
                    f"PostgreSQL 正常，資料 {database_report.get('record_count', 0)} 筆"
                    if database_healthy else str(report.get("error") or "PostgreSQL 健康檢查失敗")
                ),
                backup_count=int(report.get("backup_count") or 0),
                latest_backup_path=Path(latest_text) if latest_text else None,
                latest_backup_time=latest_time,
                backup_stale=stale,
                compressed_count=int(report.get("backup_count") or 0),
                total_bytes=int(report.get("total_bytes") or 0),
            )
        else:
            status = inspect_backup_status(
                self.database,
                stale_days=self.BACKUP_STALE_DAYS,
            )
        self.backup_status = status
        if getattr(self, "backup_status_button", None) is not None:
            self.backup_status_button.setText(status.short_text)
            color = "#86efac" if status.healthy else "#fbbf24"
            if not status.database_healthy:
                color = "#f87171"
            self.backup_status_button.setStyleSheet(f"color: {color}; padding: 2px 8px;")
        if show_warning and not status.healthy:
            self.statusBar().showMessage(
                backup_status_warning_message(status),
                10000,
            )
        return status

    def show_backup_status(self):
        status = self.refresh_backup_status()
        backup_directory = (
            getattr(self, "remote_backup_directory", "家中伺服器")
            if getattr(self, "api_mode", False)
            else self.database.backup_directory
        )
        self._show_non_modal_report_dialog(
            "_backup_status_dialog",
            BackupStatusDialog,
            status,
            backup_directory,
            self,
        )

    def backup_now(self):
        if getattr(self, "api_mode", False):
            if not self.ensure_admin("立即備份"):
                return None
            policy = self._app_component("load_backup_policy")()
            try:
                report = self.active_record_repository().create_server_backup(
                    "manual", policy["retention_days"], policy["max_count"]
                )
            except Exception as exc:
                self.refresh_backup_status(show_warning=True)
                QMessageBox.critical(self, "備份失敗", backup_failure_message(exc))
                return None
            self.refresh_backup_status()
            backup_path = report.get("backup_path") or "家中伺服器備份"
            self._log_operation("手動備份", "建立 PostgreSQL 與附件備份", str(backup_path))
            QMessageBox.information(
                self,
                "備份完成",
                f"家中伺服器已完成 PostgreSQL 與附件壓縮備份。\n{backup_path}",
            )
            return backup_path
        try:
            backup_path = self.database.backup_database("manual")
        except (OSError, ValueError) as exc:
            self.refresh_backup_status(show_warning=True)
            QMessageBox.critical(self, "備份失敗", backup_failure_message(exc))
            return None
        warnings = []
        try:
            self.database.run_backup_maintenance()
        except Exception as exc:
            warnings.append(f"後續整理未完成：{exc}")
        try:
            self.repository.log_operation("手動備份", "建立資料庫備份", str(backup_path))
        except Exception as exc:
            warnings.append(f"操作記錄未寫入：{exc}")
        self.refresh_backup_status()
        message = backup_success_message(backup_path)
        if warnings:
            message += "\n\n提醒：" + "；".join(warnings)
        QMessageBox.information(self, "備份完成", message)
        return backup_path

    def create_safety_backup(self, label):
        try:
            backup_path = self.database.backup_database(label)
        except (OSError, ValueError) as exc:
            self.refresh_backup_status(show_warning=True)
            QMessageBox.warning(self, "備份失敗", safety_backup_failure_message(exc))
            return None
        self.refresh_backup_status()
        return backup_path
