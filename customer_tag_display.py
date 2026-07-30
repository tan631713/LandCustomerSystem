"""Shared tag metadata normalization and safe display colours."""

from __future__ import annotations

import json
import re

from PySide6.QtGui import QColor


DEFAULT_TAG_COLOR = "#64748B"
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_tag_color(value, default=DEFAULT_TAG_COLOR):
    """Return a valid #RRGGBB colour without ever passing bad data to QColor."""

    text = str(value or "").strip()
    if _HEX_COLOR.fullmatch(text):
        return text.upper()
    fallback = str(default or DEFAULT_TAG_COLOR).strip()
    return fallback.upper() if _HEX_COLOR.fullmatch(fallback) else DEFAULT_TAG_COLOR


def safe_tag_qcolor(value, default=DEFAULT_TAG_COLOR):
    return QColor(normalize_tag_color(value, default))


def tag_text_qcolor(value):
    """Choose WCAG-style readable black/white text for a tag background."""

    color = safe_tag_qcolor(value)
    red = color.redF()
    green = color.greenF()
    blue = color.blueF()

    def linear(channel):
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
    return QColor("#111827") if luminance >= 0.42 else QColor("#FFFFFF")


def _decoded_tag_items(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(decoded) if isinstance(decoded, list) else []


def normalize_tag_items(value, *, names="", primary_color=""):
    """Normalize API/SQLite tag payloads and retain a legacy-server fallback."""

    result = []
    seen = set()
    for position, item in enumerate(_decoded_tag_items(value)):
        if not isinstance(item, dict):
            continue
        raw_id = item.get("tag_id", item.get("id"))
        try:
            tag_id = int(raw_id)
        except (TypeError, ValueError):
            tag_id = None
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        identity = ("id", tag_id) if tag_id is not None else ("name", name.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "tag_id": tag_id,
                "name": name,
                "color": normalize_tag_color(item.get("color")),
            }
        )

    if result:
        return result

    # Backward compatibility for a desktop client temporarily talking to an
    # older server. New API responses always provide tag_items with real IDs.
    for position, name in enumerate(str(names or "").split("、")):
        name = name.strip()
        if not name:
            continue
        result.append(
            {
                "tag_id": None,
                "name": name,
                "color": normalize_tag_color(primary_color if position == 0 else ""),
            }
        )
    return result


def deduplicate_tag_items(groups):
    """Union tag lists by tag_id while preserving each tag's own colour."""

    result = []
    seen = set()
    for items in groups:
        for item in normalize_tag_items(items):
            tag_id = item.get("tag_id")
            identity = (
                ("id", int(tag_id))
                if tag_id is not None
                else ("name", str(item.get("name") or "").casefold())
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(dict(item))
    return result


def tag_names(items):
    return "、".join(
        str(item.get("name") or "").strip()
        for item in normalize_tag_items(items)
        if str(item.get("name") or "").strip()
    )
