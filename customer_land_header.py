"""Land header (大地號、面積、現值) and the 持分分布 bar for the detail panel."""

from __future__ import annotations

from fractions import Fraction

from customer_domain import parse_number
from customer_theme import heading_font, qcolor, token
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

CAPTION_TEXT = "持分分布，點選切換地主"
CAPTION_HEIGHT = 18
BAR_HEIGHT = 30
SEGMENT_GAP = 1
LABEL_MIN_FRACTION = 0.12
SEGMENT_TOKENS = ("seg1", "seg2", "seg3")


def _fraction(value):
    number = parse_number(value)
    if number is None:
        return None
    return Fraction(number).limit_denominator(1_000_000)


def displayed_owner_name(record):
    """The name exactly as the list shows it (RecordTableModel reads display["owner_name"]).

    Never read the plain text from ``raw``: with the privacy mask on the list
    shows a masked name and the share bar must show the same thing.
    """

    return str((record.get("display") or {}).get("owner_name") or "").strip()


def shares_from_group(group):
    """One dict per ownership of ``group`` that has a usable positive share."""

    shares = []
    for record in group.records:
        raw = record.get("raw") or {}
        numerator = _fraction(raw.get("numerator"))
        denominator = _fraction(raw.get("denominator"))
        if numerator is None or denominator is None or numerator <= 0 or denominator <= 0:
            continue
        shares.append(
            {
                "record_id": int(record["id"]),
                "name": displayed_owner_name(record) or "（未填姓名）",
                "numerator": str(raw.get("numerator") or "").strip(),
                "denominator": str(raw.get("denominator") or "").strip(),
                "fraction": numerator / denominator,
            }
        )
    return shares


