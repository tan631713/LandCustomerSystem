import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import customer_ui_qt as app  # noqa: F401 - configures model dependencies
from cryptography.fernet import Fernet
from customer_land_tree import (
    group_land_records,
    normalized_land_number_key,
    ownership_area,
)
from customer_models import CHECK_COLUMN, LandTreeProxyModel, RecordTableModel
from customer_api.postgres_source import PostgreSQLCustomerDataSource
from customer_record_workflows import RecordWorkflowMixin
from customer_search_controller import SearchControllerMixin
from customer_selection_workflows import SelectionWorkflowMixin
from customer_search import CustomerRecordProcessor
from customer_security import make_fernet
from customer_table_ui import (
    LandTreeView,
    TagPillDelegate,
    apply_land_tree_visual_style,
)
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QStyle,
    QStyleOptionViewItem,
    QTreeView,
)


def record(
    record_id,
    *,
    land_id,
    owner_id,
    district="彰化縣員林市",
    section="中路段",
    subsection="",
    land_number="1-3",
    area="100",
    owner_name="王大明",
    numerator="1",
    denominator="2",
    address="地址",
    phone="0912345678",
    status="待追蹤",
    note="備註",
):
    raw = {
        "rowid": str(record_id),
        "land_id": land_id,
        "owner_id": owner_id,
        "ownership_id": record_id,
        "district": district,
        "section": section,
        "subsection": subsection,
        "land_number": land_number,
        "area": area,
        "declared_value": "1000",
        "registration_order": str(record_id),
        "numerator": numerator,
        "denominator": denominator,
        "ping": "",
        "total_declared_value": "",
        "owner_name": owner_name,
        "external_id": "",
        "address": address,
        "registration_reason": "",
        "note": note,
        "visit_log": "",
        "case_names": "",
        "tag_names": "",
        "attachment_count": "0",
        "attachment_names": "",
        "custom_values": "",
        "last_contact": "",
        "next_follow_up": "",
        "follow_up_status": status,
        "customer_status": status,
        "phone": phone,
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
        "has_note": bool(note),
        "tag_color": "",
        "background": None,
        "highlighted_fields": set(),
        "raw": raw,
        "display": dict(raw),
    }


def database_row(
    record_id,
    *,
    land_id,
    owner_id,
    owner_name,
    section="中路段",
    subsection="",
    land_number="1-3",
):
    return {
        "id": record_id,
        "ownership_id": record_id,
        "land_id": land_id,
        "owner_id": owner_id,
        "district": "桃園市桃園區",
        "section": section,
        "subsection": subsection,
        "registration_order": str(record_id),
        "land_number": land_number,
        "area": "100",
        "declared_value": "1000",
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
        "tag_names": "",
        "primary_tag_color": "",
        "attachment_count": 0,
        "attachment_names": "",
        "custom_values": "電話：0912345678；使用分區：住宅區",
        "last_contact": "",
        "next_follow_up": "",
        "follow_up_status": "待追蹤",
    }


class _WorkflowHarness(
    RecordWorkflowMixin,
    SelectionWorkflowMixin,
    SearchControllerMixin,
):
    def __init__(self, rows):
        self.table_model = RecordTableModel(lambda *_args: None)
        self.table_model.set_rows(rows)
        self.table_proxy_model = LandTreeProxyModel()
        self.table_proxy_model.setSourceModel(self.table_model)
        self.table_view = QTreeView()
        self.table_view.setModel(self.table_proxy_model)
        self.table_view.setExpandsOnDoubleClick(False)
        self.table_view.expanded.connect(self.on_land_group_expanded)
        self.table_view.collapsed.connect(self.on_land_group_collapsed)
        self.expanded_land_ids = set()
        self.search_expanded_land_ids = set()
        self.restoring_tree_state = False
        self.applying_programmatic_expansion = False
        self._applying_land_expansion = False
        self._land_search_auto_expand = False
        self._land_tree_restore_generation = 0
        self.loaded_record_id = None
        self.detail_tabs = None
        self.selected_record_id = None
        self.search_input = QLineEdit()
        self.show_checked_only = False
        self.advanced_search_criteria = {}

    def load_record(self, record_id):
        self.loaded_record_id = record_id

    def apply_table_preferences(self):
        return None

    def update_land_page_status(self):
        return None


class LandTreeGroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_grouping_uses_land_id_and_preserves_each_ownership(self):
        rows = [
            record(11, land_id=7, owner_id=1, owner_name="甲", area="1250"),
            record(12, land_id=7, owner_id=2, owner_name="乙", area="1250"),
            record(13, land_id=8, owner_id=3, owner_name="丙", area="1250"),
        ]
        result = group_land_records(rows)

        self.assertEqual(len(result.groups), 2)
        first = next(group for group in result.groups if group.land_id == 7)
        self.assertEqual(first.owner_count, 2)
        self.assertEqual(first.ownership_count, 2)
        self.assertEqual(first.area, "1250")
        self.assertEqual(first.record_ids, [11, 12])
        self.assertEqual({row["raw"]["owner_name"] for row in first.records}, {"甲", "乙"})

    def test_postgresql_record_response_select_contains_real_relation_ids(self):
        normalized = " ".join(PostgreSQLCustomerDataSource.RECORD_SELECT.split())
        self.assertIn("ownership.id AS ownership_id", normalized)
        self.assertIn("land.id AS land_id", normalized)
        self.assertIn("owner.id AS owner_id", normalized)

    def test_same_number_in_different_land_or_section_is_never_merged(self):
        rows = [
            record(1, land_id=101, owner_id=1, section="甲段", land_number="10"),
            record(2, land_id=102, owner_id=2, section="甲段", land_number="10"),
            record(3, land_id=None, owner_id=3, section="乙段", land_number="10"),
            record(4, land_id=None, owner_id=4, section="丙段", land_number="10"),
        ]
        self.assertEqual(len(group_land_records(rows).groups), 4)

    def test_owner_search_keeps_land_context_and_only_matching_children(self):
        rows = [
            database_row(1, land_id=9, owner_id=1, owner_name="王大明"),
            database_row(2, land_id=9, owner_id=2, owner_name="李小華"),
            database_row(3, land_id=10, owner_id=3, owner_name="陳先生"),
        ]
        processor = CustomerRecordProcessor(
            fernet=make_fernet(Fernet.generate_key()),
            table_columns=app.TABLE_COLUMNS,
            keyword="王大明",
            filter_field="owner_name",
        )
        result = processor.process(rows)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].land_id, 9)
        self.assertEqual(
            [item["raw"]["owner_name"] for item in result.groups[0].records],
            ["王大明"],
        )

    def test_land_search_keeps_all_matching_land_children_and_clear_restores(self):
        rows = [
            database_row(1, land_id=9, owner_id=1, owner_name="王大明"),
            database_row(2, land_id=9, owner_id=2, owner_name="李小華"),
            database_row(
                3,
                land_id=10,
                owner_id=3,
                owner_name="陳先生",
                section="其他段",
            ),
        ]
        fernet = make_fernet(Fernet.generate_key())
        filtered = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=app.TABLE_COLUMNS,
            keyword="中路",
            filter_field="section",
        ).process(rows)
        self.assertEqual(len(filtered.groups), 1)
        self.assertEqual(filtered.groups[0].ownership_count, 2)
        restored = CustomerRecordProcessor(
            fernet=fernet,
            table_columns=app.TABLE_COLUMNS,
        ).process(rows)
        self.assertEqual(len(restored.groups), 2)
        self.assertEqual(len(restored), 3)

    def test_owner_count_deduplicates_owner_id_but_not_ownership_rows(self):
        rows = [
            record(1, land_id=5, owner_id=9, numerator="1", denominator="4"),
            record(2, land_id=5, owner_id=9, numerator="1", denominator="8"),
        ]
        group = group_land_records(rows).groups[0]
        self.assertEqual(group.owner_count, 1)
        self.assertEqual(group.ownership_count, 2)
        self.assertEqual(len(group.records), 2)

    def test_ownership_area_and_required_child_fields_are_complete(self):
        row = record(1, land_id=5, owner_id=9, area="300", numerator="1", denominator="3")
        self.assertEqual(ownership_area(row), 100)
        model = RecordTableModel(lambda *_args: None)
        model.set_rows([row])
        parent = model.index(0, 0)
        child = model.index(0, 0, parent)
        keys = {key: index for index, (key, _label) in enumerate(app.TABLE_COLUMNS)}
        self.assertEqual(model.data(model.index(0, keys["owner_name"], parent)), "王大明")
        self.assertEqual(model.data(model.index(0, keys["share"], parent)), "1/3")
        self.assertEqual(
            model.data(model.index(0, keys["ownership_area"], parent)),
            "100.00 ㎡",
        )
        self.assertEqual(model.data(model.index(0, keys["address"], parent)), "地址")
        self.assertEqual(model.data(model.index(0, keys["phone"], parent)), "0912345678")
        self.assertEqual(model.data(model.index(0, keys["customer_status"], parent)), "待追蹤")
        self.assertTrue(child.isValid())

    def test_natural_land_number_sort_and_child_sort_keep_hierarchy(self):
        rows = [
            record(1, land_id=1, owner_id=1, land_number="10", owner_name="乙"),
            record(2, land_id=2, owner_id=2, land_number="2", owner_name="甲"),
            record(3, land_id=3, owner_id=3, land_number="100", owner_name="丙"),
        ]
        sorted_rows = group_land_records(rows, sort_field="land_number", reverse=False)
        self.assertEqual(
            [group.representative["raw"]["land_number"] for group in sorted_rows.groups],
            ["2", "10", "100"],
        )
        self.assertLess(normalized_land_number_key("2"), normalized_land_number_key("10"))

        children = [
            record(4, land_id=4, owner_id=4, owner_name="Bob"),
            record(5, land_id=4, owner_id=5, owner_name="Alice"),
        ]
        child_sorted = group_land_records(
            children, sort_field="owner_name", reverse=False
        )
        self.assertEqual(len(child_sorted.groups), 1)
        self.assertEqual(
            [item["raw"]["owner_name"] for item in child_sorted.groups[0].records],
            ["Alice", "Bob"],
        )
        share_sorted = group_land_records(
            [
                record(
                    6,
                    land_id=5,
                    owner_id=6,
                    numerator="1",
                    denominator="2",
                ),
                record(
                    7,
                    land_id=5,
                    owner_id=7,
                    numerator="1",
                    denominator="4",
                ),
            ],
            sort_field="share",
            reverse=False,
        )
        self.assertEqual(
            [item["id"] for item in share_sorted.groups[0].records],
            [7, 6],
        )

    def test_pagination_counts_lands_and_never_splits_children(self):
        rows = []
        for land_id in range(1, 102):
            rows.append(record(land_id * 10, land_id=land_id, owner_id=land_id))
            rows.append(record(land_id * 10 + 1, land_id=land_id, owner_id=land_id + 1000))
        model = RecordTableModel(lambda *_args: None)
        model.set_rows(group_land_records(rows, sort_field="land_number", reverse=False))

        self.assertEqual(model.total_count, 101)
        self.assertEqual(model.ownership_total_count, 202)
        self.assertEqual(model.rowCount(), 100)
        first_page_ids = {
            model.group_for_index(model.index(row, 0)).land_id
            for row in range(model.rowCount())
        }
        self.assertEqual(len(first_page_ids), 100)
        self.assertTrue(model.next_page())
        self.assertEqual(model.rowCount(), 1)
        self.assertNotIn(
            model.group_for_index(model.index(0, 0)).land_id,
            first_page_ids,
        )
        self.assertEqual(model.rowCount(model.index(0, 0)), 2)

    def test_parent_and_child_selection_resolve_real_ids(self):
        rows = [
            record(21, land_id=9, owner_id=1),
            record(22, land_id=9, owner_id=2),
        ]
        model = RecordTableModel(lambda *_args: None)
        model.set_rows(rows)
        parent = model.index(0, 0)
        child = model.index(1, 0, parent)
        self.assertEqual(model.record_ids_for_index(parent), [21, 22])
        self.assertEqual(model.record_ids_for_index(child), [22])
        node_data = model.data(child, Qt.UserRole + 2)
        self.assertEqual(
            (node_data["land_id"], node_data["owner_id"], node_data["ownership_id"]),
            (9, 2, 22),
        )

    def test_checkbox_set_data_checks_unchecks_and_parent_becomes_partial(self):
        changes = []
        model = RecordTableModel(
            lambda record_id, checked: changes.append((record_id, checked))
        )
        model.set_rows(
            [
                record(31, land_id=11, owner_id=1),
                record(32, land_id=11, owner_id=2),
            ]
        )
        parent = model.index(0, CHECK_COLUMN)
        first_child = model.index(0, CHECK_COLUMN, parent)
        second_child = model.index(1, CHECK_COLUMN, parent)

        self.assertTrue(
            model.flags(first_child) & Qt.ItemIsUserCheckable
        )
        self.assertTrue(
            model.setData(
                first_child,
                Qt.Checked.value,
                Qt.CheckStateRole,
            )
        )
        self.assertEqual(
            model.data(first_child, Qt.CheckStateRole),
            Qt.Checked,
        )
        self.assertEqual(
            model.data(second_child, Qt.CheckStateRole),
            Qt.Unchecked,
        )
        self.assertEqual(
            model.data(parent, Qt.CheckStateRole),
            Qt.PartiallyChecked,
        )
        self.assertTrue(
            model.setData(
                first_child,
                Qt.Unchecked.value,
                Qt.CheckStateRole,
            )
        )
        self.assertEqual(
            model.data(first_child, Qt.CheckStateRole),
            Qt.Unchecked,
        )
        self.assertTrue(
            model.setData(
                parent,
                Qt.Checked.value,
                Qt.CheckStateRole,
            )
        )
        self.assertEqual(
            model.data(first_child, Qt.CheckStateRole),
            Qt.Checked,
        )
        self.assertEqual(
            model.data(second_child, Qt.CheckStateRole),
            Qt.Checked,
        )
        self.assertEqual(
            model.data(parent, Qt.CheckStateRole),
            Qt.Checked,
        )
        self.assertEqual(
            changes,
            [
                (31, True),
                (31, False),
                (31, True),
                (32, True),
            ],
        )

    def test_real_checkbox_mouse_click_toggles_without_model_reset(self):
        changes = []
        model = RecordTableModel(
            lambda record_id, checked: changes.append((record_id, checked))
        )
        model.set_rows([record(33, land_id=12, owner_id=3)])
        proxy = LandTreeProxyModel()
        proxy.setSourceModel(model)
        view = LandTreeView()
        view.setModel(proxy)
        view.resize(700, 240)
        view.show()
        QApplication.processEvents()
        reset_count = 0

        def record_reset():
            nonlocal reset_count
            reset_count += 1

        model.modelReset.connect(record_reset)
        try:
            index = proxy.index(0, CHECK_COLUMN)
            option = QStyleOptionViewItem()
            option.initFrom(view)
            option.rect = view.visualRect(index)
            option.widget = view
            view.itemDelegateForIndex(index).initStyleOption(option, index)
            checkbox_rect = view.style().subElementRect(
                QStyle.SE_ItemViewItemCheckIndicator,
                option,
                view,
            )

            QTest.mouseClick(
                view.viewport(),
                Qt.LeftButton,
                Qt.NoModifier,
                checkbox_rect.center(),
            )
            QApplication.processEvents()

            self.assertEqual(index.data(Qt.CheckStateRole), Qt.Checked)
            self.assertEqual(changes, [(33, True)])
            self.assertEqual(reset_count, 0)
        finally:
            view.close()

    def test_tag_delegate_is_only_installed_on_tag_column(self):
        model = RecordTableModel(lambda *_args: None)
        model.set_rows([record(34, land_id=13, owner_id=4)])
        proxy = LandTreeProxyModel()
        proxy.setSourceModel(model)
        view = LandTreeView()
        view.setModel(proxy)
        delegate = TagPillDelegate(view)
        tag_column = {
            key: index for index, (key, _label) in enumerate(app.TABLE_COLUMNS)
        }["tag_names"]

        view.configure_tag_delegate(delegate, tag_column)

        self.assertIs(view.itemDelegateForColumn(tag_column), delegate)
        self.assertIsNot(view.itemDelegateForColumn(CHECK_COLUMN), delegate)
        self.assertNotIn("editorEvent", TagPillDelegate.__dict__)
        view.close()

    def test_checkbox_callback_updates_checked_ids_without_refresh(self):
        harness = _WorkflowHarness(
            [record(35, land_id=14, owner_id=5)]
        )
        harness.checked_record_ids = set()
        harness.show_checked_only = True
        harness.schedule_selection_state_save = lambda: None
        harness.update_selection_status = lambda *_args, **_kwargs: None
        harness.table_model.checked_changed_callback = (
            harness.on_checked_state_changed
        )
        index = harness.table_model.index(0, CHECK_COLUMN)

        with patch(
            "customer_selection_workflows.QTimer.singleShot"
        ) as single_shot:
            self.assertTrue(
                harness.table_model.setData(
                    index,
                    Qt.Checked.value,
                    Qt.CheckStateRole,
                )
            )

        self.assertEqual(harness.checked_record_ids, {35})
        single_shot.assert_not_called()

    def test_batch_selection_expands_land_parent_to_real_ownership_ids(self):
        harness = _WorkflowHarness(
            [
                record(41, land_id=19, owner_id=1),
                record(42, land_id=19, owner_id=2),
            ]
        )
        selection = harness.table_view.selectionModel()
        parent = harness.table_proxy_model.index(0, 0)
        selection.select(
            parent,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.assertEqual(harness.selected_table_record_ids(), [41, 42])

        child = harness.table_proxy_model.index(1, 0, parent)
        selection.select(
            child,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.assertEqual(harness.selected_table_record_ids(), [42])

    def test_expand_collapse_restore_and_removed_ids(self):
        harness = _WorkflowHarness(
            [
                record(1, land_id=1, owner_id=1),
                record(2, land_id=2, owner_id=2),
            ]
        )
        first = harness.table_proxy_model.index(0, 0)
        harness.on_land_group_expanded(first)
        self.assertIn(harness.table_model.groups[0].state_id, harness.expanded_land_ids)
        harness.restore_land_expansion_state()
        self.assertTrue(harness.table_view.isExpanded(first))
        harness.on_land_group_collapsed(first)
        self.assertNotIn(harness.table_model.groups[0].state_id, harness.expanded_land_ids)

        harness.expanded_land_ids = {1, 999}
        harness.table_model.set_rows([record(1, land_id=1, owner_id=1)])
        harness.restore_land_expansion_state()
        self.assertEqual(harness.expanded_land_ids, {1})
        harness.expand_all_land_groups()
        self.assertTrue(harness.table_view.isExpanded(harness.table_proxy_model.index(0, 0)))
        harness.collapse_all_land_groups()
        self.assertFalse(harness.table_view.isExpanded(harness.table_proxy_model.index(0, 0)))

    def test_double_click_dispatches_by_node_level(self):
        harness = _WorkflowHarness([record(31, land_id=4, owner_id=6)])
        parent = harness.table_proxy_model.index(0, 0)
        child = harness.table_proxy_model.index(0, 0, parent)
        with patch("customer_record_workflows.LandDetailsDialog") as dialog:
            harness.on_tree_double_clicked(parent)
            dialog.assert_called_once()
        self.assertIsNone(harness.loaded_record_id)
        harness.on_tree_double_clicked(child)
        self.assertEqual(harness.loaded_record_id, 31)

    def test_parent_and_child_use_different_context_menus(self):
        harness = _WorkflowHarness([record(51, land_id=6, owner_id=7)])
        harness.land_menu = MagicMock()
        harness.record_menu = MagicMock()
        parent = harness.table_proxy_model.index(0, 0)
        child = harness.table_proxy_model.index(0, 0, parent)

        harness.table_view.indexAt = lambda _position: parent
        harness.show_record_menu(QPoint())
        harness.land_menu.exec.assert_called_once()
        harness.record_menu.exec.assert_not_called()

        harness.land_menu.reset_mock()
        harness.table_view.indexAt = lambda _position: child
        harness.show_record_menu(QPoint())
        harness.record_menu.exec.assert_called_once()
        harness.land_menu.exec.assert_not_called()

    def test_land_tree_uses_one_base_colour_instead_of_alternating_rows(self):
        tree = QTreeView()
        tree.setAlternatingRowColors(True)
        apply_land_tree_visual_style(tree, 30)
        self.assertFalse(tree.alternatingRowColors())
        stylesheet = tree.styleSheet()
        self.assertIn("alternate-background-color: #2d2d2d", stylesheet)
        self.assertIn("QTreeView::item:selected", stylesheet)
        self.assertIn("min-height: 30px", stylesheet)

    def test_partial_expansion_selection_and_scroll_survive_reload(self):
        harness = _WorkflowHarness(
            [
                record(71, land_id=101, owner_id=11, owner_name="甲"),
                record(72, land_id=102, owner_id=12, owner_name="乙"),
            ]
        )
        first_source = harness.table_model.index_for_group_state_id(101)
        first_proxy = harness.proxy_table_index(first_source)
        harness.table_view.setExpanded(first_proxy, True)
        second_child = harness.table_model.index_for_record_id(72)
        harness.table_view.selectionModel().setCurrentIndex(
            harness.proxy_table_index(second_child),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        harness.table_view.verticalScrollBar().setRange(0, 500)
        harness.table_view.horizontalScrollBar().setRange(0, 500)
        harness.table_view.verticalScrollBar().setValue(123)
        harness.table_view.horizontalScrollBar().setValue(45)
        state = harness.capture_land_tree_view_state()
        # Offscreen Qt collapses the range immediately because only two rows
        # exist; inject the captured values that a scrollable live view has.
        state["vertical_scroll"] = 123
        state["horizontal_scroll"] = 45

        harness.table_model.set_rows(
            [
                record(71, land_id=101, owner_id=11, owner_name="甲更新"),
                record(72, land_id=102, owner_id=12, owner_name="乙更新"),
            ]
        )
        # A real view recalculates these ranges during layout.  Keep explicit
        # ranges in this offscreen two-row test so restoration can be asserted.
        harness.table_view.verticalScrollBar().setRange(0, 500)
        harness.table_view.horizontalScrollBar().setRange(0, 500)
        with (
            patch.object(
                harness.table_view.verticalScrollBar(),
                "setValue",
                wraps=harness.table_view.verticalScrollBar().setValue,
            ) as vertical_set,
            patch.object(
                harness.table_view.horizontalScrollBar(),
                "setValue",
                wraps=harness.table_view.horizontalScrollBar().setValue,
            ) as horizontal_set,
        ):
            harness.restore_land_tree_view_state(state)
            vertical_set.assert_any_call(123)
            horizontal_set.assert_any_call(45)

        first_source = harness.table_model.index_for_group_state_id(101)
        second_source = harness.table_model.index_for_group_state_id(102)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(first_source))
        )
        self.assertFalse(
            harness.table_view.isExpanded(harness.proxy_table_index(second_source))
        )
        current = harness.source_table_index(harness.table_view.currentIndex())
        current_node = harness.table_model.node_for_index(current)
        self.assertEqual(current_node.kind, "ownership")
        self.assertEqual(current_node.record["ownership_id"], 72)

    def test_all_collapsed_remains_collapsed_after_reload(self):
        harness = _WorkflowHarness(
            [
                record(81, land_id=201, owner_id=21),
                record(82, land_id=202, owner_id=22),
            ]
        )
        harness.collapse_all_land_groups()
        state = harness.capture_land_tree_view_state()
        harness.table_model.set_rows(
            [
                record(81, land_id=201, owner_id=21, address="新地址"),
                record(82, land_id=202, owner_id=22, phone="0900000000"),
            ]
        )
        harness.restore_land_tree_view_state(state)
        for row in range(harness.table_model.rowCount()):
            source = harness.table_model.index(row, 0)
            self.assertFalse(
                harness.table_view.isExpanded(harness.proxy_table_index(source))
            )

    def test_owner_content_edit_updates_in_place_without_expansion_change(self):
        harness = _WorkflowHarness(
            [
                record(91, land_id=301, owner_id=31, owner_name="舊姓名"),
                record(92, land_id=302, owner_id=32),
            ]
        )
        source = harness.table_model.index_for_group_state_id(301)
        harness.table_view.setExpanded(harness.proxy_table_index(source), True)
        state = harness.capture_land_tree_view_state()
        changed = [
            record(
                91,
                land_id=301,
                owner_id=31,
                owner_name="新姓名",
                address="新地址",
                phone="0911000000",
            ),
            record(92, land_id=302, owner_id=32),
        ]
        self.assertTrue(harness.table_model.update_rows_in_place(changed))
        harness.restore_land_tree_view_state(state)
        source = harness.table_model.index_for_group_state_id(301)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(source))
        )
        child = harness.table_model.index_for_record_id(91)
        self.assertEqual(
            harness.table_model.record_for_index(child)["raw"]["owner_name"],
            "新姓名",
        )

    def test_ownership_share_edit_updates_in_place_without_expansion_change(self):
        harness = _WorkflowHarness(
            [
                record(
                    101,
                    land_id=401,
                    owner_id=41,
                    numerator="1",
                    denominator="2",
                )
            ]
        )
        source = harness.table_model.index_for_group_state_id(401)
        harness.table_view.setExpanded(harness.proxy_table_index(source), True)
        state = harness.capture_land_tree_view_state()
        self.assertTrue(
            harness.table_model.update_rows_in_place(
                [
                    record(
                        101,
                        land_id=401,
                        owner_id=41,
                        numerator="3",
                        denominator="4",
                    )
                ]
            )
        )
        harness.restore_land_tree_view_state(state)
        source = harness.table_model.index_for_group_state_id(401)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(source))
        )
        child = harness.table_model.index_for_record_id(101)
        self.assertEqual(
            harness.table_model.record_for_index(child)["raw"]["numerator"],
            "3",
        )

    def test_land_and_ownership_selection_are_restored_by_real_ids(self):
        harness = _WorkflowHarness(
            [
                record(111, land_id=501, owner_id=51),
                record(112, land_id=502, owner_id=52),
            ]
        )
        land = harness.table_model.index_for_group_state_id(501)
        harness.table_view.selectionModel().setCurrentIndex(
            harness.proxy_table_index(land),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        land_state = harness.capture_land_tree_view_state()
        self.assertEqual(land_state["selection"]["node_type"], "land")
        self.assertEqual(land_state["selection"]["land_id"], 501)
        harness.table_model.set_rows(list(harness.table_model.all_rows))
        harness.restore_land_tree_view_state(land_state)
        current = harness.source_table_index(harness.table_view.currentIndex())
        self.assertEqual(harness.table_model.node_for_index(current).kind, "land")
        self.assertEqual(
            harness.table_model.group_for_index(current).land_id,
            501,
        )

        child = harness.table_model.index_for_record_id(112)
        harness.table_view.selectionModel().setCurrentIndex(
            harness.proxy_table_index(child),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        ownership_state = harness.capture_land_tree_view_state()
        self.assertEqual(ownership_state["selection"]["owner_id"], 52)
        self.assertEqual(ownership_state["selection"]["ownership_id"], 112)
        harness.table_model.set_rows(list(harness.table_model.all_rows))
        harness.restore_land_tree_view_state(ownership_state)
        current = harness.source_table_index(harness.table_view.currentIndex())
        self.assertEqual(
            harness.table_model.record_for_index(current)["ownership_id"],
            112,
        )

    def test_removed_expanded_land_is_discarded_without_error(self):
        harness = _WorkflowHarness(
            [
                record(121, land_id=601, owner_id=61),
                record(122, land_id=602, owner_id=62),
            ]
        )
        source = harness.table_model.index_for_group_state_id(601)
        harness.table_view.setExpanded(harness.proxy_table_index(source), True)
        state = harness.capture_land_tree_view_state()
        harness.table_model.set_rows([record(122, land_id=602, owner_id=62)])
        harness.restore_land_tree_view_state(state)
        self.assertEqual(harness.expanded_land_ids, set())

    def test_search_auto_expansion_does_not_pollute_normal_expansion_state(self):
        harness = _WorkflowHarness(
            [
                record(131, land_id=701, owner_id=71),
                record(132, land_id=702, owner_id=72),
            ]
        )
        land_701 = harness.table_model.index_for_group_state_id(701)
        harness.table_view.setExpanded(
            harness.proxy_table_index(land_701),
            True,
        )
        normal_state = harness.capture_land_tree_view_state()
        harness._land_search_auto_expand = True
        # Simulate a search that filters the manually expanded land out.
        harness.table_model.set_rows([record(132, land_id=702, owner_id=72)])
        harness.restore_land_tree_view_state(
            normal_state,
            search_auto_expand=True,
        )
        self.assertEqual(harness.expanded_land_ids, {701})
        for row in range(harness.table_model.rowCount()):
            source = harness.table_model.index(row, 0)
            self.assertTrue(
                harness.table_view.isExpanded(harness.proxy_table_index(source))
            )
        search_snapshot = harness.capture_land_tree_view_state()
        self.assertEqual(search_snapshot["expanded_land_ids"], {701})

        harness._land_search_auto_expand = False
        harness.table_model.set_rows(
            [
                record(131, land_id=701, owner_id=71),
                record(132, land_id=702, owner_id=72),
            ]
        )
        harness.restore_land_tree_view_state(
            search_snapshot,
            search_auto_expand=False,
        )
        land_701 = harness.table_model.index_for_group_state_id(701)
        land_702 = harness.table_model.index_for_group_state_id(702)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(land_701))
        )
        self.assertFalse(
            harness.table_view.isExpanded(harness.proxy_table_index(land_702))
        )

    def test_refresh_state_restore_never_calls_expand_all(self):
        harness = _WorkflowHarness(
            [
                record(141, land_id=801, owner_id=81),
                record(142, land_id=802, owner_id=82),
            ]
        )
        state = harness.capture_land_tree_view_state()
        with patch.object(harness.table_view, "expandAll") as expand_all:
            harness.restore_land_tree_view_state(state)
        expand_all.assert_not_called()

    def test_save_refresh_controller_uses_in_place_update_and_preserves_state(self):
        harness = _WorkflowHarness(
            [
                record(151, land_id=901, owner_id=91, owner_name="儲存前"),
                record(152, land_id=902, owner_id=92),
            ]
        )
        land = harness.table_model.index_for_group_state_id(901)
        harness.table_view.setExpanded(harness.proxy_table_index(land), True)
        child = harness.table_model.index_for_record_id(151)
        harness.table_view.selectionModel().setCurrentIndex(
            harness.proxy_table_index(child),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        state = harness.capture_land_tree_view_state()
        changed = [
            record(
                151,
                land_id=901,
                owner_id=91,
                owner_name="儲存後",
                phone="0922000000",
                address="儲存後地址",
            ),
            record(152, land_id=902, owner_id=92),
        ]
        with patch.object(
            harness.table_model,
            "set_rows",
            wraps=harness.table_model.set_rows,
        ) as reset_model:
            harness.apply_record_rows(changed, 151, state)
        reset_model.assert_not_called()
        land = harness.table_model.index_for_group_state_id(901)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(land))
        )
        other_land = harness.table_model.index_for_group_state_id(902)
        self.assertFalse(
            harness.table_view.isExpanded(harness.proxy_table_index(other_land))
        )
        current = harness.source_table_index(harness.table_view.currentIndex())
        self.assertEqual(
            harness.table_model.record_for_index(current)["ownership_id"],
            151,
        )

    def test_content_edit_preserves_model_when_sort_order_would_change(self):
        initial = group_land_records(
            [
                record(161, land_id=1001, owner_id=101, land_number="10"),
                record(162, land_id=1002, owner_id=102, land_number="20"),
            ],
            sort_field="land_number",
            reverse=True,
        )
        model = RecordTableModel(lambda *_args: None)
        model.set_rows(initial)
        original_root_nodes = list(model._root_nodes)
        original_order = [group.state_id for group in model.groups]

        changed = group_land_records(
            [
                record(161, land_id=1001, owner_id=101, land_number="30"),
                record(162, land_id=1002, owner_id=102, land_number="20"),
            ],
            sort_field="land_number",
            reverse=True,
        )
        self.assertNotEqual(
            [group.state_id for group in changed.groups],
            original_order,
        )

        with (
            patch.object(model, "beginResetModel") as begin_reset,
            patch.object(model, "endResetModel") as end_reset,
        ):
            self.assertTrue(model.update_rows_in_place(changed))

        begin_reset.assert_not_called()
        end_reset.assert_not_called()
        self.assertEqual(model._root_nodes, original_root_nodes)
        self.assertEqual(
            [group.state_id for group in model.groups],
            original_order,
        )
        updated = model.index_for_record_id(161)
        self.assertEqual(
            model.record_for_index(updated)["raw"]["land_number"],
            "30",
        )

    def test_save_inside_search_does_not_expand_collapsed_groups(self):
        harness = _WorkflowHarness(
            [
                record(171, land_id=1101, owner_id=111, owner_name="王甲"),
                record(172, land_id=1102, owner_id=112, owner_name="王乙"),
            ]
        )
        first_land = harness.table_model.index_for_group_state_id(1101)
        harness.table_view.setExpanded(
            harness.proxy_table_index(first_land),
            True,
        )
        state = harness.capture_land_tree_view_state()
        harness.search_input.setText("王")
        changed = [
            record(171, land_id=1101, owner_id=111, owner_name="王甲已修改"),
            record(172, land_id=1102, owner_id=112, owner_name="王乙"),
        ]

        with patch.object(
            harness.table_model,
            "set_rows",
            wraps=harness.table_model.set_rows,
        ) as reset_model:
            harness.apply_record_rows(
                changed,
                171,
                state,
                search_auto_expand=False,
            )

        reset_model.assert_not_called()
        first_land = harness.table_model.index_for_group_state_id(1101)
        second_land = harness.table_model.index_for_group_state_id(1102)
        self.assertTrue(
            harness.table_view.isExpanded(
                harness.proxy_table_index(first_land)
            )
        )
        self.assertFalse(
            harness.table_view.isExpanded(
                harness.proxy_table_index(second_land)
            )
        )
        self.assertFalse(harness._land_search_auto_expand)

    def test_all_collapsed_stays_collapsed_after_tag_content_refresh(self):
        harness = _WorkflowHarness(
            [
                record(181, land_id=1201, owner_id=121),
                record(182, land_id=1202, owner_id=122),
            ]
        )
        harness.collapse_all_land_groups()
        state = harness.capture_land_tree_view_state()
        changed = list(harness.table_model.all_rows)
        changed[0]["raw"]["tag_names"] = "重要"
        changed[0]["display"]["tag_names"] = "重要"

        harness.apply_record_rows(changed, 181, state)

        self.assertEqual(harness.user_expanded_land_ids, set())
        self.assertEqual(harness.search_expanded_land_ids, set())
        for row in range(harness.table_model.rowCount()):
            self.assertFalse(
                harness.table_view.isExpanded(
                    harness.proxy_table_index(
                        harness.table_model.index(row, 0)
                    )
                )
            )

    def test_manual_a_stays_only_expanded_after_owner_save(self):
        harness = _WorkflowHarness(
            [
                record(191, land_id=1301, owner_id=131),
                record(192, land_id=1302, owner_id=132),
            ]
        )
        a = harness.table_model.index_for_group_state_id(1301)
        harness.table_view.setExpanded(harness.proxy_table_index(a), True)
        state = harness.capture_land_tree_view_state()
        changed = [
            record(
                191,
                land_id=1301,
                owner_id=131,
                owner_name="更新姓名",
                phone="0988000000",
                address="更新地址",
            ),
            record(192, land_id=1302, owner_id=132),
        ]

        harness.apply_record_rows(changed, 191, state)

        self.assertEqual(harness.user_expanded_land_ids, {1301})
        for land_id, expected in ((1301, True), (1302, False)):
            source = harness.table_model.index_for_group_state_id(land_id)
            self.assertEqual(
                harness.table_view.isExpanded(
                    harness.proxy_table_index(source)
                ),
                expected,
            )

    def test_manual_a_b_stay_only_expanded_after_batch_tag_refresh(self):
        harness = _WorkflowHarness(
            [
                record(201, land_id=1401, owner_id=141),
                record(202, land_id=1402, owner_id=142),
                record(203, land_id=1403, owner_id=143),
            ]
        )
        for land_id in (1401, 1402):
            source = harness.table_model.index_for_group_state_id(land_id)
            harness.table_view.setExpanded(
                harness.proxy_table_index(source), True
            )
        state = harness.capture_land_tree_view_state()
        changed = list(harness.table_model.all_rows)
        for row in changed:
            row["raw"]["tag_names"] = "批量標籤"
            row["display"]["tag_names"] = "批量標籤"

        harness.apply_record_rows(changed, 201, state)

        self.assertEqual(harness.user_expanded_land_ids, {1401, 1402})
        for land_id, expected in (
            (1401, True),
            (1402, True),
            (1403, False),
        ):
            source = harness.table_model.index_for_group_state_id(land_id)
            self.assertEqual(
                harness.table_view.isExpanded(
                    harness.proxy_table_index(source)
                ),
                expected,
            )

    def test_search_c_is_temporary_and_user_a_b_restore_after_clear(self):
        harness = _WorkflowHarness(
            [
                record(211, land_id=1501, owner_id=151),
                record(212, land_id=1502, owner_id=152),
                record(213, land_id=1503, owner_id=153),
            ]
        )
        for land_id in (1501, 1502):
            source = harness.table_model.index_for_group_state_id(land_id)
            harness.table_view.setExpanded(
                harness.proxy_table_index(source), True
            )
        state = harness.capture_land_tree_view_state()

        harness.table_model.set_rows(
            [record(213, land_id=1503, owner_id=153)]
        )
        harness.restore_land_tree_view_state(
            state,
            search_auto_expand=True,
        )
        c = harness.table_model.index_for_group_state_id(1503)
        self.assertTrue(
            harness.table_view.isExpanded(harness.proxy_table_index(c))
        )
        self.assertEqual(harness.user_expanded_land_ids, {1501, 1502})
        self.assertEqual(harness.search_expanded_land_ids, {1503})

        harness.table_model.set_rows(
            [
                record(211, land_id=1501, owner_id=151),
                record(212, land_id=1502, owner_id=152),
                record(213, land_id=1503, owner_id=153),
            ]
        )
        harness.restore_land_tree_view_state(
            state,
            search_auto_expand=False,
        )

        self.assertEqual(harness.search_expanded_land_ids, set())
        for land_id, expected in (
            (1501, True),
            (1502, True),
            (1503, False),
        ):
            source = harness.table_model.index_for_group_state_id(land_id)
            self.assertEqual(
                harness.table_view.isExpanded(
                    harness.proxy_table_index(source)
                ),
                expected,
            )

    def test_new_land_defaults_collapsed(self):
        harness = _WorkflowHarness(
            [record(221, land_id=1601, owner_id=161)]
        )
        a = harness.table_model.index_for_group_state_id(1601)
        harness.table_view.setExpanded(harness.proxy_table_index(a), True)
        state = harness.capture_land_tree_view_state()
        harness.table_model.set_rows(
            [
                record(221, land_id=1601, owner_id=161),
                record(222, land_id=1602, owner_id=162),
            ]
        )

        harness.restore_land_tree_view_state(state)

        self.assertEqual(harness.user_expanded_land_ids, {1601})
        new_land = harness.table_model.index_for_group_state_id(1602)
        self.assertFalse(
            harness.table_view.isExpanded(
                harness.proxy_table_index(new_land)
            )
        )

    def test_deleted_expanded_land_is_removed_from_both_sets(self):
        harness = _WorkflowHarness(
            [
                record(231, land_id=1701, owner_id=171),
                record(232, land_id=1702, owner_id=172),
            ]
        )
        deleted = harness.table_model.index_for_group_state_id(1701)
        harness.table_view.setExpanded(
            harness.proxy_table_index(deleted), True
        )
        harness.search_expanded_land_ids.add(1701)
        state = harness.capture_land_tree_view_state()
        harness.table_model.set_rows(
            [record(232, land_id=1702, owner_id=172)]
        )

        harness.restore_land_tree_view_state(
            state,
            search_auto_expand=False,
        )

        self.assertNotIn(1701, harness.user_expanded_land_ids)
        self.assertNotIn(1701, harness.search_expanded_land_ids)


if __name__ == "__main__":
    unittest.main()
