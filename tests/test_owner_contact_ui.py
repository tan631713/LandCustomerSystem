import os
import ast
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QGraphicsLineItem, QMessageBox

from customer_owner_contacts import (
    DeactivateRelationDialog,
    OwnerContactDialog,
    OwnerContactsWidget,
    OwnerContactTreeView,
    address_choices,
    phone_choices,
)


class _Repository:
    def __init__(self):
        self.calls = []
        self.fail_list = False
        self.search_results = []
        self.rows = [
            {
                "relation_id": 1,
                "owner_id": 2,
                "contact_id": 3,
                "name": "王小明",
                "external_id": "A123*****9",
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
                "external_id": "",
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

    def reveal_owner_contact_identity(self, record_id, relation_id):
        self.calls.append(("reveal", record_id, relation_id))
        return "A123456789"

    def search_owner_contacts(self, query, limit=50):
        self.calls.append(("search", query, limit))
        return [dict(row) for row in self.search_results]

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


class _FakeSignal:
    """Stand-in for a real Qt signal on plain-Python fake dialogs -- see
    the identical helper in tests/test_ui_workflow.py for the full
    rationale (production dialogs are real QDialog subclasses with a
    genuine `.finished` signal _show_non_modal_dialog() connects to;
    these fakes are plain Python objects with no human present, so
    `.show()` immediately `.emit()`s it)."""

    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


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
        self.finished = _FakeSignal()

    def exec(self):
        return QDialog.Accepted

    def show(self):
        self.finished.emit(QDialog.Accepted)

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def isVisible(self):
        return False

    def result(self):
        return QDialog.Accepted

    def result_values(self):
        return dict(self.payload)


class _DetailDialog:
    instances = []

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs
        self.edit_requested = False
        self.finished = _FakeSignal()
        self.instances.append(self)

    def exec(self):
        return QDialog.Rejected

    def show(self):
        # Matches the old .exec() -> QDialog.Rejected this fake always
        # returned: a read-only detail view the "user" closed without
        # requesting edit.
        self.finished.emit(QDialog.Rejected)

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def isVisible(self):
        return False

    def result(self):
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

    def test_tree_view_toggle_builds_one_node_per_visible_contact(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")
        self.assertIs(widget.view_stack.currentWidget(), widget.table)

        widget.tree_view_button.click()
        self.assertIs(widget.view_stack.currentWidget(), widget.tree_view)
        self.assertTrue(widget.tree_view_button.isChecked())
        self.assertFalse(widget.list_view_button.isChecked())
        # One row is active (visible in the table by default) -- the tree
        # must show exactly the same rows, not a separate data source.
        self.assertEqual(len(widget.tree_view._row_boxes), widget.table.rowCount())

        widget.list_view_button.click()
        self.assertIs(widget.view_stack.currentWidget(), widget.table)

    def test_tree_node_double_click_opens_the_same_detail_as_the_table(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")

        widget.tree_view.node_activated.emit(0)

        self.assertEqual(widget.table.currentRow(), 0)
        self.assertIn(("get", 7, 1), self.repository.calls)

    def test_tree_relation_labels_paint_above_their_own_backing_rect(self):
        # Regression test from a real user screenshot: the relationship
        # label ("兒子", "配偶"...) on each connecting line showed as a
        # blank rectangular notch with no visible text. Root cause: the
        # label's opaque backing rect was added to the scene *after* the
        # label itself, and QGraphicsScene paints equal-Z items in
        # insertion order -- so the backing silently painted over the
        # text on every single relation, every time, with no exception
        # or warning anywhere to catch it.
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")

        self.assertTrue(widget.tree_view._relation_labels)
        for label, backing in widget.tree_view._relation_labels:
            self.assertGreater(label.zValue(), backing.zValue())

    def test_tree_view_with_no_rows_shows_a_placeholder_instead_of_nodes(self):
        tree = OwnerContactTreeView()
        tree.set_data("", [])
        self.assertEqual(tree._row_boxes, [])

        tree.set_data("地主甲", [])
        self.assertEqual(tree._row_boxes, [])

    def test_tree_uses_right_angle_org_chart_connectors_not_diagonal_lines(self):
        # Per explicit user request (they supplied a reference org-chart
        # image): one vertical stem from the root down to a shared
        # horizontal trunk, then one vertical drop per contact -- not the
        # original single diagonal line per contact. For 3 contacts that
        # is 1 stem + 1 trunk + 3 drops = 5 line items, and every one of
        # them must be perfectly horizontal or vertical (a diagonal line
        # sneaking back in would have both a nonzero dx and dy).
        tree = OwnerContactTreeView()
        tree.set_data(
            "地主甲",
            [
                {"name": "陳美玉", "relationship_type": "配偶", "is_active": True},
                {"name": "王大明", "relationship_type": "兒子", "is_active": True},
                {"name": "王小華", "relationship_type": "女兒", "is_active": False},
            ],
        )
        lines = [item for item in tree.scene().items() if isinstance(item, QGraphicsLineItem)]
        self.assertEqual(len(lines), 5)
        for line in lines:
            segment = line.line()
            self.assertTrue(
                segment.x1() == segment.x2() or segment.y1() == segment.y2(),
                "connector line is diagonal, not right-angled",
            )

    def test_tree_zoom_in_and_out_change_scale_and_stay_within_bounds(self):
        # set_data()'s own reset_zoom() fits the tree to whatever this
        # (headless, never shown/resized) view's default viewport size
        # happens to be -- not a fixed number -- so read back the actual
        # starting zoom instead of assuming one, and check zoom_in/
        # zoom_out relative to it.
        tree = OwnerContactTreeView()
        tree.set_data("地主甲", [{"name": "王小明", "relationship_type": "兒子", "is_active": True}])
        starting_zoom = tree._zoom
        self.assertGreater(starting_zoom, 0)

        tree.zoom_in()
        self.assertAlmostEqual(tree._zoom, starting_zoom * tree._ZOOM_STEP, places=4)
        self.assertAlmostEqual(tree.transform().m11(), tree._zoom, places=4)

        tree.zoom_out()
        tree.zoom_out()
        self.assertAlmostEqual(tree._zoom, starting_zoom / tree._ZOOM_STEP, places=4)

        for _ in range(60):
            tree.zoom_out()
        self.assertGreaterEqual(tree._zoom, tree._MIN_ZOOM)

        for _ in range(60):
            tree.zoom_in()
        self.assertLessEqual(tree._zoom, tree._MAX_ZOOM)

    def test_tree_reset_zoom_never_divides_by_zero_with_no_viewport_size(self):
        # Regression guard: fitInView() scales by the viewport's current
        # pixel size, which is genuinely 0x0 before a widget has ever
        # been shown/resized (true for every headless test, and briefly
        # true for a real one too) -- that used to leave self._zoom at 0,
        # and zoom_in()/zoom_out() divide by self._zoom, so the very next
        # call after a reset would raise ZeroDivisionError.
        tree = OwnerContactTreeView()
        tree.set_data("地主甲", [{"name": "王小明", "relationship_type": "兒子", "is_active": True}])
        self.assertGreater(tree._zoom, 0)
        tree.zoom_in()
        tree.zoom_out()
        tree.reset_zoom()
        self.assertGreater(tree._zoom, 0)

    def test_zoom_buttons_are_only_enabled_while_the_tree_view_is_active(self):
        widget = OwnerContactsWidget(self.repository, current_role="editor")
        widget.set_record(7, "地主甲")
        self.assertFalse(widget.tree_zoom_in_button.isEnabled())

        widget.tree_view_button.click()
        self.assertTrue(widget.tree_zoom_in_button.isEnabled())
        self.assertTrue(widget.tree_zoom_out_button.isEnabled())
        self.assertTrue(widget.tree_zoom_reset_button.isEnabled())

        widget.list_view_button.click()
        self.assertFalse(widget.tree_zoom_in_button.isEnabled())

    def test_identity_is_masked_revealed_and_preserved_when_unchanged(self):
        existing = dict(self.repository.rows[0])
        dialog = OwnerContactDialog(
            self.repository,
            7,
            existing=existing,
        )
        self.assertEqual(dialog.edit_external_id.text(), "A123*****9")
        self.assertIsNone(dialog.result_values()["contact"]["external_id"])
        dialog._toggle_identity("edit")
        self.assertEqual(dialog.edit_external_id.text(), "A123456789")
        self.assertIn(("reveal", 7, 1), self.repository.calls)
        self.assertIsNone(dialog.result_values()["contact"]["external_id"])
        dialog._identity_text_edited("edit", "h100059743")
        self.assertEqual(dialog.edit_external_id.text(), "H100059743")
        self.assertEqual(
            dialog.result_values()["contact"]["external_id"], "H100059743"
        )

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
        # deactivate_selected() now opens this non-modally (.show(), not
        # .exec()) -- calling the dialog's own real .accept() when shown
        # is the equivalent simulated "user accepted" trigger: it sets
        # result() to Accepted and emits the real finished signal, same
        # as a genuine button click would.
        with patch.object(
            DeactivateRelationDialog,
            "show",
            lambda self: self.accept(),
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

    def test_add_dialog_has_no_upfront_mode_tabs(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            self.assertFalse(hasattr(dialog, "mode_tabs"))
            self.assertTrue(dialog._match_table.isHidden())
            self.assertTrue(dialog._use_match_button.isHidden())
            self.assertTrue(dialog._unlink_button.isHidden())
        finally:
            dialog.close()

    def test_typing_a_name_shows_live_matches_without_a_separate_tab(self):
        self.repository.search_results = [
            {
                "id": 9,
                "name": "王小明",
                "mobile_phone": "0912345678",
                "home_phone": "",
                "registered_address": "桃園市桃園區",
                "contact_address": "",
                "owner_count": 2,
            }
        ]
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog.new_name.setText("王小明")
            dialog._search_for_matching_contacts()
            self.assertIn(("search", "王小明", 5), self.repository.calls)
            self.assertFalse(dialog._match_table.isHidden())
            self.assertFalse(dialog._use_match_button.isHidden())
            self.assertEqual(dialog._match_table.rowCount(), 1)
            self.assertIn("1", dialog._match_hint.text())
        finally:
            dialog.close()

    def test_short_or_empty_name_does_not_search(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog.new_name.setText("王")
            dialog._search_for_matching_contacts()
            self.assertEqual(
                [call for call in self.repository.calls if call[0] == "search"], []
            )
            self.assertTrue(dialog._match_table.isHidden())
        finally:
            dialog.close()

    def test_no_matches_shows_hint_and_hides_table(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog.new_name.setText("查無此人")
            dialog._search_for_matching_contacts()
            self.assertIn("沒有找到", dialog._match_hint.text())
            self.assertTrue(dialog._match_table.isHidden())
            self.assertTrue(dialog._use_match_button.isHidden())
        finally:
            dialog.close()

    def test_applying_a_match_locks_shared_fields_and_switches_to_link_mode(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog._apply_contact_link(
                {
                    "id": 9,
                    "name": "王小明",
                    "mobile_phone": "0912345678",
                    "home_phone": "",
                    "registered_address": "桃園市桃園區",
                    "contact_address": "台中市",
                    "owner_count": 2,
                }
            )
            self.assertEqual(dialog.new_name.text(), "王小明")
            self.assertEqual(dialog.new_mobile_phone.text(), "0912345678")
            self.assertFalse(dialog.new_mobile_phone.isEnabled())
            self.assertFalse(dialog.new_registered_address.isEnabled())
            self.assertFalse(dialog._unlink_button.isHidden())
            self.assertIn("王小明", dialog._link_banner.text())
            self.assertIn("2", dialog._link_banner.text())

            values = dialog.result_values()
            self.assertEqual(values["mode"], "link")
            self.assertEqual(values["contact_id"], 9)
        finally:
            dialog.close()

    def test_unlink_button_restores_manual_entry_mode(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog._apply_contact_link(
                {
                    "id": 9,
                    "name": "王小明",
                    "mobile_phone": "0912345678",
                    "home_phone": "",
                    "registered_address": "桃園市桃園區",
                    "contact_address": "",
                    "owner_count": 2,
                }
            )
            dialog._clear_contact_link()
            self.assertTrue(dialog.new_mobile_phone.isEnabled())
            self.assertEqual(dialog.new_mobile_phone.text(), "")
            self.assertTrue(dialog._unlink_button.isHidden())

            dialog.new_name.setText("陳先生")
            dialog.new_relationship_type.setCurrentText("兒子")
            values = dialog.result_values()
            self.assertEqual(values["mode"], "new")
            self.assertEqual(values["contact"]["name"], "陳先生")
        finally:
            dialog.close()

    def test_birth_year_updates_age_live_and_carries_through_link_and_unlink(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            self.assertEqual(dialog.new_age.text(), "")
            dialog.new_birth_year.setText("1980")
            expected_age = str(date.today().year - 1980)
            self.assertEqual(dialog.new_age.text(), expected_age)
            values = dialog.result_values()
            self.assertEqual(values["contact"]["birth_year"], "1980")

            dialog._apply_contact_link(
                {
                    "id": 9,
                    "name": "王小明",
                    "mobile_phone": "0912345678",
                    "home_phone": "",
                    "registered_address": "桃園市桃園區",
                    "contact_address": "",
                    "birth_year": "1990",
                    "owner_count": 2,
                }
            )
            linked_age = str(date.today().year - 1990)
            self.assertEqual(dialog.new_birth_year.text(), "1990")
            self.assertEqual(dialog.new_age.text(), linked_age)
            self.assertFalse(dialog.new_birth_year.isEnabled())

            dialog._clear_contact_link()
            self.assertTrue(dialog.new_birth_year.isEnabled())
            self.assertEqual(dialog.new_birth_year.text(), "")
            self.assertEqual(dialog.new_age.text(), "")
        finally:
            dialog.close()

    def test_manual_entry_without_touching_matches_still_creates_new_contact(self):
        dialog = OwnerContactDialog(self.repository, 7)
        try:
            dialog.new_name.setText("李小美")
            dialog.new_relationship_type.setCurrentText("女兒")
            values = dialog.result_values()
            self.assertEqual(values["mode"], "new")
            self.assertEqual(values["contact"]["name"], "李小美")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
