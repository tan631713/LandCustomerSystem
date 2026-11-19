"""基本資料頂端「名下其他土地」標籤列.

Shows, right under the 基本資料 tab, every parcel the selected record's owner
holds: a one-line summary (名下共 N 筆土地、合計持分坪數), one clickable chip
per holding (地段＋地號＋持分, the selected one filled green) and the basis of
the grouping (依身分證／依姓名＋地址歸戶).  More than ``VISIBLE_CHIP_LIMIT``
chips fold into 「＋N 筆 ▾」.  Clicking a chip opens that record.

The data comes from the rows the desktop client already holds (家中伺服器 mode
downloads the whole list; 單機 reads the local database), grouped with the
same owner identity as the land tree (customer_land_tree.owner_identity):
owner_id when the server gives one, else 身分證, else 姓名＋地址.  Nothing is
written anywhere.  Note that the server's owner_id is itself keyed on the
identity number, so a 5-digit 身分證 shared by two people lists both people's
land here; the basis label says which key was used so the user can check.

Layout: ui/main/owner_lands_bar.ui; colours: ui/theme.qss.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from customer_domain import PING_CONVERSION_FACTOR
from customer_flow_layout import FlowLayout
from customer_land_tree import land_identity, owner_identity, ownership_area
from customer_security import decrypt_value
from customer_theme import repolish, token
from customer_ui_loader import find_child, load_ui

OWNER_LANDS_UI_FILE = "main/owner_lands_bar.ui"
OWNER_LANDS_REQUIRED_NAMES = (
    "ownerLandsBar",
    "ownerLandsSummaryLabel",
    "ownerLandsTotalLabel",
    "ownerLandsBasisLabel",
    "ownerLandsChips",
)
VISIBLE_CHIP_LIMIT = 4
DISTRICT_SUFFIXES = ("區", "鎮", "鄉", "市")


# -- pure helpers (no Qt) --------------------------------------------------------


def _text(value):
    return str(value or "").strip()


def _natural_key(value):
    """'130-2' sorts after '13' and before '131'."""

    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", _text(value).casefold())
        if part
    ]


def short_district(district):
    district = _text(district)
    if len(district) > 2 and district.endswith(DISTRICT_SUFFIXES):
        return district[:-1]
    return district


def owner_key_of_row(row, decrypt):
    """The land tree's owner identity for one database/API row.

    ``decrypt(row)`` returns the decrypted owner_name/external_id/address; it
    is only called for rows without an owner_id (單機 database).
    """

    try:
        owner_id = row["owner_id"]
    except (KeyError, IndexError):
        owner_id = None
    record = {"id": row["id"], "owner_id": owner_id, "raw": {}}
    if owner_id in (None, ""):
        sensitive = decrypt(row)
        record["raw"] = {
            "external_id": sensitive.get("external_id"),
            "owner_name": sensitive.get("owner_name"),
            "address": sensitive.get("address"),
        }
    return owner_identity(record)


def land_key_of_row(row):
    """The land tree's land identity for one database/API row."""

    def value(key):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None

    return land_identity(
        {
            "id": row["id"],
            "land_id": value("land_id"),
            "raw": {key: value(key) for key in ("district", "section", "subsection", "land_number")},
        }
    )


def build_owner_index(rows, decrypt):
    """{owner identity: [row, ...]} over every row."""

    index = {}
    for row in rows:
        index.setdefault(owner_key_of_row(row, decrypt), []).append(row)
    return index


def holding_ping(record):
    area = ownership_area(record)
    return None if area is None else area * PING_CONVERSION_FACTOR


def format_ping(value):
    return f"{value:,.1f} 坪"


def chip_label(raw, current_district=""):
    """「中路段 123」, or 「八德 大湳段 56」 when the district differs."""

    parts = []
    district = _text(raw.get("district"))
    if district and district != _text(current_district):
        parts.append(short_district(district))
    for key in ("section", "subsection", "land_number"):
        value = _text(raw.get(key))
        if value:
            parts.append(value)
    return " ".join(parts) or "未填地號"


