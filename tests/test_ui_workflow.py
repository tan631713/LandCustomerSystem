import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import customer_ui_qt as app
import customer_auth
import customer_import_controller as import_controller
import customer_backup_status as backup_status_module
from customer_database import CustomerDatabase
from customer_repository import CustomerRepository
from customer_security import decrypt_value


class UiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.originals = {
            "DB_PATH": app.DB_PATH,
            "BACKUP_DIR": app.BACKUP_DIR,
            "DATABASE": app.DATABASE,
            "REPOSITORY": app.REPOSITORY,
        }
        app.DB_PATH = self.root / "customers.db"
        app.BACKUP_DIR = self.root / "backups"
        app.DATABASE = CustomerDatabase(app.DB_PATH, app.BACKUP_DIR)
        app.REPOSITORY = CustomerRepository(
            app.DATABASE,
            app.SCHEMA_PATH,
            self.root / "missing-seed.sql",
            app.LAND_FIELDS,
        )
        app.init_db()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def wait_for_record_searches(self, window, timeout_ms=12000):
        loop = QEventLoop()
        poll_timer = QTimer()
        poll_timer.timeout.connect(
            lambda: loop.quit() if not window.record_searches else None
        )
        poll_timer.start(10)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        poll_timer.stop()
        self.assertFalse(window.record_searches, "背景搜尋未在時限內結束")

    def test_postgresql_login_uses_api_account_not_legacy_sqlite_account(self):
        class FakeApiClient:
            def __init__(self):
                self.current_user = None
                self.calls = []

            def login(self, username, password):
                self.calls.append((username, password))
                self.current_user = {
                    "username": username,
                    "display_name": "API 使用者",
                    "role": "admin",
                }
                return {"access_token": "token", "user": self.current_user}

        fake_client = FakeApiClient()
        original_authenticate = customer_auth.AUTHENTICATE_USER
        try:
            app.configure_api_authentication(fake_client)
            with patch.object(
                app.REPOSITORY,
                "authenticate_user",
                side_effect=AssertionError("不得使用 SQLite 帳號登入 PostgreSQL 正式版"),
            ):
                key = customer_auth.AUTHENTICATE_USER("remote-admin", "remote-password")
            self.assertEqual(fake_client.calls, [("remote-admin", "remote-password")])
            self.assertEqual(len(key), 44)
        finally:
            customer_auth.configure_auth_dialog(
                admin_username=app.ADMIN_USERNAME,
                create_admin_user=app.create_admin_user,
                authenticate_user=original_authenticate,
            )

    def test_login_create_search_update_and_delete_flow(self):
        with (
            patch.object(app.QMessageBox, "information", return_value=QMessageBox.Ok),
            patch.object(app.QMessageBox, "warning", return_value=QMessageBox.Ok),
            patch.object(app.QMessageBox, "critical", return_value=QMessageBox.Ok),
            patch.object(app.QMessageBox, "question", return_value=QMessageBox.Yes),
        ):
            setup_dialog = app.AuthDialog(setup_mode=True)
            setup_dialog.password_edit.setText("test-password")
            setup_dialog.confirm_edit.setText("test-password")
            setup_dialog.submit()
            self.assertEqual(setup_dialog.result(), QDialog.Accepted)
            self.assertIsNotNone(setup_dialog.encryption_key)

            login_dialog = app.AuthDialog(setup_mode=False)
            login_dialog.password_edit.setText("test-password")
            login_dialog.submit()
            self.assertEqual(login_dialog.result(), QDialog.Accepted)

            window = app.LandApp(login_dialog.encryption_key)
            try:
                values = {
                    "district": "中正區",
                    "section": "一段",
                    "land_number": "100",
                    "area": "100",
                    "declared_value": "20,000",
                    "numerator": "1",
                    "denominator": "2",
                    "owner_name": "王小明",
                    "address": "台北市舊地址",
                }
                for key, value in values.items():
                    window.set_field_text(key, value)
                window.save_record()
                record_id = window.selected_record_id

                self.assertIsNotNone(record_id)
                self.assertEqual(len(window.table_model.all_rows), 1)
                self.assertEqual(window.table_model.all_rows[0]["raw"]["owner_name"], "王小明")

                window.search_input.setText("王小明")
                window.refresh_records()
                self.assertEqual(len(window.table_model.all_rows), 1)
                window.search_input.setText("不存在")
                window.refresh_records()
                self.assertEqual(len(window.table_model.all_rows), 0)

                window.search_input.clear()
                window.refresh_records(record_id)
                window.load_record(record_id)
                window.set_field_text("address", "台北市新地址")
                window.save_record()
                with app.connect() as conn:
                    encrypted_address = conn.execute(
                        "SELECT address FROM customers WHERE id = ?", (record_id,)
                    ).fetchone()[0]
                self.assertEqual(
                    decrypt_value(window.fernet, encrypted_address),
                    "台北市新地址",
                )
                history_logs = app.REPOSITORY.get_record_change_logs(record_id)
                self.assertTrue(
                    any(
                        row["field_key"] == "address"
                        and decrypt_value(window.fernet, row["old_value"]) == "台北市舊地址"
                        and decrypt_value(window.fernet, row["new_value"]) == "台北市新地址"
                        for row in history_logs
                    )
                )

                window.delete_record()
                with app.connect() as conn:
                    customer_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                    actions = [
                        row[0]
                        for row in conn.execute(
                            "SELECT action_type FROM operation_logs ORDER BY id"
                        )
                    ]
                self.assertEqual(customer_count, 0)
                self.assertEqual(actions, ["新增資料", "修改資料", "刪除資料"])
            finally:
                window.close()

    def test_follow_up_dashboard_and_history_dialogs(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            window.set_field_text("district", "桃園區")
            window.set_field_text("section", "一段")
            window.set_field_text("land_number", "100")
            window.set_field_text("owner_name", "王小明")
            with patch.object(app.QMessageBox, "information", return_value=QMessageBox.Ok):
                window.save_record()
            record_id = window.selected_record_id

            class FakeFollowUpReminderDialog:
                delete_requested = False

                def __init__(self, label, reminder, parent):
                    self.label = label
                    self.reminder = reminder
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def values(self):
                    return {"due_date": "2026-07-20", "status": "待回覆", "note": "再聯絡"}

            captured = {}

            class FakeDashboardDialog:
                def __init__(self, stats, parent):
                    captured["stats"] = stats
                    captured["dashboard_parent"] = parent

                def exec(self):
                    return QDialog.Accepted

            class FakeFollowUpListDialog:
                def __init__(self, reminders, parent=None, on_record_activated=None):
                    captured["reminders"] = reminders
                    captured["list_parent"] = parent
                    captured["on_record_activated"] = on_record_activated

                def exec(self):
                    return QDialog.Accepted

            class FakeRecordHistoryDialog:
                def __init__(self, logs, record_label="", parent=None):
                    captured["history_logs"] = logs
                    captured["history_label"] = record_label
                    captured["history_parent"] = parent

                def exec(self):
                    return QDialog.Accepted

            with (
                patch.object(app, "FollowUpReminderDialog", FakeFollowUpReminderDialog),
                patch.object(app, "DashboardDialog", FakeDashboardDialog),
                patch.object(app, "FollowUpListDialog", FakeFollowUpListDialog),
                patch.object(app, "RecordHistoryDialog", FakeRecordHistoryDialog),
                patch.object(app.QMessageBox, "information", return_value=QMessageBox.Ok),
            ):
                window.edit_follow_up_reminder()
                window.show_dashboard()
                window.show_follow_up_list()
                window.show_record_history()

            reminder = app.REPOSITORY.get_follow_up_reminder(record_id)
            self.assertEqual(reminder["status"], "待回覆")
            self.assertEqual(decrypt_value(window.fernet, reminder["note"]), "再聯絡")
            self.assertEqual(captured["stats"]["open_follow_ups"], 1)
            self.assertEqual(captured["reminders"][0]["customer_id"], record_id)
            self.assertEqual(captured["reminders"][0]["note"], "再聯絡")
            self.assertIn("ID", captured["history_label"])
        finally:
            window.close()

    def test_extra_management_workflows_and_readonly_mode(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            first_plain = window.normalize_record_data(
                {
                    "district": "D",
                    "section": "S",
                    "land_number": "100",
                    "owner_name": "Owner 1",
                    "note": "",
                    "name": "Owner 1",
                }
            )
            second_plain = window.normalize_record_data(
                {
                    "district": "D",
                    "section": "S",
                    "land_number": "100",
                    "owner_name": "Owner 2",
                    "external_id": "A2",
                    "address": "Address 2",
                    "note": "secondary note",
                    "name": "Owner 2",
                }
            )
            first_id = app.REPOSITORY.save_customer(app.encrypt_record(window.fernet, first_plain))
            second_id = app.REPOSITORY.save_customer(app.encrypt_record(window.fernet, second_plain))
            case_id = app.REPOSITORY.save_case("Case A")
            tag_id = app.REPOSITORY.save_tag("Important")
            field_id = app.REPOSITORY.save_custom_field("Extra", "extra")
            template_id = app.REPOSITORY.save_text_template("Note", "Template text", "note")
            window.refresh_records(first_id)
            window.load_record(first_id)
            window.checked_record_ids = {first_id}

            class FakeCaseSelectDialog:
                def __init__(self, cases, selected_count, parent):
                    self.cases = cases
                    self.selected_count = selected_count
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def selected_case_id(self):
                    return case_id

            class FakeCustomerTagsDialog:
                def __init__(self, tags, selected_ids, record_label, parent):
                    self.tags = tags
                    self.selected_ids_before = selected_ids
                    self.record_label = record_label
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def selected_ids(self):
                    return [tag_id]

            class FakeCustomerCustomValuesDialog:
                def __init__(self, fields, values, record_label, parent):
                    self.fields = fields
                    self.values = values
                    self.record_label = record_label
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def result_values(self):
                    return {field_id: "custom value"}

            class FakeApplyTemplateDialog:
                def __init__(self, templates, parent):
                    self.templates = templates
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def values(self):
                    return {
                        "target_field": "note",
                        "template": {
                            "id": template_id,
                            "title": "Note",
                            "content": "Template text",
                        },
                    }

            class FakeContactLogDialog:
                action = "add"

                def __init__(self, logs, record_label, parent):
                    self.logs = logs
                    self.record_label = record_label
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

                def values(self):
                    return {
                        "contact_date": "2026-07-13",
                        "method": "phone",
                        "result": "ok",
                        "next_follow_up": "2026-07-20",
                        "note": "contact note",
                    }

            class FakeMergeRecordsDialog:
                def __init__(self, primary_label, secondary_label, preview_lines, parent):
                    self.primary_label = primary_label
                    self.secondary_label = secondary_label
                    self.preview_lines = preview_lines
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

            captured = {}

            class FakeHealthCheckDialog:
                def __init__(self, checks, parent):
                    captured["checks"] = checks
                    captured["health_parent"] = parent

                def exec(self):
                    return QDialog.Accepted

            with (
                patch.object(app, "CaseSelectDialog", FakeCaseSelectDialog),
                patch.object(app, "CustomerTagsDialog", FakeCustomerTagsDialog),
                patch.object(app, "CustomerCustomValuesDialog", FakeCustomerCustomValuesDialog),
                patch.object(app, "ApplyTemplateDialog", FakeApplyTemplateDialog),
                patch.object(app, "ContactLogDialog", FakeContactLogDialog),
                patch.object(app, "MergeRecordsDialog", FakeMergeRecordsDialog),
                patch.object(app, "HealthCheckDialog", FakeHealthCheckDialog),
                patch.object(app.QMessageBox, "information", return_value=QMessageBox.Ok),
                patch.object(app.QMessageBox, "warning", return_value=QMessageBox.Ok),
            ):
                window.assign_checked_records_to_case()
                window.edit_customer_tags()
                window.edit_customer_custom_values()
                window.apply_text_template()
                self.assertIn("Template text", window.get_field_text("note"))
                window.manage_contact_logs()
                window.show_health_check()
                window.checked_record_ids = {first_id, second_id}
                window.merge_checked_records()

            self.assertEqual(len(app.REPOSITORY.list_case_members(case_id)), 1)
            self.assertEqual(app.REPOSITORY.get_customer_tag_ids(first_id), {tag_id})
            self.assertEqual(app.REPOSITORY.get_customer_custom_values(first_id)[field_id], "custom value")
            self.assertEqual(decrypt_value(window.fernet, app.REPOSITORY.list_contact_logs(first_id)[0]["note"]), "contact note")
            self.assertIsNone(app.REPOSITORY.get_customer(second_id))
            self.assertTrue(captured["checks"])

            app.set_setting(app.READONLY_MODE_SETTING_KEY, "1")
            with patch.object(app.QMessageBox, "warning", return_value=QMessageBox.Ok) as warning:
                window.save_record()
            self.assertTrue(warning.called)
        finally:
            app.set_setting(app.READONLY_MODE_SETTING_KEY, "0")
            window.close()

    def test_excel_import_can_update_existing_duplicate_records(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            existing = window.normalize_record_data(
                {
                    "district": "桃園區",
                    "section": "一段",
                    "land_number": "100",
                    "owner_name": "王小明",
                    "address": "舊地址",
                    "name": "王小明",
                }
            )
            record_id = app.REPOSITORY.save_customer(app.encrypt_record(window.fernet, existing))

            class FakePreviewDialog:
                import_mode = "update_duplicates"

                def __init__(self, records, columns, duplicates, parent):
                    self.records = records
                    self.columns = columns
                    self.duplicates = duplicates
                    self.parent = parent

                def exec(self):
                    return QDialog.Accepted

            captured = {}

            class FakeImportResultDialog:
                def __init__(self, summary_lines, detail_lines=None, error_rows=None, parent=None):
                    captured["summary_lines"] = summary_lines
                    captured["detail_lines"] = detail_lines
                    captured["error_rows"] = error_rows
                    captured["parent"] = parent

                def exec(self):
                    return QDialog.Accepted

            result = {
                "column_map": {
                    1: "district",
                    2: "section",
                    3: "land_number",
                    4: "owner_name",
                    5: "address",
                },
                "records": [
                    {
                        "district": "桃園區",
                        "section": "一段",
                        "land_number": "100",
                        "owner_name": "王小明",
                        "address": "新地址",
                        "name": "王小明",
                    }
                ],
                "error_rows": [],
            }

            with (
                patch.object(import_controller, "ImportPreviewDialog", FakePreviewDialog),
                patch.object(import_controller, "ImportResultDialog", FakeImportResultDialog),
                patch.object(app.QMessageBox, "question", return_value=QMessageBox.Yes),
                patch.object(app.QMessageBox, "critical", return_value=QMessageBox.Ok),
            ):
                window.handle_excel_import_ready(result)

            with app.connect() as conn:
                rows = conn.execute("SELECT id, address FROM customers ORDER BY id").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], record_id)
            self.assertEqual(decrypt_value(window.fernet, rows[0]["address"]), "新地址")
            self.assertIn("成功更新：1", captured["summary_lines"])
            logs = app.REPOSITORY.get_record_change_logs(record_id)
            self.assertTrue(any(row["field_key"] == "address" for row in logs))
        finally:
            window.close()

    def test_postgresql_preview_excel_import_uses_api_batch_without_sqlite_backup(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")

        class ApiImportRepository:
            data_revision = 0

            def __init__(self):
                self.import_calls = []

            def count_customers(self):
                return 0

            def fetch_customer_page(self, limit, before_id=None):
                del limit, before_id
                return []

            def fetch_search_candidate_rows(self, **_criteria):
                return []

            def fetch_duplicate_candidates(self):
                return []

            def find_watchlist_match(self, _name):
                return None

            def get_customer(self, _record_id):
                return None

            def import_records(self, inserted, updated, source_file_name):
                self.import_calls.append((list(inserted), list(updated), source_file_name))
                self.data_revision += 1
                return {
                    "batch_id": 21,
                    "inserted_count": len(inserted),
                    "updated_count": len(updated),
                    "inserted_ids": [501],
                    "updated_ids": [],
                }

        class FakePreviewDialog:
            import_mode = "import_all"

            def __init__(self, records, columns, duplicates, parent):
                del records, columns, duplicates, parent

            def exec(self):
                return QDialog.Accepted

        captured = {}

        class FakeImportResultDialog:
            def __init__(self, summary_lines, detail_lines=None, error_rows=None, parent=None):
                captured["summary_lines"] = summary_lines
                del detail_lines, error_rows, parent

            def exec(self):
                return QDialog.Accepted

        repository = ApiImportRepository()
        window = app.LandApp(
            encryption_key,
            record_repository=repository,
            api_mode=True,
        )
        try:
            result = {
                "source_file_name": "地主清冊.xlsx",
                "column_map": {
                    1: "district",
                    2: "section",
                    3: "land_number",
                    4: "owner_name",
                },
                "records": [
                    {
                        "district": "中壢區",
                        "section": "青埔段",
                        "land_number": "200-8",
                        "owner_name": "李小華",
                        "name": "李小華",
                    }
                ],
                "error_rows": [],
            }
            with (
                patch.object(import_controller, "ImportPreviewDialog", FakePreviewDialog),
                patch.object(import_controller, "ImportResultDialog", FakeImportResultDialog),
                patch.object(window, "create_safety_backup") as safety_backup,
                patch.object(window, "refresh_records"),
            ):
                window.handle_excel_import_ready(result)

            safety_backup.assert_not_called()
            self.assertEqual(len(repository.import_calls), 1)
            inserted, updated, source_name = repository.import_calls[0]
            self.assertEqual(len(inserted), 1)
            self.assertFalse(updated)
            self.assertEqual(source_name, "地主清冊.xlsx")
            self.assertIn("成功新增：1", captured["summary_lines"])
        finally:
            window.close()

    def test_default_browse_uses_pages_but_search_scans_all_records(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        records = [
            ("D", "oldest-special-target" if number == 0 else f"land-{number}")
            for number in range(505)
        ]
        with app.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                records,
            )

        window = app.LandApp(encryption_key)
        try:
            self.assertEqual(window.table_model.total_count, 505)
            self.assertEqual(window.table_model.rowCount(), app.TABLE_BATCH_SIZE)
            self.assertTrue(window.table_model.canFetchMore())

            window.search_input.setText("oldest-special-target")
            window.refresh_records()
            loop = QEventLoop()
            poll_timer = QTimer()
            poll_timer.timeout.connect(
                lambda: loop.quit() if not window.record_searches else None
            )
            poll_timer.start(10)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            poll_timer.stop()
            self.assertFalse(window.record_searches)
            self.assertEqual(len(window.table_model.all_rows), 1)
            self.assertEqual(
                window.table_model.all_rows[0]["raw"]["land_number"],
                "oldest-special-target",
            )

            window.search_input.setText("land-504")
            window.refresh_records()
            window.search_input.setText("land-503")
            window.refresh_records()
            loop = QEventLoop()
            poll_timer = QTimer()
            poll_timer.timeout.connect(
                lambda: loop.quit() if not window.record_searches else None
            )
            poll_timer.start(10)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            poll_timer.stop()
            self.assertFalse(window.record_searches)
            self.assertEqual(len(window.table_model.all_rows), 1)
            self.assertEqual(
                window.table_model.all_rows[0]["raw"]["land_number"],
                "land-503",
            )
        finally:
            window.close()

    def test_checked_and_selected_records_survive_window_reopen(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            record_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("D", "persistent-selection"),
            ).lastrowid

        first_window = app.LandApp(encryption_key)
        try:
            checked_index = first_window.table_model.index(0, 0)
            self.assertTrue(
                first_window.table_model.setData(
                    checked_index, Qt.Checked, Qt.CheckStateRole
                )
            )
            first_window.load_record(record_id)
        finally:
            first_window.close()

        second_window = app.LandApp(encryption_key)
        try:
            self.assertEqual(second_window.selected_record_id, record_id)
            self.assertEqual(second_window.checked_record_ids, {record_id})
            row_number = second_window.table_model.row_for_record_id(record_id)
            self.assertGreaterEqual(row_number, 0)
            self.assertTrue(second_window.table_model.rows[row_number]["checked"])
        finally:
            second_window.close()

    def test_bulk_selection_actions_check_visible_and_selected_rows(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            first_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("SEL", "bulk-visible-1"),
            ).lastrowid
            second_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("SEL", "bulk-visible-2"),
            ).lastrowid
            third_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("OTHER", "bulk-hidden"),
            ).lastrowid

        window = app.LandApp(encryption_key)
        try:
            selection = window.table_view.selectionModel()
            selection.clearSelection()
            for record_id in (first_id, second_id):
                row_number = window.table_model.row_for_record_id(record_id)
                index = window.table_model.index(row_number, 0)
                selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)

            self.assertEqual(set(window.selected_table_record_ids()), {first_id, second_id})
            self.assertEqual(set(window.selected_or_checked_record_ids()), {first_id, second_id})
            window.check_selected_rows()
            self.assertEqual(window.checked_record_ids, {first_id, second_id})

            window.uncheck_selected_rows()
            self.assertEqual(window.checked_record_ids, set())

            window.search_input.setText("bulk-visible")
            window.refresh_records()
            visible_ids = {row["id"] for row in window.table_model.load_all()}
            self.assertEqual(visible_ids, {first_id, second_id})

            window.check_visible_records()
            self.assertEqual(window.checked_record_ids, {first_id, second_id})
            self.assertNotIn(third_id, window.checked_record_ids)

            window.invert_visible_checked_records()
            self.assertEqual(window.checked_record_ids, set())

            window.checked_record_ids = {first_id, second_id, third_id}
            window.clear_checked_selection()
            self.assertEqual(window.checked_record_ids, set())
        finally:
            window.close()

    def test_tools_menu_is_grouped_by_workflow(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            top_level_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("進階搜尋", top_level_texts)
            self.assertIn("資料品質檢查", top_level_texts)
            self.assertIn("資料統計儀表板", top_level_texts)

            submenus = window.tool_submenus
            self.assertEqual(
                set(submenus),
                {
                    "搜尋與條件",
                    "單筆資料工具",
                    "勾選與批量操作",
                    "案件與分類管理",
                    "檢查與報表",
                    "危險操作",
                },
            )

            batch_actions = [action.text() for action in submenus["勾選與批量操作"].actions()]
            self.assertIn("勾選目前選取列", batch_actions)
            self.assertIn("取消全部勾選", batch_actions)
            self.assertIn("批次修改勾選資料", batch_actions)
            self.assertIn("從案件移除選取資料", batch_actions)
            self.assertIn("批量設定標籤", batch_actions)
            self.assertIn("批量設定自訂欄位", batch_actions)

            danger_actions = [action.text() for action in submenus["危險操作"].actions()]
            self.assertEqual(
                danger_actions,
                ["刪除已勾選資料", "刪除全部資料", "加密既有資料"],
            )

            management_keys = {
                "case_names",
                "tag_names",
                "attachment_count",
                "attachment_names",
                "custom_values",
                "last_contact",
                "next_follow_up",
                "follow_up_status",
            }
            self.assertTrue(management_keys.issubset(dict(app.TABLE_COLUMNS)))
            self.assertTrue(management_keys.issubset(dict(app.FILTERABLE_FIELDS)))
            self.assertTrue(management_keys.issubset(dict(app.ADVANCED_SEARCH_FIELDS)))
            self.assertTrue(management_keys.issubset(dict(window.get_export_columns())))

            context_actions = [action.text() for action in window.record_menu.actions()]
            self.assertIn("設定標籤", context_actions)
            self.assertIn("聯絡紀錄", context_actions)
            self.assertIn("設定追蹤提醒", context_actions)
            self.assertIn("附件管理", context_actions)
        finally:
            window.close()

    def test_management_summary_compacts_long_external_attachment_url(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            long_url = "https://www.google.com/maps/place/" + ("very-long-map-data/" * 100)
            window.update_management_summary(
                {"attachment_names": long_url, "attachment_count": 1}
            )

            summary = window.management_summary_label.text()
            self.assertEqual(summary, "附件：外部連結（www.google.com），共 1 個")
            self.assertNotIn("very-long-map-data", summary)
        finally:
            window.close()

    def test_primary_menus_have_unique_complete_action_inventory(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            data_actions = [action.text() for action in window.data_menu.actions() if action.text()]
            self.assertEqual(
                data_actions,
                [
                    "同地號批量新增",
                    "匯入 .xlsx",
                    "Excel 匯入設定檔",
                    "匯出 Excel",
                    "匯出選取資料",
                    "匯出選取 Word",
                    "報表與列印範本",
                    "傳送選取資料到手機",
                ],
            )

            settings_actions = [
                action.text() for action in window.settings_menu.actions() if action.text()
            ]
            self.assertEqual(len(settings_actions), len(set(settings_actions)))
            self.assertEqual(
                settings_actions,
                [
                    "注意名單管理",
                    "操作記錄",
                    "使用者與權限",
                    "字體大小",
                    "欄位顯示",
                    "唯讀模式",
                    "修改密碼",
                    "備份狀態",
                    "備份管理",
                    "異地完整備份",
                    "立即備份",
                    "還原備份",
                    "開啟備份資料夾",
                    "檢查納管附件",
                    "使用說明",
                    "關於系統",
                ],
            )
        finally:
            window.close()

    def test_selection_state_writes_are_debounced(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            record_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("D", "debounced-selection"),
            ).lastrowid

        window = app.LandApp(encryption_key)
        try:
            with patch.object(
                app.REPOSITORY,
                "set_settings",
                wraps=app.REPOSITORY.set_settings,
            ) as save_settings:
                window.on_checked_state_changed(record_id, True)
                window.load_record(record_id)
                window.on_checked_state_changed(record_id, False)
                window.on_checked_state_changed(record_id, True)
                self.assertEqual(save_settings.call_count, 0)

                loop = QEventLoop()
                QTimer.singleShot(app.SELECTION_SAVE_DELAY_MS + 150, loop.quit)
                loop.exec()
                self.assertEqual(save_settings.call_count, 1)
        finally:
            window.close()

    def test_table_layout_preferences_survive_window_reopen(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        address_column = next(
            index
            for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
            if key == "address"
        )

        first_window = app.LandApp(encryption_key)
        try:
            header = first_window.table_view.horizontalHeader()
            first_window.table_view.setColumnWidth(address_column, 333)
            first_window.table_view.setColumnHidden(address_column, True)
            header.moveSection(header.visualIndex(address_column), 1)
            first_window.save_table_preferences()
        finally:
            first_window.close()

        second_window = app.LandApp(encryption_key)
        try:
            header = second_window.table_view.horizontalHeader()
            self.assertTrue(second_window.table_view.isColumnHidden(address_column))
            self.assertEqual(header.visualIndex(address_column), 1)
            self.assertEqual(
                second_window.load_table_preferences()["widths"]["address"],
                333,
            )
        finally:
            second_window.close()

    def test_search_presets_survive_reopen_and_clear_cleanly(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        criteria = {
            "keyword": "桃園",
            "filter_field": "address",
            "sort_field": "land_number",
            "sort_order": "asc",
            "advanced": {"district": "桃園區"},
        }

        first_window = app.LandApp(encryption_key)
        try:
            first_window.apply_search_state(criteria)
            first_window.saved_searches = [
                {"name": "桃園案件", "criteria": criteria}
            ]
            first_window.persist_saved_searches()
        finally:
            first_window.close()

        second_window = app.LandApp(encryption_key)
        try:
            self.assertEqual(second_window.advanced_search_criteria, {"district": "桃園區"})
            self.assertEqual(second_window.saved_searches[0]["name"], "桃園案件")
            second_window.apply_search_state(criteria)
            self.assertEqual(second_window.get_current_search_state(), criteria)

            second_window.clear_search()
            state = second_window.get_current_search_state()
            self.assertEqual(state["keyword"], "")
            self.assertEqual(state["filter_field"], "all")
            self.assertEqual(state["sort_field"], "rowid")
            self.assertEqual(state["sort_order"], "desc")
            self.assertEqual(state["advanced"], {})
            self.assertEqual(app.get_setting(app.ADVANCED_SEARCH_SETTING_KEY), "")
        finally:
            second_window.close()

    def test_advanced_search_applies_multiple_conditions_without_old_quick_filter(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")

        class FakeAdvancedSearchDialog:
            def __init__(self, current_criteria, parent=None):
                self.current_criteria = dict(current_criteria)
                self.parent = parent

            def exec(self):
                return QDialog.Accepted

            def criteria(self):
                return {
                    "district": "中壢區",
                    "section": "中原段",
                    "land_number": "382-2",
                }

        window = app.LandApp(encryption_key)
        try:
            window.search_input.setText("舊的快速搜尋")
            window.filter_field_combo.setCurrentIndex(
                window.filter_field_combo.findData("owner_name")
            )
            with (
                patch("customer_search_presets.AdvancedSearchDialog", FakeAdvancedSearchDialog),
                patch.object(window, "refresh_records") as refresh,
            ):
                window.open_advanced_search()

            self.assertEqual(window.search_input.text(), "")
            self.assertEqual(window.get_filter_field(), "all")
            self.assertEqual(
                window.advanced_search_criteria,
                {
                    "district": "中壢區",
                    "section": "中原段",
                    "land_number": "382-2",
                },
            )
            self.assertIn("3 個進階條件", window.statusBar().currentMessage())
            refresh.assert_called_once_with()
        finally:
            window.close()

    def test_export_selection_merges_checked_rows_and_respects_visible_columns(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            first_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("D", "export-1"),
            ).lastrowid
            second_id = conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("D", "export-2"),
            ).lastrowid

        window = app.LandApp(encryption_key)
        try:
            window.checked_record_ids = {first_id}
            self.assertTrue(window.select_record_in_table(second_id))
            rows = window.selected_or_checked_rows()
            self.assertEqual({row["id"] for row in rows}, {first_id, second_id})
            self.assertEqual(len(rows), 2)

            note_column = next(
                index
                for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
                if key == "note"
            )
            address_column = next(
                index
                for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
                if key == "address"
            )
            window.table_view.setColumnHidden(note_column, True)
            header = window.table_view.horizontalHeader()
            header.moveSection(header.visualIndex(address_column), 1)
            export_keys = [key for key, _label in window.get_export_columns()]
            self.assertEqual(export_keys[0], "address")
            self.assertNotIn("note", export_keys)
            self.assertNotIn("checked", export_keys)
        finally:
            window.close()

    def test_manual_backup_updates_visible_backup_status(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            with patch.object(backup_status_module.QMessageBox, "information"):
                backup_path = window.backup_now()
            self.assertTrue(backup_path.is_file())
            self.assertTrue(window.backup_status.healthy)
            self.assertIn("備份正常", window.backup_status_button.text())
        finally:
            window.close()

    def test_manual_backup_still_succeeds_when_followup_maintenance_fails(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(
                    window.database,
                    "run_backup_maintenance",
                    side_effect=OSError("maintenance busy"),
                ),
                patch.object(backup_status_module.QMessageBox, "information") as information,
            ):
                backup_path = window.backup_now()
            self.assertTrue(backup_path.is_file())
            self.assertIn("maintenance busy", information.call_args.args[2])
        finally:
            window.close()

    def test_backup_management_saves_policy_and_runs_maintenance(self):
        class FakeBackupManagementDialog:
            requested_action = "save"

            def __init__(self, *, compress_backups, retention_days, max_count, parent=None):
                self.initial_policy = (compress_backups, retention_days, max_count)
                self.parent = parent

            def exec(self):
                return QDialog.Accepted

            def selected_policy(self):
                return {
                    "compress_backups": False,
                    "retention_days": 45,
                    "max_count": 12,
                }

        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(app, "BackupManagementDialog", FakeBackupManagementDialog),
                patch.object(app.QMessageBox, "information"),
            ):
                result = window.manage_backups()

            self.assertIsNotNone(result)
            self.assertFalse(app.DATABASE.compress_backups)
            self.assertEqual(app.DATABASE.backup_retention_days, 45)
            self.assertEqual(app.DATABASE.backup_max_count, 12)
            self.assertEqual(app.get_setting(app.BACKUP_COMPRESSION_SETTING_KEY), "0")
            self.assertEqual(app.get_setting(app.BACKUP_RETENTION_DAYS_SETTING_KEY), "45")
            self.assertEqual(app.get_setting(app.BACKUP_MAX_COUNT_SETTING_KEY), "12")
        finally:
            window.close()

    def test_backup_management_real_dialog_accepts_saved_policy(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            action = next(
                action
                for action in window.settings_menu.actions()
                if action.text() == "備份管理"
            )
            with patch.object(
                app.BackupManagementDialog,
                "exec",
                return_value=QDialog.Rejected,
            ) as execute_dialog:
                action.trigger()
            execute_dialog.assert_called_once()
        finally:
            window.close()

    def test_backup_management_failure_is_visible_and_keeps_running(self):
        class FakeBackupManagementDialog:
            requested_action = "save"

            def __init__(self, **_kwargs):
                pass

            def exec(self):
                return QDialog.Accepted

            def selected_policy(self):
                return {"compress_backups": True, "retention_days": 90, "max_count": 30}

        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(app, "BackupManagementDialog", FakeBackupManagementDialog),
                patch.object(app, "save_backup_policy", side_effect=OSError("disk full")),
                patch.object(app.QMessageBox, "critical") as critical,
            ):
                result = window.manage_backups()
            self.assertIsNone(result)
            self.assertIn("disk full", critical.call_args.args[2])
        finally:
            window.close()

    def test_health_check_recognizes_zip_backup_and_error_log_state(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            backup_path = window.database.backup_database("health")
            checks = {check["title"]: check for check in window.build_health_checks()}
            self.assertEqual(backup_path.suffix, ".zip")
            self.assertEqual(checks["備份"]["status"], "OK")
            self.assertIn(".zip", checks["備份"]["detail"])
            self.assertEqual(checks["系統錯誤記錄"]["status"], "OK")
        finally:
            window.close()

    def test_health_check_reports_one_failed_category_without_closing(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        window = app.LandApp(encryption_key)
        try:
            with patch.object(
                window.repository,
                "count_customers",
                side_effect=OSError("count unavailable"),
            ):
                checks = {check["title"]: check for check in window.build_health_checks()}
            self.assertEqual(checks["資料量"]["status"], "錯誤")
            self.assertIn("count unavailable", checks["資料量"]["detail"])
            self.assertIn("SQLite 完整性", checks)
            self.assertIn("備份", checks)
            self.assertIn("系統錯誤記錄", checks)
        finally:
            window.close()

    def test_data_quality_check_reports_database_issues(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            record_id = conn.execute(
                """
                INSERT INTO customers (district, section, land_number, owner_name, denominator)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("桃園市", "一段", "", "", "0"),
            ).lastrowid

        captured = {}

        class FakeDataQualityRulesDialog:
            def __init__(self, selected_rules, parent=None):
                captured["selected_rules_before"] = list(selected_rules)
                captured["rules_parent"] = parent

            def exec(self):
                return QDialog.Accepted

            def selected_rules(self):
                return ["land_number_missing", "denominator_zero"]

        class FakeDataQualityDialog:
            def __init__(
                self,
                issues,
                total_records,
                parent=None,
                on_issue_activated=None,
                on_issue_ignored=None,
                ignored_count=0,
                on_clear_ignored=None,
            ):
                captured["issues"] = list(issues)
                captured["total_records"] = total_records
                captured["parent"] = parent
                captured["on_issue_activated"] = on_issue_activated
                captured["on_issue_ignored"] = on_issue_ignored
                captured["ignored_count"] = ignored_count
                captured["on_clear_ignored"] = on_clear_ignored

            def exec(self):
                captured["on_issue_ignored"](captured["issues"][0])
                captured["on_issue_activated"](captured["issues"][0].record_id)
                return QDialog.Accepted

        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(app, "DataQualityRulesDialog", FakeDataQualityRulesDialog),
                patch.object(app, "DataQualityDialog", FakeDataQualityDialog),
            ):
                window.run_data_quality_check()

            self.assertEqual(captured["total_records"], 1)
            categories = {issue.category for issue in captured["issues"]}
            self.assertIn("地號缺漏", categories)
            self.assertIn("分母為 0", categories)
            self.assertNotIn("姓名空白", categories)
            self.assertIs(captured["rules_parent"], window)
            self.assertIs(captured["parent"], window)
            self.assertEqual(captured["ignored_count"], 0)
            self.assertEqual(window.selected_record_id, record_id)
            self.assertEqual(window.get_field_text("denominator"), "0")
            saved_signatures = app.load_ignored_quality_issue_signatures()
            self.assertIn(app.quality_issue_signature(captured["issues"][0]), saved_signatures)
            self.assertEqual(app.load_quality_rule_keys(), ["land_number_missing", "denominator_zero"])
        finally:
            window.close()

    def test_ten_thousand_records_start_and_search_within_limits(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        records = [
            ("D", "oldest-performance-target" if number == 0 else f"land-{number}")
            for number in range(10000)
        ]
        with app.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                records,
            )

        started = time.perf_counter()
        window = app.LandApp(encryption_key)
        startup_elapsed = time.perf_counter() - started
        try:
            self.assertLess(startup_elapsed, 5.0)
            self.assertEqual(window.table_model.total_count, 10000)
            self.assertEqual(window.table_model.rowCount(), app.TABLE_BATCH_SIZE)

            started = time.perf_counter()
            window.search_input.setText("oldest-performance-target")
            window.refresh_records()
            self.wait_for_record_searches(window)
            search_elapsed = time.perf_counter() - started
            self.assertLess(search_elapsed, 10.0)
            self.assertEqual(len(window.table_model.all_rows), 1)
            self.assertEqual(
                window.table_model.all_rows[0]["raw"]["land_number"],
                "oldest-performance-target",
            )
        finally:
            window.close()

    def test_background_search_failure_is_reported_and_cleaned_up(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        with app.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                [("D", str(number)) for number in range(app.ASYNC_SEARCH_THRESHOLD + 1)],
            )

        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(
                    app.REPOSITORY,
                    "fetch_search_candidate_rows",
                    side_effect=RuntimeError("simulated database failure"),
                ),
                patch.object(app.QMessageBox, "critical", return_value=QMessageBox.Ok) as critical,
            ):
                window.search_input.setText("anything")
                window.refresh_records()
                self.wait_for_record_searches(window)
                critical.assert_called_once()
                self.assertIn("simulated database failure", critical.call_args.args[2])
        finally:
            window.close()

    def test_batch_add_shared_land_records(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")

        class FakeBatchDialog:
            def __init__(self, _initial_values, _parent):
                pass

            def exec(self):
                return QDialog.Accepted

            def values(self):
                return (
                    {
                        "district": "中正區",
                        "section": "一段",
                        "land_number": "100",
                        "area": "100",
                        "declared_value": "20,000",
                    },
                    "1\t王小明\tA123456789\t台北市\t1\t2\t重要\t已拜訪\n"
                    "2\t陳小華\tB123456789\t新北市\t1\t3",
                )

        class FakePreviewDialog:
            import_mode = "all"
            columns = None

            def __init__(self, records, columns, _duplicates, _parent):
                self.records = records
                FakePreviewDialog.columns = columns

            def exec(self):
                return QDialog.Accepted

        window = app.LandApp(encryption_key)
        try:
            with (
                patch.object(import_controller, "SharedLandBatchDialog", FakeBatchDialog),
                patch.object(import_controller, "ImportPreviewDialog", FakePreviewDialog),
                patch.object(app.QMessageBox, "information", return_value=QMessageBox.Ok),
                patch.object(app.QMessageBox, "question", return_value=QMessageBox.Yes),
            ):
                window.batch_add_shared_land_records()

            with app.connect() as conn:
                rows = conn.execute(
                    "SELECT district, section, registration_order, land_number, owner_name, external_id, "
                    "address, area, declared_value, numerator, denominator, ping, "
                    "total_declared_value, note, visit_log "
                    "FROM customers ORDER BY id"
                ).fetchall()
                actions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT action_type FROM operation_logs ORDER BY id"
                    )
                ]
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {(row["district"], row["section"], row["land_number"]) for row in rows},
                {("中正區", "一段", "100")},
            )
            self.assertEqual(
                [decrypt_value(window.fernet, row["owner_name"]) for row in rows],
                ["王小明", "陳小華"],
            )
            self.assertEqual(
                [key for key, _label in FakePreviewDialog.columns[:8]],
                [
                    "registration_order",
                    "owner_name",
                    "external_id",
                    "address",
                    "numerator",
                    "denominator",
                    "note",
                    "visit_log",
                ],
            )
            self.assertEqual(
                [row["registration_order"] for row in rows],
                ["1", "2"],
            )
            self.assertEqual(
                [key for key, _label in FakePreviewDialog.columns[-5:]],
                ["district", "section", "land_number", "area", "declared_value"],
            )
            self.assertEqual(decrypt_value(window.fernet, rows[0]["external_id"]), "A123456789")
            self.assertEqual(decrypt_value(window.fernet, rows[0]["address"]), "台北市")
            self.assertEqual((rows[0]["area"], rows[0]["declared_value"]), ("100", "20,000"))
            self.assertEqual((rows[0]["numerator"], rows[0]["denominator"]), ("1", "2"))
            self.assertEqual((rows[0]["ping"], rows[0]["total_declared_value"]), ("15.12", "1,000,000"))
            self.assertEqual(decrypt_value(window.fernet, rows[0]["note"]), "重要")
            self.assertEqual(decrypt_value(window.fernet, rows[0]["visit_log"]), "已拜訪")
            self.assertEqual(actions, ["批量新增"])
        finally:
            window.close()

    def test_postgresql_api_mode_enables_remote_safe_tools_only(self):
        app.REPOSITORY.create_admin_user("test-password")
        encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")

        class PreviewRepository:
            data_revision = 0

            def __init__(self):
                self.rows = []

            def count_customers(self):
                return len(self.rows)

            def fetch_customer_page(self, limit, before_id=None):
                del limit, before_id
                return list(self.rows)

            def fetch_search_candidate_rows(self, **_criteria):
                return list(self.rows)

            def get_customer(self, record_id):
                return next(
                    (row for row in self.rows if row["id"] == int(record_id)), None
                )

        preview_repository = PreviewRepository()
        window = app.LandApp(
            encryption_key,
            record_repository=preview_repository,
            api_mode=True,
        )
        try:
            self.assertIs(window.record_repository, preview_repository)
            self.assertIn("PostgreSQL 正式版", window.windowTitle())
            self.assertTrue(window.data_button.isEnabled())
            self.assertTrue(window.tools_button.isEnabled())
            self.assertTrue(window.settings_button.isEnabled())
            self.assertEqual(
                [action.text() for action in window.api_preview_supported_data_actions],
                [
                    "同地號批量新增",
                    "匯入 .xlsx",
                    "Excel 匯入設定檔",
                    "匯出 Excel",
                    "匯出選取資料",
                    "匯出選取 Word",
                    "報表與列印範本",
                    "傳送選取資料到手機",
                ],
            )
            self.assertTrue(
                all(
                    action.isEnabled()
                    for action in window.api_preview_supported_data_actions
                )
            )
            self.assertTrue(
                all(
                    not action.isEnabled()
                    for action in window.api_preview_unavailable_data_actions
                )
            )
            self.assertTrue(
                all(
                    action.isEnabled()
                    for action in window.api_preview_supported_context_actions
                )
            )
            supported_labels = {
                action.text() for action in window.api_preview_supported_context_actions
            }
            self.assertIn("案件管理", supported_labels)
            self.assertIn("加入選取／勾選資料到案件", supported_labels)
            self.assertIn("從案件移除選取／勾選資料", supported_labels)
            self.assertTrue(
                all(
                    not action.isEnabled()
                    for action in window.api_preview_unavailable_context_actions
                )
            )
            supported_tool_labels = {
                action.text() for action in window.api_supported_tool_actions
            }
            self.assertIn("進階搜尋", supported_tool_labels)
            self.assertIn("資料統計儀表板", supported_tool_labels)
            self.assertIn("系統健康檢查", supported_tool_labels)
            self.assertIn("查看修改歷史", supported_tool_labels)
            self.assertIn("批次修改勾選資料", supported_tool_labels)
            self.assertIn("自訂欄位管理", supported_tool_labels)
            self.assertIn("智慧重複資料檢查", supported_tool_labels)
            self.assertIn("地圖與地號視覺化", supported_tool_labels)
            self.assertIn("刪除已勾選資料", supported_tool_labels)
            self.assertIn("通知中心", supported_tool_labels)
            self.assertIn("案件工作流程與任務看板", supported_tool_labels)
            self.assertIn("回收桶", supported_tool_labels)
            self.assertIn("復原批次操作", supported_tool_labels)
            self.assertIn("合併勾選兩筆資料", supported_tool_labels)
            self.assertIn("加密既有資料", supported_tool_labels)
            self.assertTrue(
                all(action.isEnabled() for action in window.api_supported_tool_actions)
            )
            self.assertTrue(
                all(not action.isEnabled() for action in window.api_unavailable_tool_actions)
            )
            supported_setting_labels = {
                action.text() for action in window.api_supported_settings_actions
            }
            self.assertEqual(
                supported_setting_labels,
                {
                    "伺服器連線設定",
                    "注意名單管理",
                    "操作記錄",
                    "使用者與權限",
                    "字體大小",
                    "欄位顯示",
                    "唯讀模式",
                    "修改密碼",
                    "備份狀態",
                    "備份管理",
                    "立即備份",
                    "開啟備份資料夾",
                    "異地完整備份",
                    "還原備份",
                    "檢查納管附件",
                    "使用說明",
                    "關於系統",
                },
            )
            self.assertTrue(
                all(action.isEnabled() for action in window.api_supported_settings_actions)
            )
            self.assertTrue(
                all(
                    not action.isEnabled()
                    for action in window.api_unavailable_settings_actions
                )
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
