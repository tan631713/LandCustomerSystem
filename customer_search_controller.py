"""Qt coordination for paged browsing and background customer searches."""

from customer_search import (
    CustomerDecryptionCache,
    CustomerRecordProcessor,
    CustomerSearchWorker,
)
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

TABLE_COLUMNS = ()
TABLE_BATCH_SIZE = 200
ASYNC_SEARCH_THRESHOLD = 500
ROW_COLOR_CHECKED = None
ROW_COLOR_WATCHLIST = None
ROW_COLOR_OVERDUE = None
ROW_COLOR_NOTE = None


def configure_search_controller(**dependencies):
    globals().update(dependencies)


class SearchControllerMixin:
    def active_record_repository(self):
        return getattr(self, "record_repository", self.repository)

    def create_record_processor(
        self,
        *,
        keyword="",
        filter_field="all",
        sort_field="rowid",
        reverse=True,
        advanced_criteria=None,
        checked_ids=None,
        show_checked_only=False,
    ):
        if not hasattr(self, "search_decryption_cache"):
            self.search_decryption_cache = CustomerDecryptionCache()
        self.search_decryption_cache.sync_revision(
            self.active_record_repository().data_revision
        )
        return CustomerRecordProcessor(
            fernet=self.fernet,
            table_columns=TABLE_COLUMNS,
            checked_ids=(self.checked_record_ids if checked_ids is None else checked_ids),
            watchlist_names=self.watchlist_names,
            show_full_external_id=self.show_full_external_id,
            checked_color=ROW_COLOR_CHECKED,
            watchlist_color=ROW_COLOR_WATCHLIST,
            overdue_color=ROW_COLOR_OVERDUE,
            note_color=ROW_COLOR_NOTE,
            keyword=keyword,
            filter_field=filter_field,
            sort_field=sort_field,
            reverse=reverse,
            advanced_criteria=advanced_criteria,
            show_checked_only=show_checked_only,
            decryption_cache=self.search_decryption_cache,
        )

    def refresh_records(self, record_to_select=None):
        record_repository = self.active_record_repository()
        self.record_search_request_id += 1
        request_id = self.record_search_request_id
        for thread, _worker in list(self.record_searches.values()):
            thread.requestInterruption()
        self.refresh_watchlist_cache()
        keyword = self.search_input.text().strip().casefold()
        filter_field = self.get_filter_field()
        sort_field = self.get_sort_field()
        reverse = self.get_sort_reverse()
        target_id = record_to_select if record_to_select is not None else self.selected_record_id
        use_paged_browse = (
            not keyword
            and filter_field == "all"
            and sort_field == "rowid"
            and reverse
            and not self.show_checked_only
            and not any(str(value or "").strip() for value in self.advanced_search_criteria.values())
        )
        if use_paged_browse:
            initial_rows = self.load_customer_page(0, TABLE_BATCH_SIZE)
            self.table_model.set_paged_rows(
                initial_rows,
                record_repository.count_customers(),
                self.load_customer_page,
            )
            rows = initial_rows
            self.apply_table_preferences()
            if target_id is not None and self.select_record_in_table(target_id):
                return
            if not rows:
                self.table_view.clearSelection()
                if self.selected_record_id is not None:
                    self.new_record()
            return

        checked_ids = set(self.checked_record_ids)
        advanced_criteria = dict(self.advanced_search_criteria)
        processor = self.create_record_processor(
            keyword=keyword,
            filter_field=filter_field,
            sort_field=sort_field,
            reverse=reverse,
            checked_ids=checked_ids,
            advanced_criteria=advanced_criteria,
            show_checked_only=self.show_checked_only,
        )
        process_rows = processor.process
        row_loader = lambda: record_repository.fetch_search_candidate_rows(
            keyword=keyword,
            filter_field=filter_field,
            advanced_criteria=advanced_criteria,
        )

        if record_repository.count_customers() > ASYNC_SEARCH_THRESHOLD:
            self.start_record_search(request_id, row_loader, process_rows, target_id)
            return

        rows = process_rows(row_loader(), lambda: False)
        self.apply_record_rows(rows, target_id)

    def start_record_search(self, request_id, row_loader, row_processor, target_id):
        thread = QThread(self)
        worker = CustomerSearchWorker(
            request_id,
            row_loader,
            row_processor,
        )
        self.record_searches[request_id] = (thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda completed_id, rows: self.handle_record_search_ready(
                completed_id, rows, target_id
            )
        )
        worker.failed.connect(self.handle_record_search_failure)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(lambda: self.finish_record_search(request_id))
        self.statusBar().showMessage("正在背景搜尋資料…")
        thread.start()

    def handle_record_search_ready(self, request_id, rows, target_id):
        if request_id != self.record_search_request_id:
            return
        self.apply_record_rows(rows, target_id)
        self.statusBar().showMessage(f"搜尋完成，共 {len(rows)} 筆。", 3000)

    def handle_record_search_failure(self, request_id, message):
        if request_id != self.record_search_request_id:
            return
        QMessageBox.critical(self, "搜尋失敗", message)

    def finish_record_search(self, request_id):
        search = self.record_searches.pop(request_id, None)
        if search is not None:
            thread, _worker = search
            thread.deleteLater()

    def apply_record_rows(self, rows, target_id):
        self.table_model.set_rows(rows)
        self.apply_table_preferences()
        if target_id is not None and self.select_record_in_table(target_id):
            return

        if not rows:
            self.table_view.clearSelection()
            if self.selected_record_id is not None:
                self.new_record()

    def load_customer_page(self, offset, limit):
        processor = self.create_record_processor()
        record_repository = self.active_record_repository()
        before_id = None
        if offset and self.table_model is not None and self.table_model.all_rows:
            before_id = self.table_model.all_rows[-1]["id"]
        return [
            processor.build_record(row, include_search_text=False)
            for row in record_repository.fetch_customer_page(limit, before_id=before_id)
        ]
