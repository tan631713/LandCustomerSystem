"""Qt coordination for paged browsing and background customer searches."""

from customer_search import (
    CustomerDecryptionCache,
    CustomerRecordProcessor,
    CustomerSearchWorker,
)
from customer_land_tree import group_land_records
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QMessageBox

TABLE_COLUMNS = ()
TABLE_BATCH_SIZE = 200
ASYNC_SEARCH_THRESHOLD = 500
SEARCH_CANCEL_WAIT_MS = 2000
ROW_COLOR_CHECKED = None
ROW_COLOR_WATCHLIST = None
ROW_COLOR_OVERDUE = None
ROW_COLOR_NOTE = None


def configure_search_controller(**dependencies):
    globals().update(dependencies)


class SearchControllerMixin:
    def land_search_is_active(self):
        return bool(
            self.search_input.text().strip()
            or self.show_checked_only
            or any(
                str(value or "").strip()
                for value in self.advanced_search_criteria.values()
            )
        )

    def refresh_records_for_search(self, record_to_select=None):
        """Run an explicit search and manage only temporary search expansion."""

        self.refresh_records(
            record_to_select,
            auto_expand_search_matches=self.land_search_is_active(),
        )

    def cancel_pending_record_searches(self):
        """Fully stop any in-flight background searches before superseding them.

        Requesting interruption alone is not enough: the worker's database
        fetch is not interruptible mid-query, so without an explicit
        quit()/wait() here a rapid second search could start while the
        previous search's QThread genuinely still runs, leaving two
        background search threads alive at the same time. That overlap
        (two threads each opening their own SQLite connection and
        registering SQL functions concurrently) produced an intermittent
        access-violation crash. Mirror the same quit()+wait() pattern
        already used by closeEvent() so at most one record-search thread
        is ever running.
        """
        pending = list(self.record_searches.values())
        for thread, _worker in pending:
            thread.requestInterruption()
        for thread, _worker in pending:
            thread.quit()
            thread.wait(SEARCH_CANCEL_WAIT_MS)

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
            privacy_mask_enabled=self.privacy_mask_enabled,
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
        self.cancel_pending_record_searches()
        self.refresh_watchlist_cache()
        keyword = self.search_input.text().strip().casefold()
        filter_field = self.get_filter_field()
        sort_field = self.get_sort_field()
        reverse = self.get_sort_reverse()
        target_id = record_to_select if record_to_select is not None else self.selected_record_id
        # Tri-state: True starts temporary search expansion, False clears it,
        # and None preserves whatever explicit search previously established.
        search_auto_expand = (
            None
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
            with self._programmatic_land_expansion(restoring=True):
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
        self._record_search_context[request_id] = (
            target_id,
            tree_state,
            search_auto_expand,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # finished/failed/cancelled used to also be wired directly to
        # thread.quit()/worker.deleteLater() on the same signal, which let
        # the worker schedule its own teardown (from its own thread) in the
        # very same emit() call that was still delivering the search
        # results to the main thread. Route everything through one
        # main-thread handler instead, so results are fully handled first
        # and teardown (quit + wait + deleteLater) always happens afterward,
        # synchronously, from the main thread.
        #
        # Connecting to bound methods of `self` (not bare lambdas) with an
        # explicit Qt.QueuedConnection is deliberate, not stylistic: a real
        # production crash (Windows Application Error, access violation,
        # confirmed via faulthandler -- see native-crash-trace.log) showed
        # this exact signal chain -- worker.finished.emit() in
        # CustomerSearchWorker.run(), which executes on `thread`, this
        # search's background QThread -- running all the way down into
        # apply_record_rows()/restore_land_tree_view_state() and touching
        # RecordTableModel.parent() while still on that background thread.
        # QAbstractItemModel/QTreeView are not thread-safe; touching them
        # off the GUI thread is undefined behaviour in Qt itself, which
        # matches everything observed across many failed fix attempts
        # aimed at the model's internal-pointer handling instead: crash
        # locations/modules that varied release to release (python314.dll
        # at different offsets, then Qt6Core.dll), and zero effect from any
        # amount of Python-level exception handling.
        #
        # The likely mechanism: connecting a Signal directly to a bare
        # lambda (as this code used to) gives Qt.AutoConnection no bound
        # QObject to read a thread affinity from, so there is no reliable
        # guarantee it resolves to a queued, marshaled-to-the-main-thread
        # call rather than a same-thread direct call. A bound method of
        # `self` (this window, a QObject that lives on the main thread for
        # its entire life) gives AutoConnection an unambiguous receiver
        # thread to compare against the emitting worker thread -- this is
        # the standard, Qt-documented mechanism for cross-thread
        # signal/slot delivery. Qt.QueuedConnection is passed explicitly
        # anyway so this does not silently regress back to a direct call
        # if `self`'s thread affinity ever changes for an unrelated reason.
        worker.finished.connect(self._handle_record_search_finished, Qt.QueuedConnection)
        worker.failed.connect(self._handle_record_search_failed, Qt.QueuedConnection)
        worker.cancelled.connect(self._handle_record_search_cancelled, Qt.QueuedConnection)
        self.statusBar().showMessage("正在背景搜尋資料…")
        thread.start()

    def _handle_record_search_finished(self, completed_id, rows):
        search = self.record_searches.get(completed_id)
        if search is None:
            return
        thread, worker = search
        target_id, tree_state, search_auto_expand = self._record_search_context.pop(
            completed_id, (None, None, None)
        )
        self._finish_record_search(
            completed_id,
            thread,
            worker,
            lambda: self.handle_record_search_ready(
                completed_id,
                rows,
                target_id,
                tree_state,
                search_auto_expand,
            ),
        )

    def _handle_record_search_failed(self, completed_id, message):
        search = self.record_searches.get(completed_id)
        if search is None:
            return
        thread, worker = search
        self._record_search_context.pop(completed_id, None)
        self._finish_record_search(
            completed_id,
            thread,
            worker,
            lambda: self.handle_record_search_failure(completed_id, message),
        )

    def _handle_record_search_cancelled(self, completed_id):
        search = self.record_searches.get(completed_id)
        if search is None:
            return
        thread, worker = search
        self._record_search_context.pop(completed_id, None)
        self._finish_record_search(completed_id, thread, worker, None)

    def _finish_record_search(self, request_id, thread, worker, callback):
        if callback is not None:
            callback()
        self.record_searches.pop(request_id, None)
        # v1.9.36 changed this to an async teardown (thread.quit(), then
        # deleteLater() deferred via thread.finished) specifically to avoid
        # a blocking thread.wait() here freezing the GUI. That introduced a
        # real, if subtle, use-after-thread-death race: `worker`'s own
        # thread affinity is still the background `thread` at the moment
        # `thread.finished` fires (worker.moveToThread(thread) was never
        # undone), so worker.deleteLater()'s deferred-delete event was
        # being posted to a queue whose event loop could already be gone.
        # A production crash (Qt6Core.dll, access violation, confirmed via
        # faulthandler -- see native-crash-trace.log) followed almost
        # immediately after that version shipped, with no Python frames on
        # the stack at all -- consistent with a fault deep inside Qt's own
        # cross-thread object/event-queue bookkeeping rather than anything
        # our own code executes. Reverted to the blocking wait(): it is
        # slower (blocks the GUI for up to SEARCH_CANCEL_WAIT_MS in the
        # worst case) but unambiguously safe, since worker/thread are only
        # deleted once the background thread has verifiably, fully
        # stopped. The perceived "2-3 second wait after adding an owner"
        # this was trying to fix was never actually confirmed to BE this
        # wait() -- it may simply be the real cost of grouping/processing
        # a large dataset over the network, which no amount of teardown
        # optimization here would change. Do not re-attempt an async
        # teardown without a way to verify it against a real Windows
        # session; this class of QThread lifecycle bug does not reproduce
        # in the local (offscreen, small-dataset) test suite.
        thread.quit()
        thread.wait(SEARCH_CANCEL_WAIT_MS)
        worker.deleteLater()
        thread.deleteLater()

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
            with self._programmatic_land_expansion(restoring=True):
                self.table_model.set_rows(rows)
        self.apply_table_preferences()
        self.update_land_page_status()
        selection_restored = self.restore_land_tree_view_state(
            tree_state,
            search_auto_expand=search_auto_expand,
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