class ShareBarWidget(QWidget):
    """Self-painted bar: one segment per owner, width = numerator / denominator."""

    ownerClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shares = []
        self._selected_id = None
        self._focus_index = -1
        self.setObjectName("shareBar")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(CAPTION_HEIGHT + 2 + BAR_HEIGHT)

    # -- data -------------------------------------------------------------------

    def set_shares(self, shares, selected_record_id=None):
        self._shares = [dict(share) for share in shares]
        self._selected_id = None if selected_record_id is None else int(selected_record_id)
        self._focus_index = self._index_of_record(self._selected_id)
        self._update_accessible_name()
        self.update()

    def shares(self):
        return [dict(share) for share in self._shares]

    def _index_of_record(self, record_id):
        for index, share in enumerate(self._shares):
            if share["record_id"] == record_id:
                return index
        return 0 if self._shares else -1

    def total_fraction(self):
        return sum((share["fraction"] for share in self._shares), Fraction(0))

    def summary_text(self):
        count = len(self._shares)
        total = self.total_fraction()
        if total == 1:
            return f"共 {count} 位，合計 1/1"
        text = "合計未滿 1" if total < 1 else "合計超過 1"
        return f"共 {count} 位，{text}（{total.numerator}/{total.denominator}）"

    def summary_is_warning(self):
        return bool(self._shares) and self.total_fraction() != 1

    def segment_texts(self):
        return [self._segment_text(share) for share in self._shares]

    def segment_tooltips(self):
        return [self._segment_text(share) for share in self._shares]

    @staticmethod
    def _segment_text(share):
        return f"{share['name']} {share['numerator']}/{share['denominator']}"

    # -- geometry ---------------------------------------------------------------

    def bar_top(self):
        return CAPTION_HEIGHT + 2

    def segment_widths(self, total_width=None):
        """Full (gap-free) widths; the bar never overflows when the sum is over 1."""

        width = float(self.width() if total_width is None else total_width)
        scale = max(Fraction(1), self.total_fraction())
        return [float(share["fraction"] / scale) * width for share in self._shares]

    def segment_rects(self):
        rects = []
        x = 0.0
        top = float(self.bar_top())
        widths = self.segment_widths()
        for index, width in enumerate(widths):
            gap = SEGMENT_GAP if index < len(widths) - 1 else 0
            rects.append(QRectF(x, top, max(1.0, width - gap), float(BAR_HEIGHT)))
            x += width
        return rects

    def segment_at(self, position):
        point = QPointF(position)
        for index, rect in enumerate(self.segment_rects()):
            slot = QRectF(rect.x(), rect.y(), rect.width() + SEGMENT_GAP, rect.height())
            if slot.contains(point):
                return index
        return -1

    # -- interaction ------------------------------------------------------------

    def _activate(self, index):
        if 0 <= index < len(self._shares):
            self._focus_index = index
            self._update_accessible_name()
            self.update()
            self.ownerClicked.emit(self._shares[index]["record_id"])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.segment_at(event.position())
            if index >= 0:
                self.setFocus(Qt.MouseFocusReason)
                self._activate(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        count = len(self._shares)
        if count and event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -1 if event.key() == Qt.Key_Left else 1
            self._focus_index = (max(0, self._focus_index) + step) % count
            self._update_accessible_name()
            self.update()
            event.accept()
            return
        if count and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._activate(max(0, self._focus_index))
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        if self._shares and self._focus_index < 0:
            self._focus_index = 0
        self._update_accessible_name()
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def event(self, event):
        if event.type() == QEvent.ToolTip:
            index = self.segment_at(event.pos())
            if index >= 0:
                QToolTip.showText(event.globalPos(), self.segment_tooltips()[index], self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def _update_accessible_name(self):
        if 0 <= self._focus_index < len(self._shares):
            share = self._shares[self._focus_index]
            self.setAccessibleName(
                f"{share['name']}，持分 {share['numerator']}/{share['denominator']}"
            )
        else:
            self.setAccessibleName("持分分布")

    # -- painting ---------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_caption(painter)
            self._paint_bar(painter)
        finally:
            painter.end()

    def _paint_caption(self, painter):
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        caption_rect = QRectF(0, 0, self.width(), CAPTION_HEIGHT)
        painter.setPen(qcolor("ink2"))
        painter.drawText(caption_rect, int(Qt.AlignLeft | Qt.AlignVCenter), CAPTION_TEXT)
        painter.setPen(qcolor("amber_ink" if self.summary_is_warning() else "ink2"))
        painter.drawText(
            caption_rect, int(Qt.AlignRight | Qt.AlignVCenter), self.summary_text()
        )

    def _paint_bar(self, painter):
        rects = self.segment_rects()
        bar_top = float(self.bar_top())
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor("auto"))
        painter.drawRoundedRect(QRectF(0, bar_top, self.width(), BAR_HEIGHT), 4, 4)
        other_index = 0
        for index, (share, rect) in enumerate(zip(self._shares, rects)):
            selected = share["record_id"] == self._selected_id
            if selected:
                fill, text_color = qcolor("green"), qcolor("green_ink")
            else:
                fill = qcolor(SEGMENT_TOKENS[other_index % len(SEGMENT_TOKENS)])
                text_color = qcolor("ink")
                other_index += 1
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 3, 3)
            if rect.width() >= self.width() * LABEL_MIN_FRACTION:
                font = QFont(self.font())
                font.setBold(selected)
                painter.setFont(font)
                painter.setPen(text_color)
                text = QFontMetrics(font).elidedText(
                    self._segment_text(share), Qt.ElideRight, int(rect.width() - 10)
                )
                painter.drawText(rect, int(Qt.AlignCenter), text)
        if self.hasFocus() and 0 <= self._focus_index < len(rects):
            pen = QPen(qcolor("ink"))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rects[self._focus_index].adjusted(1, 1, -1, -1), 3, 3)


