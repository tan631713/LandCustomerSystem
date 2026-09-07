"""Application release metadata."""

APP_VERSION = "1.9.41"
DESKTOP_CLIENT_VERSION = "1.9.71"
BUILD_DATE = "2026-09-07"
DESKTOP_CLIENT_BUILD_DATE = "2026-09-07"
MOBILE_ASSET_VERSION = 32


def version_label():
    return f"v{APP_VERSION}"


def desktop_client_version_label():
    return f"v{DESKTOP_CLIENT_VERSION}"


def full_version_text():
    return f"土地資料系統 {version_label()}\n建置日期：{BUILD_DATE}"
