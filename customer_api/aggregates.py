"""Read-model projections for owner and land API views."""

import hashlib
from decimal import Decimal, InvalidOperation

from customer_domain import normalize_match_text


def _number(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _number_text(value):
    value = value.quantize(Decimal("0.01"))
    return format(value, "f")


def _stable_key(prefix, *parts):
    content = "\x1f".join(normalize_match_text(part) for part in parts)
    return hashlib.sha256(f"{prefix}:{content}".encode("utf-8")).hexdigest()[:24]


def aggregate_owners(records):
    owners = {}
    for record in records:
        identity = str(record.get("external_id") or "").strip()
        name = str(record.get("owner_name") or record.get("name") or "").strip()
        address = str(record.get("address") or "").strip()
        owner_key = (
            _stable_key("identity", identity)
            if identity
            else _stable_key("owner", name, address)
        )
        owner = owners.setdefault(
            owner_key,
            {
                "owner_key": owner_key,
                "name": name,
                "external_id": identity,
                "address": address,
                "record_ids": [],
                "lands": set(),
                "total_ping": Decimal("0"),
                "total_declared_value": Decimal("0"),
            },
        )
        owner["record_ids"].append(int(record["id"]))
        owner["lands"].add(
            (
                str(record.get("district") or ""),
                str(record.get("section") or ""),
                str(record.get("land_number") or ""),
            )
        )
        owner["total_ping"] += _number(record.get("ping"))
        owner["total_declared_value"] += _number(record.get("total_declared_value"))
    result = []
    for owner in owners.values():
        result.append(
            {
                **{key: value for key, value in owner.items() if key not in {"lands", "total_ping", "total_declared_value"}},
                "record_count": len(owner["record_ids"]),
                "land_count": len(owner["lands"]),
                "total_ping": _number_text(owner["total_ping"]),
                "total_declared_value": _number_text(owner["total_declared_value"]),
            }
        )
    return sorted(result, key=lambda item: (item["name"], item["owner_key"]))


def aggregate_lands(records):
    lands = {}
    for record in records:
        district = str(record.get("district") or "")
        section = str(record.get("section") or "")
        subsection = str(record.get("subsection") or "")
        land_number = str(record.get("land_number") or "")
        # subsection is deliberately left out of the land_key -- see the
        # PostgreSQL migration comment in postgres/schema.sql (version 13):
        # it is a plain descriptive field here, not part of land identity.
        land_key = _stable_key("land", district, section, land_number)
        land = lands.setdefault(
            land_key,
            {
                "land_key": land_key,
                "district": district,
                "section": section,
                "subsection": subsection,
                "land_number": land_number,
                "area": record.get("area") or "",
                "declared_value": record.get("declared_value") or "",
                "owners": [],
            },
        )
        land["owners"].append(
            {
                "record_id": int(record["id"]),
                "name": record.get("owner_name") or record.get("name") or "",
                "external_id": record.get("external_id") or "",
                "numerator": record.get("numerator") or "",
                "denominator": record.get("denominator") or "",
                "ping": record.get("ping") or "",
                "total_declared_value": record.get("total_declared_value") or "",
            }
        )
    return sorted(
        lands.values(),
        key=lambda item: (
            item["district"],
            item["section"],
            item["subsection"],
            item["land_number"],
        ),
    )
