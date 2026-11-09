"""Customer-record and transactional import routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query

from customer_api.auth import ApiSession
from customer_api.postgres_owner_match import OwnerAttachError
from customer_api.schemas import (
    RecordImportBatch,
    RecordUpdateWithHistory,
    RecordWrite,
)
from customer_api.types import AuthenticatedUser


def register_record_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/records")
    def records(
        session: Annotated[ApiSession, Depends(current_session)],
        q: str = Query(default="", max_length=200),
        district: str = Query(default="", max_length=100),
        section: str = Query(default="", max_length=100),
        subsection: str = Query(default="", max_length=100),
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
                "subsection": subsection,
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

    @app.get("/api/v1/owner-candidates")
    def owner_candidates(
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
        owner_name: str = Query(default="", max_length=200),
        external_id: str = Query(default="", max_length=100),
        address: str = Query(default="", max_length=1000),
        phone: str = Query(default="", max_length=60),
        rejected_record_id: Annotated[list[int] | None, Query()] = None,
        limit: int = Query(default=10, ge=1, le=30),
    ):
        """Existing owners a hand-typed new record probably belongs to.

        Identity numbers and phones are masked in the answer; matching runs
        here on the decrypted values.  SQLite (單機) sources answer
        ``supported: false`` and the desktop then simply saves as before.
        """

        finder = getattr(source, "owner_candidates", None)
        if not callable(finder):
            return {"supported": False, "items": [], "exact_owner_id": None}
        result = finder(
            user,
            {
                "owner_name": owner_name,
                "external_id": external_id,
                "address": address,
                "phone": phone,
            },
            limit=limit,
            rejected_record_ids=rejected_record_id or (),
        )
        return {"supported": True, **result}

    @app.post("/api/v1/records", status_code=201)
    def create_record(
        payload: RecordWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        values = payload.normalized_values()
        if values.get("owner_id") is not None and not callable(
            getattr(source, "owner_candidates", None)
        ):
            raise HTTPException(
                status_code=409,
                detail="這個資料來源不支援指定既有地主。",
            )
        try:
            record_id = source.save_record(user, values)
        except OwnerAttachError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            if values.get("owner_id") is None:
                raise
            raise HTTPException(
                status_code=404, detail="找不到選擇的既有地主，請重新查詢。"
            ) from exc
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

    @app.put("/api/v1/records/{record_id}/with-history")
    def replace_record_with_history(
        record_id: int,
        payload: RecordUpdateWithHistory,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if any(item.record_id != record_id for item in payload.change_logs):
            raise HTTPException(
                status_code=409,
                detail="修改紀錄的資料 ID 與更新目標不一致。",
            )
        try:
            saved_id = source.save_record_with_change_logs(
                user,
                payload.values.normalized_values(),
                record_id,
                [item.model_dump() for item in payload.change_logs],
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
        options = (
            {} if payload.urban_plan_id is None else {"urban_plan_id": payload.urban_plan_id}
        )
        try:
            return source.import_records(user, items, payload.source_file_name, **options)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="匯入要更新的資料不存在。"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
