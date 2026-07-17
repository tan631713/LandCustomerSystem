"""Explicit data-access routing for local and remote desktop modes."""

from __future__ import annotations

from typing import Any


class DesktopDataAccess:
    """Expose the active record store while retaining device-local services."""

    def __init__(self, local_repository: Any, record_repository: Any | None = None):
        self._local_repository = local_repository
        self._record_repository = record_repository or local_repository

    @property
    def records(self) -> Any:
        """Repository used for customer records in the current desktop mode."""

        return self._record_repository

    @property
    def local(self) -> Any:
        """Repository for settings and other device-local state."""

        return self._local_repository

    @property
    def is_remote(self) -> bool:
        return self._record_repository is not self._local_repository

    def fetch_record_ids(self) -> set[int]:
        """Return IDs from the active record store, never device-local settings."""

        fetch_ids = getattr(self.records, "fetch_customer_ids", None)
        if callable(fetch_ids):
            return {int(record_id) for record_id in fetch_ids()}
        return {
            int(row["id"])
            for row in self.records.fetch_search_candidate_rows()
        }
