"""Backup health inspection and Qt controls for manual backups."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
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
        self.setModal(True)
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
        BackupStatusDialog(status, self.database.backup_directory, self).exec()

    def backup_now(self):
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
