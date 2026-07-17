"""Stable data-source facade for the customer API."""

from customer_api.config import ApiSettings
from customer_api.data_source_base import (
    CustomerDataSource,
    RECORD_SEARCH_FIELDS,
    _decrypt_record,
    _encrypted_record,
    _filter_records,
    _json_value,
    _row_dict,
)
from customer_api.postgres_source import PostgreSQLCustomerDataSource
from customer_api.sqlite_source import SQLiteCustomerDataSource


def create_data_source(settings: ApiSettings) -> CustomerDataSource:
    if settings.backend == "postgresql":
        return PostgreSQLCustomerDataSource(settings)
    return SQLiteCustomerDataSource(settings)


__all__ = [
    "CustomerDataSource",
    "PostgreSQLCustomerDataSource",
    "RECORD_SEARCH_FIELDS",
    "SQLiteCustomerDataSource",
    "create_data_source",
]
