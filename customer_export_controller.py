"""Copy, mobile-share, and Excel-export workflows for table rows."""

from datetime import datetime

from customer_excel import ExcelExportWorker
from customer_mobile_share import MobileShareDialog
from customer_word import write_records_docx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

APP_DIR = None
TABLE_COLUMNS = ()


def configure_export_controller(**dependencies):
    globals().update(dependencies)


class ExportControllerMixin:
    def get_export_columns(self):
        export_columns = []
        if self.table_view is not None:
            header = self.table_view.horizontalHeader()
            ordered_indexes = sorted(
                range(len(TABLE_COLUMNS)),
                key=lambda logical_index: header.visualIndex(logical_index),
            )
            for logical_index in ordered_indexes:
                key, label = TABLE_COLUMNS[logical_index]
                if key == "checked":
                    continue
                if self.table_view.isColumnHidden(logical_index):
                    continue
                export_columns.append((key, label))
        else:
            export_columns = TABLE_COLUMNS[1:]
        return export_columns

    def selected_table_rows(self):
        if self.table_view is None or self.table_view.selectionModel() is None:
            return []
        selected_indexes = self.table_view.selectionModel().selectedIndexes()
        selected_row_numbers = sorted(
            {index.row() for index in selected_indexes if index.isValid()}
        )
        rows = []
        for row_number in selected_row_numbers:
            row = self.table_model.row_record(row_number)
            if row:
                rows.append(row)
        return rows

    def copy_selected_cells(self):
        if self.table_view is None or self.table_view.selectionModel() is None:
            return

        selected_indexes = [
            index
            for index in self.table_view.selectionModel().selectedIndexes()
            if index.isValid()
            and not self.table_view.isColumnHidden(index.column())
            and TABLE_COLUMNS[index.column()][0] != "checked"
        ]
        if not selected_indexes:
            self.statusBar().showMessage("沒有可複製的儲存格。", 2500)
            return

        selected_positions = {(index.row(), index.column()) for index in selected_indexes}
        selected_rows = sorted({index.row() for index in selected_indexes})
        header = self.table_view.horizontalHeader()
        selected_columns = sorted(
            {index.column() for index in selected_indexes},
            key=lambda column: header.visualIndex(column),
        )

        copied_lines = []
        for row_number in selected_rows:
            values = []
            for column_number in selected_columns:
                if (row_number, column_number) not in selected_positions:
                    values.append("")
                    continue
                model_index = self.table_model.index(row_number, column_number)
                value = self.table_model.data(model_index, Qt.DisplayRole)
                values.append(str(value or ""))
            copied_lines.append("\t".join(values))

        QApplication.clipboard().setText("\n".join(copied_lines))
        self.statusBar().showMessage(
            f"已複製 {len(selected_rows)} 列、{len(selected_columns)} 欄。",
            2500,
        )

    def checked_table_rows(self):
        if not self.checked_record_ids:
            return []
        self.table_model.load_all()
        return [
            row for row in self.table_model.all_rows if row["id"] in self.checked_record_ids
        ]

    def selected_or_checked_rows(self):
        rows = self.selected_table_rows()
        checked_rows = self.checked_table_rows()
        checked_ids = {row["id"] for row in checked_rows}
        return checked_rows + [row for row in rows if row["id"] not in checked_ids]

    def share_selected_to_mobile(self):
        rows = self.selected_or_checked_rows()
        if not rows:
            QMessageBox.warning(self, "尚未選取", "請先反白或勾選要傳送的資料。")
            return
        columns = self.get_export_columns()
        if not columns:
            QMessageBox.warning(self, "沒有欄位", "目前沒有可傳送的顯示欄位。")
            return
        try:
            import qrcode  # noqa: F401

            dialog = MobileShareDialog(rows, columns, self)
        except (ImportError, OSError) as exc:
            QMessageBox.critical(self, "無法建立 QR 分享", str(exc))
            return
        dialog.exec()

    def export_rows_to_xlsx(self, rows):
        if not rows:
            QMessageBox.information(self, "沒有資料", "目前沒有可匯出的資料。")
            return
        export_columns = self.get_export_columns()
        if not export_columns:
            QMessageBox.information(self, "沒有可匯出欄位", "目前所有資料欄位都被隱藏，無法匯出。")
            return

        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出 Excel",
            str(APP_DIR / f"customers-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"),
            "Excel 檔案 (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path += ".xlsx"

        raw_rows = [dict(row["raw"]) for row in rows]
        worker = ExcelExportWorker(file_path, raw_rows, export_columns)
        self.start_excel_worker(worker, self.handle_excel_export_ready, "正在背景匯出 Excel…")

    def handle_excel_export_ready(self, file_path, row_count):
        QMessageBox.information(
            self,
            "匯出完成",
            f"已匯出 {row_count} 筆資料。\n檔案位置：{file_path}",
        )

    def export_xlsx(self):
        self.export_rows_to_xlsx(list(self.table_model.load_all()))

    def export_selected_xlsx(self):
        rows = self.selected_or_checked_rows()
        if not rows:
            QMessageBox.warning(self, "尚未選取", "請先在表格選取要匯出的資料。")
            return
        self.export_rows_to_xlsx(rows)

    def export_selected_word(self):
        rows = self.selected_or_checked_rows()
        if not rows:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要匯出的資料。")
            return
        export_columns = self.get_export_columns()
        if not export_columns:
            QMessageBox.information(self, "沒有可匯出欄位", "目前沒有可匯出的顯示欄位。")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "匯出 Word",
            str(APP_DIR / f"customers-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.docx"),
            "Word 文件 (*.docx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".docx"):
            file_path += ".docx"
        row_count = write_records_docx(file_path, [row["raw"] for row in rows], export_columns)
        QMessageBox.information(self, "匯出完成", f"已匯出 {row_count} 筆資料：\n{file_path}")
