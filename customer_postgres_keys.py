"""Stable privacy-preserving keys shared by PostgreSQL migration and writes."""

import hashlib
import hmac

from customer_domain import normalize_match_text


def _keyed_digest(data_key, namespace, *parts):
    message = "\x1f".join(normalize_match_text(part) for part in parts)
    return hmac.new(
        bytes(data_key),
        f"{namespace}:{message}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def owner_key_for(record, data_key):
    identity = normalize_match_text(record.get("external_id"))
    if identity:
        return _keyed_digest(data_key, "identity", identity)
    name = normalize_match_text(record.get("owner_name") or record.get("name"))
    address = normalize_match_text(record.get("address"))
    if name or address:
        return _keyed_digest(data_key, "owner", name, address)
    return _keyed_digest(data_key, "legacy-owner", record.get("id"))


def land_key_for(record):
    message = "\x1f".join(
        normalize_match_text(record.get(key))
        for key in ("district", "section", "land_number")
    )
    return hashlib.sha256(f"land:{message}".encode("utf-8")).hexdigest()
