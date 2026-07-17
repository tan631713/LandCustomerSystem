"""Tag and tag-assignment routes."""

from typing import Annotated
from fastapi import Depends, HTTPException
from customer_api.auth import ApiSession
from customer_api.schemas import BulkRecordTagsUpdate, RecordTagsUpdate, TagWrite
from customer_api.types import AuthenticatedUser


def register_tag_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/tags")
    def tags(session: Annotated[ApiSession, Depends(current_session)]):
        return {"items": source.list_tags(session.user)}

    @app.post("/api/v1/tags", status_code=201)
    def create_tag(
        payload: TagWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            tag_id = source.save_tag(user, payload.name, payload.color)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": tag_id}

    @app.put("/api/v1/tags/assignments")
    def update_tag_assignments(
        payload: BulkRecordTagsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            processed = source.set_records_tags(
                user, payload.record_ids, payload.tag_ids, payload.mode
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="資料或標籤不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"processed": processed}

    @app.put("/api/v1/tags/{tag_id}")
    def update_tag(
        tag_id: int,
        payload: TagWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_tag(user, payload.name, payload.color, tag_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到標籤。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/tags/{tag_id}", status_code=204)
    def delete_tag(
        tag_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_tag(user, tag_id):
            raise HTTPException(status_code=404, detail="找不到標籤。")
        return None

    @app.get("/api/v1/records/{record_id}/tags")
    def record_tags(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            tag_ids = source.get_record_tag_ids(session.user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        items = [
            tag for tag in source.list_tags(session.user) if int(tag["id"]) in tag_ids
        ]
        return {"tag_ids": sorted(tag_ids), "items": items}

    @app.put("/api/v1/records/{record_id}/tags")
    def update_record_tags(
        record_id: int,
        payload: RecordTagsUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            count = source.set_record_tags(user, record_id, payload.tag_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="資料或標籤不存在。") from exc
        return {"count": count}
