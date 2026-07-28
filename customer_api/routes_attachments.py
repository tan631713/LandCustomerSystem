"""External and managed attachment routes."""

import hashlib
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError

from customer_api.auth import ApiSession
from customer_api.field_visit_permissions import FieldVisitPermissionDenied
from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    field_visit_request_hash,
)
from customer_api.schemas import AttachmentMetadataUpdate, ExternalAttachmentCreate
from customer_api.types import AuthenticatedUser


OptionalIdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]


def register_attachment_routes(app, *, settings, source, current_session, editor_user):
    def managed_attachment(user, record_id, attachment_id):
        try:
            attachment = source.get_attachment(user, record_id, attachment_id)
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
        return attachment, candidate

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
        idempotency_key: OptionalIdempotencyKey = None,
    ):
        try:
            request_hash = field_visit_request_hash(
                "create_external_attachment",
                {"record_id": int(record_id), "values": payload.model_dump(mode="json")},
            )
            attachment_id = source.add_external_attachment(
                user,
                record_id,
                payload.file_path,
                payload.description,
                payload.category,
                payload.field_visit_route_item_id,
                idempotency_key,
                request_hash,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="不能將附件加入其他使用者的外勤行程。",
            ) from exc
        except FieldVisitIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail="這個附件識別碼已用於不同內容，請重新選取後再試。",
            ) from exc
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
        category: str = Form(default="", max_length=50),
        field_visit_route_item_id: int | None = Form(default=None, ge=1),
        idempotency_key: OptionalIdempotencyKey = None,
    ):
        safe_name = Path(str(file.filename or "attachment")).name or "attachment"
        suffix = Path(safe_name).suffix[:20]
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temporary_path = Path(handle.name)
                size = 0
                content_digest = hashlib.sha256()
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
                    content_digest.update(chunk)
            try:
                request_hash = field_visit_request_hash(
                    "upload_managed_attachment",
                    {
                        "record_id": int(record_id),
                        "original_name": safe_name,
                        "description": description,
                        "category": category,
                        "field_visit_route_item_id": field_visit_route_item_id,
                        "size_bytes": size,
                        "sha256": content_digest.hexdigest(),
                    },
                )
                attachment_id = source.import_managed_attachment(
                    user,
                    record_id,
                    temporary_path,
                    safe_name,
                    description,
                    file.content_type or "",
                    category,
                    field_visit_route_item_id,
                    idempotency_key,
                    request_hash,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="找不到資料。") from exc
            except PermissionError as exc:
                raise HTTPException(
                    status_code=403,
                    detail="不能將附件加入其他使用者的外勤行程。",
                ) from exc
            except FieldVisitIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail="這個附件識別碼已用於不同內容，請重新選取後再試。",
                ) from exc
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
        attachment, candidate = managed_attachment(
            session.user, record_id, attachment_id
        )
        return FileResponse(
            candidate,
            media_type=attachment.get("media_type") or "application/octet-stream",
            filename=Path(str(attachment.get("original_name") or candidate.name)).name,
        )

    @app.get(
        "/api/v1/records/{record_id}/attachments/{attachment_id}/thumbnail"
    )
    def attachment_thumbnail(
        record_id: int,
        attachment_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        attachment, candidate = managed_attachment(
            session.user, record_id, attachment_id
        )
        media_type = str(attachment.get("media_type") or "").casefold()
        if not media_type.startswith("image/") and candidate.suffix.casefold() not in {
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"
        }:
            raise HTTPException(status_code=415, detail="這個附件不是可預覽的照片。")
        try:
            with Image.open(candidate) as source_image:
                image = ImageOps.exif_transpose(source_image)
                image.thumbnail((640, 640), Image.Resampling.LANCZOS)
                if image.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                elif image.mode != "RGB":
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="JPEG", quality=82, optimize=True)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(
                status_code=415, detail="伺服器無法產生這張照片的縮圖。"
            ) from exc
        return Response(
            content=output.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=300"},
        )

    @app.patch(
        "/api/v1/records/{record_id}/attachments/{attachment_id}"
    )
    def update_attachment_metadata(
        record_id: int,
        attachment_id: int,
        payload: AttachmentMetadataUpdate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            updated = source.update_attachment_metadata(
                user,
                record_id,
                attachment_id,
                payload.description,
                payload.category,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="找不到資料。") from exc
        if not updated:
            raise HTTPException(status_code=404, detail="找不到附件。")
        return {"updated": True}

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
        except (FieldVisitPermissionDenied, PermissionError) as exc:
            raise HTTPException(
                status_code=403,
                detail="只有附件上傳者或管理員可以刪除這個附件。",
            ) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到附件。")
        return None
