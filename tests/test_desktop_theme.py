import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.fernet import Fernet
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

import customer_settings_workflows
import customer_theme
import customer_ui_qt as app
import customer_window_ui as window_ui_module
from customer_database import CustomerDatabase
from customer_land_header import ShareBarWidget, shares_from_group
from customer_repository import CustomerRepository

ROOT = Path(__file__).resolve().parents[1]


def share(record_id, name, numerator, denominator):
    from fractions import Fraction

    return {
        "record_id": record_id,
        "name": name,
        "numerator": str(numerator),
        "denominator": str(denominator),
        "fraction": Fraction(numerator, denominator),
    }


class ThemeModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        # Never touch the real settings table: use an in-memory store.
        self.store = {}
        self.saved_storage = dict(customer_theme._storage)
        self.saved_memory_key = customer_theme._memory_key
        self.saved_active_key = customer_theme.active_theme_key()
        customer_theme.configure_storage(
            lambda key, default=None: self.store.get(key, default),
            lambda key, value: self.store.__setitem__(key, value),
        )

    def tearDown(self):
        customer_theme._storage.update(self.saved_storage)
        customer_theme._memory_key = self.saved_memory_key
        customer_theme.activate_theme(self.saved_active_key)
        customer_theme.load_bundled_fonts()

    def test_stylesheets_build_for_both_themes_without_mixing_colours(self):
        light = customer_theme.build_app_stylesheet(customer_theme.LIGHT)
        dark = customer_theme.build_app_stylesheet(customer_theme.DARK)

        self.assertTrue(light.strip())
        self.assertTrue(dark.strip())
        self.assertNotIn(customer_theme.DARK["ground"].lower(), light.lower())
        self.assertNotIn(customer_theme.LIGHT["ground"].lower(), dark.lower())
        self.assertIn(customer_theme.LIGHT["green"].lower(), light.lower())
        self.assertIn(customer_theme.DARK["green"].lower(), dark.lower())

    def test_theme_key_defaults_to_light_saves_and_rejects_unknown_values(self):
        self.assertEqual(customer_theme.current_theme_key(), "light")

        self.assertEqual(customer_theme.set_theme_key("dark"), "dark")
        self.assertEqual(self.store[customer_theme.THEME_SETTING_KEY], "dark")
        self.assertEqual(customer_theme.current_theme_key(), "dark")

        self.store[customer_theme.THEME_SETTING_KEY] = "neon"
        self.assertEqual(customer_theme.current_theme_key(), "light")
        self.assertEqual(customer_theme.set_theme_key("neon"), "light")
        self.assertEqual(customer_theme.current_theme_key(), "light")

    def test_colours_follow_the_activated_theme_not_the_saved_preference(self):
        customer_theme.activate_theme("light")
        customer_theme.set_theme_key("dark")

        # The preference is for the next launch; this run keeps its colours.
        self.assertEqual(customer_theme.qcolor("ground").name().upper(), customer_theme.LIGHT["ground"])
        customer_theme.activate_theme()
        self.assertEqual(customer_theme.qcolor("ground").name().upper(), customer_theme.DARK["ground"])

    def test_bundled_heading_font_loads_and_failure_falls_back_quietly(self):
        font_file = ROOT / "assets" / "fonts" / "NotoSerifTC-Bold.otf"
        self.assertTrue(font_file.is_file())
        self.assertTrue(customer_theme.load_bundled_fonts())
        self.assertIn("Noto Serif TC", QFontDatabase.families())
        self.assertEqual(customer_theme.heading_font(13).family(), "Noto Serif TC")

        with patch.object(
            customer_theme, "bundled_font_path", return_value=ROOT / "assets" / "fonts" / "missing.otf"
        ):
            self.assertFalse(customer_theme.load_bundled_fonts())
        self.assertEqual(customer_theme.heading_font(13).family(), "Microsoft JhengHei UI")
        self.assertTrue(customer_theme.heading_font(13).bold())

    def test_packaging_ships_the_font_together_with_its_licence(self):
        build_script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

        self.assertIn(r'--add-data "assets\fonts;assets\fonts"', build_script)
        self.assertTrue((ROOT / "assets" / "fonts" / "OFL.txt").is_file())
        self.assertIn("SIL OPEN FONT LICENSE", (ROOT / "assets" / "fonts" / "OFL.txt").read_text(encoding="utf-8").upper())

    def test_no_stray_hex_colours_outside_the_theme(self):
        import re

        allowed = {
            "customer_theme.py",
            "customer_tag_display.py",  # tag defaults / contrast rule
            "customer_productivity.py",  # the stand-alone map HTML
            "customer_mobile_share.py",  # the stand-alone phone page HTML
            "customer_extra_dialogs.py",  # the colour dialog's own default
            "customer_table_ui.py",  # the default tag colour of the +N pill
        }
        pattern = re.compile(r"#[0-9a-fA-F]{6}\b")
        offenders = []
        for path in sorted(ROOT.glob("customer_*.py")):
            if path.name in allowed:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [])


class ShareBarWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def make_bar(self, shares, selected=None):
        bar = ShareBarWidget()
        bar.resize(400, 60)
        bar.set_shares(shares, selected)
        return bar

    def test_segment_widths_follow_the_shares_and_a_click_picks_the_owner(self):
        bar = self.make_bar([share(11, "甲", 1, 2), share(12, "乙", 1, 4), share(13, "丙", 1, 4)], 11)
        widths = bar.segment_widths()

        self.assertAlmostEqual(widths[0] / widths[1], 2.0, places=3)
        self.assertAlmostEqual(widths[1] / widths[2], 1.0, places=3)
        picked = []
        bar.ownerClicked.connect(picked.append)
        QTest.mouseClick(
            bar, Qt.LeftButton, Qt.NoModifier, bar.segment_rects()[1].center().toPoint()
        )
        self.assertEqual(picked, [12])

    def test_keyboard_moves_between_segments_and_enter_selects(self):
        bar = self.make_bar([share(11, "甲", 1, 2), share(12, "乙", 1, 2)], 11)
        bar.show()
        bar.setFocus()
        picked = []
        bar.ownerClicked.connect(picked.append)

        QTest.keyClick(bar, Qt.Key_Right)
        self.assertIn("乙", bar.accessibleName())
        QTest.keyClick(bar, Qt.Key_Return)

        self.assertEqual(picked, [12])
        bar.close()

    def test_summary_flags_totals_that_are_not_one(self):
        exact = self.make_bar([share(1, "甲", 1, 2), share(2, "乙", 1, 2)])
        short = self.make_bar([share(1, "甲", 1, 2), share(2, "乙", 1, 4)])
        over = self.make_bar([share(1, "甲", 1, 2), share(2, "乙", 3, 4)])

        self.assertIn("合計 1/1", exact.summary_text())
        self.assertFalse(exact.summary_is_warning())
        self.assertIn("合計未滿 1", short.summary_text())
        self.assertTrue(short.summary_is_warning())
        self.assertIn("合計超過 1", over.summary_text())
        self.assertTrue(over.summary_is_warning())
        # Over 1 still fits inside the bar.
        self.assertAlmostEqual(sum(over.segment_widths()), 400.0, places=3)

    def test_segment_text_and_tooltip_use_the_displayed_masked_name(self):
        group = SimpleNamespace(
            records=[
                {
                    "id": 5,
                    "raw": {"numerator": "1", "denominator": "2", "owner_name": "王大明"},
                    "display": {"owner_name": "王○○"},
                },
                {
                    "id": 6,
                    "raw": {"numerator": "1", "denominator": "2", "owner_name": "李小華"},
                    "display": {"owner_name": "李○○"},
                },
                {  # no usable share: not drawn
                    "id": 7,
                    "raw": {"numerator": "0", "denominator": "2", "owner_name": "陳美玲"},
                    "display": {"owner_name": "陳○○"},
                },
            ]
        )
        bar = self.make_bar(shares_from_group(group), 5)

        self.assertEqual(len(bar.shares()), 2)
        shown = " ".join(bar.segment_texts() + bar.segment_tooltips() + [bar.accessibleName()])
        self.assertIn("王○○", shown)
        for plain in ("王大明", "李小華", "陳美玲"):
            self.assertNotIn(plain, shown)


class DesktopWindowThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.originals = {
            name: getattr(app, name)
            for name in ("DB_PATH", "BACKUP_DIR", "DATABASE", "REPOSITORY")
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
        self.windows = []
        self.saved_memory_key = customer_theme._memory_key

    def tearDown(self):
        # Close while this test's database still exists (closing saves state).
        for window in self.windows:
            window.close()
        self.windows.clear()
        self.application.processEvents()
        customer_theme._memory_key = self.saved_memory_key
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def wait_for_record_searches(self, window, timeout_ms=12000):
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if not window.record_searches else None)
        poll.start(10)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        poll.stop()
        self.assertFalse(window.record_searches, "背景搜尋未在時限內結束")

    def add_record(self, window, land_number, owner, numerator="1", denominator="2"):
        plain = window.normalize_record_data(
            {
                "district": "D",
                "section": "S",
                "subsection": "",
                "land_number": land_number,
                "area": "100",
                "declared_value": "1000",
                "numerator": numerator,
                "denominator": denominator,
                "owner_name": owner,
                "external_id": "",
                "address": "Address",
                "note": "",
                "name": owner,
            }
        )
        return app.REPOSITORY.save_customer(app.encrypt_record(window.fernet, plain))

    def open_window(self):
        window = app.LandApp(Fernet.generate_key())
        self.windows.append(window)
        return window

    # -- batch bar ----------------------------------------------------------------

    def test_batch_bar_appears_only_while_rows_are_checked(self):
        window = self.open_window()
        first_id = self.add_record(window, "100", "Owner 1")
        window.refresh_records(first_id)
        self.wait_for_record_searches(window)

        self.assertTrue(window.batch_bar.isHidden())
        window.update_checked_records([first_id], True, "測試")
        self.assertFalse(window.batch_bar.isHidden())
        self.assertIn("已勾選 1 筆", window.batch_bar_count_label.text())

        window.clear_checked_selection()
        self.assertTrue(window.batch_bar.isHidden())

    def test_batch_bar_buttons_drive_the_existing_actions(self):
        window = self.open_window()
        first_id = self.add_record(window, "100", "Owner 1")
        window.refresh_records(first_id)
        window.update_checked_records([first_id], True, "測試")

        with patch.object(window, "batch_edit_checked_records") as batch_edit, patch.object(
            window, "clear_checked_selection"
        ) as clear_checked:
            window.batch_bar_buttons["batch_edit_action"].click()
            window.batch_bar_buttons["clear_checked_action"].click()

        batch_edit.assert_called_once()
        clear_checked.assert_called_once()

    def test_batch_bar_edit_buttons_follow_readonly_mode(self):
        window = self.open_window()
        first_id = self.add_record(window, "100", "Owner 1")
        window.refresh_records(first_id)
        window.update_checked_records([first_id], True, "測試")
        edit_button = window.batch_bar_buttons["batch_edit_action"]

        self.assertTrue(edit_button.isEnabled())
        window.toggle_readonly_mode(True)
        self.assertFalse(edit_button.isEnabled())
        # Exporting and clearing the ticks stay available.
        self.assertTrue(window.batch_bar_buttons["export_selected_action"].isEnabled())
        self.assertTrue(window.batch_bar_buttons["clear_checked_action"].isEnabled())
        window.toggle_readonly_mode(False)
        self.assertTrue(edit_button.isEnabled())

    # -- detail panel -------------------------------------------------------------

    def test_land_header_shows_the_selected_land_and_its_owners(self):
        window = self.open_window()
        first_id = self.add_record(window, "100", "Owner 1", "1", "4")
        second_id = self.add_record(window, "100", "Owner 2", "3", "4")
        window.refresh_records(first_id)
        self.wait_for_record_searches(window)
        window.load_record(first_id)

        header = window.land_header
        self.assertEqual(header.land_number_label.text(), "100")
        self.assertIn("D", header.location_label.text())
        self.assertFalse(header.share_bar.isHidden())
        self.assertEqual(
            sorted(item["record_id"] for item in header.share_bar.shares()),
            sorted([first_id, second_id]),
        )
        self.assertIn("合計 1/1", header.share_bar.summary_text())

        picked = []
        window.select_record_in_table = picked.append
        header.share_bar.ownerClicked.emit(second_id)
        self.assertEqual(picked, [second_id])

        window.new_record()
        self.assertEqual(header.land_number_label.text(), "新增資料")
        self.assertTrue(header.share_bar.isHidden())

    def test_save_state_label_tracks_user_edits_only(self):
        window = self.open_window()
        record_id = self.add_record(window, "100", "Owner 1")
        window.refresh_records(record_id)
        self.wait_for_record_searches(window)
        window.load_record(record_id)

        self.assertEqual(window.save_state_label.text(), "")
        window.set_field_text("note", "載入的備註")  # programmatic: not an edit
        self.assertEqual(window.save_state_label.text(), "")

        window.fields["address"].textEdited.emit("新地址")
        self.assertEqual(window.save_state_label.text(), window_ui_module.SAVE_STATE_DIRTY_TEXT)

        window.mark_form_saved()
        self.assertEqual(window.save_state_label.text(), window_ui_module.SAVE_STATE_SAVED_TEXT)
        window.new_record()
        self.assertEqual(window.save_state_label.text(), "")

        window.fields["address"].textEdited.emit("又改")
        window.load_record(record_id)
        self.assertEqual(window.save_state_label.text(), "")

    def test_form_is_a_zero_gap_grid_with_the_register_section_titles(self):
        window = self.open_window()

        self.assertEqual(window.basic_data_form_layout.horizontalSpacing(), 0)
        self.assertEqual(window.basic_data_form_layout.verticalSpacing(), 0)
        self.assertEqual(window_ui_module.LAND_SECTION_HEADERS["land"], "土地標示部")
        self.assertEqual(window_ui_module.LAND_SECTION_HEADERS["owner"], "土地所有權部")
        self.assertEqual(
            window.form_frame.findChild(QLabel, "landSectionHeader").text(), "土地標示部"
        )
        self.assertEqual(
            window.form_frame.findChild(QLabel, "ownerSectionHeader").text(), "土地所有權部"
        )
        outer_cells = [
            window.form_field_containers[key]
            for key in ("district", "section")
        ]
        self.assertTrue(all(cell.property("firstRow") for cell in outer_cells))
        self.assertTrue(window.form_field_containers["district"].property("firstCol"))
        self.assertTrue(window.form_field_containers["section"].property("lastCol"))

    def test_row_height_and_theme_menu_entry(self):
        window = self.open_window()

        self.assertGreaterEqual(window.table_view.verticalHeader().default_size, 34)
        self.assertEqual(window.management_summary_header.text(), "管理摘要")
        labels = [action.text() for action in window.settings_menu.actions()]
        self.assertIn("外觀主題", labels)
        self.assertEqual(labels.index("外觀主題"), labels.index("字體大小") + 1)

    def test_choosing_a_theme_saves_it_and_asks_for_a_restart(self):
        window = self.open_window()
        self.assertEqual(customer_theme.current_theme_key(), "light")

        with patch.object(app, "QMessageBox", MagicMock()) as box, patch.object(
            customer_settings_workflows.QInputDialog,
            "getItem",
            return_value=("深色", True),
        ):
            self.assertTrue(window.change_theme())

        self.assertEqual(customer_theme.current_theme_key(), "dark")
        box.information.assert_called_once()
        self.assertIn("重新啟動", box.information.call_args.args[2])

    def test_status_bar_shows_connection_login_mask_and_version(self):
        window = self.open_window()

        self.assertEqual(window.status_connection_label.text(), "單機版（本機資料庫）")
        self.assertTrue(window.status_user_label.text().startswith("登入："))
        self.assertEqual(window.status_mask_label.text(), "身分證遮罩：關閉")
        self.assertTrue(window.status_version_label.text().startswith("土地資料系統 v"))
        window.privacy_mask_enabled = True
        window.refresh_status_bar_content()
        self.assertEqual(window.status_mask_label.text(), "身分證遮罩：開啟")


if __name__ == "__main__":
    unittest.main()
