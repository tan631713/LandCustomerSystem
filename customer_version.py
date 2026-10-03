"""Application release metadata."""

APP_VERSION = "1.9.42"
DESKTOP_CLIENT_VERSION = "1.9.85"
BUILD_DATE = "2026-10-03"
DESKTOP_CLIENT_BUILD_DATE = "2026-10-03"
MOBILE_ASSET_VERSION = 32


def version_label():
    return f"v{APP_VERSION}"


def desktop_client_version_label():
    return f"v{DESKTOP_CLIENT_VERSION}"


def full_version_text():
    return f"土地資料系統 {version_label()}\n建置日期：{BUILD_DATE}"
