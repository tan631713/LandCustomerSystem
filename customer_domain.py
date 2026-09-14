"""Pure business rules for land records, formatting, and duplicate detection."""

import csv
import re
from datetime import date


PING_CONVERSION_FACTOR = 0.3025
LEGACY_SHARED_LAND_BATCH_FIELDS = (
    "owner_name",
    "external_id",
    "address",
    "numerator",
    "denominator",
    "registration_reason",
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


def calculate_age_from_birth_year(value, *, today=None):
    """Turn a 4-digit Gregorian birth year into a whole-number age string.

    Only the year is known (not month/day), so this is a simple calendar-year
    subtraction -- the same approximation used when someone says "he was born
    in 1965" rather than giving an exact birthday.
    """

    text = str(value or "").strip()
    if not text.isdigit() or len(text) != 4:
        return ""
    year = int(text)
    current_year = (today or date.today()).year
    if not (1900 <= year <= current_year):
        return ""
    return str(current_year - year)


def mask_identity_text(value):
    text = str(value or "").strip()
    if len(text) <= 5:
        return text
    return text[:4] + ("*" * (len(text) - 5)) + text[-1]


def mask_identity_to_four_digits(value):
    """Privacy-mask an identity number down to just its first 4 characters.

    Explicit user request for the "測試" privacy mask toggle: no filler
    characters (unlike mask_identity_text()'s lighter, always-on "前4碼
    +星號+末1碼" convenience mask used elsewhere) -- just the prefix, so a
    10-character Taiwan ID like "Q201623129" becomes "Q201".
    """
    return str(value or "").strip()[:4]


def mask_owner_display_name(value):
    """Reduce an owner name to just its surname for the privacy mask toggle.

    A 1-3 character name keeps only its first character (covers the
    overwhelming majority of Chinese names -- a single-character surname
    plus a 1-2 character given name). A 4+ character name keeps its first
    two characters instead, so a two-character compound surname (歐陽,
    司馬, ...) followed by a given name is not truncated into a different,
    unrelated surname. This is a length heuristic, not a real compound-
    surname dictionary lookup -- it will occasionally keep one character
    too many/few for an unusual name shape, but never leaks more of the
    given name than that.
    """
    text = str(value or "").strip()
    if not text:
        return text
    keep = 2 if len(text) >= 4 else 1
    return text[:keep]


TAIWAN_ID_LETTER_VALUES = {
    letter: value
    for letter, value in zip(
        "ABCDEFGHJKLMNPQRSTUVXYWZIO",
        (
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
        ),
    )
}


def normalize_taiwan_identity(value):
    """Normalize and validate an optional Taiwan national ID number."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Z][12]\d{8}", text):
        raise ValueError("身分證字號格式不正確。")
    letter_value = TAIWAN_ID_LETTER_VALUES[text[0]]
    checksum = (letter_value // 10) + ((letter_value % 10) * 9)
    checksum += sum(
        int(digit) * weight
        for digit, weight in zip(text[1:], range(8, 0, -1))
    )
    checksum += int(text[-1])
    if checksum % 10:
        raise ValueError("身分證字號格式不正確。")
    return text


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
        normalize_match_text(data.get("subsection")),
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
        records.append(
            {"_line_number": line_number, **{key: value or None for key, value in record.items()}}
        )
    if not records and not errors:
        errors.append("請至少輸入一筆所有權人資料")
    else:
        seen_orders = {}
        for record in records:
            order = record.get("registration_order")
            if not order:
                continue
            if order in seen_orders:
                errors.append(
                    f"第 {record['_line_number']} 行登記次序「{order}」"
                    f"與第 {seen_orders[order]} 行重複，請確認是否貼錯或漏改序號"
                )
                continue
            seen_orders[order] = record["_line_number"]
    for record in records:
        record.pop("_line_number", None)
    return records, errors
