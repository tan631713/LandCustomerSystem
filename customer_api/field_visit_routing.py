"""Pure route-planning helpers for the mobile field-visit workflow.

This module deliberately has no database or FastAPI dependency.  It can be
used by the future field-visit service and tested without opening production
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Iterable


EARTH_RADIUS_KM = 6371.0088
ALLOWED_STATUSES = frozenset(
    {"planned", "in_progress", "completed", "skipped", "postponed", "cancelled"}
)
EXCLUDED_STATUSES = frozenset({"completed", "cancelled"})


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """One visit candidate supplied by the field-visit repository."""

    item_id: int
    latitude: float | None = None
    longitude: float | None = None
    status: str = "planned"
    priority: int = 0
    route_order: int | None = None
    is_order_locked: bool = False


@dataclass(frozen=True, slots=True)
class OptimizedRouteItem:
    """One item in the calculated route.

    ``estimated_distance_km`` is the distance of this leg from the preceding
    point.  It is ``None`` when the item has no stored coordinate.
    """

    item_id: int
    route_order: int
    estimated_distance_km: float | None


@dataclass(frozen=True, slots=True)
class _PreparedCoordinate:
    """One validated coordinate with reusable trigonometric values."""

    latitude: float
    longitude: float
    latitude_radians: float
    longitude_radians: float
    cosine_latitude: float


def validate_coordinate(latitude: float, longitude: float) -> tuple[float, float]:
    """Return normalized coordinates or raise ``ValueError``."""

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("latitude and longitude must be numeric") from exc
    if not isfinite(latitude) or not isfinite(longitude):
        raise ValueError("latitude and longitude must be finite")
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    return latitude, longitude


def _prepare_coordinate(
    coordinate: tuple[float, float],
) -> _PreparedCoordinate:
    latitude, longitude = coordinate
    latitude_radians = radians(latitude)
    return _PreparedCoordinate(
        latitude=latitude,
        longitude=longitude,
        latitude_radians=latitude_radians,
        longitude_radians=radians(longitude),
        cosine_latitude=cos(latitude_radians),
    )


def _prepared_haversine_km(
    coordinate_a: _PreparedCoordinate,
    coordinate_b: _PreparedCoordinate,
) -> float:
    delta_latitude = coordinate_b.latitude_radians - coordinate_a.latitude_radians
    delta_longitude = (
        coordinate_b.longitude_radians - coordinate_a.longitude_radians
    )
    haversine = (
        sin(delta_latitude / 2) ** 2
        + coordinate_a.cosine_latitude
        * coordinate_b.cosine_latitude
        * sin(delta_longitude / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, haversine)))


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calculate the great-circle distance between two WGS84 points."""

    coordinate_a = _prepare_coordinate(
        validate_coordinate(latitude_a, longitude_a)
    )
    coordinate_b = _prepare_coordinate(
        validate_coordinate(latitude_b, longitude_b)
    )
    return _prepared_haversine_km(coordinate_a, coordinate_b)


def _coordinate(candidate: RouteCandidate) -> tuple[float, float] | None:
    if candidate.latitude is None and candidate.longitude is None:
        return None
    if candidate.latitude is None or candidate.longitude is None:
        raise ValueError(
            f"route item {candidate.item_id} must provide both latitude and longitude"
        )
    return validate_coordinate(candidate.latitude, candidate.longitude)


def _validate_candidates(
    candidates: Iterable[RouteCandidate],
) -> list[RouteCandidate]:
    normalized = list(candidates)
    seen_ids: set[int] = set()
    for candidate in normalized:
        if not isinstance(candidate, RouteCandidate):
            raise TypeError("candidates must contain RouteCandidate values")
        if candidate.item_id <= 0:
            raise ValueError("item_id must be a positive integer")
        if candidate.item_id in seen_ids:
            raise ValueError(f"duplicate route item id: {candidate.item_id}")
        seen_ids.add(candidate.item_id)
        status = str(candidate.status).strip().lower()
        if status not in ALLOWED_STATUSES:
            raise ValueError(
                f"unsupported status for route item {candidate.item_id}: {candidate.status}"
            )
        if status != candidate.status:
            raise ValueError("status must use the normalized lowercase value")
        if isinstance(candidate.priority, bool) or not isinstance(candidate.priority, int):
            raise ValueError("priority must be an integer")
        if candidate.route_order is not None and candidate.route_order <= 0:
            raise ValueError("route_order must be a positive integer or None")
        _coordinate(candidate)
    return normalized


def _nearest_neighbour(
    candidates: list[RouteCandidate],
    start: _PreparedCoordinate,
    coordinates: dict[int, _PreparedCoordinate],
) -> tuple[list[RouteCandidate], _PreparedCoordinate]:
    remaining = list(candidates)
    ordered: list[RouteCandidate] = []
    current = start
    while remaining:
        nearest_index = min(
            range(len(remaining)),
            key=lambda index: (
                _prepared_haversine_km(
                    current,
                    coordinates[remaining[index].item_id],
                ),
                remaining[index].route_order
                if remaining[index].route_order is not None
                else 2**31,
                remaining[index].item_id,
            ),
        )
        candidate = remaining.pop(nearest_index)
        ordered.append(candidate)
        current = coordinates[candidate.item_id]
    return ordered, current