def share_text(raw):
    numerator = _text(raw.get("numerator"))
    denominator = _text(raw.get("denominator"))
    if numerator and denominator:
        return f"{numerator}/{denominator}"
    return numerator or ""


def chip_tooltip(record, *, current=False):
    raw = record.get("raw") or {}
    full = _text(raw.get("full_land_number")) or chip_label(raw)
    details = []
    share = share_text(raw)
    if share:
        details.append(f"持分 {share}")
    ping = holding_ping(record)
    if ping is not None:
        details.append(f"持分面積 {format_ping(ping)}")
    use = _text(raw.get("land_use")) or _text(raw.get("urban_plan_name"))
    if use:
        details.append(use)
    lines = [f"{full} 地號"]
    if details:
        lines.append(" · ".join(details))
    tags = _text(raw.get("tag_names"))
    action = "目前這筆" if current else "點一下切換到這筆"
    lines.append(f"標籤：{tags}　　{action}" if tags else action)
    return "\n".join(lines)


def order_holdings(records, current_id):
    """The selected record first, then its own 地區, then the rest, by 地段／小段／地號."""

    current_district = next(
        (_text((r.get("raw") or {}).get("district")) for r in records if r.get("id") == current_id),
        "",
    )

    def key(record):
        raw = record.get("raw") or {}
        return (
            _text(raw.get("district")) != current_district,
            _natural_key(raw.get("district")),
            _natural_key(raw.get("section")),
            _natural_key(raw.get("subsection")),
            _natural_key(raw.get("land_number")),
            int(record.get("id") or 0),
        )

    current = [record for record in records if record.get("id") == current_id]
    others = sorted((record for record in records if record.get("id") != current_id), key=key)
    return current + others


def total_ping(records):
    values = [holding_ping(record) for record in records]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def basis_text(record):
    """「ⓘ 依身分證 H2211 歸戶」 or 「ⓘ 依姓名＋地址歸戶」 (display = masked as the form shows)."""

    raw = record.get("raw") or {}
    if _text(raw.get("external_id")):
        shown = _text((record.get("display") or {}).get("external_id"))
        return f"ⓘ 依身分證 {shown} 歸戶" if shown else "ⓘ 依身分證歸戶"
    return "ⓘ 依姓名＋地址歸戶"


# -- widgets ---------------------------------------------------------------------


