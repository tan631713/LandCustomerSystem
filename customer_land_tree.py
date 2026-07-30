"""Pure land/ownership grouping and sorting used by the desktop tree view."""

from __future__ import annotations

import re
from dataclasses import dataclass

from customer_domain import parse_number
from customer_tag_display import deduplicate_tag_items


LAND_PARENT_SORT_FIELDS = {
    "rowid",
    "district",
    "section",
    "land_number",
    "full_land_number",
    "area",
    "owner_count",
    "ownership_count",
}
CHILD_NUMERIC_SORT_FIELDS = {
    "rowid",
    "registration_order",
    "numerator",
    "denominator",
    "ping",
    "ownership_area",
    "declared_value",
    "total_declared_value",
    "attachment_count",
}
_LAND_NUMBER_PART = re.compile(r"\d+|[^\d]+")


def _value(record, key, default=""):
    raw = record.get("raw") or {}
    if key in raw:
        return raw.get(key, default)
    display = record.get("display") or {}
    return display.get(key, default)


def _positive_int(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def normalized_land_number_key(value):
    """Sort parcel numbers naturally: 2, 10, 100 and then their subnumbers."""

    text = str(value or "").strip().casefold()
    text = text.replace("之", "-").replace("－", "-").replace("—", "-")
    key = []
    for part in _LAND_NUMBER_PART.findall(text):
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key) or ((1, ""),)


def full_land_number(record):
    raw = record.get("raw") or {}
    parts = [
        str(raw.get("district") or "").strip(),
        str(raw.get("section") or "").strip(),
        str(raw.get("land_number") or "").strip(),
    ]
    text = " ".join(part for part in parts if part)
    return f"{text} 地號" if text and not text.endswith("地號") else text


def land_identity(record):
    land_id = _positive_int(record.get("land_id") or _value(record, "land_id"))
    if land_id is not None:
        return ("land_id", land_id)
    raw = record.get("raw") or {}
    # The current product stores district/section/land_number.  If the API is
    # later expanded with the more detailed cadastral components, they are
    # already included in this fallback and cannot be merged across regions.
    identity = (
        "land_key",
        str(raw.get("city") or "").strip().casefold(),
        str(raw.get("township") or raw.get("district") or "").strip().casefold(),
        str(raw.get("section") or "").strip().casefold(),
        str(raw.get("subsection") or "").strip().casefold(),
        str(raw.get("land_number_main") or raw.get("land_number") or "")
        .strip()
        .casefold(),
        str(raw.get("land_number_sub") or "").strip().casefold(),
    )
    if not any(identity[1:]):
        # A legacy or synthetic row with no parcel identity must never absorb
        # other blank rows into one false land group.
        return ("record_fallback", int(record.get("id") or 0))
    return identity


def owner_identity(record):
    owner_id = _positive_int(record.get("owner_id") or _value(record, "owner_id"))
    if owner_id is not None:
        return ("owner_id", owner_id)
    raw = record.get("raw") or {}
    external_id = str(raw.get("external_id") or "").strip().casefold()
    name = str(raw.get("owner_name") or "").strip().casefold()
    address = str(raw.get("address") or "").strip().casefold()
    if external_id:
        return ("external_id", external_id)
    if name or address:
        return ("owner_fallback", name, address)
    return ("ownership", int(record.get("id") or 0))


def ownership_area(record):
    raw = record.get("raw") or {}
    area = parse_number(raw.get("area"))
    numerator = parse_number(raw.get("numerator"))
    denominator = parse_number(raw.get("denominator"))
    if area is None or numerator is None or denominator in (None, 0):
        return None
    return area * numerator / denominator


def status_summary(records):
    values = []
    for key in ("customer_status", "follow_up_status", "case_names", "tag_names"):
        for record in records:
            value = str(_value(record, key) or "").strip()
            if value and value not in values:
                values.append(value)
    return "／".join(values[:4])


@dataclass(slots=True)
class LandGroup:
    identity: tuple
    land_id: int | None
    records: list
    owner_count: int
    ownership_count: int
    full_land_number: str
    area: object
    land_use: str
    status_summary: str
    tags: list

    @property
    def representative(self):
        return self.records[0]

    @property
    def record_ids(self):
        return [int(record["id"]) for record in self.records]

    @property
    def state_id(self):
        return self.land_id if self.land_id is not None else self.identity


class LandTreeRows(list):
    """List-compatible search result carrying precomputed background groups."""

    def __init__(self, records, groups):
        super().__init__(records)
        self.groups = list(groups)


def _parent_sort_key(group, field):
    raw = group.representative.get("raw") or {}
    if field == "rowid":
        return group.land_id or max(group.record_ids)
    if field == "district":
        return str(raw.get("district") or "").casefold()
    if field == "section":
        return str(raw.get("section") or "").casefold()
    if field in {"land_number", "full_land_number"}:
        return normalized_land_number_key(raw.get("land_number"))
    if field == "area":
        value = parse_number(group.area)
        return float("-inf") if value is None else value
    if field == "owner_count":
        return group.owner_count
    if field == "ownership_count":
        return group.ownership_count
    return (
        str(raw.get("district") or "").casefold(),
        str(raw.get("section") or "").casefold(),
        normalized_land_number_key(raw.get("land_number")),
        group.land_id or 0,
    )


def _child_sort_key(record, field):
    value = _value(record, field)
    if field == "owner_name":
        return str(value or "").casefold()
    if field == "share":
        raw = record.get("raw") or {}
        numerator = parse_number(raw.get("numerator"))
        denominator = parse_number(raw.get("denominator"))
        if numerator is None or denominator in (None, 0):
            return float("-inf")
        return numerator / denominator
    if field == "ownership_area":
        value = ownership_area(record)
    if field in CHILD_NUMERIC_SORT_FIELDS:
        number = parse_number(value)
        return float("-inf") if number is None else number
    return str(value or "").casefold()


def group_land_records(records, *, sort_field="rowid", reverse=True):
    """Group ownership records without ever merging distinct land IDs."""

    grouped = {}
    order = []
    for record in records:
        identity = land_identity(record)
        if identity not in grouped:
            grouped[identity] = []
            order.append(identity)
        grouped[identity].append(record)

    groups = []
    child_sort = sort_field not in LAND_PARENT_SORT_FIELDS
    for identity in order:
        children = grouped[identity]
        if child_sort:
            children.sort(
                key=lambda row: _child_sort_key(row, sort_field),
                reverse=bool(reverse),
            )
        representative = children[0]
        raw = representative.get("raw") or {}
        land_id = _positive_int(
            representative.get("land_id") or raw.get("land_id")
        )
        groups.append(
            LandGroup(
                identity=identity,
                land_id=land_id,
                records=children,
                owner_count=len({owner_identity(row) for row in children}),
                ownership_count=len(children),
                full_land_number=full_land_number(representative),
                area=raw.get("area"),
                land_use=str(raw.get("land_use") or "").strip(),
                status_summary=status_summary(children),
                tags=deduplicate_tag_items(
                    record.get("tags")
                    or (record.get("raw") or {}).get("tag_items")
                    or []
                    for record in children
                ),
            )
        )

    parent_field = sort_field if sort_field in LAND_PARENT_SORT_FIELDS else "land_number"
    groups.sort(
        key=lambda group: _parent_sort_key(group, parent_field),
        reverse=bool(reverse) if not child_sort else False,
    )
    flattened = [record for group in groups for record in group.records]
    return LandTreeRows(flattened, groups)
