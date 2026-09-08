"""Tests for the "匯出 Excel" already-exported duplicate-detection workflow.

User request: "我想要在輸出Excel時能自行判斷哪些地主是已經輸出過並提示我讓我選擇
先前輸出過的要不要再次輸出" -- when exporting to Excel from the main screen,
warn about (and let the user exclude) land owners that were already exported
to Excel before, at any point.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import customer_ui_qt as app  # noqa: F401 -- configures customer_export_controller's module-level APP_DIR/TABLE_COLUMNS at import time
from cryptography.fernet import Fernet
from customer_database import CustomerDatabase
from customer_export_controller import (
    MAIL_DUPLICATE_TAG_SETTING,
    ExportControllerMixin,
    PreviousExportDuplicatesDialog,
    load_mail_duplicate_tag,
    save_mail_duplicate_tag,
)
from customer_repository import CustomerRepository
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QWidget

LAND_FIELDS = app.LAND_FIELDS


class _ExportWorkflowHarness(ExportControllerMixin, QWidget):
    """Minimal host object exercising ExportControllerMixin's real
    methods without needing a full LandApp/QMainWindow -- mirrors the
    _WorkflowHarness pattern already used in test_land_tree_grouping.py
    for other controller mixins. A real QWidget (rather than a bare
    object) because export_rows_to_xlsx() passes `self` as the parent of
    PreviousExportDuplicatesDialog, which Qt requires to be a QWidget."""

    def __init__(self, repository):
        QWidget.__init__(self)
        self.repository = repository
        # decrypt_value() is safe/idempotent on already-plaintext values
        # (checks the encryption prefix before attempting to decrypt), so
        # any real Fernet key works here -- these tests never actually
        # encrypt anything, matching how the rest of this file's fixtures
        # save customers directly with plaintext field values.
        self.fernet = Fernet(Fernet.generate_key())
        # None -> get_export_columns() falls back to TABLE_COLUMNS[1:],
        # same as when no table view has been built yet.
        self.table_view = None
        self.ready_calls = []

    def active_record_repository(self):
        return self.repository

    def start_excel_worker(self, worker, finished_handler, status_message):
        # Bypass the real QThread machinery (start_excel_worker's normal
        # home is ImportControllerMixin, not mixed in here) -- run the
        # worker synchronously and forward its "finished" signal exactly
        # like the real wiring would (worker.finished -> finished_handler,
        # i.e. the real bound handle_excel_export_ready below), so
        # export_rows_to_xlsx()'s actual production code path -- the one
        # that was fixed after a real "frozen, blank message box" bug
        # report -- still gets exercised for real, not bypassed.
        del status_message
        captured = {}

        def capture(file_path, row_count):
            captured["file_path"] = file_path
            captured["row_count"] = row_count

        worker.finished.connect(capture)
        worker.run()
        if captured:
            finished_handler(captured["file_path"], captured["row_count"])
        return True

    def handle_excel_export_ready(self, file_path, row_count):
        self.ready_calls.append((file_path, row_count))
        # Exercises the real production method -- including the
        # mark-as-exported bookkeeping that lives there specifically so
        # it runs through a genuine bound-method (properly thread-safe)
        # Qt connection instead of a bare closure. QMessageBox.information
        # is patched here rather than skipped: a real, unmocked call
        # would otherwise block this test forever on a modal dialog with
        # no one to click it.
        with patch("customer_export_controller.QMessageBox"):
            ExportControllerMixin.handle_excel_export_ready(self, file_path, row_count)


def _row(customer_id, **fields):
    raw = {key: "" for key, _label in LAND_FIELDS}
    raw.update(fields)
    return {"id": customer_id, "raw": raw}


def _land_record(**values):
    base = {key: "" for key, _label in LAND_FIELDS}
    base.update(values)
    base["name"] = base.get("owner_name") or ""
    return base


class ExportDuplicateDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.database = CustomerDatabase(self.root / "customers.db", self.root / "backups")
        project_root = Path(__file__).resolve().parents[1]
        self.repository = CustomerRepository(
            self.database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            LAND_FIELDS,
        )
        self.repository.init_db()
        self.harness = _ExportWorkflowHarness(self.repository)

    def tearDown(self):
        self.temp_context.cleanup()

    def _save_customer(self, **fields):
        return self.repository.save_customer(_land_record(**fields))

    def _export_counts(self):
        with self.repository.database.connect() as conn:
            return {
                row["customer_id"]: row["export_count"]
                for row in conn.execute("SELECT customer_id, export_count FROM excel_exports")
            }

    def test_finished_handler_passed_to_the_worker_is_a_real_bound_method(self):
        # Regression test: a real user report -- "按下匯出後...程式無回應"
        # (a blank, frozen "匯出完成" dialog; Windows marked the app "沒有
        # 回應") -- traced to export_rows_to_xlsx() originally passing a
        # bare Python closure as worker.finished's slot instead of a
        # bound method on self. Qt can only infer a receiver's thread
        # affinity (and auto-upgrade the connection to a queued one, so
        # the slot body actually runs on the GUI thread) for a genuine
        # QObject slot; a closure has none, so the connection silently
        # ran direct on the background worker thread -- where the
        # QMessageBox this slot shows is undefined behaviour. This also
        # explains why re-exporting the same rows never detected a
        # duplicate: the mark-as-exported write, running off-thread,
        # never reliably completed. Locks in the fix: whatever callable
        # export_rows_to_xlsx hands to start_excel_worker as
        # finished_handler must be the real bound handle_excel_export_ready
        # method, so PySide6's own thread-affinity detection applies.
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        target = str(self.root / "export-handler-identity.xlsx")
        captured = {}

        def capturing_start_excel_worker(worker, finished_handler, status_message):
            captured["finished_handler"] = finished_handler
            del worker, status_message
            return True

        with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")):
            with patch.object(
                self.harness, "start_excel_worker", side_effect=capturing_start_excel_worker
            ):
                self.harness.export_rows_to_xlsx(rows)

        self.assertEqual(captured["finished_handler"], self.harness.handle_excel_export_ready)
        self.assertTrue(hasattr(captured["finished_handler"], "__self__"))

    def test_first_time_export_proceeds_without_any_prompt(self):
        first_id = self._save_customer(owner_name="王小明")
        second_id = self._save_customer(owner_name="陳小華")
        rows = [_row(first_id, owner_name="王小明"), _row(second_id, owner_name="陳小華")]
        target = str(self.root / "export.xlsx")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")):
            with patch.object(PreviousExportDuplicatesDialog, "exec") as mocked_exec:
                self.harness.export_rows_to_xlsx(rows)
                mocked_exec.assert_not_called()
        self.assertEqual(self.harness.ready_calls, [(target, 2)])
        self.assertTrue(Path(target).is_file())
        self.assertEqual(self._export_counts(), {first_id: 1, second_id: 1})

    def test_reexporting_prompts_and_excluded_rows_are_left_out_and_not_remarked(self):
        first_id = self._save_customer(owner_name="王小明")
        second_id = self._save_customer(owner_name="陳小華")
        rows = [_row(first_id, owner_name="王小明"), _row(second_id, owner_name="陳小華")]
        self.repository.mark_customers_exported_to_excel([first_id, second_id])

        def fake_exec(dialog_self):
            for index in range(dialog_self.list_widget.count()):
                item = dialog_self.list_widget.item(index)
                if item.data(Qt.UserRole) == first_id:
                    item.setCheckState(Qt.Checked)
            return QDialog.Accepted

        target = str(self.root / "export2.xlsx")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")):
            with patch.object(PreviousExportDuplicatesDialog, "exec", fake_exec):
                self.harness.export_rows_to_xlsx(rows)

        # Only the second customer (陳小華) actually got exported this time.
        self.assertEqual(self.harness.ready_calls, [(target, 1)])
        # First customer was excluded -- untouched at its original count;
        # second customer was exported again -- count bumped to 2.
        self.assertEqual(self._export_counts(), {first_id: 1, second_id: 2})

    def test_leaving_everything_unchecked_exports_all_rows_again(self):
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        self.repository.mark_customers_exported_to_excel([customer_id])

        target = str(self.root / "export3.xlsx")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")):
            with patch.object(
                PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Accepted
            ):
                self.harness.export_rows_to_xlsx(rows)

        self.assertEqual(self.harness.ready_calls, [(target, 1)])
        self.assertEqual(self._export_counts(), {customer_id: 2})

    def test_cancelling_the_duplicate_dialog_aborts_the_whole_export(self):
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        self.repository.mark_customers_exported_to_excel([customer_id])

        with patch.object(QFileDialog, "getSaveFileName") as mocked_save_dialog:
            with patch.object(
                PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Rejected
            ):
                self.harness.export_rows_to_xlsx(rows)
            mocked_save_dialog.assert_not_called()
        self.assertEqual(self.harness.ready_calls, [])
        self.assertEqual(self._export_counts(), {customer_id: 1})

    def test_excluding_every_row_shows_a_message_and_exports_nothing(self):
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        self.repository.mark_customers_exported_to_excel([customer_id])

        def fake_exec(dialog_self):
            dialog_self.list_widget.item(0).setCheckState(Qt.Checked)
            return QDialog.Accepted

        with patch.object(QFileDialog, "getSaveFileName") as mocked_save_dialog:
            with patch.object(PreviousExportDuplicatesDialog, "exec", fake_exec):
                with patch("customer_export_controller.QMessageBox") as mocked_message_box:
                    self.harness.export_rows_to_xlsx(rows)
                    mocked_message_box.information.assert_called_once()
            mocked_save_dialog.assert_not_called()
        self.assertEqual(self.harness.ready_calls, [])
        self.assertEqual(self._export_counts(), {customer_id: 1})

    def test_repository_marks_and_lists_previously_exported_ids(self):
        first_id = self._save_customer(owner_name="王小明")
        second_id = self._save_customer(owner_name="陳小華")

        self.assertEqual(
            self.repository.list_previously_exported_customer_ids([first_id, second_id]),
            set(),
        )
        self.repository.mark_customers_exported_to_excel([first_id])
        self.assertEqual(
            self.repository.list_previously_exported_customer_ids([first_id, second_id]),
            {first_id},
        )
        self.repository.mark_customers_exported_to_excel([first_id, second_id])
        self.assertEqual(
            self.repository.list_previously_exported_customer_ids([first_id, second_id]),
            {first_id, second_id},
        )
        self.assertEqual(self._export_counts(), {first_id: 2, second_id: 1})

    def test_lookup_failure_is_logged_and_does_not_block_the_export(self):
        # Regression test: a real user reported the duplicate-export
        # prompt never appearing at all, even for genuinely re-exported
        # data, with the underlying API round-trip separately confirmed
        # to work correctly -- meaning some failure in
        # list_previously_exported_customer_ids() was being silently
        # swallowed. That failure must now be logged via
        # customer_error_handler.log_diagnostic_event() so it is
        # attributable instead of indistinguishable from "nothing was
        # exported before".
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        target = str(self.root / "export-lookup-failure.xlsx")

        with (
            patch.object(
                self.repository,
                "list_previously_exported_customer_ids",
                side_effect=RuntimeError("simulated lookup failure"),
            ),
            patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")),
            patch("customer_error_handler.log_diagnostic_event") as mocked_log,
        ):
            self.harness.export_rows_to_xlsx(rows)

        # The export must still proceed rather than being blocked by the
        # lookup failure.
        self.assertEqual(self.harness.ready_calls, [(target, 1)])
        # log_diagnostic_event() now also fires unconditionally (not just
        # on failure) around this same check and the later mark step, so
        # more than one call is expected here -- find the specific
        # lookup-failure entry among them instead of assuming it is the
        # only one.
        failure_calls = [
            call
            for call in mocked_log.call_args_list
            if call.args[0] == "ExportControllerMixin.list_previously_exported_customer_ids"
            and "lookup failed" in call.args[1]
        ]
        self.assertEqual(len(failure_calls), 1)

    def test_marking_failure_is_logged_and_does_not_hide_export_success(self):
        customer_id = self._save_customer(owner_name="王小明")
        rows = [_row(customer_id, owner_name="王小明")]
        target = str(self.root / "export-mark-failure.xlsx")

        with (
            patch.object(
                self.repository,
                "mark_customers_exported_to_excel",
                side_effect=RuntimeError("simulated marking failure"),
            ),
            patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")),
            patch("customer_error_handler.log_diagnostic_event") as mocked_log,
        ):
            self.harness.export_rows_to_xlsx(rows)

        # The export itself must be reported as successful even though
        # the bookkeeping write failed.
        self.assertEqual(self.harness.ready_calls, [(target, 1)])
        # log_diagnostic_event() now also fires unconditionally (not just
        # on failure) around this same mark step and the earlier lookup,
        # so more than one call is expected here -- find the specific
        # marking-failure entry among them instead of assuming it is the
        # only one.
        failure_calls = [
            call
            for call in mocked_log.call_args_list
            if call.args[0] == "ExportControllerMixin.mark_customers_exported_to_excel"
            and "marking failed" in call.args[1]
        ]
        self.assertEqual(len(failure_calls), 1)
        # And the failed write genuinely left no trace -- next time this
        # customer is exported, it should still be treated as new.
        self.assertEqual(
            self.repository.list_previously_exported_customer_ids([customer_id]), set()
        )

    def test_select_all_and_clear_all_buttons_toggle_every_checkbox(self):
        rows = [
            _row(1, owner_name="王小明"),
            _row(2, owner_name="陳小華"),
            _row(3, owner_name="林先生"),
        ]
        dialog = PreviousExportDuplicatesDialog(rows)
        try:
            self.assertEqual(dialog.excluded_ids(), set())

            dialog._check_all()
            self.assertEqual(dialog.excluded_ids(), {1, 2, 3})

            dialog._uncheck_all()
            self.assertEqual(dialog.excluded_ids(), set())
        finally:
            dialog.close()


class MailDuplicateTagTests(unittest.TestCase):
    """Tests for the "設定寄信重複偵測標籤" workflow. User request: 匯出
    「選取資料」前，自動偵測已經有某個使用者自選標籤（例如「已寄信」）的
    地主並提示排除 -- separate from, and much simpler than, the Excel
    export-history tracking: which tag to watch is a local preference,
    and matching a tag is just inspecting data already loaded with each
    row, not a new database table or a new round trip to the server.

    Originally wired to "匯出選取 Word" (信封/寄信名單常用的匯出方式);
    moved to "匯出選取資料" per explicit follow-up user request, once
    they confirmed their actual mailing workflow exports through Excel
    instead."""

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.database = CustomerDatabase(self.root / "customers.db", self.root / "backups")
        project_root = Path(__file__).resolve().parents[1]
        self.repository = CustomerRepository(
            self.database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            LAND_FIELDS,
        )
        self.repository.init_db()
        self.harness = _ExportWorkflowHarness(self.repository)

    def tearDown(self):
        self.temp_context.cleanup()

    def test_configure_mail_duplicate_tag_warns_when_no_tags_exist(self):
        with patch("customer_export_controller.QMessageBox") as mocked_message_box:
            self.harness.configure_mail_duplicate_tag()
            mocked_message_box.information.assert_called_once()
        self.assertIsNone(load_mail_duplicate_tag(self.repository))

    def test_configure_mail_duplicate_tag_saves_the_chosen_tag(self):
        self.repository.save_tag("已寄信", "#FBBF24")
        self.repository.save_tag("VIP", "#111111")

        with patch.object(QInputDialog, "getItem", return_value=("已寄信", True)):
            self.harness.configure_mail_duplicate_tag()
        self.assertEqual(load_mail_duplicate_tag(self.repository), "已寄信")
        self.assertEqual(
            self.repository.get_setting(MAIL_DUPLICATE_TAG_SETTING), "已寄信"
        )

    def test_configure_mail_duplicate_tag_can_be_cleared(self):
        self.repository.save_tag("已寄信", "#FBBF24")
        with patch.object(QInputDialog, "getItem", return_value=("已寄信", True)):
            self.harness.configure_mail_duplicate_tag()
        self.assertEqual(load_mail_duplicate_tag(self.repository), "已寄信")

        with patch.object(QInputDialog, "getItem", return_value=("（不偵測）", True)):
            self.harness.configure_mail_duplicate_tag()
        self.assertIsNone(load_mail_duplicate_tag(self.repository))

    def test_configure_mail_duplicate_tag_declined_leaves_setting_untouched(self):
        self.repository.save_tag("已寄信", "#FBBF24")
        with patch.object(QInputDialog, "getItem", return_value=("已寄信", False)):
            self.harness.configure_mail_duplicate_tag()
        self.assertIsNone(load_mail_duplicate_tag(self.repository))

    def test_exclude_with_no_tag_configured_returns_rows_unchanged(self):
        rows = [_row(1, owner_name="王小明", tag_items=[{"name": "已寄信", "tag_id": 1}])]
        self.assertIsNone(load_mail_duplicate_tag(self.repository))
        result = self.harness._exclude_rows_with_mail_duplicate_tag(rows)
        self.assertEqual(result, rows)

    def test_exclude_with_no_matching_rows_returns_rows_unchanged_without_prompting(self):
        self.repository.save_tag("已寄信", "#FBBF24")
        save_mail_duplicate_tag(self.repository, "已寄信")
        rows = [_row(1, owner_name="王小明", tag_items=[{"name": "VIP", "tag_id": 2}])]
        with patch.object(PreviousExportDuplicatesDialog, "exec") as mocked_exec:
            result = self.harness._exclude_rows_with_mail_duplicate_tag(rows)
            mocked_exec.assert_not_called()
        self.assertEqual(result, rows)

    def test_exclude_prompts_and_excludes_only_checked_tagged_rows(self):
        save_mail_duplicate_tag(self.repository, "已寄信")
        rows = [
            _row(1, owner_name="王小明", tag_items=[{"name": "已寄信", "tag_id": 1}]),
            _row(2, owner_name="陳小華", tag_items=[]),
            _row(3, owner_name="林先生", tag_items=[{"name": "已寄信", "tag_id": 1}]),
        ]

        def fake_exec(dialog_self):
            self.assertEqual(dialog_self.list_widget.count(), 2)
            for index in range(dialog_self.list_widget.count()):
                item = dialog_self.list_widget.item(index)
                if item.data(Qt.UserRole) == 1:
                    item.setCheckState(Qt.Checked)
            return QDialog.Accepted

        with patch.object(PreviousExportDuplicatesDialog, "exec", fake_exec):
            result = self.harness._exclude_rows_with_mail_duplicate_tag(rows)

        self.assertEqual({row["id"] for row in result}, {2, 3})

    def test_exclude_detects_the_same_owner_tagged_under_a_different_land_parcel(self):
        # User request: "同一位地主當過去已經寡過信（不同地號/持分，只要
        # 同一個人就算）" -- a real owner often has several ownership
        # records under different land parcels; tagging any one of them
        # must still be caught when a *different* parcel for the same
        # person is exported later.
        tag_id = self.repository.save_tag("已寄信", "#FBBF24")
        tagged_id = self.repository.save_customer(
            _land_record(
                land_number="100", owner_name="王小明", external_id="A123456789",
                address="桃園市桃園區泰成路1號",
            )
        )
        self.repository.set_customer_tags(tagged_id, [tag_id])
        save_mail_duplicate_tag(self.repository, "已寄信")

        other_parcel_row = _row(
            9999, owner_name="王小明", external_id="A123456789", address="不同地址",
            tag_items=[],
        )
        with patch.object(
            PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Rejected
        ) as mocked_exec:
            result = self.harness._exclude_rows_with_mail_duplicate_tag([other_parcel_row])
            mocked_exec.assert_called_once()
        self.assertIsNone(result)

    def test_exclude_detects_the_same_address_tagged_under_a_different_owner(self):
        # User request: "同一地址寡過（避免同一個信箱重複收到兩封）" --
        # two different owners (e.g. co-residents) sharing one mailing
        # address must not each get a separate letter.
        tag_id = self.repository.save_tag("已寄信", "#FBBF24")
        tagged_id = self.repository.save_customer(
            _land_record(
                land_number="100", owner_name="王小明", external_id="A111111111",
                address="桃園市桃園區泰成路1號",
            )
        )
        self.repository.set_customer_tags(tagged_id, [tag_id])
        save_mail_duplicate_tag(self.repository, "已寄信")

        co_resident_row = _row(
            9999, owner_name="王小華", external_id="B222222222",
            address="桃園市桃園區泰成路1號", tag_items=[],
        )
        with patch.object(
            PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Rejected
        ) as mocked_exec:
            result = self.harness._exclude_rows_with_mail_duplicate_tag([co_resident_row])
            mocked_exec.assert_called_once()
        self.assertIsNone(result)

    def test_exclude_does_not_flag_an_unrelated_customer(self):
        tag_id = self.repository.save_tag("已寄信", "#FBBF24")
        tagged_id = self.repository.save_customer(
            _land_record(
                land_number="100", owner_name="王小明", external_id="A111111111",
                address="桃園市桃園區泰成路1號",
            )
        )
        self.repository.set_customer_tags(tagged_id, [tag_id])
        save_mail_duplicate_tag(self.repository, "已寄信")

        unrelated_row = _row(
            9999, owner_name="陳小華", external_id="C333333333",
            address="台北市中正區忠孝東路100號", tag_items=[],
        )
        with patch.object(PreviousExportDuplicatesDialog, "exec") as mocked_exec:
            result = self.harness._exclude_rows_with_mail_duplicate_tag([unrelated_row])
            mocked_exec.assert_not_called()
        self.assertEqual(result, [unrelated_row])

    def test_exclude_cancelling_the_dialog_aborts_the_whole_export(self):
        save_mail_duplicate_tag(self.repository, "已寄信")
        rows = [_row(1, owner_name="王小明", tag_items=[{"name": "已寄信", "tag_id": 1}])]

        with patch.object(
            PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Rejected
        ):
            result = self.harness._exclude_rows_with_mail_duplicate_tag(rows)
        self.assertIsNone(result)

    def test_export_selected_data_runs_the_mail_duplicate_tag_check(self):
        # Moved from export_selected_word() to export_rows_to_xlsx() per
        # explicit user request: their real mailing workflow exports
        # through "匯出選取資料" (Excel), not Word, so the check needs to
        # run here to actually catch anything.
        save_mail_duplicate_tag(self.repository, "已寄信")
        customer_id = self.repository.save_customer(_land_record(owner_name="王小明"))
        row = _row(
            customer_id, owner_name="王小明",
            tag_items=[{"name": "已寄信", "tag_id": 1}],
        )

        with patch.object(
            PreviousExportDuplicatesDialog, "exec", return_value=QDialog.Rejected
        ) as mocked_exec:
            result = self.harness.export_rows_to_xlsx([row])

        mocked_exec.assert_called_once()
        self.assertIsNone(result)

    def test_export_selected_word_no_longer_runs_the_mail_duplicate_tag_check(self):
        save_mail_duplicate_tag(self.repository, "已寄信")
        customer_id = self.repository.save_customer(_land_record(owner_name="王小明"))
        row = _row(
            customer_id, owner_name="王小明",
            tag_items=[{"name": "已寄信", "tag_id": 1}],
        )
        self.harness.selected_or_checked_rows = lambda: [row]
        target = str(self.root / "export-word-no-tag-check.docx")

        with (
            patch.object(PreviousExportDuplicatesDialog, "exec") as mocked_exec,
            patch("customer_export_controller.write_records_docx", return_value=1),
            patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")),
            patch("customer_export_controller.QMessageBox"),
        ):
            self.harness.export_selected_word()

        mocked_exec.assert_not_called()

    def test_mail_duplicate_tag_setting_is_local_not_tied_to_record_repository(self):
        # Mirrors the Google API key lesson (see load_mail_duplicate_tag's
        # own docstring): this must be readable/writable through
        # self.repository directly, never through active_record_repository()
        # -- which in API mode is a DesktopApiRecordRepository that has no
        # generic settings storage at all.
        save_mail_duplicate_tag(self.repository, "已寄信")
        self.assertEqual(
            self.repository.get_setting(MAIL_DUPLICATE_TAG_SETTING), "已寄信"
        )


if __name__ == "__main__":
    unittest.main()
