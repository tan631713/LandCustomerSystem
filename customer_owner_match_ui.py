"""「可能是同一位地主」: existing-owner suggestions while typing a new record.

Only for a brand-new record in 家中伺服器 (API) mode.  When the 姓名 field
loses focus the home server is asked for owners with that name; the panel
under the form lists them (identity numbers and phones masked by the
server).  「選這位」 puts the new ownership under that owner when saving,
「都不是，新增新地主」 saves as before and records the decision in
duplicate_reviews so the same pair is not suggested again.  Editing an
existing record never triggers any of this.

Layout: ui/main/owner_match_panel.ui; colours: ui/theme.qss.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from customer_owner_match import normalize_owner_name
from customer_ui_loader import find_child, load_ui

logger = logging.getLogger(__name__)

OWNER_MATCH_UI_FILE = "main/owner_match_panel.ui"
OWNER_MATCH_REQUIRED_NAMES = (
    "ownerMatchTitle",
    "ownerMatchHint",
    "ownerMatchChosenLabel",
    "ownerMatchTable",
    "ownerMatchChooseButton",
    "ownerMatchNewOwnerButton",
    "ownerMatchClearChoiceButton",
)
OWNER_MATCH_DEFAULT_HINT = (
    "選「選這位」會把這筆土地加到該地主名下，不會另外新增地主。"
)


def candidate_reason_text(item, separator="\n"):
    """「姓名✓ 身分證✓ 地址✗」 and the note under it, one per line."""

    reasons = [str(reason) for reason in item.get("reasons") or () if reason]
    if separator == "\n":
        # A long note such as 地址相同、姓名不同（可能是家人或姓名打錯）
        # goes on two lines so the narrow form does not cut it off.
        reasons = [
            reason.replace("（", "\n（", 1)
            if len(reason) > 14 and "（" in reason
            else reason
            for reason in reasons
        ]
    return separator.join(reasons) or "姓名相同"


def candidate_summary(item):
    parts = [str(item.get("owner_name") or "")]
    if item.get("external_id_masked"):
        parts.append(str(item["external_id_masked"]))
    parts.append(f"已有 {int(item.get('land_count') or 0)} 筆土地")
    return "，".join(part for part in parts if part)


def chosen_owner_text(item):
    """「已選擇既有地主：邱小姐（H2211，13 筆土地），儲存時會加到這位地主名下」"""

    details = []
    if item.get("external_id_masked"):
        details.append(str(item["external_id_masked"]))
    details.append(f"{int(item.get('land_count') or 0)} 筆土地")
    return (
        f"已選擇既有地主：{item.get('owner_name') or ''}（{'，'.join(details)}），"
        "儲存時會加到這位地主名下"
    )


class OwnerMatchPanel(QWidget):
    """The candidate list; emits what the user picked, holds no record state."""

    choose_requested = Signal(dict)
    new_owner_requested = Signal()
    clear_choice_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ownerMatchPanelHost")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.content = load_ui(
            OWNER_MATCH_UI_FILE, required_names=OWNER_MATCH_REQUIRED_NAMES
        )
        layout.addWidget(self.content)
        self.title_label = find_child(self.content, "ownerMatchTitle", QLabel)
        self.hint_label = find_child(self.content, "ownerMatchHint", QLabel)
        self.chosen_label = find_child(self.content, "ownerMatchChosenLabel", QLabel)
        self.table = find_child(self.content, "ownerMatchTable", QTableWidget)
        self.choose_button = find_child(
            self.content, "ownerMatchChooseButton", QPushButton
        )
        self.new_owner_button = find_child(
            self.content, "ownerMatchNewOwnerButton", QPushButton
        )
        self.clear_choice_button = find_child(
            self.content, "ownerMatchClearChoiceButton", QPushButton
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Columns (ui file): 地主, 地址／相符原因, 土地／電話 -- two lines per
        # cell, so everything fits the narrow form without a horizontal
        # scroll bar.  地址／相符原因 takes the spare width.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # Columns 0 and 2 are sized from their labels in show_candidates().
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setWordWrap(True)
        self.items = []
        self.chosen = None
        self.choose_button.clicked.connect(self._emit_choose)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._emit_choose())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.new_owner_button.clicked.connect(self.new_owner_requested.emit)
        self.clear_choice_button.clicked.connect(self.clear_choice_requested.emit)
        self.reset()

    # -- state -------------------------------------------------------------

    def reset(self):
        self.items = []
        self.chosen = None
        self.table.setRowCount(0)
        self.chosen_label.setText("")
        self.hint_label.setText(OWNER_MATCH_DEFAULT_HINT)
        self.setVisible(False)
        self._sync_buttons()

    def show_candidates(self, items, *, note=""):
        self.items = [dict(item) for item in items]
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            phones = "、".join(item.get("phones_masked") or ())
            lands = item.get("lands") or []
            land_count = f"{int(item.get('land_count') or 0)} 筆土地"
            values = (
                "\n".join((
                    str(item.get("owner_name") or ""),
                    str(item.get("external_id_masked") or "（未填身分證）"),
                )),
                "\n".join((
                    str(item.get("address") or "（未填地址）"),
                    candidate_reason_text(item),
                )),
                "\n".join((land_count, phones or "（無電話）")),
            )
            tips = (
                values[0],
                values[1],
                "\n".join([land_count, *lands, phones]).strip(),
            )
            row_height = 0
            for column, text in enumerate(values):
                # The Fluent delegate paints one elided line, so the cell
                # itself stays empty (still selectable) and the two lines are
                # a label on top of it.
                cell = QTableWidgetItem("")
                cell.setData(Qt.UserRole, row)
                cell.setData(Qt.AccessibleTextRole, text)
                cell.setToolTip(tips[column])
                self.table.setItem(row, column, cell)
                label = QLabel(text)
                label.setObjectName("ownerMatchCellLabel")
                label.setWordWrap(False)
                label.setToolTip(tips[column])
                label.setContentsMargins(10, 4, 10, 4)
                label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                label.setStyleSheet("background: transparent;")
                self.table.setCellWidget(row, column, label)
                row_height = max(row_height, label.sizeHint().height() + 8)
            self.table.setRowHeight(row, max(row_height, 52))
        header = self.table.horizontalHeader()
        for column in (0, 2):
            widths = [
                self.table.cellWidget(row, column).sizeHint().width()
                for row in range(self.table.rowCount())
                if self.table.cellWidget(row, column) is not None
            ]
            widths.append(header.sectionSizeFromContents(column).width())
            header.resizeSection(column, max(widths) + 8)
        if self.items:
            self.table.selectRow(0)
        self.hint_label.setText(note or OWNER_MATCH_DEFAULT_HINT)
        self.setVisible(bool(self.items) or self.chosen is not None)
        self._sync_buttons()

    def set_chosen(self, item):
        self.chosen = None if item is None else dict(item)
        if self.chosen is None:
            self.chosen_label.setText("")
        else:
            self.chosen_label.setText(chosen_owner_text(self.chosen))
            self.chosen_label.show()
            self.setVisible(True)
        self._sync_buttons()

    def selected_item(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows or rows[0] >= len(self.items):
            return None
        return self.items[rows[0]]

    def _emit_choose(self):
        item = self.selected_item()
        if item is not None:
            self.choose_requested.emit(dict(item))

    def _sync_buttons(self):
        # Once an owner is chosen the list folds away and only the one-line
        # 「已選擇既有地主」 bar with 取消選擇 stays; 取消選擇 unfolds it again.
        chosen = self.chosen is not None
        listing = bool(self.items) and not chosen
        self.title_label.setVisible(not chosen)
        self.hint_label.setVisible(not chosen)
        self.table.setVisible(listing)
        self.choose_button.setVisible(listing)
        self.new_owner_button.setVisible(listing)
        self.choose_button.setEnabled(self.selected_item() is not None)
        self.clear_choice_button.setVisible(chosen)


class _OwnerMatchBridge(QObject):
    """Carries a background lookup's answer back to the GUI thread."""

    finished = Signal(int, object)


