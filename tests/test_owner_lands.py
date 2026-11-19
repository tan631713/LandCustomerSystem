"""基本資料頂端「名下其他土地」標籤列：歸戶、排序、摘要、點擊切換。"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import customer_ui_qt as app  # noqa: E402
from customer_database import CustomerDatabase  # noqa: E402
from customer_desktop_api import DesktopApiRecordRepository  # noqa: E402
from customer_owner_lands import (  # noqa: E402
    VISIBLE_CHIP_LIMIT,
    basis_text,
    build_owner_index,
    chip_label,
    chip_tooltip,
    order_holdings,
    share_text,
    short_district,
    total_ping,
)
from customer_repository import CustomerRepository  # noqa: E402
from customer_security import make_fernet  # noqa: E402

from tests.test_desktop_save_latency import FakeHomeServer  # noqa: E402


def record(record_id, district="桃園區", section="中路段", land_number="1", area="100",
           numerator="1", denominator="1", **raw):
    values = {
        "district": district, "section": section, "subsection": "", "land_number": land_number,
        "area": area, "numerator": numerator, "denominator": denominator, **raw,
    }
    return {"id": record_id, "raw": values, "display": dict(values)}


class HelperTests(unittest.TestCase):
    def test_chip_label_adds_short_district_only_when_it_differs(self):
        raw = {"district": "八德區", "section": "大湳段", "land_number": "56"}
        self.assertEqual(chip_label(raw, "桃園區"), "八德 大湳段 56")
        self.assertEqual(chip_label(raw, "八德區"), "大湳段 56")
        self.assertEqual(short_district("區"), "區")
        self.assertEqual(chip_label({}, ""), "未填地號")

    def test_share_text(self):
        self.assertEqual(share_text({"numerator": "1", "denominator": "3"}), "1/3")
        self.assertEqual(share_text({}), "")

    def test_order_current_first_then_same_district_then_natural_land_number(self):
        records = [
            record(1, land_number="123"),
            record(2, district="八德區", section="大湳段", land_number="56"),
            record(3, land_number="130-2"),
            record(4, land_number="124"),
            record(5, land_number="13"),
        ]
        ordered = [item["id"] for item in order_holdings(records, 1)]
        self.assertEqual(ordered, [1, 5, 4, 3, 2])

    def test_total_ping_sums_ownership_area(self):
        records = [record(1, area="100", numerator="1", denominator="2"), record(2, area="", numerator="1")]
        self.assertAlmostEqual(total_ping(records), 50 * 0.3025)
        self.assertIsNone(total_ping([record(3, area="")]))

    def test_tooltip_lists_full_number_share_area_use_and_tags(self):
        item = record(1, area="400", numerator="1", denominator="3", full_land_number="八德區 大湳段 56",
                      land_use="農業區", tag_names="追蹤中")
        text = chip_tooltip(item)
        self.assertIn("八德區 大湳段 56 地號", text)
        self.assertIn("持分 1/3", text)
        self.assertIn("持分面積 40.3 坪", text)
        self.assertIn("農業區", text)
        self.assertIn("標籤：追蹤中", text)
        self.assertIn("點一下切換到這筆", text)
        self.assertIn("目前這筆", chip_tooltip(item, current=True))

    def test_basis_uses_the_identity_as_shown_on_the_form(self):
        item = record(1, external_id="H2211")
        item["display"]["external_id"] = "H2***"
        self.assertEqual(basis_text(item), "ⓘ 依身分證 H2*** 歸戶")
        self.assertEqual(basis_text(record(2, external_id="")), "ⓘ 依姓名＋地址歸戶")

    def test_index_prefers_owner_id_and_falls_back_to_identity(self):
        rows = [
            {"id": 1, "owner_id": 7}, {"id": 2, "owner_id": 7}, {"id": 3, "owner_id": 8},
            {"id": 4, "owner_id": None, "x": "H2211"}, {"id": 5, "owner_id": None, "x": "h2211 "},
        ]
        index = build_owner_index(
            rows, lambda row: {"external_id": row["x"], "owner_name": "", "address": ""}
        )
        self.assertEqual([row["id"] for row in index[("owner_id", 7)]], [1, 2])
        self.assertEqual([row["id"] for row in index[("external_id", "h2211")]], [4, 5])


def wait_for_search(application, window):
    loop = QEventLoop()
    for _attempt in range(300):
        if not window.record_searches:
            break
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    application.processEvents()


class _WindowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.originals = {
            name: getattr(app, name) for name in ("DB_PATH", "BACKUP_DIR", "DATABASE", "REPOSITORY")
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
        self.window = self.make_window()
        self.application.processEvents()

    def tearDown(self):
        self.window.wait_for_background_tasks()
        self.window.close()
        self.application.processEvents()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()


class LocalDatabaseTests(_WindowCase):
    """單機資料庫：沒有 owner_id，依身分證（沒有時姓名＋地址）歸戶。"""

    OWNER = {"owner_name": "王小明", "external_id": "H2211", "address": "桃園市桃園區中正路 100 號"}
    LANDS = (
        ("桃園區", "中路段", "123", "100", "1", "2", OWNER),
        ("桃園區", "中路段", "123", "100", "1", "2",
         {"owner_name": "李小華", "external_id": "A1234", "address": "桃園市"}),
        ("桃園區", "中路段", "124", "330", "1", "1", OWNER),
        ("桃園區", "中路段", "130-2", "166.6", "1", "4", OWNER),
        ("八德區", "大湳段", "56", "400", "1", "3", OWNER),
        ("蘆竹區", "南崁段", "812", "500", "1", "2", OWNER),
    )

    def make_window(self):
        return app.LandApp(self.key)

    def add_lands(self):
        ids = []
        for district, section, number, area, numerator, denominator, owner in self.LANDS:
            plain = self.window.normalize_record_data({
                "district": district, "section": section, "subsection": "", "land_number": number,
                "area": area, "declared_value": "1000", "numerator": numerator,
                "denominator": denominator, "note": "", "name": owner["owner_name"], **owner,
            })
            ids.append(app.REPOSITORY.save_customer(app.encrypt_record(self.window.fernet, plain)))
        self.window.refresh_records(ids[0])
        wait_for_search(self.application, self.window)
        return ids

    def test_bar_lists_every_land_of_the_owner_and_folds_extra_chips(self):
        ids = self.add_lands()
        self.assertTrue(self.window.select_record_in_table(ids[0]))
        bar = self.window.owner_lands_bar
        self.assertFalse(bar.isHidden())
        self.assertEqual(bar.summary_plain_text(), "王小明 名下共 5 筆土地")
        self.assertEqual(bar.total_label.text(), "合計 243.5 坪")
        self.assertEqual(
            bar.chip_texts(),
            ["中路段 123 1/2", "中路段 124 1/1", "中路段 130-2 1/4", "八德 大湳段 56 1/3", "＋1 筆 ▾"],
        )
        self.assertTrue(bar.chips[0].property("current"))
        self.assertIn("H2211", bar.basis_label.text())
        bar.chips[-1].clicked.emit()
        self.assertEqual(len(bar.chips), 6)
        self.assertEqual(bar.chip_texts()[-2:], ["蘆竹 南崁段 812 1/2", "收合 ▴"])
        bar.chips[-1].clicked.emit()
        self.assertEqual(len(bar.chips), VISIBLE_CHIP_LIMIT + 1)

    def test_other_owner_on_the_same_land_has_only_its_own_land(self):
        ids = self.add_lands()
        self.window.select_record_in_table(ids[1])
        bar = self.window.owner_lands_bar
        self.assertEqual(bar.summary_plain_text(), "李小華 名下共 1 筆土地")
        self.assertEqual(bar.chip_texts(), ["中路段 123 1/2"])

    def test_clicking_a_chip_opens_that_record(self):
        ids = self.add_lands()
        self.window.select_record_in_table(ids[0])
        bar = self.window.owner_lands_bar
        bar.chips[1].clicked.emit()
        self.application.processEvents()
        self.assertEqual(self.window.selected_record_id, ids[2])
        self.assertEqual(self.window.get_field_text("land_number"), "124")
        self.assertTrue(self.window.owner_lands_bar.chips[0].property("current"))

    def test_chip_outside_the_search_result_still_opens(self):
        ids = self.add_lands()
        self.window.search_input.setText("中路段")
        self.window.refresh_records(ids[0])
        wait_for_search(self.application, self.window)
        self.window.select_record_in_table(ids[0])
        bar = self.window.owner_lands_bar
        self.assertEqual(bar.summary_plain_text(), "王小明 名下共 5 筆土地")
        target = next(chip for chip in bar.chips if chip.text().startswith("八德"))
        target.clicked.emit()
        self.application.processEvents()
        self.assertEqual(self.window.selected_record_id, ids[4])
        self.assertEqual(self.window.get_field_text("section"), "大湳段")

    def test_share_bar_shows_in_plan_view_and_switches_owner(self):
        ids = self.add_lands()
        self.window.select_record_in_table(ids[0])
        self.window.plan_view_active = lambda: True
        self.window.load_record(ids[0])
        bar = self.window.land_header.share_bar
        self.assertFalse(bar.isHidden())
        self.assertEqual(sorted(item["record_id"] for item in bar.shares()), sorted(ids[:2]))
        self.window.land_header.ownerClicked.emit(ids[1])
        self.application.processEvents()
        self.assertEqual(self.window.selected_record_id, ids[1])
        self.assertEqual(self.window.owner_lands_bar.summary_plain_text(), "李小華 名下共 1 筆土地")

    def test_share_bar_shows_for_a_record_outside_the_search_result(self):
        ids = self.add_lands()
        self.window.search_input.setText("南崁段")
        self.window.refresh_records(ids[0])
        wait_for_search(self.application, self.window)
        self.window.load_record(ids[0])
        shares = self.window.land_header.share_bar.shares()
        self.assertEqual(sorted(item["record_id"] for item in shares), sorted(ids[:2]))

    def test_new_record_hides_the_bar(self):
        ids = self.add_lands()
        self.window.select_record_in_table(ids[0])
        self.window.new_record()
        self.assertTrue(self.window.owner_lands_bar.isHidden())

    def test_bar_sits_above_the_form_in_the_basic_tab(self):
        basic_layout = self.window.basic_data_scroll_area.parentWidget().layout()
        self.assertLess(
            basic_layout.indexOf(self.window.owner_lands_bar),
            basic_layout.indexOf(self.window.basic_data_scroll_area),
        )


class HomeServerTests(_WindowCase):
    """家中伺服器：依伺服器給的 owner_id 歸戶，不另外發請求。"""

    def make_window(self):
        self.server = FakeHomeServer(6)
        for row in self.server.rows:
            if row["id"] in (2, 4, 6):
                row["owner_id"] = 2
                row["owner_name"] = "王大明2"
        repository = DesktopApiRecordRepository(self.server, make_fernet(self.key))
        window = app.LandApp(self.key, record_repository=repository, api_mode=True)
        window.wait_for_background_tasks()
        return window

    def test_groups_by_owner_id_without_extra_requests(self):
        wait_for_search(self.application, self.window)
        before = self.server.count("list all records")
        self.window.load_record(4)
        bar = self.window.owner_lands_bar
        self.assertEqual(bar.summary_plain_text(), "王大明2 名下共 3 筆土地")
        self.assertEqual(len(bar.chips), 3)
        self.assertEqual(self.server.count("list all records"), before)
        self.window.load_record(5)
        self.assertEqual(bar.summary_plain_text(), "王大明5 名下共 1 筆土地")


if __name__ == "__main__":
    unittest.main()
