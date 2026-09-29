"""Saving an owner against the home server must not wait on a full re-download.

The window is built in API mode on top of a fake home server that records which
requests the *GUI thread* had to wait for before the "資料已儲存" message.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import customer_ui_qt as app
from customer_database import CustomerDatabase
from customer_desktop_api import DesktopApiConnectionError, DesktopApiRecordRepository
from customer_repository import CustomerRepository
from customer_security import make_fernet

MAIN_THREAD = threading.main_thread()


def make_rows(count):
    rows = []
    for record_id in range(count, 0, -1):
        land_id = record_id // 2 + 1
        rows.append({
            "id": record_id, "ownership_id": record_id, "land_id": land_id, "owner_id": record_id,
            "district": "中壢區", "section": f"段{land_id % 40}", "subsection": "",
            "registration_order": f"{record_id:04d}", "land_number": f"{land_id:04d}-0000",
            "area": "123.45", "declared_value": "100000", "numerator": "1", "denominator": "3",
            "ping": "12.3", "total_declared_value": "3000", "registration_reason": "買賣",
            "note": "舊備註", "visit_log": "拜訪紀錄", "owner_name": f"王大明{record_id}",
            "external_id": f"A{100000000 + record_id}", "address": "桃園市中壢區某路 123 號",
            "name": f"王大明{record_id}", "birth_year": "1960",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            "case_names": "", "tag_names": "", "tag_items": [], "tags": [], "primary_tag_color": "",
            "attachment_count": 0, "attachment_names": "", "custom_values": "",
        })
    return rows


class FakeHomeServer:
    def __init__(self, count):
        self.rows = make_rows(count)
        self.requests = []  # (description, ran_on_gui_thread)
        self.moved_land_id = None
        self.operation_log_error = None

    def _hit(self, description):
        self.requests.append((description, threading.current_thread() is MAIN_THREAD))

    # Re-selecting the saved row after the refresh reloads the owner-contact
    # list (a separate, pre-existing request that belongs to selecting a row,
    # not to saving), so it is not counted as something the save waits for.
    SELECTION_RELOAD = {"list_owner_contacts"}

    def gui_requests(self):
        return [
            name for name, on_gui in self.requests
            if on_gui and name not in self.SELECTION_RELOAD
        ]

    def count(self, description):
        return sum(1 for name, _on_gui in self.requests if name == description)

    def list_all_records(self, **_kwargs):
        self._hit("list all records")
        return [dict(row) for row in self.rows]

    def get_record(self, record_id):
        self._hit("get one record")
        row = dict(next(item for item in self.rows if item["id"] == int(record_id)))
        if self.moved_land_id is not None:
            row["land_id"] = self.moved_land_id
        return row

    def replace_record_with_history(self, record_id, values, _logs):
        self._hit("save record")
        for row in self.rows:
            if row["id"] == int(record_id):
                row.update(values)
        return int(record_id)

    def replace_record(self, record_id, values):
        return self.replace_record_with_history(record_id, values, [])

    def create_record(self, values):
        self._hit("create record")
        record_id = max(row["id"] for row in self.rows) + 1
        row = make_rows(1)[0]
        row.update(values)
        row.update(id=record_id, ownership_id=record_id, land_id=5000 + record_id, owner_id=record_id)
        self.rows.insert(0, row)
        return record_id

    def list_watchlist(self):
        self._hit("get watchlist")
        return []

    def add_operation_log(self, *_args, **_kwargs):
        self._hit("write operation log")
        if self.operation_log_error is not None:
            raise self.operation_log_error
        return 1

    def __getattr__(self, name):
        def any_other_request(*_args, **_kwargs):
            self._hit(name)
            return []

        return any_other_request


class DesktopSaveLatencyTests(unittest.TestCase):
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
            app.DATABASE, app.SCHEMA_PATH, self.root / "missing-seed.sql", app.LAND_FIELDS
        )
        app.init_db()
        app.REPOSITORY.create_admin_user("test-password")
        self.key = app.REPOSITORY.authenticate_user("admin", "test-password")

    def tearDown(self):
        self.application.processEvents()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def open_window(self, count):
        server = FakeHomeServer(count)
        repository = DesktopApiRecordRepository(server, make_fernet(self.key))
        window = app.LandApp(self.key, record_repository=repository, api_mode=True)
        self.settle(window)
        return server, repository, window

    def settle(self, window, timeout_ms=30000):
        """Let background searches, the reconcile fetch and queued refreshes finish."""

        deadline = QTimer()
        deadline.setSingleShot(True)
        loop = QEventLoop()
        deadline.timeout.connect(loop.quit)
        deadline.start(timeout_ms)
        poll = QTimer()

        def check():
            window.wait_for_background_tasks(0.01)
            busy = window.record_searches or getattr(window, "_saved_record_reconcile", None)
            if not busy:
                loop.quit()

        poll.timeout.connect(check)
        poll.start(20)
        loop.exec()
        poll.stop()
        deadline.stop()
        window.wait_for_background_tasks()
        self.application.processEvents()

    def displayed(self, window, record_id):
        return next(
            record["raw"]
            for record in window.table_model.all_rows
            if int(record["id"]) == record_id
        )

    def save_with_message_snapshot(self, window, server):
        """Run save_record(); report which requests had been waited for when the
        "資料已儲存" message was shown."""

        snapshot = {}

        def information(*_args, **_kwargs):
            snapshot["waited_for"] = server.gui_requests()

        with patch.object(app, "QMessageBox") as message_box:
            message_box.Yes = 1
            message_box.information.side_effect = information
            window.save_record()
        return snapshot["waited_for"]

    def test_saving_waits_only_for_the_write_and_updates_the_list_in_place(self):
        for count in (40, 600):  # below and above the background-search threshold
            with self.subTest(records=count):
                server, repository, window = self.open_window(count)
                try:
                    target = count // 2
                    window.load_record(target)
                    self.settle(window)
                    server.requests.clear()
                    window.set_field_text("note", "改過的備註")

                    waited_for = self.save_with_message_snapshot(window, server)
                    self.assertEqual(waited_for, ["save record"])

                    self.settle(window)
                    self.assertEqual(server.count("list all records"), 0)
                    self.assertEqual(server.count("write operation log"), 1)
                    self.assertEqual(server.count("get one record"), 0)  # same land, same owner
                    self.assertEqual(self.displayed(window, target)["note"], "改過的備註")
                finally:
                    window.close()

    def check_new_record_is_cheap(self, count):
        server, repository, window = self.open_window(count)
        try:
            server.requests.clear()
            window.new_record()
            for key, value in {"district": "中壢區", "section": "新段", "land_number": "77-0",
                               "owner_name": "新地主", "note": "新增的備註"}.items():
                window.set_field_text(key, value)

            waited_for = self.save_with_message_snapshot(window, server)
            self.assertEqual(waited_for, ["create record", "get one record"])

            self.settle(window)
            self.assertEqual(server.count("list all records"), 0)
            new_id = window.selected_record_id
            self.assertEqual(self.displayed(window, new_id)["note"], "新增的備註")
        finally:
            window.close()

    # One test per list size: the window remembers its selection in the
    # (per-test) settings database, which would leak into a second window.
    def test_a_new_record_does_not_download_the_whole_list_either(self):
        self.check_new_record_is_cheap(40)

    def test_a_new_record_in_a_long_list_uses_the_background_search_and_stays_cheap(self):
        self.check_new_record_is_cheap(600)

    def test_moving_a_record_to_another_land_is_reconciled_in_the_background(self):
        server, repository, window = self.open_window(40)
        try:
            target = 20
            window.load_record(target)
            self.settle(window)
            server.requests.clear()
            server.moved_land_id = 9999  # the server puts it on a new parcel
            window.set_field_text("land_number", "9999-0000")

            waited_for = self.save_with_message_snapshot(window, server)
            self.assertEqual(waited_for, ["save record"])

            self.settle(window)
            self.assertEqual(server.count("get one record"), 1)
            self.assertEqual(server.count("list all records"), 0)
            self.assertEqual(self.displayed(window, target)["land_id"], 9999)
            self.assertEqual(self.displayed(window, target)["land_number"], "9999-0000")
        finally:
            window.close()

    def test_a_failing_operation_log_never_breaks_the_save(self):
        server, repository, window = self.open_window(40)
        try:
            target = 10
            window.load_record(target)
            self.settle(window)
            server.requests.clear()
            server.operation_log_error = DesktopApiConnectionError("offline")
            window.set_field_text("note", "仍然要存")

            waited_for = self.save_with_message_snapshot(window, server)
            self.assertEqual(waited_for, ["save record"])
            self.settle(window)
            self.assertEqual(server.count("write operation log"), 1)
            self.assertEqual(self.displayed(window, target)["note"], "仍然要存")
        finally:
            window.close()

    def test_the_watchlist_is_not_downloaded_again_for_every_save(self):
        server, repository, window = self.open_window(40)
        try:
            window.load_record(5)
            self.settle(window)
            server.requests.clear()
            for note in ("第一次", "第二次", "第三次"):
                window.set_field_text("note", note)
                self.save_with_message_snapshot(window, server)
                self.settle(window)
            self.assertEqual(server.count("get watchlist"), 0)
        finally:
            window.close()

    def test_local_mode_still_writes_the_operation_log_synchronously(self):
        window = app.LandApp(self.key)
        try:
            for key, value in {"district": "中正區", "section": "一段", "land_number": "100",
                               "owner_name": "王小明"}.items():
                window.set_field_text(key, value)
            with patch.object(window, "_log_operation") as log, patch.object(app, "QMessageBox"):
                window.save_record()
                log.assert_called_once()
            self.application.processEvents()
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
