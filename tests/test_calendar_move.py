"""行程月曆「移到其他天」: API route, service rules, SQL flow and dialog."""

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi.testclient import TestClient

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.field_visit_service import (
    FieldVisitService,
    FieldVisitTransitionError,
)
from tests.test_field_visit_api import _FieldVisitApiSource
from tests.test_postgres_field_visits import USER, _Connection, _Source


class _MoveApiSource(_FieldVisitApiSource):
    def move_field_visit_item(self, user, item_id, target_date, **options):
        self.calls.append(("move", user.role, item_id, target_date, options))
        if item_id == 999:
            raise KeyError(item_id)
        if item_id == 998:
            raise ValueError("那一天已經排了這位地主，不能重複排入。")
        if item_id == 997:
            raise FieldVisitTransitionError("not movable")
        return {"item_id": item_id, "route_id": 20, "visit_date": str(target_date)}


class CalendarMoveApiTests(unittest.TestCase):
    def setUp(self):
        self.source = _MoveApiSource()
        self.app = create_app(
            settings=ApiSettings(backend="sqlite"),
            data_source=self.source,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.target = (date.today() + timedelta(days=2)).isoformat()

    def tearDown(self):
        self.client.close()

    def login(self, role="editor"):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": role, "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def move(self, item_id, target, role="editor", key="move-key-0001"):
        headers = self.login(role)
        if key:
            headers["Idempotency-Key"] = key
        return self.client.post(
            f"/api/v1/field-visit-items/{item_id}/move",
            json={"target_date": target},
            headers=headers,
        )

    def test_requires_login_editor_and_idempotency_key(self):
        unauthorized = self.client.post(
            "/api/v1/field-visit-items/5/move", json={"target_date": self.target}
        )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(self.move(5, self.target, role="viewer").status_code, 403)
        self.assertEqual(self.move(5, self.target, key=None).status_code, 422)

    def test_editor_moves_item_to_target_date(self):
        response = self.move(5, self.target)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["visit_date"], self.target)
        call = self.source.calls[-1]
        self.assertEqual(call[:4], ("move", "editor", 5, date.fromisoformat(self.target)))
        self.assertTrue(call[4]["idempotency_key"])
        self.assertTrue(call[4]["request_hash"])

    def test_rejects_past_dates_and_bad_payload(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        response = self.move(5, yesterday)
        self.assertEqual(response.status_code, 409)
        self.assertIn("今天以前", response.json()["detail"])
        self.assertEqual(self.move(5, "not-a-date").status_code, 422)
        extra = self.client.post(
            "/api/v1/field-visit-items/5/move",
            json={"target_date": self.target, "route_id": 3},
            headers={**self.login(), "Idempotency-Key": "move-key-0002"},
        )
        self.assertEqual(extra.status_code, 422)

    def test_maps_errors_to_readable_responses(self):
        self.assertEqual(self.move(999, self.target).status_code, 404)
        duplicate = self.move(998, self.target, key="move-key-0003")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("已經排了", duplicate.json()["detail"])
        self.assertEqual(self.move(997, self.target, key="move-key-0004").status_code, 409)


class CalendarMoveServiceTests(unittest.TestCase):
    def test_service_validates_before_reaching_the_database(self):
        class Source:
            def move_field_visit_item(self, *args, **kwargs):
                raise AssertionError("must not be called")

        service = FieldVisitService(Source())
        today = date(2026, 11, 18)
        with self.assertRaises(ValueError):
            service.move_item(USER, 5, date(2026, 11, 17), today=today)
        with self.assertRaises(ValueError):
            service.move_item(USER, 0, date(2026, 11, 20), today=today)
        with self.assertRaises(ValueError):
            service.move_item(USER, 5, "2026-11-20", today=today)


class CalendarMoveSqlTests(unittest.TestCase):
    """The SQL flow against a scripted connection; the same method was also
    checked end-to-end against a real PostgreSQL 16 with postgres/schema.sql."""

    def current(self, status="planned", user_id=None):
        return {
            "id": 9,
            "route_id": 4,
            "status": status,
            "ownership_id": 101,
            "user_id": USER.id if user_id is None else user_id,
            "visit_date": date(2026, 11, 18),
            "route_status": "in_progress",
        }

    def test_moves_into_a_new_route_and_records_history(self):
        connection = _Connection(
            [
                self.current("postponed"),
                None,  # no route that day yet
                {"id": 7, "status": "planned"},  # created
                None,  # not already on that route
                {"next_order": 1},
                None,  # UPDATE item
                {"id": 33},  # history
                None,  # reopen target route
                {"remaining": 0},
                None,  # update source route
                None,  # audit
            ]
        )
        result = _Source(connection).move_field_visit_item(USER, 9, date(2026, 11, 20))
        self.assertEqual(result["route_id"], 7)
        self.assertEqual(result["old_status"], "postponed")
        self.assertEqual(result["new_status"], "planned")
        self.assertTrue(result["created_route"])
        update_sql, update_params = connection.calls[5]
        self.assertIn("UPDATE field_visit_route_items", update_sql)
        self.assertIn("postponed_until = NULL", update_sql)
        self.assertEqual(update_params, (7, 1, 9))
        history_sql, history_params = connection.calls[6]
        self.assertIn("field_visit_status_history", history_sql)
        self.assertEqual(history_params[3], "改期：2026-11-18 → 2026-11-20")
        self.assertIn("api_move_field_visit_item", str(connection.calls[10][1]))
        self.assertEqual(connection.responses, [])

    def test_rejects_started_or_finished_items(self):
        for status in ("in_progress", "completed", "skipped", "cancelled"):
            connection = _Connection([self.current(status)])
            with self.assertRaises(FieldVisitTransitionError):
                _Source(connection).move_field_visit_item(USER, 9, date(2026, 11, 20))

    def test_rejects_another_users_item_and_same_day(self):
        with self.assertRaises(PermissionError):
            _Source(_Connection([self.current(user_id=99)])).move_field_visit_item(
                USER, 9, date(2026, 11, 20)
            )
        with self.assertRaises(ValueError):
            _Source(_Connection([self.current()])).move_field_visit_item(
                USER, 9, date(2026, 11, 18)
            )

    def test_rejects_owner_already_on_target_day(self):
        connection = _Connection(
            [self.current(), {"id": 7, "status": "planned"}, {"id": 55}]
        )
        with self.assertRaises(ValueError) as caught:
            _Source(connection).move_field_visit_item(USER, 9, date(2026, 11, 20))
        self.assertIn("已經排了", str(caught.exception))


class CalendarMoveDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.application = QApplication.instance() or QApplication([])

    def make_dialog(self):
        from PySide6.QtCore import QDate

        from customer_dialogs import VisitCalendarDialog

        today = QDate.currentDate().toString("yyyy-MM-dd")

        class Window:
            def __init__(self):
                self.moves = []
                self.items = [
                    {
                        "id": 9,
                        "customer_id": 101,
                        "date": today,
                        "item_kind": "route_item",
                        "item_status": "planned",
                        "calendar_status": "scheduled",
                        "owner_name": "王小明",
                    },
                    {
                        "id": 12,
                        "customer_id": 102,
                        "date": today,
                        "item_kind": "contact_log",
                        "calendar_status": "completed",
                        "owner_name": "李大華",
                    },
                ]

            def load_visit_calendar_items(self, start_date, end_date, mine_only=False):
                del mine_only
                return [i for i in self.items if start_date <= i["date"] <= end_date]

            def move_visit_calendar_item(self, item, target_date):
                self.moves.append((item["id"], target_date))
                item["date"] = target_date

        window = Window()
        return VisitCalendarDialog(window), window

    def test_move_button_only_for_scheduled_route_items(self):
        dialog, _window = self.make_dialog()
        try:
            self.assertFalse(dialog.move_button.isEnabled())
            dialog.table.selectRow(0)
            self.assertTrue(dialog.move_button.isEnabled())
            dialog.table.selectRow(1)
            self.assertFalse(dialog.move_button.isEnabled())
        finally:
            dialog.close()

    def test_move_updates_calendar_and_selects_target_day(self):
        from PySide6.QtCore import QDate

        dialog, window = self.make_dialog()
        try:
            target = QDate.currentDate().addDays(3)
            self.assertTrue(dialog.move_item_to(window.items[0], target))
            self.assertEqual(window.moves, [(9, target.toString("yyyy-MM-dd"))])
            self.assertEqual(dialog.selected_date, target)
            self.assertEqual(dialog.table.item(0, 0).text(), "王小明")
            self.assertIn("已把「王小明」移到", dialog.summary_label.text())
        finally:
            dialog.close()

    def test_past_day_is_refused_without_calling_the_server(self):
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QMessageBox

        dialog, window = self.make_dialog()
        try:
            with patch.object(QMessageBox, "information") as info:
                moved = dialog.move_item_to(window.items[0], QDate.currentDate().addDays(-1))
            self.assertFalse(moved)
            info.assert_called_once()
            self.assertEqual(window.moves, [])
        finally:
            dialog.close()

    def test_drop_asks_then_moves(self):
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QMessageBox

        dialog, window = self.make_dialog()
        try:
            target = QDate.currentDate().addDays(1)
            dialog._start_drag(window.items[0])
            with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
                dialog._drop_on_day(target)
            self.assertEqual(window.moves, [])
            dialog._start_drag(window.items[0])
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dialog._drop_on_day(target)
            self.assertEqual(window.moves, [(9, target.toString("yyyy-MM-dd"))])
        finally:
            dialog.close()

    def test_server_error_is_shown_not_raised(self):
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QMessageBox

        from customer_desktop_api import DesktopApiResponseError

        dialog, window = self.make_dialog()

        def fail(item, target_date):
            raise DesktopApiResponseError(404, "Not Found")

        window.move_visit_calendar_item = fail
        try:
            with patch.object(QMessageBox, "warning") as warning:
                moved = dialog.move_item_to(window.items[0], QDate.currentDate().addDays(1))
            self.assertFalse(moved)
            self.assertIn("伺服器", warning.call_args[0][2])
        finally:
            dialog.close()


class CalendarScheduledOnlyTests(unittest.TestCase):
    """只看排程: hides completed/skipped records, unchecking restores them."""

    make_dialog = CalendarMoveDialogTests.make_dialog

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.application = QApplication.instance() or QApplication([])

    def _names(self, dialog):
        return [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]

    def test_defaults_to_unchecked_and_shows_everything(self):
        dialog, _window = self.make_dialog()
        try:
            self.assertFalse(dialog.scheduled_only_checkbox.isChecked())
            self.assertEqual(dialog.scheduled_only_checkbox.text(), "只看排程")
            self.assertEqual(self._names(dialog), ["王小明", "李大華"])
        finally:
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()

    def test_checking_hides_completed_and_unchecking_restores(self):
        from PySide6.QtCore import QDate

        dialog, window = self.make_dialog()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        window.items.append(
            {
                "id": 13,
                "customer_id": 103,
                "date": today,
                "item_kind": "route_item",
                "item_status": "planned",
                "calendar_status": "overdue",
                "owner_name": "陳逾期",
            }
        )
        window.items.append(
            {
                "id": 14,
                "customer_id": 104,
                "date": today,
                "item_kind": "route_item",
                "item_status": "skipped",
                "calendar_status": "skipped",
                "owner_name": "林略過",
            }
        )
        try:
            dialog.refresh()
            self.assertEqual(len(self._names(dialog)), 4)
            dialog.scheduled_only_checkbox.setChecked(True)
            self.assertEqual(self._names(dialog), ["王小明", "陳逾期"])
            self.assertEqual(len(dialog.items_by_date[today]), 2)
            self.assertIn("共有 2 筆排程（只看排程）", dialog.summary_label.text())
            dialog.scheduled_only_checkbox.setChecked(False)
            self.assertEqual(self._names(dialog), ["王小明", "李大華", "陳逾期", "林略過"])
            self.assertIn("共有 4 筆行程／紀錄", dialog.summary_label.text())
        finally:
            dialog.close()
            dialog.deleteLater()
            self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
