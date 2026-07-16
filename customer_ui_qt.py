import json
import os
import sqlite3
import sys
from base64 import b64decode, b64encode
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from customer_auth import AuthDialog, configure_auth_dialog, validate_new_password
from customer_backup_status import BackupManagementDialog, BackupStatusMixin, format_storage_size
from customer_database import (
    AUTO_BACKUP_LIMIT,
    DEFAULT_BACKUP_MAX_COUNT,
    DEFAULT_BACKUP_RETENTION_DAYS,
    SQLITE_TIMEOUT_SECONDS,
    CustomerDatabase,
)
from customer_dialogs import (
    BatchEditDialog,
    BatchEditPreviewDialog,
    ChangePasswordDialog,
    DashboardDialog,
    FontSizeDialog,
    FollowUpListDialog,
    FollowUpReminderDialog,
    HelpDialog,
    DataQualityDialog,
    DataQualityRulesDialog,
    OperationLogDialog,
    RecordHistoryDialog,
    WatchlistDialog,
    configure_dialogs,
)
from customer_extra_dialogs import (
    ApplyTemplateDialog,
    AttachmentDialog,
    BatchCustomerCustomValuesDialog,
    BatchCustomerTagsDialog,
    CaseManagementDialog,
    CaseSelectDialog,
    ContactLogDialog,
    CustomFieldManagementDialog,
    CustomerCustomValuesDialog,
    CustomerTagsDialog,
    HealthCheckDialog,
    MergeRecordsDialog,
    TagManagementDialog,
    TextTemplateDialog,
)
from customer_domain import (
    calculate_ping,
    calculate_total_declared_value,
    format_number,
    format_number_text,
    format_ping_text,
    mask_identity_text,
    normalize_text,
    parse_number,
    parse_rights_scope,
    split_rights_scope,
)
from customer_excel import ExcelService
from customer_export_controller import ExportControllerMixin, configure_export_controller
from customer_import_controller import ImportControllerMixin, configure_import_controller
from customer_desktop import open_local_path
from customer_desktop_api import (
    DEFAULT_API_URL,
    DesktopApiClient,
    DesktopApiError,
    DesktopApiRecordRepository,
)
from customer_error_handler import get_error_log_path
from customer_fields import LAND_FIELDS
from customer_messages import (
    backup_management_failure_message,
    database_save_failure_message,
    password_change_failure_message,
    password_changed_message,
    restore_confirmation_message,
    restore_failure_message,
    restore_success_message,
    startup_backup_notice,
)
from customer_models import RecordTableModel, configure_table_model
from customer_quality import (
    DEFAULT_QUALITY_RULE_KEYS,
    inspect_customer_quality,
    quality_issue_signature,
)
from customer_repository import CustomerRepository, normalize_watch_name
from customer_productivity import (
    BackupTargetsDialog,
    DuplicateFinderDialog,
    ImportProfilesDialog,
    MapLocationsDialog,
    NotificationCenterDialog,
    OffsiteBackupWorker,
    ProductivityService,
    RecycleBinDialog,
    ReportTemplatesDialog,
    UndoOperationsDialog,
    UserManagementDialog,
    WorkflowDialog,
    apply_default_import_profile,
    export_report_with_template,
)
from customer_search_controller import SearchControllerMixin, configure_search_controller
from customer_search_presets import SearchPresetMixin, configure_search_presets
from customer_ui_state import UiStateMixin, configure_ui_state
from customer_version import full_version_text, version_label
from customer_security import (
    ENCRYPTED_FIELDS,
    decrypt_value,
    encrypt_record,
    encrypt_value,
    make_fernet,
)
from PySide6.QtCore import QEvent, QPoint, QItemSelectionModel, QThread, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)


def get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
RESOURCE_DIR = get_resource_dir()
DESKTOP_BACKEND_ENV = "LAND_CUSTOMER_DESKTOP_BACKEND"
DESKTOP_API_URL_ENV = "LAND_CUSTOMER_API_URL"
REMOTE_DESKTOP_MODE = (
    os.environ.get(DESKTOP_BACKEND_ENV, "").strip().casefold() == "postgresql"
)
if REMOTE_DESKTOP_MODE:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    CLIENT_SETTINGS_DIR = local_app_data / "LandCustomerSystem" / "desktop-client"
    DB_PATH = CLIENT_SETTINGS_DIR / "desktop-client-settings.db"
    BACKUP_DIR = CLIENT_SETTINGS_DIR / "unused-backups"
else:
    CLIENT_SETTINGS_DIR = APP_DIR
    DB_PATH = APP_DIR / "customers.db"
    BACKUP_DIR = APP_DIR / "backups"
SCHEMA_PATH = RESOURCE_DIR / "schema.sql"
SEED_PATH = RESOURCE_DIR / "seed.sql"
APP_ICON_PATH = RESOURCE_DIR / "assets" / "app_icon.png"
ATTACHMENTS_DIR = APP_DIR / "attachments"
ADMIN_USERNAME = "admin"
DATABASE = CustomerDatabase(
    DB_PATH,
    BACKUP_DIR,
    timeout_seconds=SQLITE_TIMEOUT_SECONDS,
    auto_backup_limit=AUTO_BACKUP_LIMIT,
)
DEFAULT_FONT_SIZE_KEY = "medium"
TABLE_PREFS_SETTING_KEY = "table_preferences"
ADVANCED_SEARCH_SETTING_KEY = "advanced_search"
SAVED_SEARCHES_SETTING_KEY = "saved_searches"
CHECKED_RECORDS_SETTING_KEY = "checked_record_ids"
SELECTED_RECORD_SETTING_KEY = "selected_record_id"
IGNORED_QUALITY_ISSUES_SETTING_KEY = "ignored_quality_issue_signatures"
QUALITY_RULES_SETTING_KEY = "quality_rule_keys"
READONLY_MODE_SETTING_KEY = "readonly_mode"
BACKUP_COMPRESSION_SETTING_KEY = "backup_compression_enabled"
BACKUP_RETENTION_DAYS_SETTING_KEY = "backup_retention_days"
BACKUP_MAX_COUNT_SETTING_KEY = "backup_max_count"
FONT_SIZE_OPTIONS = [
    ("small", "小", 10),
    ("medium", "中", 11),
    ("large", "大", 13),
    ("xlarge", "特大", 15),
]
ROW_COLOR_CHECKED = QColor("#1e3a5f")
ROW_COLOR_WATCHLIST = QColor("#5b2230")
ROW_COLOR_OVERDUE = QColor("#7c2d12")
ROW_COLOR_NOTE = QColor("#564113")
ROW_TEXT_COLOR = QColor("#f8fafc")
SEARCH_HIGHLIGHT_COLOR = QColor("#6b4f1d")


def compact_summary_text(value, max_length=120):
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def attachment_display_name(value):
    text = " ".join(str(value or "").split())
    if "（" in text and text.endswith("）"):
        description = text.rsplit("（", 1)[0].strip()
        if description:
            return compact_summary_text(description, 48)

    parsed = urlsplit(text)
    if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
        return f"外部連結（{parsed.netloc}）"

    file_name = text.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    return compact_summary_text(file_name or "附件", 48)


def format_attachment_summary(attachment_names, attachment_count=0):
    items = [item.strip() for item in str(attachment_names or "").split("；") if item.strip()]
    labels = [attachment_display_name(item) for item in items[:2]]
    if len(items) > 2:
        labels.append("…")

    try:
        count = max(0, int(attachment_count or 0))
    except (TypeError, ValueError):
        count = 0
    count = count or len(items)

    names_text = "、".join(label for label in labels if label)
    if names_text and count:
        return f"{names_text}，共 {count} 個"
    if names_text:
        return names_text
    if count:
        return f"{count} 個"
    return ""


MANAGEMENT_FIELDS = [
    ("case_names", "案件"),
    ("tag_names", "標籤"),
    ("attachment_count", "附件數"),
    ("attachment_names", "附件內容"),
    ("custom_values", "自訂欄位"),
    ("last_contact", "最近聯絡"),
    ("next_follow_up", "下次追蹤"),
    ("follow_up_status", "追蹤狀態"),
]
REPOSITORY = CustomerRepository(
    DATABASE,
    SCHEMA_PATH,
    SEED_PATH,
    LAND_FIELDS,
    admin_username=ADMIN_USERNAME,
)

TABLE_COLUMNS = [
    ("checked", "選取"),
    ("rowid", "系統ID"),
    *LAND_FIELDS,
    *MANAGEMENT_FIELDS,
]

FILTERABLE_FIELDS = [
    ("all", "全部欄位"),
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("owner_name", "姓名"),
    ("external_id", "身分證"),
    ("address", "地址"),
    ("registration_reason", "原因"),
    ("note", "備註"),
    ("visit_log", "出訪記錄"),
    *MANAGEMENT_FIELDS,
]

