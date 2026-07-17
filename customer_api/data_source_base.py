"""Shared protocol and record transformation helpers for API data sources."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from customer_api.types import AuthenticatedUser
from customer_domain import (
    mask_identity_text,
    normalize_match_text,
    normalize_search_text,
    split_search_terms,
)
from customer_fields import LAND_FIELDS
from customer_security import ENCRYPTED_FIELDS, decrypt_value, encrypt_record, make_fernet


RECORD_SEARCH_FIELDS = (
    "district",
    "section",
    "registration_order",
    "land_number",
    "owner_name",
    "external_id",
    "address",
    "registration_reason",
    "note",
    "visit_log",
)


class CustomerDataSource(Protocol):
    backend_name: str

    def health(self) -> dict: ...

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None: ...

    def list_records(
        self,
        user: AuthenticatedUser,
        *,
        query: str = "",
        filters: dict | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict: ...

    def get_record(self, user: AuthenticatedUser, record_id: int) -> dict | None: ...

    def save_record(
        self,
        user: AuthenticatedUser,
        values: dict,
        record_id: int | None = None,
    ) -> int: ...

    def delete_record(self, user: AuthenticatedUser, record_id: int) -> bool: ...

    def import_records(
        self,
        user: AuthenticatedUser,
        items: list[dict],
        source_file_name: str = "import.xlsx",
    ) -> dict: ...

    def list_contact_logs(self, user: AuthenticatedUser, record_id: int) -> list[dict]: ...

    def add_contact_log(self, user: AuthenticatedUser, record_id: int, values: dict) -> int: ...

    def delete_contact_log(
        self, user: AuthenticatedUser, record_id: int, log_id: int
    ) -> bool: ...

    def get_follow_up(
        self, user: AuthenticatedUser, record_id: int
    ) -> dict | None: ...

    def save_follow_up(self, user: AuthenticatedUser, record_id: int, values: dict) -> None: ...

    def delete_follow_up(self, user: AuthenticatedUser, record_id: int) -> bool: ...

    def list_follow_ups(self, user: AuthenticatedUser, limit: int = 500) -> list[dict]: ...

    def list_projects(self, user: AuthenticatedUser) -> list[dict]: ...

    def save_project(
        self,
        user: AuthenticatedUser,
        title: str,
        status: str = "進行中",
        note: str = "",
        project_id: int | None = None,
    ) -> int: ...

    def delete_project(self, user: AuthenticatedUser, project_id: int) -> bool: ...

    def add_records_to_project(
        self,
        user: AuthenticatedUser,
        project_id: int,
        record_ids: list[int],
    ) -> int: ...

    def remove_records_from_project(
        self,
        user: AuthenticatedUser,
        project_id: int,
        record_ids: list[int],
    ) -> int: ...

    def list_tags(self, user: AuthenticatedUser) -> list[dict]: ...

    def save_tag(
        self,
        user: AuthenticatedUser,
        name: str,
        color: str = "",
        tag_id: int | None = None,
    ) -> int: ...

    def delete_tag(self, user: AuthenticatedUser, tag_id: int) -> bool: ...

    def get_record_tag_ids(
        self, user: AuthenticatedUser, record_id: int
    ) -> set[int]: ...

    def set_record_tags(
        self, user: AuthenticatedUser, record_id: int, tag_ids: list[int]
    ) -> int: ...

    def set_records_tags(
        self,
        user: AuthenticatedUser,
        record_ids: list[int],
        tag_ids: list[int],
        mode: str = "add",
    ) -> int: ...

    def list_attachments(
        self, user: AuthenticatedUser, record_id: int
    ) -> list[dict]: ...

    def get_attachment(
        self, user: AuthenticatedUser, record_id: int, attachment_id: int
    ) -> dict | None: ...

    def add_external_attachment(
        self,
        user: AuthenticatedUser,
        record_id: int,
        file_path: str,
        description: str = "",
    ) -> int: ...

    def import_managed_attachment(
        self,
        user: AuthenticatedUser,
        record_id: int,
        source_path: str | Path,
        original_name: str,
        description: str = "",
        media_type: str = "",
    ) -> int: ...

    def delete_attachment(
        self, user: AuthenticatedUser, record_id: int, attachment_id: int
    ) -> bool: ...


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row):
    return {str(key): _json_value(value) for key, value in dict(row).items()}


def _decrypt_record(row, user):
    values = _row_dict(row)
    fernet = make_fernet(user.data_key)
    for field in ENCRYPTED_FIELDS:
        if field in values:
            values[field] = decrypt_value(fernet, values.get(field))
    if user.role == "viewer":
        values["external_id"] = mask_identity_text(values.get("external_id"))
    return values


def _filter_records(records, *, query="", filters=None):
    query = normalize_match_text(query)
    normalized_filters = {}
    for key, value in dict(filters or {}).items():
        terms = split_search_terms(value)
        if terms:
            normalized_filters[key] = terms
    matched = []
    for record in records:
        if query and not any(
            query in normalize_match_text(record.get(field)) for field in RECORD_SEARCH_FIELDS
        ):
            continue
        if any(
            not any(term in normalize_search_text(record.get(key)) for term in terms)
            for key, terms in normalized_filters.items()
        ):
            continue
        matched.append(record)
    return matched


def _encrypted_record(user, values):
    plain = {key: values.get(key) for key, _label in LAND_FIELDS}
    plain["name"] = plain.get("owner_name") or None
    return encrypt_record(make_fernet(user.data_key), plain)
