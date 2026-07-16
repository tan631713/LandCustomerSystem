"""Serialization and validation for desktop preferences."""

import json


def encode_table_preferences(preferences):
    return json.dumps(preferences, ensure_ascii=False)


def decode_table_preferences(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def sanitize_saved_searches(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        criteria = item.get("criteria")
        if not name or not isinstance(criteria, dict):
            continue
        cleaned.append({"name": name, "criteria": criteria})
    return cleaned
