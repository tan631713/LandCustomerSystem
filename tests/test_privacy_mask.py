"""Tests for the "測試" privacy-mask settings toggle.

User request: a settings-menu action (deliberately labeled "測試" so a spot
inspector browsing the menu cannot tell what it does) that, once turned on
with the current user's password, reduces every displayed owner name down
to just its surname, hides the "關係人" tab entirely, and covers Excel/Word
exports and the map popup the same way -- and can only be turned back off
with the password again. The mask is a display-layer transform only: the
real encrypted data must never be touched, and saving a record while masked
must never write the truncated display text back to the database.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog

import customer_ui_qt as app
from customer_database import CustomerDatabase
from customer_repository import CustomerRepository


class PrivacyMaskTests(unittest.TestCase):
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
        app.REPOSITORY.create_admin_user("test-password")
        self.encryption_key = app.REPOSITORY.authenticate_user("admin", "test-password")
        self._windows = []

    def tearDown(self):
        # Windows must close (their closeEvent() persists selection state
        # through self.repository) *before* the temp directory holding
        # their database disappears -- addCleanup() runs after tearDown(),
        # which is too late, so this closes them explicitly first.
        for window in self._windows:
            window.close()
        self.application.processEvents()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def _make_window(self):
        window = app.LandApp(self.encryption_key)
        self._windows.append(window)
        return window

    def _enable_mask(self, window, password="test-password"):
        with patch.object(QInputDialog, "getText", return_value=(password, True)):
            window.privacy_mask_action.setChecked(True)

    def _disable_mask(self, window, password="test-password"):
        with patch.object(QInputDialog, "getText", return_value=(password, True)):
            window.privacy_mask_action.setChecked(False)

    def test_toggle_requires_correct_password(self):
        window = self._make_window()
        self._enable_mask(window)
        self.assertTrue(window.privacy_mask_enabled)
        self.assertTrue(window.privacy_mask_action.isChecked())
        self.assertEqual(
            window.repository.get_setting(window.privacy_mask_setting_key, "0"), "1"
        )

    def test_toggle_cancelled_password_prompt_reverts_and_leaves_setting_untouched(self):
        window = self._make_window()
        with patch.object(QInputDialog, "getText", return_value=("", False)):
            window.privacy_mask_action.setChecked(True)
        self.assertFalse(window.privacy_mask_enabled)
        self.assertFalse(window.privacy_mask_action.isChecked())
        self.assertEqual(
            window.repository.get_setting(window.privacy_mask_setting_key, "0"), "0"
        )

    def test_toggle_wrong_password_reverts_and_warns(self):
        window = self._make_window()
        with patch.object(QInputDialog, "getText", return_value=("wrong-password", True)):
            with patch.object(app.QMessageBox, "warning") as mocked_warning:
                window.privacy_mask_action.setChecked(True)
        mocked_warning.assert_called_once()
        self.assertFalse(window.privacy_mask_enabled)
        self.assertFalse(window.privacy_mask_action.isChecked())

    def test_disabling_the_mask_also_requires_the_password(self):
        window = self._make_window()
        self._enable_mask(window)
        with patch.object(QInputDialog, "getText", return_value=("wrong-password", True)):
            with patch.object(app.QMessageBox, "warning"):
                window.privacy_mask_action.setChecked(False)
        # Wrong password on the *off* direction must leave masking on.
        self.assertTrue(window.privacy_mask_enabled)
        self.assertTrue(window.privacy_mask_action.isChecked())

        self._disable_mask(window)
        self.assertFalse(window.privacy_mask_enabled)
        self.assertFalse(window.privacy_mask_action.isChecked())

    def test_owner_contacts_tab_is_hidden_while_masked(self):
        window = self._make_window()
        index = window.detail_tabs.indexOf(window.owner_contacts_widget)
        self.assertTrue(window.detail_tabs.isTabVisible(index))

        self._enable_mask(window)
        self.assertFalse(window.detail_tabs.isTabVisible(index))

        self._disable_mask(window)
        self.assertTrue(window.detail_tabs.isTabVisible(index))

    def test_owner_name_field_is_masked_readonly_and_saving_keeps_the_real_name(self):
        window = self._make_window()
        window.set_field_text("district", "桃園區")
        window.set_field_text("section", "一段")
        window.set_field_text("land_number", "100")
        window.set_field_text("owner_name", "王小明")
        with patch.object(app.QMessageBox, "information"):
            window.save_record()
        record_id = window.selected_record_id
        self.assertIsNotNone(record_id)

        self._enable_mask(window)
        window.load_record(record_id)
        owner_name_widget = window.field_widgets["owner_name"]
        self.assertEqual(owner_name_widget.text(), "王")
        self.assertTrue(owner_name_widget.isReadOnly())

        # Saving while masked must never write the truncated display text
        # back to the database -- get_form_data() has to substitute the
        # real cached name back in.
        with patch.object(app.QMessageBox, "information"):
            window.save_record()
        saved_row = app.REPOSITORY.get_customer(record_id)
        plain = window.get_plain_record_data(saved_row)
        self.assertEqual(plain["owner_name"], "王小明")

        self._disable_mask(window)
        window.load_record(record_id)
        self.assertEqual(window.field_widgets["owner_name"].text(), "王小明")
        self.assertFalse(window.field_widgets["owner_name"].isReadOnly())

    def test_external_id_field_is_masked_to_four_digits_and_saving_keeps_the_real_value(self):
        window = self._make_window()
        window.set_field_text("district", "桃園區")
        window.set_field_text("section", "一段")
        window.set_field_text("land_number", "100")
        window.set_field_text("owner_name", "王小明")
        window.show_full_external_id = True
        window.apply_external_id_visibility()
        window.set_field_text("external_id", "A123456789")
        with patch.object(app.QMessageBox, "information"):
            window.save_record()
        record_id = window.selected_record_id

        self._enable_mask(window)
        window.load_record(record_id)
        external_id_widget = window.field_widgets["external_id"]
        self.assertEqual(external_id_widget.text(), "A123")
        self.assertTrue(external_id_widget.isReadOnly())
        self.assertFalse(window.toggle_external_id_action.isEnabled())

        # The lightweight "顯示身分證" button must not be able to defeat
        # the password-gated mask even if clicked while masked.
        window.toggle_external_id_visibility()
        self.assertEqual(external_id_widget.text(), "A123")
        self.assertTrue(external_id_widget.isReadOnly())

        with patch.object(app.QMessageBox, "information"):
            window.save_record()
        saved_row = app.REPOSITORY.get_customer(record_id)
        plain = window.get_plain_record_data(saved_row)
        self.assertEqual(plain["external_id"], "A123456789")

        self._disable_mask(window)
        self.assertTrue(window.toggle_external_id_action.isEnabled())

    def test_new_record_owner_name_field_is_locked_while_masked(self):
        # A deliberate trade-off, not an oversight: unlocking the field
        # while masked would defeat the point of the mask, so entering a
        # brand-new owner's name requires turning the mask off first.
        window = self._make_window()
        self._enable_mask(window)
        window.new_record()
        self.assertTrue(window.field_widgets["owner_name"].isReadOnly())
        self.assertEqual(window.field_widgets["owner_name"].text(), "")

    def test_main_table_display_masks_owner_name_and_external_id_when_enabled(self):
        window = self._make_window()
        window.set_field_text("district", "桃園區")
        window.set_field_text("section", "一段")
        window.set_field_text("land_number", "100")
        window.set_field_text("owner_name", "王小明")
        window.show_full_external_id = True
        window.apply_external_id_visibility()
        window.set_field_text("external_id", "A123456789")
        with patch.object(app.QMessageBox, "information"):
            window.save_record()
        record_id = window.selected_record_id

        self._enable_mask(window)
        window.refresh_records(record_id)
        row = next(row for row in window.table_model.all_rows if row["id"] == record_id)
        self.assertEqual(row["display"]["owner_name"], "王")
        self.assertEqual(row["display"]["external_id"], "A123")
        self.assertEqual(row["raw"]["owner_name"], "王小明")
        self.assertEqual(row["raw"]["external_id"], "A123456789")

    def test_mask_state_persists_across_app_restart(self):
        window = self._make_window()
        self._enable_mask(window)
        window.close()
        self._windows.remove(window)

        second_window = self._make_window()
        self.assertTrue(second_window.privacy_mask_enabled)
        self.assertTrue(second_window.privacy_mask_action.isChecked())
        index = second_window.detail_tabs.indexOf(second_window.owner_contacts_widget)
        self.assertFalse(second_window.detail_tabs.isTabVisible(index))


if __name__ == "__main__":
    unittest.main()
