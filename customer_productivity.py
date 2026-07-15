"""Safety, collaboration, workflow, reporting, and map feature UI/services."""

import hashlib
import html
import io
import json
import os
import shutil
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from customer_responsive_dialog import ResponsiveDialog as QDialog

from customer_domain import normalize_match_text
from customer_excel import HEADER_MAP, normalize_header
from customer_word import write_report_docx
from customer_security import decrypt_value


ROLE_LABELS = {"admin": "管理員", "editor": "編輯者", "viewer": "唯讀人員"}


def _set_table_row(table, row_number, values, row_id=None):
    for column, value in enumerate(values):
        item = QTableWidgetItem("" if value is None else str(value))
        if column == 0 and row_id is not None:
            item.setData(Qt.UserRole, int(row_id))
        table.setItem(row_number, column, item)


def _selected_ids(table):
    ids = []
    for index in table.selectionModel().selectedRows():
        item = table.item(index.row(), 0)
        if item is not None and item.data(Qt.UserRole) is not None:
            ids.append(int(item.data(Qt.UserRole)))
    return sorted(set(ids))


def apply_default_import_profile(repository):
    """Install the saved default header aliases into the Excel parser."""
    profiles = [dict(row) for row in repository.list_import_profiles()]
    profile = next((row for row in profiles if row.get("is_default")), None)
    if profile is None:
        return 0
    mapping = json.loads(profile["mapping_json"])
    applied = 0
    for source_header, target_key in mapping.items():
        normalized = normalize_header(source_header)
        if normalized and target_key:
            HEADER_MAP[normalized] = target_key
            applied += 1
    return applied


