"""Read-only parcel summary opened from a land parent node."""

from customer_land_tree import ownership_area
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class LandDetailsDialog(QDialog):
    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("土地詳細資料")
        self.resize(980, 520)
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"{group.full_land_number}\n"
            f"土地總面積：{group.area or '未設定'} ㎡　"
            f"地主：{group.owner_count} 位　"
            f"所有權資料：{group.ownership_count} 筆\n"
            f"地目／使用分區：{group.land_use or '未設定'}　"
            f"狀態：{group.status_summary or '無'}"
        )
        heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        heading.setStyleSheet(
            "background:#1f2937;color:#e5e7eb;border-radius:6px;padding:12px;"
        )
        layout.addWidget(heading)

        columns = (
            ("owner_name", "地主姓名"),
            ("share", "持分"),
            ("ownership_area", "權利範圍面積"),
            ("address", "地主地址"),
            ("phone", "電話"),
            ("customer_status", "客戶狀態"),
            ("note_summary", "備註摘要"),
        )
        table = QTableWidget(len(group.records), len(columns), self)
        table.setHorizontalHeaderLabels([label for _key, label in columns])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        for row_number, record in enumerate(group.records):
            raw = record.get("raw") or {}
            numerator = str(raw.get("numerator") or "")
            denominator = str(raw.get("denominator") or "")
            area = ownership_area(record)
            values = {
                "owner_name": raw.get("owner_name") or "",
                "share": (
                    f"{numerator}/{denominator}"
                    if numerator or denominator
                    else ""
                ),
                "ownership_area": "" if area is None else f"{area:,.2f} ㎡",
                "address": raw.get("address") or "",
                "phone": raw.get("phone") or "",
                "customer_status": raw.get("follow_up_status") or "",
                "note_summary": str(raw.get("note") or "").replace("\n", " "),
            }
            for column_number, (key, _label) in enumerate(columns):
                item = QTableWidgetItem(str(values.get(key) or ""))
                item.setToolTip(str(values.get(key) or ""))
                item.setData(
                    Qt.UserRole,
                    {
                        "land_id": group.land_id,
                        "owner_id": record.get("owner_id"),
                        "ownership_id": record.get("ownership_id")
                        or record.get("id"),
                    },
                )
                table.setItem(row_number, column_number, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
