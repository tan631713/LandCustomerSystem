"""Read-only parcel summary opened from a land parent node."""

from customer_land_tree import ownership_area
from customer_ui_loader import find_child, install_ui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)


class LandDetailsDialog(QDialog):
    # Layout: ui/dialogs/land_details_dialog.ui; the table rows are filled here.
    ui_file = "dialogs/land_details_dialog.ui"
    ui_object_names = ("headingLabel", "detailsTable", "buttonBox")

    def __init__(self, group, parent=None):
        super().__init__(parent)
        content = install_ui(self, self.ui_file, self.ui_object_names)
        find_child(content, "headingLabel", QLabel).setText(
            f"{group.full_land_number}\n"
            f"土地總面積：{group.area or '未設定'} ㎡　"
            f"地主：{group.owner_count} 位　"
            f"所有權資料：{group.ownership_count} 筆\n"
            f"地目／使用分區：{group.land_use or '未設定'}　"
            f"狀態：{group.status_summary or '無'}"
        )

        columns = (
            ("owner_name", "地主姓名"),
            ("share", "持分"),
            ("ownership_area", "權利範圍面積"),
            ("address", "地主地址"),
            ("phone", "電話"),
            ("customer_status", "客戶狀態"),
            ("note_summary", "備註摘要"),
        )
        table = find_child(content, "detailsTable", QTableWidget)
        table.setRowCount(len(group.records))
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([label for _key, label in columns])
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
        buttons = find_child(content, "buttonBox", QDialogButtonBox)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
