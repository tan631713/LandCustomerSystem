"""Validation helpers for the configurable company-client server address."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


API_PORT = 8732
NETBIRD_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
SERVER_API_URL_SETTING_KEY = "company_server_api_url"


def normalize_server_api_url(value: str) -> str:
    """Return a canonical HTTPS API URL from a user-entered NetBird IPv4 address."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("請輸入家中伺服器的 NetBird IP。")

    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme.casefold() != "https":
        raise ValueError("伺服器連線必須使用 HTTPS。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("請只輸入 IP，不要加入帳號、密碼或其他參數。")
    if parsed.path not in {"", "/"}:
        raise ValueError("請只輸入 IP，不要加入網址路徑。")
    if not parsed.hostname:
        raise ValueError("伺服器 IP 格式不正確。")

    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("伺服器 IP 格式不正確。") from exc
    if address.version != 4 or address not in NETBIRD_IPV4_NETWORK:
        raise ValueError("請輸入 100.64.0.0/10 範圍內的 NetBird IPv4 位址。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("伺服器連接埠格式不正確。") from exc
    if port not in {None, API_PORT}:
        raise ValueError(f"公司客戶端固定使用 HTTPS {API_PORT} 連接埠。")
    return f"https://{address}:{API_PORT}"


def server_ip_from_api_url(value: str) -> str:
    """Extract the display IP from a validated API URL."""

    return str(urlparse(normalize_server_api_url(value)).hostname)
