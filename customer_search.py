"""Background worker used for expensive customer searches and sorts."""

import threading
from datetime import date

from customer_domain import (
    calculate_ping,
    format_number_text,
    format_ping_text,
    mask_identity_text,
    normalize_match_text,
    normalize_search_text,
    parse_number,
    split_search_terms,
)
from customer_repository import normalize_watch_name
from customer_security import decrypt_value
from PySide6.QtCore import QObject, QThread, Signal, Slot


class CustomerDecryptionCache:
    """Login-session cache keyed by record id and encrypted field values."""

    SENSITIVE_FIELDS = ("owner_name", "external_id", "address", "note", "visit_log")

    def __init__(self):
        self.revision = None
        self.entries = {}
        self.lock = threading.RLock()

    def sync_revision(self, revision):
        with self.lock:
            if self.revision == revision:
                return
            self.entries.clear()
            self.revision = revision

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.revision = None

    def decrypt_fields(self, row, fernet):
        record_id = row["id"]
        fingerprint = tuple(row[key] or "" for key in self.SENSITIVE_FIELDS)
        with self.lock:
            cached = self.entries.get(record_id)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]

        decrypted = {
            key: decrypt_value(fernet, row[key] or "")
            for key in self.SENSITIVE_FIELDS
        }
        with self.lock:
            self.entries[record_id] = (fingerprint, decrypted)
        return decrypted


