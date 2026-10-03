"""Dialogs for 都市計畫: management, delete confirmation and batch assignment."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from customer_urban_plan_tree import UNASSIGNED_PLAN_ID, UNASSIGNED_PLAN_NAME

PLAN_ID_ROLE = Qt.UserRole + 31
MUTED_STYLE = "color: #8b98ab; font-size: 12px;"


def _plan_id(plan):
    return int(plan.get("plan_id", plan.get("id")) or 0)


def _count_text(value):
    return f"{int(value or 0):,}"


class UrbanPlanManagementDialog(QDialog):
    """List, add, rename and delete named 都市計畫.

    The dialog does no network work itself: `load_plans()` returns the
    repository's listing, `create_plan(name)` / `rename_plan(plan_id, name)`
    save, and `delete_plan(plan)` asks for confirmation and deletes (True when
    it did). Errors raised by those callbacks are shown here.
    """

    def __init__(
        self,
        load_plans,
        create_plan,
        rename_plan,
        delete_plan,
        parent=None,
        *,
        can_edit=True,
    ):
        super().__init__(parent)
        self.setWindowTitle("都市計畫管理")
        self.setObjectName("urbanPlanManagementDialog")
        self.setMinimumSize(560, 460)
        self.load_plans = load_plans
        self.create_plan = create_plan
        self.rename_plan = rename_plan
        self.delete_plan = delete_plan
        self.can_edit = bool(can_edit)
        self.changed = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel("先在這裡建立都市計畫，之後新增或匯入資料時選擇「輸入到」哪一個，資料就會歸入該計畫。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("urbanPlanTable")
        self.table.setHorizontalHeaderLabels(["名稱", "土地", "地主", "持分"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            header.resizeSection(column, 80)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.rename_selected())
        layout.addWidget(self.table, 1)

        self.add_row = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("urbanPlanNameInput")
        self.name_input.setPlaceholderText("新都市計畫名稱，例如 龍岡都市計畫")
        self.name_input.setMaxLength(100)
        self.name_input.returnPressed.connect(self.add_plan)
        self.add_button = QPushButton("新增")
        self.add_button.setObjectName("urbanPlanAddButton")
        self.add_button.clicked.connect(self.add_plan)
        self.add_row.addWidget(self.name_input, 1)
        self.add_row.addWidget(self.add_button)
        layout.addLayout(self.add_row)

        self.note = QLabel("刪除都市計畫不會刪除任何土地或地主，該計畫的土地會回到「未分類」。")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(MUTED_STYLE)
        layout.addWidget(self.note)

        buttons = QHBoxLayout()
        self.rename_button = QPushButton("重新命名")
        self.rename_button.setObjectName("urbanPlanRenameButton")
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button = QPushButton("刪除")
        self.delete_button.setObjectName("urbanPlanDeleteButton")
        self.delete_button.clicked.connect(self.delete_selected)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        if not self.can_edit:
            for widget in (self.name_input, self.add_button):
                widget.setEnabled(False)
            self.name_input.setPlaceholderText("唯讀帳號不能新增或修改都市計畫")
        self.reload()

    # -- data -------------------------------------------------------------

    def reload(self, select_plan_id=None):
        try:
            data = self.load_plans()
        except Exception as exc:  # noqa: BLE001 - shown to the user, dialog stays usable
            QMessageBox.critical(self, "讀取失敗", str(exc))
            data = {"items": [], "unassigned": {}}
        self.plans = [dict(item) for item in data.get("items") or []]
        self.unassigned = dict(data.get("unassigned") or {})
        self.table.setRowCount(0)
        for plan in self.plans:
            self._append_row(
                plan.get("name", ""), plan, plan_id=_plan_id(plan)
            )
        self._append_row(UNASSIGNED_PLAN_NAME, self.unassigned, plan_id=UNASSIGNED_PLAN_ID)
        target = select_plan_id
        for row in range(self.table.rowCount()):
            if target is not None and self.table.item(row, 0).data(PLAN_ID_ROLE) == target:
                self.table.selectRow(row)
                break
        self.update_buttons()

    def _append_row(self, name, counts, *, plan_id):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(str(name))
        name_item.setData(PLAN_ID_ROLE, plan_id)
        if plan_id == UNASSIGNED_PLAN_ID:
            name_item.setForeground(Qt.gray)
        self.table.setItem(row, 0, name_item)
        for column, key in ((1, "land_count"), (2, "owner_count"), (3, "ownership_count")):
            item = QTableWidgetItem(_count_text(counts.get(key)))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, column, item)

    def selected_plan(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        plan_id = self.table.item(rows[0].row(), 0).data(PLAN_ID_ROLE)
        if plan_id == UNASSIGNED_PLAN_ID:
            return None
        return next((plan for plan in self.plans if _plan_id(plan) == plan_id), None)

    def update_buttons(self):
        selected = self.selected_plan() is not None and self.can_edit
        self.rename_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    # -- actions ------------------------------------------------------------

    def _run(self, action, *args):
        try:
            return True, action(*args)
        except Exception as exc:  # noqa: BLE001 - ValueError / DesktopApiError text goes to the user
            # A server refusal carries a readable `detail`; "API 409: …" is noise.
            QMessageBox.warning(self, "都市計畫管理失敗", str(getattr(exc, "detail", None) or exc))
            return False, None

    def add_plan(self):
        name = " ".join(self.name_input.text().split())
        if not name:
            QMessageBox.information(self, "請輸入名稱", "請先輸入都市計畫名稱。")
            return False
        ok, plan_id = self._run(self.create_plan, name)
        if not ok:
            return False
        self.changed = True
        self.name_input.clear()
        self.reload(select_plan_id=plan_id)
        return True

    def rename_selected(self):
        plan = self.selected_plan()
        if plan is None or not self.can_edit:
            return False
        name, accepted = QInputDialog.getText(
            self, "重新命名", "新的都市計畫名稱：", QLineEdit.Normal, str(plan.get("name") or "")
        )
        name = " ".join(str(name).split())
        if not accepted or not name or name == plan.get("name"):
            return False
        ok, _result = self._run(self.rename_plan, _plan_id(plan), name)
        if not ok:
            return False
        self.changed = True
        self.reload(select_plan_id=_plan_id(plan))
        return True

    def delete_selected(self):
        plan = self.selected_plan()
        if plan is None or not self.can_edit:
            return False
        ok, deleted = self._run(self.delete_plan, plan)
        if not ok or not deleted:
            return False
        self.changed = True
        self.reload()
        return True


class ImportPlanChoice(QWidget):
    """「這批資料屬於」: the plan an import (or batch add) files its lands under."""

    def __init__(self, plans, default_plan_id=0, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("這批資料屬於："))
        self.combo = QComboBox()
        self.combo.setObjectName("importPlanCombo")
        self.combo.setMinimumWidth(200)
        self.combo.addItem("不指定（未分類）", UNASSIGNED_PLAN_ID)
        for plan in plans:
            self.combo.addItem(str(plan.get("name") or ""), _plan_id(plan))
        index = self.combo.findData(int(default_plan_id or 0))
        self.combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.combo)
        note = QLabel("已經屬於其他都市計畫的土地不會被改動，匯入後會列出清單。")
        note.setStyleSheet(MUTED_STYLE)
        note.setWordWrap(True)
        layout.addWidget(note, 1)

    def plan_id(self):
        return int(self.combo.currentData() or UNASSIGNED_PLAN_ID)


class ImportPlanResultSection(QWidget):
    """The 都市計畫 part of the import result: what was filed, and what was not.

    `summary` is the server's `urban_plan` block: name, assigned_land_count,
    kept_land_count and kept_lands (rows with district/section/subsection/
    land_number/urban_plan_name, possibly fewer than kept_land_count).
    """

    def __init__(self, summary, parent=None):
        super().__init__(parent)
        self.summary = dict(summary or {})
        self.kept_lands = [dict(item) for item in self.summary.get("kept_lands") or []]
        kept_count = int(self.summary.get("kept_land_count") or len(self.kept_lands))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        name = str(self.summary.get("name") or "")
        assigned = int(self.summary.get("assigned_land_count") or 0)
        self.header_label = QLabel(f"都市計畫「{name}」：{assigned:,} 筆土地新歸入這個都市計畫。")
        self.header_label.setObjectName("importPlanHeader")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)
        self.table = None
        self.export_button = None
        if not kept_count:
            return
        self.kept_label = QLabel(
            f"另有 {kept_count:,} 筆土地原本已屬於其他都市計畫，沒有變更歸屬："
        )
        self.kept_label.setObjectName("importPlanKeptLabel")
        self.kept_label.setStyleSheet("color: #fbbf24;")
        self.kept_label.setWordWrap(True)
        layout.addWidget(self.kept_label)
        self.table = QTableWidget(len(self.kept_lands), 3)
        self.table.setObjectName("importPlanKeptTable")
        self.table.setHorizontalHeaderLabels(["地段", "地號", "目前所屬"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(140)
        for row, land in enumerate(self.kept_lands):
            for column, text in enumerate(self._row_texts(land)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        layout.addWidget(self.table, 1)
        if kept_count > len(self.kept_lands):
            more = QLabel(f"…其餘 {kept_count - len(self.kept_lands):,} 筆未列出。")
            more.setStyleSheet(MUTED_STYLE)
            layout.addWidget(more)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("匯出這份清單")
        self.export_button.setObjectName("importPlanExportButton")
        self.export_button.clicked.connect(self.export_kept_lands)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    @staticmethod
    def _row_texts(land):
        section = f"{land.get('district') or ''}{land.get('section') or ''}".strip()
        subsection = str(land.get("subsection") or "").strip()
        return (
            f"{section} {subsection}".strip(),
            str(land.get("land_number") or ""),
            str(land.get("urban_plan_name") or ""),
        )

    def export_rows(self):
        return [
            dict(zip(("section", "land_number", "plan"), self._row_texts(land)))
            for land in self.kept_lands
        ]

    def export_kept_lands(self):
        from datetime import datetime

        from customer_excel import ExcelService

        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出這份清單",
            f"沒有變更歸屬的土地-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx",
            "Excel 檔案 (*.xlsx)",
        )
        if not file_path:
            return False
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"
        try:
            ExcelService.write_rows(
                file_path,
                self.export_rows(),
                [("section", "地段"), ("land_number", "地號"), ("plan", "目前所屬都市計畫")],
                "沒有變更歸屬",
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user
            QMessageBox.critical(self, "無法匯出", str(exc))
            return False
        QMessageBox.information(
            self, "匯出完成", f"已匯出 {len(self.kept_lands):,} 筆土地。\n檔案位置：{file_path}"
        )
        return True


class DeleteUrbanPlanDialog(QDialog):
    """「刪除確認」: says what will (and will not) happen before a plan is deleted."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("刪除確認")
        self.setObjectName("deleteUrbanPlanDialog")
        self.setMinimumWidth(420)
        name = str(plan.get("name") or "")
        lands = int(plan.get("land_count") or 0)
        owners = int(plan.get("owner_count") or 0)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel(f"確定要刪除「{name}」？")
        title.setObjectName("deleteUrbanPlanTitle")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        title.setWordWrap(True)
        layout.addWidget(title)
        if lands:
            detail = (
                f"這個都市計畫目前有 {lands:,} 筆土地、{owners:,} 位地主。\n"
                "刪除後這些土地會回到「未分類」，土地與地主資料都不會被刪除。"
            )
        else:
            detail = "這個都市計畫目前沒有任何土地，刪除不會影響其他資料。"
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("deleteUrbanPlanDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("deleteUrbanPlanCancel")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton("刪除")
        self.confirm_button.setObjectName("deleteUrbanPlanConfirm")
        self.confirm_button.setStyleSheet(
            "QPushButton { background-color: #b42318; border-color: #d92d20; color: #ffffff; }"
            "QPushButton:hover { background-color: #d92d20; }"
        )
        self.confirm_button.clicked.connect(self.accept)
        cancel.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        layout.addLayout(buttons)


class SetUrbanPlanDialog(QDialog):
    """「設定都市計畫」: put the lands of the selected rows into a plan.

    `land_plans` maps each selected land id to its current plan id (0 =
    未分類). Lands that already belong to another plan are left alone unless
    the user clears the safety checkbox.
    """

    def __init__(self, plans, land_plans, record_count, parent=None, *, default_plan_id=None):
        super().__init__(parent)
        self.setWindowTitle("設定都市計畫")
        self.setObjectName("setUrbanPlanDialog")
        self.setMinimumWidth(460)
        self.land_plans = {int(land): int(plan or 0) for land, plan in dict(land_plans).items()}
        self.plan_names = {_plan_id(plan): str(plan.get("name") or "") for plan in plans}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.header_label = QLabel(
            f"已選取 {int(record_count):,} 筆資料，涵蓋 {len(self.land_plans):,} 筆土地。"
        )
        self.header_label.setObjectName("setUrbanPlanHeader")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        layout.addWidget(QLabel("設定為："))
        self.plan_combo = QComboBox()
        self.plan_combo.setObjectName("setUrbanPlanCombo")
        for plan in plans:
            self.plan_combo.addItem(str(plan.get("name") or ""), _plan_id(plan))
        self.plan_combo.addItem("未分類（移出目前的都市計畫）", UNASSIGNED_PLAN_ID)
        if default_plan_id:
            index = self.plan_combo.findData(int(default_plan_id))
            if index >= 0:
                self.plan_combo.setCurrentIndex(index)
        self.plan_combo.currentIndexChanged.connect(self.update_summary)
        layout.addWidget(self.plan_combo)

        self.only_unassigned_check = QCheckBox("只設定目前「未分類」的土地（已屬於其他都市計畫的不變更）")
        self.only_unassigned_check.setObjectName("setUrbanPlanOnlyUnassigned")
        self.only_unassigned_check.setChecked(True)
        self.only_unassigned_check.toggled.connect(self.update_summary)
        layout.addWidget(self.only_unassigned_check)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("setUrbanPlanSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(MUTED_STYLE)
        layout.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("套用")
        self.apply_button.setObjectName("setUrbanPlanApply")
        self.apply_button.clicked.connect(self.accept)
        self.apply_button.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.update_summary()

    def plan_id(self):
        return int(self.plan_combo.currentData() or UNASSIGNED_PLAN_ID)

    def only_unassigned(self):
        return self.plan_id() != UNASSIGNED_PLAN_ID and self.only_unassigned_check.isChecked()

    def land_ids(self):
        return sorted(self.land_plans)

    def affected_land_count(self):
        """How many of the selected lands this choice would actually change."""

        target = self.plan_id()
        count = 0
        for current in self.land_plans.values():
            if target == UNASSIGNED_PLAN_ID:
                count += current != UNASSIGNED_PLAN_ID
            elif current == target:
                continue
            elif self.only_unassigned() and current != UNASSIGNED_PLAN_ID:
                continue
            else:
                count += 1
        return count

    def update_summary(self, *_args):
        target = self.plan_id()
        releasing = target == UNASSIGNED_PLAN_ID
        self.only_unassigned_check.setEnabled(not releasing)
        total = len(self.land_plans)
        unassigned = sum(1 for plan in self.land_plans.values() if plan == UNASSIGNED_PLAN_ID)
        same = sum(1 for plan in self.land_plans.values() if plan == target and not releasing)
        elsewhere = total - unassigned - same
        affected = self.affected_land_count()
        if releasing:
            text = f"將有 {affected:,} 筆土地改為「未分類」。"
        else:
            parts = [f"將有 {affected:,} 筆土地設定為「{self.plan_names.get(target, '')}」。"]
            if same:
                parts.append(f"{same:,} 筆原本就在這個計畫。")
            if elsewhere and self.only_unassigned():
                parts.append(f"{elsewhere:,} 筆已屬於其他都市計畫，不會變更。")
            elif elsewhere:
                parts.append(f"{elsewhere:,} 筆原屬其他都市計畫，會被改到這個計畫。")
            text = " ".join(parts)
        self.summary_label.setText(text)
        self.apply_button.setEnabled(affected > 0)
