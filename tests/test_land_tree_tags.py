import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import customer_ui_qt as app  # noqa: F401 - configures table dependencies
from customer_models import (
    TAGS_ROLE,
    LandTreeProxyModel,
    RecordTableModel,
)
from customer_table_ui import LandTreeView, TagPillDelegate
from customer_tag_display import (
    DEFAULT_TAG_COLOR,
    normalize_tag_color,
    tag_text_qcolor,
)
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem


def tagged_record(record_id, land_id, owner_id, tags, *, owner_name="地主"):
    names = "、".join(item["name"] for item in tags)
    raw = {
        "rowid": str(record_id),
        "land_id": land_id,
        "owner_id": owner_id,
        "ownership_id": record_id,
        "district": "桃園市",
        "section": "中路段",
        "land_number": "1-3",
        "area": "100",
        "declared_value": "1000",
        "registration_order": str(record_id),
        "numerator": "1",
        "denominator": "2",
        "ping": "",
        "total_declared_value": "",
        "owner_name": owner_name,
        "external_id": "",
        "address": "地址",
        "registration_reason": "",
        "note": "",
        "visit_log": "",
        "case_names": "",
        "tag_names": names,
        "tag_items": list(tags),
        "attachment_count": "0",
        "attachment_names": "",
        "custom_values": "",
        "last_contact": "",
        "next_follow_up": "",
        "follow_up_status": "",
        "customer_status": "",
        "phone": "",
        "land_use": "住宅區",
    }
    return {
        "id": record_id,
        "ownership_id": record_id,
        "land_id": land_id,
        "owner_id": owner_id,
        "checked": False,
        "is_watchlist": False,
        "is_overdue": False,
        "has_note": False,
        "tags": list(tags),
        "tag_color": tags[0]["color"] if tags else "",
        "background": None,
        "highlighted_fields": set(),
        "raw": raw,
        "display": dict(raw),
    }


class LandTreeTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.tag_column = next(
            index
            for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
            if key == "tag_names"
        )

    def _model(self, rows):
        model = RecordTableModel(lambda *_args: None)
        model.set_rows(rows)
        return model

    def test_single_and_multiple_tags_keep_each_name_and_color(self):
        tags = [
            {"tag_id": 1, "name": "優先", "color": "#FF0000"},
            {"tag_id": 2, "name": "已拜訪", "color": "#00AA66"},
        ]
        model = self._model([tagged_record(1, 10, 20, tags)])
        parent = model.index(0, 0)
        child_tag = model.index(0, self.tag_column, parent)

        self.assertEqual(model.data(child_tag, Qt.DisplayRole), "優先、已拜訪")
        self.assertEqual(model.data(child_tag, TAGS_ROLE), tags)
        self.assertFalse(model.data(child_tag, Qt.DecorationRole).isNull())

    def test_parent_deduplicates_complete_tags_while_children_stay_separate(self):
        first = [{"tag_id": 1, "name": "優先", "color": "#FF0000"}]
        second = [
            {"tag_id": 1, "name": "優先", "color": "#FF0000"},
            {"tag_id": 2, "name": "已拜訪", "color": "#00AA66"},
        ]
        model = self._model(
            [
                tagged_record(1, 10, 20, first, owner_name="甲"),
                tagged_record(2, 10, 21, second, owner_name="乙"),
            ]
        )
        parent_tag = model.index(0, self.tag_column)
        parent = model.index(0, 0)
        first_child = model.index(0, self.tag_column, parent)
        second_child = model.index(1, self.tag_column, parent)

        self.assertEqual(
            model.data(parent_tag, TAGS_ROLE),
            [
                {"tag_id": 1, "name": "優先", "color": "#FF0000"},
                {"tag_id": 2, "name": "已拜訪", "color": "#00AA66"},
            ],
        )
        self.assertEqual(model.data(first_child, TAGS_ROLE), first)
        self.assertEqual(model.data(second_child, TAGS_ROLE), second)

    def test_invalid_and_blank_colors_use_safe_default(self):
        rows = [
            tagged_record(
                1,
                10,
                20,
                [
                    {"tag_id": 1, "name": "空白", "color": ""},
                    {"tag_id": 2, "name": "無效", "color": "red"},
                ],
            )
        ]
        model = self._model(rows)
        parent = model.index(0, 0)
        tags = model.data(model.index(0, self.tag_column, parent), TAGS_ROLE)
        self.assertEqual([item["color"] for item in tags], [DEFAULT_TAG_COLOR] * 2)
        self.assertEqual(normalize_tag_color("not-a-color"), DEFAULT_TAG_COLOR)

    def test_tag_change_refreshes_all_roles_without_restarting_or_losing_color(self):
        original = tagged_record(
            1,
            10,
            20,
            [{"tag_id": 1, "name": "優先", "color": "#FF0000"}],
        )
        model = self._model([original])
        emissions = []
        model.dataChanged.connect(
            lambda _top, _bottom, roles: emissions.append(list(roles))
        )
        changed = tagged_record(
            1,
            10,
            20,
            [{"tag_id": 1, "name": "優先", "color": "#0055FF"}],
        )

        self.assertTrue(model.update_rows_in_place([changed]))
        parent = model.index(0, 0)
        child_tag = model.index(0, self.tag_column, parent)
        self.assertEqual(model.data(child_tag, TAGS_ROLE)[0]["color"], "#0055FF")
        required = {
            Qt.DisplayRole,
            Qt.BackgroundRole,
            Qt.ForegroundRole,
            Qt.DecorationRole,
            TAGS_ROLE,
        }
        self.assertTrue(any(required.issubset(set(roles)) for roles in emissions))

        model.set_rows([changed])
        parent = model.index(0, 0)
        child_tag = model.index(0, self.tag_column, parent)
        self.assertEqual(model.data(child_tag, TAGS_ROLE)[0]["color"], "#0055FF")

    def test_delegate_remains_installed_after_set_model(self):
        tree = LandTreeView()
        delegate = TagPillDelegate(tree)
        tree.configure_tag_delegate(delegate, self.tag_column)
        first_proxy = LandTreeProxyModel(tree)
        first_proxy.setSourceModel(self._model([]))
        tree.setModel(first_proxy)
        self.assertIs(tree.itemDelegateForColumn(self.tag_column), delegate)

        second_proxy = LandTreeProxyModel(tree)
        second_proxy.setSourceModel(self._model([]))
        tree.setModel(second_proxy)
        self.assertIs(tree.itemDelegateForColumn(self.tag_column), delegate)
        tree.close()

    def test_selected_tag_pills_paint_and_light_dark_text_are_readable(self):
        model = self._model(
            [
                tagged_record(
                    1,
                    10,
                    20,
                    [
                        {"tag_id": 1, "name": "亮色", "color": "#FFFF00"},
                        {"tag_id": 2, "name": "深色", "color": "#003366"},
                    ],
                )
            ]
        )
        parent = model.index(0, 0)
        index = model.index(0, self.tag_column, parent)
        delegate = TagPillDelegate()
        image = QImage(320, 42, QImage.Format_ARGB32)
        image.fill(QColor("#202020"))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 320, 42)
        option.state = QStyle.State_Enabled | QStyle.State_Selected
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        self.assertEqual(tag_text_qcolor("#FFFF00"), QColor("#111827"))
        self.assertEqual(tag_text_qcolor("#003366"), QColor("#FFFFFF"))
        self.assertNotEqual(image.pixelColor(20, 20), QColor("#202020"))


if __name__ == "__main__":
    unittest.main()
