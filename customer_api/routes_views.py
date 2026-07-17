"""Owner and land read-model routes."""

from typing import Annotated

from fastapi import Depends, Query

from customer_api.aggregates import aggregate_lands, aggregate_owners
from customer_api.auth import ApiSession


def register_view_routes(app, *, settings, source, current_session):
    @app.get("/api/v1/owners")
    def owners(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        records_result = source.list_records(
            session.user, query=q, offset=0, limit=100_000
        )
        items = aggregate_owners(records_result["items"])
        limit = min(limit, settings.max_page_size)
        return {"total": len(items), "items": items[offset : offset + limit]}

    @app.get("/api/v1/lands")
    def lands(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        district: str = Query(default="", max_length=100),
        section: str = Query(default="", max_length=100),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        records_result = source.list_records(
            session.user,
            query=q,
            filters={"district": district, "section": section},
            offset=0,
            limit=100_000,
        )
        items = aggregate_lands(records_result["items"])
        limit = min(limit, settings.max_page_size)
        return {"total": len(items), "items": items[offset : offset + limit]}