def _automatic_order(
    candidates: list[RouteCandidate],
    start: tuple[float, float],
) -> list[RouteCandidate]:
    with_coordinates: list[RouteCandidate] = []
    without_coordinates: list[RouteCandidate] = []
    coordinates: dict[int, _PreparedCoordinate] = {}
    for candidate in candidates:
        coordinate = _coordinate(candidate)
        if coordinate is None:
            without_coordinates.append(candidate)
            continue
        with_coordinates.append(candidate)
        coordinates[candidate.item_id] = _prepare_coordinate(coordinate)

    current = _prepare_coordinate(start)
    ordered: list[RouteCandidate] = []
    for postponed in (False, True):
        group = [
            candidate
            for candidate in with_coordinates
            if (candidate.status == "postponed") is postponed
        ]
        priorities = sorted({candidate.priority for candidate in group}, reverse=True)
        for priority in priorities:
            priority_group = [
                candidate for candidate in group if candidate.priority == priority
            ]
            nearest, current = _nearest_neighbour(
                priority_group,
                current,
                coordinates,
            )
            ordered.extend(nearest)

    without_coordinates.sort(
        key=lambda candidate: (
            candidate.status == "postponed",
            -candidate.priority,
            candidate.route_order
            if candidate.route_order is not None
            else 2**31,
            candidate.item_id,
        )
    )
    ordered.extend(without_coordinates)
    return ordered


def _merge_locked_positions(
    automatic: list[RouteCandidate],
    locked: list[RouteCandidate],
    forced_first: RouteCandidate | None,
) -> list[RouteCandidate]:
    size = len(automatic) + len(locked) + (1 if forced_first else 0)
    slots: list[RouteCandidate | None] = [None] * size
    if forced_first is not None:
        slots[0] = forced_first

    locked = sorted(
        locked,
        key=lambda candidate: (
            candidate.route_order
            if candidate.route_order is not None
            else 2**31,
            candidate.item_id,
        ),
    )
    for candidate in locked:
        target = min(max((candidate.route_order or size) - 1, 0), size - 1)
        open_index = next(
            (index for index in range(target, size) if slots[index] is None),
            None,
        )
        if open_index is None:
            open_index = next(
                index for index in range(target - 1, -1, -1) if slots[index] is None
            )
        slots[open_index] = candidate

    automatic_iter = iter(automatic)
    for index, candidate in enumerate(slots):
        if candidate is None:
            slots[index] = next(automatic_iter)
    return [candidate for candidate in slots if candidate is not None]


def optimize_route(
    candidates: Iterable[RouteCandidate],
    current_latitude: float,
    current_longitude: float,
    *,
    keep_current_item_id: int | None = None,
    include_skipped: bool = False,
) -> list[OptimizedRouteItem]:
    """Order remaining visit items with a deterministic nearest-neighbour plan.

    Rules, in descending precedence:

    1. Completed and cancelled items are excluded. Skipped items are excluded
       unless ``include_skipped`` is explicitly enabled.
    2. ``keep_current_item_id`` is kept first when supplied.
    3. Manually locked items retain their requested 1-based route slots.
    4. Higher numeric priorities are planned before lower priorities.
    5. Postponed items are planned after other coordinate-bearing items.
    6. Items without coordinates are placed last.
    """

    start = validate_coordinate(current_latitude, current_longitude)
    normalized = _validate_candidates(candidates)
    eligible = [
        candidate
        for candidate in normalized
        if candidate.status not in EXCLUDED_STATUSES
        and (include_skipped or candidate.status != "skipped")
    ]
    expected_eligible_ids = {candidate.item_id for candidate in eligible}

    forced_first = None
    if keep_current_item_id is not None:
        forced_first = next(
            (
                candidate
                for candidate in eligible
                if candidate.item_id == int(keep_current_item_id)
            ),
            None,
        )
        if forced_first is None:
            raise ValueError("keep_current_item_id is not an eligible route item")
        eligible.remove(forced_first)
        forced_coordinate = _coordinate(forced_first)
        if forced_coordinate is not None:
            start_for_automatic = forced_coordinate
        else:
            start_for_automatic = start
    else:
        start_for_automatic = start

    locked = [candidate for candidate in eligible if candidate.is_order_locked]
    automatic_candidates = [
        candidate for candidate in eligible if not candidate.is_order_locked
    ]
    automatic = _automatic_order(automatic_candidates, start_for_automatic)
    ordered = _merge_locked_positions(automatic, locked, forced_first)
    ordered_ids = [candidate.item_id for candidate in ordered]
    if (
        len(ordered_ids) != len(expected_eligible_ids)
        or set(ordered_ids) != expected_eligible_ids
    ):
        raise RuntimeError(
            "route planning integrity check failed: eligible items were lost or duplicated"
        )

    current = start
    result: list[OptimizedRouteItem] = []
    for route_order, candidate in enumerate(ordered, start=1):
        coordinate = _coordinate(candidate)
        distance = None
        if coordinate is not None:
            distance = haversine_km(current[0], current[1], coordinate[0], coordinate[1])
            current = coordinate
        result.append(
            OptimizedRouteItem(
                item_id=candidate.item_id,
                route_order=route_order,
                estimated_distance_km=distance,
            )
        )
    return result
