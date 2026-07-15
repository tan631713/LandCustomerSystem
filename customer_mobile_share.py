"""Temporary local-network sharing for selected customer rows."""

import html
import io
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from customer_responsive_dialog import ResponsiveDialog as QDialog


def get_lan_ip_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
    except OSError:
        address = socket.gethostbyname(socket.gethostname())
    finally:
        probe.close()
    if not address or address.startswith("127."):
        raise OSError("找不到可供手機連線的區域網路位址。")
    return address


def build_mobile_share_html(rows, columns):
    header_cells = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body_rows = []
    for row in rows:
        cells = []
        for key, _label in columns:
            value = html.escape(str(row["display"].get(key, "") or "")).replace("\n", "<br>")
            cells.append(f"<td>{value}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>土地資料</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #17211a; background: #f4f7f4; font-family: system-ui, sans-serif; }}
header {{ position: sticky; top: 0; z-index: 2; padding: 14px 16px; color: white; background: #176b3a; }}
h1 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
.count {{ margin-top: 3px; font-size: 13px; opacity: .85; }}
.table-wrap {{ width: 100%; overflow: auto; }}
table {{ width: max-content; min-width: 100%; border-collapse: collapse; background: white; }}
th, td {{ max-width: 280px; padding: 10px 12px; border: 1px solid #d8dfda; text-align: left; vertical-align: top; white-space: nowrap; }}
th {{ color: #f8fffa; background: #23824a; font-size: 14px; }}
td {{ font-size: 14px; }}
tr:nth-child(even) td {{ background: #f5faf6; }}
</style>
</head>
<body>
<header><h1>土地資料</h1><div class="count">{len(rows)} 筆</div></header>
<div class="table-wrap"><table><thead><tr>{header_cells}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>
</body>
</html>"""


class TemporaryShareServer:
    def __init__(self, page_html, ip_resolver=None):
        self.token = secrets.token_urlsafe(24)
        page_bytes = page_html.encode("utf-8")
        expected_path = f"/{self.token}"
        ip_resolver = ip_resolver or get_lan_ip_address
        lan_ip = ip_resolver()

        class ShareHandler(BaseHTTPRequestHandler):
            def do_GET(handler_self):
                request_path = handler_self.path.split("?", 1)[0].rstrip("/") or "/"
                if request_path != expected_path:
                    handler_self.send_error(404)
                    return
                handler_self.send_response(200)
                handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                handler_self.send_header("Content-Length", str(len(page_bytes)))
                handler_self.send_header("Cache-Control", "no-store, max-age=0")
                handler_self.send_header("X-Content-Type-Options", "nosniff")
                handler_self.send_header("X-Frame-Options", "DENY")
                handler_self.send_header("Referrer-Policy", "no-referrer")
                handler_self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
                )
                handler_self.send_header("Connection", "close")
                handler_self.end_headers()
                handler_self.wfile.write(page_bytes)

            def log_message(self, _format, *_args):
                return

        self.httpd = ThreadingHTTPServer((lan_ip, 0), ShareHandler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://{lan_ip}:{self.httpd.server_port}/{self.token}"

    def stop(self):
        if self.httpd is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=1)
        self.httpd = None


class MobileShareDialog(QDialog):
    SHARE_DURATION_MS = 10 * 60 * 1000

    def __init__(self, rows, columns, parent=None):
        super().__init__(parent)
        self.share_server = TemporaryShareServer(build_mobile_share_html(rows, columns))
        self.setWindowTitle("傳送到手機")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"已選取 {len(rows)} 筆資料")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignCenter)
        qr_label.setPixmap(self.create_qr_pixmap(self.share_server.url, 320))
        layout.addWidget(qr_label)

        hint = QLabel("手機與電腦連接同一個 Wi-Fi 後掃描；關閉視窗即停止分享。")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        url_label = QLabel(self.share_server.url)
        url_label.setAlignment(Qt.AlignCenter)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_label.setStyleSheet("color: #9ec5fe;")
        layout.addWidget(url_label)

        stop_button = QPushButton("停止分享")
        stop_button.clicked.connect(self.reject)
        layout.addWidget(stop_button)

        self.expiry_timer = QTimer(self)
        self.expiry_timer.setSingleShot(True)
        self.expiry_timer.timeout.connect(self.reject)
        self.expiry_timer.start(self.SHARE_DURATION_MS)

    @staticmethod
    def create_qr_pixmap(value, size):
        import qrcode

        qr_image = qrcode.make(value)
        image_buffer = io.BytesIO()
        qr_image.save(image_buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(image_buffer.getvalue(), "PNG")
        return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def done(self, result):
        self.expiry_timer.stop()
        if self.share_server is not None:
            self.share_server.stop()
            self.share_server = None
        super().done(result)
