"""Contact-log routes."""

from datetime import date as date_cls
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Query
from customer_api.auth import ApiSession
from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    field_visit_request_hash,
)
from customer_api.schemas import ContactLogCreate
from customer_api.types import AuthenticatedUser


OptionalIdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]


def register_contact_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/records/{record_id}/contact-logs")
    def contact_logs(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        if source.get_record(session.user, record_id) is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return {"items": source.list_contact_logs(session.user, record_id)}

    @app.post("/api/v1/records/{record_id}/contact-logs", status_code=201)
    def create_contact_log(
        record_id: int,
        payload: ContactLogCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
        idempotency_key: OptionalIdempotencyKey = None,
    ):
        values = payload.model_dump(mode="json")
        try:
            request_hash = field_visit_request_hash(
                "create_contact_log",
                {"record_id": int(record_id), "values": values},
            )
            log_id = source.add_contact_log(
                user,
                record_id,
                values,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if values.get("next_follow_up"):
                source.save_follow_up(
                    user,
                    record_id,
                    {
                        "due_date": values["next_follow_up"],
                        "status": "未處理",
                        "note": values.get("note"),
                    },
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403, detail="不能將紀錄加入其他使用者的外勤行程。"
            ) from exc
        except FieldVisitIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail="這筆聯絡紀錄已用相同識別碼送出，請重新整理後再試。",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": log_id}

    @app.delete(
        "/api/v1/records/{record_id}/contact-logs/{log_id}", status_code=204
    )
    def delete_contact_log(
        record_id: int,
        log_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            deleted = source.delete_contact_log(user, record_id, log_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到聯絡紀錄。")
        return None

    @app.get("/api/v1/contact-logs")
    def contact_logs_by_date(
        session: Annotated[ApiSession, Depends(current_session)],
        date: str = Query(..., min_length=10, max_length=10),
        mine_only: bool = Query(default=False),
    ):
        try:
            date_cls.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="日期格式錯誤，請使用 YYYY-MM-DD。"
            ) from exc
        return {
            "items": source.list_contact_logs_by_date(
                session.user, date, mine_only=mine_only
            )
        }
