"""Serve only the public local CA certificate to an iPhone on the same LAN."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from setup_local_https import (
    certificate_paths,
    create_local_https_certificate,
    lan_ipv4_addresses,
    local_ip_address,
)


HTML = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>安裝土地資料系統憑證</title>
<style>body{font-family:-apple-system,sans-serif;max-width:620px;margin:40px auto;padding:20px;line-height:1.7}
a{display:block;background:#0f766e;color:white;text-align:center;padding:15px;border-radius:12px;text-decoration:none;font-weight:700}</style>
</head><body><h1>土地資料系統</h1><p>此頁只提供公開 CA 憑證，不會傳送土地或地主資料。</p>
<a href="/land-customer-local-ca.cer">下載並安裝憑證</a>
<ol><li>下載後到「設定」完成描述檔安裝。</li><li>到「設定 → 一般 → 關於本機 → 憑證信任設定」。</li>
<li>開啟「Land Customer System Local CA」完整信任。</li></ol></body></html>"""


def handler_class(certificate_bytes: bytes):
    class CertificateHandler(BaseHTTPRequestHandler):
        server_version = "LandCustomerCertificate/1"

        def do_GET(self):
            if self.path in {"/", "/index.html"}:
                payload = HTML.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif self.path.split("?", 1)[0] == "/land-customer-local-ca.cer":
                payload = certificate_bytes
                content_type = "application/x-x509-ca-cert"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if content_type.startswith("application/"):
                self.send_header("Content-Disposition", 'attachment; filename="land-customer-local-ca.cer"')
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            print(f"憑證下載：{self.client_address[0]} - {format % args}")

    return CertificateHandler


def build_parser():
    parser = argparse.ArgumentParser(description="讓 iPhone 安裝土地資料系統公開 CA 憑證")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--prefer-vpn", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    create_local_https_certificate(prefer_vpn=args.prefer_vpn)
    public_certificate = certificate_paths().ca_certificate_der.read_bytes()
    server = ThreadingHTTPServer((args.host, args.port), handler_class(public_certificate))
    addresses = lan_ipv4_addresses(prefer_vpn=args.prefer_vpn)
    address = addresses[0] if addresses else local_ip_address()
    print(f"請用 iPhone Safari 開啟：http://{address}:{args.port}/")
    print("安裝完成後按 Ctrl+C 停止此臨時憑證下載服務。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
