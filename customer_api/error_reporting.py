"""Safe server-side reporting for otherwise opaque API 500 responses."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse


SERVER_ERROR_LOG_NAME = "server-error.log"


def default_server_error_log_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "LandCustomerSystem" / "logs" / SERVER_ERROR_LOG_NAME


def _database_diagnostic(exc) -> dict[str, str]:
    diagnostic = getattr(exc, "diag", None)
    return {
        "sqlstate": str(getattr(exc, "sqlstate", "") or ""),
        "constraint": str(getattr(diagnostic, "constraint_name", "") or ""),
        "table": str(getattr(diagnostic, "table_name", "") or ""),
        "column": str(getattr(diagnostic, "column_name", "") or ""),
    }


def _public_error_detail(exc, reference: str) -> tuple[int, str]:
    diagnostic = _database_diagnostic(exc)
    sqlstate = diagnostic["sqlstate"]
    constraint = diagnostic["constraint"]
    suffix = f"錯誤代碼：{reference}"
    if constraint == "lands_district_section_land_number_key":
        return 409, f"同一地區、地段與地號已存在，請重新整理後再選取資料。{suffix}"
    if sqlstate == "23505":
        return 409, f"儲存內容與現有資料重複，請確認後再試。{suffix}"
    if sqlstate == "23503":
        return 409, f"關聯資料已被變更，請重新整理後再試。{suffix}"
    if sqlstate and sqlstate.startswith("22"):
        return 400, f"欄位內容無法寫入資料庫，請檢查格式。{suffix}"
    return 500, f"伺服器儲存資料時發生錯誤。{suffix}"


def _server_error_logger(log_path: Path) -> logging.Logger:
    resolved = log_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"land_customer.server.{resolved}")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            resolved,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


def install_server_error_reporting(app, log_path: Path | str | None = None) -> Path:
    """Log unhandled exceptions locally and return a safe client reference."""

    destination = Path(log_path or default_server_error_log_path()).resolve()
    logger = _server_error_logger(destination)

    async def handle_unexpected_error(request: Request, exc: Exception):
        reference = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3).upper()
        diagnostic = _database_diagnostic(exc)
        logger.error(
            "reference=%s method=%s path=%s exception=%s sqlstate=%s constraint=%s table=%s column=%s",
            reference,
            request.method,
            request.url.path,
            exc.__class__.__name__,
            diagnostic["sqlstate"],
            diagnostic["constraint"],
            diagnostic["table"],
            diagnostic["column"],
            exc_info=(exc.__class__, exc, exc.__traceback__),
        )
        status_code, detail = _public_error_detail(exc, reference)
        return JSONResponse(status_code=status_code, content={"detail": detail})

    app.add_exception_handler(Exception, handle_unexpected_error)
    app.state.server_error_log_path = destination
    app.state.server_error_logger = logger
    return destination
