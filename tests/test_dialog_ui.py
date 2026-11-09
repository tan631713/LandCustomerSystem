import importlib.util
import os
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import customer_ui_loader

ROOT = Path(__file__).resolve().parents[1]
WEB_VIEW_DIALOGS = ("MapLocationsDialog",)
KEPT_UNTIL_EXIT = []


def load_preview_tool():
    spec = importlib.util.spec_from_file_location(
        "preview_dialog", ROOT / "tools" / "preview_dialog.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def focus_chain(window):
    chain = []
    current = window.nextInFocusChain()
    while current is not window and len(chain) < 500:
        if current.focusPolicy() & Qt.TabFocus and current.isVisibleTo(window):
            chain.append(current)
        current = current.nextInFocusChain()
    return chain


class DialogUiFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.dialogs = load_preview_tool().sample_dialogs()
        cls.classes = {}
        for _name, (ui_file, dialog_class, _factory) in cls.dialogs.items():
            cls.classes[ui_file] = dialog_class

    def test_every_dialog_ui_file_is_listed_and_exists(self):
        on_disk = {
            f"dialogs/{path.name}" for path in (ROOT / "ui" / "dialogs").glob("*.ui")
        }
        listed = {ui_file for ui_file in self.classes if ui_file.startswith("dialogs/")}
        self.assertEqual(listed, on_disk)
        self.assertEqual(len(on_disk), 57)

    def test_ui_files_load_with_their_required_names(self):
        for ui_file, dialog_class in self.classes.items():
            with self.subTest(ui_file=ui_file):
                names = getattr(dialog_class, "ui_object_names", None)
                if names is None:  # OwnerContactDialog: its .ui files are the two group boxes
                    names = dialog_class.CONTACT_GROUP_OBJECT_NAMES
                widget = customer_ui_loader.load_ui(ui_file, required_names=names)
                widget.deleteLater()

    def test_ui_files_survive_a_designer_save(self):
        # See test_main_window_ui: Designer drops a bare QWidget container in
        # a layout unless it is marked native="true".  Names must be unique.
        for ui_file in self.classes:
            with self.subTest(ui_file=ui_file):
                tree = ElementTree.parse(ROOT / "ui" / ui_file)
                flattened = [
                    widget.get("name")
                    for item in tree.iter("item")
                    for widget in [item.find("widget")]
                    if widget is not None
                    and widget.get("class") == "QWidget"
                    and widget.get("native") != "true"
                ]
                self.assertEqual(flattened, [])
                names = [
                    element.get("name")
                    for element in tree.iter()
                    if element.tag in ("widget", "layout", "spacer")
                ]
                self.assertEqual(len(names), len(set(names)), "objectName 重複")

    def test_every_dialog_builds_offscreen(self):
        for name, (_ui_file, dialog_class, factory) in self.dialogs.items():
            with self.subTest(dialog=name):
                dialog = factory()
                try:
                    self.assertIsInstance(dialog, dialog_class)
                    self.assertTrue(dialog.windowTitle())
                    dialog.show()
                    self.application.processEvents()
                    self.assertTrue(dialog.isVisible())
                finally:
                    dialog.done(0)
                    if name in WEB_VIEW_DIALOGS:
                        # Deleting a web view before the process ends crashes the
                        # web engine at exit (the old code does too); keep it.
                        KEPT_UNTIL_EXIT.append(dialog)
                    else:
                        dialog.deleteLater()
                    self.application.processEvents()

    def test_dialog_sizes_titles_and_dynamic_texts(self):
        dialogs = {name: entry[2]() for name, entry in self.dialogs.items()
                   if name not in WEB_VIEW_DIALOGS}
        try:
            login, setup = dialogs["AuthDialog"], dialogs["AuthDialog-setup"]
            self.assertEqual((login.width(), login.height()), (360, 190))
            self.assertEqual((setup.minimumWidth(), setup.minimumHeight()), (360, 220))
            self.assertEqual(login.windowTitle(), "登入")
            self.assertEqual(setup.windowTitle(), "設定密碼")
            self.assertTrue(login.confirm_edit.isHidden())
            self.assertFalse(setup.confirm_edit.isHidden())
            self.assertEqual(setup.username_edit.text(), "admin")

            self.assertEqual(dialogs["ChangePasswordDialog"].maximumSize().width(), 380)
            self.assertEqual(dialogs["BatchEditDialog"].size().width(), 420)
            self.assertEqual(dialogs["BackupManagementDialog"].minimumWidth(), 540)
            self.assertEqual(dialogs["DeleteUrbanPlanDialog"].objectName(), "deleteUrbanPlanDialog")
            self.assertGreaterEqual(dialogs["HelpDialog"].tabs.count(), 6)
            self.assertEqual(dialogs["LandDetailsDialog"].findChild(QWidget, "detailsTable").rowCount(), 2)
            self.assertEqual(dialogs["PreviousExportDuplicatesDialog"].list_widget.count(), 2)
            self.assertEqual(dialogs["FollowUpReminderDialog"].status_combo.currentText(), "待回覆")
            buttons = [b.text() for b in dialogs["ImportResultDialog"].findChildren(QPushButton) if b.isVisibleTo(dialogs["ImportResultDialog"])]
            self.assertIn("匯出錯誤列", buttons)
        finally:
            for dialog in dialogs.values():
                dialog.done(0)
                dialog.deleteLater()
            self.application.processEvents()

    def test_widget_put_in_a_slot_keeps_the_slots_tab_position(self):
        dialog = self.dialogs["ExistingContactPickerDialog"][2]()
        try:
            dialog.show()
            self.application.processEvents()
            chain = focus_chain(dialog)
            self.assertIs(chain[0], dialog.table)
            slot = dialog.findChild(QWidget, "contactTableSlot")
            self.assertTrue(slot.isHidden())
            self.assertEqual(dialog.table.parentWidget().layout().indexOf(slot), -1)
        finally:
            dialog.done(0)
            dialog.deleteLater()
            self.application.processEvents()

    def test_table_dialogs_keep_headers_slots_and_dynamic_parts(self):
        dialogs = {name: entry[2]() for name, entry in self.dialogs.items()
                   if name not in WEB_VIEW_DIALOGS}
        try:
            tags = dialogs["TagManagementDialog"]
            self.assertEqual(
                [tags.table.horizontalHeaderItem(c).text() for c in range(tags.table.columnCount())],
                ["ID", "標籤", "顏色", "筆數"],
            )
            preview = dialogs["ImportPreviewDialog"]
            self.assertEqual(preview.table.columnCount(), 4)
            self.assertEqual(preview.table.horizontalHeaderItem(3).text(), "姓名")
            visible = [b.text() for b in preview.findChildren(QPushButton) if b.isVisibleTo(preview)]
            self.assertIn("略過重複後匯入", visible)
            plain = dialogs["ImportPreviewDialog-plans"]
            hidden = [b.text() for b in plain.findChildren(QPushButton) if not b.isVisibleTo(plain)]
            self.assertIn("略過重複後匯入", hidden)
            self.assertEqual(plain.plan_id(), 1)

            readonly = dialogs["UrbanPlanManagementDialog-readonly"]
            self.assertFalse(readonly.add_button.isEnabled())
            self.assertEqual(readonly.objectName(), "urbanPlanManagementDialog")
            self.assertEqual(readonly.table.rowCount(), 2)
            self.assertEqual(
                dialogs["BackupStatusDialog"].findChild(QWidget, "backupCountValue").text(), "12"
            )
            restore = dialogs["ServerBackupRestoreDialog"]
            self.assertFalse(restore.restore_button.isEnabled())
            restore.confirmation_edit.setText(restore.CONFIRMATION_TEXT)
            self.assertTrue(restore.restore_button.isEnabled())
            self.assertEqual(dialogs["ReportTemplatesDialog"].fields.count(), 5)
        finally:
            for dialog in dialogs.values():
                dialog.done(0)
                dialog.deleteLater()
            self.application.processEvents()

    def test_container_put_in_a_slot_brings_its_children_into_the_tab_order(self):
        dialog = self.dialogs["ImportPreviewDialog-plans"][2]()
        try:
            dialog.show()
            self.application.processEvents()
            chain = focus_chain(dialog)
            self.assertIs(chain[0], dialog.plan_choice.combo)
            self.assertLess(chain.index(dialog.plan_choice.combo), chain.index(dialog.table))
        finally:
            dialog.done(0)
            dialog.deleteLater()
            self.application.processEvents()

    def test_table_rows_are_measured_like_the_hand_built_dialogs(self):
        # The old HealthCheckDialog measured rows on a 640-wide table, so a
        # long 說明 cell stayed on one line; see size_like_unparented().
        dialog = self.dialogs["HealthCheckDialog"][2]()
        try:
            single_line = dialog.table.verticalHeader().defaultSectionSize()
            # Fluent F2: the table is Fluent's TableWidget, whose cells add a
            # 2 px margin above and below (row 38 by default) -- still one line.
            self.assertLessEqual(dialog.table.rowHeight(0), max(single_line, 32) + 4)
        finally:
            dialog.done(0)
            dialog.deleteLater()
            self.application.processEvents()

    def test_large_dialogs_fill_their_containers_and_keep_their_behaviour(self):
        from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit

        from customer_quality import QUALITY_RULE_OPTIONS

        dialogs = {name: entry[2]() for name, entry in self.dialogs.items()
                   if name not in WEB_VIEW_DIALOGS}
        try:
            rules = dialogs["DataQualityRulesDialog"]
            self.assertEqual(len(rules.rule_checkboxes), len(QUALITY_RULE_OPTIONS))
            self.assertEqual((rules.width(), rules.height()), (500, 430))
            chain = focus_chain(rules)
            first_box = next(iter(rules.rule_checkboxes.values()))
            self.assertLess(chain.index(rules.preset_combo), chain.index(first_box))

            quality = dialogs["DataQualityDialog"]
            self.assertEqual(quality.table.rowCount(), 2)
            self.assertEqual(quality.filter_combo.count(), 8)

            custom = dialogs["CustomerCustomValuesDialog"]
            self.assertEqual(len(custom.edits), 2)
            self.assertEqual(next(iter(custom.edits.values())).text(), "0912")
            custom_chain = focus_chain(custom)
            self.assertIs(custom_chain[0], next(iter(custom.edits.values())))

            batch = dialogs["BatchCustomerCustomValuesDialog"]
            checkbox, edit = next(iter(batch.rows.values()))
            self.assertFalse(edit.isEnabled())
            checkbox.setChecked(True)
            self.assertTrue(edit.isEnabled())

            new_contact = dialogs["OwnerContactDialog-new"]
            self.assertIsNotNone(new_contact._match_table)
            self.assertEqual(new_contact.new_external_id_button.text(), "👁 隱藏")
            edit_contact = dialogs["OwnerContactDialog-edit"]
            form = edit_contact.edit_name.parentWidget().layout()
            self.assertIsInstance(form, QFormLayout)
            hint = edit_contact.findChild(QLabel, "matchHint")
            row, _role = form.getWidgetPosition(hint)
            self.assertFalse(form.isRowVisible(row))
            self.assertEqual(edit_contact.edit_name.text(), "王小明")
            self.assertEqual(edit_contact.edit_relationship_type.currentText(), "配偶")
            view = dialogs["OwnerContactDialog-view"]
            self.assertFalse(view.edit_name.isEnabled())

            workflow = dialogs["WorkflowDialog"]
            self.assertEqual(
                [workflow.case_status.itemText(i) for i in range(workflow.case_status.count())],
                ["進行中", "等待中", "完成", "暫停"],
            )
            self.assertEqual(workflow.task_case.count(), 1)
            self.assertIn("2 筆", workflow.attach_status_label.text())

            calendar = dialogs["VisitCalendarDialog"]
            self.assertGreater(calendar.grid_layout.count(), 7)
            shared = dialogs["SharedLandBatchDialog"]
            self.assertEqual(shared.shared_inputs["district"].text(), "桃園區")
            self.assertIsNotNone(shared.shared_inputs["district"].completer())
            advanced = dialogs["AdvancedSearchDialog"]
            self.assertEqual(advanced.exclude_input.text(), "測試")

            result = dialogs["ImportResultDialog-plan"]
            self.assertIsNotNone(result.plan_section.table)
            self.assertEqual(result.plan_section.table.rowCount(), 2)
        finally:
            for dialog in dialogs.values():
                dialog.done(0)
                dialog.deleteLater()
            self.application.processEvents()

    def test_import_plan_result_without_kept_lands_hides_that_part(self):
        from customer_urban_plan_dialogs import ImportPlanResultSection

        section = ImportPlanResultSection({"name": "中壢", "assigned_land_count": 3})
        try:
            self.assertIsNone(section.table)
            self.assertIsNone(section.export_button)
            self.assertTrue(section.kept_label.isHidden())
            self.assertIn("3 筆土地", section.header_label.text())
        finally:
            section.deleteLater()


if __name__ == "__main__":
    unittest.main()
