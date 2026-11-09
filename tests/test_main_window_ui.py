import os
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from string import Template
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.fernet import Fernet
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPlainTextEdit, QWidget

import customer_theme
import customer_ui_loader
import customer_ui_qt as app
import customer_window_ui as window_ui_module
from customer_database import CustomerDatabase
from customer_fields import LAND_FIELDS
from customer_repository import CustomerRepository

ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW_UI = ROOT / "ui" / window_ui_module.MAIN_WINDOW_UI_FILE


def ui_object_names():
    """objectName -> element tag for every widget, layout and spacer in the .ui."""

    tree = ElementTree.parse(MAIN_WINDOW_UI)
    names = {}
    duplicates = []
    for element in tree.iter():
        if element.tag in ("widget", "layout", "spacer") and element.get("name"):
            name = element.get("name")
            if name in names:
                duplicates.append(name)
            names[name] = element
    return names, duplicates


class MainWindowUiFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_every_fixed_form_field_has_its_widgets_in_the_ui_file(self):
        names, duplicates = ui_object_names()

        self.assertEqual(duplicates, [], "objectName 重複")
        keys = window_ui_module.form_field_keys(LAND_FIELDS)
        self.assertEqual(
            set(keys),
            {key for key, _label in LAND_FIELDS}
            | set(window_ui_module.EXTRA_OWNER_FORM_FIELD_LABELS),
        )
        missing = [
            name
            for name in window_ui_module.main_window_object_names(LAND_FIELDS)
            if name not in names
        ]
        self.assertEqual(missing, [], f"{MAIN_WINDOW_UI.name} 缺少這些 objectName")

    def test_plain_widget_containers_survive_a_designer_save(self):
        # Qt Designer treats a bare <widget class="QWidget"> that sits in a
        # layout and has its own layout as a layout-only helper and drops it
        # (with its objectName and properties) on save; native="true" keeps it.
        tree = ElementTree.parse(MAIN_WINDOW_UI)
        flattened = []
        for item in tree.iter("item"):
            widget = item.find("widget")
            if widget is not None and widget.get("class") == "QWidget" and widget.get("native") != "true":
                flattened.append(widget.get("name"))
        self.assertEqual(flattened, [], 'QWidget 容器缺少 native="true"')

    def test_field_widget_types_match_the_program(self):
        names, _duplicates = ui_object_names()
        for key in window_ui_module.form_field_keys(LAND_FIELDS):
            # Fluent F1: the form fields are promoted to Fluent classes.
            expected_class = {"urban_plan": "ComboBox", "note": "PlainTextEdit"}.get(
                key, "LineEdit"
            )
            self.assertEqual(names[f"field_{key}"].get("class"), expected_class, key)
            self.assertEqual(names[f"fieldLabel_{key}"].get("class"), "QLabel", key)
            self.assertEqual(names[f"fieldCell_{key}"].get("class"), "QWidget", key)

    def test_ui_file_loads_with_quiloader_and_has_the_required_names(self):
        widget = customer_ui_loader.load_ui(
            window_ui_module.MAIN_WINDOW_UI_FILE,
            required_names=window_ui_module.main_window_object_names(LAND_FIELDS),
        )
        try:
            self.assertEqual(widget.objectName(), "appGround")
            self.assertIsInstance(widget.findChild(QLineEdit, "field_owner_name"), QLineEdit)
            self.assertIsInstance(widget.findChild(QPlainTextEdit, "field_note"), QPlainTextEdit)
            self.assertTrue(widget.findChild(QLineEdit, "field_total_declared_value").isReadOnly())
            self.assertEqual(widget.findChild(QLineEdit, "field_birth_year").maxLength(), 4)
            self.assertEqual(widget.findChild(QLabel, "landSectionHeader").text(), "土地標示部")
            # The list area is filled in by code and must stay empty in the .ui.
            self.assertEqual(widget.findChild(QWidget, "listFrame").layout().count(), 0)
        finally:
            widget.deleteLater()

    def test_missing_object_name_gives_a_clear_error(self):
        with self.assertRaises(customer_ui_loader.UiLoadError) as raised:
            customer_ui_loader.load_ui(
                window_ui_module.MAIN_WINDOW_UI_FILE,
                required_names=("field_does_not_exist",),
            )
        self.assertIn("field_does_not_exist", str(raised.exception))
        self.assertIn(window_ui_module.MAIN_WINDOW_UI_FILE, str(raised.exception))

        with patch.object(customer_ui_loader, "ui_dir", return_value=ROOT / "no-such-ui"):
            with self.assertRaises(customer_ui_loader.UiLoadError) as raised:
                customer_ui_loader.load_ui(window_ui_module.MAIN_WINDOW_UI_FILE)
        self.assertIn("找不到介面檔", str(raised.exception))

    def test_qss_files_render_for_both_themes_without_falling_back(self):
        for tokens in (customer_theme.LIGHT, customer_theme.DARK):
            with patch.object(customer_theme, "_STYLESHEET", Template("FALLBACK")):
                stylesheet = customer_theme.build_app_stylesheet(tokens)
            self.assertNotIn("FALLBACK", stylesheet)
            self.assertIn("QFrame#searchGroup", stylesheet)
            self.assertIn(tokens["green"], stylesheet)

            form = customer_ui_loader.render_qss(
                window_ui_module.DETAIL_FORM_STYLESHEET_FILE, "FALLBACK", tokens
            )
            self.assertNotEqual(form, "FALLBACK")
            self.assertIn(tokens["rule_strong"], form)

    def test_missing_or_broken_qss_falls_back_to_the_built_in_style(self):
        with patch.object(customer_ui_loader, "ui_dir", return_value=ROOT / "no-such-ui"):
            with self.assertLogs("customer_ui_loader", level="WARNING"):
                stylesheet = customer_theme.build_app_stylesheet(customer_theme.LIGHT)
        self.assertIn("QFrame#searchGroup", stylesheet)

        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "theme.qss").write_text("QWidget { color: $no_such_colour; }", encoding="utf-8")
            with patch.object(customer_ui_loader, "ui_dir", return_value=Path(folder)):
                with self.assertLogs("customer_ui_loader", level="WARNING"):
                    stylesheet = customer_theme.build_app_stylesheet(customer_theme.LIGHT)
        self.assertIn("QFrame#searchGroup", stylesheet)
        self.assertNotIn("no_such_colour", stylesheet)

    def test_main_window_part_files_load_and_survive_a_designer_save(self):
        from customer_land_header import LandHeaderWidget
        from customer_owner_contacts import OwnerContactDialog, OwnerContactsWidget
        from customer_urban_plan_dialogs import ImportPlanChoice, ImportPlanResultSection

        required = {
            "main/plan_view_bar.ui": ("planViewCombo", "planInputCombo", "expandAllButton",
                                      "collapseAllButton", "planHintLabel"),
            "main/batch_bar.ui": ("batchBarCount", "batchBar_batch_edit_action",
                                  "batchBar_clear_checked_action"),
            "main/list_footer.ui": ("landCountLabel", "previousPageButton", "landPageLabel",
                                    "nextPageButton", "legendChecked", "legendNote"),
            LandHeaderWidget.ui_file: LandHeaderWidget.ui_object_names,
            OwnerContactsWidget.ui_file: OwnerContactsWidget.ui_object_names,
            OwnerContactDialog.CONTACT_GROUP_UI_FILE: OwnerContactDialog.CONTACT_GROUP_OBJECT_NAMES,
            OwnerContactDialog.RELATION_GROUP_UI_FILE: OwnerContactDialog.RELATION_GROUP_OBJECT_NAMES,
            ImportPlanChoice.ui_file: ImportPlanChoice.ui_object_names,
            ImportPlanResultSection.ui_file: ImportPlanResultSection.ui_object_names,
        }
        on_disk = {f"main/{path.name}" for path in (ROOT / "ui" / "main").glob("*.ui")}
        self.assertEqual(set(required), on_disk)
        for ui_file, names in required.items():
            with self.subTest(ui_file=ui_file):
                customer_ui_loader.load_ui(ui_file, required_names=names).deleteLater()
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

    def test_packaging_ships_the_ui_folder(self):
        build_script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

        self.assertIn('--add-data "ui;ui"', build_script)


