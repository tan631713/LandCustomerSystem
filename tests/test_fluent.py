"""Fluent F1-F4: theme file, scoped theme.qss, promoted .ui widgets, tables, Designer plugin."""

import json
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QApplication

import customer_fluent
import customer_theme
import customer_ui_loader

F1_DIALOG_FILES = (
    "auth_dialog", "change_password_dialog", "font_size_dialog", "batch_edit_dialog",
    "batch_edit_preview_dialog", "follow_up_reminder_dialog", "import_result_dialog", "help_dialog",
    "case_select_dialog", "field_visit_schedule_dialog", "merge_records_dialog", "apply_template_dialog",
    "mobile_share_dialog", "delete_urban_plan_dialog", "set_urban_plan_dialog", "backup_management_dialog",
    "existing_contact_picker_dialog", "deactivate_relation_dialog", "land_details_dialog",
    "previous_export_duplicates_dialog",
)
F2_DIALOG_FILES = (
    "dashboard_dialog", "record_history_dialog", "follow_up_list_dialog", "import_preview_dialog",
    "saved_search_dialog", "operation_log_dialog", "watchlist_dialog", "tag_management_dialog",
    "customer_tags_dialog", "batch_customer_tags_dialog", "attachment_dialog", "custom_field_management_dialog",
    "contact_log_dialog", "health_check_dialog", "recycle_bin_dialog", "undo_operations_dialog",
    "notification_center_dialog", "import_profiles_dialog", "report_templates_dialog", "duplicate_finder_dialog",
    "backup_status_dialog", "server_backup_targets_dialog", "server_backup_restore_dialog",
    "urban_plan_management_dialog",
)
F3_MAIN_FILES = (
    "batch_bar", "import_plan_choice", "import_plan_result_section", "land_header", "list_footer",
    "owner_contact_group", "owner_contacts", "owner_relation_group", "plan_view_bar",
)
F4_DIALOG_FILES = (
    "advanced_search_dialog", "backup_targets_dialog", "batch_customer_custom_values_dialog",
    "column_visibility_dialog", "customer_custom_values_dialog", "data_quality_dialog",
    "data_quality_rules_dialog", "map_locations_dialog", "shared_land_batch_dialog", "text_template_dialog",
    "user_management_dialog", "visit_calendar_dialog", "workflow_dialog",
)
EXTENDS = {
    "LineEdit": "QLineEdit", "PasswordLineEdit": "QLineEdit", "PlainTextEdit": "QPlainTextEdit",
    "CheckBox": "QCheckBox", "SpinBox": "QSpinBox", "ComboBox": "QPushButton",
    "PushButton": "QPushButton", "PrimaryPushButton": "QPushButton", "TransparentPushButton": "QPushButton",
    "TableWidget": "QTableWidget", "ListWidget": "QListWidget", "ToggleButton": "QPushButton",
    "DialogButtonBox": "QDialogButtonBox",
}
# Plain Qt widgets that stay (see docs/Fluent改造計畫.md).
KEPT_PLAIN = {"QDateEdit", "QDialogButtonBox", "QTableWidget", "QListWidget", "QTabWidget"}


class FluentThemeFileTests(unittest.TestCase):
    def test_bundled_file_reads_as_the_defaults(self):
        settings = customer_fluent.load_fluent_theme()
        self.assertEqual(settings["primaryColor"], "#2F6B4F")
        self.assertEqual(settings["darkPrimaryColor"], "#6DBE93")
        self.assertEqual(settings["fontFamilies"][0], "Microsoft JhengHei UI")

    def test_missing_broken_or_wrong_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = customer_fluent.load_fluent_theme(Path(folder, "none.json"))
            self.assertEqual(missing, customer_fluent.DEFAULT_FLUENT_THEME)

            broken = Path(folder, "broken.json")
            broken.write_text('{"primaryColor": "#123456",', encoding="utf-8")
            with self.assertLogs(customer_fluent.LOGGER, "WARNING"):
                self.assertEqual(customer_fluent.load_fluent_theme(broken), customer_fluent.DEFAULT_FLUENT_THEME)

            partial = Path(folder, "partial.json")
            partial.write_text(json.dumps({"primaryColor": "not a colour", "darkPrimaryColor": "#336699",
                                           "fontFamilies": "標楷體"}), encoding="utf-8")
            with self.assertLogs(customer_fluent.LOGGER, "WARNING"):
                settings = customer_fluent.load_fluent_theme(partial)
            self.assertEqual(settings["primaryColor"], "#2F6B4F")
            self.assertEqual(settings["darkPrimaryColor"], "#336699")
            self.assertEqual(settings["fontFamilies"], ["標楷體"])


class FluentApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def tearDown(self):
        customer_theme.activate_theme("light")
        customer_fluent.apply_fluent_theme("light", customer_fluent.DEFAULT_POINT_SIZE)

    def test_dark_accent_is_the_configured_green_not_mint(self):
        import qfluentwidgets

        customer_fluent.apply_fluent_theme("dark", 11)
        self.assertEqual(qfluentwidgets.themeColor().name().upper(), "#6DBE93")
        customer_fluent.apply_fluent_theme("light", 11)
        self.assertEqual(qfluentwidgets.themeColor().name().upper(), "#2F6B4F")

    def test_fluent_text_follows_the_font_size_setting(self):
        customer_fluent.apply_fluent_theme("light", 11)
        self.assertEqual(customer_fluent._scale_qss_fonts("font: 14px 'A'; font-size: 7px;"),
                         "font: 11.0pt 'A'; font-size: 5.5pt;")
        customer_fluent.set_font_point_size(15)
        self.assertIn("15.0pt", customer_fluent._scale_qss_fonts("font: 14px x"))
        from qfluentwidgets.common.font import getFont

        self.assertAlmostEqual(getFont(14).pointSizeF(), 15.0)


class ScopedThemeQssTests(unittest.TestCase):
    CONTROLS = ("QLineEdit", "QPlainTextEdit", "QTextEdit", "QComboBox", "QPushButton", "QCheckBox",
                "QMenu", "QAbstractSpinBox", "QSpinBox")

    def _selectors(self, qss):
        qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
        return re.findall(r"([^{}]+)\{", qss)

    def test_control_rules_only_match_plain_qt_widgets(self):
        sheets = {
            "ui/theme.qss": (ROOT / "ui" / "theme.qss").read_text(encoding="utf-8"),
            "built-in": customer_theme._STYLESHEET.template,
        }
        bare = re.compile(r"(?<![\w.#-])(" + "|".join(self.CONTROLS) + r")\b")
        for name, qss in sheets.items():
            for selector in self._selectors(qss):
                with self.subTest(sheet=name, selector=selector.strip()):
                    self.assertIsNone(bare.search(selector))

    def test_fluent_widgets_qss_matches_its_builtin_copy(self):
        text = (ROOT / "ui" / "fluent_widgets.qss").read_text(encoding="utf-8")
        body = text[text.index("*/") + 2:].strip()
        self.assertEqual(body, customer_fluent.FLUENT_WIDGETS_STYLESHEET.strip())


class FluentUiFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def _files(self):
        yield "main_window.ui"
        for name in F1_DIALOG_FILES:
            yield f"dialogs/{name}.ui"
        for name in F2_DIALOG_FILES:
            yield f"dialogs/{name}.ui"
        for name in F3_MAIN_FILES:
            yield f"main/{name}.ui"
        for name in F4_DIALOG_FILES:
            yield f"dialogs/{name}.ui"

    def test_promoted_classes_are_declared_for_designer(self):
        for name in self._files():
            with self.subTest(file=name):
                root = ET.parse(customer_ui_loader.ui_path(name)).getroot()
                used = {w.get("class") for w in root.iter("widget")} & set(EXTENDS)
                declared = {cw.findtext("class"): cw for cw in root.iter("customwidget")}
                for class_name in used:
                    self.assertIn(class_name, declared)
                    self.assertEqual(declared[class_name].findtext("extends"), EXTENDS[class_name])
                    self.assertEqual(declared[class_name].findtext("header"),
                                     "customer_fluent" if class_name == "DialogButtonBox" else "qfluentwidgets")
                plain_controls = {w.get("class") for w in root.iter("widget")} & {
                    "QPushButton", "QLineEdit", "QComboBox", "QCheckBox", "QSpinBox", "QPlainTextEdit"}
                if name != "main_window.ui":
                    self.assertEqual(plain_controls, set(), "F1/F2 dialogs keep no plain controls")
                if Path(name).stem in F2_DIALOG_FILES:
                    plain_views = {w.get("class") for w in root.iter("widget")} & {"QTableWidget", "QListWidget"}
                    self.assertEqual(plain_views, set(), "F2 tables and lists are Fluent")

    def test_every_non_qt_class_in_the_ui_files_is_a_fluent_widget(self):
        """A class name QUiLoader does not know (an alias such as TogglePushButton)
        would silently load as the plain widget it extends."""

        registered = {widget_class.__name__ for widget_class in customer_fluent.fluent_widget_classes()}
        for path in sorted(customer_ui_loader.ui_dir().rglob("*.ui")):
            root = ET.parse(path).getroot()
            for element in root.iter("widget"):
                class_name = element.get("class")
                if not class_name.startswith("Q"):
                    with self.subTest(file=path.name, widget=element.get("name")):
                        self.assertIn(class_name, registered)

    def test_files_load_as_fluent_widgets_without_extra_tab_stops(self):
        classes = {widget_class.__name__: widget_class for widget_class in customer_fluent.fluent_widget_classes()}
        for name in self._files():
            with self.subTest(file=name):
                widget = customer_ui_loader.load_ui(name)
                try:
                    root = ET.parse(customer_ui_loader.ui_path(name)).getroot()
                    for element in root.iter("widget"):
                        class_name = element.get("class")
                        if class_name in EXTENDS:
                            child = widget.findChild(classes[class_name], element.get("name"))
                            self.assertIsNotNone(child, element.get("name"))
                            self.assertIs(type(child), classes[class_name])
                            if class_name == "DialogButtonBox":
                                # Its buttons are real Tab stops -- and all Fluent now.
                                self.assertTrue(all(type(b).__module__.startswith("qfluentwidgets")
                                                    for b in child.buttons()))
                                continue
                            for inner in child.findChildren(QAbstractButton):
                                self.assertEqual(inner.focusPolicy(), Qt.NoFocus)
                finally:
                    widget.deleteLater()

    def test_toolbar_and_form_widgets_are_fluent(self):
        import qfluentwidgets

        widget = customer_ui_loader.load_ui("main_window.ui")
        try:
            for name, class_name in (("searchFilterCombo", "ComboBox"), ("searchInput", "LineEdit"),
                                     ("newRecordButton", "PrimaryPushButton"),
                                     ("saveRecordButton", "PrimaryPushButton"),
                                     ("deleteRecordButton", "TransparentPushButton"),
                                     ("field_urban_plan", "ComboBox"), ("field_note", "PlainTextEdit"),
                                     ("field_owner_name", "LineEdit")):
                self.assertIsInstance(widget.findChild(getattr(qfluentwidgets, class_name), name),
                                      getattr(qfluentwidgets, class_name), name)
        finally:
            widget.deleteLater()


class FluentTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def _table(self):
        import qfluentwidgets
        from PySide6.QtWidgets import QTableWidgetItem, QWidget

        root = QWidget()
        table = qfluentwidgets.TableWidget(root)
        table.setColumnCount(2)
        table.setRowCount(3)
        for row in range(3):
            for column in range(2):
                table.setItem(row, column, QTableWidgetItem(f"{row}-{column}"))
        customer_fluent.style_fluent_widgets(root)
        return root, table

    def test_rows_selected_by_code_are_highlighted(self):
        from PySide6.QtCore import QItemSelectionModel

        root, table = self._table()
        try:
            table.selectionModel().select(
                table.model().index(2, 0),
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
            self.assertEqual(table.delegate.selectedRows, {2})
            table.selectionModel().clearSelection()
            self.assertEqual(table.delegate.selectedRows, set())
            table.selectRow(1)
            table.setRowCount(0)
            self.assertEqual(table.delegate.selectedRows, set())
        finally:
            root.deleteLater()

    def test_cells_use_the_body_text_size(self):
        from PySide6.QtWidgets import QStyleOptionViewItem

        customer_fluent.apply_fluent_theme("light", 13)
        root, table = self._table()
        try:
            option = QStyleOptionViewItem()
            table.delegate.initStyleOption(option, table.model().index(0, 0))
            self.assertAlmostEqual(option.font.pointSizeF(), 13.0)
        finally:
            root.deleteLater()
            customer_fluent.apply_fluent_theme("light", customer_fluent.DEFAULT_POINT_SIZE)

    def test_tag_mode_combo_keeps_its_values(self):
        import customer_extra_dialogs

        dialog = customer_extra_dialogs.BatchCustomerTagsDialog([{"id": 1, "name": "優先", "color": ""}], 2)
        try:
            self.assertEqual(dialog.mode_combo.currentData(), "add")
            dialog.mode_combo.setCurrentIndex(2)
            self.assertEqual(dialog.mode_combo.currentData(), "replace")
        finally:
            dialog.deleteLater()


class FluentMainWindowPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_read_only_relation_editor_disables_the_fluent_dropdown(self):
        import customer_owner_contacts
        import qfluentwidgets
        from unittest.mock import MagicMock

        dialog = customer_owner_contacts.OwnerContactDialog(
            MagicMock(), 1, existing={"contact_id": 1, "name": "王小明", "relationship_type": "本人"},
            readonly=True, allow_edit=True)
        try:
            combos = dialog.findChildren(qfluentwidgets.ComboBox)
            self.assertTrue(combos)
            self.assertTrue(all(not combo.isEnabled() for combo in combos))
        finally:
            dialog.deleteLater()

    def test_list_and_tree_view_buttons_are_toggle_buttons(self):
        import qfluentwidgets

        widget = customer_ui_loader.load_ui("main/owner_contacts.ui")
        try:
            button = widget.findChild(qfluentwidgets.ToggleButton, "listViewButton")
            self.assertIsNotNone(button)
            self.assertTrue(button.isCheckable() and button.isChecked())
        finally:
            widget.deleteLater()


class FluentAllDialogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_no_dialog_keeps_plain_buttons_inputs_or_button_rows(self):
        """After F4 the only plain controls left in ui/ are the date boxes and the
        workflow tab / scroll / stacked containers (see docs/Fluent改造計畫.md)."""

        plain = {"QPushButton", "QLineEdit", "QComboBox", "QCheckBox", "QSpinBox", "QPlainTextEdit",
                 "QTableWidget", "QListWidget", "QDialogButtonBox"}
        for path in sorted(customer_ui_loader.ui_dir().rglob("*.ui")):
            root = ET.parse(path).getroot()
            with self.subTest(file=path.name):
                self.assertEqual({w.get("class") for w in root.iter("widget")} & plain, set())

    def test_button_rows_are_fluent_and_keep_their_roles(self):
        import qfluentwidgets
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

        box_class = customer_fluent.dialog_button_box_class()
        dialog = QDialog()
        box = box_class(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        QVBoxLayout(dialog).addWidget(box)
        box.use_fluent_buttons()
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        try:
            ok, cancel = box.button(QDialogButtonBox.Ok), box.button(QDialogButtonBox.Cancel)
            self.assertIsInstance(ok, qfluentwidgets.PrimaryPushButton)
            self.assertIsInstance(cancel, qfluentwidgets.PushButton)
            self.assertEqual(box.standardButton(ok), QDialogButtonBox.Ok)
            self.assertEqual([b for b in box.buttons() if b.isVisible() or True], [b for b in box.buttons()])
            self.assertEqual(len(box.buttons()), 2)
            ok.setText("繼續匯出")
            dialog.show()
            self.application.processEvents()
            self.assertTrue(ok.isDefault() or ok.autoDefault())
            ok.click()
            self.assertEqual(dialog.result(), QDialog.Accepted)
            dialog.show()
            cancel.click()
            self.assertEqual(dialog.result(), QDialog.Rejected)
            extra = box.addButton("立即壓縮", QDialogButtonBox.ActionRole)
            self.assertIsInstance(extra, qfluentwidgets.PushButton)
        finally:
            dialog.deleteLater()

    def test_escape_still_closes_a_dialog_with_a_fluent_button_row(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

        dialog = QDialog()
        box = customer_fluent.dialog_button_box_class()(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        QVBoxLayout(dialog).addWidget(box)
        box.use_fluent_buttons()
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        try:
            dialog.show()
            self.application.processEvents()
            QTest.keyClick(dialog, Qt.Key_Escape)
            self.assertEqual(dialog.result(), QDialog.Rejected)
            dialog.show()
            self.application.processEvents()
            QTest.keyClick(dialog, Qt.Key_Return)
            self.assertEqual(dialog.result(), QDialog.Accepted)
        finally:
            dialog.deleteLater()

    def test_workflow_status_and_priority_options_come_from_code(self):
        import customer_productivity

        self.assertEqual(customer_productivity.CASE_STATUS_OPTIONS, ("進行中", "等待中", "完成", "暫停"))
        self.assertEqual(customer_productivity.TASK_STATUS_OPTIONS, ("待處理", "進行中", "等待中", "完成"))
        self.assertEqual(customer_productivity.PRIORITY_OPTIONS, ("一般", "高", "緊急"))


class DesignerPluginTests(unittest.TestCase):
    def test_plugin_registers_widgets_when_run_like_designer_does(self):
        """Designer runs the file with separate globals and locals dicts."""

        path = ROOT / "tools" / "designer_plugins" / "register_fluent_widgets.py"
        source = path.read_text(encoding="utf-8")
        from PySide6.QtDesigner import QPyDesignerCustomWidgetCollection

        with patch.object(QPyDesignerCustomWidgetCollection, "registerCustomWidget") as register:
            exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)}, {})
        names = {call.args[0].__name__ for call in register.call_args_list}
        for class_name in ("PushButton", "PrimaryPushButton", "LineEdit", "ComboBox", "CheckBox", "BodyLabel"):
            self.assertIn(class_name, names)
        modules = {call.args[0].__name__: call.kwargs["module"] for call in register.call_args_list}
        self.assertEqual(modules.pop("DialogButtonBox"), "customer_fluent")
        self.assertTrue(all(module == "qfluentwidgets" for module in modules.values()))

    def test_open_designer_bat_points_designer_at_the_plugin_folder(self):
        bat = (ROOT / "tools" / "open_designer.bat").read_text(encoding="utf-8")
        self.assertIn("PYSIDE_DESIGNER_PLUGINS=%HERE%designer_plugins", bat)
        self.assertIn("pyside6-designer", bat)


if __name__ == "__main__":
    unittest.main()
