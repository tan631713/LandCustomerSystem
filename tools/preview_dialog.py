"""Open one dialog with made-up sample data to check its ui/dialogs/*.ui file.

    python tools\\preview_dialog.py --list              (list the dialog names)
    python tools\\preview_dialog.py AuthDialog
    python tools\\preview_dialog.py AuthDialog dark
    python tools\\preview_dialog.py AuthDialog --screenshot out.png

No login and no database: every dialog gets fixed sample values, and nothing
it does is saved (the 傳送到手機 dialog does not start its share server).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_GROUP = SimpleNamespace(
    full_land_number="桃園區 中路段 123 地號",
    area="1,234.5",
    owner_count=2,
    ownership_count=2,
    land_use="住宅區",
    status_summary="追蹤中",
    land_id=7,
    records=[
        {"id": 1, "owner_id": 11, "raw": {"owner_name": "王小明", "numerator": "1", "denominator": "2",
                                          "address": "桃園市桃園區", "phone": "0912345678", "note": "下午較方便"}},
        {"id": 2, "owner_id": 12, "raw": {"owner_name": "李小華", "numerator": "1", "denominator": "2",
                                          "address": "台北市", "phone": "", "note": ""}},
    ],
)
SAMPLE_CONTACTS = [
    {"name": "王小明", "mobile_phone": "0912345678", "home_phone": "03-1234567",
     "registered_address": "桃園市桃園區", "contact_address": "同上", "owner_count": 2},
    {"name": "陳大文", "mobile_phone": "", "home_phone": "", "registered_address": "",
     "contact_address": "", "owner_count": 0},
]
SAMPLE_DUPLICATES = [
    {"id": 1, "raw": {"district": "桃園區", "section": "中路段", "land_number": "123", "owner_name": "王小明"}},
    {"id": 2, "raw": {"district": "桃園區", "section": "中路段", "land_number": "124", "owner_name": "李小華"}},
]


SAMPLE_TAGS = [
    {"id": 1, "name": "優先", "color": "#F5DC7A", "customer_count": 12},
    {"id": 2, "name": "已寄信", "color": "", "customer_count": 30},
]
SAMPLE_FIELD_LABELS = {"district": "地區", "section": "地段", "land_number": "地號", "owner_name": "姓名", "address": "地址"}
SAMPLE_PLANS = {
    "items": [{"id": 1, "name": "中壢都市計畫", "land_count": 1200, "owner_count": 3400, "ownership_count": 3600}],
    "unassigned": {"land_count": 5, "owner_count": 7, "ownership_count": 7},
}
SAMPLE_IMPORT_RECORDS = [
    {"district": "桃園區", "land_number": "123", "owner_name": "王小明"},
    {"district": "桃園區", "land_number": "124", "owner_name": "李小華", "_duplicate_reason": "可能重複：同地號同姓名"},
]
SAMPLE_IMPORT_COLUMNS = [("district", "地區"), ("land_number", "地號"), ("owner_name", "姓名")]


class _PreviewRepository:
    """Answers the repository calls some dialogs make while opening; saves nothing."""

    def refresh_notifications(self, _today):
        return None

    def list_notifications(self, include_read=False):
        rows = [
            {"id": 1, "severity": "高", "category": "追蹤", "title": "王小明 追蹤逾期", "detail": "原定 2026-10-30 回電",
             "read_at": None, "created_at": "2026-11-01 09:00"},
            {"id": 2, "severity": "中", "category": "案件", "title": "中路段整合 今日到期", "detail": "",
             "read_at": None, "created_at": "2026-11-02 08:00"},
        ]
        if include_read:
            rows.append({"id": 3, "severity": "低", "category": "任務", "title": "已讀通知", "detail": "",
                         "read_at": "2026-11-01", "created_at": "2026-10-31 10:00"})
        return rows

    def mark_notifications(self, _ids, _action):
        return None

    def list_import_profiles(self):
        mapping = json.dumps({"所有權人": "owner_name", "地號": "land_number"}, ensure_ascii=False)
        return [{"id": 1, "name": "地政事務所格式", "is_default": 1, "mapping_json": mapping}]

    def save_import_profile(self, *_args, **_kwargs):
        raise ValueError("預覽模式不會儲存。")

    def delete_import_profile(self, _profile_id):
        return None

    def list_report_templates(self):
        return [{"id": 1, "name": "拜訪清單", "title": "土地資料報表",
                 "fields_json": json.dumps(["district", "land_number", "owner_name"]),
                 "header_text": "", "footer_text": ""}]

    def save_report_template(self, *_args, **_kwargs):
        raise ValueError("預覽模式不會儲存。")

    def delete_report_template(self, _template_id):
        return None

    def list_server_backup_targets(self):
        return [{"id": 1, "name": "家中外接硬碟", "directory_path": "E:\\土地備份", "enabled": 1,
                 "last_success_at": "2026-11-01 03:00", "last_error": ""}]

    def save_server_backup_target(self, *_args, **_kwargs):
        raise ValueError("預覽模式不會儲存。")

    def delete_server_backup_target(self, _target_id):
        return None

    def sync_server_backup_targets(self, *_args):
        raise ValueError("預覽模式不會同步。")

    def get_watchlist_entries(self):
        return [{"name": "陳大文", "note": "曾要求不要再聯絡"}, {"name": "林美麗", "note": None}]

    def replace_watchlist_entries(self, _entries):
        return None

    # -- batch 5 --
    def list_users(self):
        return [{"id": 1, "username": "admin", "display_name": "管理員", "role": "admin", "active": 1,
                 "created_at": "2026-01-01", "last_login_at": "2026-11-02"}]

    def list_backup_targets(self):
        return [{"id": 1, "name": "辦公室 NAS", "directory_path": "\\\\NAS\\backup", "enabled": 1,
                 "last_success_at": "2026-11-01", "last_error": ""}]

    def list_cases(self):
        return [{"id": 1, "title": "中路段整合", "status": "進行中", "assigned_to": "王", "due_date": "2026-12-01",
                 "priority": "高", "next_action": "寄信", "customer_count": 12, "archived_at": None, "note": ""}]

    def list_case_tasks(self):
        return [{"id": 1, "case_id": 1, "case_title": "中路段整合", "title": "寄存證信函", "assignee": "王",
                 "due_date": "2026-11-20", "status": "待處理", "priority": "一般", "checklist": "印信封"}]

    def get_setting(self, _key, default=None):
        return default

    def list_customer_locations(self):
        return [{"customer_id": 1, "latitude": 24.99, "longitude": 121.31, "source": "manual"}]

    def fetch_all_customer_rows(self):
        encrypt = lambda value: PREVIEW_FERNET.encrypt(value.encode()).decode()  # noqa: E731
        return [
            {"id": 1, "district": "桃園區", "section": "中路段", "subsection": "", "land_number": "123",
             "owner_name": encrypt("王小明"), "address": encrypt("桃園市桃園區")},
            {"id": 2, "district": "桃園區", "section": "中路段", "subsection": "", "land_number": "124",
             "owner_name": encrypt("李小華"), "address": encrypt("")},
        ]

    def get_customer(self, _customer_id):
        return None

    def search_owner_contacts(self, _query, limit=5):
        return []

    def __getattr__(self, name):
        # Anything else a dialog would save or change: refuse, never write.
        if name.startswith("_"):
            raise AttributeError(name)
        return _preview_refusal


class _PreviewCalendarWindow:
    """What VisitCalendarDialog asks its main window for: a few sample visits."""

    def load_visit_calendar_items(self, start, _end, mine_only=False):
        return [
            {"date": start[:8] + "05", "owner_name": "王小明", "district": "桃園區", "section": "中路段",
             "land_number": "123", "calendar_status": "scheduled", "customer_id": 1},
            {"date": start[:8] + "05", "owner_name": "李小華", "district": "桃園區", "land_number": "124",
             "calendar_status": "overdue", "customer_id": 2},
            {"date": start[:8] + "12", "owner_name": "陳大文", "calendar_status": "completed", "customer_id": 3},
        ]


class _PreviewBackupService:
    database = SimpleNamespace(backup_directory=str(ROOT / "backups"))


PREVIEW_FERNET = None


def _preview_refusal(*_args, **_kwargs):
    raise ValueError("預覽模式不會儲存。")


class _PreviewShareServer:
    """Stands in for TemporaryShareServer so a preview never opens a port."""

    def __init__(self, *_args, **_kwargs):
        self.url = "http://192.168.1.10:8765/preview"

    def stop(self):
        pass


def sample_dialogs():
    """name -> (ui file, factory).  Import only after a QApplication exists."""

    import customer_ui_qt  # noqa: F401 - injects the dialogs' app settings
    import customer_auth
    import customer_backup_status
    import customer_dialogs as dialogs
    import customer_export_controller
    import customer_extra_dialogs as extra
    import customer_land_details
    import customer_mobile_share
    import customer_owner_contacts as contacts
    import customer_productivity as productivity
    import customer_urban_plan_dialogs as plans

    global PREVIEW_FERNET
    from cryptography.fernet import Fernet
    from customer_quality import DataQualityIssue

    PREVIEW_FERNET = Fernet(Fernet.generate_key())
    repository = _PreviewRepository()
    quality_issues = [
        DataQualityIssue(1, "重要", "姓名空白", "姓名是空的", "補上姓名"),
        DataQualityIssue(2, "提醒", "地址格式異常", "地址缺少縣市", "補上縣市"),
    ]
    contact = {
        "name": "王小明", "external_id": "A12******9", "mobile_phone": "0912345678", "home_phone": "",
        "registered_address": "桃園市", "contact_address": "", "work_address": "", "birth_year": "1965",
        "identity_note": "", "contact_notes": "", "relationship_type": "配偶", "relationship_note": "",
        "is_primary": 1, "sort_order": 10, "relation_notes": "", "owner_count": 2, "relation_id": 5,
        "is_active": 1, "updated_at": "2026-11-01",
    }
    custom_fields = [{"id": 1, "label": "第二支電話"}, {"id": 2, "field_key": "line_id"}]

    def mobile_share():
        with patch.object(customer_mobile_share, "TemporaryShareServer", _PreviewShareServer):
            return customer_mobile_share.MobileShareDialog([{"raw": {}}], [])

    entries = {
        "AuthDialog": (customer_auth.AuthDialog, lambda: customer_auth.AuthDialog(setup_mode=False)),
        "AuthDialog-setup": (customer_auth.AuthDialog, lambda: customer_auth.AuthDialog(setup_mode=True)),
        "ChangePasswordDialog": (dialogs.ChangePasswordDialog, dialogs.ChangePasswordDialog),
        "FontSizeDialog": (dialogs.FontSizeDialog, lambda: dialogs.FontSizeDialog("medium")),
        "BatchEditDialog": (dialogs.BatchEditDialog, lambda: dialogs.BatchEditDialog(3)),
        "BatchEditPreviewDialog": (dialogs.BatchEditPreviewDialog, lambda: dialogs.BatchEditPreviewDialog(
            "地址", "桃園市中壢區", ["1. 王小明：桃園市 → 桃園市中壢區", "2. 李小華：台北市 → 桃園市中壢區"])),
        "CaseSelectDialog": (extra.CaseSelectDialog, lambda: extra.CaseSelectDialog(
            [{"id": 1, "title": "中路段整合", "status": "進行中"}], 2)),
        "FieldVisitScheduleDialog": (extra.FieldVisitScheduleDialog, lambda: extra.FieldVisitScheduleDialog(2)),
        "MergeRecordsDialog": (extra.MergeRecordsDialog, lambda: extra.MergeRecordsDialog(
            "王小明 123 地號", "王小明 124 地號", ["姓名：相同", "地址：由第二筆補上"])),
        "ApplyTemplateDialog": (extra.ApplyTemplateDialog, lambda: extra.ApplyTemplateDialog(
            [{"id": 1, "title": "電話未接", "template_type": "visit_log"}])),
        "FollowUpReminderDialog": (dialogs.FollowUpReminderDialog, lambda: dialogs.FollowUpReminderDialog(
            "桃園區 中路段 123 地號 王小明", {"due_date": "2026-11-20", "status": "待回覆", "note": "再打一次"})),
        "ImportResultDialog": (dialogs.ImportResultDialog, lambda: dialogs.ImportResultDialog(
            ["新增 3 筆", "更新 1 筆", "失敗 1 筆"], ["第 5 列：缺少地號"], [{"row": 5}])),
        "MobileShareDialog": (customer_mobile_share.MobileShareDialog, mobile_share),
        "DeleteUrbanPlanDialog": (plans.DeleteUrbanPlanDialog, lambda: plans.DeleteUrbanPlanDialog(
            {"name": "中壢都市計畫", "land_count": 1200, "owner_count": 3400})),
        "SetUrbanPlanDialog": (plans.SetUrbanPlanDialog, lambda: plans.SetUrbanPlanDialog(
            [{"id": 1, "name": "中壢都市計畫"}, {"id": 2, "name": "桃園都市計畫"}], {10: 0, 11: 2, 12: 1}, 5)),
        "BackupManagementDialog": (customer_backup_status.BackupManagementDialog,
                                   lambda: customer_backup_status.BackupManagementDialog(
                                       compress_backups=True, retention_days=30, max_count=10)),
        "ExistingContactPickerDialog": (contacts.ExistingContactPickerDialog,
                                        lambda: contacts.ExistingContactPickerDialog(SAMPLE_CONTACTS)),
        "DeactivateRelationDialog": (contacts.DeactivateRelationDialog,
                                     lambda: contacts.DeactivateRelationDialog("王小明")),
        "HelpDialog": (dialogs.HelpDialog, dialogs.HelpDialog),
        "LandDetailsDialog": (customer_land_details.LandDetailsDialog,
                              lambda: customer_land_details.LandDetailsDialog(SAMPLE_GROUP)),
        "PreviousExportDuplicatesDialog": (customer_export_controller.PreviousExportDuplicatesDialog,
                                           lambda: customer_export_controller.PreviousExportDuplicatesDialog(
                                               SAMPLE_DUPLICATES)),
        # -- batch 3: tables and buttons --
        "DashboardDialog": (dialogs.DashboardDialog, lambda: dialogs.DashboardDialog({
            "total_records": 120, "total_area": "5,432.1", "with_note": 30,
            "district_counts": [("桃園區", 80), ("", 3)], "case_counts": [("中路段整合", 12, "進行中")],
            "tag_counts": [("優先", 12)]})),
        "RecordHistoryDialog": (dialogs.RecordHistoryDialog, lambda: dialogs.RecordHistoryDialog([
            {"created_at": "2026-11-01 10:00", "action_type": "修改資料", "field_label": "地址",
             "old_value": "桃園市", "new_value": "桃園市桃園區", "customer_id": 7}], "桃園區 123 地號 王小明")),
        "FollowUpListDialog": (dialogs.FollowUpListDialog, lambda: dialogs.FollowUpListDialog([
            {"due_date": "2026-10-30", "status": "未處理", "owner_name": "王小明", "district": "桃園區",
             "section": "中路段", "land_number": "123", "note": "回電", "is_overdue": True, "customer_id": 7},
            {"due_date": "2026-11-20", "status": "待回覆", "owner_name": "李小華", "district": "桃園區",
             "land_number": "124", "customer_id": 8}])),
        "ImportPreviewDialog": (dialogs.ImportPreviewDialog, lambda: dialogs.ImportPreviewDialog(
            SAMPLE_IMPORT_RECORDS, SAMPLE_IMPORT_COLUMNS, [1])),
        "ImportPreviewDialog-plans": (dialogs.ImportPreviewDialog, lambda: dialogs.ImportPreviewDialog(
            SAMPLE_IMPORT_RECORDS[:1], SAMPLE_IMPORT_COLUMNS, [], plans=[{"id": 1, "name": "中壢都市計畫"}],
            default_plan_id=1)),
        "SavedSearchDialog": (dialogs.SavedSearchDialog, lambda: dialogs.SavedSearchDialog(
            [{"name": "桃園區未聯絡", "criteria": {"keyword": "桃園", "advanced": {"a": 1}}}])),
        "OperationLogDialog": (dialogs.OperationLogDialog, lambda: dialogs.OperationLogDialog(rows=[
            {"created_at": "2026-11-01 10:00", "action_type": "匯入", "summary": "匯入 3 筆", "detail": None}])),
        "WatchlistDialog": (dialogs.WatchlistDialog, lambda: dialogs.WatchlistDialog(repository=repository)),
        "TagManagementDialog": (extra.TagManagementDialog, lambda: extra.TagManagementDialog(SAMPLE_TAGS)),
        "CustomerTagsDialog": (extra.CustomerTagsDialog, lambda: extra.CustomerTagsDialog(
            SAMPLE_TAGS, [1], "桃園區 123 地號 王小明")),
        "BatchCustomerTagsDialog": (extra.BatchCustomerTagsDialog, lambda: extra.BatchCustomerTagsDialog(SAMPLE_TAGS, 5)),
        "AttachmentDialog": (extra.AttachmentDialog, lambda: extra.AttachmentDialog([
            {"id": 1, "original_name": "謄本.pdf", "file_path": "attachments/1.pdf", "description": "第一類謄本",
             "status": "managed", "created_at": "2026-11-01"}], "桃園區 123 地號 王小明")),
        "CustomFieldManagementDialog": (extra.CustomFieldManagementDialog, lambda: extra.CustomFieldManagementDialog(
            [{"id": 1, "field_key": "phone2", "label": "第二支電話"}])),
        "ContactLogDialog": (extra.ContactLogDialog, lambda: extra.ContactLogDialog([
            {"id": 1, "contact_date": "2026-11-01", "method": "電話", "result": "未接",
             "next_follow_up": "2026-11-05", "note": "晚上再打"}], "桃園區 123 地號 王小明")),
        "HealthCheckDialog": (extra.HealthCheckDialog, lambda: extra.HealthCheckDialog([
            {"status": "正常", "title": "資料庫", "detail": "完整性檢查通過"},
            {"status": "注意", "title": "備份", "detail": "超過 3 天沒有備份"}])),
        "RecycleBinDialog": (productivity.RecycleBinDialog, lambda: productivity.RecycleBinDialog([
            {"id": 1, "original_id": 7, "display_label": "桃園區 123 地號 王小明", "deleted_by": "admin",
             "deleted_at": "2026-11-01", "entity_type": "customer"}])),
        "UndoOperationsDialog": (productivity.UndoOperationsDialog, lambda: productivity.UndoOperationsDialog([
            {"id": 1, "operation_type": "批次修改", "summary": "地址 3 筆", "actor_username": "admin",
             "status": "可復原", "created_at": "2026-11-01"}])),
        "NotificationCenterDialog": (productivity.NotificationCenterDialog,
                                     lambda: productivity.NotificationCenterDialog(repository)),
        "ImportProfilesDialog": (productivity.ImportProfilesDialog,
                                 lambda: productivity.ImportProfilesDialog(repository, SAMPLE_FIELD_LABELS)),
        "ReportTemplatesDialog": (productivity.ReportTemplatesDialog,
                                  lambda: productivity.ReportTemplatesDialog(repository, SAMPLE_FIELD_LABELS)),
        "DuplicateFinderDialog": (productivity.DuplicateFinderDialog, lambda: productivity.DuplicateFinderDialog([
            {"left_id": 7, "right_id": 9, "score": 92, "reason": "同身分證、同地號",
             "left_label": "王小明 123", "right_label": "王小明 123-1"}])),
        "BackupStatusDialog": (customer_backup_status.BackupStatusDialog,
                               lambda: customer_backup_status.BackupStatusDialog(customer_backup_status.BackupStatus(
                                   database_healthy=True, database_message="ok", backup_count=12,
                                   compressed_count=10, total_bytes=123456789,
                                   latest_backup_time=datetime(2026, 11, 2, 3, 0, 0),
                                   latest_backup_path="C:\\backups\\customers-20261102.zip"), "C:\\backups")),
        "ServerBackupTargetsDialog": (customer_backup_status.ServerBackupTargetsDialog,
                                      lambda: customer_backup_status.ServerBackupTargetsDialog(repository)),
        "ServerBackupRestoreDialog": (customer_backup_status.ServerBackupRestoreDialog,
                                      lambda: customer_backup_status.ServerBackupRestoreDialog([
                                          {"status": "ok", "name": "server-20261102.zip",
                                           "created_at": "2026-11-02 03:00", "record_count": 5000,
                                           "attachment_count": 120, "bytes": 52428800}])),
        "UrbanPlanManagementDialog": (plans.UrbanPlanManagementDialog, lambda: plans.UrbanPlanManagementDialog(
            lambda: SAMPLE_PLANS, _preview_refusal, _preview_refusal, lambda _plan: False)),
        "UrbanPlanManagementDialog-readonly": (plans.UrbanPlanManagementDialog,
                                               lambda: plans.UrbanPlanManagementDialog(
                                                   lambda: SAMPLE_PLANS, _preview_refusal, _preview_refusal,
                                                   lambda _plan: False, can_edit=False)),
        # -- batch 5: large dialogs --
        "ImportResultDialog-plan": (dialogs.ImportResultDialog, lambda: dialogs.ImportResultDialog(
            ["新增 3 筆"], plan_summary={
                "name": "中壢都市計畫", "assigned_land_count": 3, "kept_land_count": 3,
                "kept_lands": [{"district": "桃園區", "section": "中路段", "land_number": "123", "urban_plan_name": "桃園"},
                               {"district": "桃園區", "section": "中路段", "land_number": "124", "urban_plan_name": "桃園"}]})),
        "DataQualityRulesDialog": (dialogs.DataQualityRulesDialog, dialogs.DataQualityRulesDialog),
        "DataQualityDialog": (dialogs.DataQualityDialog, lambda: dialogs.DataQualityDialog(
            quality_issues, 10, ignored_count=1)),
        "VisitCalendarDialog": (dialogs.VisitCalendarDialog, lambda: dialogs.VisitCalendarDialog(_PreviewCalendarWindow())),
        "ColumnVisibilityDialog": (dialogs.ColumnVisibilityDialog, lambda: dialogs.ColumnVisibilityDialog(
            [("district", "地區"), ("section", "地段"), ("land_number", "地號"), ("owner_name", "姓名")], ["section"])),
        "AdvancedSearchDialog": (dialogs.AdvancedSearchDialog, lambda: dialogs.AdvancedSearchDialog(
            {"owner_name": "王", "_exclude_keyword": "測試"})),
        "SharedLandBatchDialog": (dialogs.SharedLandBatchDialog, lambda: dialogs.SharedLandBatchDialog(
            {"district": "桃園區", "section": "中路段"}, district_options=["桃園區", "中壢區"])),
        "CustomerCustomValuesDialog": (extra.CustomerCustomValuesDialog, lambda: extra.CustomerCustomValuesDialog(
            custom_fields, {1: "0912"}, "桃園區 123 地號 王小明")),
        "BatchCustomerCustomValuesDialog": (extra.BatchCustomerCustomValuesDialog,
                                            lambda: extra.BatchCustomerCustomValuesDialog(custom_fields, 3)),
        "TextTemplateDialog": (extra.TextTemplateDialog, lambda: extra.TextTemplateDialog(
            [{"id": 1, "template_type": "note", "title": "未接", "content": "電話未接，晚點再打"}])),
        "OwnerContactDialog-new": (contacts.OwnerContactDialog, lambda: contacts.OwnerContactDialog(
            repository, 1, owner_address="桃園市")),
        "OwnerContactDialog-edit": (contacts.OwnerContactDialog, lambda: contacts.OwnerContactDialog(
            repository, 1, existing=contact, owner_address="桃園市")),
        "OwnerContactDialog-view": (contacts.OwnerContactDialog, lambda: contacts.OwnerContactDialog(
            repository, 1, existing=contact, readonly=True, allow_edit=True)),
        "UserManagementDialog": (productivity.UserManagementDialog,
                                 lambda: productivity.UserManagementDialog(repository, b"preview")),
        "BackupTargetsDialog": (productivity.BackupTargetsDialog,
                                lambda: productivity.BackupTargetsDialog(repository, _PreviewBackupService())),
        "WorkflowDialog": (productivity.WorkflowDialog, lambda: productivity.WorkflowDialog(
            repository, record_ids_to_attach=[1, 2])),
        "MapLocationsDialog": (productivity.MapLocationsDialog,
                               lambda: productivity.MapLocationsDialog(repository, PREVIEW_FERNET)),
    }
    return {
        name: (getattr(cls, "ui_file", None) or cls.CONTACT_GROUP_UI_FILE, cls, factory)
        for name, (cls, factory) in entries.items()
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", help="dialog name (see --list)")
    parser.add_argument("theme", nargs="?", default="light", choices=("light", "dark"))
    parser.add_argument("--list", action="store_true", help="list the dialog names and their .ui files")
    parser.add_argument("--screenshot", help="save a PNG of the dialog and exit")
    args = parser.parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    import customer_theme
    import customer_ui_qt as app

    customer_theme.activate_theme(args.theme)
    app.refresh_theme_constants()
    customer_theme.load_bundled_fonts()
    app.apply_font_size(qt_app, app.DEFAULT_FONT_SIZE_KEY)
    app.apply_app_style(qt_app)

    dialogs = sample_dialogs()
    if args.list or not args.name:
        for name, (ui_file, _cls, _factory) in dialogs.items():
            print(f"{name:32} ui/{ui_file}")
        return 0
    if args.name not in dialogs:
        print(f"沒有這個對話框：{args.name}（用 --list 看全部名稱）")
        return 2

    dialog = dialogs[args.name][2]()
    dialog.setWindowTitle(dialog.windowTitle() + "（預覽）")
    dialog.finished.connect(qt_app.quit)
    dialog.show()
    if args.screenshot:
        def save_and_quit():
            dialog.grab().save(args.screenshot)
            dialog.done(0)

        QTimer.singleShot(500, save_and_quit)
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