SORTABLE_FIELDS = [
    ("rowid", "系統ID"),
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("area", "面積/m2"),
    ("declared_value", "公告現值"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("ping", "坪數"),
    ("total_declared_value", "總現值/元"),
    ("owner_name", "姓名"),
    ("case_names", "案件"),
    ("tag_names", "標籤"),
    ("attachment_count", "附件數"),
    ("last_contact", "最近聯絡"),
    ("next_follow_up", "下次追蹤"),
    ("follow_up_status", "追蹤狀態"),
]

TABLE_BATCH_SIZE = 200
ASYNC_SEARCH_THRESHOLD = 500
SELECTION_SAVE_DELAY_MS = 300

TABLE_WIDTHS = {
    "checked": 52,
    "rowid": 68,
    "district": 95,
    "section": 100,
    "registration_order": 82,
    "land_number": 105,
    "area": 84,
    "declared_value": 110,
    "numerator": 70,
    "denominator": 70,
    "ping": 84,
    "total_declared_value": 130,
    "owner_name": 112,
    "external_id": 124,
    "address": 320,
    "registration_reason": 120,
    "note": 160,
    "visit_log": 140,
    "case_names": 150,
    "tag_names": 150,
    "attachment_count": 72,
    "attachment_names": 240,
    "custom_values": 220,
    "last_contact": 170,
    "next_follow_up": 105,
    "follow_up_status": 95,
}

ADVANCED_SEARCH_FIELDS = [
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("owner_name", "姓名"),
    ("external_id", "身分證"),
    ("address", "地址"),
    ("registration_reason", "原因"),
    ("note", "備註"),
    ("visit_log", "出訪記錄"),
    *MANAGEMENT_FIELDS,
]

BATCH_EDITABLE_FIELDS = [
    ("district", "地區"),
    ("section", "地段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("area", "面積/m2"),
    ("declared_value", "公告現值"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("ping", "坪數"),
    ("owner_name", "姓名"),
    ("external_id", "身分證"),
    ("address", "地址"),
    ("registration_reason", "原因"),
    ("note", "備註"),
    ("visit_log", "出訪記錄"),
]

def encode_table_preferences(preferences):
    return json.dumps(preferences, ensure_ascii=False)


def decode_table_preferences(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def sanitize_saved_searches(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        criteria = item.get("criteria")
        if not name or not isinstance(criteria, dict):
            continue
        cleaned.append({"name": name, "criteria": criteria})
    return cleaned


def connect():
    return DATABASE.connect()


def validate_database_file(database_path):
    return DATABASE.validate_database_file(database_path)


def backup_database(label="auto", source_path=None):
    return DATABASE.backup_database(label, source_path)


def restore_database(source_path):
    return DATABASE.restore_database(source_path)


def prune_auto_backups(limit=AUTO_BACKUP_LIMIT):
    return DATABASE.prune_auto_backups(limit)


def ensure_daily_backup():
    return DATABASE.ensure_daily_backup()


def get_columns(conn, table_name):
    return REPOSITORY.get_columns(conn, table_name)


def init_settings_db(conn):
    return REPOSITORY.init_settings_db(conn)


def get_setting(setting_key, default=None):
    return REPOSITORY.get_setting(setting_key, default)


def set_setting(setting_key, setting_value):
    return REPOSITORY.set_setting(setting_key, setting_value)


def _setting_integer(setting_key, default, minimum):
    try:
        return max(minimum, int(get_setting(setting_key, str(default))))
    except (TypeError, ValueError):
        return default


def load_backup_policy():
    return {
        "compress_backups": get_setting(BACKUP_COMPRESSION_SETTING_KEY, "1") != "0",
        "retention_days": _setting_integer(
            BACKUP_RETENTION_DAYS_SETTING_KEY,
            DEFAULT_BACKUP_RETENTION_DAYS,
            0,
        ),
        "max_count": _setting_integer(
            BACKUP_MAX_COUNT_SETTING_KEY,
            DEFAULT_BACKUP_MAX_COUNT,
            3,
        ),
    }


def save_backup_policy(policy):
    REPOSITORY.set_settings(
        {
            BACKUP_COMPRESSION_SETTING_KEY: "1" if policy["compress_backups"] else "0",
            BACKUP_RETENTION_DAYS_SETTING_KEY: str(policy["retention_days"]),
            BACKUP_MAX_COUNT_SETTING_KEY: str(policy["max_count"]),
        }
    )


def apply_backup_policy(database=None):
    policy = load_backup_policy()
    (database or DATABASE).configure_backup_policy(**policy)
    return policy


def load_ignored_quality_issue_signatures():
    raw_value = get_setting(IGNORED_QUALITY_ISSUES_SETTING_KEY, "[]")
    try:
        values = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if value}


def save_ignored_quality_issue_signatures(signatures):
    normalized = sorted({str(signature) for signature in signatures if signature})
    set_setting(IGNORED_QUALITY_ISSUES_SETTING_KEY, json.dumps(normalized, ensure_ascii=False))


def load_quality_rule_keys():
    raw_value = get_setting(QUALITY_RULES_SETTING_KEY, "")
    try:
        values = json.loads(raw_value) if raw_value else list(DEFAULT_QUALITY_RULE_KEYS)
    except (TypeError, json.JSONDecodeError):
        return list(DEFAULT_QUALITY_RULE_KEYS)
    allowed = set(DEFAULT_QUALITY_RULE_KEYS)
    selected = [str(value) for value in values if str(value) in allowed] if isinstance(values, list) else []
    return selected or list(DEFAULT_QUALITY_RULE_KEYS)


def save_quality_rule_keys(rule_keys):
    allowed = set(DEFAULT_QUALITY_RULE_KEYS)
    selected = [str(rule_key) for rule_key in rule_keys if str(rule_key) in allowed]
    set_setting(
        QUALITY_RULES_SETTING_KEY,
        json.dumps(selected or list(DEFAULT_QUALITY_RULE_KEYS), ensure_ascii=False),
    )


def get_font_size_option(font_size_key):
    for key, label, point_size in FONT_SIZE_OPTIONS:
        if key == font_size_key:
            return key, label, point_size
    return next(option for option in FONT_SIZE_OPTIONS if option[0] == DEFAULT_FONT_SIZE_KEY)


def get_saved_font_size_key():
    value = get_setting("font_size", DEFAULT_FONT_SIZE_KEY)
    return get_font_size_option(value)[0]


def apply_font_size(app, font_size_key):
    _key, _label, point_size = get_font_size_option(font_size_key)
    font = QFont(app.font())
    font.setPointSize(point_size)
    app.setFont(font)
    return font


def apply_app_style(app):
    app.setStyleSheet(
        """
        QWidget {
            background-color: #232323;
            color: #f3f4f6;
            selection-background-color: #365d8d;
            selection-color: #f9fafb;
        }
        QFrame#formFrame {
            background-color: #262626;
            border: 1px solid #343434;
            border-radius: 10px;
        }
        QFrame#listFrame {
            background-color: transparent;
            border: none;
        }
        QMainWindow, QDialog {
            background-color: #232323;
        }
        QLabel {
            color: #e5e7eb;
        }
        QLineEdit, QPlainTextEdit, QComboBox, QTableView, QTableWidget {
            background-color: #2d2d2d;
            color: #f9fafb;
            border: 1px solid #454545;
            border-radius: 6px;
        }
        QLineEdit, QComboBox {
            min-height: 28px;
            padding: 4px 8px;
        }
        QPlainTextEdit {
            padding: 6px 8px;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QTableView:focus, QTableWidget:focus {
            border: 1px solid #6ea8ff;
        }
        QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {
            background-color: #262626;
            color: #cbd5e1;
        }
        QPushButton {
            background-color: #3a3a3a;
            color: #f9fafb;
            border: 1px solid #565656;
            border-radius: 6px;
            padding: 6px 14px;
            min-height: 30px;
        }
        QPushButton:hover {
            background-color: #464646;
            border-color: #6b7280;
        }
        QPushButton:pressed {
            background-color: #2f2f2f;
        }
        QComboBox::drop-down {
            border: none;
            width: 22px;
        }
        QComboBox QAbstractItemView, QMenu {
            background-color: #2c2c2c;
            color: #f9fafb;
            border: 1px solid #454545;
            selection-background-color: #365d8d;
            selection-color: #ffffff;
            outline: none;
        }
        QMenu::item {
            padding: 7px 18px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #365d8d;
        }
        QMenu::separator {
            height: 1px;
            background: #424242;
            margin: 6px 10px;
        }
        QHeaderView::section {
            background-color: #353535;
            color: #f3f4f6;
            border: 1px solid #4a4a4a;
            padding: 6px 8px;
            font-weight: 600;
        }
        QTableView {
            gridline-color: #3e3e3e;
            alternate-background-color: #292929;
        }
        QTableView::item {
            padding: 4px 6px;
        }
        QTableView::item:selected, QTableWidget::item:selected {
            background-color: #88addc;
            color: #111827;
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: #262626;
            border: none;
            margin: 0px;
        }
        QScrollBar:vertical {
            width: 12px;
        }
        QScrollBar:horizontal {
            height: 12px;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #555555;
            border-radius: 5px;
            min-height: 28px;
            min-width: 28px;
        }
        QScrollBar::handle:hover {
            background: #6b7280;
        }
        QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
            background: none;
            border: none;
        }
        QSplitter::handle {
            background-color: #303030;
            width: 1px;
        }
        """
    )


def init_watchlist_db(conn):
    return REPOSITORY.init_watchlist_db(conn)


def init_operation_log_db(conn):
    return REPOSITORY.init_operation_log_db(conn)


def log_operation(action_type, summary, detail=None):
    if desktop_api_requested():
        return None
    return REPOSITORY.log_operation(action_type, summary, detail)


def get_operation_logs(limit=300):
    return REPOSITORY.get_operation_logs(limit)


def get_watchlist_entries():
    return REPOSITORY.get_watchlist_entries()


def replace_watchlist_entries(entries):
    return REPOSITORY.replace_watchlist_entries(entries)


def find_watchlist_match(name):
    return REPOSITORY.find_watchlist_match(name)


def init_auth_db(conn):
    return REPOSITORY.init_auth_db(conn)


def has_admin_user():
    return REPOSITORY.has_admin_user()


def create_admin_user(password):
    return REPOSITORY.create_admin_user(password)


def authenticate_user(username, password):
    return REPOSITORY.authenticate_user(username, password)


def change_admin_password(current_password, new_password):
    return REPOSITORY.change_admin_password(current_password, new_password)


def migrate_db(conn):
    return REPOSITORY.migrate_db(conn)


def init_db():
    return REPOSITORY.init_db()


def init_remote_client_settings():
    """Create only device preferences for API mode, never local customer tables."""

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATABASE.connect() as conn:
        REPOSITORY.init_settings_db(conn)


configure_auth_dialog(
    admin_username=ADMIN_USERNAME,
    create_admin_user=create_admin_user,
    authenticate_user=authenticate_user,
)


EXCEL_SERVICE = ExcelService(
    LAND_FIELDS,
    parse_number,
    split_rights_scope,
    format_number_text,
    calculate_ping,
    format_ping_text,
    calculate_total_declared_value,
)

configure_dialogs(
    APP_DIR=APP_DIR,
    LAND_FIELDS=LAND_FIELDS,
    FONT_SIZE_OPTIONS=FONT_SIZE_OPTIONS,
    DEFAULT_FONT_SIZE_KEY=DEFAULT_FONT_SIZE_KEY,
    ADVANCED_SEARCH_FIELDS=ADVANCED_SEARCH_FIELDS,
    BATCH_EDITABLE_FIELDS=BATCH_EDITABLE_FIELDS,
    ROW_TEXT_COLOR=ROW_TEXT_COLOR,
    get_operation_logs=get_operation_logs,
    get_watchlist_entries=get_watchlist_entries,
    replace_watchlist_entries=replace_watchlist_entries,
    write_error_rows=EXCEL_SERVICE.write_error_rows,
)
configure_table_model(
    TABLE_COLUMNS=TABLE_COLUMNS,
    TABLE_BATCH_SIZE=TABLE_BATCH_SIZE,
    ROW_COLOR_CHECKED=ROW_COLOR_CHECKED,
    ROW_COLOR_WATCHLIST=ROW_COLOR_WATCHLIST,
    ROW_COLOR_OVERDUE=ROW_COLOR_OVERDUE,
    ROW_COLOR_NOTE=ROW_COLOR_NOTE,
    ROW_TEXT_COLOR=ROW_TEXT_COLOR,
    SEARCH_HIGHLIGHT_COLOR=SEARCH_HIGHLIGHT_COLOR,
)
configure_search_controller(
    TABLE_COLUMNS=TABLE_COLUMNS,
    TABLE_BATCH_SIZE=TABLE_BATCH_SIZE,
    ASYNC_SEARCH_THRESHOLD=ASYNC_SEARCH_THRESHOLD,
    ROW_COLOR_CHECKED=ROW_COLOR_CHECKED,
    ROW_COLOR_WATCHLIST=ROW_COLOR_WATCHLIST,
    ROW_COLOR_OVERDUE=ROW_COLOR_OVERDUE,
    ROW_COLOR_NOTE=ROW_COLOR_NOTE,
)
configure_ui_state(
    TABLE_COLUMNS=TABLE_COLUMNS,
    TABLE_WIDTHS=TABLE_WIDTHS,
    TABLE_PREFS_SETTING_KEY=TABLE_PREFS_SETTING_KEY,
    CHECKED_RECORDS_SETTING_KEY=CHECKED_RECORDS_SETTING_KEY,
    SELECTED_RECORD_SETTING_KEY=SELECTED_RECORD_SETTING_KEY,
    GET_SETTING=get_setting,
    SET_SETTING=set_setting,
    ENCODE_PREFERENCES=encode_table_preferences,
    DECODE_PREFERENCES=decode_table_preferences,
)
configure_search_presets(
    ADVANCED_SEARCH_SETTING_KEY=ADVANCED_SEARCH_SETTING_KEY,
    SAVED_SEARCHES_SETTING_KEY=SAVED_SEARCHES_SETTING_KEY,
    SET_SETTING=set_setting,
    ENCODE_PREFERENCES=encode_table_preferences,
)
configure_export_controller(
    APP_DIR=APP_DIR,
    TABLE_COLUMNS=TABLE_COLUMNS,
)
configure_import_controller(
    LAND_FIELDS=LAND_FIELDS,
    EXCEL_SERVICE=EXCEL_SERVICE,
)


def require_login(setup_mode=None):
    if setup_mode is None:
        setup_mode = not has_admin_user()
    dialog = AuthDialog(setup_mode=bool(setup_mode))
    if dialog.exec() == QDialog.Accepted:
        return dialog.encryption_key
    return None


def desktop_api_requested():
    return os.environ.get(DESKTOP_BACKEND_ENV, "").strip().casefold() in {
        "api",
        "postgres",
        "postgresql",
    }


def configure_api_authentication(api_client):
    def authenticate_api_user(username, password):
        try:
            api_client.login(username, password)
        except DesktopApiError:
            return None
        # API records arrive as plaintext over the authenticated local/VPN
        # connection.  The desktop UI still expects a Fernet key for its
        # in-memory form pipeline, so use an ephemeral session-only key rather
        # than depending on the retired SQLite user store.
        return Fernet.generate_key()

    configure_auth_dialog(
        admin_username=ADMIN_USERNAME,
        create_admin_user=create_admin_user,
        authenticate_user=authenticate_api_user,
    )


class LandApp(
    BackupStatusMixin,
    UiStateMixin,
    SearchPresetMixin,
    ImportControllerMixin,
    ExportControllerMixin,
    SearchControllerMixin,
    QMainWindow,
):
    def __init__(
        self,
        encryption_key,
        startup_backup_path=None,
        record_repository=None,
        api_mode=False,
        current_user=None,
    ):
        super().__init__()
        self.repository = REPOSITORY
        self.record_repository = record_repository or self.repository
        self.api_mode = bool(api_mode)
        self.database = DATABASE
        self.encryption_key = encryption_key
        self.fernet = make_fernet(encryption_key)
        self.current_user = dict(
            current_user
            or self.repository.last_authenticated_user
            or {"username": ADMIN_USERNAME, "display_name": ADMIN_USERNAME, "role": "admin"}
        )
        self.repository.current_actor = self.current_user.get("username")
        self.productivity = ProductivityService(
            self.repository, self.database, APP_DIR, ATTACHMENTS_DIR, self.fernet
        )
        apply_backup_policy(self.database)
        mode_label = " [PostgreSQL 正式版]" if self.api_mode else ""
        self.setWindowTitle(f"土地資料系統 {version_label()}{mode_label}")
        self.resize(1280, 760)
        self.setMinimumSize(1080, 660)
        self.setStyleSheet("QMenu { padding: 6px; }")

        self.current_font_size_key = get_saved_font_size_key()
        self.startup_backup_path = startup_backup_path
        self.selected_record_id = None
        self.checked_record_ids = set()
        self.persisted_selection_snapshot = None
        self.restore_selection_state()
        self.persisted_selection_snapshot = self.selection_state_snapshot()
        self.selection_save_timer = QTimer(self)
        self.selection_save_timer.setSingleShot(True)
        self.selection_save_timer.setInterval(SELECTION_SAVE_DELAY_MS)
        self.selection_save_timer.timeout.connect(self.persist_selection_state)
        self.watchlist_names = set()
        self.show_checked_only = False
        self.fields = {}
        self.field_widgets = {}
        self.show_full_external_id = False
        self.current_external_id_plain = ""
        self.advanced_search_criteria = decode_table_preferences(get_setting(ADVANCED_SEARCH_SETTING_KEY, "")) or {}
        self.saving_table_preferences = False

        self.search_input = None
        self.filter_field_combo = None
        self.sort_field_combo = None
        self.sort_order_combo = None
        self.saved_searches = sanitize_saved_searches(
            decode_table_preferences(get_setting(SAVED_SEARCHES_SETTING_KEY, ""))
        )
        self.data_button = None
        self.external_id_button = None
        self.tools_button = None
        self.settings_button = None
        self.table_view = None
        self.table_model = None
        self.record_menu = None
        self.data_menu = None
        self.tools_menu = None
        self.tool_submenus = {}
        self.settings_menu = None
        self.management_summary_label = None
        self.show_checked_only_action = None
        self.readonly_mode_action = None
        self.excel_thread = None
        self.excel_worker = None
        self.record_search_request_id = 0
        self.record_searches = {}
        self.offsite_backup_thread = None
        self.offsite_backup_worker = None

        self.create_layout()
        if self.api_mode:
            self.configure_api_mode_ui()
        else:
            self.setup_backup_status()
            self.setup_notification_status()
            self.setup_offsite_backup()
        self.refresh_records()
        self.apply_saved_font_size()
        if self.startup_backup_path:
            QTimer.singleShot(0, self.show_startup_backup_notice)

    def create_layout(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        root.addLayout(toolbar)

        toolbar.addWidget(QLabel("搜尋"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入關鍵字")
        self.search_input.returnPressed.connect(self.refresh_records)
        self.search_input.setMinimumWidth(300)
        toolbar.addWidget(self.search_input)

        search_button = QPushButton("搜尋")
        search_button.clicked.connect(lambda _checked=False: self.refresh_records())
        toolbar.addWidget(search_button)

        toolbar.addWidget(QLabel("篩選"))
        self.filter_field_combo = QComboBox()
        for key, label in FILTERABLE_FIELDS:
            self.filter_field_combo.addItem(label, key)
        self.filter_field_combo.setCurrentIndex(0)
        self.filter_field_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
        toolbar.addWidget(self.filter_field_combo)

        toolbar.addWidget(QLabel("排序"))
        self.sort_field_combo = QComboBox()
        for key, label in SORTABLE_FIELDS:
            self.sort_field_combo.addItem(label, key)
        self.sort_field_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
        toolbar.addWidget(self.sort_field_combo)

        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItem("新到舊", "desc")
        self.sort_order_combo.addItem("舊到新", "asc")
        self.sort_order_combo.currentIndexChanged.connect(lambda _index: self.refresh_records())
        toolbar.addWidget(self.sort_order_combo)

        clear_button = QPushButton("清除")
        clear_button.clicked.connect(self.clear_search)
        toolbar.addWidget(clear_button)

        self.data_button = QPushButton("資料")
        self.data_button.clicked.connect(self.show_data_menu)
        toolbar.addWidget(self.data_button)

        self.tools_button = QPushButton("工具")
        self.tools_button.clicked.connect(self.show_tools_menu)
        toolbar.addWidget(self.tools_button)

        self.settings_button = QPushButton("設定")
        self.settings_button.clicked.connect(self.show_settings_menu)
        toolbar.addWidget(self.settings_button)

        toolbar.addStretch(1)

        new_button = QPushButton("新增資料")
        new_button.clicked.connect(self.new_record)
        toolbar.addWidget(new_button)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        list_frame = QFrame()
        list_frame.setObjectName("listFrame")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(list_frame)

        form_frame = QFrame()
        form_frame.setObjectName("formFrame")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(18, 14, 18, 18)
        form_layout.setSpacing(12)
        splitter.addWidget(form_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.create_table(list_layout)
        self.create_form(form_layout)

    def create_table(self, parent_layout):
        self.table_model = RecordTableModel(self.on_checked_state_changed, self)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QTableView.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setWordWrap(False)
        self.table_view.setSortingEnabled(False)
        self.table_view.setShowGrid(True)
        self.table_view.setCornerButtonEnabled(False)
        self.table_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.verticalHeader().setDefaultSectionSize(28)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionsMovable(True)
        self.table_view.horizontalHeader().sectionResized.connect(self.on_table_section_resized)
        self.table_view.horizontalHeader().sectionMoved.connect(self.on_table_section_moved)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_record_menu)
        copy_action = QAction("複製", self.table_view)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.copy_selected_cells)
        self.table_view.addAction(copy_action)

        self.saving_table_preferences = True
        try:
            for column_index, (key, _label) in enumerate(TABLE_COLUMNS):
                self.table_view.setColumnWidth(column_index, TABLE_WIDTHS[key])

            self.apply_table_preferences()
        finally:
            self.saving_table_preferences = False

        self.table_view.selectionModel().currentRowChanged.connect(self.on_record_select)
        self.table_view.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected: self.update_selection_status()
        )
        self.table_view.clicked.connect(self.on_table_clicked)

        parent_layout.addWidget(self.table_view)

        self.record_menu = QMenu(self)
        check_selected_context_action = QAction("勾選目前選取列", self)
        check_selected_context_action.triggered.connect(self.check_selected_rows)
        self.record_menu.addAction(check_selected_context_action)
        uncheck_selected_context_action = QAction("取消選取列勾選", self)
        uncheck_selected_context_action.triggered.connect(self.uncheck_selected_rows)
        self.record_menu.addAction(uncheck_selected_context_action)
        self.record_menu.addSeparator()
        context_case_manage_action = QAction("案件管理", self)
        context_case_manage_action.triggered.connect(self.manage_cases)
        self.record_menu.addAction(context_case_manage_action)
        context_assign_case_action = QAction("加入選取／勾選資料到案件", self)
        context_assign_case_action.triggered.connect(self.assign_checked_records_to_case)
        self.record_menu.addAction(context_assign_case_action)
        context_remove_case_action = QAction("從案件移除選取／勾選資料", self)
        context_remove_case_action.triggered.connect(self.remove_selected_records_from_case)
        self.record_menu.addAction(context_remove_case_action)
        self.record_menu.addSeparator()
        context_tags_action = QAction("設定標籤", self)
        context_tags_action.triggered.connect(self.edit_customer_tags)
        self.record_menu.addAction(context_tags_action)
        context_batch_tags_action = QAction("批量設定標籤", self)
        context_batch_tags_action.triggered.connect(self.batch_edit_customer_tags)
        self.record_menu.addAction(context_batch_tags_action)
        context_contact_action = QAction("聯絡紀錄", self)
        context_contact_action.triggered.connect(self.manage_contact_logs)
        self.record_menu.addAction(context_contact_action)
        context_follow_up_action = QAction("設定追蹤提醒", self)
        context_follow_up_action.triggered.connect(self.edit_follow_up_reminder)
        self.record_menu.addAction(context_follow_up_action)
        context_attachment_action = QAction("附件管理", self)
        context_attachment_action.triggered.connect(self.manage_attachments)
        self.record_menu.addAction(context_attachment_action)
        self.record_menu.addSeparator()
        delete_action = QAction("刪除資料", self)
        delete_action.triggered.connect(self.delete_record)
        self.record_menu.addAction(delete_action)

        self.api_preview_context_actions = (
            context_case_manage_action,
            context_assign_case_action,
            context_remove_case_action,
            context_tags_action,
            context_batch_tags_action,
            context_contact_action,
            context_follow_up_action,
            context_attachment_action,
        )
        self.api_preview_supported_context_actions = (
            context_case_manage_action,
            context_assign_case_action,
            context_remove_case_action,
            context_tags_action,
            context_batch_tags_action,
            context_contact_action,
            context_follow_up_action,
            context_attachment_action,
        )
        self.api_preview_unavailable_context_actions = ()

        self.data_menu = QMenu(self)
        batch_add_action = QAction("同地號批量新增", self)
        batch_add_action.triggered.connect(self.batch_add_shared_land_records)
        self.data_menu.addAction(batch_add_action)
        self.data_menu.addSeparator()
        import_action = QAction("匯入 .xlsx", self)
        import_action.triggered.connect(self.import_xlsx)
        self.data_menu.addAction(import_action)
        import_profiles_action = QAction("Excel 匯入設定檔", self)
        import_profiles_action.triggered.connect(self.manage_import_profiles)
        self.data_menu.addAction(import_profiles_action)
        export_action = QAction("匯出 Excel", self)
        export_action.triggered.connect(self.export_xlsx)
        self.data_menu.addAction(export_action)
        export_selected_action = QAction("匯出選取資料", self)
        export_selected_action.triggered.connect(self.export_selected_xlsx)
        self.data_menu.addAction(export_selected_action)
        export_selected_word_action = QAction("匯出選取 Word", self)
        export_selected_word_action.triggered.connect(self.export_selected_word)
        self.data_menu.addAction(export_selected_word_action)
        report_templates_action = QAction("報表與列印範本", self)
        report_templates_action.triggered.connect(self.manage_report_templates)
        self.data_menu.addAction(report_templates_action)
        self.data_menu.addSeparator()
        share_mobile_action = QAction("傳送選取資料到手機", self)
        share_mobile_action.triggered.connect(self.share_selected_to_mobile)
        self.data_menu.addAction(share_mobile_action)
        self.api_preview_supported_data_actions = (
            batch_add_action,
            import_action,
            export_action,
            export_selected_action,
            export_selected_word_action,
            share_mobile_action,
        )
        self.api_preview_unavailable_data_actions = (
            import_profiles_action,
            report_templates_action,
        )

        self.tools_menu = QMenu(self)

        notification_action = QAction("通知中心", self)
        notification_action.triggered.connect(self.show_notification_center)
        self.tools_menu.addAction(notification_action)
        workflow_action = QAction("案件工作流程與任務看板", self)
        workflow_action.triggered.connect(self.show_workflow_board)
        self.tools_menu.addAction(workflow_action)
        recycle_action = QAction("回收桶", self)
        recycle_action.triggered.connect(self.show_recycle_bin)
        self.tools_menu.addAction(recycle_action)
        undo_action = QAction("復原批次操作", self)
        undo_action.triggered.connect(self.show_undo_operations)
        self.tools_menu.addAction(undo_action)
        self.tools_menu.addSeparator()

        advanced_search_action = QAction("進階搜尋", self)
        advanced_search_action.setStatusTip("開啟多條件搜尋。")
        advanced_search_action.triggered.connect(self.open_advanced_search)
        self.tools_menu.addAction(advanced_search_action)

        data_quality_action = QAction("資料品質檢查", self)
        data_quality_action.setStatusTip("檢查缺漏、數字格式、分母為 0 與疑似重複。")
        data_quality_action.triggered.connect(self.run_data_quality_check)
        self.tools_menu.addAction(data_quality_action)

        dashboard_action = QAction("資料統計儀表板", self)
        dashboard_action.setStatusTip("查看總筆數、面積、現值、地區/地段與追蹤統計。")
        dashboard_action.triggered.connect(self.show_dashboard)
        self.tools_menu.addAction(dashboard_action)
        self.tools_menu.addSeparator()

        search_menu = QMenu("搜尋與條件", self.tools_menu)
        self.tools_menu.addMenu(search_menu)
        self.tool_submenus["搜尋與條件"] = search_menu
        save_search_action = QAction("儲存目前搜尋條件", self)
        save_search_action.triggered.connect(self.save_current_search)
        search_menu.addAction(save_search_action)
        load_search_action = QAction("開啟常用條件", self)
        load_search_action.triggered.connect(self.open_saved_searches)
        search_menu.addAction(load_search_action)

        single_record_menu = QMenu("單筆資料工具", self.tools_menu)
        self.tools_menu.addMenu(single_record_menu)
        self.tool_submenus["單筆資料工具"] = single_record_menu
        toggle_external_id_action = QAction("顯示/隱藏身分證", self)
        toggle_external_id_action.triggered.connect(self.toggle_external_id_visibility)
        single_record_menu.addAction(toggle_external_id_action)
        follow_up_action = QAction("設定追蹤提醒", self)
        follow_up_action.triggered.connect(self.edit_follow_up_reminder)
        single_record_menu.addAction(follow_up_action)
        record_history_action = QAction("查看修改歷史", self)
        record_history_action.triggered.connect(self.show_record_history)
        single_record_menu.addAction(record_history_action)
        contact_log_action = QAction("聯絡紀錄", self)
        contact_log_action.triggered.connect(self.manage_contact_logs)
        single_record_menu.addAction(contact_log_action)
        attachment_action = QAction("附件管理", self)
        attachment_action.triggered.connect(self.manage_attachments)
        single_record_menu.addAction(attachment_action)
        customer_tags_action = QAction("設定標籤", self)
        customer_tags_action.triggered.connect(self.edit_customer_tags)
        single_record_menu.addAction(customer_tags_action)
        customer_custom_values_action = QAction("設定自訂欄位", self)
        customer_custom_values_action.triggered.connect(self.edit_customer_custom_values)
        single_record_menu.addAction(customer_custom_values_action)
        apply_template_action = QAction("套用快速範本", self)
        apply_template_action.triggered.connect(self.apply_text_template)
        single_record_menu.addAction(apply_template_action)

        batch_menu = QMenu("勾選與批量操作", self.tools_menu)
        self.tools_menu.addMenu(batch_menu)
        self.tool_submenus["勾選與批量操作"] = batch_menu
        self.show_checked_only_action = QAction("僅顯示勾選資料", self)
        self.show_checked_only_action.setCheckable(True)
        self.show_checked_only_action.toggled.connect(self.toggle_checked_only)
        batch_menu.addAction(self.show_checked_only_action)
        batch_menu.addSeparator()
        check_selected_action = QAction("勾選目前選取列", self)
        check_selected_action.triggered.connect(self.check_selected_rows)
        batch_menu.addAction(check_selected_action)
        uncheck_selected_action = QAction("取消選取列勾選", self)
        uncheck_selected_action.triggered.connect(self.uncheck_selected_rows)
        batch_menu.addAction(uncheck_selected_action)
        check_visible_action = QAction("勾選目前搜尋結果", self)
        check_visible_action.triggered.connect(self.check_visible_records)
        batch_menu.addAction(check_visible_action)
        uncheck_visible_action = QAction("取消目前搜尋結果勾選", self)
        uncheck_visible_action.triggered.connect(self.uncheck_visible_records)
        batch_menu.addAction(uncheck_visible_action)
        invert_visible_action = QAction("反轉目前搜尋結果勾選", self)
        invert_visible_action.triggered.connect(self.invert_visible_checked_records)
        batch_menu.addAction(invert_visible_action)
        clear_checked_action = QAction("取消全部勾選", self)
        clear_checked_action.triggered.connect(self.clear_checked_selection)
        batch_menu.addAction(clear_checked_action)
        batch_menu.addSeparator()
        batch_edit_action = QAction("批次修改勾選資料", self)
        batch_edit_action.triggered.connect(self.batch_edit_checked_records)
        batch_menu.addAction(batch_edit_action)
        merge_action = QAction("合併勾選兩筆資料", self)
        merge_action.triggered.connect(self.merge_checked_records)
        batch_menu.addAction(merge_action)
        assign_case_action = QAction("加入勾選資料到案件", self)
        assign_case_action.triggered.connect(self.assign_checked_records_to_case)
        batch_menu.addAction(assign_case_action)
        remove_case_action = QAction("從案件移除選取資料", self)
        remove_case_action.triggered.connect(self.remove_selected_records_from_case)
        batch_menu.addAction(remove_case_action)
        batch_tags_action = QAction("批量設定標籤", self)
        batch_tags_action.triggered.connect(self.batch_edit_customer_tags)
        batch_menu.addAction(batch_tags_action)
        batch_custom_values_action = QAction("批量設定自訂欄位", self)
        batch_custom_values_action.triggered.connect(self.batch_edit_custom_values)
        batch_menu.addAction(batch_custom_values_action)

        management_menu = QMenu("案件與分類管理", self.tools_menu)
        self.tools_menu.addMenu(management_menu)
        self.tool_submenus["案件與分類管理"] = management_menu
        case_manage_action = QAction("案件管理", self)
        case_manage_action.triggered.connect(self.manage_cases)
        management_menu.addAction(case_manage_action)
        tag_manage_action = QAction("標籤管理", self)
        tag_manage_action.triggered.connect(self.manage_tags)
        management_menu.addAction(tag_manage_action)
        custom_field_manage_action = QAction("自訂欄位管理", self)
        custom_field_manage_action.triggered.connect(self.manage_custom_fields)
        management_menu.addAction(custom_field_manage_action)
        template_manage_action = QAction("快速範本管理", self)
        template_manage_action.triggered.connect(self.manage_text_templates)
        management_menu.addAction(template_manage_action)

        report_menu = QMenu("檢查與報表", self.tools_menu)
        self.tools_menu.addMenu(report_menu)
        self.tool_submenus["檢查與報表"] = report_menu
        follow_up_list_action = QAction("追蹤提醒清單", self)
        follow_up_list_action.triggered.connect(self.show_follow_up_list)
        report_menu.addAction(follow_up_list_action)
        health_check_action = QAction("系統健康檢查", self)
        health_check_action.triggered.connect(self.show_health_check)
        report_menu.addAction(health_check_action)
        duplicate_action = QAction("智慧重複資料檢查", self)
        duplicate_action.triggered.connect(self.show_duplicate_finder)
        report_menu.addAction(duplicate_action)
        map_action = QAction("地圖與地號視覺化", self)
        map_action.triggered.connect(self.show_map_visualization)
        report_menu.addAction(map_action)

        danger_menu = QMenu("危險操作", self.tools_menu)
        self.tools_menu.addMenu(danger_menu)
        self.tool_submenus["危險操作"] = danger_menu
        delete_checked_action = QAction("刪除已勾選資料", self)
        delete_checked_action.triggered.connect(self.delete_checked_records)
        danger_menu.addAction(delete_checked_action)
        delete_all_action = QAction("刪除全部資料", self)
        delete_all_action.triggered.connect(self.delete_all_records)
        danger_menu.addAction(delete_all_action)
        encrypt_action = QAction("加密既有資料", self)
        encrypt_action.triggered.connect(self.encrypt_existing_records)
        danger_menu.addAction(encrypt_action)

        self.settings_menu = QMenu(self)
        watchlist_action = QAction("注意名單管理", self)
        watchlist_action.triggered.connect(self.manage_watchlist)
        self.settings_menu.addAction(watchlist_action)
        operation_log_action = QAction("操作記錄", self)
        operation_log_action.triggered.connect(self.show_operation_logs)
        self.settings_menu.addAction(operation_log_action)
        user_management_action = QAction("使用者與權限", self)
        user_management_action.triggered.connect(self.manage_users)
        self.settings_menu.addAction(user_management_action)
        font_size_action = QAction("字體大小", self)
        font_size_action.triggered.connect(self.change_font_size)
        self.settings_menu.addAction(font_size_action)
        column_visibility_action = QAction("欄位顯示", self)
        column_visibility_action.triggered.connect(self.change_column_visibility)
        self.settings_menu.addAction(column_visibility_action)
        self.readonly_mode_action = QAction("唯讀模式", self)
        self.readonly_mode_action.setCheckable(True)
        self.readonly_mode_action.setChecked(self.is_readonly_mode())
        self.readonly_mode_action.toggled.connect(self.toggle_readonly_mode)
        self.settings_menu.addAction(self.readonly_mode_action)
        change_password_action = QAction("修改密碼", self)
        change_password_action.triggered.connect(self.change_password)
        self.settings_menu.addAction(change_password_action)
        self.settings_menu.addSeparator()
        backup_status_action = QAction("備份狀態", self)
        backup_status_action.triggered.connect(self.show_backup_status)
        self.settings_menu.addAction(backup_status_action)
        backup_management_action = QAction("備份管理", self)
        backup_management_action.triggered.connect(self.manage_backups)
        self.settings_menu.addAction(backup_management_action)
        external_backup_action = QAction("異地完整備份", self)
        external_backup_action.triggered.connect(self.manage_external_backups)
        self.settings_menu.addAction(external_backup_action)
        backup_now_action = QAction("立即備份", self)
        backup_now_action.triggered.connect(self.backup_now)
        self.settings_menu.addAction(backup_now_action)
        restore_backup_action = QAction("還原備份", self)
        restore_backup_action.triggered.connect(self.restore_backup)
        self.settings_menu.addAction(restore_backup_action)
        open_backup_action = QAction("開啟備份資料夾", self)
        open_backup_action.triggered.connect(self.open_backup_folder)
        self.settings_menu.addAction(open_backup_action)
        attachment_check_action = QAction("檢查納管附件", self)
        attachment_check_action.triggered.connect(self.verify_managed_attachments)
        self.settings_menu.addAction(attachment_check_action)
        self.settings_menu.addSeparator()
        help_action = QAction("使用說明", self)
        help_action.triggered.connect(self.show_help)
        self.settings_menu.addAction(help_action)
        about_action = QAction("關於系統", self)
        about_action.triggered.connect(self.show_about)
        self.settings_menu.addAction(about_action)

        self.api_supported_tool_actions = (
            advanced_search_action,
            save_search_action,
            load_search_action,
            toggle_external_id_action,
            follow_up_action,
            contact_log_action,
            attachment_action,
            customer_tags_action,
            self.show_checked_only_action,
            check_selected_action,
            uncheck_selected_action,
            check_visible_action,
            uncheck_visible_action,
            invert_visible_action,
            clear_checked_action,
            assign_case_action,
            remove_case_action,
            batch_tags_action,
            case_manage_action,
            tag_manage_action,
            data_quality_action,
            dashboard_action,
            follow_up_list_action,
            health_check_action,
        )
        self.api_unavailable_tool_actions = (
            notification_action,
            workflow_action,
            recycle_action,
            undo_action,
            record_history_action,
            customer_custom_values_action,
            apply_template_action,
            batch_edit_action,
            merge_action,
            batch_custom_values_action,
            custom_field_manage_action,
            template_manage_action,
            duplicate_action,
            map_action,
            delete_checked_action,
            delete_all_action,
            encrypt_action,
        )
        self.api_supported_settings_actions = (
            font_size_action,
            column_visibility_action,
            self.readonly_mode_action,
            help_action,
            about_action,
        )
        self.api_unavailable_settings_actions = (
            watchlist_action,
            operation_log_action,
            user_management_action,
            change_password_action,
            backup_status_action,
            backup_management_action,
            external_backup_action,
            backup_now_action,
            restore_backup_action,
            open_backup_action,
            attachment_check_action,
        )

    def configure_api_mode_ui(self):
        unavailable_text = "這項本機資料庫功能尚未提供遠端版本"
        self.data_button.setEnabled(True)
        self.data_button.setToolTip("遠端資料可批量新增、匯入與匯出")
        for button in (self.tools_button, self.settings_button):
            button.setEnabled(True)
            button.setToolTip("可使用的遠端工具已開放；灰色項目仍僅限家中主機")
        for action in getattr(self, "api_preview_supported_data_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_preview_unavailable_data_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        for action in getattr(self, "api_supported_tool_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_unavailable_tool_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        for action in getattr(self, "api_supported_settings_actions", ()):
            action.setEnabled(True)
        for action in getattr(self, "api_unavailable_settings_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        for action in getattr(self, "api_preview_unavailable_context_actions", ()):
            action.setEnabled(False)
            action.setStatusTip(unavailable_text)
        self.statusBar().showMessage(
            "PostgreSQL 正式版：資料由 FastAPI 寫入 PostgreSQL，可使用查詢、編輯、匯入、案件、標籤、附件、聯絡與追蹤。"
        )

    # Keep the old method name for extensions created during the preview stage.
    configure_api_preview_ui = configure_api_mode_ui

    def setup_notification_status(self):
        self.notification_status_button = QPushButton("通知 0")
        self.notification_status_button.setFlat(True)
        self.notification_status_button.setToolTip("開啟通知中心")
        self.notification_status_button.clicked.connect(self.show_notification_center)
        self.statusBar().addPermanentWidget(self.notification_status_button)
        self.notification_timer = QTimer(self)
        self.notification_timer.setInterval(60 * 60 * 1000)
        self.notification_timer.timeout.connect(self.refresh_notification_status)
        self.notification_timer.start()
        self.refresh_notification_status()

    def refresh_notification_status(self):
        try:
            self.repository.refresh_notifications(date.today().isoformat())
            count = len(self.repository.list_notifications())
        except Exception:
            count = 0
        if getattr(self, "notification_status_button", None) is not None:
            self.notification_status_button.setText(f"通知 {count}")
            color = "#fbbf24" if count else "#86efac"
            self.notification_status_button.setStyleSheet(f"color: {color}; padding: 2px 8px;")
        return count

    def setup_offsite_backup(self):
        self.offsite_backup_timer = QTimer(self)
        self.offsite_backup_timer.setInterval(6 * 60 * 60 * 1000)
        self.offsite_backup_timer.timeout.connect(self.run_scheduled_offsite_backup)
        self.offsite_backup_timer.start()
        QTimer.singleShot(30_000, self.run_scheduled_offsite_backup)

    def run_scheduled_offsite_backup(self):
        if self.offsite_backup_thread is not None and self.offsite_backup_thread.isRunning():
            return
        targets = [row for row in self.repository.list_backup_targets() if row["enabled"]]
        if not targets:
            return
        if self.repository.get_setting(
            self.productivity.OFFSITE_LAST_SYNC_SETTING, ""
        ) == date.today().isoformat():
            return
        password = self.productivity.load_offsite_backup_password()
        if not password:
            self.statusBar().showMessage(
                "異地備份尚未設定保存的備份密碼，請到「設定 → 異地完整備份」完成一次同步。",
                15000,
            )
            return
        thread = QThread(self)
        worker = OffsiteBackupWorker(self.productivity, password)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.offsite_backup_completed)
        worker.failed.connect(self.offsite_backup_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.offsite_backup_thread_finished)
        self.offsite_backup_thread = thread
        self.offsite_backup_worker = worker
        self.statusBar().showMessage("正在背景建立異地完整備份…")
        thread.start()

    def offsite_backup_completed(self, result):
        archive_path, results = result
        failures = [row for row in results if row[1] != "成功"]
        if results and not failures:
            self.repository.set_setting(
                self.productivity.OFFSITE_LAST_SYNC_SETTING,
                date.today().isoformat(),
            )
            self.statusBar().showMessage(
                f"異地完整備份完成：{Path(archive_path).name}", 15000
            )
            self.repository.log_operation(
                "自動異地備份", "同步完成", str(archive_path)
            )
        else:
            self.statusBar().showMessage(
                f"異地備份有 {len(failures)} 個目的地失敗，稍後會重試。",
                15000,
            )

    def offsite_backup_failed(self, error_text):
        self.statusBar().showMessage(f"異地備份失敗：{error_text}", 15000)
        try:
            self.repository.log_operation("自動異地備份失敗", error_text, "")
        except Exception:
            pass

    def offsite_backup_thread_finished(self):
        self.offsite_backup_thread = None
        self.offsite_backup_worker = None

    def ensure_admin(self, action_text="這個操作"):
        if self.current_user.get("role") == "admin":
            return True
        QMessageBox.warning(
            self,
            "權限不足",
            f"「{action_text}」只允許管理員執行。",
        )
        return False

    def show_recycle_bin(self):
        while True:
            dialog = RecycleBinDialog(self.repository.list_recycle_bin(), self)
            if dialog.exec() != QDialog.Accepted:
                return
            if dialog.action == "restore":
                if not self.ensure_can_modify("還原回收桶資料"):
                    return
                restored = self.repository.restore_recycle_items(dialog.selected_ids())
                self.repository.log_operation("回收桶還原", f"還原 {len(restored)} 筆", "")
                self.refresh_records(restored[0] if restored else None)
            elif dialog.action in {"purge", "purge_all"}:
                if not self.ensure_admin("永久清除回收桶"):
                    return
                reply = QMessageBox.question(
                    self,
                    "永久刪除確認",
                    "永久刪除後只能從備份還原，確定繼續嗎？",
                )
                if reply != QMessageBox.Yes:
                    continue
                ids = None if dialog.action == "purge_all" else dialog.selected_ids()
                count = self.repository.purge_recycle_items(ids, ATTACHMENTS_DIR)
                self.repository.log_operation("清理回收桶", f"永久刪除 {count} 筆", "")

    def show_undo_operations(self):
        if not self.ensure_can_modify("復原批次操作"):
            return
        dialog = UndoOperationsDialog(self.repository.list_undo_operations(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        if QMessageBox.question(
            self,
            "確認復原",
            "系統會把所選操作涉及的資料恢復到操作前，確定繼續嗎？",
        ) != QMessageBox.Yes:
            return
        result = self.repository.undo_operation(dialog.operation_id)
        if result:
            self.repository.log_operation("復原批次操作", result["summary"], "")
            self.checked_record_ids.clear()
            self.new_record()
            self.refresh_records()
            QMessageBox.information(self, "復原完成", result["summary"])

    def manage_users(self):
        if not self.ensure_admin("使用者與權限管理"):
            return
        UserManagementDialog(self.repository, self.encryption_key, self).exec()
        self.repository.log_operation("使用者管理", "檢視或更新帳號與權限", "")

    def manage_external_backups(self):
        if not self.ensure_admin("異地完整備份"):
            return
        dialog = BackupTargetsDialog(self.repository, self.productivity, self)
        dialog.exec()
        if dialog.restore_succeeded:
            QApplication.quit()
            return
        self.repository.log_operation("異地備份", "開啟異地備份管理", "")
        self.refresh_backup_status()

    def show_workflow_board(self):
        if not self.ensure_can_modify("案件工作流程"):
            return
        WorkflowDialog(self.repository, self).exec()
        self.repository.log_operation("案件工作流程", "更新案件或任務", "")
        self.refresh_records(self.selected_record_id)
        self.refresh_notification_status()

    def show_notification_center(self):
        NotificationCenterDialog(self.repository, self).exec()
        self.refresh_notification_status()

    def manage_import_profiles(self):
        if not self.ensure_can_modify("Excel 匯入設定檔"):
            return
        ImportProfilesDialog(self.repository, dict(LAND_FIELDS), self).exec()
        applied = apply_default_import_profile(self.repository)
        self.repository.log_operation("匯入設定檔", f"套用 {applied} 個預設欄名", "")

    def manage_report_templates(self):
        if not self.ensure_can_modify("報表與列印範本"):
            return
        dialog = ReportTemplatesDialog(self.repository, dict(LAND_FIELDS), self)
        if dialog.exec() != QDialog.Accepted or not dialog.export_template:
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            QMessageBox.information(self, "尚未選取", "請先勾選或選取要輸出的資料。")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存範本報表",
            str(APP_DIR / "土地資料報表.docx"),
            "Word 文件 (*.docx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".docx"):
            file_path += ".docx"
        rows = []
        for row in self.repository.fetch_customers_by_ids(record_ids):
            plain = self.get_plain_record_data(row)
            plain["id"] = row["id"]
            rows.append(plain)
        count = export_report_with_template(
            file_path, rows, dialog.export_template, dict(LAND_FIELDS)
        )
        self.repository.log_operation("範本報表", f"輸出 {count} 筆", file_path)
        QMessageBox.information(self, "報表完成", f"已輸出 {count} 筆資料：\n{file_path}")

    def show_duplicate_finder(self):
        if not self.ensure_can_modify("智慧重複資料檢查"):
            return
        rows = []
        for raw_row in self.repository.fetch_all_customer_rows():
            plain = self.get_plain_record_data(raw_row)
            plain["id"] = raw_row["id"]
            rows.append(plain)
        pairs = self.productivity.find_duplicate_pairs(
            rows, self.repository.ignored_duplicate_pairs()
        )
        if not pairs:
            QMessageBox.information(self, "檢查完成", "沒有發現尚未確認的高相似資料。")
            return
        dialog = DuplicateFinderDialog(pairs, self)
        if dialog.exec() != QDialog.Accepted or not dialog.pair:
            return
        left_id, right_id = dialog.pair["left_id"], dialog.pair["right_id"]
        if dialog.action == "ignore":
            self.repository.ignore_duplicate_pair(left_id, right_id)
            self.repository.log_operation("忽略重複建議", f"ID {left_id} / {right_id}", "")
            return
        self.checked_record_ids = {left_id, right_id}
        self.merge_checked_records()

    def show_map_visualization(self):
        if not self.ensure_can_modify("地圖與地號視覺化"):
            return
        dialog = MapLocationsDialog(
            self.repository, self.fernet, self.selected_record_id, self
        )
        if dialog.exec() != QDialog.Accepted or not dialog.export_requested:
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存土地位置視覺化",
            str(APP_DIR / "土地位置與地號視覺化.html"),
            "HTML 網頁 (*.html)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".html"):
            file_path += ".html"
        count = self.productivity.build_map_html(dialog.rows, file_path)
        self.repository.log_operation("地圖視覺化", f"輸出 {count} 個位置", file_path)
        open_local_path(file_path, self, item_label="土地位置視覺化")

    def verify_managed_attachments(self):
        if not self.ensure_admin("檢查納管附件"):
            return
        results = self.repository.verify_managed_attachments()
        abnormal = [row for row in results if row["state"] != "正常"]
        detail = "\n".join(
            f"ID {row['id']} {row['name']}：{row['state']}" for row in abnormal[:20]
        )
        message = f"已檢查 {len(results)} 個納管附件；異常 {len(abnormal)} 個。"
        if detail:
            message += "\n\n" + detail
        QMessageBox.information(self, "附件完整性檢查", message)
        self.repository.log_operation("附件完整性檢查", message, "")

    def create_form(self, parent_layout):
        title = QLabel("土地資料")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #f9fafb; padding-bottom: 4px;")
        parent_layout.addWidget(title)

        self.management_summary_label = QLabel("尚未選取資料")
        self.management_summary_label.setWordWrap(True)
        self.management_summary_label.setStyleSheet(
            "background: #1f2937; color: #dbeafe; border: 1px solid #374151; "
            "border-radius: 5px; padding: 8px;"
        )
        self.management_summary_label.setToolTip(
            "顯示案件、標籤、附件、自訂欄位、最近聯絡與追蹤狀態。"
        )
        parent_layout.addWidget(self.management_summary_label)

        form_widget = QWidget()
        form_layout = QGridLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

        for index, (key, label) in enumerate(LAND_FIELDS, start=0):
            row = index
            label_widget = QLabel(label)
            label_widget.setStyleSheet("color: #d1d5db; padding-right: 6px;")
            form_layout.addWidget(label_widget, row, 0)
            if key == "note":
                widget = QPlainTextEdit()
                widget.setFixedHeight(88)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.fields[key] = widget
            else:
                widget = QLineEdit()
                if key == "total_declared_value":
                    widget.setReadOnly(True)
                self.fields[key] = widget
                self.field_widgets[key] = widget
                if key == "declared_value":
                    widget.editingFinished.connect(self.format_declared_value)
                if key == "external_id":
                    widget.textEdited.connect(self.on_external_id_edited)
                    widget.installEventFilter(self)
            form_layout.addWidget(widget, row, 1)

        form_layout.setColumnStretch(1, 1)
        parent_layout.addWidget(form_widget)
        self.bind_total_formula()

        button_row = QHBoxLayout()
        save_button = QPushButton("儲存")
        save_button.clicked.connect(self.save_record)
        button_row.addWidget(save_button)

        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.new_record)
        button_row.addWidget(clear_button)

        button_row.addStretch(1)

        delete_button = QPushButton("刪除")
        delete_button.clicked.connect(self.delete_record)
        button_row.addWidget(delete_button)

        parent_layout.addLayout(button_row)
        parent_layout.addStretch(1)

    def show_settings_menu(self):
        if self.settings_menu is None or self.settings_button is None:
            return
        position = self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft())
        self.settings_menu.exec(position)

    def show_about(self):
        QMessageBox.information(self, "關於系統", full_version_text())

    def show_help(self):
        HelpDialog(self).exec()

    def show_data_menu(self):
        if self.data_menu is None or self.data_button is None:
            return
        position = self.data_button.mapToGlobal(self.data_button.rect().bottomLeft())
        self.data_menu.exec(position)

    def show_tools_menu(self):
        if self.tools_menu is None or self.tools_button is None:
            return
        position = self.tools_button.mapToGlobal(self.tools_button.rect().bottomLeft())
        self.tools_menu.exec(position)

    def run_data_quality_check(self):
        selected_rule_keys = load_quality_rule_keys()
        rules_dialog = DataQualityRulesDialog(selected_rule_keys, self)
        if rules_dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("已取消資料品質檢查。", 2500)
            return
        selected_rule_keys = rules_dialog.selected_rules()
        save_quality_rule_keys(selected_rule_keys)

        rows = self.active_record_repository().fetch_all_customer_rows()
        plain_records = []
        for row in rows:
            data = self.get_plain_record_data(row)
            data["id"] = row["id"]
            plain_records.append(data)
        all_issues = inspect_customer_quality(plain_records, enabled_rules=selected_rule_keys)
        ignored_signatures = load_ignored_quality_issue_signatures()
        issues = [
            issue for issue in all_issues
            if quality_issue_signature(issue) not in ignored_signatures
        ]
        ignored_count = len(all_issues) - len(issues)
        active_count_state = {"value": len(issues)}
        ignored_count_state = {"value": ignored_count}

        def ignore_quality_issue(issue):
            signature = quality_issue_signature(issue)
            if signature not in ignored_signatures:
                ignored_signatures.add(signature)
                active_count_state["value"] = max(0, active_count_state["value"] - 1)
                ignored_count_state["value"] += 1
                save_ignored_quality_issue_signatures(ignored_signatures)

        def clear_ignored_quality_issues():
            ignored_signatures.clear()
            ignored_count_state["value"] = 0
            save_ignored_quality_issue_signatures(ignored_signatures)

        DataQualityDialog(
            issues,
            total_records=len(plain_records),
            parent=self,
            on_issue_activated=self.open_quality_issue_record,
            on_issue_ignored=ignore_quality_issue,
            ignored_count=ignored_count,
            on_clear_ignored=clear_ignored_quality_issues,
        ).exec()
        self.statusBar().showMessage(
            f"資料品質檢查完成：{len(plain_records)} 筆資料，"
            f"{active_count_state['value']} 個未確認提醒，{ignored_count_state['value']} 個已隱藏；"
            f"已啟用 {len(selected_rule_keys)} 項規則。",
            4000,
        )

    def open_quality_issue_record(self, record_id):
        self.refresh_records(record_id)
        self.load_record(record_id)
        self.statusBar().showMessage(f"已載入資料 ID {record_id}，可在右側表單修正。", 4000)

    def show_dashboard(self):
        DashboardDialog(self.dashboard_stats(), self).exec()

    def show_record_history(self):
        if self.selected_record_id is None:
            QMessageBox.warning(self, "尚未選取", "請先選取要查看歷史的資料。")
            return
        row = self.repository.get_customer(self.selected_record_id)
        if row is None:
            QMessageBox.warning(self, "找不到資料", "目前選取的資料不存在。")
            return
        plain_data = self.get_plain_record_data(row)
        logs = self.plain_record_change_logs(self.selected_record_id)
        RecordHistoryDialog(
            logs,
            self.record_label(self.selected_record_id, plain_data),
            self,
        ).exec()

    def edit_follow_up_reminder(self):
        if not self.ensure_can_modify("追蹤提醒"):
            return
        if self.selected_record_id is None:
            QMessageBox.warning(self, "尚未選取", "請先選取要設定追蹤提醒的資料。")
            return
        repository = self.active_record_repository()
        try:
            row = repository.get_customer(self.selected_record_id)
            reminder = self.plain_follow_up_reminder(
                repository.get_follow_up_reminder(self.selected_record_id)
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if row is None:
            QMessageBox.warning(self, "找不到資料", "目前選取的資料不存在。")
            return
        plain_data = self.get_plain_record_data(row)
        dialog = FollowUpReminderDialog(
            self.record_label(self.selected_record_id, plain_data),
            reminder,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.delete_requested:
            try:
                deleted = repository.delete_follow_up_reminder(
                    self.selected_record_id
                )
            except DesktopApiError as exc:
                QMessageBox.critical(self, "清除失敗", str(exc))
                return
            if deleted and not self.api_mode:
                repository.log_operation(
                    "清除追蹤提醒",
                    self.record_label(self.selected_record_id, plain_data),
                    "",
                )
            QMessageBox.information(self, "已清除", "已清除這筆資料的追蹤提醒。")
            self.refresh_records(self.selected_record_id)
            return
        values = dialog.values()
        encrypted_note = encrypt_value(self.fernet, values.get("note") or "")
        try:
            repository.save_follow_up_reminder(
                self.selected_record_id,
                values.get("due_date"),
                values.get("status"),
                encrypted_note,
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return
        if not self.api_mode:
            repository.log_operation(
                "設定追蹤提醒",
                self.record_label(self.selected_record_id, plain_data),
                f"{values.get('due_date') or '未設定日期'} / {values.get('status')}",
            )
        self.refresh_records(self.selected_record_id)
        QMessageBox.information(self, "已儲存", "追蹤提醒已儲存。")

    def show_follow_up_list(self):
        repository = self.active_record_repository()
        reminders = [
            self.plain_follow_up_reminder(row)
            for row in repository.list_follow_up_reminders()
        ]
        FollowUpListDialog(reminders, self, on_record_activated=self.open_quality_issue_record).exec()

    def is_readonly_mode(self):
        return get_setting(READONLY_MODE_SETTING_KEY, "0") == "1"

    def ensure_can_modify(self, action_text="這個操作"):
        if self.current_user.get("role") == "viewer":
            QMessageBox.warning(
                self,
                "唯讀權限",
                f"目前帳號是唯讀人員，已阻止「{action_text}」。",
            )
            return False
        if not self.is_readonly_mode():
            return True
        QMessageBox.warning(
            self,
            "唯讀模式",
            f"目前已啟用唯讀模式，已阻止「{action_text}」。請到「設定 > 唯讀模式」關閉後再操作。",
        )
        return False

    def toggle_readonly_mode(self, enabled):
        set_setting(READONLY_MODE_SETTING_KEY, "1" if enabled else "0")
        self.statusBar().showMessage(
            "已啟用唯讀模式，會阻止新增/修改/刪除。" if enabled else "已關閉唯讀模式。",
            3500,
        )

    def selected_or_checked_record_ids(self):
        ids = set(self.checked_record_ids)
        ids.update(self.selected_table_record_ids())
        return sorted(ids)

    def selected_table_record_ids(self):
        if self.table_view is None or self.table_view.selectionModel() is None:
            return []
        selected_rows = sorted(
            {
                index.row()
                for index in self.table_view.selectionModel().selectedIndexes()
                if index.isValid()
            }
        )
        record_ids = []
        for row_number in selected_rows:
            row = self.table_model.row_record(row_number)
            if row is not None:
                record_ids.append(row["id"])
        if not record_ids and self.selected_record_id is not None:
            record_ids.append(self.selected_record_id)
        return record_ids

    def current_result_record_ids(self):
        if self.table_model is None:
            return []
        return [row["id"] for row in self.table_model.load_all()]

    def update_checked_records(self, record_ids, checked, action_label):
        ids = sorted({int(record_id) for record_id in record_ids})
        if not ids:
            QMessageBox.information(self, "沒有資料", "目前沒有可處理的資料。")
            return 0
        changed = 0
        for record_id in ids:
            already_checked = record_id in self.checked_record_ids
            if checked and not already_checked:
                self.checked_record_ids.add(record_id)
                changed += 1
            elif not checked and already_checked:
                self.checked_record_ids.discard(record_id)
                changed += 1
            self.table_model.update_checked_state(record_id, record_id in self.checked_record_ids)
        if changed:
            self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"{action_label}：{changed} 筆，已勾選 {len(self.checked_record_ids)} 筆")
        return changed

    def check_selected_rows(self):
        ids = self.selected_table_record_ids()
        if not ids:
            QMessageBox.information(self, "尚未選取", "請先在表格中選取一列或多列。")
            return
        self.update_checked_records(ids, True, "勾選選取列")

    def uncheck_selected_rows(self):
        ids = self.selected_table_record_ids()
        if not ids:
            QMessageBox.information(self, "尚未選取", "請先在表格中選取一列或多列。")
            return
        self.update_checked_records(ids, False, "取消選取列勾選")

    def check_visible_records(self):
        self.update_checked_records(self.current_result_record_ids(), True, "勾選目前搜尋結果")

    def uncheck_visible_records(self):
        self.update_checked_records(self.current_result_record_ids(), False, "取消目前搜尋結果勾選")

    def invert_visible_checked_records(self):
        ids = self.current_result_record_ids()
        if not ids:
            QMessageBox.information(self, "沒有資料", "目前搜尋結果沒有可反轉的資料。")
            return
        changed = 0
        for record_id in ids:
            if record_id in self.checked_record_ids:
                self.checked_record_ids.discard(record_id)
            else:
                self.checked_record_ids.add(record_id)
            changed += 1
            self.table_model.update_checked_state(record_id, record_id in self.checked_record_ids)
        if changed:
            self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"已反轉目前搜尋結果 {changed} 筆，已勾選 {len(self.checked_record_ids)} 筆")

    def clear_checked_selection(self):
        count = len(self.checked_record_ids)
        if not count:
            self.update_selection_status("目前沒有已勾選資料")
            return
        ids = sorted(self.checked_record_ids)
        self.checked_record_ids.clear()
        for record_id in ids:
            self.table_model.update_checked_state(record_id, False)
        self.schedule_selection_state_save()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)
        self.update_selection_status(f"已取消全部勾選：{count} 筆")

    def update_selection_status(self, message=None):
        if self.table_view is None or self.table_model is None:
            return
        if message:
            self.statusBar().showMessage(message, 3500)
            return
        selected_count = len(self.selected_table_record_ids())
        checked_count = len(self.checked_record_ids)
        if selected_count or checked_count:
            self.statusBar().showMessage(
                f"已選取 {selected_count} 筆；已勾選 {checked_count} 筆",
                2500,
            )

    def selected_record_plain_data(self):
        if self.selected_record_id is None:
            return None, None
        row = self.active_record_repository().get_customer(self.selected_record_id)
        if row is None:
            return None, None
        return row, self.get_plain_record_data(row)

    def filter_management_records(self, field_key, value):
        value = str(value or "").strip()
        if not value:
            return
        self.advanced_search_criteria = {}
        set_setting(ADVANCED_SEARCH_SETTING_KEY, encode_table_preferences({}))
        self.search_input.setText(value)
        index = self.filter_field_combo.findData(field_key)
        self.filter_field_combo.blockSignals(True)
        try:
            self.filter_field_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.filter_field_combo.blockSignals(False)
        self.refresh_records()
        self.statusBar().showMessage(f"已顯示「{value}」相關資料。", 3500)

    def show_health_check(self):
        HealthCheckDialog(self.build_health_checks(), self).exec()

    def build_health_checks(self):
        if self.api_mode:
            checks = []
            try:
                health = self.record_repository.client.health()
                checks.append(
                    {
                        "status": "OK" if health.get("status") == "ok" else "錯誤",
                        "title": "家中 PostgreSQL API",
                        "detail": (
                            f"版本 {health.get('version') or '未知'}；"
                            f"資料結構 {health.get('schema_version') or '未知'}；"
                            f"資料 {health.get('record_count') or 0} 筆"
                        ),
                    }
                )
            except Exception as exc:
                checks.append(
                    {"status": "錯誤", "title": "家中 PostgreSQL API", "detail": str(exc)}
                )
            checks.append(
                {
                    "status": "提醒" if self.is_readonly_mode() else "OK",
                    "title": "客戶端權限模式",
                    "detail": "唯讀模式已啟用" if self.is_readonly_mode() else "可依帳號權限修改資料",
                }
            )
            diagnostics_path = (
                Path(os.environ.get("LOCALAPPDATA", APP_DIR))
                / "LandCustomerSystem"
                / "client-network-diagnostics.json"
            )
            checks.append(
                {
                    "status": "OK" if diagnostics_path.is_file() else "提醒",
                    "title": "客戶端連線診斷",
                    "detail": str(diagnostics_path),
                }
            )
            return checks
        checks = []
        try:
            with self.database.connect() as conn:
                quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
            checks.append(
                {
                    "status": "OK" if quick_check == "ok" else "警告",
                    "title": "SQLite 完整性",
                    "detail": quick_check,
                }
            )
        except Exception as exc:
            checks.append({"status": "錯誤", "title": "SQLite 完整性", "detail": str(exc)})

        try:
            total_records = self.repository.count_customers()
            counts = self.repository.management_table_counts()
            checks.append(
                {
                    "status": "OK",
                    "title": "資料量",
                    "detail": (
                        f"客戶 {total_records} 筆；案件 {counts.get('cases', 0)} 個／關聯 {counts.get('case_customers', 0)} 筆；"
                        f"標籤 {counts.get('tags', 0)} 個／套用 {counts.get('customer_tags', 0)} 次；"
                        f"附件 {counts.get('customer_attachments', 0)}；自訂值 {counts.get('customer_custom_values', 0)}；"
                        f"聯絡紀錄 {counts.get('contact_logs', 0)}"
                    ),
                }
            )
        except Exception as exc:
            checks.append({"status": "錯誤", "title": "資料量", "detail": str(exc)})

        try:
            plain_records = [
                self.get_plain_record_data(row)
                for row in self.repository.fetch_all_customer_rows()
            ]
            issues = inspect_customer_quality(plain_records, enabled_rules=load_quality_rule_keys())
            checks.append(
                {
                    "status": "OK" if not issues else "提醒",
                    "title": "資料品質",
                    "detail": f"{len(issues)} 個待確認項目",
                }
            )
        except Exception as exc:
            checks.append({"status": "警告", "title": "資料品質", "detail": str(exc)})

        try:
            reminders = [
                self.plain_follow_up_reminder(row)
                for row in self.repository.list_follow_up_reminders()
            ]
            overdue_count = sum(1 for reminder in reminders if reminder.get("is_overdue"))
            checks.append(
                {
                    "status": "OK" if overdue_count == 0 else "提醒",
                    "title": "追蹤提醒",
                    "detail": f"{len(reminders)} 筆提醒；{overdue_count} 筆已逾期",
                }
            )
        except Exception as exc:
            checks.append({"status": "警告", "title": "追蹤提醒", "detail": str(exc)})

        try:
            backup_files = self.database.list_backup_files()
            latest_backup = backup_files[0] if backup_files else None
            checks.append(
                {
                    "status": "OK" if latest_backup else "提醒",
                    "title": "備份",
                    "detail": str(latest_backup) if latest_backup else "尚未找到備份檔",
                }
            )
        except Exception as exc:
            checks.append({"status": "錯誤", "title": "備份", "detail": str(exc)})
        try:
            readonly_mode = self.is_readonly_mode()
            checks.append(
                {
                    "status": "提醒" if readonly_mode else "OK",
                    "title": "權限模式",
                    "detail": "唯讀模式已啟用" if readonly_mode else "可新增/修改資料",
                }
            )
        except Exception as exc:
            checks.append({"status": "警告", "title": "權限模式", "detail": str(exc)})
        error_log_path = get_error_log_path(self.database.database_path.parent)
        checks.append(
            {
                "status": "提醒" if error_log_path.exists() else "OK",
                "title": "系統錯誤記錄",
                "detail": str(error_log_path) if error_log_path.exists() else "尚無未預期錯誤記錄",
            }
        )
        return checks

    def manage_cases(self):
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        dialog = CaseManagementDialog(cases, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if dialog.action == "view":
            self.filter_management_records("case_names", values.get("title"))
            return
        if not self.ensure_can_modify("案件管理"):
            return
        try:
            if dialog.action == "save":
                case_id = repository.save_case(
                    values["title"],
                    values["status"],
                    values["note"],
                    values["case_id"],
                )
                if not self.api_mode:
                    log_operation("案件管理", f"儲存案件 {case_id}", values["title"])
            elif dialog.action == "delete":
                if QMessageBox.question(self, "刪除案件", "確定刪除選取案件？案件關聯會一起移除。") != QMessageBox.Yes:
                    return
                repository.delete_case(values["case_id"])
                if not self.api_mode:
                    log_operation("案件管理", f"刪除案件 {values['case_id']}", "")
        except (sqlite3.IntegrityError, ValueError, DesktopApiError) as exc:
            QMessageBox.warning(self, "案件管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def assign_checked_records_to_case(self):
        if not self.ensure_can_modify("加入案件"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要加入案件的資料。")
            return
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if not cases:
            QMessageBox.information(self, "尚無案件", "請先建立案件。")
            self.manage_cases()
            return
        dialog = CaseSelectDialog(cases, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            added = repository.add_customers_to_case(
                dialog.selected_case_id(), record_ids
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "加入案件失敗", str(exc))
            return
        if not self.api_mode:
            log_operation("加入案件", f"加入 {added} 筆資料", f"case_id={dialog.selected_case_id()}")
        self.refresh_records(self.selected_record_id)
        QMessageBox.information(self, "完成", f"已加入 {added} 筆資料到案件。")

    def remove_selected_records_from_case(self):
        if not self.ensure_can_modify("從案件移除資料"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要從案件移除的資料。")
            return
        repository = self.active_record_repository()
        try:
            cases = repository.list_cases()
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if not cases:
            QMessageBox.information(self, "尚無案件", "目前沒有可移除的案件。")
            return
        dialog = CaseSelectDialog(
            cases,
            len(record_ids),
            self,
            dialog_title="從案件移除資料",
            action_text="移除",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            removed = repository.remove_customers_from_case(
                dialog.selected_case_id(),
                record_ids,
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "移出案件失敗", str(exc))
            return
        if not self.api_mode:
            log_operation(
                "移出案件",
                f"移除 {removed} 筆資料",
                f"case_id={dialog.selected_case_id()}",
            )
        self.refresh_records(self.selected_record_id)
        QMessageBox.information(self, "完成", f"已從案件移除 {removed} 筆資料。")

    def batch_edit_customer_tags(self):
        if not self.ensure_can_modify("批量設定標籤"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要設定標籤的資料。")
            return
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if not tags:
            QMessageBox.information(self, "尚無標籤", "請先建立標籤。")
            self.manage_tags()
            return
        dialog = BatchCustomerTagsDialog(tags, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            processed = repository.set_customers_tags(
                record_ids,
                dialog.selected_ids(),
                dialog.mode(),
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "設定失敗", str(exc))
            return
        if not self.api_mode:
            log_operation(
                "批量設定標籤",
                f"處理 {processed} 筆資料",
                f"mode={dialog.mode()} / tags={dialog.selected_ids()}",
            )
        self.refresh_records(self.selected_record_id)
        QMessageBox.information(self, "完成", f"已更新 {processed} 筆資料的標籤。")

    def batch_edit_custom_values(self):
        if not self.ensure_can_modify("批量設定自訂欄位"):
            return
        record_ids = self.selected_or_checked_record_ids()
        if not record_ids:
            QMessageBox.warning(self, "未選取資料", "請先選取或勾選要設定自訂欄位的資料。")
            return
        fields = self.repository.list_custom_fields()
        if not fields:
            QMessageBox.information(self, "尚無自訂欄位", "請先建立自訂欄位。")
            self.manage_custom_fields()
            return
        dialog = BatchCustomerCustomValuesDialog(fields, len(record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_values()
        processed = self.repository.set_customers_custom_values(record_ids, values)
        log_operation(
            "批量設定自訂欄位",
            f"處理 {processed} 筆資料",
            f"fields={sorted(values)}",
        )
        self.refresh_records(self.selected_record_id)
        QMessageBox.information(self, "完成", f"已更新 {processed} 筆資料的自訂欄位。")

    def manage_tags(self):
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        dialog = TagManagementDialog(tags, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if dialog.action == "view":
            self.filter_management_records("tag_names", values.get("name"))
            return
        if not self.ensure_can_modify("標籤管理"):
            return
        try:
            if dialog.action == "save":
                tag_id = repository.save_tag(
                    values["name"], values["color"], values["tag_id"]
                )
                if not self.api_mode:
                    log_operation("標籤管理", f"儲存標籤 {tag_id}", values["name"])
            elif dialog.action == "delete":
                if QMessageBox.question(self, "刪除標籤", "確定刪除選取標籤？") != QMessageBox.Yes:
                    return
                repository.delete_tag(values["tag_id"])
                if not self.api_mode:
                    log_operation("標籤管理", f"刪除標籤 {values['tag_id']}", "")
        except (sqlite3.IntegrityError, ValueError, DesktopApiError) as exc:
            QMessageBox.warning(self, "標籤管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def edit_customer_tags(self):
        if not self.ensure_can_modify("設定標籤"):
            return
        _row, plain_data = self.selected_record_plain_data()
        if plain_data is None:
            QMessageBox.warning(self, "未選取資料", "請先選取一筆資料。")
            return
        repository = self.active_record_repository()
        try:
            tags = repository.list_tags()
            selected_tag_ids = repository.get_customer_tag_ids(
                self.selected_record_id
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if not tags:
            QMessageBox.information(self, "尚無標籤", "請先建立標籤。")
            self.manage_tags()
            return
        dialog = CustomerTagsDialog(
            tags,
            selected_tag_ids,
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            count = repository.set_customer_tags(
                self.selected_record_id, dialog.selected_ids()
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "設定失敗", str(exc))
            return
        if not self.api_mode:
            log_operation(
                "設定標籤",
                self.record_label(self.selected_record_id, plain_data),
                f"{count} 個標籤",
            )
        self.refresh_records(self.selected_record_id)

    def manage_attachments(self):
        repository = self.active_record_repository()
        try:
            _row, plain_data = self.selected_record_plain_data()
            attachments = (
                repository.list_customer_attachments(self.selected_record_id)
                if plain_data is not None
                else []
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if plain_data is None:
            QMessageBox.warning(self, "未選取資料", "請先選取一筆資料。")
            return
        dialog = AttachmentDialog(
            attachments,
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("附件管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "add":
                if values.get("managed"):
                    attachment_id = repository.import_managed_attachment(
                        self.selected_record_id,
                        values["file_path"],
                        ATTACHMENTS_DIR,
                        values["description"],
                    )
                else:
                    attachment_id = repository.add_customer_attachment(
                        self.selected_record_id,
                        values["file_path"],
                        values["description"],
                    )
                if not self.api_mode:
                    log_operation("新增附件", self.record_label(self.selected_record_id, plain_data), values["file_path"])
                saved_as = "系統納管附件" if values.get("managed") else "外部連結"
                QMessageBox.information(self, "完成", f"已新增附件 ID {attachment_id}（{saved_as}）。")
            elif dialog.action == "delete":
                repository.delete_customer_attachment(
                    values["attachment_id"], ATTACHMENTS_DIR
                )
                if not self.api_mode:
                    log_operation("刪除附件", self.record_label(self.selected_record_id, plain_data), str(values["attachment_id"]))
        except (ValueError, DesktopApiError) as exc:
            QMessageBox.warning(self, "附件管理失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def manage_custom_fields(self):
        dialog = CustomFieldManagementDialog(self.repository.list_custom_fields(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("自訂欄位管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "save":
                field_id = self.repository.save_custom_field(
                    values["label"],
                    values["field_key"],
                    values["field_id"],
                )
                log_operation("自訂欄位管理", f"儲存欄位 {field_id}", values["label"])
            elif dialog.action == "delete":
                if QMessageBox.question(self, "刪除自訂欄位", "確定刪除選取欄位與所有填寫值？") != QMessageBox.Yes:
                    return
                self.repository.delete_custom_field(values["field_id"])
                log_operation("自訂欄位管理", f"刪除欄位 {values['field_id']}", "")
        except (sqlite3.IntegrityError, ValueError) as exc:
            QMessageBox.warning(self, "自訂欄位失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def edit_customer_custom_values(self):
        if not self.ensure_can_modify("設定自訂欄位"):
            return
        _row, plain_data = self.selected_record_plain_data()
        if plain_data is None:
            QMessageBox.warning(self, "未選取資料", "請先選取一筆資料。")
            return
        fields = self.repository.list_custom_fields()
        if not fields:
            QMessageBox.information(self, "尚無自訂欄位", "請先建立自訂欄位。")
            self.manage_custom_fields()
            return
        dialog = CustomerCustomValuesDialog(
            fields,
            self.repository.get_customer_custom_values(self.selected_record_id),
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        count = self.repository.set_customer_custom_values(
            self.selected_record_id,
            dialog.result_values(),
        )
        log_operation("設定自訂欄位", self.record_label(self.selected_record_id, plain_data), f"{count} 個欄位")
        self.refresh_records(self.selected_record_id)

    def manage_text_templates(self):
        dialog = TextTemplateDialog(self.repository.list_text_templates(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("快速範本管理"):
            return
        values = dialog.values()
        try:
            if dialog.action == "save":
                template_id = self.repository.save_text_template(
                    values["title"],
                    values["content"],
                    values["template_type"],
                    values["template_id"],
                )
                log_operation("快速範本管理", f"儲存範本 {template_id}", values["title"])
            elif dialog.action == "delete":
                self.repository.delete_text_template(values["template_id"])
                log_operation("快速範本管理", f"刪除範本 {values['template_id']}", "")
        except ValueError as exc:
            QMessageBox.warning(self, "快速範本失敗", str(exc))

    def apply_text_template(self):
        if not self.ensure_can_modify("套用快速範本"):
            return
        templates = self.repository.list_text_templates()
        if not templates:
            QMessageBox.information(self, "尚無範本", "請先建立快速範本。")
            self.manage_text_templates()
            return
        dialog = ApplyTemplateDialog(templates, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        template = values.get("template")
        if not template:
            return
        target = values.get("target_field")
        current_text = self.get_field_text(target)
        addition = template.get("content") or ""
        separator = "\n" if current_text else ""
        self.set_field_text(target, f"{current_text}{separator}{addition}")
        self.statusBar().showMessage("已套用快速範本，請記得儲存資料。", 3500)

    def plain_contact_logs(self, customer_id):
        logs = []
        for row in self.active_record_repository().list_contact_logs(customer_id):
            log = dict(row)
            log["note"] = decrypt_value(self.fernet, log.get("note") or "")
            logs.append(log)
        return logs

    def manage_contact_logs(self):
        repository = self.active_record_repository()
        try:
            _row, plain_data = self.selected_record_plain_data()
            logs = (
                self.plain_contact_logs(self.selected_record_id)
                if plain_data is not None
                else []
            )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "讀取失敗", str(exc))
            return
        if plain_data is None:
            QMessageBox.warning(self, "未選取資料", "請先選取一筆資料。")
            return
        dialog = ContactLogDialog(
            logs,
            self.record_label(self.selected_record_id, plain_data),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.ensure_can_modify("聯絡紀錄"):
            return
        values = dialog.values()
        try:
            if dialog.action == "add":
                note = encrypt_value(self.fernet, values.get("note") or "")
                repository.add_contact_log(
                    self.selected_record_id,
                    values.get("contact_date"),
                    values.get("method"),
                    values.get("result"),
                    values.get("next_follow_up"),
                    note,
                )
                if values.get("next_follow_up") and not self.api_mode:
                    existing = repository.get_follow_up_reminder(
                        self.selected_record_id
                    )
                    repository.save_follow_up_reminder(
                        self.selected_record_id,
                        values.get("next_follow_up"),
                        existing["status"] if existing is not None else "未處理",
                        existing["note"]
                        if existing is not None
                        else encrypt_value(self.fernet, ""),
                    )
                if not self.api_mode:
                    log_operation(
                        "新增聯絡紀錄",
                        self.record_label(self.selected_record_id, plain_data),
                        values.get("method") or "",
                    )
            elif dialog.action == "delete":
                repository.delete_contact_log(values["log_id"])
                if not self.api_mode:
                    log_operation(
                        "刪除聯絡紀錄",
                        self.record_label(self.selected_record_id, plain_data),
                        str(values["log_id"]),
                    )
        except DesktopApiError as exc:
            QMessageBox.critical(self, "操作失敗", str(exc))
            return
        self.refresh_records(self.selected_record_id)

    def merged_plain_record(self, primary, secondary, secondary_id):
        merged = dict(primary)
        for key, _label in LAND_FIELDS:
            primary_value = str(primary.get(key) or "").strip()
            secondary_value = str(secondary.get(key) or "").strip()
            if key in {"note", "visit_log"} and primary_value and secondary_value and primary_value != secondary_value:
                merged[key] = f"{primary_value}\n--- 合併自 ID {secondary_id} ---\n{secondary_value}"
            elif not primary_value and secondary_value:
                merged[key] = secondary.get(key)
        merged["name"] = merged.get("owner_name") or ""
        return self.normalize_record_data(merged)

    def merge_checked_records(self):
        if not self.ensure_can_modify("合併資料"):
            return
        ids = sorted(self.checked_record_ids)
        if len(ids) != 2:
            QMessageBox.warning(self, "勾選數量不正確", "請剛好勾選兩筆資料再合併。")
            return
        rows = self.repository.fetch_customers_by_ids(ids)
        if len(rows) != 2:
            QMessageBox.warning(self, "資料不存在", "勾選資料已不存在，請重新整理後再試。")
            return
        primary_row, secondary_row = rows
        primary_plain = self.get_plain_record_data(primary_row)
        secondary_plain = self.get_plain_record_data(secondary_row)
        merged_plain = self.merged_plain_record(primary_plain, secondary_plain, secondary_row["id"])
        label_by_key = {key: label for key, label in LAND_FIELDS}
        preview_lines = []
        for key, _label in LAND_FIELDS:
            old_value = str(primary_plain.get(key) or "")
            new_value = str(merged_plain.get(key) or "")
            if old_value != new_value:
                preview_lines.append(f"{label_by_key.get(key, key)}: {old_value or '(空白)'} -> {new_value or '(空白)'}")
        if not preview_lines:
            preview_lines.append("主資料欄位沒有變更；仍會轉移案件、標籤、附件、自訂欄位與聯絡紀錄。")
        dialog = MergeRecordsDialog(
            self.record_label(primary_row["id"], primary_plain),
            self.record_label(secondary_row["id"], secondary_plain),
            preview_lines,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.create_safety_backup("merge")
        self.repository.record_customer_undo(
            "合併資料",
            ids,
            f"合併 ID {primary_row['id']} 與 {secondary_row['id']}",
        )
        change_logs = self.build_record_change_logs(
            primary_row["id"],
            primary_plain,
            merged_plain,
            "合併資料",
        )
        self.repository.merge_customers(
            primary_row["id"],
            secondary_row["id"],
            encrypt_record(self.fernet, merged_plain),
        )
        if change_logs:
            self.repository.add_record_change_logs(change_logs)
        self.checked_record_ids.discard(secondary_row["id"])
        self.checked_record_ids.add(primary_row["id"])
        log_operation("合併資料", f"保留 ID {primary_row['id']}", f"刪除 ID {secondary_row['id']}")
        self.refresh_records(primary_row["id"])
        QMessageBox.information(self, "合併完成", f"已保留 ID {primary_row['id']}，並合併/刪除 ID {secondary_row['id']}。")

    def open_backup_folder(self):
        backup_directory = self.database.backup_directory
        try:
            backup_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "無法建立備份資料夾", str(exc))
            return False
        return open_local_path(backup_directory, self, item_label="備份資料夾")

    def manage_backups(self):
        policy = load_backup_policy()
        dialog = BackupManagementDialog(parent=self, **policy)
        if dialog.exec() != QDialog.Accepted:
            return None

        policy = dialog.selected_policy()
        try:
            save_backup_policy(policy)
            self.database.configure_backup_policy(**policy)
            if dialog.requested_action == "compress":
                result = self.database.compress_existing_backups()
                action_text = "壓縮"
            elif dialog.requested_action == "clean":
                result = self.database.prune_backups()
                action_text = "清理"
            else:
                result = self.database.run_backup_maintenance()
                action_text = "維護"
        except Exception as exc:
            self.refresh_backup_status(show_warning=True)
            QMessageBox.critical(self, "備份管理失敗", backup_management_failure_message(exc))
            return None

        detail = (
            f"已壓縮 {result.compressed_count} 份、刪除 {result.deleted_count} 份，"
            f"釋放 {format_storage_size(result.reclaimed_bytes)}。"
        )
        if result.failed_paths:
            detail += f"\n另有 {len(result.failed_paths)} 份無法處理，已保留原檔。"
        try:
            self.repository.log_operation("備份管理", action_text, detail)
        except Exception as exc:
            detail += f"\n操作已完成，但操作記錄未寫入：{exc}"
        self.refresh_backup_status()
        QMessageBox.information(self, "備份管理完成", detail)
        return result

    def apply_saved_font_size(self):
        app = QApplication.instance()
        if app is None:
            return
        apply_font_size(app, self.current_font_size_key)
        self.update_table_metrics()

    def update_table_metrics(self):
        if self.table_view is None:
            return
        point_size = get_font_size_option(self.current_font_size_key)[2]
        row_height = max(28, point_size + 18)
        self.table_view.verticalHeader().setDefaultSectionSize(row_height)

    def change_font_size(self):
        dialog = FontSizeDialog(self.current_font_size_key, self)
        if dialog.exec() != QDialog.Accepted:
            return
        selected_key = dialog.selected_font_size_key()
        if selected_key == self.current_font_size_key:
            return
        self.current_font_size_key = selected_key
        set_setting("font_size", selected_key)
        self.apply_saved_font_size()

    def manage_watchlist(self):
        if not self.ensure_can_modify("注意名單管理"):
            return
        dialog = WatchlistDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_records(self.selected_record_id)

    def refresh_watchlist_cache(self):
        self.watchlist_names = {
            normalize_watch_name(row["name"])
            for row in get_watchlist_entries()
        }

    def show_operation_logs(self):
        dialog = OperationLogDialog(self)
        dialog.exec()

    def show_startup_backup_notice(self):
        QMessageBox.information(
            self,
            "自動備份提醒",
            startup_backup_notice(self.startup_backup_path),
        )

    def confirm_watchlist_match(self, owner_name):
        match = find_watchlist_match(owner_name)
        if match is None:
            return True

        note_text = match["note"] or "無"
        message = (
            f"姓名「{match['name']}」已在注意名單中。\n"
            f"備註：{note_text}\n\n"
            "仍要繼續儲存這筆資料嗎？"
        )
        reply = QMessageBox.question(self, "注意名單提醒", message)
        return reply == QMessageBox.Yes

    def restore_backup(self):
        if not self.ensure_can_modify("還原備份"):
            return
        backup_directory = self.database.backup_directory
        try:
            backup_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "無法開啟備份資料夾", str(exc))
            return
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "選擇要還原的備份檔",
            str(backup_directory),
            "備份檔案 (*.zip *.db);;ZIP 壓縮備份 (*.zip);;資料庫備份 (*.db);;所有檔案 (*.*)",
        )
        if not file_path:
            return

        reply = QMessageBox.question(
            self,
            "確認還原",
            restore_confirmation_message(),
        )
        if reply != QMessageBox.Yes:
            return

        try:
            backup_path = self.database.restore_database(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "還原失敗", restore_failure_message(exc))
            return

        QMessageBox.information(
            self,
            "還原完成",
            restore_success_message(backup_path),
        )
        log_operation("還原備份", Path(file_path).name, str(backup_path) if backup_path else "")
        self.close()

    def bind_total_formula(self):
        for key in ("area", "declared_value", "numerator", "denominator"):
            self.field_widgets[key].textChanged.connect(self.update_total_declared_value)

    def get_filter_field(self):
        if self.filter_field_combo is None:
            return "all"
        return self.filter_field_combo.currentData() or "all"

    def get_sort_field(self):
        if self.sort_field_combo is None:
            return "rowid"
        return self.sort_field_combo.currentData() or "rowid"

    def get_sort_reverse(self):
        if self.sort_order_combo is None:
            return True
        return (self.sort_order_combo.currentData() or "desc") == "desc"

    def closeEvent(self, event):
        if self.excel_thread is not None and self.excel_thread.isRunning():
            QMessageBox.information(self, "Excel 處理中", "請等待 Excel 工作完成後再關閉程式。")
            event.ignore()
            return
        if self.offsite_backup_thread is not None and self.offsite_backup_thread.isRunning():
            QMessageBox.information(
                self,
                "異地備份處理中",
                "請等待完整備份完成後再關閉程式，避免目的地留下不完整檔案。",
            )
            event.ignore()
            return
        for thread, _worker in list(self.record_searches.values()):
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(2000):
                QMessageBox.information(self, "搜尋處理中", "請稍候，背景搜尋即將結束。")
                event.ignore()
                return
        self.selection_save_timer.stop()
        self.persist_selection_state()
        self.save_table_preferences()
        super().closeEvent(event)

    def on_checked_state_changed(self, record_id, checked):
        if checked:
            self.checked_record_ids.add(record_id)
        else:
            self.checked_record_ids.discard(record_id)
        self.schedule_selection_state_save()
        self.update_selection_status()
        if self.show_checked_only:
            QTimer.singleShot(0, self.refresh_records)

    def toggle_checked_only(self, enabled):
        self.show_checked_only = enabled
        self.refresh_records()
        message = "目前僅顯示勾選資料" if enabled else "已顯示全部符合條件的資料"
        self.statusBar().showMessage(message, 2500)

    def eventFilter(self, watched, event):
        return super().eventFilter(watched, event)

    def on_external_id_edited(self, text):
        if self.show_full_external_id:
            self.current_external_id_plain = text

    def get_field_text(self, key):
        widget = self.fields[key]
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        return widget.text().strip()

    def set_field_text(self, key, value):
        widget = self.fields[key]
        text = value or ""
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)

    def update_total_declared_value(self):
        data = {
            "area": self.get_field_text("area"),
            "declared_value": self.get_field_text("declared_value"),
            "numerator": self.get_field_text("numerator"),
            "denominator": self.get_field_text("denominator"),
        }
        self.set_field_text("ping", calculate_ping(data) or "")
        self.set_field_text("total_declared_value", calculate_total_declared_value(data) or "")

    def format_declared_value(self):
        self.set_field_text("declared_value", format_number_text(self.get_field_text("declared_value")))

    def toggle_external_id_visibility(self):
        self.show_full_external_id = not self.show_full_external_id
        if self.external_id_button is not None:
            self.external_id_button.setText("隱藏身分證" if self.show_full_external_id else "顯示身分證")
        self.apply_external_id_visibility()
        self.refresh_records(self.selected_record_id)

    def apply_external_id_visibility(self):
        widget = self.field_widgets.get("external_id")
        if widget is None:
            return
        if self.show_full_external_id:
            widget.setReadOnly(False)
            widget.setText(self.current_external_id_plain)
        else:
            widget.setText(mask_identity_text(self.current_external_id_plain))
            widget.setReadOnly(True)

    def select_record_in_table(self, record_id):
        row_number = self.table_model.row_for_record_id(record_id)
        if row_number < 0:
            return False
        index = self.table_model.index(row_number, 0)
        selection_model = self.table_view.selectionModel()
        selection_model.setCurrentIndex(
            index,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.table_view.scrollTo(index, QAbstractItemView.PositionAtCenter)
        return True

    def on_record_select(self, current, _previous):
        if not current.isValid():
            return
        row = self.table_model.row_record(current.row())
        if row:
            self.load_record(row["id"])

    def on_table_clicked(self, index):
        if not index.isValid() or index.column() != 0:
            return
        row = self.table_model.row_record(index.row())
        if row is None:
            return
        new_state = Qt.Unchecked if row["checked"] else Qt.Checked
        self.table_model.setData(index, new_state, Qt.CheckStateRole)

    def show_record_menu(self, position: QPoint):
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return
        row = self.table_model.row_record(index.row())
        if row is None:
            return
        selected_ids = set(self.selected_table_record_ids())
        if row["id"] not in selected_ids:
            self.select_record_in_table(row["id"])
        self.record_menu.exec(self.table_view.viewport().mapToGlobal(position))

    def load_record(self, record_id):
        row = self.record_repository.get_customer(record_id)
        if row is None:
            return

        self.selected_record_id = record_id
        self.schedule_selection_state_save()
        for key in self.fields:
            value = row[key] or ""
            if key in ENCRYPTED_FIELDS:
                value = decrypt_value(self.fernet, value)
            if key == "external_id":
                self.current_external_id_plain = value
            self.set_field_text(key, value)

        self.apply_external_id_visibility()
        self.format_declared_value()
        self.update_total_declared_value()
        self.update_management_summary(row)

    def update_management_summary(self, row=None):
        if self.management_summary_label is None:
            return
        if row is None:
            self.management_summary_label.setText("尚未選取資料")
            return
        parts = []
        for key, label in (
            ("case_names", "案件"),
            ("tag_names", "標籤"),
            ("custom_values", "自訂欄位"),
            ("last_contact", "最近聯絡"),
            ("next_follow_up", "下次追蹤"),
            ("follow_up_status", "追蹤狀態"),
        ):
            value = str(row[key] or "").strip() if key in row.keys() else ""
            if value:
                parts.append(f"{label}：{compact_summary_text(value)}")
        attachment_names = row["attachment_names"] if "attachment_names" in row.keys() else ""
        attachment_count = row["attachment_count"] if "attachment_count" in row.keys() else 0
        attachment_summary = format_attachment_summary(attachment_names, attachment_count)
        if attachment_summary:
            parts.append(f"附件：{attachment_summary}")
        self.management_summary_label.setText(
            " ｜ ".join(parts) if parts else "此筆資料尚未設定案件、標籤、附件、聯絡或追蹤資訊。"
        )

    def new_record(self):
        self.selected_record_id = None
        self.schedule_selection_state_save()
        self.current_external_id_plain = ""
        self.table_view.clearSelection()
        for key in self.fields:
            self.set_field_text(key, "")
        self.apply_external_id_visibility()
        self.update_management_summary()

    def get_form_data(self):
        self.format_declared_value()
        self.update_total_declared_value()
        data = {}
        for key in self.fields:
            value = self.get_field_text(key)
            data[key] = value or None
        if self.show_full_external_id:
            self.current_external_id_plain = data.get("external_id") or ""
        else:
            data["external_id"] = self.current_external_id_plain or None
        data["ping"] = format_ping_text(data.get("ping") or "")
        data["name"] = data.get("owner_name") or ""
        return data

    def get_plain_record_data(self, row):
        data = {}
        for key in [field_key for field_key, _label in LAND_FIELDS]:
            value = row[key] if key in row.keys() else None
            if key in ENCRYPTED_FIELDS:
                value = decrypt_value(self.fernet, value or "")
            data[key] = value or None
        data["name"] = data.get("owner_name") or ""
        return data

    def record_label(self, record_id, data):
        parts = [
            f"ID {record_id}",
            str(data.get("district") or "").strip(),
            str(data.get("section") or "").strip(),
            str(data.get("land_number") or "").strip(),
            str(data.get("owner_name") or "").strip(),
        ]
        return " / ".join(part for part in parts if part)

    def build_record_change_logs(self, record_id, old_plain, new_plain, action_type="修改資料"):
        logs = []
        label_by_key = {key: label for key, label in LAND_FIELDS}
        for key, label in LAND_FIELDS:
            old_value = "" if old_plain.get(key) is None else str(old_plain.get(key))
            new_value = "" if new_plain.get(key) is None else str(new_plain.get(key))
            if old_value == new_value:
                continue
            stored_old = encrypt_value(self.fernet, old_value) if key in ENCRYPTED_FIELDS else old_value
            stored_new = encrypt_value(self.fernet, new_value) if key in ENCRYPTED_FIELDS else new_value
            logs.append(
                {
                    "customer_id": record_id,
                    "action_type": action_type,
                    "field_key": key,
                    "field_label": label_by_key.get(key, key),
                    "old_value": stored_old,
                    "new_value": stored_new,
                }
            )
        return logs

    def plain_record_change_logs(self, record_id):
        logs = []
        for row in self.repository.get_record_change_logs(record_id):
            log = dict(row)
            if log.get("field_key") in ENCRYPTED_FIELDS:
                log["old_value"] = decrypt_value(self.fernet, log.get("old_value") or "")
                log["new_value"] = decrypt_value(self.fernet, log.get("new_value") or "")
            logs.append(log)
        return logs

    def plain_follow_up_reminder(self, row):
        if row is None:
            return None
        data = dict(row)
        data["note"] = decrypt_value(self.fernet, data.get("note") or "")
        if "owner_name" in data:
            data["owner_name"] = decrypt_value(self.fernet, data.get("owner_name") or "")
        if "external_id" in data:
            data["external_id"] = decrypt_value(self.fernet, data.get("external_id") or "")
        if "address" in data:
            data["address"] = decrypt_value(self.fernet, data.get("address") or "")
        due_date = str(data.get("due_date") or "")
        try:
            data["is_overdue"] = bool(due_date) and date.fromisoformat(due_date) < date.today()
        except ValueError:
            data["is_overdue"] = False
        return data

    def dashboard_stats(self):
        repository = self.active_record_repository()
        rows = repository.fetch_all_customer_rows()
        district_counts = {}
        section_counts = {}
        total_area = 0
        total_declared_value = 0
        total_current_value = 0
        with_external_id = 0
        with_note = 0
        with_visit_log = 0
        with_case = 0
        with_tags = 0
        with_attachments = 0
        with_custom_values = 0
        with_contact = 0
        for row in rows:
            data = self.get_plain_record_data(row)
            district = data.get("district") or "(空白)"
            section = data.get("section") or "(空白)"
            district_counts[district] = district_counts.get(district, 0) + 1
            section_counts[section] = section_counts.get(section, 0) + 1
            total_area += parse_number(data.get("area")) or 0
            total_declared_value += parse_number(data.get("declared_value")) or 0
            total_current_value += parse_number(data.get("total_declared_value")) or 0
            if data.get("external_id"):
                with_external_id += 1
            if data.get("note"):
                with_note += 1
            if data.get("visit_log"):
                with_visit_log += 1
            if row["case_names"]:
                with_case += 1
            if row["tag_names"]:
                with_tags += 1
            if row["attachment_count"]:
                with_attachments += 1
            if row["custom_values"]:
                with_custom_values += 1
            if row["last_contact"]:
                with_contact += 1
        reminders = [self.plain_follow_up_reminder(row) for row in repository.list_follow_up_reminders()]
        follow_status_counts = {}
        open_follow_ups = 0
        for reminder in reminders:
            status = reminder.get("status") or "未處理"
            follow_status_counts[status] = follow_status_counts.get(status, 0) + 1
            if status != "完成":
                open_follow_ups += 1
        cases = [dict(row) for row in repository.list_cases()]
        tags = [dict(row) for row in repository.list_tags()]
        if hasattr(repository, "management_table_counts"):
            management_counts = repository.management_table_counts()
        else:
            management_counts = {
                "customer_attachments": sum(int(row.get("attachment_count") or 0) for row in rows),
                "contact_logs": with_contact,
            }
        return {
            "total_records": len(rows),
            "total_area": format_number(total_area),
            "total_declared_value": format_number(total_declared_value),
            "total_current_value": format_number(total_current_value),
            "with_external_id": with_external_id,
            "without_external_id": len(rows) - with_external_id,
            "with_note": with_note,
            "with_visit_log": with_visit_log,
            "with_case": with_case,
            "with_tags": with_tags,
            "with_attachments": with_attachments,
            "with_custom_values": with_custom_values,
            "with_contact": with_contact,
            "case_count": len(cases),
            "tag_count": len(tags),
            "attachment_count": management_counts.get("customer_attachments", 0),
            "contact_log_count": management_counts.get("contact_logs", 0),
            "open_follow_ups": open_follow_ups,
            "district_counts": sorted(district_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
            "section_counts": sorted(section_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
            "follow_up_status_counts": sorted(follow_status_counts.items(), key=lambda item: item[0]),
            "case_counts": [
                (case.get("title") or "(未命名)", case.get("customer_count") or 0, case.get("status") or "")
                for case in cases[:20]
            ],
            "tag_counts": [
                (tag.get("name") or "(未命名)", tag.get("customer_count") or 0)
                for tag in tags[:20]
            ],
        }

    def normalize_record_data(self, data):
        normalized = dict(data)
        if "declared_value" in normalized:
            normalized["declared_value"] = format_number_text(normalized.get("declared_value") or "") or None
        if "ping" in normalized:
            normalized["ping"] = format_ping_text(normalized.get("ping") or "") or None

        if any(key in normalized for key in ("area", "declared_value", "numerator", "denominator")):
            normalized["ping"] = calculate_ping(normalized) or normalized.get("ping")
            normalized["total_declared_value"] = calculate_total_declared_value(normalized)

        if normalized.get("owner_name"):
            normalized["name"] = normalized["owner_name"]
        else:
            normalized["name"] = None
        return normalized

    def build_batch_edit_preview_lines(self, rows, field_key, field_label, new_value):
        preview_lines = []
        for row in rows[:30]:
            plain_data = self.get_plain_record_data(row)
            old_value = str(plain_data.get(field_key) or "")
            preview_lines.append(
                f"ID {row['id']} | {plain_data.get('district') or ''} {plain_data.get('section') or ''} "
                f"{plain_data.get('land_number') or ''} | {field_label}: {old_value or '(空白)'} -> {new_value or '(清空)'}"
            )
        if len(rows) > 30:
            preview_lines.append(f"...其餘 {len(rows) - 30} 筆未展開")
        return preview_lines

    def batch_edit_checked_records(self):
        if not self.ensure_can_modify("批次修改"):
            return
        if not self.checked_record_ids:
            QMessageBox.warning(self, "尚未勾選", "請先勾選要批次修改的資料。")
            return

        dialog = BatchEditDialog(len(self.checked_record_ids), self)
        if dialog.exec() != QDialog.Accepted:
            return

        field_key, new_value = dialog.values()
        if not field_key:
            return
        if field_key == "owner_name" and new_value and not self.confirm_watchlist_match(new_value):
            return

        ids = sorted(self.checked_record_ids)
        rows = REPOSITORY.fetch_customers_by_ids(ids)
        preview_lines = self.build_batch_edit_preview_lines(
            rows,
            field_key,
            dialog.field_combo.currentText(),
            new_value,
        )
        preview_dialog = BatchEditPreviewDialog(
            dialog.field_combo.currentText(),
            new_value,
            preview_lines,
            self,
        )
        if preview_dialog.exec() != QDialog.Accepted:
            return
        self.create_safety_backup("batch-edit")
        self.repository.record_customer_undo(
            "批次修改",
            ids,
            f"批次修改 {len(ids)} 筆「{dialog.field_combo.currentText()}」",
        )
        updates = []
        change_logs = []
        for row in rows:
            plain_data = self.get_plain_record_data(row)
            old_plain = dict(plain_data)
            plain_data[field_key] = new_value or None
            normalized = self.normalize_record_data(plain_data)
            updates.append({**encrypt_record(self.fernet, normalized), "id": row["id"]})
            change_logs.extend(
                self.build_record_change_logs(
                    row["id"],
                    old_plain,
                    normalized,
                    "批次修改",
                )
            )
        updated_count = REPOSITORY.update_customers(updates)
        if change_logs:
            REPOSITORY.add_record_change_logs(change_logs)

        self.refresh_records(self.selected_record_id)
        log_operation("批次修改", f"更新 {updated_count} 筆", f"欄位：{dialog.field_combo.currentText()}")
        QMessageBox.information(self, "批次修改完成", f"已更新 {updated_count} 筆資料。")

    def save_record(self):
        if not self.ensure_can_modify("儲存資料"):
            return
        plain_data = self.normalize_record_data(self.get_form_data())
        if not self.confirm_watchlist_match(plain_data.get("owner_name") or ""):
            return
        is_new_record = self.selected_record_id is None
        old_plain_data = None
        if not is_new_record:
            old_row = self.record_repository.get_customer(self.selected_record_id)
            if old_row is not None:
                old_plain_data = self.get_plain_record_data(old_row)
        data = encrypt_record(self.fernet, plain_data)

        try:
            self.selected_record_id = self.record_repository.save_customer(
                data,
                self.selected_record_id,
            )
        except (sqlite3.IntegrityError, DesktopApiError) as exc:
            QMessageBox.critical(self, "儲存失敗", database_save_failure_message(exc))
            return

        if not is_new_record and old_plain_data is not None:
            change_logs = self.build_record_change_logs(
                self.selected_record_id,
                old_plain_data,
                plain_data,
                "修改資料",
            )
            if change_logs and not self.api_mode:
                REPOSITORY.add_record_change_logs(change_logs)

        self.refresh_records(self.selected_record_id)
        action_type = "新增資料" if is_new_record else "修改資料"
        log_operation(action_type, plain_data.get("owner_name") or "未命名資料", plain_data.get("land_number") or "")
        QMessageBox.information(self, "完成", "資料已儲存。")

    def change_password(self):
        dialog = ChangePasswordDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        current_password, new_password, confirm_password = dialog.values()
        policy_error = validate_new_password(new_password)
        if policy_error:
            QMessageBox.warning(self, "密碼太短", policy_error)
            return
        if new_password != confirm_password:
            QMessageBox.warning(self, "密碼不一致", "兩次輸入的新密碼不一致。")
            return
        if current_password == new_password:
            QMessageBox.warning(self, "密碼未變更", "新密碼不能和目前密碼相同。")
            return

        try:
            if self.current_user.get("username") == ADMIN_USERNAME:
                new_encryption_key, backup_path = change_admin_password(
                    current_password, new_password
                )
            else:
                new_encryption_key, backup_path = self.repository.change_user_password(
                    self.current_user.get("username"),
                    current_password,
                    new_password,
                    self.encryption_key,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "無法修改密碼", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "修改失敗", password_change_failure_message(exc))
            return

        self.encryption_key = new_encryption_key
        self.fernet = make_fernet(new_encryption_key)
        self.productivity.fernet = self.fernet
        self.refresh_records(self.selected_record_id)
        log_operation("修改密碼", "更新登入與解密密碼", str(backup_path) if backup_path else "")
        QMessageBox.information(self, "修改完成", password_changed_message(backup_path))

    def delete_record(self):
        if not self.ensure_can_modify("刪除資料"):
            return
        if self.selected_record_id is None:
            QMessageBox.warning(self, "尚未選取", "請先選取資料。")
            return
        reply = QMessageBox.question(self, "確認刪除", "確定要刪除這筆土地資料嗎？")
        if reply != QMessageBox.Yes:
            return
        try:
            self.record_repository.delete_customers([self.selected_record_id])
        except DesktopApiError as exc:
            QMessageBox.critical(self, "刪除失敗", str(exc))
            return
        self.checked_record_ids.discard(self.selected_record_id)
        log_operation("刪除資料", f"ID {self.selected_record_id}", "")
        self.new_record()
        self.refresh_records()

    def delete_checked_records(self):
        if not self.ensure_can_modify("清除勾選資料"):
            return
        if not self.checked_record_ids:
            QMessageBox.warning(self, "尚未勾選", "請先勾選要清除的資料。")
            return
        count = len(self.checked_record_ids)
        reply = QMessageBox.question(self, "確認清除", f"確定要清除已勾選的 {count} 筆資料嗎？")
        if reply != QMessageBox.Yes:
            return
        self.create_safety_backup("delete-selected")
        ids = sorted(self.checked_record_ids)
        REPOSITORY.delete_customers(ids)
        self.checked_record_ids.clear()
        log_operation("清除勾選", f"刪除 {count} 筆", "")
        self.new_record()
        self.refresh_records()

    def delete_all_records(self):
        if not self.ensure_can_modify("全部清除"):
            return
        messages = (
            "這會清除全部資料，確定要繼續嗎？",
            "第二次確認：所有土地資料都會被刪除，確定嗎？",
            "最後確認：按「是」後會清空全部資料，無法從系統內復原。確定清除？",
        )
        for message in messages:
            reply = QMessageBox.question(self, "全部清除確認", message)
            if reply != QMessageBox.Yes:
                return
        self.create_safety_backup("delete-all")
        REPOSITORY.delete_all_customers()
        self.checked_record_ids.clear()
        log_operation("全部清除", "清空全部資料", "")
        self.new_record()
        self.refresh_records()

    def encrypt_existing_records(self):
        if not self.ensure_can_modify("加密既有資料"):
            return
        reply = QMessageBox.question(
            self,
            "加密既有資料",
            "這會將目前資料庫裡的姓名、身分證、地址、備註、出訪記錄轉為加密儲存。確定要執行嗎？",
        )
        if reply != QMessageBox.Yes:
            return

        self.create_safety_backup("encrypt")
        updated = REPOSITORY.encrypt_existing_customers(self.fernet)

        self.refresh_records(self.selected_record_id)
        log_operation("加密資料", f"處理 {updated} 筆", "")
        QMessageBox.information(self, "加密完成", f"已處理 {updated} 筆既有資料。")


def main():
    api_mode = desktop_api_requested()
    if api_mode:
        init_remote_client_settings()
    else:
        init_db()
    startup_backup_path = None
    if not api_mode:
        apply_default_import_profile(REPOSITORY)
        apply_backup_policy()
        startup_backup_path = ensure_daily_backup()
    app = QApplication.instance() or QApplication(sys.argv)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    app.setStyle("Fusion")
    apply_font_size(app, get_saved_font_size_key())
    apply_app_style(app)
    api_client = None
    if api_mode:
        try:
            api_client = DesktopApiClient(
                os.environ.get(DESKTOP_API_URL_ENV, DEFAULT_API_URL)
            )
            health = api_client.health()
            if health.get("backend") != "postgresql":
                raise DesktopApiError("API 目前不是 PostgreSQL 模式")
        except (DesktopApiError, ValueError) as exc:
            QMessageBox.critical(
                None,
                "PostgreSQL API 無法使用",
                f"無法啟動 PostgreSQL 正式版。\n\n{exc}",
            )
            return 1
        configure_api_authentication(api_client)
    encryption_key = require_login(setup_mode=False if api_mode else None)
    if not encryption_key:
        return 0
    record_repository = (
        DesktopApiRecordRepository(api_client, make_fernet(encryption_key))
        if api_mode
        else None
    )
    window = LandApp(
        encryption_key,
        startup_backup_path=startup_backup_path,
        record_repository=record_repository,
        api_mode=api_mode,
        current_user=api_client.current_user if api_client else None,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
