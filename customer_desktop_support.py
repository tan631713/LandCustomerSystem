"""Shared dependency seams for desktop workflow mixins."""

import logging
import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

logger = logging.getLogger(__name__)


class DesktopSupportMixin:
    """Resolve replaceable UI components and operation logging."""

    def _app_component(self, name):
        module = sys.modules[self.__class__.__module__]
        return getattr(module, name)

    # 都市計畫 hooks called by the record/selection/search workflows. The real
    # implementations live in UrbanPlanWorkflowMixin, which is listed *before*
    # this class in LandApp's bases; windows (and test harnesses) without it
    # simply never have a plan view.
    def plan_view_active(self):
        return False

    def refresh_urban_plan_view(self, rows=None, *, force=False):
        return None

    def urban_plan_checks_changed(self):
        return None

    urban_plan_input_id = 0

    def urban_plans_available(self):
        return False

    def load_urban_plan_into_form(self, row):
        return None

    def set_urban_plan_form_value(self, plan_id, plan_name=None):
        return None

    def urban_plan_form_value(self):
        return 0

    def update_urban_plan_view_metrics(self, row_height):
        return None

    def _log_operation(self, action_type, summary, detail=None):
        repository = (
            self.active_record_repository()
            if getattr(self, "api_mode", False)
            else self.repository
        )
        return repository.log_operation(action_type, summary, detail)

    def _start_background_task(self, target):
        """Run plain Python work (network calls only, never Qt objects) off the GUI thread."""

        thread = threading.Thread(target=target, daemon=True)
        tasks = [task for task in getattr(self, "_background_tasks", []) if task.is_alive()]
        tasks.append(thread)
        self._background_tasks = tasks
        thread.start()
        return thread

    def wait_for_background_tasks(self, timeout=10.0):
        for task in list(getattr(self, "_background_tasks", [])):
            task.join(timeout)

    def _log_operation_in_background(self, action_type, summary, detail=None):
        """`_log_operation`, but against the home server the round trip no longer
        holds up the window (a lost operation-log line must never break the UI)."""

        if not getattr(self, "api_mode", False):
            return self._log_operation(action_type, summary, detail)
        repository = self.active_record_repository()

        def write_log():
            try:
                repository.log_operation(action_type, summary, detail)
            except Exception as exc:  # noqa: BLE001 - see docstring
                logger.warning("背景寫入操作紀錄失敗：%s", exc)

        return self._start_background_task(write_log)

    def _start_saved_record_reconcile(self):
        """After a save, fetch the saved record(s) whose server-side ids may have
        changed (moved to another parcel/owner) and refresh the tree only if the
        server's version differs from what was merged locally."""

        repository = self.active_record_repository()
        pop_ids = getattr(repository, "pop_reconcile_ids", None)
        if pop_ids is None:
            return
        record_ids = pop_ids()
        if not record_ids:
            return
        outcome = {"changed": False}

        def reconcile():
            for record_id in record_ids:
                try:
                    if repository.reconcile_record(record_id):
                        outcome["changed"] = True
                except Exception:  # noqa: BLE001 - fall back to a reload on the next refresh
                    repository.invalidate_cache()
                    return

        self._saved_record_reconcile = (self._start_background_task(reconcile), outcome)
        QTimer.singleShot(150, self._poll_saved_record_reconcile)

    def _poll_saved_record_reconcile(self):
        pending = getattr(self, "_saved_record_reconcile", None)
        if pending is None:
            return
        thread, outcome = pending
        try:
            if thread.is_alive():
                QTimer.singleShot(150, self._poll_saved_record_reconcile)
                return
            self._saved_record_reconcile = None
            if outcome["changed"]:
                self.refresh_records(
                    self.selected_record_id, preserve_existing_model=True
                )
        except RuntimeError:  # the window was closed while the fetch was running
            self._saved_record_reconcile = None

    def _show_non_modal_dialog(self, dialog, on_accepted=None, on_finished=None):
        """Open an editing dialog non-modally instead of blocking on .exec().

        Explicit user request, phase 2: every dialog in the app -- not
        just the view-only ones from phase 1 -- should be usable
        alongside other windows instead of blocking everything else while
        open. Most of these dialogs collect input and, on acceptance,
        save it -- code that used to run synchronously right after a
        blocking `dialog.exec()` call:

            if dialog.exec() != QDialog.Accepted:
                return
            values = dialog.values()
            self.repository.save_xyz(values)

        `.show()` does not block, so that save code cannot simply stay
        where it was -- it would run immediately, before the user has
        touched the dialog at all. It has to move into a callback that
        only fires once the dialog is actually closed, which is what
        `on_accepted` is for: pass the same "process the result and save"
        logic as a closure, and this method fires it exactly when the old
        code after `.exec()` used to run, but from `dialog.finished`
        instead.

        Unlike `_show_non_modal_report_dialog()` (a per-type *singleton*
        for view-only report windows, where reopening the same window
        type should refocus the existing one), every editing dialog here
        is opened for a specific record or selection each time -- reusing
        an old instance for a new context would show stale or outright
        wrong data in it. So each call creates and tracks its own
        instance; several of the same dialog TYPE can be open at once
        (e.g. two ContactLogDialogs for two different records), each keyed
        by object identity in `self._open_edit_dialogs`, not by type.

        Concurrency policy (explicitly confirmed with the user): last
        save wins. No locking, no "this record is already open elsewhere"
        warning -- if two open dialogs both save the same underlying
        record, whichever one's save call lands last is what persists.
        Simple, and matches how the same two dialogs already behaved
        today if opened one after the other.

        A few call sites had code that ran after `.exec()` unconditionally
        -- logging, a status refresh -- regardless of whether the user
        accepted or rejected the dialog (no `!= QDialog.Accepted` check at
        all). `on_finished` covers that: it always fires once the dialog
        closes, Accepted or not, exactly matching that old timing.
        """
        if not hasattr(self, "_open_edit_dialogs"):
            self._open_edit_dialogs = []
        self._open_edit_dialogs.append(dialog)

        def handle_finished(_result=None):
            if dialog in self._open_edit_dialogs:
                self._open_edit_dialogs.remove(dialog)
            if on_accepted is not None and dialog.result() == QDialog.Accepted:
                on_accepted()
            if on_finished is not None:
                on_finished()

        dialog.finished.connect(handle_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog
