import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import customer_ui_qt as app
from customer_dialogs import (
    AdvancedSearchDialog,
    BatchEditDialog,
    ChangePasswordDialog,
    ColumnVisibilityDialog,
    DataQualityDialog,
    DataQualityRulesDialog,
    DashboardDialog,
    FontSizeDialog,
    FollowUpListDialog,
    FollowUpReminderDialog,
    HelpDialog,
    ImportPreviewDialog,
    RecordHistoryDialog,
    SavedSearchDialog,
    SharedLandBatchDialog,
    VisitCalendarDialog,
)
from customer_extra_dialogs import (
    ApplyTemplateDialog,
    AttachmentDialog,
    BatchCustomerCustomValuesDialog,
    BatchCustomerTagsDialog,
    CaseSelectDialog,
    ContactLogDialog,
    CustomFieldManagementDialog,
    CustomerCustomValuesDialog,
    CustomerTagsDialog,
    FieldVisitScheduleDialog,
    HealthCheckDialog,
    MergeRecordsDialog,
    TagManagementDialog,
    TextTemplateDialog,
)
from customer_models import RecordTableModel
from customer_responsive_dialog import ResponsiveDialog
from customer_word import write_records_docx


class UiComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_table_model_displays_and_updates_checked_state(self):
        changes = []
        model = RecordTableModel(lambda record_id, checked: changes.append((record_id, checked)))
        row = {
            "id": 7,
            "checked": False,
            "is_watchlist": False,
            "has_note": False,
            "background": None,
            "highlighted_fields": set(),
            "display": {key: "" for key, _label in app.TABLE_COLUMNS},
        }
        model.set_rows([row])

        checked_index = model.index(0, 0)
        self.assertEqual(model.rowCount(), 1)
        self.assertTrue(model.setData(checked_index, Qt.Checked, Qt.CheckStateRole))
        self.assertEqual(changes, [(7, True)])
        self.assertEqual(model.data(checked_index, Qt.CheckStateRole), Qt.Checked)

    def test_table_model_aligns_requested_columns(self):
        model = RecordTableModel(lambda _record_id, _checked: None)
        row = {
            "id": 7,
            "checked": False,
            "is_watchlist": False,
            "has_note": False,
            "background": None,
            "highlighted_fields": set(),
            "display": {key: "測試" for key, _label in app.TABLE_COLUMNS},
        }
        model.set_rows([row])
        column_indexes = {
            key: index for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
        }

        centered = {
            "district", "section", "registration_order", "land_number", "area",
            "numerator", "denominator", "ping", "owner_name", "external_id",
            "address", "registration_reason",
        }
        for key in centered:
            alignment = model.data(
                model.index(0, column_indexes[key]), Qt.TextAlignmentRole
            )
            self.assertEqual(alignment, int(Qt.AlignCenter), key)

        for key in {"declared_value", "total_declared_value"}:
            alignment = model.data(
                model.index(0, column_indexes[key]), Qt.TextAlignmentRole
            )
            self.assertEqual(alignment, int(Qt.AlignVCenter | Qt.AlignRight), key)

    def test_tag_column_keeps_semantic_row_background_and_exposes_tag_roles(self):
        model = RecordTableModel(lambda _record_id, _checked: None)
        display = {key: "" for key, _label in app.TABLE_COLUMNS}
        display.update({"note": "有備註", "tag_names": "優先"})
        model.set_rows(
            [
                {
                    "id": 7,
                    "checked": False,
                    "is_watchlist": False,
                    "has_note": True,
                    "background": QColor("#564113"),
                    "tag_color": "#ff0000",
                    "tags": [
                        {"tag_id": 3, "name": "優先", "color": "#ff0000"}
                    ],
                    "highlighted_fields": set(),
                    "display": display,
                }
            ]
        )
        column_indexes = {
            key: index for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
        }
        note_index = model.index(0, column_indexes["note"])
        tag_index = model.index(0, column_indexes["tag_names"])

        self.assertEqual(model.data(note_index, Qt.BackgroundRole), QColor("#564113"))
        self.assertEqual(model.data(tag_index, Qt.BackgroundRole), QColor("#564113"))
        self.assertEqual(model.data(tag_index, Qt.ForegroundRole), QColor("#f8fafc"))
        self.assertEqual(
            model.data(tag_index, Qt.UserRole + 3),
            [{"tag_id": 3, "name": "優先", "color": "#FF0000"}],
        )
        self.assertFalse(model.data(tag_index, Qt.DecorationRole).isNull())

    def test_table_model_loads_database_pages_on_demand(self):
        model = RecordTableModel(lambda _record_id, _checked: None)
        model.batch_size = 2
        source = [
            {
                "id": record_id,
                "checked": False,
                "display": {key: "" for key, _label in app.TABLE_COLUMNS},
            }
            for record_id in range(1, 6)
        ]
        calls = []

        def load_page(offset, limit):
            calls.append((offset, limit))
            return source[offset : offset + limit]

        model.set_paged_rows(source[:2], len(source), load_page)
        self.assertEqual(model.rowCount(), 2)
        self.assertTrue(model.canFetchMore())
        self.assertEqual(model.row_for_record_id(5), 4)
        self.assertEqual(model.rowCount(), 5)
        self.assertEqual(calls, [(2, 2), (4, 2)])
        self.assertEqual(model.load_all(), source)

    def test_core_dialogs_construct_with_existing_configuration(self):
        dialogs = [
            ChangePasswordDialog(),
            FontSizeDialog("medium"),
            ColumnVisibilityDialog(app.TABLE_COLUMNS[1:], {"address"}),
            AdvancedSearchDialog({"district": "中正區"}),
            ImportPreviewDialog(
                [{"district": "中正區", "_duplicate_reason": ""}],
                [("district", "地區")],
                set(),
            ),
            BatchEditDialog(2),
            SharedLandBatchDialog(
                {
                    "district": "中正區",
                    "section": "一段",
                    "subsection": "",
                    "land_number": "100",
                    "area": "120",
                    "declared_value": "20,000",
                }
            ),
            SavedSearchDialog([]),
            HelpDialog(),
            DataQualityRulesDialog(["land_number_missing"]),
            DataQualityDialog([], total_records=0),
        ]

        self.assertEqual(dialogs[1].selected_font_size_key(), "medium")
        self.assertIn("address", dialogs[2].hidden_keys())
        self.assertEqual(dialogs[3].criteria()["district"], "中正區")
        shared_values, _rows_text = dialogs[6].values()
        self.assertEqual(shared_values["land_number"], "100")
        self.assertEqual(shared_values["area"], "120")
        self.assertEqual(shared_values["declared_value"], "20,000")
        self.assertGreaterEqual(dialogs[8].tabs.count(), 6)
        self.assertIn("批量新增", dialogs[8].tabs.tabText(1))
        self.assertEqual(dialogs[9].selected_rules(), ["land_number_missing"])
        self.assertEqual(dialogs[10].table.rowCount(), 0)
        for dialog in dialogs:
            dialog.close()

    def test_long_dialogs_scroll_and_fit_inside_small_screen(self):
        screen_geometry = QRect(100, 50, 800, 600)
        base_dialog = ResponsiveDialog()
        base_dialog.resize(1400, 1000)
        base_dialog.fit_to_available_screen(screen_geometry)
        self.assertLessEqual(base_dialog.width(), int(screen_geometry.width() * 0.94))
        self.assertLessEqual(base_dialog.height(), int(screen_geometry.height() * 0.90))

        dialogs = [
            AdvancedSearchDialog({"district": "中正區"}),
            ColumnVisibilityDialog(app.TABLE_COLUMNS[1:], {"address"}),
        ]
        try:
            for dialog in dialogs:
                dialog.resize(360, 260)
                dialog.show()
                self.application.processEvents()
                self.assertTrue(dialog.scroll_area.widgetResizable())
                self.assertGreater(dialog.scroll_area.verticalScrollBar().maximum(), 0)
                self.assertLessEqual(dialog.height(), int(self.application.primaryScreen().availableGeometry().height() * 0.90))
        finally:
            base_dialog.close()
            for dialog in dialogs:
                dialog.close()

    def test_advanced_search_accepts_multiple_fields_and_enter_moves_forward(self):
        dialog = AdvancedSearchDialog({})
        try:
            dialog.show()
            district = dialog.inputs["district"]
            section = dialog.inputs["section"]
            district.setText("中壢區")
            district.setFocus()
            self.application.processEvents()

            QTest.keyClick(district, Qt.Key_Return)
            self.application.processEvents()

            self.assertTrue(dialog.isVisible())
            self.assertTrue(section.hasFocus())
            section.setText("中路、中路段")
            dialog.inputs["land_number"].setText("382-2")
            self.assertIn("、", section.placeholderText())
            self.assertEqual(
                dialog.criteria(),
                {
                    "district": "中壢區",
                    "section": "中路、中路段",
                    "land_number": "382-2",
                },
            )
        finally:
            dialog.close()

    def test_help_dialog_contains_batch_add_examples(self):
        dialog = HelpDialog()
        try:
            self.assertEqual(dialog.windowTitle(), "使用說明")
            tab_titles = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
            self.assertIn("批量新增", tab_titles)

            batch_tab = dialog.tabs.widget(tab_titles.index("批量新增"))
            text = batch_tab.toPlainText()
            self.assertIn("15、王弘益、H100059743", text)
            self.assertIn("身分證可以空白", text)
            self.assertIn("登記次序、姓名、身分證、地址、分子、分母", text)

            backup_tab = dialog.tabs.widget(tab_titles.index("備份與還原"))
            backup_text = backup_tab.toPlainText()
            self.assertIn("備份管理", backup_text)
            self.assertIn(".zip", backup_text)
        finally:
            dialog.close()

    def test_data_quality_rules_dialog_selects_rules(self):
        dialog = DataQualityRulesDialog(["land_number_missing", "denominator_zero"])
        try:
            self.assertEqual(dialog.windowTitle(), "選擇資料品質檢查項目")
            self.assertEqual(dialog.selected_rules(), ["land_number_missing", "denominator_zero"])
            self.assertEqual(dialog.selected_preset_key(), "custom")
            dialog.clear_all()
            self.assertEqual(dialog.selected_rules(), [])
            dialog.select_all()
            self.assertIn("duplicate", dialog.selected_rules())
            self.assertEqual(dialog.selected_preset_key(), "complete")
        finally:
            dialog.close()

    def test_data_quality_rules_dialog_applies_presets(self):
        dialog = DataQualityRulesDialog([])
        try:
            duplicate_index = dialog.preset_combo.findData("duplicate")
            self.assertGreaterEqual(duplicate_index, 0)
            dialog.preset_combo.setCurrentIndex(duplicate_index)
            self.assertEqual(dialog.selected_rules(), ["duplicate"])
            self.assertEqual(dialog.selected_preset_key(), "duplicate")

            numeric_index = dialog.preset_combo.findData("numeric")
            dialog.preset_combo.setCurrentIndex(numeric_index)
            self.assertEqual(dialog.selected_rules(), ["numeric_format", "denominator_zero"])
            self.assertEqual(dialog.selected_preset_key(), "numeric")

            dialog.rule_checkboxes["owner_name_missing"].setChecked(True)
            self.assertEqual(dialog.selected_preset_key(), "custom")
        finally:
            dialog.close()

    def test_new_management_dialogs_construct(self):
        dialogs = [
            DashboardDialog(
                {
                    "total_records": 2,
                    "total_area": "100",
                    "total_declared_value": "20,000",
                    "total_current_value": "2,000,000",
                    "open_follow_ups": 1,
                    "with_external_id": 1,
                    "without_external_id": 1,
                    "with_note": 1,
                    "with_visit_log": 1,
                    "district_counts": [("桃園區", 2)],
                    "section_counts": [("一段", 2)],
                    "follow_up_status_counts": [("待回覆", 1)],
                }
            ),
            RecordHistoryDialog(
                [
                    {
                        "created_at": "2026-07-13",
                        "action_type": "修改資料",
                        "field_label": "地號",
                        "old_value": "100",
                        "new_value": "101",
                        "customer_id": 7,
                    }
                ],
                "ID 7 / 桃園區 / 一段 / 101",
            ),
            FollowUpReminderDialog(
                "ID 7 / 桃園區 / 一段 / 101",
                {"due_date": "2026-07-20", "status": "待回覆", "note": "再聯絡"},
            ),
            FollowUpListDialog(
                [
                    {
                        "customer_id": 7,
                        "due_date": "2026-07-20",
                        "status": "待回覆",
                        "owner_name": "王小明",
                        "district": "桃園區",
                        "section": "一段",
                        "subsection": "",
                        "land_number": "101",
                        "note": "再聯絡",
                    }
                ]
            ),
        ]

        class StubVisitCalendarWindow:
            def load_visit_calendar_items(self, start_date, end_date, mine_only=False):
                del start_date, end_date, mine_only
                return [
                    {
                        "customer_id": 7,
                        "date": QDate.currentDate().toString("yyyy-MM-dd"),
                        "calendar_status": "completed",
                        "owner_name": "王小明",
                        "district": "桃園區",
                        "section": "一段",
                        "subsection": "",
                        "land_number": "101",
                    }
                ]

        dialogs.append(VisitCalendarDialog(StubVisitCalendarWindow()))
        try:
            self.assertEqual(dialogs[0].table.rowCount(), 12)
            self.assertEqual(dialogs[1].table.item(0, 2).text(), "地號")
            self.assertEqual(dialogs[2].values()["status"], "待回覆")
            self.assertEqual(dialogs[3].table.item(0, 2).text(), "王小明")
            self.assertEqual(dialogs[4].table.item(0, 0).text(), "王小明")
            self.assertEqual(dialogs[4].table.item(0, 5).text(), "已完成")
        finally:
            for dialog in dialogs:
                dialog.close()

    def test_extra_management_dialogs_and_word_export_construct(self):
        cases = [{"id": 1, "title": "Case A", "status": "進行中", "note": "note", "customer_count": 2}]
        tags = [{"id": 2, "name": "Important", "color": "#ffcc00", "customer_count": 1}]
        fields = [{"id": 3, "field_key": "extra", "label": "Extra"}]
        templates = [{"id": 4, "template_type": "note", "title": "Note", "content": "Call back"}]
        opened_attachments = []
        dialogs = [
            # The old standalone CaseManagementDialog was unified into
            # WorkflowDialog ("案件規劃", see customer_productivity.py) --
            # a repository-backed, tabbed dialog no longer constructible
            # from a plain in-memory case list like the fakes here, so
            # it is no longer part of this shared-fixture smoke test.
            CaseSelectDialog(cases, 2),
            FieldVisitScheduleDialog(3),
            TagManagementDialog(tags),
            CustomerTagsDialog(tags, {2}, "ID 1"),
            AttachmentDialog(
                [{
                    "id": 5,
                    "file_path": "C:/server/attachments/5/a.pdf",
                    "original_name": "a.pdf",
                    "description": "contract",
                    "status": "managed",
                    "created_at": "2026-07-13",
                }],
                "ID 1",
                open_attachment=lambda attachment: opened_attachments.append(
                    int(attachment["id"])
                ),
            ),
            CustomFieldManagementDialog(fields),
            CustomerCustomValuesDialog(fields, {3: "value"}, "ID 1"),
            TextTemplateDialog(templates),
            ApplyTemplateDialog(templates),
            ContactLogDialog(
                [
                    {
                        "id": 6,
                        "contact_date": "2026-07-13",
                        "method": "phone",
                        "result": "ok",
                        "next_follow_up": "2026-07-20",
                        "note": "note",
                    }
                ],
                "ID 1",
            ),
            MergeRecordsDialog("ID 1", "ID 2", ["owner: A -> B"]),
            HealthCheckDialog([{"status": "OK", "title": "Database", "detail": "ok"}]),
            BatchCustomerTagsDialog(tags, 2),
            BatchCustomerCustomValuesDialog(fields, 2),
        ]
        try:
            self.assertEqual(dialogs[0].selected_case_id(), 1)
            self.assertEqual(dialogs[1].title(), "今日拜訪行程")
            self.assertRegex(dialogs[1].selected_date(), r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(dialogs[1].priority(), 0)
            dialogs[1].priority_checkbox.setChecked(True)
            self.assertEqual(dialogs[1].priority(), 100)
            self.assertEqual(dialogs[3].selected_ids(), [2])
            dialogs[4].table.selectRow(0)
            dialogs[4].open_selected_file()
            self.assertEqual(opened_attachments, [5])
            self.assertEqual(dialogs[4].table.item(0, 1).text(), "a.pdf")
            self.assertEqual(dialogs[6].result_values()[3], "value")
            self.assertEqual(dialogs[8].values()["template"]["title"], "Note")
            self.assertEqual(dialogs[11].table.rowCount(), 1)
            dialogs[12].list_widget.item(0).setCheckState(Qt.Checked)
            self.assertEqual(dialogs[12].selected_ids(), [2])
            checkbox, edit = dialogs[13].rows[3]
            checkbox.setChecked(True)
            edit.setText("batch value")
            self.assertEqual(dialogs[13].result_values(), {3: "batch value"})
        finally:
            for dialog in dialogs:
                dialog.close()

    def test_tag_management_dialog_separates_create_and_edit_modes(self):
        tags = [
            {
                "id": 2,
                "name": "標籤 A",
                "color": "#FF0000",
                "customer_count": 0,
            }
        ]
        create_dialog = TagManagementDialog(tags)
        edit_dialog = TagManagementDialog(tags)
        try:
            self.assertFalse(create_dialog.edit_mode)
            self.assertIsNone(create_dialog.current_tag_id)
            self.assertIsNone(create_dialog.selected_tag)
            self.assertIsNone(create_dialog.values()["tag_id"])

            create_dialog.table.selectRow(0)
            QApplication.processEvents()
            self.assertTrue(create_dialog.edit_mode)
            self.assertEqual(create_dialog.current_tag_id, 2)
            self.assertEqual(create_dialog.selected_tag["name"], "標籤 A")

            create_dialog.begin_new_tag()
            self.assertFalse(create_dialog.edit_mode)
            self.assertIsNone(create_dialog.current_tag_id)
            self.assertIsNone(create_dialog.selected_tag)
            self.assertFalse(create_dialog.table.selectionModel().hasSelection())
            self.assertEqual(create_dialog.name_edit.text(), "")
            self.assertEqual(create_dialog.color_edit.text(), "")

            create_dialog.name_edit.setText("標籤 B")
            create_dialog.color_edit.setText("#00FF00")
            create_dialog.request_save()
            self.assertEqual(create_dialog.action, "create")
            self.assertEqual(
                create_dialog.values(),
                {"tag_id": None, "name": "標籤 B", "color": "#00FF00"},
            )

            edit_dialog.table.selectRow(0)
            QApplication.processEvents()
            edit_dialog.name_edit.setText("標籤 A（更新）")
            edit_dialog.request_save()
            self.assertEqual(edit_dialog.action, "update")
            self.assertEqual(edit_dialog.values()["tag_id"], 2)
        finally:
            create_dialog.close()
            edit_dialog.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "records.docx")
            row_count = write_records_docx(
                output_path,
                [{"owner_name": "Owner", "land_number": "100"}],
                [("owner_name", "姓名"), ("land_number", "地號")],
            )
            self.assertEqual(row_count, 1)
            import zipfile

            with zipfile.ZipFile(output_path) as archive:
                self.assertIn("word/document.xml", archive.namelist())
                xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("Owner", xml)
            self.assertIn("地號", xml)

    # test_case_management_new_mode_does_not_reuse_selected_case_id used to
    # live here, covering CaseManagementDialog's new-vs-edit toggle. That
    # dialog was unified into the repository-backed WorkflowDialog
    # ("案件規劃", see customer_productivity.py), which uses a different
    # internal widget layout; this coverage was lost to an accidental
    # `git checkout` on this file (see MEMORY/session notes) and has not
    # been rewritten against WorkflowDialog's actual API yet.

    def test_import_preview_dialog_update_existing_mode(self):
        dialog = ImportPreviewDialog(
            [{"district": "中正區", "_duplicate_reason": "資料庫已存在"}],
            [("district", "地區")],
            {0},
        )
        try:
            dialog.import_update_duplicates()
            self.assertEqual(dialog.import_mode, "update_duplicates")
            self.assertEqual(dialog.result(), QDialog.Accepted)
        finally:
            dialog.close()

    def test_data_quality_dialog_lists_issues(self):
        from customer_quality import DataQualityIssue

        activated = []
        ignored = []
        cleared_ignored = []
        dialog = DataQualityDialog(
            [
                DataQualityIssue(
                    record_id=7,
                    severity="重要",
                    category="分母為 0",
                    summary="#7 桃園市 / 一段 / 100：分母不可為 0",
                    suggestion="請修正分母。",
                ),
                DataQualityIssue(
                    record_id=8,
                    severity="提醒",
                    category="疑似重複",
                    summary="#8 桃園市 / 一段 / 100：疑似重複",
                    suggestion="請確認是否重複建檔。",
                )
            ],
            total_records=2,
            on_issue_activated=lambda record_id: activated.append(record_id),
            on_issue_ignored=lambda issue: ignored.append(issue.record_id),
            ignored_count=1,
            on_clear_ignored=lambda: cleared_ignored.append(True),
        )
        try:
            self.assertEqual(dialog.windowTitle(), "資料品質檢查")
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 2).text(), "分母為 0")
            self.assertEqual(dialog.category_summary_table.rowCount(), 2)
            self.assertEqual(dialog.category_summary_table.item(0, 0).text(), "分母為 0")
            self.assertEqual(dialog.category_summary_table.item(0, 1).text(), "1")
            self.assertEqual(dialog.category_summary_table.item(0, 3).text(), "1")
            self.assertEqual(len(dialog.summary_rows()), 3)
            self.assertEqual(dialog.summary_rows()[-1]["category"], "已確認隱藏")
            self.assertEqual(dialog.summary_rows()[-1]["total"], 1)

            with patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok):
                dialog.copy_summary()
            summary_text = QApplication.clipboard().text()
            self.assertIn("類型\t重要\t提醒\t合計", summary_text)
            self.assertIn("分母為 0\t1\t0\t1", summary_text)
            self.assertIn("已確認隱藏\t\t\t1", summary_text)

            with (
                patch("customer_dialogs.QFileDialog.getSaveFileName", return_value=("C:/tmp/quality-summary", "")),
                patch("customer_dialogs.write_quality_summary") as write_summary,
                patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok),
            ):
                dialog.export_summary()
            write_summary.assert_called_once()
            self.assertEqual(write_summary.call_args.args[0], "C:/tmp/quality-summary.xlsx")
            self.assertEqual(write_summary.call_args.args[1][-1]["category"], "已確認隱藏")

            duplicate_filter_index = dialog.filter_combo.findData("category:疑似重複")
            dialog.filter_combo.setCurrentIndex(duplicate_filter_index)
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 2).text(), "疑似重複")

            dialog.filter_by_summary_item(dialog.category_summary_table.item(0, 0))
            self.assertEqual(dialog.filter_combo.currentData(), "category:分母為 0")
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 2).text(), "分母為 0")

            important_filter_index = dialog.filter_combo.findData("severity:重要")
            dialog.filter_combo.setCurrentIndex(important_filter_index)
            self.assertEqual(dialog.table.rowCount(), 1)

            with (
                patch("customer_dialogs.QFileDialog.getSaveFileName", return_value=("C:/tmp/quality", "")),
                patch("customer_dialogs.write_quality_issues") as write_quality,
                patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok),
            ):
                dialog.export_issues()
            write_quality.assert_called_once()
            self.assertEqual(write_quality.call_args.args[0], "C:/tmp/quality.xlsx")
            self.assertEqual(len(write_quality.call_args.args[1]), 1)
            self.assertEqual(write_quality.call_args.args[1][0].category, "分母為 0")

            with patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok):
                dialog.copy_current_issues()
            clipboard_text = QApplication.clipboard().text()
            self.assertIn("資料ID\t程度\t類型\t問題\t建議處理", clipboard_text)
            self.assertIn("7\t重要\t分母為 0", clipboard_text)
            self.assertNotIn("8\t提醒\t疑似重複", clipboard_text)

            with patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok):
                dialog.clear_ignored_issues()
            self.assertEqual(cleared_ignored, [True])
            self.assertFalse(dialog.clear_ignored_button.isEnabled())

            dialog.table.selectRow(0)
            self.assertEqual(dialog.current_issue().record_id, 7)
            dialog.activate_current_issue()
            self.assertEqual(activated, [7])

            with patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok):
                dialog.ignore_current_issue()
            self.assertEqual(ignored, [7])
            self.assertEqual(dialog.table.rowCount(), 0)
        finally:
            dialog.close()

    def test_data_quality_dialog_bulk_ignores_filtered_and_category(self):
        from customer_quality import DataQualityIssue

        ignored = []
        dialog = DataQualityDialog(
            [
                DataQualityIssue(1, "重要", "分母為 0", "#1：分母不可為 0", "修正分母"),
                DataQualityIssue(2, "提醒", "疑似重複", "#2：疑似重複", "確認是否重複"),
                DataQualityIssue(3, "提醒", "疑似重複", "#3：疑似重複", "確認是否重複"),
            ],
            total_records=3,
            on_issue_ignored=lambda issue: ignored.append(issue.record_id),
        )
        try:
            duplicate_filter_index = dialog.filter_combo.findData("category:疑似重複")
            dialog.filter_combo.setCurrentIndex(duplicate_filter_index)
            with (
                patch("customer_dialogs.QMessageBox.question", return_value=QMessageBox.Yes),
                patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok),
            ):
                dialog.ignore_filtered_issues()
            self.assertEqual(sorted(ignored), [2, 3])
            self.assertEqual([issue.record_id for issue in dialog.issues], [1])

            all_filter_index = dialog.filter_combo.findData("all")
            dialog.filter_combo.setCurrentIndex(all_filter_index)
            dialog.table.selectRow(0)
            with (
                patch("customer_dialogs.QMessageBox.question", return_value=QMessageBox.Yes),
                patch("customer_dialogs.QMessageBox.information", return_value=QMessageBox.Ok),
            ):
                dialog.ignore_same_category_issues()
            self.assertEqual(sorted(ignored), [1, 2, 3])
            self.assertEqual(dialog.table.rowCount(), 0)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
