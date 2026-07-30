import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from customer_database import CustomerDatabase
from customer_repository import CustomerRepository
from customer_security import decrypt_value, encrypt_record, make_fernet


class CustomerRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.database = CustomerDatabase(
            self.root / "customers.db",
            self.root / "backups",
        )
        project_root = Path(__file__).resolve().parents[1]
        self.repository = CustomerRepository(
            self.database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            [
                ("district", ""),
                ("land_number", ""),
                ("owner_name", ""),
                ("external_id", ""),
                ("address", ""),
                ("note", ""),
                ("visit_log", ""),
            ],
        )
        self.repository.init_db()

    def tearDown(self):
        self.temp_context.cleanup()

    def test_settings_logs_and_watchlist(self):
        self.repository.set_setting("font_size", "large")
        self.repository.log_operation("test", "saved", "detail")
        self.repository.replace_watchlist_entries(
            [
                {"name": " 王 小明 ", "note": "first"},
                {"name": "王小明", "note": "duplicate"},
            ]
        )

        self.assertEqual(self.repository.get_setting("font_size"), "large")
        self.assertEqual(self.repository.get_operation_logs(1)[0]["summary"], "saved")
        self.assertEqual(len(self.repository.get_watchlist_entries()), 1)
        self.assertEqual(self.repository.find_watchlist_match("王小明")["note"], "first")

    def test_change_logs_and_follow_up_reminders(self):
        record_id = self.repository.save_customer(
            {
                "district": "桃園區",
                "land_number": "100",
                "owner_name": "王小明",
                "external_id": "A1",
                "address": "地址",
                "note": None,
                "visit_log": None,
                "name": "王小明",
            }
        )

        self.assertEqual(
            self.repository.add_record_change_logs(
                [
                    {
                        "customer_id": record_id,
                        "action_type": "修改資料",
                        "field_key": "land_number",
                        "field_label": "地號",
                        "old_value": "100",
                        "new_value": "101",
                    }
                ]
            ),
            1,
        )
        logs = self.repository.get_record_change_logs(record_id)
        self.assertEqual(logs[0]["field_label"], "地號")
        self.assertEqual(logs[0]["new_value"], "101")

        self.repository.save_follow_up_reminder(record_id, "2026-07-20", "待回覆", "再聯絡")
        reminder = self.repository.get_follow_up_reminder(record_id)
        self.assertEqual(reminder["status"], "待回覆")
        self.assertEqual(self.repository.list_follow_up_reminders()[0]["customer_id"], record_id)
        self.assertEqual(self.repository.delete_follow_up_reminder(record_id), 1)
        self.assertIsNone(self.repository.get_follow_up_reminder(record_id))

    def test_management_tables_and_merge_helpers(self):
        first_id = self.repository.save_customer(
            {
                "district": "D",
                "land_number": "100",
                "owner_name": "Owner 1",
                "external_id": "",
                "address": "",
                "note": "primary",
                "visit_log": "",
                "name": "Owner 1",
            }
        )
        second_id = self.repository.save_customer(
            {
                "district": "D",
                "land_number": "100",
                "owner_name": "Owner 2",
                "external_id": "A2",
                "address": "Address 2",
                "note": "secondary",
                "visit_log": "visit",
                "name": "Owner 2",
            }
        )

        case_id = self.repository.save_case("Case A", "進行中", "note")
        self.assertEqual(self.repository.add_customers_to_case(case_id, [first_id, second_id]), 2)
        self.assertEqual(self.repository.list_cases()[0]["customer_count"], 2)

        tag_id = self.repository.save_tag("Important", "#ffcc00")
        self.assertEqual(self.repository.set_customer_tags(second_id, [tag_id]), 1)
        self.assertEqual(self.repository.get_customer_tag_ids(second_id), {tag_id})

        attachment_id = self.repository.add_customer_attachment(second_id, "C:/tmp/a.pdf", "contract")
        self.assertEqual(
            self.repository.list_customer_attachments(second_id)[0]["id"],
            attachment_id,
        )

        field_id = self.repository.save_custom_field("Extra Field", "extra_field")
        self.assertEqual(
            self.repository.set_customer_custom_values(second_id, {field_id: "custom value"}),
            1,
        )
        self.assertEqual(
            self.repository.get_customer_custom_values(second_id)[field_id],
            "custom value",
        )

        template_id = self.repository.save_text_template("Visit", "Call again", "visit_log")
        self.assertEqual(self.repository.list_text_templates()[0]["id"], template_id)

        contact_id = self.repository.add_contact_log(
            second_id,
            "2026-07-13",
            "phone",
            "ok",
            "2026-07-20",
            "note",
        )
        self.assertEqual(self.repository.list_contact_logs(second_id)[0]["id"], contact_id)
        self.repository.save_follow_up_reminder(second_id, "2026-07-20", "待回覆", "reminder")

        merged = {
            "district": "D",
            "land_number": "100",
            "owner_name": "Owner 1",
            "external_id": "A2",
            "address": "Address 2",
            "note": "primary\nsecondary",
            "visit_log": "visit",
            "name": "Owner 1",
        }
        self.repository.merge_customers(first_id, second_id, merged)

        self.assertIsNone(self.repository.get_customer(second_id))
        self.assertEqual(self.repository.get_customer(first_id)["external_id"], "A2")
        self.assertEqual(self.repository.get_customer_tag_ids(first_id), {tag_id})
        self.assertEqual(len(self.repository.list_customer_attachments(first_id)), 1)
        self.assertEqual(len(self.repository.list_contact_logs(first_id)), 1)
        self.assertEqual(self.repository.get_follow_up_reminder(first_id)["due_date"], "2026-07-20")
        self.assertEqual(self.repository.get_customer_custom_values(first_id)[field_id], "custom value")
        self.assertEqual(len(self.repository.list_case_members(case_id)), 1)

    def test_management_metadata_and_batch_updates_are_connected(self):
        first_id = self.repository.save_customer(
            {
                "district": "D",
                "land_number": "100",
                "owner_name": "Owner 1",
                "external_id": "",
                "address": "",
                "note": "",
                "visit_log": "",
                "name": "Owner 1",
            }
        )
        second_id = self.repository.save_customer(
            {
                "district": "D",
                "land_number": "101",
                "owner_name": "Owner 2",
                "external_id": "",
                "address": "",
                "note": "",
                "visit_log": "",
                "name": "Owner 2",
            }
        )
        case_id = self.repository.save_case("Priority Case")
        self.repository.add_customers_to_case(case_id, [first_id, second_id])
        urgent_id = self.repository.save_tag("Urgent", "#ff0000")
        visited_id = self.repository.save_tag("Visited", "#00ff00")
        self.assertEqual(
            self.repository.set_customers_tags(
                [first_id, second_id],
                [urgent_id],
                "add",
            ),
            2,
        )
        field_id = self.repository.save_custom_field("Channel", "channel")
        self.assertEqual(
            self.repository.set_customers_custom_values(
                [first_id, second_id],
                {field_id: "phone"},
            ),
            2,
        )
        self.repository.add_customer_attachment(first_id, "C:/tmp/a.pdf", "contract")
        self.repository.add_contact_log(
            first_id,
            "2026-07-13",
            "phone",
            "answered",
            "2026-07-20",
            "note",
        )
        self.repository.save_follow_up_reminder(first_id, "2026-07-20", "待回覆", "note")

        row = self.repository.get_customer(first_id)
        self.assertEqual(row["case_names"], "Priority Case")
        self.assertEqual(row["tag_names"], "Urgent")
        self.assertEqual(row["primary_tag_color"], "#ff0000")
        self.assertEqual(
            json.loads(row["tag_items"]),
            [{"tag_id": urgent_id, "name": "Urgent", "color": "#ff0000"}],
        )
        self.assertEqual(row["attachment_count"], 1)
        self.assertIn("contract", row["attachment_names"])
        self.assertEqual(row["custom_values"], "Channel：phone")
        self.assertIn("phone", row["last_contact"])
        self.assertEqual(row["next_follow_up"], "2026-07-20")
        self.assertEqual(row["follow_up_status"], "待回覆")

        self.repository.set_customers_tags([first_id], [visited_id], "replace")
        self.assertEqual(self.repository.get_customer_tag_ids(first_id), {visited_id})
        self.repository.set_customers_tags([first_id], [visited_id], "remove")
        self.assertEqual(self.repository.get_customer_tag_ids(first_id), set())
        self.assertEqual(
            self.repository.remove_customers_from_case(case_id, [second_id]),
            1,
        )
        self.assertEqual(len(self.repository.list_case_members(case_id)), 1)
        self.repository.set_customers_custom_values([first_id], {field_id: ""})
        self.assertEqual(self.repository.get_customer_custom_values(first_id), {})

    def test_password_change_rotates_encrypted_customer_fields(self):
        self.repository.create_admin_user("old-password")
        old_key = self.repository.authenticate_user("admin", "old-password")
        old_fernet = make_fernet(old_key)
        encrypted = encrypt_record(
            old_fernet,
            {
                "owner_name": "王小明",
                "external_id": "A123456789",
                "address": "台北市",
                "note": "private",
                "visit_log": "visit",
                "name": "王小明",
            },
        )
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO customers
                    (district, section, land_number, owner_name, external_id,
                     address, note, visit_log, name)
                VALUES ('D', 'S', '1', :owner_name, :external_id,
                        :address, :note, :visit_log, :name)
                """,
                encrypted,
            )

        new_key, backup_path = self.repository.change_admin_password(
            "old-password", "new-password"
        )

        self.assertTrue(backup_path.is_file())
        self.assertIsNone(self.repository.authenticate_user("admin", "old-password"))
        self.assertEqual(self.repository.authenticate_user("admin", "new-password"), new_key)
        with self.database.connect() as conn:
            owner_name = conn.execute("SELECT owner_name FROM customers").fetchone()[0]
        self.assertEqual(decrypt_value(make_fernet(new_key), owner_name), "王小明")


    def test_customer_count_and_pages_are_newest_first(self):
        with self.database.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                [("D", str(number)) for number in range(5)],
            )

        self.assertEqual(self.repository.count_customers(), 5)
        first_page = self.repository.fetch_customer_page(2)
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO customers (district, land_number) VALUES (?, ?)",
                ("D", "new-after-first-page"),
            )
        second_page = self.repository.fetch_customer_page(
            2,
            before_id=first_page[-1]["id"],
        )
        all_rows = self.repository.fetch_all_customer_rows()
        self.assertEqual([row["land_number"] for row in first_page], ["4", "3"])
        self.assertEqual([row["land_number"] for row in second_page], ["2", "1"])
        self.assertEqual(
            [row["land_number"] for row in all_rows],
            ["new-after-first-page", "4", "3", "2", "1", "0"],
        )

    def test_multiple_settings_are_saved_together(self):
        self.repository.set_settings({"checked_record_ids": "[1, 2]", "selected_record_id": "2"})

        self.assertEqual(self.repository.get_setting("checked_record_ids"), "[1, 2]")
        self.assertEqual(self.repository.get_setting("selected_record_id"), "2")

    def test_customer_crud_and_bulk_operations(self):
        starting_revision = self.repository.data_revision
        first = {
            "district": "D1",
            "land_number": "100",
            "owner_name": "Owner 1",
            "external_id": "A1",
            "address": "Address 1",
            "note": None,
            "visit_log": None,
            "name": "Owner 1",
        }
        first_id = self.repository.save_customer(first)
        self.assertGreater(self.repository.data_revision, starting_revision)
        self.assertEqual(self.repository.get_customer(first_id)["land_number"], "100")

        first["land_number"] = "101"
        self.assertEqual(self.repository.save_customer(first, first_id), first_id)
        self.assertEqual(self.repository.get_customer(first_id)["land_number"], "101")

        second = {**first, "district": "D2", "land_number": "200", "name": "Owner 2"}
        self.assertEqual(self.repository.insert_customers([second]), 1)
        second_id = max(self.repository.fetch_customer_ids())
        rows = self.repository.fetch_customers_by_ids([first_id, second_id])
        self.assertEqual([row["land_number"] for row in rows], ["101", "200"])
        self.assertEqual(len(self.repository.fetch_duplicate_candidates()), 2)

        updates = []
        for row in rows:
            values = {key: row[key] for key in self.repository.customer_data_columns}
            values.update({"id": row["id"], "note": "updated"})
            updates.append(values)
        self.assertEqual(self.repository.update_customers(updates), 2)
        self.assertEqual(self.repository.get_customer(first_id)["note"], "updated")

        self.assertEqual(self.repository.delete_customers([first_id]), 1)
        self.assertIsNone(self.repository.get_customer(first_id))
        self.assertEqual(self.repository.delete_all_customers(), 1)
        self.assertEqual(self.repository.count_customers(), 0)

    def test_non_sensitive_search_conditions_reduce_database_candidates(self):
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO customers
                    (district, section, land_number, owner_name, registration_reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("桃 園區", "一段", "100", "encrypted-owner-1", "買賣"),
                    ("中壢區", "二段", "200", "encrypted-owner-2", "贈與"),
                    ("桃園區", "三段", "300", "encrypted-owner-3", "繼承"),
                ],
            )

        keyword_rows = self.repository.fetch_search_candidate_rows(
            keyword="桃園",
            filter_field="district",
        )
        self.assertEqual([row["land_number"] for row in keyword_rows], ["300"])

        advanced_rows = self.repository.fetch_search_candidate_rows(
            advanced_criteria={"district": "桃園區", "section": "一段、三段"},
        )
        self.assertEqual(
            {row["land_number"] for row in advanced_rows},
            {"100", "300"},
        )

        sensitive_rows = self.repository.fetch_search_candidate_rows(
            keyword="owner",
            filter_field="owner_name",
        )
        self.assertEqual(len(sensitive_rows), 3)


if __name__ == "__main__":
    unittest.main()
