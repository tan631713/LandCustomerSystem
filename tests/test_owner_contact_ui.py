import os
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from customer_owner_contacts import (
    DeactivateRelationDialog,
    OwnerContactsWidget,
    address_choices,
    phone_choices,
)


class _Repository:
    def __init__(self):
        self.calls = []
        self.fail_list = False
        self.rows = [
            {
                "relation_id": 1,
                "owner_id": 2,
                "contact_id": 3,
                "name": "王小明",
                "relationship_type": "兒子",
                "relationship_note": "長子",
                "mobile_phone": "0912",
                "home_phone": "",
                "registered_address": "桃園市",
                "contact_address": "台中市",
                "work_address": "台中五金行",
                "identity_note": "長子",
                "is_primary": True,
                "sort_order": 10,
                "contact_notes": "",
                "relation_notes": "優先聯絡",
                "is_active": True,
                "owner_count": 1,
            },
            {
                "relation_id": 2,
                "owner_id": 2,
                "contact_id": 4,
                "name": "王小華",
                "relationship_type": "女兒",
                "relationship_note": "",
                "mobile_phone": "0922",
                "home_phone": "",
                "registered_address": "",
                "contact_address": "",
                "work_address": "",
                "identity_note": "",
                "is_primary": False,
                "sort_order": 20,
                "contact_notes": "",
                "relation_notes": "",
                "is_active": False,
                "owner_count": 1,
            },
        ]

    def list_owner_contacts(self, record_id, include_inactive=False):
        self.calls.append(("list", record_id, include_inactive))
        if self.fail_list:
            raise RuntimeError("測試連線錯誤")
        return [
            dict(row)
            for row in self.rows
            if include_inactive or row["is_active"]
        ]

    def get_owner_contact(self, record_id, relation_id):
        self.calls.append(("get", record_id, relation_id))
        return next(
            dict(row) for row in self.rows if row["relation_id"] == relation_id
        )

    def search_owner_contacts(self, query, limit=50):
        self.calls.append(("search", query, limit))
        return []

    def find_owner_contact_duplicates(self, **values):
        self.calls.append(("duplicates", values))
        return []

    def create_owner_contact(self, record_id, values):
        self.calls.append(("create", record_id, values))
        self.rows.append(
            {
                "relation_id": 3,
                "owner_id": 2,
                "contact_id": 5,
                "name": values["contact"]["name"],
                "relationship_type": values["relation"]["relationship_type"],
                "relationship_note": "",
                "mobile_phone": "",
                "home_phone": "",
                "registered_address": "",
                "contact_address": "",
                "work_address": "",
                "identity_note": "",
                "is_primary": False,
                "sort_order": values["relation"]["sort_order"],
                "contact_notes": "",
                "relation_notes": "",
                "is_active": True,
                "owner_count": 1,
            }
        )

    def link_owner_contact(self, record_id, values):
        self.calls.append(("link", record_id, values))

    def update_owner_contact(self, record_id, relation_id, values):
        self.calls.append(("update", record_id, relation_id, values))
        row = next(row for row in self.rows if row["relation_id"] == relation_id)
        row["name"] = values["contact"]["name"]

    def deactivate_owner_contact(self, record_id, relation_id, **values):
        self.calls.append(("deactivate", record_id, relation_id, values))
        row = next(row for row in self.rows if row["relation_id"] == relation_id)
        row["is_active"] = False
        row["is_primary"] = False

    def reactivate_owner_contact(self, record_id, relation_id, **values):
        self.calls.append(("reactivate", record_id, relation_id, values))
        row = next(row for row in self.rows if row["relation_id"] == relation_id)
        row["is_active"] = True
        row["is_primary"] = False


class _AcceptedDialog:
    payload = {
        "mode": "new",
        "contact": {
            "name": "李小美",
            "mobile_phone": "",
            "home_phone": "",
            "registered_address": "",
            "contact_address": "",
            "work_address": "",
            "identity_note": "",
            "notes": "",
        },
        "relation": {
            "relationship_type": "女兒",
            "relationship_note": "",
            "is_primary": False,
            "sort_order": 30,
            "notes": "",
        },
    }

    def __init__(self, *_args, **_kwargs):
        pass

    def exec(self):
        return QDialog.Accepted

    def result_values(self):
        return dict(self.payload)


class _DetailDialog:
    instances = []

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs
        self.edit_requested = False
        self.instances.append(self)

    def exec(self):
        return QDialog.Rejected


class OwnerContactUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.repository = _Repository()

    def test_switch_owner_loads_rows_and_clear_disables_actions(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")
        self.assertEqual(widget.table.rowCount(), 1)
        self.assertEqual(self.repository.calls[-1], ("list", 7, False))
        self.assertTrue(widget.add_button.isEnabled())

        widget.clear_owner()
        self.assertEqual(widget.table.rowCount(), 0)
        self.assertFalse(widget.add_button.isEnabled())
        self.assertFalse(widget.refresh_button.isEnabled())

    def test_viewer_can_view_but_write_buttons_are_disabled(self):
        widget = OwnerContactsWidget(self.repository, current_role="viewer")
        widget.set_record(7, "地主甲")
        widget.table.selectRow(0)
        self.assertFalse(widget.add_button.isEnabled())
        self.assertTrue(widget.edit_button.isEnabled())
        self.assertEqual(widget.edit_button.text(), "查看")
        self.assertFalse(widget.deactivate_button.isEnabled())
        self.assertFalse(widget.reactivate_button.isEnabled())

    def test_show_inactive_and_reactivate(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")
        widget.show_inactive.setChecked(True)
        self.assertEqual(widget.table.rowCount(), 2)
        widget.table.selectRow(1)
        self.assertTrue(widget.reactivate_button.isEnabled())
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ):
            widget.reactivate_selected()
        self.assertTrue(
            any(
                call[:3] == ("reactivate", 7, 2)
                for call in self.repository.calls
            )
        )
        self.assertTrue(self.repository.rows[1]["is_active"])
        self.assertFalse(self.repository.rows[1]["is_primary"])

    def test_add_edit_and_deactivate_refresh_table(self):
        widget = OwnerContactsWidget(
            self.repository,
            current_role="editor",
            dialog_factory=_AcceptedDialog,
        )
        widget.set_record(7, "地主甲")
        widget.add_contact()
        self.assertTrue(any(call[0] == "create" for call in self.repository.calls))
        self.assertEqual(widget.table.rowCount(), 2)

        _AcceptedDialog.payload = {
            "mode": "edit",
            "contact": {
                "name": "王大明",
                "mobile_phone": "0912",
                "home_phone": "",
                "registered_address": "桃園市",
                "contact_address": "台中市",
                "work_address": "",
                "identity_note": "長子",
                "notes": "",
            },
            "relation": {
                "relationship_type": "兒子",
                "relationship_note": "",
                "is_primary": False,
                "sort_order": 10,
                "notes": "",
            },
        }
        widget.table.selectRow(0)
        widget.edit_selected()
        self.assertTrue(any(call[0] == "update" for call in self.repository.calls))
        self.assertEqual(self.repository.rows[0]["name"], "王大明")

        widget.table.selectRow(0)
        with patch.object(
            DeactivateRelationDialog,
            "exec",
            return_value=QDialog.Accepted,
        ):
            widget.deactivate_selected()
        self.assertTrue(
            any(call[0] == "deactivate" for call in self.repository.calls)
        )
        self.assertEqual(widget.table.rowCount(), 1)

    def test_repository_failure_is_shown_without_crashing(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        self.repository.fail_list = True
        widget.set_record(7, "地主甲")
        self.assertEqual(widget.table.rowCount(), 0)
        self.assertIn("載入失敗", widget.status_label.text())

    def test_windows_contact_ui_has_no_database_or_server_service_imports(self):
        root = Path(__file__).resolve().parents[1]
        ui_source = (root / "customer_owner_contacts.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(ui_source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertFalse(any(name.startswith("psycopg") for name in imports))
        self.assertFalse(any(name.startswith("customer_api") for name in imports))
        for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM "):
            self.assertNotIn(keyword, ui_source)

        desktop_api_source = (root / "customer_desktop_api.py").read_text(
            encoding="utf-8"
        )
        desktop_tree = ast.parse(desktop_api_source)
        desktop_imports = {
            alias.name
            for node in ast.walk(desktop_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            any(name.startswith("psycopg") for name in desktop_imports)
        )

    def test_empty_state_tooltips_and_owner_switch_do_not_leak_rows(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")
        self.assertEqual(widget.table.item(0, 5).toolTip(), "桃園市")
        self.assertEqual(widget.table.item(0, 6).toolTip(), "台中市")
        self.repository.rows = []
        widget.set_record(8, "地主乙")
        self.assertEqual(widget.table.rowCount(), 0)
        self.assertEqual(widget.status_label.text(), "目前尚未建立關係人資料。")

    def test_viewer_can_copy_phone_and_address_but_not_write(self):
        widget = OwnerContactsWidget(self.repository, current_role="viewer")
        widget.set_record(7, "地主甲")
        widget.table.selectRow(0)
        self.assertTrue(widget.copy_phone_button.isEnabled())
        self.assertTrue(widget.copy_address_button.isEnabled())
        self.assertEqual(phone_choices(self.repository.rows[0])[0][1], "0912")
        self.assertEqual(
            address_choices(self.repository.rows[0])[0],
            ("聯絡地址", "台中市"),
        )
        with patch.object(
            widget,
            "_copy_choice",
            return_value=True,
        ) as copied:
            widget.copy_selected_phone()
            widget.copy_selected_address()
        self.assertEqual(copied.call_count, 2)
        self.assertFalse(widget.add_button.isEnabled())
        self.assertFalse(widget.deactivate_button.isEnabled())

    def test_copy_buttons_disable_when_selected_contact_has_no_values(self):
        self.repository.rows[1]["mobile_phone"] = ""
        widget = OwnerContactsWidget(self.repository, current_role="viewer")
        widget.show_inactive.setChecked(True)
        widget.set_record(7, "地主甲")
        widget.table.selectRow(1)
        self.assertFalse(widget.copy_phone_button.isEnabled())
        self.assertFalse(widget.copy_address_button.isEnabled())

    def test_double_click_detail_is_readonly_and_editor_may_request_edit(self):
        _DetailDialog.instances.clear()
        widget = OwnerContactsWidget(
            self.repository,
            current_role="editor",
            dialog_factory=_DetailDialog,
        )
        widget.set_record(7, "地主甲")
        widget.table.selectRow(0)
        widget.view_selected()
        detail = _DetailDialog.instances[-1]
        self.assertTrue(detail.kwargs["readonly"])
        self.assertTrue(detail.kwargs["allow_edit"])


if __name__ == "__main__":
    unittest.main()
