"""Visible crash reporting for the windowed desktop application."""

import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


ERROR_LOG_DIRECTORY = "logs"
ERROR_LOG_FILENAME = "application-error.log"
MAX_ERROR_LOG_BYTES = 2 * 1024 * 1024
NATIVE_CRASH_LOG_FILENAME = "native-crash-trace.log"
MAX_NATIVE_CRASH_LOG_BYTES = 2 * 1024 * 1024

# Kept alive for the whole process lifetime -- see install_native_crash_tracer().
_active_native_crash_log_file = None

# Set once by install_exception_handler()/install_native_crash_tracer() at
# startup so log_diagnostic_event() (see below) can find the log directory
# without every caller having to thread app_directory through to it.
_active_app_directory = None


def get_error_log_path(app_directory):
    return Path(app_directory) / ERROR_LOG_DIRECTORY / ERROR_LOG_FILENAME


def get_native_crash_log_path(app_directory):
    return Path(app_directory) / ERROR_LOG_DIRECTORY / NATIVE_CRASH_LOG_FILENAME


def install_native_crash_tracer(app_directory):
    """Enable faulthandler so a native crash leaves a real Python call stack.

    Context: production has hit repeated native crashes -- Windows
    "Application Error" events, exception code 0xc0000005 (access
    violation), inside python314.dll and, once, Qt6Core.dll -- that
    Python's normal exception handling (sys.excepthook, see
    install_exception_handler() above) never sees, because the process is
    gone by the time anything could log it. All we've had to go on so far
    is which DLL and what byte offset faulted, which has not been enough
    to pin down the actual cause after several fix attempts targeting
    different hypotheses.

    faulthandler is the standard library's own answer to exactly this: it
    installs a handler for SIGSEGV and the Windows-equivalent access
    violation that, right before the process dies, dumps the Python-level
    call stack of every thread to a file. That turns "python314.dll,
    offset 0x20169" into an actual Python traceback pointing at the line
    that was executing -- or, if the fault is genuinely deep inside Qt/C++
    with no Python frame involved at that instant, at least tells us that
    for certain instead of leaving it to guesswork.

    The returned file object is also stashed on this module so a caller
    forgetting to hold a reference can't let it get garbage collected --
    faulthandler writes to the file's underlying descriptor from a
    restricted signal-handler context, so the file must stay open (and
    unclosed) for the rest of the process's life.
    """
    global _active_native_crash_log_file, _active_app_directory
    app_directory = Path(app_directory)
    _active_app_directory = app_directory
    log_path = get_native_crash_log_path(app_directory)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size >= MAX_NATIVE_CRASH_LOG_BYTES:
        rotated_path = log_path.with_name(f"{log_path.stem}.previous{log_path.suffix}")
        try:
            os.replace(log_path, rotated_path)
        except OSError:
            pass
    log_file = log_path.open("a", encoding="utf-8")
    log_file.write(
        f"[{datetime.now().isoformat(timespec='seconds')}] faulthandler enabled for this run\n"
    )
    log_file.flush()
    faulthandler.enable(file=log_file, all_threads=True)
    _active_native_crash_log_file = log_file
    return log_file


def write_exception_log(app_directory, exception_type, exception_value, exception_traceback):
    log_path = get_error_log_path(app_directory)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size >= MAX_ERROR_LOG_BYTES:
        rotated_path = log_path.with_name(f"{log_path.stem}.previous{log_path.suffix}")
        os.replace(log_path, rotated_path)
    formatted = "".join(
        traceback.format_exception(exception_type, exception_value, exception_traceback)
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{datetime.now().isoformat(timespec='seconds')}]\n")
        log_file.write(formatted)
        log_file.write("\n")
    return log_path


def _show_exception_message(exception_value, log_path):
    from PySide6.QtWidgets import QApplication, QMessageBox

    application = QApplication.instance()
    if application is None:
        return False
    message = (
        "系統執行功能時發生未預期錯誤。\n\n"
        "錯誤已記錄，資料庫不會因這個提示被自動修改。\n\n"
        f"技術訊息：{exception_value}\n\n"
        f"錯誤記錄：{log_path}"
    )
    QMessageBox.critical(application.activeWindow(), "系統錯誤", message)
    return True


def build_exception_handler(app_directory, fallback_handler=None):
    app_directory = Path(app_directory)
    fallback_handler = fallback_handler or sys.__excepthook__
    state = {"handling": False}

    def handle_exception(exception_type, exception_value, exception_traceback):
        if issubclass(exception_type, KeyboardInterrupt):
            fallback_handler(exception_type, exception_value, exception_traceback)
            return
        if state["handling"]:
            fallback_handler(exception_type, exception_value, exception_traceback)
            return

        state["handling"] = True
        log_path = get_error_log_path(app_directory)
        try:
            try:
                log_path = write_exception_log(
                    app_directory,
                    exception_type,
                    exception_value,
                    exception_traceback,
                )
            except Exception:
                pass
            try:
                _show_exception_message(exception_value, log_path)
            except Exception:
                pass
            fallback_handler(exception_type, exception_value, exception_traceback)
        finally:
            state["handling"] = False

    return handle_exception


def install_exception_handler(app_directory):
    global _active_app_directory
    _active_app_directory = Path(app_directory)
    if getattr(sys.excepthook, "_customer_system_handler", False):
        return sys.excepthook
    handler = build_exception_handler(app_directory, sys.excepthook)
    handler._customer_system_handler = True
    sys.excepthook = handler
    return handler


def log_diagnostic_event(source, message):
    """Append a non-fatal note to application-error.log without crashing.

    This exists for exactly one purpose today: RecordTableModel's
    thread-affinity guard (see customer_models.py's _warn_if_wrong_thread())
    calls this if a model method is ever invoked from a non-GUI thread
    again -- the exact class of bug fixed in DESKTOP_CLIENT_VERSION 1.9.35
    (see customer_search_controller.py's start_record_search() for the
    full story: touching QAbstractItemModel off the GUI thread is
    undefined behaviour in Qt and was silently corrupting memory,
    surfacing later as an unrelated-looking native crash with no
    attributable cause).

    If this bug class is ever reintroduced -- by a future change to this
    codebase, most likely -- this turns it back into an immediate,
    attributable, *non-fatal* log entry the moment it happens, instead of
    another round of guessing from a Windows Event Viewer offset. It is
    deliberately best-effort and silent-on-failure: a broken diagnostic
    log must never itself become a new crash, and it does nothing at all
    if install_exception_handler()/install_native_crash_tracer() were
    never called (e.g. running under the test suite) -- callers should
    treat this purely as a bonus breadcrumb, not something to depend on.
    """
    if _active_app_directory is None:
        return
    try:
        log_path = get_error_log_path(_active_app_directory)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{datetime.now().isoformat(timespec='seconds')}] [{source}]\n")
            log_file.write(message)
            log_file.write("\n\n")
    except Exception:
        pass