class OwnerMatchWorkflowMixin:
    """Window side: when to ask, what to do with the answer, save hooks."""

    # Tests set this to run lookups on the calling thread.
    owner_match_run_inline = False

    def setup_owner_match_panel(self, host_layout, index=None):
        self._owner_match_seq = 0
        self._owner_match_last = None
        self._owner_match_declined_owner_ids = set()
        self._owner_match_declined_record_ids = set()
        self._owner_match_bridge = _OwnerMatchBridge()
        self._owner_match_bridge.finished.connect(self._apply_owner_match_result)
        panel = OwnerMatchPanel()
        if index is None:
            host_layout.addWidget(panel)
        else:
            host_layout.insertWidget(index, panel)
        panel.choose_requested.connect(self.choose_owner_match)
        panel.new_owner_requested.connect(self.decline_owner_matches)
        panel.clear_choice_requested.connect(self.clear_owner_match_choice)
        self.owner_match_panel = panel
        for key in ("owner_name", "external_id", "address"):
            widget = self.field_widgets.get(key)
            if widget is not None:
                widget.editingFinished.connect(self.on_owner_match_field_finished)
        name_widget = self.field_widgets.get("owner_name")
        if name_widget is not None:
            name_widget.textEdited.connect(self._on_owner_match_name_edited)
        return panel

    # -- availability --------------------------------------------------------

    def owner_match_available(self):
        if getattr(self, "owner_match_panel", None) is None:
            return False
        if self.selected_record_id is not None:
            return False
        repository = self.active_record_repository()
        return callable(getattr(repository, "find_owner_candidates", None))

    def owner_match_chosen(self):
        panel = getattr(self, "owner_match_panel", None)
        return None if panel is None else panel.chosen

    def reset_owner_match_state(self):
        panel = getattr(self, "owner_match_panel", None)
        if panel is None:
            return
        self._owner_match_seq += 1
        self._owner_match_last = None
        self._owner_match_declined_owner_ids = set()
        self._owner_match_declined_record_ids = set()
        panel.reset()

    # -- query ---------------------------------------------------------------

    def owner_match_query(self):
        def text(key):
            widget = self.field_widgets.get(key)
            return widget.text().strip() if widget is not None else ""

        owner_name = text("owner_name")
        if getattr(self, "privacy_mask_enabled", False):
            owner_name = str(self.current_owner_name_plain or "").strip()
        external_id = str(getattr(self, "current_external_id_plain", "") or "").strip()
        if not external_id:
            external_id = text("external_id")
        return {
            "owner_name": owner_name,
            "external_id": external_id,
            "address": text("address"),
        }

    @staticmethod
    def _owner_match_query_has_terms(query):
        """姓名、身分證或地址 -- any one is enough to look up."""

        return bool(
            normalize_owner_name(query.get("owner_name"))
            or str(query.get("external_id") or "").strip()
            or str(query.get("address") or "").strip()
        )

    @staticmethod
    def _owner_match_query_key(query):
        return (
            normalize_owner_name(query.get("owner_name")),
            str(query.get("external_id") or "").strip().upper(),
            str(query.get("address") or "").strip(),
        )

    def _owner_match_fetch(self, query):
        repository = self.active_record_repository()
        return repository.find_owner_candidates(
            query, rejected_record_ids=sorted(self._owner_match_declined_record_ids)
        )

    def on_owner_match_field_finished(self):
        if not self.owner_match_available() or self.owner_match_chosen() is not None:
            return
        query = self.owner_match_query()
        if not self._owner_match_query_has_terms(query):
            self.owner_match_panel.show_candidates([])
            return
        key = self._owner_match_query_key(query)
        if self._owner_match_last is not None and self._owner_match_last[0] == key:
            return
        self._owner_match_seq += 1
        seq = self._owner_match_seq
        if self.owner_match_run_inline:
            self._apply_owner_match_result(seq, self._owner_match_safe_fetch(query, key))
            return
        bridge = self._owner_match_bridge

        def lookup():
            bridge.finished.emit(seq, self._owner_match_safe_fetch(query, key))

        self._start_background_task(lookup)

    def _owner_match_safe_fetch(self, query, key):
        try:
            return {"key": key, "result": self._owner_match_fetch(query)}
        except Exception as exc:  # noqa: BLE001 - suggestions must never block typing
            logger.warning("查詢既有地主失敗：%s", exc)
            return {"key": key, "result": None}

    def _visible_owner_matches(self, result):
        declined = self._owner_match_declined_owner_ids
        exact = (result or {}).get("exact_owner_id")
        return [
            item
            for item in (result or {}).get("items") or []
            if int(item["owner_id"]) not in declined
            and int(item["owner_id"]) != (int(exact) if exact else -1)
        ]

    def _owner_match_note(self, result):
        exact = (result or {}).get("exact_owner_id")
        if not exact:
            return ""
        same = next(
            (
                item
                for item in (result or {}).get("items") or []
                if int(item["owner_id"]) == int(exact)
            ),
            None,
        )
        label = candidate_summary(same) if same else "既有地主"
        return f"姓名與身分證／地址和「{label}」完全相同，儲存時會自動加到這位地主名下。"

    def _apply_owner_match_result(self, seq, payload):
        if seq != self._owner_match_seq or self.selected_record_id is not None:
            return
        result = (payload or {}).get("result")
        if result is None or result.get("supported") is False:
            self.owner_match_panel.show_candidates([])
            return
        self._owner_match_last = (payload["key"], result)
        if self.owner_match_chosen() is not None:
            return
        self.owner_match_panel.show_candidates(
            self._visible_owner_matches(result), note=self._owner_match_note(result)
        )

    # -- user decisions ------------------------------------------------------

    def choose_owner_match(self, item):
        if self.selected_record_id is not None:
            return
        panel = self.owner_match_panel
        masked_id = str(item.get("external_id_masked") or "")
        if masked_id and not self.get_field_text("external_id"):
            # Only the mask is known here; the server swaps in the real
            # number for the chosen owner when saving.
            self.current_external_id_plain = masked_id
            self.set_field_text("external_id", masked_id)
        elif masked_id and "*" in str(self.current_external_id_plain or ""):
            self.current_external_id_plain = masked_id
            self.set_field_text("external_id", masked_id)
        if item.get("address"):
            self.set_field_text("address", str(item["address"]))
        if item.get("owner_name") and (
            item.get("address_only") or not self.get_field_text("owner_name")
        ):
            # Picking a different-name owner at the same address means the
            # typed name was wrong: use the owner's own name.
            self.set_field_text("owner_name", str(item["owner_name"]))
            self.current_owner_name_plain = str(item["owner_name"])
        panel.set_chosen(item)
        panel.show_candidates(panel.items)
        self.mark_form_dirty()

    def clear_owner_match_choice(self):
        panel = getattr(self, "owner_match_panel", None)
        if panel is None or panel.chosen is None:
            return
        if "*" in str(self.current_external_id_plain or ""):
            self.current_external_id_plain = ""
            self.set_field_text("external_id", "")
        panel.set_chosen(None)
        panel.show_candidates(panel.items)

    def decline_owner_matches(self, items=None):
        panel = self.owner_match_panel
        items = panel.items if items is None else items
        for item in items:
            self._owner_match_declined_owner_ids.add(int(item["owner_id"]))
            if item.get("sample_record_id"):
                self._owner_match_declined_record_ids.add(int(item["sample_record_id"]))
        panel.set_chosen(None)
        panel.show_candidates([])

    def _on_owner_match_name_edited(self, _text=""):
        panel = getattr(self, "owner_match_panel", None)
        if panel is None or self.selected_record_id is not None:
            return
        if panel.chosen is not None:
            # A different name: the earlier choice no longer applies.
            self.clear_owner_match_choice()
        self._owner_match_last = None

    # -- save hooks ----------------------------------------------------------

    def confirm_owner_match_before_save(self):
        """True to go on saving; False when the user went back to choose."""

        if not self.owner_match_available() or self.owner_match_chosen() is not None:
            return True
        query = self.owner_match_query()
        if not self._owner_match_query_has_terms(query):
            return True
        key = self._owner_match_query_key(query)
        if self._owner_match_last is not None and self._owner_match_last[0] == key:
            result = self._owner_match_last[1]
        else:
            try:
                result = self._owner_match_fetch(query)
            except Exception as exc:  # noqa: BLE001 - never block a save on this
                logger.warning("儲存前查詢既有地主失敗：%s", exc)
                return True
            if result is not None:
                self._owner_match_last = (key, result)
        if not result or result.get("supported") is False or result.get("exact_owner_id"):
            return True
        high = [item for item in self._visible_owner_matches(result) if item.get("high_match")]
        if not high:
            return True
        self.owner_match_panel.show_candidates(self._visible_owner_matches(result))
        if self.ask_owner_match_decision(high) == "new":
            self.decline_owner_matches(self._visible_owner_matches(result))
            return True
        return False

    def ask_owner_match_decision(self, high):
        """"new" = 確定新增新地主, anything else = go back and choose."""

        lines = "\n".join(
            f"・{candidate_summary(item)}（{candidate_reason_text(item, '，')}）"
            for item in high[:5]
        )
        box_class = self._app_component("QMessageBox")
        box = box_class(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("可能是同一位地主")
        box.setText(
            "找到很可能是同一位的既有地主：\n" + lines
            + "\n\n要回到下方清單選擇「選這位」，還是確定新增一位新地主？"
        )
        back_button = box.addButton("回去選擇", QMessageBox.RejectRole)
        new_button = box.addButton("確定新增新地主", QMessageBox.AcceptRole)
        box.setDefaultButton(back_button)
        box.exec()
        return "new" if box.clickedButton() is new_button else "back"

    def owner_match_save_kwargs(self, is_new_record):
        chosen = self.owner_match_chosen() if is_new_record else None
        if chosen is None:
            return {}
        return {"owner_id": int(chosen["owner_id"])}

    def after_owner_match_saved(self, new_record_id):
        """Record each 「都不是」 against the new record, then forget the state."""

        record_ids = sorted(getattr(self, "_owner_match_declined_record_ids", set()))
        if record_ids and new_record_id:
            repository = self.active_record_repository()
            pairs = [
                (int(new_record_id), record_id)
                for record_id in record_ids
                if int(record_id) != int(new_record_id)
            ]

            def write_reviews():
                for left_id, right_id in pairs:
                    try:
                        repository.ignore_duplicate_pair(left_id, right_id)
                    except Exception as exc:  # noqa: BLE001 - a lost review only re-asks later
                        logger.warning("記錄「不是同一位地主」失敗：%s", exc)

            if self.owner_match_run_inline:
                write_reviews()
            else:
                self._start_background_task(write_reviews)
        self.reset_owner_match_state()
