import gc
import json
import os
import sqlite3
import sys
from base64 import b64decode, b64encode
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet
from customer_analytics import build_dashboard_stats
from customer_auth import AuthDialog, configure_auth_dialog, validate_new_password
from customer_backup_status import (
    BackupManagementDialog,
    BackupStatusMixin,
    ServerBackupRestoreDialog,
    ServerBackupTargetsDialog,
    format_storage_size,
)
from customer_client_connection import (
    SERVER_API_URL_SETTING_KEY,
    normalize_server_api_url,
    server_ip_from_api_url,
)
from customer_client_certificate import (
    ClientCertificateError,
    ensure_trusted_server_ca,
)
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
    VisitCalendarDialog,
    WatchlistDialog,
    configure_dialogs,
)
from customer_extra_dialogs import (
    ApplyTemplateDialog,
    AttachmentDialog,
    BatchCustomerCustomValuesDialog,
    BatchCustomerTagsDialog,
    CaseSelectDialog,
    ContactLogDialog,
    CustomFieldManagementDialog,
    CustomerCustomValuesDialog,
    CustomerTagsDialog,
    FieldVisitScheduleDialog,
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
from customer_health import SystemHealthCheckService
from customer_import_controller import ImportControllerMixin, configure_import_controller
from customer_desktop import open_local_path
from customer_desktop_data import DesktopDataAccess
from customer_desktop_support import DesktopSupportMixin
from customer_desktop_state import DesktopStateMixin
from customer_display import attachment_display_name, compact_summary_text, format_attachment_summary
from customer_desktop_api import (
    DesktopApiClient,
    DesktopApiError,
    DesktopApiRecordRepository,
)
from customer_error_handler import get_error_log_path
from customer_fields import LAND_FIELDS
from customer_management_workflows import ManagementWorkflowMixin
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
from customer_record_workflows import RecordWorkflowMixin
from customer_productivity_workflows import ProductivityWorkflowMixin
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
from customer_preferences import decode_table_preferences, encode_table_preferences, sanitize_saved_searches
from customer_search_controller import SearchControllerMixin, configure_search_controller
from customer_selection_workflows import SelectionWorkflowMixin
from customer_search_presets import SearchPresetMixin, configure_search_presets
from customer_table_ui import build_customer_table_ui
from customer_ui_state import UiStateMixin, configure_ui_state
from customer_version import (
    desktop_client_version_label,
    full_version_text,
    version_label,
)
from customer_window_ui import DesktopWindowMixin
from customer_settings_workflows import SettingsWorkflowMixin
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
    QInputDialog,
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


# Python's cyclic garbage collector can run its collection pass at any
# allocation point, including deep inside PySide6/shiboken's C++ callback
# handling for a QThread's cross-thread queued signal delivery (search,
# Excel import, and offsite-backup workers all use this pattern -- see
# customer_search_controller.py, customer_import_controller.py, and
# customer_productivity_workflows.py). If a collection happens to land while
# such a callback is mid-flight, PySide6 can crash with a Windows access
# violation; this was reproduced reliably by running the full desktop test
# suite (disabling the collector made it disappear across many repeated
# runs, while every other mitigation attempted on the app's own thread
# lifecycle left it unchanged). Reference counting still reclaims ordinary
# objects immediately without the collector; only reference *cycles* would
# accumulate, so periodic_gc_collect() below reclaims those explicitly, but
# only while no background QThread could be in flight.
gc.disable()


def periodic_gc_collect(window):
    """Run a manual collection pass, but only when it's actually safe to.

    Never called while a search, Excel import, or offsite-backup QThread
    might still be delivering a queued cross-thread signal -- see the
    gc.disable() comment above.
    """
    if window.record_searches:
        return
    if getattr(window, "excel_thread", None) is not None:
        return
    if getattr(window, "offsite_backup_thread", None) is not None:
        return
    gc.collect()


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
PRIVACY_MASK_SETTING_KEY = "privacy_mask_enabled"
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
    ("full_land_number", "完整地號"),
    ("owner_count", "地主數"),
    ("ownership_count", "持分筆數"),
    ("land_use", "地目／使用分區"),
    ("status_summary", "狀態摘要"),
    *LAND_FIELDS,
    ("share", "持分"),
    ("ownership_area", "權利範圍面積"),
    ("phone", "電話"),
    ("customer_status", "客戶狀態"),
    ("note_summary", "備註摘要"),
    *MANAGEMENT_FIELDS,
]

