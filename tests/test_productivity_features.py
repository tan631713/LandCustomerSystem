import json
import os
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from customer_database import CustomerDatabase
from customer_excel import HEADER_MAP, normalize_header
from customer_productivity import (
    BackupTargetsDialog,
    DuplicateFinderDialog,
    ImportProfilesDialog,
    MapLocationsDialog,
    NotificationCenterDialog,
    ProductivityService,
    RecycleBinDialog,
    ReportTemplatesDialog,
    UndoOperationsDialog,
    UserManagementDialog,
    WorkflowDialog,
    apply_default_import_profile,
    export_report_with_template,
)
from customer_repository import CustomerRepository
from customer_security import decrypt_value, encrypt_record, make_fernet


LAND_FIELDS = [
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("area", "面積"),
    ("declared_value", "公告現值"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("ping", "坪數"),
    ("total_declared_value", "總現值"),
    ("owner_name", "姓名"),
    ("external_id", "身分證"),
    ("address", "地址"),
    ("registration_reason", "原因"),
    ("note", "備註"),
    ("visit_log", "出訪記錄"),
]


class ProductivityFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.database = CustomerDatabase(
            self.root / "customers.db", self.root / "backups"
        )
        project_root = Path(__file__).resolve().parents[1]
        self.repository = CustomerRepository(
            self.database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            LAND_FIELDS,
        )
        self.repository.init_db()
        self.service = ProductivityService(
            self.repository,
            self.database,
            self.root,
            self.root / "attachments",
        )

    def tearDown(self):
        self.temp_context.cleanup()

    @staticmethod
    def record(**values):
        base = {key: "" for key, _label in LAND_FIELDS}
        base.update(values)
        base["name"] = base.get("owner_name") or ""
        return base

    def test_recycle_bin_restores_customer_and_all_management_relations(self):
        customer_id = self.repository.save_customer(
            self.record(
                district="桃園區", section="中正段", land_number="100",
                owner_name="王小明",
            )
        )
        case_id = self.repository.save_case("收購案")
        tag_id = self.repository.save_tag("重要")
        field_id = self.repository.save_custom_field("來源")
        self.repository.add_customers_to_case(case_id, [customer_id])
        self.repository.set_customer_tags(customer_id, [tag_id])
        self.repository.set_customer_custom_values(customer_id, {field_id: "介紹"})
        self.repository.add_customer_attachment(customer_id, "C:/docs/a.pdf", "謄本")
        self.repository.add_contact_log(customer_id, "2026-07-13", "電話", "完成")
        self.repository.save_follow_up_reminder(customer_id, "2026-07-14", "待處理")
        self.repository.set_customer_location(customer_id, 25.033, 121.5654)

        self.assertEqual(self.repository.delete_customers([customer_id]), 1)
        self.assertIsNone(self.repository.get_customer(customer_id))
        recycle_row = self.repository.list_recycle_bin()[0]
        restored = self.repository.restore_recycle_items([recycle_row["id"]])

        self.assertEqual(restored, [customer_id])
        self.assertIsNotNone(self.repository.get_customer(customer_id))
        self.assertEqual(len(self.repository.list_case_members(case_id)), 1)
        self.assertEqual(self.repository.get_customer_tag_ids(customer_id), {tag_id})
        self.assertEqual(
            self.repository.get_customer_custom_values(customer_id)[field_id], "介紹"
        )
        self.assertEqual(len(self.repository.list_customer_attachments(customer_id)), 1)
        self.assertEqual(len(self.repository.list_contact_logs(customer_id)), 1)
        self.assertIsNotNone(self.repository.get_follow_up_reminder(customer_id))
        self.assertEqual(len(self.repository.list_customer_locations()), 1)

    def test_batch_insert_and_update_undo_operations_are_effective(self):
        customer_id = self.repository.save_customer(
            self.record(district="舊地區", land_number="100", owner_name="A")
        )
        self.repository.record_customer_undo("批次修改", [customer_id], "修改地區")
        changed = self.record(district="新地區", land_number="100", owner_name="A")
        self.repository.save_customer(changed, customer_id)
        operation = self.repository.list_undo_operations()[0]
        self.repository.undo_operation(operation["id"])
        self.assertEqual(self.repository.get_customer(customer_id)["district"], "舊地區")

        self.repository.insert_customers(
            [self.record(district="D", land_number="200", owner_name="B")]
        )
        inserted_id = self.repository.last_inserted_customer_ids[0]
        self.repository.record_insert_undo("匯入", [inserted_id], "匯入一筆")
        self.repository.undo_operation()
        self.assertIsNone(self.repository.get_customer(inserted_id))

    def test_multi_user_accounts_share_the_same_encryption_key_and_roles(self):
        self.repository.create_admin_user("admin-password")
        data_key = self.repository.authenticate_user("admin", "admin-password")
        fernet = make_fernet(data_key)
        customer_id = self.repository.save_customer(
            encrypt_record(
                fernet,
                self.record(owner_name="王小明", external_id="A123456789"),
            )
        )
        user_id = self.repository.create_user(
            "editor1", "editor-password", "editor", data_key, "編輯人員"
        )

        editor_key = self.repository.authenticate_user("editor1", "editor-password")
        self.assertEqual(editor_key, data_key)
        self.assertEqual(
            decrypt_value(make_fernet(editor_key), self.repository.get_customer(customer_id)["owner_name"]),
            "王小明",
        )
        self.assertEqual(self.repository.last_authenticated_user["role"], "editor")
        self.repository.update_user(user_id, active=False)
        self.assertIsNone(self.repository.authenticate_user("editor1", "editor-password"))

    def test_saved_offsite_password_survives_admin_password_change(self):
        self.repository.create_admin_user("admin-password")
        data_key = self.repository.authenticate_user("admin", "admin-password")
        service = ProductivityService(
            self.repository,
            self.database,
            self.root,
            self.root / "attachments",
            make_fernet(data_key),
        )
        service.save_offsite_backup_password("portable-password")
        new_key, _backup_path = self.repository.change_admin_password(
            "admin-password", "new-admin-password"
        )
        self.assertEqual(new_key, data_key)
        service.fernet = make_fernet(new_key)
        self.assertEqual(service.load_offsite_backup_password(), "portable-password")

    def test_managed_attachments_portable_backup_and_verified_mirror(self):
        customer_id = self.repository.save_customer(
            self.record(district="D", land_number="100")
        )
        source = self.root / "source.txt"
        source.write_text("attachment-content", encoding="utf-8")
        attachment_id = self.repository.import_managed_attachment(
            customer_id, source, self.root / "attachments", "文件"
        )
        results = self.repository.verify_managed_attachments()
        self.assertEqual(results[0]["id"], attachment_id)
        self.assertEqual(results[0]["state"], "正常")

        target = self.root / "offsite"
        self.repository.save_backup_target("USB", target)
        archive_path, sync_results = self.service.sync_backup_targets()
        self.assertEqual(sync_results[0][1], "成功")
        self.assertTrue((target / archive_path.name).is_file())
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("database/customers.db", archive.namelist())
            self.assertTrue(any(name.startswith("attachments/") for name in archive.namelist()))

    def test_encrypted_full_backup_verifies_and_restores_database_and_attachments(self):
        self.repository.create_admin_user("admin-password")
        data_key = self.repository.authenticate_user("admin", "admin-password")
        encrypted_service = ProductivityService(
            self.repository,
            self.database,
            self.root,
            self.root / "attachments",
            make_fernet(data_key),
        )
        customer_id = self.repository.save_customer(
            self.record(district="備份前", land_number="100")
        )
        source = self.root / "source.txt"
        source.write_text("original", encoding="utf-8")
        self.repository.import_managed_attachment(
            customer_id, source, self.root / "attachments"
        )
        managed_path = Path(
            self.repository.list_customer_attachments(customer_id)[0]["storage_path"]
        )
        archive = encrypted_service.create_full_backup("portable-password")
        self.assertEqual(archive.suffix, ".lcsbak")
        self.assertTrue(
            encrypted_service.verify_full_backup(archive, "portable-password")
        )
        with self.assertRaises(ValueError):
            encrypted_service.verify_full_backup(archive, "wrong-password")

        self.repository.save_customer(
            self.record(district="備份後", land_number="100"), customer_id
        )
        managed_path.write_text("changed", encoding="utf-8")
        encrypted_service.restore_full_backup(archive, "portable-password")
        self.assertEqual(self.repository.get_customer(customer_id)["district"], "備份前")
        restored_path = Path(
            self.repository.list_customer_attachments(customer_id)[0]["storage_path"]
        )
        self.assertEqual(restored_path.read_text(encoding="utf-8"), "original")

    def test_workflow_notifications_profiles_reports_duplicates_and_map(self):
        due = date.today().isoformat()
        customer_id = self.repository.save_customer(
            self.record(
                district="桃園區", section="中正段", land_number="100",
                owner_name="王小明", external_id="A123456789", address="桃園市測試路1號",
            )
        )
        duplicate_id = self.repository.save_customer(
            self.record(
                district="桃園區", section="中正段", land_number="100",
                owner_name="王小明", external_id="A123456789", address="桃園市測試路1號",
            )
        )
        case_id = self.repository.save_case(
            "案件A", assigned_to="小李", due_date=due, priority="高", next_action="聯絡"
        )
        task_id = self.repository.save_case_task(
            case_id,
            "確認謄本",
            assignee="小李",
            due_date=(date.today() - timedelta(days=1)).isoformat(),
            priority="緊急",
        )
        self.repository.save_follow_up_reminder(customer_id, due, "待處理")
        self.repository.refresh_notifications(due)
        categories = {row["category"] for row in self.repository.list_notifications()}
        self.assertEqual(categories, {"追蹤", "案件", "任務"})
        self.assertEqual(self.repository.list_case_tasks()[0]["id"], task_id)

        self.repository.save_import_profile(
            "地政格式", {"所有權人": "owner_name"}, is_default=True
        )
        self.assertEqual(apply_default_import_profile(self.repository), 1)
        self.assertEqual(HEADER_MAP[normalize_header("所有權人")], "owner_name")

        template_id = self.repository.save_report_template(
            "地主清冊", "地主清冊", ["district", "land_number", "owner_name"],
            header_text="測試頁首", footer_text="測試頁尾",
        )
        template = dict(self.repository.list_report_templates()[0])
        report_path = self.root / "report.docx"
        export_report_with_template(
            report_path,
            [self.record(district="桃園區", land_number="100", owner_name="王小明")],
            template,
            dict(LAND_FIELDS),
        )
        self.assertEqual(template["id"], template_id)
        self.assertTrue(report_path.is_file())

        plain_records = [dict(self.repository.get_customer(customer_id)), dict(self.repository.get_customer(duplicate_id))]
        pairs = self.service.find_duplicate_pairs(plain_records)
        self.assertEqual(pairs[0]["score"], 100)

        self.repository.set_customer_location(customer_id, 25.033, 121.5654)
        locations = [dict(row) for row in self.repository.list_customer_locations()]
        map_path = self.root / "map.html"
        self.assertEqual(self.service.build_map_html(locations, map_path), 1)
        map_text = map_path.read_text(encoding="utf-8")
        self.assertIn("OpenStreetMap", map_text)
        self.assertIn("桃園區", map_text)

    def test_all_productivity_dialogs_construct_against_real_repository(self):
        self.repository.create_admin_user("admin-password")
        data_key = self.repository.authenticate_user("admin", "admin-password")
        dialogs = [
            RecycleBinDialog(self.repository.list_recycle_bin()),
            UndoOperationsDialog(self.repository.list_undo_operations()),
            UserManagementDialog(self.repository, data_key),
            BackupTargetsDialog(self.repository, self.service),
            WorkflowDialog(self.repository),
            NotificationCenterDialog(self.repository),
            ImportProfilesDialog(self.repository, dict(LAND_FIELDS)),
            ReportTemplatesDialog(self.repository, dict(LAND_FIELDS)),
            DuplicateFinderDialog([]),
            MapLocationsDialog(self.repository, make_fernet(data_key)),
        ]
        try:
            self.assertEqual(len(dialogs), 10)
            self.assertTrue(all(dialog.windowTitle() for dialog in dialogs))
        finally:
            for dialog in dialogs:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
