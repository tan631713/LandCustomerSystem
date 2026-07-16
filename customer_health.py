"""System health checks independent from the Qt window layer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


HealthCheck = dict[str, str]


class SystemHealthCheckService:
    """Build health-check rows while isolating failures by category."""

    def __init__(
        self,
        *,
        readonly_mode: Callable[[], bool],
        api_client: Any | None = None,
        diagnostics_path: Path | None = None,
        database: Any | None = None,
        repository: Any | None = None,
        plain_record: Callable[[Any], dict[str, Any]] | None = None,
        inspect_quality: Callable[..., list[Any]] | None = None,
        quality_rule_keys: Callable[[], list[str]] | None = None,
        plain_reminder: Callable[[Any], dict[str, Any]] | None = None,
        error_log_path: Path | None = None,
    ):
        self.readonly_mode = readonly_mode
        self.api_client = api_client
        self.diagnostics_path = diagnostics_path
        self.database = database
        self.repository = repository
        self.plain_record = plain_record
        self.inspect_quality = inspect_quality
        self.quality_rule_keys = quality_rule_keys
        self.plain_reminder = plain_reminder
        self.error_log_path = error_log_path

    def build(self) -> list[HealthCheck]:
        if self.api_client is not None:
            return self._build_api_checks()
        return self._build_local_checks()

    @staticmethod
    def _try_check(
        checks: list[HealthCheck],
        title: str,
        build_result: Callable[[], tuple[str, str]],
        *,
        error_status: str,
    ) -> None:
        try:
            status, detail = build_result()
        except Exception as exc:
            status, detail = error_status, str(exc)
        checks.append({"status": status, "title": title, "detail": detail})

    def _readonly_result(self, *, api_mode: bool) -> tuple[str, str]:
        readonly = self.readonly_mode()
        if api_mode:
            detail = "唯讀模式已啟用" if readonly else "可依帳號權限修改資料"
        else:
            detail = "唯讀模式已啟用" if readonly else "可新增/修改資料"
        return ("提醒" if readonly else "OK", detail)

    def _build_api_checks(self) -> list[HealthCheck]:
        checks: list[HealthCheck] = []

        def api_result() -> tuple[str, str]:
            health = self.api_client.health()
            detail = (
                f"版本 {health.get('version') or '未知'}；"
                f"資料結構 {health.get('schema_version') or '未知'}；"
                f"資料 {health.get('record_count') or 0} 筆"
            )
            return ("OK" if health.get("status") == "ok" else "錯誤", detail)

        self._try_check(checks, "家中 PostgreSQL API", api_result, error_status="錯誤")
        self._try_check(
            checks,
            "客戶端權限模式",
            lambda: self._readonly_result(api_mode=True),
            error_status="警告",
        )
        diagnostics_path = self.diagnostics_path
        checks.append(
            {
                "status": "OK" if diagnostics_path and diagnostics_path.is_file() else "提醒",
                "title": "客戶端連線診斷",
                "detail": str(diagnostics_path or "尚未設定診斷檔路徑"),
            }
        )
        return checks

    def _build_local_checks(self) -> list[HealthCheck]:
        checks: list[HealthCheck] = []

        def integrity_result() -> tuple[str, str]:
            with self.database.connect() as conn:
                result = conn.execute("PRAGMA quick_check").fetchone()[0]
            return ("OK" if result == "ok" else "警告", str(result))

        def volume_result() -> tuple[str, str]:
            total_records = self.repository.count_customers()
            counts = self.repository.management_table_counts()
            detail = (
                f"客戶 {total_records} 筆；案件 {counts.get('cases', 0)} 個／關聯 {counts.get('case_customers', 0)} 筆；"
                f"標籤 {counts.get('tags', 0)} 個／套用 {counts.get('customer_tags', 0)} 次；"
                f"附件 {counts.get('customer_attachments', 0)}；自訂值 {counts.get('customer_custom_values', 0)}；"
                f"聯絡紀錄 {counts.get('contact_logs', 0)}"
            )
            return "OK", detail

        def quality_result() -> tuple[str, str]:
            records = [self.plain_record(row) for row in self.repository.fetch_all_customer_rows()]
            issues = self.inspect_quality(records, enabled_rules=self.quality_rule_keys())
            return ("OK" if not issues else "提醒", f"{len(issues)} 個待確認項目")

        def reminder_result() -> tuple[str, str]:
            reminders = [
                self.plain_reminder(row)
                for row in self.repository.list_follow_up_reminders()
            ]
            overdue_count = sum(1 for reminder in reminders if reminder.get("is_overdue"))
            return (
                "OK" if overdue_count == 0 else "提醒",
                f"{len(reminders)} 筆提醒；{overdue_count} 筆已逾期",
            )

        def backup_result() -> tuple[str, str]:
            backup_files = self.database.list_backup_files()
            latest_backup = backup_files[0] if backup_files else None
            return (
                "OK" if latest_backup else "提醒",
                str(latest_backup) if latest_backup else "尚未找到備份檔",
            )

        self._try_check(checks, "SQLite 完整性", integrity_result, error_status="錯誤")
        self._try_check(checks, "資料量", volume_result, error_status="錯誤")
        self._try_check(checks, "資料品質", quality_result, error_status="警告")
        self._try_check(checks, "追蹤提醒", reminder_result, error_status="警告")
        self._try_check(checks, "備份", backup_result, error_status="錯誤")
        self._try_check(
            checks,
            "權限模式",
            lambda: self._readonly_result(api_mode=False),
            error_status="警告",
        )

        error_log_path = self.error_log_path
        checks.append(
            {
                "status": "提醒" if error_log_path and error_log_path.exists() else "OK",
                "title": "系統錯誤記錄",
                "detail": (
                    str(error_log_path)
                    if error_log_path and error_log_path.exists()
                    else "尚無未預期錯誤記錄"
                ),
            }
        )
        return checks