class ProductivityService:
    ENCRYPTED_BACKUP_MAGIC = b"LCSBACKUP1\n"
    PORTABLE_BACKUP_MAGIC = b"LCSBACKUP2\n"
    BACKUP_KDF_ITERATIONS = 600_000
    OFFSITE_PASSWORD_SETTING = "offsite_backup_password_encrypted"
    OFFSITE_LAST_SYNC_SETTING = "offsite_backup_last_sync_date"

    def __init__(
        self,
        repository,
        database,
        app_directory,
        attachments_directory,
        fernet=None,
    ):
        self.repository = repository
        self.database = database
        self.app_directory = Path(app_directory)
        self.attachments_directory = Path(attachments_directory)
        self.fernet = fernet

    @staticmethod
    def sha256_file(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def save_offsite_backup_password(self, password):
        if self.fernet is None:
            raise ValueError("目前登入工作階段沒有可用的加密金鑰")
        token = self.fernet.encrypt(str(password).encode("utf-8")).decode("ascii")
        self.repository.set_setting(self.OFFSITE_PASSWORD_SETTING, token)

    def load_offsite_backup_password(self):
        token = self.repository.get_setting(self.OFFSITE_PASSWORD_SETTING, "")
        if not token or self.fernet is None:
            return None
        try:
            return self.fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            return None

    def clear_offsite_backup_password(self):
        self.repository.set_setting(self.OFFSITE_PASSWORD_SETTING, "")

    @classmethod
    def _backup_password_fernet(cls, password, salt):
        key = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            bytes(salt),
            cls.BACKUP_KDF_ITERATIONS,
            dklen=32,
        )
        from customer_security import make_fernet

        return make_fernet(urlsafe_b64encode(key))

    def create_full_backup(self, backup_password=None):
        """Create a verified portable ZIP containing database and managed files."""
        self.database.backup_directory.mkdir(parents=True, exist_ok=True)
        database_snapshot = self.database.backup_database(
            "portable-data", compress=False
        )
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_path = self.database.backup_directory / f"system-full-{timestamp}.zip"
        counter = 1
        while archive_path.exists():
            archive_path = self.database.backup_directory / f"system-full-{timestamp}-{counter}.zip"
            counter += 1
        try:
            with zipfile.ZipFile(
                archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                archive.write(database_snapshot, "database/customers.db")
                if self.attachments_directory.exists():
                    for file_path in self.attachments_directory.rglob("*"):
                        if file_path.is_file():
                            archive.write(
                                file_path,
                                Path("attachments") / file_path.relative_to(
                                    self.attachments_directory
                                ),
                            )
                manifest = {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "database": "database/customers.db",
                    "attachments": "attachments/",
                    "application": "LandCustomerSystem",
                }
                archive.writestr(
                    "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
                )
            with zipfile.ZipFile(archive_path, "r") as archive:
                if archive.testzip() is not None:
                    raise ValueError("完整備份 ZIP 驗證失敗")
                if "database/customers.db" not in archive.namelist():
                    raise ValueError("完整備份缺少資料庫")
        finally:
            Path(database_snapshot).unlink(missing_ok=True)
        if backup_password:
            salt = os.urandom(16)
            encrypted_path = archive_path.with_suffix(".lcsbak")
            encrypted_path.write_bytes(
                self.PORTABLE_BACKUP_MAGIC
                + salt
                + self._backup_password_fernet(backup_password, salt).encrypt(
                    archive_path.read_bytes()
                )
            )
            archive_path.unlink()
            archive_path = encrypted_path
            self.verify_full_backup(archive_path, backup_password)
        elif self.fernet is not None:
            encrypted_path = archive_path.with_suffix(".lcsbak")
            encrypted_path.write_bytes(
                self.ENCRYPTED_BACKUP_MAGIC
                + self.fernet.encrypt(archive_path.read_bytes())
            )
            archive_path.unlink()
            archive_path = encrypted_path
            self.verify_full_backup(archive_path)
        self._prune_full_archives(self.database.backup_directory)
        return archive_path

    def _backup_zip_bytes(self, archive_path, backup_password=None):
        archive_path = Path(archive_path)
        payload = archive_path.read_bytes()
        if payload.startswith(self.PORTABLE_BACKUP_MAGIC):
            if not backup_password:
                raise ValueError("請輸入建立這份完整備份時使用的備份密碼")
            salt_start = len(self.PORTABLE_BACKUP_MAGIC)
            salt = payload[salt_start : salt_start + 16]
            try:
                payload = self._backup_password_fernet(
                    backup_password, salt
                ).decrypt(payload[salt_start + 16 :])
            except Exception as exc:
                raise ValueError("備份密碼錯誤或完整備份已損壞") from exc
        elif payload.startswith(self.ENCRYPTED_BACKUP_MAGIC):
            if self.fernet is None:
                raise ValueError("這份完整備份已加密，必須登入原系統才能驗證或還原")
            try:
                payload = self.fernet.decrypt(
                    payload[len(self.ENCRYPTED_BACKUP_MAGIC) :]
                )
            except Exception as exc:
                raise ValueError("完整備份密碼不符或檔案已損壞") from exc
        return payload

    def verify_full_backup(self, archive_path, backup_password=None):
        payload = self._backup_zip_bytes(archive_path, backup_password)
        try:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                if archive.testzip() is not None:
                    raise ValueError("完整備份內容驗證失敗")
                if "database/customers.db" not in archive.namelist():
                    raise ValueError("完整備份缺少資料庫")
        except zipfile.BadZipFile as exc:
            raise ValueError("不是有效的完整備份檔") from exc
        return True

    def restore_full_backup(self, archive_path, backup_password=None):
        """Restore the database and managed attachments from a verified archive."""
        payload = self._backup_zip_bytes(archive_path, backup_password)
        current_backup = self.create_full_backup(backup_password)
        with tempfile.TemporaryDirectory(prefix="land-customer-full-restore-") as temp:
            root = Path(temp)
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                if archive.testzip() is not None:
                    raise ValueError("完整備份內容驗證失敗")
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ValueError("完整備份包含不安全的檔案路徑")
                archive.extractall(root)
            database_path = root / "database" / "customers.db"
            self.database.validate_database_file(database_path)
            safety_database = self.database.restore_database(database_path)
            restored_attachments = root / "attachments"
            restored_attachments.mkdir(parents=True, exist_ok=True)
            temporary_current = self.attachments_directory.with_name(
                f".{self.attachments_directory.name}.restore-old-{datetime.now():%Y%m%d%H%M%S}"
            )
            if self.attachments_directory.exists():
                self.attachments_directory.replace(temporary_current)
            try:
                shutil.copytree(restored_attachments, self.attachments_directory)
            except Exception:
                if temporary_current.exists() and not self.attachments_directory.exists():
                    temporary_current.replace(self.attachments_directory)
                raise
            shutil.rmtree(temporary_current, ignore_errors=True)
            with self.database.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, customer_id, storage_path
                    FROM customer_attachments
                    WHERE storage_path IS NOT NULL AND storage_path <> ''
                    """
                ).fetchall()
                for row in rows:
                    restored_path = (
                        self.attachments_directory
                        / str(row["customer_id"])
                        / Path(row["storage_path"]).name
                    )
                    conn.execute(
                        """
                        UPDATE customer_attachments
                        SET storage_path = ?, file_path = ?
                        WHERE id = ?
                        """,
                        (str(restored_path), str(restored_path), row["id"]),
                    )
        return current_backup, safety_database

    def _prune_full_archives(self, directory):
        directory = Path(directory)
        paths = sorted(
            [*directory.glob("system-full-*.zip"), *directory.glob("system-full-*.lcsbak")],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        keep_count = max(3, int(getattr(self.database, "backup_max_count", 30)))
        retention_days = int(getattr(self.database, "backup_retention_days", 90))
        cutoff = datetime.now().timestamp() - retention_days * 86400 if retention_days else None
        for index, path in enumerate(paths):
            if index < 3:
                continue
            expired = cutoff is not None and path.stat().st_mtime < cutoff
            if index >= keep_count or expired:
                path.unlink(missing_ok=True)

    def sync_backup_targets(self, backup_password=None):
        archive_path = self.create_full_backup(backup_password)
        source_hash = self.sha256_file(archive_path)
        results = []
        for row in self.repository.list_backup_targets():
            target = dict(row)
            if not target.get("enabled"):
                continue
            try:
                directory = Path(target["directory_path"]).expanduser()
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / archive_path.name
                shutil.copy2(archive_path, destination)
                if self.sha256_file(destination) != source_hash:
                    raise ValueError("複製後雜湊驗證不一致")
                self.repository.update_backup_target_result(target["id"])
                self._prune_full_archives(directory)
                results.append((target["name"], "成功", str(destination)))
            except Exception as exc:
                self.repository.update_backup_target_result(target["id"], exc)
                results.append((target["name"], "失敗", str(exc)))
        return archive_path, results
    @staticmethod
    def find_duplicate_pairs(records, ignored_pairs=()):
        ignored_pairs = set(ignored_pairs)
        normalized = []
        buckets = defaultdict(set)
        for record in records:
            item = dict(record)
            item["id"] = int(item["id"])
            values = {
                key: normalize_match_text(item.get(key))
                for key in (
                    "district", "section", "land_number", "registration_order",
                    "owner_name", "external_id", "address",
                )
            }
            normalized.append((item, values))
            for key in (
                ("external_id", values["external_id"]),
                ("owner_land", f"{values['owner_name']}|{values['district']}|{values['section']}|{values['land_number']}"),
                ("address_land", f"{values['address']}|{values['land_number']}"),
            ):
                if key[1].strip("|"):
                    buckets[key].add(item["id"])
        by_id = {item["id"]: (item, values) for item, values in normalized}
        candidate_pairs = set()
        for ids in buckets.values():
            ids = sorted(ids)
            for index, left_id in enumerate(ids):
                for right_id in ids[index + 1 :]:
                    candidate_pairs.add((left_id, right_id))
        results = []
        for left_id, right_id in candidate_pairs:
            if (left_id, right_id) in ignored_pairs:
                continue
            left, a = by_id[left_id]
            right, b = by_id[right_id]
            score = 0
            reasons = []
            if a["external_id"] and a["external_id"] == b["external_id"]:
                score += 50
                reasons.append("身分證相同")
            land_equal = all(
                a[key] and a[key] == b[key]
                for key in ("district", "section", "land_number")
            )
            if land_equal:
                score += 30
                reasons.append("地區地段地號相同")
            if a["owner_name"] and a["owner_name"] == b["owner_name"]:
                score += 20
                reasons.append("姓名相同")
            if a["address"] and a["address"] == b["address"]:
                score += 15
                reasons.append("地址相同")
            if a["registration_order"] and a["registration_order"] == b["registration_order"]:
                score += 10
                reasons.append("序號相同")
            if score >= 50:
                results.append(
                    {
                        "left_id": left_id,
                        "right_id": right_id,
                        "score": min(100, score),
                        "reason": "、".join(reasons),
                        "left_label": f"{left.get('owner_name') or ''}／{left.get('land_number') or ''}",
                        "right_label": f"{right.get('owner_name') or ''}／{right.get('land_number') or ''}",
                    }
                )
        return sorted(results, key=lambda item: (-item["score"], item["left_id"]))

    @staticmethod
    def build_map_html(locations, output_path):
        rows = [dict(row) for row in locations]
        district_counts = defaultdict(int)
        section_counts = defaultdict(int)
        for row in rows:
            district_counts[row.get("district") or "未填地區"] += 1
            section_counts[
                f"{row.get('district') or '未填地區'}／{row.get('section') or '未填地段'}"
            ] += 1
        latitudes = [float(row["latitude"]) for row in rows] or [23.7]
        longitudes = [float(row["longitude"]) for row in rows] or [121.0]
        min_lat, max_lat = min(latitudes), max(latitudes)
        min_lon, max_lon = min(longitudes), max(longitudes)

        def point(row):
            x = 40 + 820 * ((float(row["longitude"]) - min_lon) / (max_lon - min_lon or 1))
            y = 440 - 380 * ((float(row["latitude"]) - min_lat) / (max_lat - min_lat or 1))
            label = " ".join(
                str(row.get(key) or "")
                for key in ("district", "section", "land_number", "owner_name")
            ).strip()
            osm = f"https://www.openstreetmap.org/?mlat={row['latitude']}&mlon={row['longitude']}#map=18/{row['latitude']}/{row['longitude']}"
            title = html.escape(f"{label} ({row['latitude']}, {row['longitude']})")
            return (
                f'<a href="{html.escape(osm)}"><circle cx="{x:.1f}" cy="{y:.1f}" r="7">'
                f"<title>{title}</title></circle></a>"
            )

        point_svg = "".join(point(row) for row in rows)
        district_html = "".join(
            f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
            for name, count in sorted(district_counts.items(), key=lambda item: -item[1])
        )
        section_html = "".join(
            f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
            for name, count in sorted(section_counts.items(), key=lambda item: -item[1])[:50]
        )
        document = f"""<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<title>土地位置與地號視覺化</title><style>
body{{font-family:system-ui;margin:24px;background:#f8fafc;color:#172033}}
.grid{{display:grid;grid-template-columns:2fr 1fr;gap:20px}}section{{background:white;padding:18px;border:1px solid #d8dee9;border-radius:10px}}
svg{{width:100%;height:auto;background:#eef6ff;border:1px solid #b8c8dc}}circle{{fill:#2563eb;stroke:white;stroke-width:2;cursor:pointer}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:7px;text-align:left}}</style>
<h1>土地位置與地號視覺化</h1><p>產生時間：{datetime.now():%Y-%m-%d %H:%M:%S}　定位資料：{len(rows)} 筆。點擊藍點可開啟 OpenStreetMap。</p>
<div class="grid"><section><h2>座標分布</h2><svg viewBox="0 0 900 480" role="img"><path d="M40 440H860M40 440V60" stroke="#8aa0b8" fill="none"/>{point_svg}</svg></section>
<section><h2>地區統計</h2><table><tr><th>地區</th><th>筆數</th></tr>{district_html}</table></section></div>
<section><h2>地段分布</h2><table><tr><th>地區／地段</th><th>筆數</th></tr>{section_html}</table></section></html>"""
        Path(output_path).write_text(document, encoding="utf-8")
        return len(rows)


class OffsiteBackupWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, backup_password):
        super().__init__()
        self.service = service
        self.backup_password = backup_password

    @Slot()
    def run(self):
        try:
            self.finished.emit(
                self.service.sync_backup_targets(self.backup_password)
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class RecycleBinDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = [dict(row) for row in rows]
        self.action = None
        self.setWindowTitle("回收桶")
        self.resize(820, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("刪除的土地資料會連同案件、標籤、附件與聯絡關聯保存在這裡。"))
        self.table = QTableWidget(len(self.rows), 6)
        self.table.setHorizontalHeaderLabels(["ID", "原始ID", "資料", "刪除者", "刪除時間", "類型"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for index, row in enumerate(self.rows):
            _set_table_row(
                self.table, index,
                [row["id"], row["original_id"], row["display_label"], row["deleted_by"], row["deleted_at"], row["entity_type"]],
                row["id"],
            )
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        restore = QPushButton("還原選取")
        purge = QPushButton("永久刪除選取")
        purge_all = QPushButton("清空回收桶")
        close = QPushButton("關閉")
        restore.clicked.connect(lambda: self._request("restore"))
        purge.clicked.connect(lambda: self._request("purge"))
        purge_all.clicked.connect(lambda: self._request("purge_all"))
        close.clicked.connect(self.reject)
        buttons.addWidget(restore)
        buttons.addStretch(1)
        buttons.addWidget(purge)
        buttons.addWidget(purge_all)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _request(self, action):
        if action != "purge_all" and not _selected_ids(self.table):
            QMessageBox.information(self, "尚未選取", "請先選取資料。")
            return
        self.action = action
        self.accept()

    def selected_ids(self):
        return _selected_ids(self.table)


class UndoOperationsDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = [dict(row) for row in rows]
        self.operation_id = None
        self.setWindowTitle("批次操作復原")
        self.resize(760, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("可復原批次修改、Excel 匯入、同地號新增與資料合併。"))
        self.table = QTableWidget(len(self.rows), 6)
        self.table.setHorizontalHeaderLabels(["ID", "操作", "摘要", "執行者", "狀態", "時間"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for index, row in enumerate(self.rows):
            _set_table_row(self.table, index, [row["id"], row["operation_type"], row["summary"], row["actor_username"], row["status"], row["created_at"]], row["id"])
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        undo = buttons.addButton("復原選取操作", QDialogButtonBox.ActionRole)
        undo.clicked.connect(self.request_undo)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request_undo(self):
        ids = _selected_ids(self.table)
        if not ids:
            QMessageBox.information(self, "尚未選取", "請先選取可復原操作。")
            return
        self.operation_id = ids[0]
        self.accept()


class UserManagementDialog(QDialog):
    def __init__(self, repository, data_key, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.data_key = data_key
        self.setWindowTitle("使用者與權限管理")
        self.resize(780, 540)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("管理員可管理帳號；編輯者可修改資料；唯讀人員只能查詢與匯出。"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "帳號", "顯示名稱", "角色", "啟用", "建立時間", "最後登入"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.load_selected)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.username = QLineEdit()
        self.display_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.role = QComboBox()
        for key, label in ROLE_LABELS.items():
            self.role.addItem(label, key)
        self.active = QCheckBox("啟用帳號")
        self.active.setChecked(True)
        form.addRow("帳號", self.username)
        form.addRow("顯示名稱", self.display_name)
        form.addRow("新密碼", self.password)
        form.addRow("角色", self.role)
        form.addRow("狀態", self.active)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        new_mode = QPushButton("新增模式")
        create = QPushButton("新增帳號")
        update = QPushButton("更新角色/狀態")
        reset = QPushButton("重設選取帳號密碼")
        close = QPushButton("關閉")
        new_mode.clicked.connect(self.clear_form)
        create.clicked.connect(self.create_user)
        update.clicked.connect(self.update_user)
        reset.clicked.connect(self.reset_password)
        close.clicked.connect(self.accept)
        buttons.addWidget(new_mode)
        buttons.addWidget(create)
        buttons.addWidget(update)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def clear_form(self):
        self.table.clearSelection()
        self.username.setReadOnly(False)
        self.username.clear()
        self.display_name.clear()
        self.password.clear()
        self.role.setCurrentIndex(max(0, self.role.findData("editor")))
        self.active.setChecked(True)

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_users()]
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            _set_table_row(self.table, index, [row["id"], row["username"], row["display_name"], ROLE_LABELS.get(row["role"], row["role"]), "是" if row["active"] else "否", row["created_at"], row["last_login_at"]], row["id"])

    def selected_user(self):
        ids = _selected_ids(self.table)
        return next((row for row in self.rows if row["id"] in ids), None)

    def load_selected(self):
        row = self.selected_user()
        if not row:
            return
        self.username.setText(row["username"])
        self.username.setReadOnly(True)
        self.display_name.setText(row["display_name"] or "")
        self.role.setCurrentIndex(max(0, self.role.findData(row["role"])))
        self.active.setChecked(bool(row["active"]))
        self.password.clear()

    def create_user(self):
        password = self.password.text()
        if len(password) < 10:
            QMessageBox.warning(self, "密碼太短", "密碼至少需要 10 個字元。")
            return
        try:
            self.repository.create_user(self.username.text(), password, self.role.currentData(), self.data_key, self.display_name.text())
        except Exception as exc:
            QMessageBox.warning(self, "新增失敗", str(exc))
            return
        self.username.setReadOnly(False)
        self.username.clear(); self.display_name.clear(); self.password.clear()
        self.refresh()

    def update_user(self):
        row = self.selected_user()
        if not row:
            return
        try:
            self.repository.update_user(row["id"], display_name=self.display_name.text(), role=self.role.currentData(), active=self.active.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "更新失敗", str(exc))
            return
        self.refresh()

    def reset_password(self):
        row = self.selected_user()
        password = self.password.text()
        if not row or len(password) < 10:
            QMessageBox.warning(self, "資料不足", "請選取帳號並輸入至少 10 個字元的新密碼。")
            return
        self.repository.reset_user_password(row["id"], password, self.data_key)
        self.password.clear()
        QMessageBox.information(self, "完成", "密碼已重設。")


class BackupTargetsDialog(QDialog):
    def __init__(self, repository, service, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.service = service
        self.restore_succeeded = False
        self.setWindowTitle("異地備份")
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("目的地可選 USB、NAS 或 OneDrive 同步資料夾；每次同步都會驗證 SHA-256。"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "名稱", "資料夾", "啟用", "最後成功", "錯誤"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.load_selected)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：辦公室 NAS")
        self.path = QLineEdit()
        browse = QPushButton("瀏覽")
        browse.clicked.connect(self.browse)
        self.enabled = QCheckBox("啟用")
        self.enabled.setChecked(True)
        row.addWidget(QLabel("名稱")); row.addWidget(self.name)
        row.addWidget(QLabel("資料夾")); row.addWidget(self.path, 1); row.addWidget(browse); row.addWidget(self.enabled)
        layout.addLayout(row)
        password_row = QHBoxLayout()
        self.backup_password = QLineEdit()
        self.backup_password.setEchoMode(QLineEdit.Password)
        self.backup_password.setPlaceholderText("至少 10 個字元；災難還原時需要")
        self.backup_password_confirm = QLineEdit()
        self.backup_password_confirm.setEchoMode(QLineEdit.Password)
        self.remember_password = QCheckBox("加密保存在本機並每日自動同步")
        self.remember_password.setChecked(True)
        password_row.addWidget(QLabel("備份密碼"))
        password_row.addWidget(self.backup_password)
        password_row.addWidget(QLabel("確認"))
        password_row.addWidget(self.backup_password_confirm)
        password_row.addWidget(self.remember_password)
        layout.addLayout(password_row)
        buttons = QHBoxLayout()
        save = QPushButton("新增/更新")
        delete = QPushButton("刪除")
        sync = QPushButton("立即建立完整備份並同步")
        restore = QPushButton("還原完整備份")
        close = QPushButton("關閉")
        save.clicked.connect(self.save); delete.clicked.connect(self.delete); sync.clicked.connect(self.sync); restore.clicked.connect(self.restore); close.clicked.connect(self.accept)
        buttons.addWidget(save); buttons.addWidget(delete); buttons.addStretch(1); buttons.addWidget(restore); buttons.addWidget(sync); buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_backup_targets()]
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            _set_table_row(self.table, index, [row["id"], row["name"], row["directory_path"], "是" if row["enabled"] else "否", row["last_success_at"], row["last_error"]], row["id"])

    def selected(self):
        ids = _selected_ids(self.table)
        return next((row for row in self.rows if row["id"] in ids), None)

    def load_selected(self):
        row = self.selected()
        if row:
            self.name.setText(row["name"]); self.path.setText(row["directory_path"]); self.enabled.setChecked(bool(row["enabled"]))

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "選擇異地備份資料夾")
        if path:
            self.path.setText(path)

    def save(self):
        selected = self.selected()
        try:
            self.repository.save_backup_target(self.name.text(), self.path.text(), enabled=self.enabled.isChecked(), target_id=selected["id"] if selected else None)
        except Exception as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh()

    def delete(self):
        row = self.selected()
        if row:
            self.repository.delete_backup_target(row["id"]); self.refresh()

    def sync(self):
        backup_password = self.backup_password.text()
        if len(backup_password) < 10:
            QMessageBox.warning(self, "備份密碼太短", "備份密碼至少需要 10 個字元。")
            return
        if backup_password != self.backup_password_confirm.text():
            QMessageBox.warning(self, "密碼不一致", "兩次輸入的備份密碼不一致。")
            return
        try:
            archive, results = self.service.sync_backup_targets(backup_password)
        except Exception as exc:
            QMessageBox.critical(self, "同步失敗", str(exc)); return
        if self.remember_password.isChecked():
            self.service.save_offsite_backup_password(backup_password)
            if results and all(row[1] == "成功" for row in results):
                self.repository.set_setting(
                    self.service.OFFSITE_LAST_SYNC_SETTING, date.today().isoformat()
                )
            else:
                self.repository.set_setting(
                    self.service.OFFSITE_LAST_SYNC_SETTING, ""
                )
        else:
            self.service.clear_offsite_backup_password()
        detail = "\n".join(f"{name}：{status}（{message}）" for name, status, message in results) or "尚未設定啟用的異地目的地。"
        QMessageBox.information(self, "備份完成", f"完整備份：{archive}\n\n{detail}")
        self.refresh()

    def restore(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "選擇完整備份",
            str(self.service.database.backup_directory),
            "完整備份 (*.lcsbak *.zip);;所有檔案 (*.*)",
        )
        if not file_path:
            return
        backup_password, accepted = QInputDialog.getText(
            self,
            "完整備份密碼",
            "請輸入建立這份完整備份時使用的備份密碼：",
            QLineEdit.Password,
        )
        if not accepted or not backup_password:
            return
        if QMessageBox.question(
            self,
            "還原完整備份",
            "還原會取代目前資料庫與納管附件。系統會先保存目前完整備份，確定繼續嗎？",
        ) != QMessageBox.Yes:
            return
        try:
            current_backup, safety_database = self.service.restore_full_backup(
                file_path, backup_password
            )
        except Exception as exc:
            QMessageBox.critical(self, "還原失敗", str(exc))
            return
        self.restore_succeeded = True
        QMessageBox.information(
            self,
            "還原完成",
            "資料庫與附件已還原，系統將關閉，請重新開啟。\n\n"
            f"還原前完整備份：{current_backup}\n資料庫安全備份：{safety_database}",
        )
        self.accept()


class WorkflowDialog(QDialog):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("案件工作流程與任務看板")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._case_tab(), "案件")
        tabs.addTab(self._task_tab(), "任務")
        layout.addWidget(tabs)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout.addWidget(close)
        self.refresh_all()

    def _case_tab(self):
        widget = QWidget(); layout = QVBoxLayout(widget)
        self.case_table = QTableWidget(0, 9)
        self.case_table.setHorizontalHeaderLabels(["ID", "案件", "狀態", "負責人", "期限", "優先", "下一步", "資料數", "封存"])
        self.case_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.case_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.case_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.case_table.itemSelectionChanged.connect(self.load_case)
        layout.addWidget(self.case_table)
        form = QGridLayout()
        self.case_title = QLineEdit(); self.case_status = QComboBox(); self.case_status.addItems(["進行中", "等待中", "完成", "暫停"])
        self.case_assignee = QLineEdit(); self.case_due = QLineEdit(); self.case_due.setPlaceholderText("YYYY-MM-DD")
        self.case_priority = QComboBox(); self.case_priority.addItems(["一般", "高", "緊急"])
        self.case_next = QLineEdit(); self.case_note = QPlainTextEdit(); self.case_note.setMaximumHeight(70); self.case_archived = QCheckBox("封存")
        fields = [("案件", self.case_title), ("狀態", self.case_status), ("負責人", self.case_assignee), ("期限", self.case_due), ("優先", self.case_priority), ("下一步", self.case_next)]
        for index, (label, control) in enumerate(fields):
            row, col = divmod(index, 2); form.addWidget(QLabel(label), row, col * 2); form.addWidget(control, row, col * 2 + 1)
        form.addWidget(QLabel("備註"), 3, 0); form.addWidget(self.case_note, 3, 1, 1, 3); form.addWidget(self.case_archived, 4, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout(); new = QPushButton("新增模式"); save = QPushButton("儲存案件"); archive = QPushButton("封存/取消封存")
        new.clicked.connect(self.clear_case); save.clicked.connect(self.save_case); archive.clicked.connect(self.toggle_archive)
        buttons.addWidget(new); buttons.addWidget(save); buttons.addWidget(archive); buttons.addStretch(1); layout.addLayout(buttons)
        return widget

    def _task_tab(self):
        widget = QWidget(); layout = QVBoxLayout(widget)
        self.task_table = QTableWidget(0, 8)
        self.task_table.setHorizontalHeaderLabels(["ID", "案件", "任務", "負責人", "期限", "狀態", "優先", "檢查清單"])
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.task_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.task_table.itemSelectionChanged.connect(self.load_task)
        layout.addWidget(self.task_table)
        form = QGridLayout()
        self.task_case = QComboBox(); self.task_title = QLineEdit(); self.task_assignee = QLineEdit(); self.task_due = QLineEdit(); self.task_due.setPlaceholderText("YYYY-MM-DD")
        self.task_status = QComboBox(); self.task_status.addItems(["待處理", "進行中", "等待中", "完成"])
        self.task_priority = QComboBox(); self.task_priority.addItems(["一般", "高", "緊急"])
        self.task_checklist = QPlainTextEdit(); self.task_checklist.setPlaceholderText("每行一個檢查項目"); self.task_checklist.setMaximumHeight(80)
        fields = [("案件", self.task_case), ("任務", self.task_title), ("負責人", self.task_assignee), ("期限", self.task_due), ("狀態", self.task_status), ("優先", self.task_priority)]
        for index, (label, control) in enumerate(fields):
            row, col = divmod(index, 2); form.addWidget(QLabel(label), row, col * 2); form.addWidget(control, row, col * 2 + 1)
        form.addWidget(QLabel("檢查清單"), 3, 0); form.addWidget(self.task_checklist, 3, 1, 1, 3)
        layout.addLayout(form)
        buttons = QHBoxLayout(); new = QPushButton("新增模式"); save = QPushButton("儲存任務"); delete = QPushButton("刪除任務")
        new.clicked.connect(self.clear_task); save.clicked.connect(self.save_task); delete.clicked.connect(self.delete_task)
        buttons.addWidget(new); buttons.addWidget(save); buttons.addWidget(delete); buttons.addStretch(1); layout.addLayout(buttons)
        return widget

    def refresh_all(self):
        self.cases = [dict(row) for row in self.repository.list_cases()]
        self.case_table.setRowCount(len(self.cases))
        for index, row in enumerate(self.cases):
            _set_table_row(self.case_table, index, [row["id"], row["title"], row["status"], row["assigned_to"], row["due_date"], row["priority"], row["next_action"], row["customer_count"], "是" if row["archived_at"] else "否"], row["id"])
        current_case = self.task_case.currentData() if self.task_case.count() else None
        self.task_case.clear()
        for row in self.cases:
            if not row["archived_at"]:
                self.task_case.addItem(row["title"], row["id"])
        if current_case is not None:
            self.task_case.setCurrentIndex(max(0, self.task_case.findData(current_case)))
        self.tasks = [dict(row) for row in self.repository.list_case_tasks()]
        self.task_table.setRowCount(len(self.tasks))
        for index, row in enumerate(self.tasks):
            _set_table_row(self.task_table, index, [row["id"], row["case_title"], row["title"], row["assignee"], row["due_date"], row["status"], row["priority"], row["checklist"]], row["id"])

    def selected_case(self):
        ids = _selected_ids(self.case_table); return next((row for row in self.cases if row["id"] in ids), None)

    def selected_task(self):
        ids = _selected_ids(self.task_table); return next((row for row in self.tasks if row["id"] in ids), None)

    def load_case(self):
        row = self.selected_case()
        if not row: return
        self.case_title.setText(row["title"]); self.case_status.setCurrentText(row["status"]); self.case_assignee.setText(row["assigned_to"] or ""); self.case_due.setText(row["due_date"] or ""); self.case_priority.setCurrentText(row["priority"] or "一般"); self.case_next.setText(row["next_action"] or ""); self.case_note.setPlainText(row["note"] or ""); self.case_archived.setChecked(bool(row["archived_at"]))

    def clear_case(self):
        self.case_table.clearSelection(); self.case_title.clear(); self.case_status.setCurrentText("進行中"); self.case_assignee.clear(); self.case_due.clear(); self.case_priority.setCurrentText("一般"); self.case_next.clear(); self.case_note.clear(); self.case_archived.setChecked(False)

    def save_case(self):
        row = self.selected_case()
        try:
            self.repository.save_case(self.case_title.text(), self.case_status.currentText(), self.case_note.toPlainText(), row["id"] if row else None, assigned_to=self.case_assignee.text(), due_date=self.case_due.text(), priority=self.case_priority.currentText(), next_action=self.case_next.text(), archived=self.case_archived.isChecked())
        except Exception as exc: QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh_all()

    def toggle_archive(self):
        row = self.selected_case()
        if row: self.repository.archive_case(row["id"], not bool(row["archived_at"])); self.refresh_all()

    def load_task(self):
        row = self.selected_task()
        if not row: return
        self.task_case.setCurrentIndex(max(0, self.task_case.findData(row["case_id"]))); self.task_title.setText(row["title"]); self.task_assignee.setText(row["assignee"] or ""); self.task_due.setText(row["due_date"] or ""); self.task_status.setCurrentText(row["status"]); self.task_priority.setCurrentText(row["priority"]); self.task_checklist.setPlainText(row["checklist"] or "")

    def clear_task(self):
        self.task_table.clearSelection(); self.task_title.clear(); self.task_assignee.clear(); self.task_due.clear(); self.task_status.setCurrentText("待處理"); self.task_priority.setCurrentText("一般"); self.task_checklist.clear()

    def save_task(self):
        row = self.selected_task()
        if self.task_case.currentData() is None: QMessageBox.warning(self, "尚無案件", "請先建立案件。"); return
        try:
            self.repository.save_case_task(self.task_case.currentData(), self.task_title.text(), assignee=self.task_assignee.text(), due_date=self.task_due.text(), status=self.task_status.currentText(), priority=self.task_priority.currentText(), checklist=self.task_checklist.toPlainText(), task_id=row["id"] if row else None)
        except Exception as exc: QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh_all()

    def delete_task(self):
        row = self.selected_task()
        if row: self.repository.delete_case_task(row["id"]); self.refresh_all()


class NotificationCenterDialog(QDialog):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.repository.refresh_notifications(date.today().isoformat())
        self.setWindowTitle("通知中心")
        self.resize(850, 500)
        layout = QVBoxLayout(self)
        top = QHBoxLayout(); self.include_read = QCheckBox("包含已讀"); self.include_read.toggled.connect(self.refresh); top.addWidget(QLabel("今日到期與逾期的追蹤、案件及任務會集中顯示。")); top.addStretch(1); top.addWidget(self.include_read); layout.addLayout(top)
        self.table = QTableWidget(0, 7); self.table.setHorizontalHeaderLabels(["ID", "嚴重度", "類型", "標題", "內容", "已讀", "時間"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch); layout.addWidget(self.table)
        buttons = QHBoxLayout(); read = QPushButton("標記已讀"); dismiss = QPushButton("隱藏選取"); refresh = QPushButton("重新整理"); close = QPushButton("關閉"); read.clicked.connect(lambda: self.mark("read")); dismiss.clicked.connect(lambda: self.mark("dismiss")); refresh.clicked.connect(self.refresh); close.clicked.connect(self.accept); buttons.addWidget(read); buttons.addWidget(dismiss); buttons.addStretch(1); buttons.addWidget(refresh); buttons.addWidget(close); layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.repository.refresh_notifications(date.today().isoformat())
        rows = self.repository.list_notifications(self.include_read.isChecked())
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows): _set_table_row(self.table, index, [row["id"], row["severity"], row["category"], row["title"], row["detail"], "是" if row["read_at"] else "否", row["created_at"]], row["id"])

    def mark(self, action):
        self.repository.mark_notifications(_selected_ids(self.table), action); self.refresh()


class ImportProfilesDialog(QDialog):
    def __init__(self, repository, field_labels, parent=None):
        super().__init__(parent)
        self.repository = repository; self.field_labels = dict(field_labels)
        self.setWindowTitle("Excel 匯入設定檔"); self.resize(850, 560)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("每行格式：Excel欄名=系統欄位代碼。儲存為預設後，下一次匯入會自動套用。\n可用代碼：" + "、".join(f"{key}({label})" for key, label in self.field_labels.items())))
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["ID", "名稱", "預設", "欄位對應"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self.load_selected); layout.addWidget(self.table)
        form = QFormLayout(); self.name = QLineEdit(); self.mapping = QPlainTextEdit(); self.mapping.setMaximumHeight(120); self.default = QCheckBox("設為預設"); form.addRow("名稱", self.name); form.addRow("對應", self.mapping); form.addRow("", self.default); layout.addLayout(form)
        buttons = QHBoxLayout(); new = QPushButton("新增模式"); save = QPushButton("儲存"); delete = QPushButton("刪除"); close = QPushButton("關閉"); new.clicked.connect(self.clear); save.clicked.connect(self.save); delete.clicked.connect(self.delete); close.clicked.connect(self.accept); buttons.addWidget(new); buttons.addWidget(save); buttons.addWidget(delete); buttons.addStretch(1); buttons.addWidget(close); layout.addLayout(buttons); self.refresh()

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_import_profiles()]; self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows): _set_table_row(self.table, index, [row["id"], row["name"], "是" if row["is_default"] else "否", "；".join(f"{k}={v}" for k, v in json.loads(row["mapping_json"]).items())], row["id"])

    def selected(self):
        ids = _selected_ids(self.table); return next((row for row in self.rows if row["id"] in ids), None)

    def load_selected(self):
        row = self.selected()
        if row: self.name.setText(row["name"]); self.mapping.setPlainText("\n".join(f"{k}={v}" for k, v in json.loads(row["mapping_json"]).items())); self.default.setChecked(bool(row["is_default"]))

    def clear(self): self.table.clearSelection(); self.name.clear(); self.mapping.clear(); self.default.setChecked(False)

    def parsed_mapping(self):
        result = {}
        for number, line in enumerate(self.mapping.toPlainText().splitlines(), 1):
            if not line.strip(): continue
            if "=" not in line: raise ValueError(f"第 {number} 行缺少 =")
            source, target = (part.strip() for part in line.split("=", 1))
            if target not in self.field_labels: raise ValueError(f"第 {number} 行的系統欄位代碼不存在：{target}")
            result[source] = target
        return result

    def save(self):
        row = self.selected()
        try: self.repository.save_import_profile(self.name.text(), self.parsed_mapping(), profile_id=row["id"] if row else None, is_default=self.default.isChecked()); apply_default_import_profile(self.repository)
        except Exception as exc: QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh()

    def delete(self):
        row = self.selected()
        if row: self.repository.delete_import_profile(row["id"]); self.refresh()


class ReportTemplatesDialog(QDialog):
    def __init__(self, repository, field_labels, parent=None):
        super().__init__(parent)
        self.repository = repository; self.field_labels = dict(field_labels); self.export_template = None
        self.setWindowTitle("報表與列印範本"); self.resize(900, 650)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["ID", "名稱", "報表標題", "欄位"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self.load_selected); layout.addWidget(self.table)
        body = QHBoxLayout(); form = QFormLayout(); self.name = QLineEdit(); self.title = QLineEdit("土地資料報表"); self.header = QPlainTextEdit(); self.header.setMaximumHeight(70); self.footer = QPlainTextEdit(); self.footer.setMaximumHeight(70); form.addRow("範本名稱", self.name); form.addRow("報表標題", self.title); form.addRow("頁首文字", self.header); form.addRow("頁尾文字", self.footer); body.addLayout(form, 2)
        self.fields = QListWidget()
        for key, label in self.field_labels.items(): item = QListWidgetItem(f"{label}（{key}）"); item.setData(Qt.UserRole, key); item.setFlags(item.flags() | Qt.ItemIsUserCheckable); item.setCheckState(Qt.Checked if key in {"district", "section", "land_number", "owner_name", "address"} else Qt.Unchecked); self.fields.addItem(item)
        body.addWidget(self.fields, 1); layout.addLayout(body)
        buttons = QHBoxLayout(); new = QPushButton("新增模式"); save = QPushButton("儲存範本"); delete = QPushButton("刪除"); export = QPushButton("用選取範本匯出勾選資料"); close = QPushButton("關閉"); new.clicked.connect(self.clear); save.clicked.connect(self.save); delete.clicked.connect(self.delete); export.clicked.connect(self.request_export); close.clicked.connect(self.reject); buttons.addWidget(new); buttons.addWidget(save); buttons.addWidget(delete); buttons.addStretch(1); buttons.addWidget(export); buttons.addWidget(close); layout.addLayout(buttons); self.refresh()

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_report_templates()]; self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows): _set_table_row(self.table, index, [row["id"], row["name"], row["title"], "、".join(self.field_labels.get(k, k) for k in json.loads(row["fields_json"]))], row["id"])

    def selected(self): ids = _selected_ids(self.table); return next((row for row in self.rows if row["id"] in ids), None)

    def selected_fields(self): return [self.fields.item(i).data(Qt.UserRole) for i in range(self.fields.count()) if self.fields.item(i).checkState() == Qt.Checked]

    def load_selected(self):
        row = self.selected()
        if not row: return
        self.name.setText(row["name"]); self.title.setText(row["title"]); self.header.setPlainText(row["header_text"] or ""); self.footer.setPlainText(row["footer_text"] or ""); selected = set(json.loads(row["fields_json"]));
        for i in range(self.fields.count()): self.fields.item(i).setCheckState(Qt.Checked if self.fields.item(i).data(Qt.UserRole) in selected else Qt.Unchecked)

    def clear(self): self.table.clearSelection(); self.name.clear(); self.title.setText("土地資料報表"); self.header.clear(); self.footer.clear()

    def save(self):
        row = self.selected()
        try: self.repository.save_report_template(self.name.text(), self.title.text(), self.selected_fields(), header_text=self.header.toPlainText(), footer_text=self.footer.toPlainText(), template_id=row["id"] if row else None)
        except Exception as exc: QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh()

    def delete(self):
        row = self.selected()
        if row: self.repository.delete_report_template(row["id"]); self.refresh()

    def request_export(self):
        row = self.selected()
        if not row: QMessageBox.information(self, "尚未選取", "請先選取報表範本。"); return
        self.export_template = row; self.accept()


class DuplicateFinderDialog(QDialog):
    def __init__(self, pairs, parent=None):
        super().__init__(parent); self.pairs = list(pairs); self.action = None; self.pair = None
        self.setWindowTitle("智慧重複資料檢查"); self.resize(900, 520)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("分數綜合身分證、地號、姓名、地址與序號；合併前仍會顯示既有合併預覽。"))
        self.table = QTableWidget(len(self.pairs), 7); self.table.setHorizontalHeaderLabels(["左ID", "右ID", "相似度", "判斷原因", "左資料", "右資料", "狀態"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for index, pair in enumerate(self.pairs): _set_table_row(self.table, index, [pair["left_id"], pair["right_id"], f"{pair['score']}%", pair["reason"], pair["left_label"], pair["right_label"], "待確認"], pair["left_id"])
        layout.addWidget(self.table); buttons = QHBoxLayout(); merge = QPushButton("合併選取組合"); ignore = QPushButton("忽略此組"); close = QPushButton("關閉"); merge.clicked.connect(lambda: self.request("merge")); ignore.clicked.connect(lambda: self.request("ignore")); close.clicked.connect(self.reject); buttons.addWidget(merge); buttons.addWidget(ignore); buttons.addStretch(1); buttons.addWidget(close); layout.addLayout(buttons)

    def request(self, action):
        row = self.table.currentRow()
        if row < 0: return
        self.action = action; self.pair = self.pairs[row]; self.accept()


class MapLocationsDialog(QDialog):
    def __init__(self, repository, fernet, selected_customer_id=None, parent=None):
        super().__init__(parent); self.repository = repository; self.fernet = fernet; self.export_requested = False
        self.setWindowTitle("地圖與地號視覺化"); self.resize(850, 540)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("輸入座標後可產生離線分布圖；藍點可連到 OpenStreetMap。地址定位可先使用下方搜尋連結。"))
        self.table = QTableWidget(0, 7); self.table.setHorizontalHeaderLabels(["資料ID", "地區", "地段", "地號", "姓名", "緯度", "經度"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self.load_selected); layout.addWidget(self.table)
        row = QHBoxLayout(); self.customer_id = QLineEdit(str(selected_customer_id or "")); self.latitude = QLineEdit(); self.longitude = QLineEdit(); row.addWidget(QLabel("資料ID")); row.addWidget(self.customer_id); row.addWidget(QLabel("緯度")); row.addWidget(self.latitude); row.addWidget(QLabel("經度")); row.addWidget(self.longitude); layout.addLayout(row)
        buttons = QHBoxLayout(); save = QPushButton("儲存座標"); search = QPushButton("用目前資料地址搜尋地圖"); export = QPushButton("產生視覺化 HTML"); close = QPushButton("關閉"); save.clicked.connect(self.save); search.clicked.connect(self.search_address); export.clicked.connect(self.request_export); close.clicked.connect(self.reject); buttons.addWidget(save); buttons.addWidget(search); buttons.addStretch(1); buttons.addWidget(export); buttons.addWidget(close); layout.addLayout(buttons); self.refresh()

    def refresh(self):
        self.rows = [dict(row) for row in self.repository.list_customer_locations()]
        for row in self.rows:
            row["owner_name"] = decrypt_value(self.fernet, row.get("owner_name"))
            row["address"] = decrypt_value(self.fernet, row.get("address"))
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows): _set_table_row(self.table, index, [row["customer_id"], row["district"], row["section"], row["land_number"], row["owner_name"], row["latitude"], row["longitude"]], row["customer_id"])

    def load_selected(self):
        ids = _selected_ids(self.table); row = next((r for r in self.rows if r["customer_id"] in ids), None)
        if row: self.customer_id.setText(str(row["customer_id"])); self.latitude.setText(str(row["latitude"])); self.longitude.setText(str(row["longitude"]))

    def save(self):
        try: self.repository.set_customer_location(int(self.customer_id.text()), float(self.latitude.text()), float(self.longitude.text()))
        except Exception as exc: QMessageBox.warning(self, "儲存失敗", str(exc)); return
        self.refresh()

    def search_address(self):
        try: record = self.repository.get_customer(int(self.customer_id.text()))
        except Exception: record = None
        if record is None: QMessageBox.warning(self, "找不到資料", "請輸入有效的資料 ID。"); return
        address = decrypt_value(self.fernet, record["address"]) or " ".join(str(record[key] or "") for key in ("district", "section", "land_number"))
        QDesktopServices.openUrl(
            QUrl(f"https://www.openstreetmap.org/search?query={quote(str(address))}")
        )

    def request_export(self): self.export_requested = True; self.accept()


def export_report_with_template(file_path, rows, template, field_labels):
    fields = json.loads(template["fields_json"])
    columns = [(key, field_labels.get(key, key)) for key in fields]
    return write_report_docx(file_path, rows, columns, title=template["title"], header_text=template.get("header_text") or "", footer_text=template.get("footer_text") or "")
