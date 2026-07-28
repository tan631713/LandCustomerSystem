"""Authenticated API routes for mobile field visits."""

from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query

from customer_api.auth import ApiSession
from customer_api.field_visit_permissions import FieldVisitPermissionDenied
from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    FieldVisitPlanConflict,
    FieldVisitService,
    FieldVisitTransitionError,
)
from customer_api.schemas import (
    FieldVisitItemUpdate,
    FieldVisitItemsCreate,
    FieldVisitManualOrder,
    FieldVisitOptimizeApply,
    FieldVisitOptimizePreview,
    FieldVisitRouteCreate,
    FieldVisitStatusUpdate,
)
from customer_api.types import AuthenticatedUser


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=200,
        description="Unique retry key for this write operation.",
    ),
]


def _raise_field_visit_error(exc):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail="找不到指定的外勤行程或項目。") from exc
    if isinstance(exc, (FieldVisitPermissionDenied, PermissionError)):
        raise HTTPException(status_code=403, detail="目前帳號沒有這項外勤操作權限。") from exc
    if isinstance(exc, FieldVisitIdempotencyConflict):
        raise HTTPException(
            status_code=409,
            detail="這個防重複識別碼已用於不同操作，請重新整理後再試。",
        ) from exc
    if isinstance(exc, FieldVisitTransitionError):
        raise HTTPException(status_code=409, detail="目前拜訪狀態不允許這項操作。") from exc
    if isinstance(exc, FieldVisitPlanConflict):
        raise HTTPException(
            status_code=409,
            detail="行程已被修改，請重新預覽路線後再套用。",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


def register_field_visit_routes(
    app, *, settings, source, current_session, editor_user
):
    del settings
    service = FieldVisitService(source)

    @app.get("/api/v1/field-visits/today")
    def today_field_visit(
        session: Annotated[ApiSession, Depends(current_session)],
        visit_date: date = Query(default_factory=date.today),
    ):
        try:
            return {"item": service.get_today(session.user, visit_date)}
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visits", status_code=201)
    def create_field_visit(
        payload: FieldVisitRouteCreate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.create_route(
                user,
                visit_date=payload.visit_date,
                title=payload.title,
                start_latitude=payload.start_latitude,
                start_longitude=payload.start_longitude,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.get("/api/v1/field-visits/{route_id}")
    def field_visit_detail(
        route_id: int,
        session: Annotated[ApiSession, Depends(current_session)],
    ):
        try:
            return service.get_route(session.user, route_id)
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visits/{route_id}/items", status_code=201)
    def add_field_visit_items(
        route_id: int,
        payload: FieldVisitItemsCreate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.add_items(
                user,
                route_id,
                [item.model_dump(mode="json") for item in payload.items],
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.patch("/api/v1/field-visit-items/{item_id}")
    def update_field_visit_item(
        item_id: int,
        payload: FieldVisitItemUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.update_item(
                user,
                item_id,
                priority=payload.priority,
                is_order_locked=payload.is_order_locked,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visits/{route_id}/optimize/preview")
    def preview_field_visit_optimization(
        route_id: int,
        payload: FieldVisitOptimizePreview,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.preview_optimization(
                user,
                route_id,
                current_latitude=payload.current_latitude,
                current_longitude=payload.current_longitude,
                keep_current_item_first=payload.keep_current_item_first,
                current_item_id=payload.current_item_id,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visits/{route_id}/optimize")
    def apply_field_visit_optimization(
        route_id: int,
        payload: FieldVisitOptimizeApply,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.apply_optimization(
                user,
                route_id,
                current_latitude=payload.current_latitude,
                current_longitude=payload.current_longitude,
                plan_token=payload.plan_token,
                keep_current_item_first=payload.keep_current_item_first,
                current_item_id=payload.current_item_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visits/{route_id}/reorder")
    def reorder_field_visit(
        route_id: int,
        payload: FieldVisitManualOrder,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        try:
            return service.apply_manual_order(
                user,
                route_id,
                [item.model_dump(mode="json") for item in payload.items],
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    def change_item_status(
        item_id,
        new_status,
        payload,
        idempotency_key,
        user,
        *,
        allowed_old_statuses=None,
    ):
        try:
            return service.transition_item(
                user,
                item_id,
                new_status,
                latitude=payload.latitude,
                longitude=payload.longitude,
                note=payload.note,
                postponed_until=payload.postponed_until,
                allowed_old_statuses=allowed_old_statuses,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            _raise_field_visit_error(exc)

    @app.post("/api/v1/field-visit-items/{item_id}/start")
    def start_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id, "in_progress", payload, idempotency_key, user
        )

    @app.post("/api/v1/field-visit-items/{item_id}/cancel")
    def cancel_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id,
            "cancelled",
            payload,
            idempotency_key,
            user,
            allowed_old_statuses={"planned"},
        )

    @app.post("/api/v1/field-visit-items/{item_id}/restore")
    def restore_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id,
            "planned",
            payload,
            idempotency_key,
            user,
            allowed_old_statuses={"cancelled"},
        )

    @app.post("/api/v1/field-visit-items/{item_id}/complete")
    def complete_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id, "completed", payload, idempotency_key, user
        )

    @app.post("/api/v1/field-visit-items/{item_id}/skip")
    def skip_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id, "skipped", payload, idempotency_key, user
        )

    @app.post("/api/v1/field-visit-items/{item_id}/postpone")
    def postpone_field_visit_item(
        item_id: int,
        payload: FieldVisitStatusUpdate,
        idempotency_key: IdempotencyKey,
        user: Annotated[AuthenticatedUser, Depends(editor_user)],
    ):
        return change_item_status(
            item_id, "postponed", payload, idempotency_key, user
        )
