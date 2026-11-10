"""Routes that complete the full desktop workflow in remote PostgreSQL mode."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query

from customer_api.auth import ApiSession
from customer_api.schemas import (
    BulkCustomValuesWrite,
    CustomFieldWrite,
    CustomValuesWrite,
    DuplicateReviewWrite,
    ExcelExportMark,
    OperationLogCreate,
    RecordChangeLogBatch,
    RecordLocationWrite,
    TextTemplateWrite,
    WatchlistReplace,
)
from customer_api.types import AuthenticatedUser


def _missing_resource(exc, detail):
    raise HTTPException(status_code=404, detail=detail) from exc


def register_desktop_feature_routes(
    app, *, settings, source, current_session, editor_user
):
    del settings

    @app.get("/api/v1/records/{record_id}/change-logs")
    def record_change_logs(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=300, ge=1, le=1000),
    ):
        try:
            items = source.list_record_change_logs(session.user, record_id, limit)
        except KeyError as exc:
            _missing_resource(exc, "找不到資料。")
        return {"items": items}

    @app.post("/api/v1/record-change-logs", status_code=201)
    def create_record_change_logs(
        payload: RecordChangeLogBatch,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            count = source.add_record_change_logs(
                user, [item.model_dump() for item in payload.items]
            )
        except KeyError as exc:
            _missing_resource(exc, "部分資料不存在。")
        return {"count": count}

    @app.get("/api/v1/custom-fields")
    def custom_fields(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        return {"items": source.list_custom_fields(session.user)}

    @app.post("/api/v1/custom-fields", status_code=201)
    def create_custom_field(
        payload: CustomFieldWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            field_id = source.save_custom_field(
                user, payload.label, payload.field_key
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": field_id}

    @app.put("/api/v1/custom-fields/{field_id}")
    def update_custom_field(
        field_id: int,
        payload: CustomFieldWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_custom_field(
                user, payload.label, payload.field_key, field_id
            )
        except KeyError as exc:
            _missing_resource(exc, "找不到自訂欄位。")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": saved_id}

    @app.delete("/api/v1/custom-fields/{field_id}", status_code=204)
    def delete_custom_field(
        field_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_custom_field(user, field_id):
            raise HTTPException(status_code=404, detail="找不到自訂欄位。")
        return None

    @app.get("/api/v1/records/{record_id}/custom-values")
    def record_custom_values(
        record_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            values = source.get_record_custom_values(session.user, record_id)
        except KeyError as exc:
            _missing_resource(exc, "找不到資料。")
        return {"values": values}

    @app.put("/api/v1/records/{record_id}/custom-values")
    def update_record_custom_values(
        record_id: int,
        payload: CustomValuesWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            count = source.set_record_custom_values(
                user, record_id, payload.values
            )
        except KeyError as exc:
            _missing_resource(exc, "資料或自訂欄位不存在。")
        return {"count": count}

    @app.put("/api/v1/custom-values/assignments")
    def update_custom_value_assignments(
        payload: BulkCustomValuesWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            processed = source.set_records_custom_values(
                user, payload.record_ids, payload.values
            )
        except KeyError as exc:
            _missing_resource(exc, "部分資料或自訂欄位不存在。")
        return {"processed": processed}

    @app.get("/api/v1/text-templates")
    def text_templates(
        session: Annotated[ApiSession, Depends(current_session)],
        template_type: str | None = Query(default=None, max_length=80),
    ):
        return {
            "items": source.list_text_templates(
                session.user, template_type=template_type
            )
        }

    @app.post("/api/v1/text-templates", status_code=201)
    def create_text_template(
        payload: TextTemplateWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        template_id = source.save_text_template(
            user, payload.title, payload.content, payload.template_type
        )
        return {"id": template_id}

    @app.put("/api/v1/text-templates/{template_id}")
    def update_text_template(
        template_id: int,
        payload: TextTemplateWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.save_text_template(
                user,
                payload.title,
                payload.content,
                payload.template_type,
                template_id,
            )
        except KeyError as exc:
            _missing_resource(exc, "找不到快速範本。")
        return {"id": saved_id}

    @app.delete("/api/v1/text-templates/{template_id}", status_code=204)
    def delete_text_template(
        template_id: int,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        if not source.delete_text_template(user, template_id):
            raise HTTPException(status_code=404, detail="找不到快速範本。")
        return None

    @app.get("/api/v1/watchlist")
    def watchlist(session: Annotated[ApiSession, Depends(current_session)]):
        return {"items": source.list_watchlist(session.user)}

    @app.put("/api/v1/watchlist")
    def update_watchlist(
        payload: WatchlistReplace,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        count = source.replace_watchlist(
            user, [item.model_dump() for item in payload.items]
        )
        return {"count": count}

    @app.get("/api/v1/operation-logs")
    def operation_logs(
        session: Annotated[ApiSession, Depends(current_session)],
        limit: int = Query(default=300, ge=1, le=1000),
    ):
        return {"items": source.list_operation_logs(session.user, limit)}

    @app.post("/api/v1/operation-logs", status_code=201)
    def create_operation_log(
        payload: OperationLogCreate,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        log_id = source.add_operation_log(
            user, payload.action_type, payload.summary, payload.detail
        )
        return {"id": log_id}

    @app.get("/api/v1/record-locations")
    def record_locations(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        return {"items": source.list_record_locations(session.user)}

    @app.put("/api/v1/records/{record_id}/location")
    def update_record_location(
        record_id: int,
        payload: RecordLocationWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            saved_id = source.set_record_location(
                user,
                record_id,
                payload.latitude,
                payload.longitude,
                payload.source,
            )
        except KeyError as exc:
            _missing_resource(exc, "找不到資料。")
        return {"id": saved_id}

    @app.get("/api/v1/excel-export-status")
    def excel_export_status(
        session: Annotated[ApiSession, Depends(current_session)],
        ids: str = Query(default="", max_length=50_000),
    ):
        record_ids = [
            int(part) for part in ids.split(",") if part.strip().lstrip("-").isdigit()
        ]
        exported_ids = source.list_previously_exported_record_ids(
            session.user, record_ids
        )
        return {"exported_ids": sorted(exported_ids)}

    @app.post("/api/v1/excel-export-status", status_code=201)
    def mark_excel_export_status(
        payload: ExcelExportMark,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        source.mark_records_exported_to_excel(session.user, payload.record_ids)
        return {"status": "ok"}

    @app.get("/api/v1/duplicate-reviews")
    def duplicate_reviews(
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        pairs = source.ignored_duplicate_pairs(session.user)
        return {
            "items": [
                {"left_record_id": left_id, "right_record_id": right_id}
                for left_id, right_id in pairs
            ]
        }

    @app.post("/api/v1/duplicate-reviews", status_code=201)
    def create_duplicate_review(
        payload: DuplicateReviewWrite,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            source.ignore_duplicate_pair(
                user, payload.left_record_id, payload.right_record_id
            )
        except KeyError as exc:
            _missing_resource(exc, "部分資料不存在。")
        return {
            "left_record_id": min(
                payload.left_record_id, payload.right_record_id
            ),
            "right_record_id": max(
                payload.left_record_id, payload.right_record_id
            ),
        }

    @app.post("/api/v1/attachments/verify")
    def verify_attachments(
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return {"items": source.verify_managed_attachments(user)}
