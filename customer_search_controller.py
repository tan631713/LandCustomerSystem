"""Qt coordination for paged browsing and background customer searches."""

from customer_search import (
    CustomerDecryptionCache,
    CustomerRecordProcessor,
    CustomerSearchWorker,
)
from customer_land_tree import group_land_records
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
        data_access = getattr(self, "data_access", None)
        if data_access is not None:
            return data_access.records
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

    def refresh_records(
        self,
        record_to_select=None,
        *,
        tree_state=None,
        auto_expand_search_matches=None,
        preserve_existing_model=False,
    ):
        if tree_state is None:
            tree_state = self.capture_land_tree_view_state()
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
        search_active = bool(
            keyword
            or self.show_checked_only
            or any(
                str(value or "").strip()
                for value in self.advanced_search_criteria.values()
            )
        )
        search_auto_expand = (
            search_active
            if auto_expand_search_matches is None
            else bool(auto_expand_search_matches)
        )
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

        record_count = record_repository.count_customers()
        if record_count > ASYNC_SEARCH_THRESHOLD and not preserve_existing_model:
            # Keep startup responsive and immediately useful while the
            # hierarchy-aware grouping runs in the worker.  This is a preview,
            # not the final pagination result; the worker replaces it with
            # complete land groups.
            preview_rows = [
                processor.build_record(row, include_search_text=False)
                for row in record_repository.fetch_customer_page(TABLE_BATCH_SIZE)
            ]
            preview = group_land_records(
                preview_rows,
                sort_field=sort_field,
                reverse=reverse,
            )
            self.table_model.set_rows(preview)
            self.table_model.total_count = record_count
            self.table_model.ownership_total_count = record_count
            # Legacy views/tests may ask whether more preview data exists.
            # The actual full result is owned by the background worker.
            self.table_model._legacy_total_count = record_count
            self.table_model.page_loader = lambda _offset, _limit: []
            self.table_model._background_preview_pending = True
            self.apply_table_preferences()
            self.update_land_page_status()
            self._land_search_auto_expand = search_auto_expand
            self.restore_land_tree_view_state(
                tree_state,
                search_auto_expand=search_auto_expand,
                fallback_record_id=target_id,
            )
            self.start_record_search(
                request_id,
                row_loader,
                process_rows,
                target_id,
                tree_state,
                search_auto_expand,
            )
            return
        if record_count > ASYNC_SEARCH_THRESHOLD:
            # A content-only save must not replace the live tree with a
            # preview model.  Keep the current nodes visible while the server
            # result is processed, then update those nodes in place.
            self.start_record_search(
                request_id,
                row_loader,
                process_rows,
                target_id,
                tree_state,
                search_auto_expand,
            )
            return

        rows = process_rows(row_loader(), lambda: False)
        self.apply_record_rows(
            rows,
            target_id,
            tree_state,
            search_auto_expand=search_auto_expand,
        )

    def start_record_search(
        self,
        request_id,
        row_loader,
        row_processor,
        target_id,
        tree_state,
        search_auto_expand,
    ):
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
                completed_id,
                rows,
                target_id,
                tree_state,
                search_auto_expand,
            )
        )
        worker.failed.connect(self.handle_record_search_failure)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(lambda: self.finish_record_search(request_id))
        self.statusBar().showMessage("正在背景搜尋資料…")
        thread.start()

    def handle_record_search_ready(
        self,
        request_id,
        rows,
        target_id,
        tree_state,
        search_auto_expand,
    ):
        if request_id != self.record_search_request_id:
            return
        self.apply_record_rows(
            rows,
            target_id,
            tree_state,
            search_auto_expand=search_auto_expand,
        )
        self.statusBar().showMessage(
            f"搜尋完成：土地 {self.table_model.total_count} 筆／"
            f"持分 {self.table_model.ownership_total_count} 筆。",
            3000,
        )

    def handle_record_search_failure(self, request_id, message):
        if request_id != self.record_search_request_id:
            return
        QMessageBox.critical(self, "搜尋失敗", message)

    def finish_record_search(self, request_id):
        search = self.record_searches.pop(request_id, None)
        if search is not None:
            thread, _worker = search
            thread.deleteLater()

    def apply_record_rows(
        self,
        rows,
        target_id,
        tree_state=None,
        *,
        search_auto_expand=None,
    ):
        if tree_state is None:
            tree_state = self.capture_land_tree_view_state()
        updated_in_place = self.table_model.update_rows_in_place(rows)
        if not updated_in_place:
            self.table_model.set_rows(rows)
        self.apply_table_preferences()
        self.update_land_page_status()
        if search_auto_expand is None:
            search_auto_expand = bool(
                self.search_input.text().strip()
                or self.show_checked_only
                or any(
                    str(value or "").strip()
                    for value in self.advanced_search_criteria.values()
                )
            )
        self._land_search_auto_expand = bool(search_auto_expand)
        selection_restored = self.restore_land_tree_view_state(
            tree_state,
            search_auto_expand=bool(search_auto_expand),
            fallback_record_id=target_id,
        )
        if selection_restored:
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
