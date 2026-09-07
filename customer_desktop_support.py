"""Shared dependency seams for desktop workflow mixins."""

import sys

from PySide6.QtWidgets import QDialog


class DesktopSupportMixin:
    """Resolve replaceable UI components and operation logging."""

    def _app_component(self, name):
        module = sys.modules[self.__class__.__module__]
        return getattr(module, name)

    def _log_operation(self, action_type, summary, detail=None):
        repository = (
            self.active_record_repository()
            if getattr(self, "api_mode", False)
            else self.repository
        )
        return repository.log_operation(action_type, summary, detail)

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