class OwnerLandChip(QFrame):
    """One holding: 「中路段 124  1/1」; click / Enter / Space opens it."""

    clicked = Signal()

    def __init__(self, label, share="", *, current=False, more=False, parent=None):
        super().__init__(parent)
        self.setObjectName("ownerLandChip")
        self.setProperty("current", bool(current))
        self.setProperty("more", bool(more))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(4)
        self.label = QLabel(label, self)
        self.label.setObjectName("ownerLandChipLabel")
        layout.addWidget(self.label)
        self.share_label = QLabel(share, self)
        self.share_label.setObjectName("ownerLandChipShare")
        self.share_label.setVisible(bool(share))
        layout.addWidget(self.share_label)
        for child in (self.label, self.share_label):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName(f"{label} {share}".strip())

    def text(self):
        return f"{self.label.text()} {self.share_label.text()}".strip()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class OwnerLandsBar(QWidget):
    """Summary + chips for one owner; emits the record id the user picked."""

    recordClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ownerLandsBarHost")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(0)
        self.content = load_ui(OWNER_LANDS_UI_FILE, required_names=OWNER_LANDS_REQUIRED_NAMES)
        layout.addWidget(self.content)
        self.summary_label = find_child(self.content, "ownerLandsSummaryLabel", QLabel)
        self.total_label = find_child(self.content, "ownerLandsTotalLabel", QLabel)
        self.basis_label = find_child(self.content, "ownerLandsBasisLabel", QLabel)
        self.chips_host = find_child(self.content, "ownerLandsChips", QWidget)
        self.chips_layout = FlowLayout(self.chips_host, h_spacing=6, v_spacing=6)
        self.chips = []
        self.expanded = False
        self._owner_name = ""
        self._records = []
        self._current_id = None
        self.hide()

    # -- state ------------------------------------------------------------------

    def show_holdings(self, owner_name, records, current_id, basis):
        """``records`` are processed records (with raw/display), current included."""

        if current_id != self._current_id:
            self.expanded = False
        self._owner_name = owner_name
        self._current_id = current_id
        self._records = order_holdings(records, current_id)
        count = len(self._records)
        name = owner_name or "這位地主"
        self.summary_label.setText(
            f"<b>{_html(name)}</b> 名下共 "
            f"<b style='color:{token('green')}'>{count}</b> 筆土地"
        )
        total = total_ping(self._records)
        self.total_label.setText(f"合計 {format_ping(total)}" if total is not None else "")
        self.total_label.setVisible(total is not None)
        self.basis_label.setText(basis)
        self._rebuild_chips()
        self.show()

    def clear(self):
        self._records = []
        self._current_id = None
        self.expanded = False
        self._rebuild_chips()
        self.hide()

    def set_expanded(self, expanded):
        self.expanded = bool(expanded)
        self._rebuild_chips()

    def hidden_count(self):
        if self.expanded or len(self._records) <= VISIBLE_CHIP_LIMIT:
            return 0
        return len(self._records) - VISIBLE_CHIP_LIMIT

    def chip_texts(self):
        return [chip.text() for chip in self.chips]

    def summary_plain_text(self):
        return re.sub(r"<[^>]+>", "", self.summary_label.text())

    # -- chips ------------------------------------------------------------------

    def _rebuild_chips(self):
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.chips = []
        if not self._records:
            return
        current = next((r for r in self._records if r.get("id") == self._current_id), None)
        current_district = ((current or {}).get("raw") or {}).get("district", "")
        hidden = self.hidden_count()
        shown = self._records if hidden == 0 else self._records[:VISIBLE_CHIP_LIMIT]
        for record in shown:
            raw = record.get("raw") or {}
            is_current = record.get("id") == self._current_id
            chip = OwnerLandChip(
                chip_label(raw, current_district),
                share_text(raw),
                current=is_current,
                parent=self.chips_host,
            )
            chip.setToolTip(chip_tooltip(record, current=is_current))
            record_id = int(record["id"])
            chip.clicked.connect(lambda rid=record_id: self.recordClicked.emit(rid))
            self._add_chip(chip)
        if hidden:
            more = OwnerLandChip(f"＋{hidden} 筆 ▾", more=True, parent=self.chips_host)
            more.setToolTip("顯示這位地主的全部土地")
            more.clicked.connect(lambda: self.set_expanded(True))
            self._add_chip(more)
        elif self.expanded and len(self._records) > VISIBLE_CHIP_LIMIT:
            less = OwnerLandChip("收合 ▴", more=True, parent=self.chips_host)
            less.clicked.connect(lambda: self.set_expanded(False))
            self._add_chip(less)
        self.chips_host.updateGeometry()
        self.content.updateGeometry()

    def _add_chip(self, chip):
        self.chips_layout.addWidget(chip)
        self.chips.append(chip)
        repolish(chip)
        chip.show()


