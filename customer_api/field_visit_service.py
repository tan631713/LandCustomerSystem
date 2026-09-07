"""Validation and orchestration rules for mobile field visits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Iterable

from customer_api.field_visit_permissions import (
    FIELD_VISIT_COMPLETE,
    FIELD_VISIT_CREATE,
    FIELD_VISIT_OPTIMIZE,
    FIELD_VISIT_UPDATE,
    FIELD_VISIT_VIEW,
    require_field_visit_capability,
)
from customer_api.field_visit_routing import (
    ALLOWED_STATUSES,
    RouteCandidate,
    optimize_route,
    validate_coordinate,
)


STATUS_TRANSITIONS = {
    "planned": frozenset({"in_progress", "skipped", "postponed", "cancelled"}),
    "in_progress": frozenset({"completed", "skipped", "postponed", "cancelled"}),
    "skipped": frozenset({"planned", "postponed", "cancelled"}),
    "postponed": frozenset({"planned", "in_progress", "skipped", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset({"planned"}),
}


class FieldVisitTransitionError(ValueError):
    """Raised when a visit item cannot move between two statuses."""


class FieldVisitIdempotencyConflict(ValueError):
    """Raised when one idempotency key is reused for different input."""


class FieldVisitPlanConflict(ValueError):
    """Raised when a route changed after an optimization preview."""


@dataclass(frozen=True, slots=True)
class FieldVisitItemInput:
    ownership_id: int
    priority: int = 0
    route_order: int | None = None
    is_order_locked: bool = False
    note: str = ""


def validate_status_transition(old_status: str, new_status: str) -> None:
    old_status = str(old_status or "").strip().lower()
    new_status = str(new_status or "").strip().lower()
    if old_status not in STATUS_TRANSITIONS or new_status not in ALLOWED_STATUSES:
        raise FieldVisitTransitionError("unsupported field-visit status")
    if new_status == old_status:
        return
    if new_status not in STATUS_TRANSITIONS[old_status]:
        raise FieldVisitTransitionError(
            f"field-visit status cannot change from {old_status} to {new_status}"
        )


def normalize_optional_coordinate(
    latitude: float | None,
    longitude: float | None,
) -> tuple[float | None, float | None]:
    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        raise ValueError("latitude and longitude must be supplied together")
    return validate_coordinate(latitude, longitude)


def normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip()
    if not key:
        raise ValueError("idempotency key must not be blank")
    if len(key) > 200:
        raise ValueError("idempotency key must not exceed 200 characters")
    return key


def field_visit_request_hash(action: str, payload: dict) -> str:
    def json_default(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"unsupported request value: {type(value).__name__}")

    canonical = json.dumps(
        {"action": str(action), "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_location_address(value: object) -> str:
    """Normalize an address only for detecting whether saved coordinates are stale."""

    return " ".join(str(value or "").split()).casefold()


def location_address_fingerprint(value: object) -> str:
    normalized = normalize_location_address(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_item_inputs(
    items: Iterable[FieldVisitItemInput | dict],
) -> list[dict]:
    normalized = []
    seen: set[int] = set()
    for raw in items:
        if isinstance(raw, FieldVisitItemInput):
            values = asdict(raw)
        elif isinstance(raw, dict):
            values = dict(raw)
        else:
            raise TypeError("field-visit items must be mappings or FieldVisitItemInput")
        ownership_id = int(values.get("ownership_id") or 0)
        if ownership_id <= 0:
            raise ValueError("ownership_id must be a positive integer")
        if ownership_id in seen:
            raise ValueError(f"duplicate ownership_id in request: {ownership_id}")
        seen.add(ownership_id)
        priority = values.get("priority", 0)
        if isinstance(priority, bool):
            raise ValueError("priority must be an integer")
        priority = int(priority)
        route_order = values.get("route_order")
        route_order = int(route_order) if route_order is not None else None
        if route_order is not None and route_order <= 0:
            raise ValueError("route_order must be a positive integer")
        locked = bool(values.get("is_order_locked", False))
        if locked and route_order is None:
            raise ValueError("a locked item requires route_order")
        note = str(values.get("note") or "").strip()
        if len(note) > 5000:
            raise ValueError("item note must not exceed 5000 characters")
        normalized.append(
            {
                "ownership_id": ownership_id,
                "priority": priority,
                "route_order": route_order,
                "is_order_locked": locked,
                "note": note,
            }
        )
    if not normalized:
        raise ValueError("at least one field-visit item is required")
    return normalized


def _candidate_snapshot(items):
    fields = (
        "id",
        "status",
        "priority",
        "route_order",
        "is_order_locked",
        "latitude",
        "longitude",
        "updated_at",
        "location_updated_at",
    )
    return [
        {field: item.get(field) for field in fields}
        for item in sorted(items, key=lambda value: int(value["id"]))
    ]


def build_optimized_field_visit_plan(
    route_id: int,
    items: list[dict],
    current_latitude: float,
    current_longitude: float,
    *,
    keep_current_item_first: bool = True,
    current_item_id: int | None = None,
) -> tuple[dict, list[dict]]:
    """Build a preview while preserving excluded and manually locked slots."""

    current_latitude, current_longitude = validate_coordinate(
        current_latitude, current_longitude
    )
    eligible_statuses = {"planned", "in_progress", "postponed"}
    eligible = [
        item for item in items if str(item.get("status")) in eligible_statuses
    ]
    excluded = [
        item for item in items if str(item.get("status")) not in eligible_statuses
    ]
    eligible.sort(key=lambda item: (int(item["route_order"]), int(item["id"])))
    active_slots = [int(item["route_order"]) for item in eligible]

    if keep_current_item_first and current_item_id is None:
        in_progress = [
            item for item in eligible if item.get("status") == "in_progress"
        ]
        current_item_id = int(in_progress[0]["id"]) if in_progress else None
    if current_item_id is not None:
        current_item_id = int(current_item_id)

    candidates = []
    for active_rank, item in enumerate(eligible, start=1):
        candidates.append(
            RouteCandidate(
                item_id=int(item["id"]),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                status=str(item["status"]),
                priority=int(item.get("priority") or 0),
                route_order=active_rank,
                is_order_locked=bool(item.get("is_order_locked")),
            )
        )
    optimized = optimize_route(
        candidates,
        current_latitude,
        current_longitude,
        keep_current_item_id=current_item_id if keep_current_item_first else None,
    )
    optimized_rank = {
        int(item.item_id): index
        for index, item in enumerate(optimized, start=1)
    }
    for active_rank, item in enumerate(eligible, start=1):
        if item.get("is_order_locked") and optimized_rank[int(item["id"])] != active_rank:
            raise FieldVisitPlanConflict(
                "keeping the current item first would move a manually locked item"
            )
    planned_items = []
    total_distance = 0.0
    for index, item in enumerate(optimized):
        distance = (
            round(float(item.estimated_distance_km), 3)
            if item.estimated_distance_km is not None
            else None
        )
        if distance is not None:
            total_distance += distance
        planned_items.append(
            {
                "item_id": int(item.item_id),
                "route_order": active_slots[index],
                "estimated_distance_km": distance,
            }
        )
    total_distance = round(total_distance, 3)
    snapshot = _candidate_snapshot(items)
    token_payload = {
        "route_id": int(route_id),
        "current_latitude": current_latitude,
        "current_longitude": current_longitude,
        "keep_current_item_first": bool(keep_current_item_first),
        "current_item_id": current_item_id,
        "snapshot": snapshot,
        "items": planned_items,
    }
    preview = {
        "route_id": int(route_id),
        "current_item_id": current_item_id,
        "items": planned_items,
        "excluded_item_ids": [int(item["id"]) for item in excluded],
        "total_distance_km": total_distance,
        "plan_token": field_visit_request_hash("optimize_route", token_payload),
    }
    return preview, snapshot


class FieldVisitService:
    """Server-side field-visit use cases independent from FastAPI routes."""

    def __init__(self, source):
        self.source = source

    def get_today(self, user, visit_date: date):
        require_field_visit_capability(user, FIELD_VISIT_VIEW)
        return self.source.get_today_field_visit(user, visit_date)

    def get_route(self, user, route_id: int):
        require_field_visit_capability(user, FIELD_VISIT_VIEW)
        return self.source.get_field_visit_route(user, int(route_id))

    def list_unresolved(self, user, *, mine_only: bool = False):
        require_field_visit_capability(user, FIELD_VISIT_VIEW)
        return self.source.list_unresolved_field_visit_items(user, mine_only=mine_only)

    def list_calendar_items(
        self, user, *, start_date: date, end_date: date, mine_only: bool = False
    ):
        require_field_visit_capability(user, FIELD_VISIT_VIEW)
        return self.source.list_visit_calendar_items(
            user, start_date, end_date, mine_only=mine_only
        )

    def create_route(
        self,
        user,
        *,
        visit_date: date,
        title: str = "",
        start_latitude: float | None = None,
        start_longitude: float | None = None,
        idempotency_key: str | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_CREATE)
        if not isinstance(visit_date, date):
            raise ValueError("visit_date must be a date")
        title = str(title or "").strip()
        if len(title) > 200:
            raise ValueError("route title must not exceed 200 characters")
        start_latitude, start_longitude = normalize_optional_coordinate(
            start_latitude, start_longitude
        )
        payload = {
            "visit_date": visit_date,
            "title": title,
            "start_latitude": start_latitude,
            "start_longitude": start_longitude,
        }
        key = normalize_idempotency_key(idempotency_key)
        return self.source.create_field_visit_route(
            user,
            payload,
            idempotency_key=key,
            request_hash=field_visit_request_hash("create_route", payload),
        )

    def add_items(
        self,
        user,
        route_id: int,
        items: Iterable[FieldVisitItemInput | dict],
        *,
        idempotency_key: str | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_UPDATE)
        route_id = int(route_id)
        if route_id <= 0:
            raise ValueError("route_id must be a positive integer")
        normalized = normalize_item_inputs(items)
        payload = {"route_id": route_id, "items": normalized}
        key = normalize_idempotency_key(idempotency_key)
        return self.source.add_field_visit_items(
            user,
            route_id,
            normalized,
            idempotency_key=key,
            request_hash=field_visit_request_hash("add_items", payload),
        )

    def transition_item(
        self,
        user,
        item_id: int,
        new_status: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        note: str = "",
        postponed_until: datetime | None = None,
        contact_date: date | None = None,
        idempotency_key: str | None = None,
        allowed_old_statuses: Iterable[str] | None = None,
    ):
        capability = (
            FIELD_VISIT_COMPLETE
            if str(new_status).strip().lower() == "completed"
            else FIELD_VISIT_UPDATE
        )
        require_field_visit_capability(user, capability)
        item_id = int(item_id)
        if item_id <= 0:
            raise ValueError("item_id must be a positive integer")
        new_status = str(new_status or "").strip().lower()
        if new_status not in ALLOWED_STATUSES:
            raise FieldVisitTransitionError("unsupported field-visit status")
        latitude, longitude = normalize_optional_coordinate(latitude, longitude)
        note = str(note or "").strip()
        if len(note) > 5000:
            raise ValueError("status note must not exceed 5000 characters")
        if postponed_until is not None and not isinstance(postponed_until, datetime):
            raise ValueError("postponed_until must be a datetime")
        payload = {
            "item_id": item_id,
            "new_status": new_status,
            "latitude": latitude,
            "longitude": longitude,
            "note": note,
            "postponed_until": postponed_until,
            "contact_date": contact_date,
            "allowed_old_statuses": sorted(
                str(status).strip().lower()
                for status in (allowed_old_statuses or [])
            ),
        }
        key = normalize_idempotency_key(idempotency_key)
        return self.source.transition_field_visit_item(
            user,
            item_id,
            new_status,
            latitude=latitude,
            longitude=longitude,
            note=note,
            postponed_until=postponed_until,
            contact_date=contact_date,
            allowed_old_statuses=set(payload["allowed_old_statuses"]) or None,
            idempotency_key=key,
            request_hash=field_visit_request_hash("transition_item", payload),
        )

    def update_item(
        self,
        user,
        item_id: int,
        *,
        priority: int | None = None,
        is_order_locked: bool | None = None,
        idempotency_key: str | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_UPDATE)
        item_id = int(item_id)
        if item_id <= 0:
            raise ValueError("item_id must be a positive integer")
        if priority is None and is_order_locked is None:
            raise ValueError("at least one field-visit item setting is required")
        if priority is not None:
            if isinstance(priority, bool):
                raise ValueError("priority must be an integer")
            priority = int(priority)
            if priority < 0 or priority > 100:
                raise ValueError("priority must be between 0 and 100")
        payload = {
            "item_id": item_id,
            "priority": priority,
            "is_order_locked": is_order_locked,
        }
        key = normalize_idempotency_key(idempotency_key)
        return self.source.update_field_visit_item(
            user,
            item_id,
            priority=priority,
            is_order_locked=is_order_locked,
            idempotency_key=key,
            request_hash=field_visit_request_hash("update_item", payload),
        )

    def preview_optimization(
        self,
        user,
        route_id: int,
        *,
        current_latitude: float,
        current_longitude: float,
        keep_current_item_first: bool = True,
        current_item_id: int | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_OPTIMIZE)
        route_id = int(route_id)
        route = self.source.get_field_visit_route_candidates(user, route_id)
        preview, _snapshot = build_optimized_field_visit_plan(
            route_id,
            route["items"],
            current_latitude,
            current_longitude,
            keep_current_item_first=keep_current_item_first,
            current_item_id=current_item_id,
        )
        return preview

    def apply_optimization(
        self,
        user,
        route_id: int,
        *,
        current_latitude: float,
        current_longitude: float,
        plan_token: str,
        keep_current_item_first: bool = True,
        current_item_id: int | None = None,
        idempotency_key: str | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_OPTIMIZE)
        route_id = int(route_id)
        submitted_token = str(plan_token or "").strip()
        if len(submitted_token) != 64:
            raise FieldVisitPlanConflict("optimization plan token is invalid")
        route = self.source.get_field_visit_route_candidates(user, route_id)
        preview, snapshot = build_optimized_field_visit_plan(
            route_id,
            route["items"],
            current_latitude,
            current_longitude,
            keep_current_item_first=keep_current_item_first,
            current_item_id=current_item_id,
        )
        if preview["plan_token"] != submitted_token:
            raise FieldVisitPlanConflict(
                "field-visit route changed after the optimization preview"
            )
        payload = {
            "route_id": route_id,
            "plan_token": submitted_token,
            "items": preview["items"],
        }
        key = normalize_idempotency_key(idempotency_key)
        return self.source.apply_field_visit_route_order(
            user,
            route_id,
            preview["items"],
            expected_items=snapshot,
            start_latitude=float(current_latitude),
            start_longitude=float(current_longitude),
            total_distance_km=preview["total_distance_km"],
            idempotency_key=key,
            request_hash=field_visit_request_hash("apply_optimization", payload),
            action_type="api_optimize_field_visit_route",
        )

    def apply_manual_order(
        self,
        user,
        route_id: int,
        ordered_items: Iterable[dict],
        *,
        idempotency_key: str | None = None,
    ):
        require_field_visit_capability(user, FIELD_VISIT_UPDATE)
        route_id = int(route_id)
        submitted = [dict(item) for item in ordered_items]
        if not submitted:
            raise ValueError("manual route order must contain at least one item")
        item_ids = [int(item.get("item_id") or 0) for item in submitted]
        if any(item_id <= 0 for item_id in item_ids):
            raise ValueError("manual route item ids must be positive")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("manual route order contains duplicate item ids")
        route = self.source.get_field_visit_route_candidates(user, route_id)
        eligible_statuses = {"planned", "in_progress", "postponed"}
        eligible = sorted(
            [
                item
                for item in route["items"]
                if str(item.get("status")) in eligible_statuses
            ],
            key=lambda item: (int(item["route_order"]), int(item["id"])),
        )
        eligible_ids = {int(item["id"]) for item in eligible}
        if set(item_ids) != eligible_ids:
            raise FieldVisitPlanConflict(
                "manual order must contain every remaining route item exactly once"
            )
        active_slots = [int(item["route_order"]) for item in eligible]
        by_id = {int(item["id"]): item for item in eligible}
        plan_items = []
        for route_order, submitted_item in zip(active_slots, submitted, strict=True):
            current = by_id[int(submitted_item["item_id"])]
            distance = current.get("estimated_distance_km")
            if distance is not None:
                distance = float(distance)
            plan_items.append(
                {
                    "item_id": int(current["id"]),
                    "route_order": route_order,
                    "estimated_distance_km": distance,
                    "is_order_locked": bool(
                        submitted_item.get("is_order_locked", True)
                    ),
                }
            )
        payload = {"route_id": route_id, "items": plan_items}
        key = normalize_idempotency_key(idempotency_key)
        return self.source.apply_field_visit_route_order(
            user,
            route_id,
            plan_items,
            expected_items=_candidate_snapshot(route["items"]),
            start_latitude=route.get("start_latitude"),
            start_longitude=route.get("start_longitude"),
            total_distance_km=route.get("total_distance_km"),
            idempotency_key=key,
            request_hash=field_visit_request_hash("manual_reorder", payload),
            action_type="api_reorder_field_visit_route",
        )