class LandHeaderWidget(QFrame):
    """Top of the detail panel: where the land is, its big parcel number and shares."""

    ownerClicked = Signal(int)

    METRICS = (("area", "面積"), ("value", "公告現值"), ("plan", "都市計畫"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("landHeader")
        self.setStyleSheet(
            f"QFrame#landHeader {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {token('rule')}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(0)
        self.location_label = QLabel("")
        self.location_label.setObjectName("landHeaderLocation")
        self.location_label.setStyleSheet(f"color: {token('ink2')}; font-size: 12px;")
        self.location_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.land_number_label = QLabel("尚未選取資料")
        self.land_number_label.setObjectName("landHeaderNumber")
        self.land_number_label.setFont(heading_font(20))
        self.land_number_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self.location_label)
        left.addWidget(self.land_number_label)
        top.addLayout(left, 1)

        self.metric_containers = {}
        self.metric_values = {}
        for key, caption in self.METRICS:
            container = QWidget()
            container.setObjectName(f"landHeaderMetric_{key}")
            column = QVBoxLayout(container)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            caption_label = QLabel(caption)
            caption_label.setStyleSheet(f"color: {token('ink2')}; font-size: 12px;")
            value_label = QLabel("—")
            value_label.setObjectName(f"landHeaderValue_{key}")
            value_label.setStyleSheet("font-size: 14px; font-weight: 600;")
            column.addWidget(caption_label)
            column.addWidget(value_label)
            top.addWidget(container, 0, Qt.AlignBottom)
            self.metric_containers[key] = container
            self.metric_values[key] = value_label
        outer.addLayout(top)

        self.share_bar = ShareBarWidget()
        self.share_bar.ownerClicked.connect(self.ownerClicked)
        outer.addWidget(self.share_bar)
        self.share_bar.hide()

    def show_land(self, *, location, land_number, area, value, plan, show_plan):
        self.location_label.setText(location)
        self.location_label.setVisible(bool(location))
        self.land_number_label.setText(land_number or "尚未填寫地號")
        self.metric_values["area"].setText(f"{area} m²" if area else "—")
        self.metric_values["value"].setText(f"{value} 元/m²" if value else "—")
        self.metric_values["plan"].setText(plan or "—")
        self.metric_containers["plan"].setVisible(bool(show_plan))

    def show_new_record(self):
        self.show_land(
            location="", land_number="新增資料", area="", value="", plan="", show_plan=False
        )
        self.set_shares([], None)

    def show_empty(self):
        self.show_land(
            location="", land_number="尚未選取資料", area="", value="", plan="", show_plan=False
        )
        self.set_shares([], None)

    def set_shares(self, shares, selected_record_id=None):
        self.share_bar.set_shares(shares, selected_record_id)
        self.share_bar.setVisible(bool(shares))


class LandHeaderMixin:
    """Keeps the LandHeaderWidget in step with the selected record and the form."""

    def create_land_header(self, parent_layout):
        self.land_header = LandHeaderWidget()
        self.land_header.ownerClicked.connect(self.on_land_header_owner_clicked)
        parent_layout.addWidget(self.land_header)

    def on_land_header_owner_clicked(self, record_id):
        # Same path as clicking that owner in the list: on_record_select loads it.
        if self.plan_view_active():
            return
        self.select_record_in_table(record_id)

    def _share_group_for_selected_record(self):
        """The LandGroup holding the selected record, without changing the list page.

        RecordTableModel.index_for_record_id() flips the page when the record
        is on another one, which a header refresh must never do.
        """

        if self.selected_record_id is None or self.table_model is None:
            return None
        wanted = int(self.selected_record_id)
        for group in self.table_model.groups:
            if wanted in group.record_ids:
                return group
        return None

    def refresh_land_header(self, *, new_record=False):
        header = getattr(self, "land_header", None)
        if header is None:
            return
        if new_record:
            header.show_new_record()
            return
        if self.selected_record_id is None or not self.fields:
            header.show_empty()
            return
        location = " ".join(
            part
            for part in (
                "桃園市",
                self.get_field_text("district"),
                self.get_field_text("section"),
                self.get_field_text("subsection"),
            )
            if part
        )
        plan_combo = getattr(self, "urban_plan_form_combo", None)
        header.show_land(
            location=location,
            land_number=self.get_field_text("land_number"),
            area=self.get_field_text("area"),
            value=self.get_field_text("declared_value"),
            plan=plan_combo.currentText() if plan_combo is not None else "",
            show_plan=self.urban_plans_available(),
        )
        group = None if self.plan_view_active() else self._share_group_for_selected_record()
        header.set_shares(
            shares_from_group(group) if group is not None else [], self.selected_record_id
        )
