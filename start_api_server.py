"""Safe launcher for the local FastAPI service."""

import argparse
import json
import os
import sys

import uvicorn

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.data_sources import create_data_source


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def database_check_failure(exc):
    """Return a useful message without exposing the protected connection string."""
    error_type = type(exc).__name__
    if error_type == "OperationalError" or error_type.startswith("Connection"):
        message = (
            "無法在 5 秒內連線 PostgreSQL。請確認 PostgreSQL 服務正在執行；"
            "若已更換主機或 Windows 使用者，請重新執行「啟動家中伺服器.bat」。"
        )
    elif isinstance(exc, ValueError):
        message = (
            "尚未完成這台 Windows 使用者的 PostgreSQL 設定，"
            "請執行「啟動家中伺服器.bat」完成設定。"
        )
    elif isinstance(exc, OSError):
        message = (
            "無法讀取這台 Windows 使用者保存的 PostgreSQL 設定，"
            "請重新執行「啟動家中伺服器.bat」。"
        )
    else:
        message = "PostgreSQL 檢查失敗，請重新執行「啟動家中伺服器.bat」後再試。"
    return {
        "status": "error",
        "backend": "postgresql",
        "error_type": error_type,
        "message": message,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="啟動土地資料系統本機 API")
    parser.add_argument("--host", default="127.0.0.1", help="預設只允許本機連線")
    parser.add_argument("--port", type=int, default=8732)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="使用已由 setup_local_postgresql.py 安全儲存的 PostgreSQL 設定",
    )
    parser.add_argument("--lan", action="store_true", help="監聽區域網路介面")
    parser.add_argument("--prefer-vpn", action="store_true", help="優先顯示 NetBird 私人 VPN IP")
    parser.add_argument(
        "--allow-insecure-lan",
        action="store_true",
        help="明確允許未加密的區域網路測試（不可用於外網）",
    )
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    parser.add_argument("--check", action="store_true", help="只檢查資料庫與設定")
    parser.add_argument(
        "--setup-postgresql",
        action="store_true",
        help="在家中主機建立或修復本機 PostgreSQL 專用資料庫設定",
    )
    parser.add_argument("--setup-https", action="store_true", help="建立或更新區網 HTTPS 憑證後結束")
    parser.add_argument(
        "--install-iphone-certificate",
        action="store_true",
        help="啟動只提供公開 CA 憑證的 iPhone 安裝頁",
    )
    parser.add_argument("--certificate-port", type=int, default=8733)
    parser.add_argument("--backup", action="store_true", help="建立 PostgreSQL 與附件備份後結束")
    parser.add_argument("--backup-if-due-hours", type=int, default=0)
    parser.add_argument("--backup-label", default="manual")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.setup_postgresql:
        from setup_local_postgresql import main as setup_postgresql_main

        return setup_postgresql_main([])
    if args.setup_https:
        from setup_local_https import create_local_https_certificate

        print(
            json.dumps(
                create_local_https_certificate(port=args.port, prefer_vpn=args.prefer_vpn),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.install_iphone_certificate:
        from install_iphone_certificate_server import main as install_certificate_main

        certificate_arguments = ["--port", str(args.certificate_port)]
        if args.prefer_vpn:
            certificate_arguments.append("--prefer-vpn")
        return install_certificate_main(certificate_arguments)
    if args.backup or args.backup_if_due_hours:
        from backup_postgresql import main as backup_main

        backup_arguments = ["--label", args.backup_label]
        if args.backup_if_due_hours:
            backup_arguments.extend(["--if-due-hours", str(args.backup_if_due_hours)])
        return backup_main(backup_arguments)
    if args.postgres:
        os.environ["CUSTOMER_API_BACKEND"] = "postgresql"

    if args.check:
        try:
            settings = ApiSettings.from_env()
            source = create_data_source(settings)
            result = source.health()
        except Exception as exc:
            print(
                json.dumps(database_check_failure(exc), ensure_ascii=False, indent=2),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    settings = ApiSettings.from_env()
    source = create_data_source(settings)

    host = "0.0.0.0" if args.lan else args.host
    is_public_listener = host not in LOOPBACK_HOSTS
    has_tls = bool(args.ssl_certfile and args.ssl_keyfile)
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        parser.error("SSL 憑證與私鑰必須同時提供")
    if is_public_listener and not has_tls and not args.allow_insecure_lan:
        parser.error(
            "區域網路登入會傳送敏感資料；請設定 SSL，或僅在可信 Wi-Fi 測試時加上 "
            "--allow-insecure-lan。絕對不可直接開放到網際網路。"
        )

    app = create_app(settings=settings, data_source=source)
    if args.lan:
        from setup_local_https import lan_ipv4_addresses

        scheme = "https" if has_tls else "http"
        addresses = lan_ipv4_addresses(prefer_vpn=args.prefer_vpn)
        if addresses:
            print("iPhone 行動版（請使用手機目前所在網路對應的 IP）：")
            for address in addresses:
                print(f"  {scheme}://{address}:{args.port}/mobile/")
            print(f"API 文件：{scheme}://{addresses[0]}:{args.port}/docs")
        else:
            print("找不到可供手機連線的區域網路 IPv4；請先讓電腦連上 Wi-Fi 或熱點。")
        if args.prefer_vpn:
            print("私人 VPN 模式：請優先使用 100.x 開頭的 NetBird 網址。")
        print("若使用手機熱點，請先以系統管理員執行防火牆設定檔；熱點在 Windows 常屬公用網路。")
        print("外出使用時請透過私人 VPN，不要在路由器開放 API 或 PostgreSQL 連接埠。")
    uvicorn.run(
        app,
        host=host,
        port=args.port,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