class CustomerRecordProcessor:
    """Build, filter, and sort table records without touching Qt widgets."""

    def __init__(
        self,
        *,
        fernet,
        table_columns,
        checked_ids=(),
        watchlist_names=(),
        show_full_external_id=False,
        checked_color=None,
        watchlist_color=None,
        overdue_color=None,
        note_color=None,
        keyword="",
        filter_field="all",
        sort_field="rowid",
        reverse=True,
        advanced_criteria=None,
        show_checked_only=False,
        decryption_cache=None,
    ):
        self.fernet = fernet
        self.table_columns = tuple(table_columns)
        self.checked_ids = frozenset(checked_ids)
        self.watchlist_names = frozenset(watchlist_names)
        self.show_full_external_id = show_full_external_id
        self.checked_color = checked_color
        self.watchlist_color = watchlist_color
        self.overdue_color = overdue_color
        self.note_color = note_color
        self.keyword = str(keyword or "").casefold()
        self.filter_field = filter_field or "all"
        self.sort_field = sort_field or "rowid"
        self.reverse = bool(reverse)
        self.advanced_criteria = dict(advanced_criteria or {})
        self.show_checked_only = bool(show_checked_only)
        self.decryption_cache = decryption_cache

    def highlighted_fields(self, raw):
        if not self.keyword:
            return set()
        if self.filter_field != "all":
            return (
                {self.filter_field}
                if self.keyword in normalize_match_text(raw.get(self.filter_field, ""))
                else set()
            )
        return {
            key
            for key, _label in self.table_columns[1:]
            if self.keyword in normalize_match_text(raw.get(key, ""))
        }

    @staticmethod
    def row_value(row, key, default=""):
        if isinstance(row, dict):
            return row.get(key, default)
        try:
            return row[key] if key in row.keys() else default
        except (AttributeError, KeyError, TypeError):
            return default

    def build_record(self, row, include_search_text=None):
        include_search_text = bool(self.keyword) if include_search_text is None else include_search_text
        record_id = row["id"]
        if self.decryption_cache is None:
            sensitive = {
                key: decrypt_value(self.fernet, row[key] or "")
                for key in CustomerDecryptionCache.SENSITIVE_FIELDS
            }
        else:
            sensitive = self.decryption_cache.decrypt_fields(row, self.fernet)
        owner_name = sensitive["owner_name"]
        external_id = sensitive["external_id"]
        address = sensitive["address"]
        note = sensitive["note"]
        visit_log = sensitive["visit_log"]
        is_checked = record_id in self.checked_ids
        is_watchlist = normalize_watch_name(owner_name) in self.watchlist_names
        has_note = bool(str(note or "").strip())
        calculated_ping = calculate_ping(
            {
                "area": row["area"],
                "numerator": row["numerator"],
                "denominator": row["denominator"],
            }
        )
        next_follow_up = str(self.row_value(row, "next_follow_up") or "")
        follow_up_status = str(self.row_value(row, "follow_up_status") or "")
        is_overdue = (
            bool(next_follow_up)
            and follow_up_status != "完成"
            and next_follow_up < date.today().isoformat()
        )

        background = None
        if is_checked:
            background = self.checked_color
        elif is_watchlist:
            background = self.watchlist_color
        elif is_overdue:
            background = self.overdue_color
        elif has_note:
            background = self.note_color

        raw = {
            "rowid": str(record_id),
            "district": row["district"] or "",
            "section": row["section"] or "",
            "registration_order": row["registration_order"] or "",
            "land_number": row["land_number"] or "",
            "area": row["area"] or "",
            "declared_value": row["declared_value"] or "",
            "numerator": row["numerator"] or "",
            "denominator": row["denominator"] or "",
            "ping": calculated_ping or format_ping_text(row["ping"] or ""),
            "total_declared_value": row["total_declared_value"] or "",
            "owner_name": owner_name,
            "external_id": external_id,
            "address": address,
            "registration_reason": row["registration_reason"] or "",
            "note": note,
            "visit_log": visit_log,
            "case_names": self.row_value(row, "case_names") or "",
            "tag_names": self.row_value(row, "tag_names") or "",
            "attachment_count": str(self.row_value(row, "attachment_count", 0) or 0),
            "attachment_names": self.row_value(row, "attachment_names") or "",
            "custom_values": self.row_value(row, "custom_values") or "",
            "last_contact": self.row_value(row, "last_contact") or "",
            "next_follow_up": next_follow_up,
            "follow_up_status": follow_up_status,
        }
        display = {
            **raw,
            "checked": "",
            "declared_value": format_number_text(row["declared_value"] or ""),
            "total_declared_value": format_number_text(row["total_declared_value"] or ""),
            "external_id": (
                external_id if self.show_full_external_id else mask_identity_text(external_id)
            ),
        }
        return {
            "id": record_id,
            "checked": is_checked,
            "is_watchlist": is_watchlist,
            "has_note": has_note,
            "is_overdue": is_overdue,
            "tag_color": self.row_value(row, "primary_tag_color") or "",
            "background": background,
            "highlighted_fields": self.highlighted_fields(raw),
            "raw": raw,
            "display": display,
            "filter_values": raw,
            "search_text": (
                " ".join(
                    str(raw.get(key, ""))
                    for key, _label in self.table_columns[1:]
                    if raw.get(key)
                ).casefold()
                if include_search_text
                else ""
            ),
        }

    def sort_key(self, record):
        value = record["display"].get(self.sort_field, "")
        if self.sort_field == "rowid":
            return record["id"]
        if self.sort_field in {
            "area",
            "declared_value",
            "numerator",
            "denominator",
            "ping",
            "total_declared_value",
            "attachment_count",
        }:
            number = parse_number(value)
            return float("-inf") if number is None else number
        return str(value or "").casefold()

    def matches(self, record):
        if self.keyword:
            if self.filter_field == "all":
                if self.keyword not in record["search_text"]:
                    return False
            else:
                value = str(record["filter_values"].get(self.filter_field, "") or "").casefold()
                if self.keyword not in value:
                    return False
        filter_values = record.get("filter_values", {})
        for key, expected in self.advanced_criteria.items():
            expected_terms = split_search_terms(expected)
            if not expected_terms:
                continue
            actual = normalize_search_text(filter_values.get(key, ""))
            if not any(term in actual for term in expected_terms):
                return False
        return True

    def process(self, database_rows, is_cancelled=lambda: False):
        rows = []
        for row in database_rows:
            if is_cancelled():
                return None
            if self.show_checked_only and row["id"] not in self.checked_ids:
                continue
            record = self.build_record(row)
            if self.matches(record):
                rows.append(record)
        if is_cancelled():
            return None
        rows.sort(key=self.sort_key, reverse=self.reverse)
        return rows


class CustomerSearchWorker(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(self, request_id, row_loader, row_processor):
        super().__init__()
        self.request_id = request_id
        self.row_loader = row_loader
        self.row_processor = row_processor

    @Slot()
    def run(self):
        try:
            thread = QThread.currentThread()
            is_cancelled = thread.isInterruptionRequested
            database_rows = self.row_loader()
            if is_cancelled():
                self.cancelled.emit(self.request_id)
                return
            rows = self.row_processor(database_rows, is_cancelled)
            if rows is None or is_cancelled():
                self.cancelled.emit(self.request_id)
                return
            self.finished.emit(self.request_id, rows)
        except Exception as exc:
            self.failed.emit(self.request_id, str(exc))
