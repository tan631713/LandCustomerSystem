"""Application release metadata."""

APP_VERSION = "1.7.2"
BUILD_DATE = "2026-07-17"


def version_label():
    return f"v{APP_VERSION}"


def full_version_text():
    return f"土地資料系統 {version_label()}\n建置日期：{BUILD_DATE}"
