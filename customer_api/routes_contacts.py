"""Contact-log routes."""

from typing import Annotated
from fastapi import Depends, HTTPException
from customer_api.auth import ApiSession
from customer_api.schemas import ContactLogCreate
from customer_api.types import AuthenticatedUser


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
    ):
        values = payload.model_dump(mode="json")
        try:
            log_id = source.add_contact_log(user, record_id, values)
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
