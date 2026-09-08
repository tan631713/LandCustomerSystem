"""Copy, mobile-share, and Excel-export workflows for table rows."""

import json
from datetime import datetime

from customer_excel import ExcelExportWorker
from customer_mobile_share import MobileShareDialog
from customer_security import decrypt_value
from customer_word import write_records_docx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

APP_DIR = None
TABLE_COLUMNS = ()


def configure_export_controller(**dependencies):
    globals().update(dependencies)


class PreviousExportDuplicatesDialog(QDialog):
    """Shown when some of the rows about to be exported already match some
    "you've handled this before" condition -- either exported to Excel
    before (see ExportControllerMixin._exclude_previously_exported_rows())
    or already carrying a user-chosen "already mailed" tag (see
    _exclude_rows_with_mail_duplicate_tag()). Lets the user tick off which
    of those to leave out of this export; unticked rows are exported as
    usual. window_title/message default to the original Excel-export
    wording so existing callers don't need to change."""

    def __init__(
        self, duplicate_rows, parent=None, *, window_title=None, message=None, reasons=None
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title or "偵測到已匯出過的地主")
        self.resize(520, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                message
                or (
                    f"這次要匯出的資料裡，有 {len(duplicate_rows)} 筆地主先前已經匯出過 Excel。\n"
                    "勾選要「排除」的項目（不勾選的會照常匯出）："
                )
            )
        )

        reasons = reasons or {}
        self.list_widget = QListWidget()
        for row in duplicate_rows:
            raw = row.get("raw") or {}
            label = " ".join(
                str(raw.get(key) or "")
                for key in ("district", "section", "subsection", "land_number", "owner_name")
                if raw.get(key)
            ).strip() or f"資料 ID {row['id']}"
            reason = reasons.get(int(row["id"]))
            if reason:
                label = f"{label}（{reason}）"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, int(row["id"]))
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        select_all_row = QHBoxLayout()
        select_all_button = QPushButton("全部勾選")
        select_all_button.clicked.connect(self._check_all)
        clear_all_button = QPushButton("全部取消勾選")
        clear_all_button.clicked.connect(self._uncheck_all)
        select_all_row.addWidget(select_all_button)
        select_all_row.addWidget(clear_all_button)
        select_all_row.addStretch(1)
        layout.addLayout(select_all_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("繼續匯出")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _check_all(self):
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setCheckState(Qt.Checked)

    def _uncheck_all(self):
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setCheckState(Qt.Unchecked)

    def excluded_ids(self):
        excluded = set()
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                excluded.add(int(item.data(Qt.UserRole)))
        return excluded


MAIL_DUPLICATE_TAG_SETTING = "mail_duplicate_detection_tag_name"


def load_mail_duplicate_tag(repository):
    """Which tag (if any) "匯出選取 Word" should check for before exporting
    -- e.g. "已寄信", so re-mailing the same land owner isn't accidentally
    included in a new mailing list. This is a plain local machine setting
    (same treatment as the Google Geocoding API key -- see its own
    comment in customer_productivity.py for why: it must never be tied to
    the per-login Fernet key, which is a random, throwaway key every
    single login in API mode), not shared with the home server -- which
    tag to currently watch for is a personal working preference, unlike
    the excel_exports history itself (shared per customer, so every
    company laptop connected to the same server agrees on what was
    exported)."""
    return repository.get_setting(MAIL_DUPLICATE_TAG_SETTING, "") or None


def save_mail_duplicate_tag(repository, tag_name):
    repository.set_setting(MAIL_DUPLICATE_TAG_SETTING, tag_name)


def clear_mail_duplicate_tag(repository):
    repository.set_setting(MAIL_DUPLICATE_TAG_SETTING, "")


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
        rows_by_id = {}
        seen_nodes = set()
        for proxy_index in self.table_view.selectionModel().selectedIndexes():
            if not proxy_index.isValid():
                continue
            source_index = self.source_table_index(proxy_index)
            node = self.table_model.node_for_index(source_index)
            if node is None:
                continue
            node_key = (
                node.kind,
                node.group.state_id,
                None if node.record is None else int(node.record["id"]),
            )
            if node_key in seen_nodes:
                continue
            seen_nodes.add(node_key)
            records = node.group.records if node.kind == "land" else [node.record]
            for record in records:
                rows_by_id[int(record["id"])] = record
        return list(rows_by_id.values())

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

        def tree_position(index):
            parent = index.parent()
            return (
                parent.row() if parent.isValid() else index.row(),
                1 if parent.isValid() else 0,
                index.row(),
            )

        selected_row_keys = sorted(
            {tree_position(index) for index in selected_indexes}
        )
        header = self.table_view.horizontalHeader()
        selected_columns = sorted(
            {index.column() for index in selected_indexes},
            key=lambda column: header.visualIndex(column),
        )

        copied_lines = []
        view_model = self.table_view.model()
        for parent_row, depth, row_number in selected_row_keys:
            values = []
            for column_number in selected_columns:
                matching = [
                    index
                    for index in selected_indexes
                    if tree_position(index) == (parent_row, depth, row_number)
                    and index.column() == column_number
                ]
                if not matching:
                    values.append("")
                    continue
                value = view_model.data(matching[0], Qt.DisplayRole)
                values.append(str(value or ""))
            copied_lines.append("\t".join(values))

        QApplication.clipboard().setText("\n".join(copied_lines))
        self.statusBar().showMessage(
            f"已複製 {len(selected_row_keys)} 列、{len(selected_columns)} 欄。",
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
        self._show_non_modal_dialog(dialog)

    def _exclude_previously_exported_rows(self, rows):
        """Checks which of `rows` were exported to Excel before (at any
        point) and, if any were, lets the user pick which to leave out of
        this export via PreviousExportDuplicatesDialog. Returns the rows
        to actually export, or None if the user cancelled the whole
        export from that dialog."""
        ids = [int(row["id"]) for row in rows]
        try:
            from customer_error_handler import log_diagnostic_event
        except Exception:
            def log_diagnostic_event(*_args, **_kwargs):
                pass
        try:
            previously_exported_ids = (
                self.active_record_repository().list_previously_exported_customer_ids(ids)
            )
        except Exception as exc:
            # Best-effort check -- a lookup failure (e.g. transient
            # connection hiccup in API mode) must never block an export
            # the user is actively trying to run. Logged (not silently
            # swallowed) because a real user reported the duplicate
            # prompt never appearing at all -- without this, that failure
            # mode is indistinguishable from "genuinely nothing was
            # exported before" and unattributable from a bug report alone.
            try:
                log_diagnostic_event(
                    "ExportControllerMixin.list_previously_exported_customer_ids",
                    f"lookup failed for ids={ids!r}: {exc!r}",
                )
            except Exception:
                pass
            return rows
        # Unconditional (not just on-exception) diagnostic: a second real
        # bug report said the check runs with no exception at all (no
        # application-error.log entry either) but still never flags a
        # record exported moments earlier via "匯出選取資料". That means
        # either this call is genuinely returning an empty set every time
        # (the write in handle_excel_export_ready never reached the
        # database) or something before this point never even calls
        # in -- logging every call's inputs/outputs, not just failures,
        # is the only way to tell those apart from a real report instead
        # of guessing blind.
        try:
            log_diagnostic_event(
                "ExportControllerMixin.list_previously_exported_customer_ids",
                f"checked ids={ids!r}, previously_exported_ids={sorted(previously_exported_ids)!r}",
            )
        except Exception:
            pass
        if not previously_exported_ids:
            return rows
        duplicate_rows = [row for row in rows if int(row["id"]) in previously_exported_ids]
        dialog = PreviousExportDuplicatesDialog(duplicate_rows, self)
        if dialog.exec() != QDialog.Accepted:
            return None
        excluded_ids = dialog.excluded_ids()
        return [row for row in rows if int(row["id"]) not in excluded_ids]

    def export_rows_to_xlsx(self, rows):
        if not rows:
            QMessageBox.information(self, "沒有資料", "目前沒有可匯出的資料。")
            return
        export_columns = self.get_export_columns()
        if not export_columns:
            QMessageBox.information(self, "沒有可匯出欄位", "目前所有資料欄位都被隱藏，無法匯出。")
            return

        rows = self._exclude_previously_exported_rows(rows)
        if rows is None:
            return
        if not rows:
            QMessageBox.information(self, "沒有資料", "已全部排除已匯出過的資料，沒有資料可匯出。")
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
        # start_excel_worker() only guards against a *second* export
        # starting while one is already running, so there is never more
        # than one export in flight -- safe to stash the ids here and
        # read them back once in handle_excel_export_ready().
        self._pending_excel_export_ids = [int(row["id"]) for row in rows]
        worker = ExcelExportWorker(file_path, raw_rows, export_columns)
        self.start_excel_worker(worker, self.handle_excel_export_ready, "正在背景匯出 Excel…")

    def handle_excel_export_ready(self, file_path, row_count):
        # Real production bug: this used to be reached via a plain Python
        # closure passed as worker.finished's slot instead of a bound
        # method on self. Qt can only infer a receiver's thread affinity
        # (and therefore auto-upgrade the connection to a queued one) for
        # an actual QObject slot -- a bare closure has no such affinity,
        # so the connection silently ran direct, invoking this whole body
        # (including the QMessageBox below) on the worker thread rather
        # than the GUI thread. Symptom exactly as reported: a blank,
        # frozen "匯出完成" dialog and Windows marking the app "沒有回應".
        # Passing this bound method to start_excel_worker() (like every
        # other worker in this codebase already does) keeps the mark-as-
        # exported bookkeeping right here, genuinely running on the GUI
        # thread via Qt's own auto-queued connection -- exactly the same
        # crash-prevention rule documented on BatchGeocodeWorker and
        # start_record_search() elsewhere in this app.
        try:
            from customer_error_handler import log_diagnostic_event
        except Exception:
            def log_diagnostic_event(*_args, **_kwargs):
                pass
        exported_ids = getattr(self, "_pending_excel_export_ids", None) or []
        self._pending_excel_export_ids = None
        # Unconditional: a bug report said "exported once, then re-
        # exporting the same record never flags it as a duplicate" with
        # no application-error.log entry at all -- so either
        # exported_ids ends up empty here (nothing to mark, silently, no
        # exception) or mark_customers_exported_to_excel() itself
        # succeeds but the write never actually lands. Logging what this
        # call actually saw, every time, is the only way to tell those
        # apart from the matching log in
        # _exclude_previously_exported_rows instead of guessing blind.
        try:
            log_diagnostic_event(
                "ExportControllerMixin.mark_customers_exported_to_excel",
                f"about to mark exported_ids={exported_ids!r}",
            )
        except Exception:
            pass
        if exported_ids:
            try:
                self.active_record_repository().mark_customers_exported_to_excel(exported_ids)
            except Exception as exc:
                # Best-effort bookkeeping -- never let a failure here hide
                # the fact the export itself already succeeded. Logged
                # (see the matching lookup-failure log in
                # _exclude_previously_exported_rows above) so a silent
                # failure here -- which would explain "exported once, but
                # re-exporting never detects it as a duplicate" -- is
                # attributable instead of indistinguishable from working
                # correctly.
                try:
                    log_diagnostic_event(
                        "ExportControllerMixin.mark_customers_exported_to_excel",
                        f"marking failed for ids={exported_ids!r}: {exc!r}",
                    )
                except Exception:
                    pass
            else:
                try:
                    log_diagnostic_event(
                        "ExportControllerMixin.mark_customers_exported_to_excel",
                        f"marking succeeded for ids={exported_ids!r}",
                    )
                except Exception:
                    pass
        QMessageBox.information(
            self,
            "匯出完成",
            f"已匯出 {row_count} 筆資料。\n檔案位置：{file_path}",
        )

    def export_selected_xlsx(self):
        rows = self.selected_or_checked_rows()
        if not rows:
            QMessageBox.warning(self, "尚未選取", "請先在表格選取要匯出的資料。")
            return
        self.export_rows_to_xlsx(rows)

    def configure_mail_duplicate_tag(self):
        try:
            available_tags = [dict(row) for row in self.active_record_repository().list_tags()]
        except Exception as exc:
            QMessageBox.warning(self, "無法讀取標籤", f"讀取標籤清單失敗：{exc}")
            return
        tag_names_list = [str(row.get("name") or "").strip() for row in available_tags]
        tag_names_list = [name for name in tag_names_list if name]
        if not tag_names_list:
            QMessageBox.information(
                self, "沒有標籤", "系統裡目前還沒有任何標籤，請先到「標籤管理」新增標籤（例如「已寄信」）。"
            )
            return
        no_detection_label = "（不偵測）"
        options = [no_detection_label] + tag_names_list
        current = load_mail_duplicate_tag(self.repository) or ""
        current_index = options.index(current) if current in tag_names_list else 0
        choice, accepted = QInputDialog.getItem(
            self,
            "設定寄信重複偵測標籤",
            "匯出「選取 Word」前，自動偵測已有下列標籤的地主並提示排除：",
            options,
            current_index,
            editable=False,
        )
        if not accepted:
            return
        if choice == no_detection_label:
            clear_mail_duplicate_tag(self.repository)
        else:
            save_mail_duplicate_tag(self.repository, choice)

    def _customers_tagged_elsewhere(self, tag_name):
        """Scans every customer in the system (not just today's export
        selection) for the configured tag, and returns the decrypted
        external_id/address values seen on those tagged records. Used so
        a person mailed once under a *different* land parcel, or a
        mailing address shared by multiple owners, is still caught --
        not just an exact repeat of the same land record. tag_items is
        already included on every row fetch_all_customer_rows() returns
        (both local and API mode), so this needs no new database table or
        server endpoint -- it is the same data already loaded to paint
        each row's tag pills, just cross-referenced ahead of time."""
        external_ids = set()
        addresses = set()
        for row in self.active_record_repository().fetch_all_customer_rows():
            row = dict(row)
            tag_items = row.get("tag_items") or []
            if isinstance(tag_items, str):
                try:
                    tag_items = json.loads(tag_items)
                except (TypeError, ValueError):
                    tag_items = []
            if not any(
                str(item.get("name") or "").strip() == tag_name for item in tag_items
            ):
                continue
            external_id = str(decrypt_value(self.fernet, row.get("external_id")) or "").strip()
            address = str(decrypt_value(self.fernet, row.get("address")) or "").strip()
            if external_id:
                external_ids.add(external_id)
            if address:
                addresses.add(address)
        return external_ids, addresses

    def _exclude_rows_with_mail_duplicate_tag(self, rows):
        """Checks `rows` against the tag configure_mail_duplicate_tag()
        set up (if any) -- e.g. "已寄信" -- and, if any already carry it
        directly, or share the same 身分證/統一編號 (external_id, i.e. the
        same real owner under a different land parcel/持分) or the same
        地址 (address, e.g. co-residents sharing one mailbox) as a
        customer who does, lets the user pick which to leave out via the
        same PreviousExportDuplicatesDialog the Excel-export duplicate
        check uses. Unlike that check, this never writes anything back:
        the tag itself is still applied manually by the user after
        actually mailing the letters, matching the existing workflow --
        exporting a Word file is not the same as having mailed it.
        Returns the rows to actually export, or None if the user
        cancelled from the dialog."""
        tag_name = load_mail_duplicate_tag(self.repository)
        if not tag_name:
            return rows

        def has_tag(row):
            tag_items = (row.get("raw") or {}).get("tag_items") or []
            return any(
                str(item.get("name") or "").strip() == tag_name for item in tag_items
            )

        rows_without_the_tag = [row for row in rows if not has_tag(row)]
        tagged_external_ids, tagged_addresses = (
            self._customers_tagged_elsewhere(tag_name) if rows_without_the_tag else (set(), set())
        )

        reasons = {}
        duplicate_rows = []
        for row in rows:
            raw = row.get("raw") or {}
            row_id = int(row["id"])
            if has_tag(row):
                reasons[row_id] = f"本筆已有「{tag_name}」標籤"
                duplicate_rows.append(row)
                continue
            external_id = str(raw.get("external_id") or "").strip()
            address = str(raw.get("address") or "").strip()
            if external_id and external_id in tagged_external_ids:
                reasons[row_id] = f"同一地主已有其他地號標記「{tag_name}」"
                duplicate_rows.append(row)
            elif address and address in tagged_addresses:
                reasons[row_id] = f"同一地址已有其他地主標記「{tag_name}」"
                duplicate_rows.append(row)

        if not duplicate_rows:
            return rows
        dialog = PreviousExportDuplicatesDialog(
            duplicate_rows,
            self,
            window_title=f"偵測到已有「{tag_name}」標籤的地主",
            message=(
                f"這次要匯出的資料裡，有 {len(duplicate_rows)} 筆跟「{tag_name}」標籤有關\n"
                "（本筆已有標籤、或同一地主／同一地址的其他資料已有標籤）。\n"
                "勾選要「排除」的項目（不勾選的會照常匯出）："
            ),
            reasons=reasons,
        )
        if dialog.exec() != QDialog.Accepted:
            return None
        excluded_ids = dialog.excluded_ids()
        return [row for row in rows if int(row["id"]) not in excluded_ids]

    def export_selected_word(self):
        rows = self.selected_or_checked_rows()
        if not rows:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要匯出的資料。")
            return
        rows = self._exclude_rows_with_mail_duplicate_tag(rows)
        if rows is None:
            return
        if not rows:
            QMessageBox.information(self, "沒有資料", "已全部排除已有標籤的資料，沒有資料可匯出。")
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
