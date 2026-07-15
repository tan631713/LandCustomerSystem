"""Safe helpers for opening local paths and web links from Qt."""

from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox


_WEB_SCHEMES = frozenset({"http", "https"})


def _is_windows_drive_path(value):
    return len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in {"/", "\\"}


def open_local_path(path, parent=None, *, item_label="檔案"):
    path = Path(path)
    if not path.exists():
        QMessageBox.warning(parent, f"找不到{item_label}", f"找不到{item_label}：\n{path}")
        return False
    try:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
    except Exception as exc:
        QMessageBox.critical(parent, f"無法開啟{item_label}", f"開啟{item_label}時發生問題：\n{exc}")
        return False
    if not opened:
        QMessageBox.warning(
            parent,
            f"無法開啟{item_label}",
            f"Windows 沒有成功開啟{item_label}：\n{path}",
        )
        return False
    return True


def open_path_or_web_url(target, parent=None, *, item_label="檔案"):
    """Open a local path or a validated HTTP(S) URL with the system handler."""
    value = str(target or "").strip()
    if not value:
        QMessageBox.warning(parent, f"無法開啟{item_label}", f"{item_label}路徑或網址不可空白。")
        return False

    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold()
    if scheme in _WEB_SCHEMES:
        if not parsed.netloc:
            QMessageBox.warning(parent, f"無法開啟{item_label}", f"{item_label}網址格式不正確：\n{value}")
            return False
        try:
            opened = QDesktopServices.openUrl(QUrl(value))
        except Exception as exc:
            QMessageBox.critical(parent, f"無法開啟{item_label}", f"開啟{item_label}連結時發生問題：\n{exc}")
            return False
        if not opened:
            QMessageBox.warning(
                parent,
                f"無法開啟{item_label}",
                f"Windows 沒有成功開啟{item_label}連結：\n{value}",
            )
            return False
        return True

    if scheme and not _is_windows_drive_path(value):
        QMessageBox.warning(
            parent,
            f"無法開啟{item_label}",
            f"基於安全考量，外部連結只允許 http 或 https 網址：\n{value}",
        )
        return False

    return open_local_path(value, parent, item_label=item_label)
