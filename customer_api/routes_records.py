"""Customer-record and transactional import routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query

from customer_api.auth import ApiSession
from customer_api.schemas import RecordImportBatch, RecordWrite
from customer_api.types import AuthenticatedUser


def register_record_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/records")
    def records(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        district: str = Query(default="", max_length=100),
        section: str = Query(default="", max_length=100),
        land_number: str = Query(default="", max_length=100),
        owner_name: str = Query(default="", max_length=100),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ):
        return source.list_records(
            session.user,
            query=q,
            filters={
                "district": district,
                "section": section,
                "land_number": land_number,
                "owner_name": owner_name,
            },
            offset=offset,
            limit=min(limit, settings.max_page_size),
        )

    @app.get("/api/v1/records/{record_id}")
    def record_detail(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        record = source.get_record(session.user, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return record

    @app.post("/api/v1/records", status_code=201)
    def create_record(
        payload: RecordWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        record_id = source.save_record(user, payload.normalized_values())
        return {"id": record_id}

    @app.put("/api/v1/records/{record_id}")
    def replace_record(
        record_id: int,
        payload: RecordWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_record(
                user, payload.normalized_values(), record_id=record_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return {"id": saved_id}

    @app.delete("/api/v1/records/{record_id}", status_code=204)
    def delete_record(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.delete_record(user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.post("/api/v1/imports/records", status_code=201)
    def import_records(
        payload: RecordImportBatch,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        items = [
            {
                "record_id": item.record_id,
                "values": item.values.normalized_values(),
            }
            for item in payload.items
        ]
        try:
            return source.import_records(user, items, payload.source_file_name)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="匯入要更新的資料不存在。"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
