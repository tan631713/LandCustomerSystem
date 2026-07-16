"""External and managed attachment routes."""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from customer_api.auth import ApiSession
from customer_api.schemas import ExternalAttachmentCreate
from customer_api.types import AuthenticatedUser


def register_attachment_routes(app, *, settings, source, current_session, editor_user):
    @app.get("/api/v1/records/{record_id}/attachments")
    def record_attachments(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            items = source.list_attachments(session.user, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        return {"items": items}

    @app.post("/api/v1/records/{record_id}/attachments", status_code=201)
    def create_external_attachment(
        record_id: int,
        payload: ExternalAttachmentCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            attachment_id = source.add_external_attachment(
                user, record_id, payload.file_path, payload.description
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": attachment_id}

    @app.post(
        "/api/v1/records/{record_id}/attachments/upload", status_code=201
    )
    async def upload_managed_attachment(
        record_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
        file: UploadFile = File(...),
        description: str = Form(default="", max_length=1000),
    ):
        safe_name = Path(str(file.filename or "attachment")).name or "attachment"
        suffix = Path(safe_name).suffix[:20]
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temporary_path = Path(handle.name)
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_attachment_size_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "附件超過大小限制："
                                f"{settings.max_attachment_size_bytes // (1024 * 1024)} MB。"
                            ),
                        )
                    handle.write(chunk)
            try:
                attachment_id = source.import_managed_attachment(
                    user,
                    record_id,
                    temporary_path,
                    safe_name,
                    description,
                    file.content_type or "",
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="找不到資料。") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"id": attachment_id}
        finally:
            await file.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get(
        "/api/v1/records/{record_id}/attachments/{attachment_id}/content"
    )
    def attachment_content(
        record_id: int,
        attachment_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            attachment = source.get_attachment(
                session.user, record_id, attachment_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if attachment is None:
            raise HTTPException(status_code=404, detail="找不到附件。")
        candidate = Path(str(attachment.get("storage_path") or "")).resolve()
        root = settings.attachment_directory.resolve()
        if (
            str(attachment.get("status") or "") == "external"
            or not candidate.is_relative_to(root)
        ):
            raise HTTPException(
                status_code=409, detail="外部連結附件只能在原電腦開啟。"
            )
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="附件檔案已遺失。")
        return FileResponse(
            candidate,
            media_type=attachment.get("media_type") or "application/octet-stream",
            filename=Path(str(attachment.get("original_name") or candidate.name)).name,
        )

    @app.delete(
        "/api/v1/records/{record_id}/attachments/{attachment_id}",
        status_code=204,
    )
    def delete_attachment(
        record_id: int,
        attachment_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            deleted = source.delete_attachment(user, record_id, attachment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到附件。")
        return None
