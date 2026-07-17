"""Follow-up reminder routes."""

from typing import Annotated
from fastapi import Depends, HTTPException, Query
from customer_api.auth import ApiSession
from customer_api.schemas import FollowUpUpdate
from customer_api.types import AuthenticatedUser


def register_followup_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/records/{record_id}/follow-up")
    def get_follow_up(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        if source.get_record(session.user, record_id) is None:
            raise HTTPException(status_code=404, detail="找不到資料。")
        return {"item": source.get_follow_up(session.user, record_id)}

    @app.put("/api/v1/records/{record_id}/follow-up", status_code=204)
    def update_follow_up(
        record_id: int,
        payload: FollowUpUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.save_follow_up(user, record_id, payload.model_dump(mode="json"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.delete("/api/v1/records/{record_id}/follow-up", status_code=204)
    def delete_follow_up(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.delete_follow_up(user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return None

    @app.get("/api/v1/follow-ups")
    def follow_ups(
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=500, ge=1),
    ):
        return {
            "items": source.list_follow_ups(
                session.user, limit=min(limit, settings.max_page_size)
            )
        }