FILTERABLE_FIELDS = [
    ("all", "全部欄位"),
    ("district", "地區"),
    ("section", "地段"),
    ("subsection", "小段"),
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
    ("subsection", "小段"),
    ("registration_order", "序號"),
    ("land_number", "地號"),
    ("area", "面積/m2"),
    ("declared_value", "公告現值"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("ping", "坪數"),
    ("total_declared_value", "總現值/元"),
    ("owner_name", "姓名"),
    ("owner_count", "地主數量"),
    ("ownership_count", "持分筆數"),
    ("share", "持分"),
    ("ownership_area", "權利範圍面積"),
    ("customer_status", "客戶狀態"),
    ("case_names", "案件"),
    ("tag_names", "標籤"),
    ("attachment_count", "附件數"),
    ("last_contact", "最近聯絡"),
    ("next_follow_up", "下次追蹤"),
    ("follow_up_status", "追蹤狀態"),
]

TABLE_BATCH_SIZE = 100
ASYNC_SEARCH_THRESHOLD = 500
SELECTION_SAVE_DELAY_MS = 300
GC_COLLECT_INTERVAL_MS = 10 * 60 * 1000

TABLE_WIDTHS = {
    "checked": 52,
    "rowid": 68,
    "full_land_number": 250,
    "owner_count": 78,
    "ownership_count": 88,
    "land_use": 130,
    "status_summary": 170,
    "district": 95,
    "section": 100,
    "subsection": 100,
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
    "share": 90,
    "ownership_area": 120,
    "phone": 120,
    "customer_status": 100,
    "note_summary": 180,
}

ADVANCED_SEARCH_FIELDS = [
    ("district", "地區"),
    ("section", "地段"),
    ("subsection", "小段"),
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
    ("subsection", "小段"),
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
        QLineEdit, QPlainTextEdit, QComboBox {
            background-color: #111827;
            color: #f9fafb;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 6px 10px;
            selection-background-color: #365d8d;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 1px solid #3b82f6;
        }
        QLineEdit:disabled, QComboBox:disabled {
            color: #6b7280;
            background-color: #1f2937;
            border-color: #374151;
        }
        QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {
            background-color: #262626;
            color: #cbd5e1;
        }
        QTableView, QTreeView, QTableWidget {
            background-color: #2d2d2d;
            color: #f9fafb;
            border: 1px solid #454545;
            border-radius: 6px;
        }
        QTableView:focus, QTreeView:focus, QTableWidget:focus {
            border: 1px solid #6ea8ff;
        }
        QPushButton {
            background-color: #374151;
            color: #f9fafb;
            border: 1px solid #4b5563;
            border-radius: 8px;
            padding: 6px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #4b5563;
            border-color: #6b7280;
        }
        QPushButton:pressed {
            background-color: #1f2937;
        }
        QPushButton:disabled {
            background-color: #1f2937;
            color: #6b7280;
            border-color: #374151;
        }
        QComboBox::drop-down {
            border: none;
            width: 22px;
        }
        QComboBox QAbstractItemView {
            background-color: #111827;
            color: #f9fafb;
            border: 1px solid #374151;
            selection-background-color: #365d8d;
            outline: none;
        }
        QMenu {
            background-color: #1f2937;
            color: #f9fafb;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 4px;
        }
        QMenu::item {
            padding: 6px 22px;
            border-radius: 6px;
        }
        QMenu::item:selected {
            background-color: #365d8d;
            color: #ffffff;
        }
        QMenu::item:disabled {
            color: #6b7280;
        }
        QMenu::separator {
            height: 1px;
            background: #374151;
            margin: 4px 8px;
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
        QTreeView {
            background-color: #2d2d2d;
            alternate-background-color: #2d2d2d;
        }
        QTableView::item {
            padding: 4px 6px;
        }
        QTableView::item:selected, QTreeView::item:selected, QTableWidget::item:selected {
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


def prompt_server_api_url(parent=None, current_url=""):
    """Ask for a NetBird server IP until it is valid or the user cancels."""

    current_ip = ""
    if current_url:
        try:
            current_ip = server_ip_from_api_url(current_url)
        except ValueError:
            current_ip = ""
    while True:
        value, accepted = QInputDialog.getText(
            parent,
            "伺服器連線設定",
            "請輸入家中伺服器的 NetBird IP：\n例如：100.107.252.170",
            QLineEdit.Normal,
            current_ip,
        )
        if not accepted:
            return None
        try:
            return normalize_server_api_url(value)
        except ValueError as exc:
            QMessageBox.warning(parent, "IP 格式不正確", str(exc))
            current_ip = str(value or "").strip()


def create_healthy_desktop_api_client(api_url):
    client = DesktopApiClient(api_url)
    health = client.health()
    if health.get("backend") != "postgresql":
        raise DesktopApiError("連線目標不是 PostgreSQL 正式伺服器。")
    if int(health.get("schema_version") or 0) < 2:
        raise DesktopApiError("家中伺服器資料結構版本過舊，請先更新伺服器。")
    return client


def prepare_server_ca_for_api(api_url, parent=None):
    """Download, confirm, and pin the selected home server's public CA."""

    def confirm(downloaded, existing):
        changed = existing is not None
        title = "家中伺服器憑證已變更" if changed else "信任家中伺服器"
        description = (
            "偵測到家中伺服器的公開憑證已變更。"
            if changed
            else "這是此電腦第一次連線到這台家中伺服器。"
        )
        message = (
            f"{description}\n\n"
            f"NetBird IP：{downloaded.server_ip}\n"
            f"SHA-256 指紋：\n{downloaded.display_fingerprint}\n\n"
            "請確認這是你的家中主機，再選擇「是」保存公開憑證。"
        )
        return (
            QMessageBox.question(
                parent,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    try:
        ca_path = ensure_trusted_server_ca(
            api_url,
            confirm_callback=confirm,
        )
    except ClientCertificateError as exc:
        raise DesktopApiError(str(exc)) from exc
    os.environ["LAND_CUSTOMER_API_CA_CERT"] = str(ca_path)
    return ca_path


def connect_desktop_api(parent=None):
    """Resolve, validate, test, and persist the user-selected server address."""

    saved_url = str(get_setting(SERVER_API_URL_SETTING_KEY, "") or "").strip()
    environment_url = str(os.environ.get(DESKTOP_API_URL_ENV, "") or "").strip()
    candidate = saved_url or environment_url
    while True:
        if candidate:
            try:
                candidate = normalize_server_api_url(candidate)
                prepare_server_ca_for_api(candidate, parent)
                client = create_healthy_desktop_api_client(candidate)
            except (DesktopApiError, ValueError) as exc:
                QMessageBox.warning(
                    parent,
                    "無法連線到家中伺服器",
                    f"目前設定：{candidate}\n\n{exc}\n\n請重新輸入家中伺服器 IP。",
                )
                candidate = ""
                continue
            set_setting(SERVER_API_URL_SETTING_KEY, candidate)
            os.environ[DESKTOP_API_URL_ENV] = candidate
            return client

        candidate = prompt_server_api_url(parent, saved_url or environment_url)
        if not candidate:
            return None


def change_server_connection(parent):
    """Test and store a new server address selected from the Settings menu."""

    repository = parent.active_record_repository()
    current_url = getattr(getattr(repository, "client", None), "base_url", "")
    selected_url = prompt_server_api_url(parent, current_url)
    if not selected_url:
        return None
    try:
        prepare_server_ca_for_api(selected_url, parent)
        create_healthy_desktop_api_client(selected_url)
    except (DesktopApiError, ValueError) as exc:
        QMessageBox.critical(
            parent,
            "伺服器設定未儲存",
            f"無法使用 {selected_url}：\n\n{exc}",
        )
        return False
    set_setting(SERVER_API_URL_SETTING_KEY, selected_url)
    os.environ[DESKTOP_API_URL_ENV] = selected_url
    QMessageBox.information(
        parent,
        "伺服器設定已儲存",
        f"已儲存：{selected_url}\n\n請關閉並重新開啟桌面程式後使用新連線。",
    )
    return True


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
    DesktopSupportMixin,
    DesktopStateMixin,
    DesktopWindowMixin,
    SettingsWorkflowMixin,
    ProductivityWorkflowMixin,
    SelectionWorkflowMixin,
    RecordWorkflowMixin,
    ManagementWorkflowMixin,
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
        self.admin_username = ADMIN_USERNAME
        self.advanced_search_setting_key = ADVANCED_SEARCH_SETTING_KEY
        self.readonly_setting_key = READONLY_MODE_SETTING_KEY
        self.privacy_mask_setting_key = PRIVACY_MASK_SETTING_KEY
        self.record_repository = record_repository or self.repository
        self.data_access = DesktopDataAccess(self.repository, self.record_repository)
        self.api_mode = bool(api_mode)
        self.database = DATABASE
        self.attachments_dir = ATTACHMENTS_DIR
        self.app_dir = APP_DIR
        self.table_columns = TABLE_COLUMNS
        self.table_widths = TABLE_WIDTHS
        self.filterable_fields = FILTERABLE_FIELDS
        self.sortable_fields = SORTABLE_FIELDS
        self.land_fields = LAND_FIELDS
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
        displayed_version = (
            desktop_client_version_label() if self.api_mode else version_label()
        )
        self.setWindowTitle(f"土地資料系統 {displayed_version}{mode_label}")
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
        self.privacy_mask_enabled = (
            self.repository.get_setting(self.privacy_mask_setting_key, "0") == "1"
        )
        self.current_owner_name_plain = ""
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
        self.table_proxy_model = None
        self.record_menu = None
        self.land_menu = None
        # Only explicit user actions may change this set.  Search expansion is
        # temporary and deliberately tracked separately.
        self.user_expanded_land_ids: set[int] = set()
        self.search_expanded_land_ids: set[int] = set()
        self.restoring_tree_state = False
        self.applying_programmatic_expansion = False
        # Kept for compatibility with older tests/extensions.  New code checks
        # the two explicit flags above.
        self._applying_land_expansion = False
        self._land_search_auto_expand = False
        self.selected_land_state_id = None
        self.land_count_label = None
        self.land_page_label = None
        self.previous_land_page_button = None
        self.next_land_page_button = None
        self.data_menu = None
        self.tools_menu = None
        self.tool_submenus = {}
        self.settings_menu = None
        self.management_summary_label = None
        self.show_checked_only_action = None
        self.readonly_mode_action = None
        self.privacy_mask_action = None
        self.excel_thread = None
        self.excel_worker = None
        self.record_search_request_id = 0
        self.record_searches = {}
        # (target_id, tree_state, search_auto_expand) for each in-flight
        # record_searches request id -- see start_record_search()'s signal
        # connections for why this is kept separate from record_searches.
        self._record_search_context = {}
        self.offsite_backup_thread = None
        self.offsite_backup_worker = None

        # The process-wide collector is off (see the gc.disable() comment
        # at the top of this module); reclaim reference cycles manually on
        # an interval, but only at moments no background QThread could be
        # mid-signal -- periodic_gc_collect() checks that itself.
        self.gc_collect_timer = QTimer(self)
        self.gc_collect_timer.setInterval(GC_COLLECT_INTERVAL_MS)
        self.gc_collect_timer.timeout.connect(
            lambda: periodic_gc_collect(self)
        )
        self.gc_collect_timer.start()

        self.create_layout()
        self.apply_owner_contacts_tab_visibility()
        if self.api_mode:
            self.configure_api_mode_ui()
            self.setup_notification_status()
            self.setup_backup_status()
        else:
            self.setup_backup_status()
            self.setup_notification_status()
            self.setup_offsite_backup()
        # Apply the saved font size (which touches the tree view's
        # stylesheet and triggers Qt to synchronously walk every row for
        # layout recomputation) BEFORE refresh_records() populates any
        # data. For a large database, refresh_records() sets a preview into
        # the table model and starts a background search thread; a report
        # from real use showed the stylesheet-triggered walk landing while
        # that background thread's queued "results ready" signal was
        # already pending delivery, so the walk was reading QModelIndex
        # objects into _TreeNode instances the model had already replaced
        # via beginResetModel()/endResetModel() -- an
        # AttributeError: '_TreeNode' object has no attribute 'kind' from
        # a stale internalPointer(). Doing this while the tree is still
        # empty removes the race entirely; row content plays no part in
        # font-size/row-height application.
        self.apply_saved_font_size()
        self.refresh_records()
        if self.startup_backup_path:
            QTimer.singleShot(0, self.show_startup_backup_notice)







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
        api_client = connect_desktop_api()
        if api_client is None:
            return 0
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