def _html(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# -- window side -----------------------------------------------------------------


class OwnerLandsMixin:
    """Keeps the bar in step with the selected record."""

    def setup_owner_lands_bar(self, host_layout, index=None):
        bar = OwnerLandsBar()
        if index is None:
            host_layout.addWidget(bar)
        else:
            host_layout.insertWidget(index, bar)
        bar.recordClicked.connect(self.on_owner_land_clicked)
        self.owner_lands_bar = bar
        return bar

    def _owner_lands_rows(self, repository):
        for name in ("fetch_all_customer_rows", "fetch_search_candidate_rows"):
            method = getattr(repository, name, None)
            if callable(method):
                return list(method())
        return []

    def _owner_lands_decrypt(self, processor):
        cache = processor.decryption_cache

        def decrypt(row):
            if cache is not None:
                return cache.decrypt_fields(row, self.fernet)
            return {
                name: decrypt_value(self.fernet, row[name] or "")
                for name in ("owner_name", "external_id", "address")
            }

        return decrypt

    def _owner_lands_all_index(self, repository, processor):
        """{"by_id", "owners", "lands"} over every row, rebuilt when the data changes."""

        key = (id(repository), getattr(repository, "data_revision", None))
        index = getattr(self, "_owner_lands_index", None)
        if index is None or key != getattr(self, "_owner_lands_index_key", None) or key[1] is None:
            rows = self._owner_lands_rows(repository)
            decrypt = self._owner_lands_decrypt(processor)
            lands = {}
            for row in rows:
                lands.setdefault(land_key_of_row(row), []).append(row)
            index = {
                "by_id": {int(row["id"]): row for row in rows},
                "owners": build_owner_index(rows, decrypt),
                "lands": lands,
            }
            self._owner_lands_index = index
            self._owner_lands_index_key = key
        return index

    def _owner_lands_current_row(self, repository, index):
        row = index["by_id"].get(int(self.selected_record_id))
        if row is None:
            row = repository.get_customer(self.selected_record_id)
        return row

    def _owner_lands_records(self, processor, rows, current_row):
        rows = list(rows or [current_row])
        if not any(int(row["id"]) == int(current_row["id"]) for row in rows):
            rows.append(current_row)
        return [processor.build_record(row, include_search_text=False) for row in rows]

    def owner_lands_for_selected(self):
        """(current processed record, [processed records of the same owner]) or None."""

        if self.selected_record_id is None:
            return None
        repository = self.active_record_repository()
        processor = self.create_record_processor()
        index = self._owner_lands_all_index(repository, processor)
        current_row = self._owner_lands_current_row(repository, index)
        if current_row is None:
            return None
        identity = owner_key_of_row(current_row, self._owner_lands_decrypt(processor))
        records = self._owner_lands_records(processor, index["owners"].get(identity), current_row)
        current = next(r for r in records if int(r["id"]) == int(current_row["id"]))
        return current, records

    def land_share_records_for_selected(self):
        """Processed records of every owner on the selected record's land (all data, not just the list)."""

        if self.selected_record_id is None:
            return []
        repository = self.active_record_repository()
        processor = self.create_record_processor()
        index = self._owner_lands_all_index(repository, processor)
        current_row = self._owner_lands_current_row(repository, index)
        if current_row is None:
            return []
        return self._owner_lands_records(
            processor, index["lands"].get(land_key_of_row(current_row)), current_row
        )

    def refresh_owner_lands(self, *, new_record=False):
        bar = getattr(self, "owner_lands_bar", None)
        if bar is None:
            return
        if new_record or self.selected_record_id is None:
            bar.clear()
            return
        try:
            result = self.owner_lands_for_selected()
        except Exception:  # never let the summary strip break loading a record
            import logging

            logging.getLogger(__name__).exception("名下其他土地 could not be built")
            result = None
        if result is None:
            bar.clear()
            return
        current, records = result
        owner_name = (current.get("display") or {}).get("owner_name") or ""
        bar.show_holdings(owner_name, records, int(current["id"]), basis_text(current))

    def on_owner_land_clicked(self, record_id):
        if self.selected_record_id is not None and int(record_id) == int(self.selected_record_id):
            return
        if not self.plan_view_active() and self.select_record_in_table(record_id):
            return
        self.load_record(record_id)
        if self.selected_record_id == record_id and not self.plan_view_active():
            self.statusBar().showMessage(
                "這筆土地不在目前的搜尋結果裡，已直接開啟；清除搜尋就能在左側看到它。", 5000
            )
