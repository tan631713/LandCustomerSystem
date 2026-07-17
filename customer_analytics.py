"""Dashboard aggregation without UI dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from customer_domain import format_number, parse_number


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def build_dashboard_stats(
    repository: Any,
    *,
    plain_record: Callable[[Any], Mapping[str, Any]],
    plain_reminder: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate the records and management metadata used by the dashboard."""

    rows = repository.fetch_all_customer_rows()
    district_counts: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    totals = {"area": 0, "declared": 0, "current": 0}
    flags = {
        "external_id": 0,
        "note": 0,
        "visit_log": 0,
        "case": 0,
        "tags": 0,
        "attachments": 0,
        "custom_values": 0,
        "contact": 0,
    }

    for row in rows:
        data = plain_record(row)
        _increment(district_counts, data.get("district") or "(空白)")
        _increment(section_counts, data.get("section") or "(空白)")
        totals["area"] += parse_number(data.get("area")) or 0
        totals["declared"] += parse_number(data.get("declared_value")) or 0
        totals["current"] += parse_number(data.get("total_declared_value")) or 0
        flags["external_id"] += bool(data.get("external_id"))
        flags["note"] += bool(data.get("note"))
        flags["visit_log"] += bool(data.get("visit_log"))
        flags["case"] += bool(row["case_names"])
        flags["tags"] += bool(row["tag_names"])
        flags["attachments"] += bool(row["attachment_count"])
        flags["custom_values"] += bool(row["custom_values"])
        flags["contact"] += bool(row["last_contact"])

    reminders = [plain_reminder(row) for row in repository.list_follow_up_reminders()]
    follow_status_counts: dict[str, int] = {}
    for reminder in reminders:
        _increment(follow_status_counts, reminder.get("status") or "未處理")
    open_follow_ups = sum(
        count for status, count in follow_status_counts.items() if status != "完成"
    )

    cases = [dict(row) for row in repository.list_cases()]
    tags = [dict(row) for row in repository.list_tags()]
    if hasattr(repository, "management_table_counts"):
        management_counts = repository.management_table_counts()
    else:
        management_counts = {
            "customer_attachments": sum(int(row.get("attachment_count") or 0) for row in rows),
            "contact_logs": flags["contact"],
        }

    total_records = len(rows)
    return {
        "total_records": total_records,
        "total_area": format_number(totals["area"]),
        "total_declared_value": format_number(totals["declared"]),
        "total_current_value": format_number(totals["current"]),
        "with_external_id": flags["external_id"],
        "without_external_id": total_records - flags["external_id"],
        "with_note": flags["note"],
        "with_visit_log": flags["visit_log"],
        "with_case": flags["case"],
        "with_tags": flags["tags"],
        "with_attachments": flags["attachments"],
        "with_custom_values": flags["custom_values"],
        "with_contact": flags["contact"],
        "case_count": len(cases),
        "tag_count": len(tags),
        "attachment_count": management_counts.get("customer_attachments", 0),
        "contact_log_count": management_counts.get("contact_logs", 0),
        "open_follow_ups": open_follow_ups,
        "district_counts": sorted(district_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
        "section_counts": sorted(section_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
        "follow_up_status_counts": sorted(follow_status_counts.items()),
        "case_counts": [
            (case.get("title") or "(未命名)", case.get("customer_count") or 0, case.get("status") or "")
            for case in cases[:20]
        ],
        "tag_counts": [
            (tag.get("name") or "(未命名)", tag.get("customer_count") or 0)
            for tag in tags[:20]
        ],
    }
