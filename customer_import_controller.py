"""Excel import and shared-land batch-add workflows."""

from customer_dialogs import ImportPreviewDialog, ImportResultDialog, SharedLandBatchDialog
from customer_domain import (
    build_duplicate_signature,
    parse_number,
    parse_shared_land_rows,
)
from customer_excel import ExcelImportWorker
from customer_security import decrypt_value, encrypt_record
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

LAND_FIELDS = ()
EXCEL_SERVICE = None


def configure_import_controller(**dependencies):
    globals().update(dependencies)


class ImportControllerMixin:
    def active_import_repository(self):
        if hasattr(self, "active_record_repository"):
            return self.active_record_repository()
        return self.repository

    def collect_existing_duplicate_signatures(self):
        signatures = {}
        for row in self.active_import_repository().fetch_duplicate_candidates():
            signature = build_duplicate_signature(
                {
                    "district": row["district"],
                    "section": row["section"],
                    "registration_order": row["registration_order"],
                    "land_number": row["land_number"],
                    "owner_name": decrypt_value(self.fernet, row["owner_name"] or ""),
                    "external_id": decrypt_value(self.fernet, row["external_id"] or ""),
                }
            )
            if signature:
                signatures[signature] = row["id"]
        return signatures

    def annotate_import_duplicates(self, records):
        repository = self.active_import_repository()
        existing_signatures = self.collect_existing_duplicate_signatures()
        import_signatures = set()
        duplicate_indexes = set()
        watchlist_indexes = set()
        for index, record in enumerate(records):
            duplicate_reasons = []
            status_reasons = []
            signature = build_duplicate_signature(record)
            if signature:
                if signature in existing_signatures:
                    duplicate_reasons.append("資料庫已存在")
                    record["_existing_record_id"] = existing_signatures[signature]
                if signature in import_signatures:
                    duplicate_reasons.append("本次匯入重複")
                import_signatures.add(signature)
            watchlist_match = repository.find_watchlist_match(
                record.get("owner_name") or ""
            )
            if watchlist_match is not None:
                watchlist_indexes.add(index)
                record["_watchlist_note"] = watchlist_match["note"] or ""
                status_reasons.append("注意名單")
            if duplicate_reasons:
                duplicate_indexes.add(index)
                status_reasons = [*duplicate_reasons, *status_reasons]
            record["_duplicate_reason"] = "、".join(status_reasons)
        return duplicate_indexes, watchlist_indexes

    def get_imported_field_labels(self, column_map):
        label_by_key = {key: label for key, label in LAND_FIELDS}
        seen = []
        for key in column_map.values():
            if key not in seen:
                seen.append(key)
        return "、".join(label_by_key.get(key, key) for key in seen)

    def validate_import_record(self, data):
        return EXCEL_SERVICE.validate_import_record(data)

    def prepare_import_records(self, sheet, header_row, column_map, merged_values):
        return EXCEL_SERVICE.prepare_import_records(
            sheet, header_row, column_map, merged_values
        )

    def build_import_preview_columns(self, column_map):
        label_by_key = {key: label for key, label in LAND_FIELDS}
        seen_keys = []
        for key in column_map.values():
            if key not in seen_keys:
                seen_keys.append(key)
        return [(key, label_by_key.get(key, key)) for key in seen_keys]

    def build_import_result_detail_lines(
        self, imported_records, duplicate_indexes, watchlist_indexes
    ):
        detail_lines = []
        if duplicate_indexes:
            detail_lines.append("本次偵測到的重複資料：")
            shown = 0
            for index in sorted(duplicate_indexes):
                if index >= len(imported_records):
                    continue
                record = imported_records[index]
                detail_lines.append(
                    f"- {record.get('district') or ''} {record.get('section') or ''} "
                    f"{record.get('land_number') or ''} / {record.get('owner_name') or ''} "
                    f"({record.get('_duplicate_reason') or '重複'})"
                )
                shown += 1
                if shown >= 50:
                    detail_lines.append(f"...其餘 {len(duplicate_indexes) - shown} 筆未展開")
                    break
            detail_lines.append("")
        if watchlist_indexes:
            detail_lines.append("本次偵測到的注意名單：")
            shown = 0
            for index in sorted(watchlist_indexes):
                if index >= len(imported_records):
                    continue
                record = imported_records[index]
                note_text = record.get("_watchlist_note") or "無"
                detail_lines.append(
                    f"- {record.get('owner_name') or ''} / {record.get('district') or ''} "
                    f"{record.get('section') or ''} {record.get('land_number') or ''} (備註:{note_text})"
                )
                shown += 1
                if shown >= 50:
                    detail_lines.append(f"...其餘 {len(watchlist_indexes) - shown} 筆未展開")
                    break
            detail_lines.append("")
        detail_lines.append("可依上方摘要查看實際新增與略過筆數。")
        return detail_lines

    def show_import_result_report(
        self,
        imported_labels,
        total_count,
        imported_count,
        skipped_duplicate_count,
        watchlist_count,
        error_count,
        detail_lines,
        error_rows,
        updated_count=0,
    ):
        summary_lines = [
            f"總讀取筆數：{total_count}",
            f"成功新增：{imported_count}",
            f"成功更新：{updated_count}",
            f"重複略過：{skipped_duplicate_count}",
            f"注意名單：{watchlist_count}",
            f"錯誤列數：{error_count}",
            f"對應欄位：{imported_labels}",
        ]
        dialog = ImportResultDialog(summary_lines, detail_lines, error_rows, self)
        dialog.exec()

    def start_excel_worker(self, worker, finished_handler, status_message):
        if self.excel_thread is not None and self.excel_thread.isRunning():
            QMessageBox.information(self, "Excel 處理中", "請等待目前的 Excel 工作完成。")
            return False

        self.excel_thread = QThread(self)
        self.excel_worker = worker
        worker.moveToThread(self.excel_thread)
        self.excel_thread.started.connect(worker.run)
        worker.finished.connect(finished_handler)
        worker.finished.connect(self.excel_thread.quit)
        worker.failed.connect(self.handle_excel_failure)
        worker.failed.connect(self.excel_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self.excel_thread.finished.connect(self.finish_excel_task)
        if self.data_button is not None:
            self.data_button.setEnabled(False)
        self.statusBar().showMessage(status_message)
        self.excel_thread.start()
        return True

    def finish_excel_task(self):
        if self.data_button is not None:
            self.data_button.setEnabled(True)
        if self.excel_thread is not None:
            self.excel_thread.deleteLater()
        self.excel_thread = None
        self.excel_worker = None
        self.statusBar().showMessage("Excel 工作完成。", 3000)

    def handle_excel_failure(self, message):
        QMessageBox.critical(self, "Excel 處理失敗", message)

    def import_xlsx(self):
        if hasattr(self, "ensure_can_modify") and not self.ensure_can_modify("匯入 Excel"):
            return
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "選擇 Excel 檔案",
            "",
            "Excel 檔案 (*.xlsx);;所有檔案 (*.*)",
        )
        if not file_path:
            return
        worker = ExcelImportWorker(EXCEL_SERVICE, file_path)
        self.start_excel_worker(
            worker, self.handle_excel_import_ready, "正在背景讀取 Excel…"
        )

    def handle_excel_import_ready(self, result):
        try:
            repository = self.active_import_repository()
            column_map = result["column_map"]
            records = result["records"]
            error_rows = result["error_rows"]
            if not records and not error_rows:
                QMessageBox.warning(self, "匯入失敗", "這份檔案沒有可匯入的資料。")
                return

            original_records = [dict(record) for record in records]
            duplicate_indexes, watchlist_indexes = self.annotate_import_duplicates(records)
            preview_columns = self.build_import_preview_columns(column_map)
            preview_dialog = ImportPreviewDialog(
                records, preview_columns, duplicate_indexes, self
            )
            if records and preview_dialog.exec() != QDialog.Accepted:
                return

            skipped_duplicate_count = 0
            updated_count = 0
            records_to_insert = list(records)
            update_plans = []
            if records and preview_dialog.import_mode == "skip_duplicates":
                skipped_duplicate_count = len(duplicate_indexes)
                records_to_insert = [
                    record
                    for index, record in enumerate(records)
                    if index not in duplicate_indexes
                ]
            elif records and preview_dialog.import_mode == "update_duplicates":
                records_to_insert = []
                imported_keys = set(column_map.values())
                for index, record in enumerate(records):
                    existing_record_id = record.get("_existing_record_id")
                    if existing_record_id:
                        old_row = repository.get_customer(existing_record_id)
                        if old_row is None:
                            skipped_duplicate_count += 1
                            continue
                        old_plain = self.get_plain_record_data(old_row)
                        new_plain = self.merge_import_update_record(
                            old_plain,
                            record,
                            imported_keys,
                        )
                        update_plans.append((existing_record_id, old_plain, new_plain))
                    elif index in duplicate_indexes:
                        skipped_duplicate_count += 1
                    else:
                        records_to_insert.append(record)

            imported_labels = self.get_imported_field_labels(column_map)
            detail_lines = self.build_import_result_detail_lines(
                original_records, duplicate_indexes, watchlist_indexes
            )
            if not records_to_insert and not update_plans:
                self.show_import_result_report(
                    imported_labels,
                    len(original_records) + len(error_rows),
                    0,
                    skipped_duplicate_count,
                    len(watchlist_indexes),
                    len(error_rows),
                    detail_lines,
                    error_rows,
                    updated_count,
                )
                return

            if watchlist_indexes:
                reply = QMessageBox.question(
                    self,
                    "注意名單提醒",
                    f"本次匯入資料中有 {len(watchlist_indexes)} 筆命中注意名單，仍要繼續匯入嗎？",
                )
                if reply != QMessageBox.Yes:
                    return

            is_api_import = bool(
                getattr(self, "api_mode", False)
                and hasattr(repository, "import_records")
            )
            if is_api_import:
                undo_snapshots = []
            else:
                self.create_safety_backup("import")
                undo_snapshots = repository.capture_customer_snapshots(
                    [record_id for record_id, _old, _new in update_plans]
                )
            encrypted_records = [
                encrypt_record(
                    self.fernet,
                    {key: record.get(key) for key, _label in LAND_FIELDS},
                )
                for record in records_to_insert
            ]
            update_records = []
            change_logs = []
            if update_plans:
                for record_id, old_plain, new_plain in update_plans:
                    update_records.append({**encrypt_record(self.fernet, new_plain), "id": record_id})
                    if not is_api_import and hasattr(self, "build_record_change_logs"):
                        change_logs.extend(
                            self.build_record_change_logs(
                                record_id,
                                old_plain,
                                new_plain,
                                "匯入更新",
                            )
                        )
            if is_api_import:
                import_result = repository.import_records(
                    encrypted_records,
                    update_records,
                    result.get("source_file_name") or "import.xlsx",
                )
                imported_count = int(import_result.get("inserted_count") or 0)
                updated_count = int(import_result.get("updated_count") or 0)
            else:
                imported_count = self.insert_imported_records(encrypted_records)
                if update_records:
                    updated_count = repository.update_customers(update_records)
                if change_logs:
                    repository.add_record_change_logs(change_logs)
                repository.record_composite_undo(
                    "Excel 匯入",
                    undo_snapshots,
                    repository.last_inserted_customer_ids,
                    f"Excel 匯入：新增 {imported_count} 筆，更新 {updated_count} 筆",
                )
                repository.log_operation(
                    "匯入",
                    f"新增 {imported_count} 筆，更新 {updated_count} 筆",
                    f"重複略過 {skipped_duplicate_count} 筆；注意名單 "
                    f"{len(watchlist_indexes)} 筆；錯誤列 {len(error_rows)} 筆",
                )
            self.refresh_records()
            self.show_import_result_report(
                imported_labels,
                len(original_records) + len(error_rows),
                imported_count,
                skipped_duplicate_count,
                len(watchlist_indexes),
                len(error_rows),
                detail_lines,
                error_rows,
                updated_count,
            )
        except Exception as exc:
            QMessageBox.critical(self, "匯入失敗", f"處理匯入結果時發生錯誤：{exc}")

    def insert_imported_records(self, records):
        return self.active_import_repository().insert_customers(records)

    def merge_import_update_record(self, old_plain, imported_record, imported_keys):
        merged = dict(old_plain)
        for key in imported_keys:
            if key in merged:
                merged[key] = imported_record.get(key)
        if "owner_name" in imported_keys:
            merged["name"] = merged.get("owner_name") or ""
        if imported_keys & {"area", "declared_value", "numerator", "denominator", "ping"}:
            merged = self.normalize_record_data(merged)
        return merged

    def batch_add_shared_land_records(self):
        if hasattr(self, "ensure_can_modify") and not self.ensure_can_modify("同地號批量新增"):
            return
        base_data = self.get_form_data()
        dialog = SharedLandBatchDialog(base_data, self)
        while True:
            if dialog.exec() != QDialog.Accepted:
                return
            shared_values, rows_text = dialog.values()
            missing = [
                label
                for key, label in (
                    ("district", "地區"),
                    ("section", "地段"),
                    ("land_number", "地號"),
                )
                if not shared_values.get(key)
            ]
            parsed_rows, errors = parse_shared_land_rows(rows_text)
            if missing:
                errors.insert(0, f"請填寫共用欄位：{'、'.join(missing)}")
            area = parse_number(shared_values.get("area"))
            declared_value = parse_number(shared_values.get("declared_value"))
            if shared_values.get("area") and (area is None or area <= 0):
                errors.append("面積必須是大於 0 的數字")
            if shared_values.get("declared_value") and (
                declared_value is None or declared_value < 0
            ):
                errors.append("公告現值必須是大於或等於 0 的數字")
            if errors:
                shown_errors = errors[:10]
                if len(errors) > len(shown_errors):
                    shown_errors.append(f"…其餘 {len(errors) - len(shown_errors)} 項錯誤")
                QMessageBox.warning(self, "批量資料有誤", "\n".join(shown_errors))
                continue
            break

        records = []
        for parsed_row in parsed_rows:
            record = dict(base_data)
            record.update(shared_values)
            record.update(parsed_row)
            records.append(self.normalize_record_data(record))

        duplicate_indexes, _watchlist_indexes = self.annotate_import_duplicates(records)
        preview_columns = [
            ("registration_order", "登記次序"),
            ("owner_name", "姓名"),
            ("external_id", "身分證"),
            ("address", "地址"),
            ("numerator", "分子"),
            ("denominator", "分母"),
            ("note", "備註"),
            ("visit_log", "出訪記錄"),
            ("district", "地區"),
            ("section", "地段"),
            ("land_number", "地號"),
            ("area", "面積/m²"),
            ("declared_value", "公告現值"),
        ]
        preview = ImportPreviewDialog(records, preview_columns, duplicate_indexes, self)
        if preview.exec() != QDialog.Accepted:
            return
        skipped_count = 0
        if preview.import_mode == "skip_duplicates":
            skipped_count = len(duplicate_indexes)
            records = [
                record
                for index, record in enumerate(records)
                if index not in duplicate_indexes
            ]
        if not records:
            QMessageBox.information(self, "沒有新增資料", "全部資料都已略過。")
            return

        watchlist_count = sum(1 for record in records if "_watchlist_note" in record)
        if watchlist_count:
            reply = QMessageBox.question(
                self,
                "注意名單提醒",
                f"有 {watchlist_count} 筆命中注意名單，仍要繼續新增嗎？",
            )
            if reply != QMessageBox.Yes:
                return

        repository = self.active_import_repository()
        is_api_import = bool(getattr(self, "api_mode", False))
        if not is_api_import:
            self.create_safety_backup("batch-add")
        encrypted_records = [encrypt_record(self.fernet, record) for record in records]
        inserted_count = repository.insert_customers(encrypted_records)
        if not is_api_import:
            repository.record_insert_undo(
                "同地號批量新增",
                repository.last_inserted_customer_ids,
                f"同地號批量新增 {inserted_count} 筆",
            )
            repository.log_operation(
                "批量新增",
                f"新增 {inserted_count} 筆同地號資料",
                f"{shared_values['district']} {shared_values['section']} "
                f"{shared_values['land_number']}；略過重複 {skipped_count} 筆",
            )
        self.refresh_records()
        QMessageBox.information(
            self,
            "批量新增完成",
            f"已新增 {inserted_count} 筆資料；略過重複 {skipped_count} 筆。",
        )
