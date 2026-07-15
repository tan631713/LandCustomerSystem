"""Visible crash reporting for the windowed desktop application."""

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


ERROR_LOG_DIRECTORY = "logs"
ERROR_LOG_FILENAME = "application-error.log"
MAX_ERROR_LOG_BYTES = 2 * 1024 * 1024


def get_error_log_path(app_directory):
    return Path(app_directory) / ERROR_LOG_DIRECTORY / ERROR_LOG_FILENAME


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
    if getattr(sys.excepthook, "_customer_system_handler", False):
        return sys.excepthook
    handler = build_exception_handler(app_directory, sys.excepthook)
    handler._customer_system_handler = True
    sys.excepthook = handler
    return handler
