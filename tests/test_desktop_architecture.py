import inspect
import re
import unittest

import customer_search_controller
import customer_ui_qt
from customer_desktop_data import DesktopDataAccess
from customer_desktop_support import DesktopSupportMixin
from customer_management_workflows import ManagementWorkflowMixin
from customer_settings_workflows import SettingsWorkflowMixin
from PySide6.QtWidgets import QDialog


class _FakeSignal:
    """Stand-in for a real Qt signal on plain-Python fake dialogs.

    Production dialogs are genuine QDialog subclasses, so `.finished` is a
    real Qt signal `_show_non_modal_dialog()` (customer_desktop_support.py)
    can `.connect()` to. These fakes are plain Python objects with no
    human present to close them, so `.show()` immediately `.emit()`s this
    with QDialog.Accepted -- matching the old `.exec() -> QDialog.Accepted`
    behavior these fakes originally simulated before dialogs went
    non-modal.
    """

    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class LandAppStartupOrderTests(unittest.TestCase):
    def test_font_size_is_applied_before_records_are_loaded(self):
        # A real crash: refresh_records() on a large database sets a
        # preview into the table model and starts a background search
        # thread; apply_saved_font_size() then touches the tree view's
        # stylesheet, which makes Qt synchronously walk every row for
        # layout recomputation. That walk landing while the background
        # thread's "results ready" signal was pending delivery produced
        # AttributeError: '_TreeNode' object has no attribute 'kind' from
        # a stale internalPointer() -- a genuinely empty tree can't have
        # this problem, so font size must be applied first. This is a
        # source-order check rather than a reproduction of the race
        # itself (which needs real thread timing to trigger).
        source = inspect.getsource(customer_ui_qt.LandApp.__init__)
        self.assertLess(
            source.index("self.apply_saved_font_size()"),
            source.index("self.refresh_records()"),
        )


class BackgroundSearchThreadConnectionTests(unittest.TestCase):
    def test_worker_signals_are_not_connected_to_bare_lambdas(self):
        # The actual root cause of this app's long-running native-crash
        # saga (DESKTOP_CLIENT_VERSION 1.9.35): CustomerSearchWorker's
        # finished/failed/cancelled signals -- emitted on a background
        # QThread -- used to be connected to bare lambdas. Qt.AutoConnection
        # has no bound QObject to read a thread affinity from on a plain
        # lambda, so nothing guaranteed those calls (and everything they
        # touched, including the tree model) actually ran on the GUI
        # thread rather than the emitting worker thread -- QAbstractItemModel
        # is not thread-safe, and this was silently corrupting memory,
        # surfacing later as unrelated-looking native crashes.
        #
        # This is a static guard against reintroducing that exact pattern
        # in this specific method -- the real thread-timing race it guards
        # against cannot be reliably reproduced in this test suite (see
        # RecordTableModel._warn_if_wrong_thread() in customer_models.py
        # for a runtime tripwire that catches it if it ever comes back
        # anyway, anywhere in this model).
        source = inspect.getsource(
            customer_search_controller.SearchControllerMixin.start_record_search
        )
        connect_lines = [
            line
            for line in source.splitlines()
            if re.search(r"\bworker\.(finished|failed|cancelled)\.connect\(", line)
        ]
        self.assertTrue(connect_lines, "expected to find worker signal connections")
        for line in connect_lines:
            self.assertNotIn(
                "lambda",
                line,
                f"worker signal connected to a bare lambda, not a bound method: {line!r}",
            )
        self.assertIn("Qt.QueuedConnection", source)


class DesktopDataAccessTests(unittest.TestCase):
    def test_local_mode_uses_one_repository_for_records_and_settings(self):
        local = object()
        access = DesktopDataAccess(local)

        self.assertIs(access.records, local)
        self.assertIs(access.local, local)
        self.assertFalse(access.is_remote)

    def test_remote_mode_routes_records_without_replacing_local_state(self):
        local = object()
        remote = object()
        access = DesktopDataAccess(local, remote)

        self.assertIs(access.records, remote)
        self.assertIs(access.local, local)
        self.assertTrue(access.is_remote)

    def test_record_ids_are_loaded_from_remote_store(self):
        class LocalRepository:
            def fetch_customer_ids(self):
                raise AssertionError("device-local repository must not be queried")

        class RemoteRepository:
            def fetch_customer_ids(self):
                return {7, 11}

        access = DesktopDataAccess(LocalRepository(), RemoteRepository())

        self.assertEqual(access.fetch_record_ids(), {7, 11})

    def test_record_id_fallback_supports_preview_repositories(self):
        class PreviewRepository:
            def fetch_search_candidate_rows(self):
                return [{"id": "3"}, {"id": 5}]

        access = DesktopDataAccess(object(), PreviewRepository())

        self.assertEqual(access.fetch_record_ids(), {3, 5})