class MainWindowFromUiTests(unittest.TestCase):
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
            app.DATABASE,
            app.SCHEMA_PATH,
            self.root / "missing-seed.sql",
            app.LAND_FIELDS,
        )
        app.init_db()

    def tearDown(self):
        self.application.processEvents()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def test_window_built_from_ui_keeps_fields_sizes_and_order(self):
        settings = QSettings(str(self.root / "layout.ini"), QSettings.IniFormat)
        with patch.object(window_ui_module, "QSettings", return_value=settings):
            window = app.LandApp(Fernet.generate_key())
        try:
            window.show()
            self.application.processEvents()
            self.assertEqual(
                list(window.fields),
                [
                    "district", "section", "subsection", "land_number",
                    "registration_order", "numerator", "denominator",
                    "area", "declared_value", "ping", "total_declared_value",
                    "owner_name", "external_id", "birth_year",
                    "address", "registration_reason", "visit_log", "note",
                ],
            )
            self.assertEqual(len(window.field_widgets), 17)
            self.assertEqual(len(window.form_field_containers), 20)
            self.assertEqual(window.main_splitter.sizes(), list(window_ui_module.DEFAULT_SPLITTER_SIZES))
            self.assertIs(window.centralWidget(), window.main_window_ui)
            self.assertTrue(window.findChild(QWidget, "landHeaderSlot").isHidden())
            self.assertEqual(window.form_frame.layout().indexOf(window.land_header), 0)
            self.assertEqual(window.form_cell_positions["note"], ("owner", 0, 6))
            self.assertEqual(window.form_cell_positions["district"], ("land", 0, 3))
            self.assertTrue(window.form_field_containers["note"].property("lastRow"))
            self.assertTrue(window.form_field_containers["total_declared_value"].property("lastRow"))
            # The list bars, footer, land header and contacts tab come from ui/main/.
            self.assertEqual(window.plan_view_combo.objectName(), "planViewCombo")
            self.assertEqual(window.batch_bar.objectName(), "batchBar")
            self.assertEqual(
                list(window.batch_bar_buttons),
                ["field_visit_action", "assign_case_action", "batch_tags_action",
                 "batch_edit_action", "export_selected_action", "clear_checked_action"],
            )
            self.assertEqual(window.next_land_page_button.objectName(), "nextPageButton")
            self.assertEqual(window.land_header.land_number_label.text(), "尚未選取資料")
            self.assertTrue(window.land_header.share_bar.isHidden())
            contacts = window.owner_contacts_widget
            self.assertEqual(contacts.view_stack.count(), 2)
            self.assertIs(contacts.view_stack.widget(0), contacts.table)
            self.assertEqual(contacts.table.horizontalHeaderItem(1).text(), "姓名")
            self.assertFalse(contacts.tree_zoom_in_button.isEnabled())
            # Tab goes from the toolbar into the list before the detail form.
            chain = []
            current = window.new_record_button.nextInFocusChain()
            while current is not window and len(chain) < 500:
                chain.append(current)
                current = current.nextInFocusChain()
            self.assertLess(chain.index(window.table_view), chain.index(window.detail_tabs))
            self.assertLess(chain.index(window.detail_tabs), chain.index(window.fields["district"]))
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
