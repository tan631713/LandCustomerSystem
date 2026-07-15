"""Pure business rules for land records, formatting, and duplicate detection."""

import csv
import re


PING_CONVERSION_FACTOR = 0.3025
LEGACY_SHARED_LAND_BATCH_FIELDS = (
    "owner_name",
    "external_id",
    "address",
    "numerator",
    "denominator",
    "note",
    "visit_log",
)
SHARED_LAND_BATCH_FIELDS = ("registration_order", *LEGACY_SHARED_LAND_BATCH_FIELDS)


def parse_number(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_rights_scope(value):
    text = str(value or "").strip().replace(" ", "")
    if not text or text in ("全部", "全"):
        return 1.0
    if text.endswith("%"):
        number = parse_number(text[:-1])
        return None if number is None else number / 100
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        numerator_value = parse_number(numerator)
        denominator_value = parse_number(denominator)
        if numerator_value is not None and denominator_value:
            return numerator_value / denominator_value
    if "分之" in text:
        denominator, numerator = text.split("分之", 1)
        numerator_value = parse_number(numerator)
        denominator_value = parse_number(denominator)
        if numerator_value is not None and denominator_value:
            return numerator_value / denominator_value
    return parse_number(text)


def split_rights_scope(value):
    text = str(value or "").strip().replace(" ", "")
    if not text or text in ("全部", "全"):
        return "1", "1"
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return numerator or None, denominator or None
    if "分之" in text:
        denominator, numerator = text.split("分之", 1)
        return numerator or None, denominator or None
    ratio = parse_rights_scope(text)
    if ratio is None:
        return None, None
    return str(ratio), "1"


def format_number(value):
    if value is None:
        return ""
    return f"{round(value):,}"


def format_number_text(value):
    number = parse_number(value)
    return value if number is None else format_number(number)


def calculate_total_declared_value(data):
    area = parse_number(data.get("area"))
    declared_value = parse_number(data.get("declared_value"))
    numerator = parse_number(data.get("numerator"))
    denominator = parse_number(data.get("denominator")) or 1
    if numerator is None and data.get("rights_scope"):
        numerator_text, denominator_text = split_rights_scope(data.get("rights_scope"))
        numerator = parse_number(numerator_text)
        denominator = parse_number(denominator_text) or 1
    if area is None or declared_value is None or numerator is None or not denominator:
        return None
    return format_number(area * declared_value * numerator / denominator)


def calculate_ping(data):
    area = parse_number(data.get("area"))
    numerator = parse_number(data.get("numerator"))
    denominator = parse_number(data.get("denominator"))
    if numerator is None and data.get("rights_scope"):
        numerator_text, denominator_text = split_rights_scope(data.get("rights_scope"))
        numerator = parse_number(numerator_text)
        denominator = parse_number(denominator_text)
    if area is None or numerator is None or not denominator:
        return None
    return f"{area * numerator / denominator * PING_CONVERSION_FACTOR:.2f}"


def format_ping_text(value):
    number = parse_number(value)
    return "" if number is None else f"{number:.2f}"


def mask_identity_text(value):
    text = str(value or "").strip()
    if len(text) <= 4:
        return text
    return text[:3] + ("*" * (len(text) - 4)) + text[-1]


def normalize_text(value):
    return str(value or "").strip()


def normalize_match_text(value):
    return normalize_text(value).casefold()


def normalize_search_text(value):
    """Normalize a search condition without changing stored business values."""
    return "".join(normalize_match_text(value).split())


def split_search_terms(value):
    """Return unique OR-search terms separated by common Chinese punctuation."""
    terms = []
    for part in re.split(r"[、，,\r\n]+", str(value or "")):
        normalized = normalize_search_text(part)
        if normalized and normalized not in terms:
            terms.append(normalized)
    return tuple(terms)


def build_duplicate_signature(data):
    parts = [
        normalize_match_text(data.get("district")),
        normalize_match_text(data.get("section")),
        normalize_match_text(data.get("registration_order")),
        normalize_match_text(data.get("land_number")),
        normalize_match_text(data.get("owner_name")),
        normalize_match_text(data.get("external_id")),
    ]
    return tuple(parts) if any(parts) else None


def parse_shared_land_rows(text):
    records = []
    errors = []
    field_order = None
    for line_number, original_line in enumerate(str(text or "").splitlines(), start=1):
        if not original_line.strip():
            continue
        delimiter = "\t" if "\t" in original_line else ","
        source = (
            original_line
            if delimiter == "\t"
            else original_line.replace("，", ",").replace("、", ",")
        )
        values = next(csv.reader([source], delimiter=delimiter))
        values = [str(value or "").strip() for value in values]
        first_value = normalize_text(values[0]) if values else ""
        if line_number == 1:
            if first_value in {"登記次序", "序號", "registration_order"}:
                field_order = SHARED_LAND_BATCH_FIELDS
                continue
            if first_value in {"姓名", "所有權人", "owner_name"}:
                field_order = LEGACY_SHARED_LAND_BATCH_FIELDS
                continue
        if field_order is None:
            field_order = (
                SHARED_LAND_BATCH_FIELDS
                if (
                    len(values) == len(SHARED_LAND_BATCH_FIELDS)
                    or (len(values) >= 2 and parse_number(first_value) is not None)
                )
                else LEGACY_SHARED_LAND_BATCH_FIELDS
            )
        if len(values) > len(SHARED_LAND_BATCH_FIELDS):
            errors.append(f"第 {line_number} 行欄位超過 {len(SHARED_LAND_BATCH_FIELDS)} 欄")
            continue
        if len(values) > len(field_order):
            errors.append(f"第 {line_number} 行欄位數與標題不一致")
            continue
        values.extend([""] * (len(field_order) - len(values)))
        record = dict(zip(field_order, values))
        if not record["owner_name"]:
            errors.append(f"第 {line_number} 行缺少姓名")
            continue
        numerator = parse_number(record["numerator"])
        denominator = parse_number(record["denominator"])
        if record["numerator"] and numerator is None:
            errors.append(f"第 {line_number} 行分子格式錯誤")
            continue
        if record["denominator"] and (denominator is None or denominator <= 0):
            errors.append(f"第 {line_number} 行分母必須大於 0")
            continue
        records.append({key: value or None for key, value in record.items()})
    if not records and not errors:
        errors.append("請至少輸入一筆所有權人資料")
    return records, errors