class RemoteSettingsWorkflowTests(unittest.TestCase):
    def test_api_mode_never_reads_device_watchlist_tables(self):
        class RemoteWindow(SettingsWorkflowMixin):
            api_mode = True
            watchlist_names = {"stale"}

            def _app_component(self, _name):
                raise AssertionError("device-local watchlist must not be queried")

        window = RemoteWindow()

        window.refresh_watchlist_cache()

        self.assertEqual(window.watchlist_names, set())
        self.assertTrue(window.confirm_watchlist_match("any remote owner"))

    def test_api_mode_loads_and_matches_watchlist_from_remote_repository(self):
        class RemoteRepository:
            def get_watchlist_entries(self):
                return [{"id": 1, "name": "王大明", "note": "先電話聯絡"}]

            def find_watchlist_match(self, owner_name):
                if owner_name == "王大明":
                    return {"id": 1, "name": "王大明", "note": "先電話聯絡"}
                return None

        class MessageBox:
            Yes = 1

            @staticmethod
            def question(*_args):
                return MessageBox.Yes

        class RemoteWindow(SettingsWorkflowMixin):
            api_mode = True
            watchlist_names = set()

            def active_record_repository(self):
                return RemoteRepository()

            def _app_component(self, name):
                if name == "QMessageBox":
                    return MessageBox
                raise AssertionError(f"unexpected local component: {name}")

        window = RemoteWindow()

        window.refresh_watchlist_cache()

        self.assertEqual(window.watchlist_names, {"王大明"})
        self.assertTrue(window.confirm_watchlist_match("王大明"))


class DesktopFieldVisitWorkflowTests(unittest.TestCase):
    def test_remote_desktop_adds_selected_records_to_shared_field_visit(self):
        captured = {}

        class Repository:
            def add_customers_to_field_visit(
                self, record_ids, *, visit_date, title, priority
            ):
                captured["request"] = (
                    list(record_ids),
                    visit_date,
                    title,
                    priority,
                )
                return {
                    "visit_date": visit_date,
                    "added_count": 2,
                    "existing_count": 1,
                    "priority": priority,
                }

        class ScheduleDialog:
            def __init__(self, selected_count, parent):
                captured["selected_count"] = selected_count
                captured["parent"] = parent
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

            def selected_date(self):
                return "2026-07-29"

            def title(self):
                return "桃園外勤"

            def priority(self):
                return 100

        class MessageBox:
            @staticmethod
            def information(_parent, title, message):
                captured["information"] = (title, message)

            @staticmethod
            def warning(*_args):
                raise AssertionError("不應顯示警告")

            @staticmethod
            def critical(*_args):
                raise AssertionError("不應顯示錯誤")

        class Window(ManagementWorkflowMixin, DesktopSupportMixin):
            api_mode = True

            def ensure_can_modify(self, _action):
                return True

            def selected_or_checked_record_ids(self):
                return [3, 7, 9]

            def active_record_repository(self):
                return Repository()

            def _app_component(self, name):
                return {
                    "FieldVisitScheduleDialog": ScheduleDialog,
                    "QMessageBox": MessageBox,
                }[name]

        window = Window()
        window.add_selected_records_to_field_visit()

        self.assertEqual(captured["selected_count"], 3)
        self.assertEqual(
            captured["request"],
            ([3, 7, 9], "2026-07-29", "桃園外勤", 100),
        )
        self.assertIn("已加入 2 筆", captured["information"][1])
        self.assertIn("優先拜訪", captured["information"][1])
        self.assertIn("原本已在", captured["information"][1])
