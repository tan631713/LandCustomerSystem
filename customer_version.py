"""Application release metadata."""

APP_VERSION = "1.9.27"
DESKTOP_CLIENT_VERSION = "1.9.12"
BUILD_DATE = "2026-07-30"
MOBILE_ASSET_VERSION = 25


def version_label():
    return f"v{APP_VERSION}"


def desktop_client_version_label():
    return f"v{DESKTOP_CLIENT_VERSION}"


def full_version_text():
    return f"土地資料系統 {version_label()}\n建置日期：{BUILD_DATE}"
