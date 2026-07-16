"""UI-independent text formatting for desktop record summaries."""

from urllib.parse import urlsplit


def compact_summary_text(value, max_length=120):
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def attachment_display_name(value):
    text = " ".join(str(value or "").split())
    if "（" in text and text.endswith("）"):
        description = text.rsplit("（", 1)[0].strip()
        if description:
            return compact_summary_text(description, 48)

    parsed = urlsplit(text)
    if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
        return f"外部連結（{parsed.netloc}）"

    file_name = text.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    return compact_summary_text(file_name or "附件", 48)


def format_attachment_summary(attachment_names, attachment_count=0):
    items = [item.strip() for item in str(attachment_names or "").split("；") if item.strip()]
    labels = [attachment_display_name(item) for item in items[:2]]
    if len(items) > 2:
        labels.append("…")

    try:
        count = max(0, int(attachment_count or 0))
    except (TypeError, ValueError):
        count = 0
    count = count or len(items)

    names_text = "、".join(label for label in labels if label)
    if names_text and count:
        return f"{names_text}，共 {count} 個"
    if names_text:
        return names_text
    if count:
        return f"{count} 個"
    return ""
