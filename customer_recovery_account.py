"""Securely transfer one authenticated SQLite account to PostgreSQL.

The recovery package never contains the plaintext password or the plaintext
data key.  The PostgreSQL importer asks for the account password locally and
proves that the wrapped data key can decrypt existing server data before it
adds the account.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from base64 import urlsafe_b64decode
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import InvalidToken

from customer_security import (
    ENCRYPTION_PREFIX,
    derive_encryption_key,
    hash_password,
    make_fernet,
    verify_password,
)


PACKAGE_FORMAT = "land-customer-recovery-account"
PACKAGE_VERSION = 1
PACKAGE_SUFFIX = ".lcs-account"
ALLOWED_ROLES = {"admin", "editor", "viewer"}
ACCOUNT_FIELDS = (
    "username",
    "display_name",
    "role",
    "active",
    "password_salt",
    "password_hash",
    "encryption_salt",
    "wrapped_data_key",
    "created_at",
)


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_checksum(payload):
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _validate_hex(value, *, field, byte_length):
    text = str(value or "").strip()
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"帳號恢復檔的 {field} 格式不正確。") from exc
    if len(raw) != byte_length:
        raise ValueError(f"帳號恢復檔的 {field} 長度不正確。")
    return text


def _validate_wrapped_key(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("此帳號沒有獨立封裝的資料金鑰，不能用於安全恢復。")
    try:
        decoded = urlsafe_b64decode(text.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("帳號恢復檔的資料金鑰格式不正確。") from exc
    if len(decoded) < 32:
        raise ValueError("帳號恢復檔的資料金鑰內容不完整。")
    return text


def validate_account(account):
    if not isinstance(account, dict):
        raise ValueError("帳號恢復檔缺少帳號資料。")
    missing = [name for name in ACCOUNT_FIELDS if name not in account]
    if missing:
        raise ValueError(f"帳號恢復檔缺少欄位：{', '.join(missing)}。")
    username = str(account.get("username") or "").strip()
    if not username or len(username) > 100:
        raise ValueError("帳號名稱不正確。")
    role = str(account.get("role") or "").strip().lower()
    if role not in ALLOWED_ROLES:
        raise ValueError("帳號角色不正確。")
    return {
        "username": username,
        "display_name": str(account.get("display_name") or "").strip(),
        "role": role,
        "active": bool(account.get("active")),
        "password_salt": _validate_hex(
            account.get("password_salt"), field="password_salt", byte_length=16
        ),
        "password_hash": _validate_hex(
            account.get("password_hash"), field="password_hash", byte_length=32
        ),
        "encryption_salt": _validate_hex(
            account.get("encryption_salt"), field="encryption_salt", byte_length=16
        ),
        "wrapped_data_key": _validate_wrapped_key(account.get("wrapped_data_key")),
        "created_at": str(account.get("created_at") or "").strip()
        or datetime.now(timezone.utc).isoformat(),
    }


def create_recovery_package(sqlite_database, username):
    database_path = Path(sqlite_database).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"找不到單機資料庫：{database_path}")
    uri = f"file:{database_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT username, display_name, role, active, password_salt,
                   password_hash, encryption_salt, wrapped_data_key, created_at
            FROM users
            WHERE lower(username) = lower(?)
            """,
            (str(username).strip(),),
        ).fetchall()
    if not rows:
        raise ValueError(f"單機版找不到帳號：{username}")
    if len(rows) != 1:
        raise ValueError("單機資料庫存在名稱重複的帳號，已停止匯出。")
    account = validate_account(dict(rows[0]))
    payload = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account,
    }
    return {**payload, "payload_sha256": _payload_checksum(payload)}


def write_recovery_package(sqlite_database, username, output_path, *, overwrite=False):
    destination = Path(output_path).resolve()
    if destination.suffix.lower() != PACKAGE_SUFFIX:
        raise ValueError(f"帳號恢復檔必須使用 {PACKAGE_SUFFIX} 副檔名。")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"檔案已存在：{destination}")
    package = create_recovery_package(sqlite_database, username)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(package, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_recovery_package(package_path):
    source = Path(package_path).resolve()
    if source.suffix.lower() != PACKAGE_SUFFIX:
        raise ValueError(f"帳號恢復檔必須使用 {PACKAGE_SUFFIX} 副檔名。")
    try:
        package = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("帳號恢復檔無法讀取或格式已損壞。") from exc
    if package.get("format") != PACKAGE_FORMAT or package.get("version") != PACKAGE_VERSION:
        raise ValueError("帳號恢復檔版本不受支援。")
    supplied_checksum = str(package.get("payload_sha256") or "").strip().lower()
    payload = {key: value for key, value in package.items() if key != "payload_sha256"}
    if not supplied_checksum or supplied_checksum != _payload_checksum(payload):
        raise ValueError("帳號恢復檔校驗失敗，檔案可能不完整。")
    return validate_account(package.get("account"))


def unwrap_account_data_key(account, password):
    if not verify_password(password, account["password_salt"], account["password_hash"]):
        raise ValueError("新帳號密碼不正確，未匯入任何資料。")
    wrapping_key = derive_encryption_key(password, account["encryption_salt"])
    try:
        return make_fernet(wrapping_key).decrypt(
            account["wrapped_data_key"].encode("ascii")
        )
    except (InvalidToken, ValueError) as exc:
        raise ValueError("帳號恢復檔無法解開資料金鑰，未匯入任何資料。") from exc


def _encrypted_sample(connection):
    candidates = (
        ("owners", "owner_name"),
        ("owners", "address"),
        ("ownerships", "name"),
        ("ownerships", "note"),
    )
    for table, column in candidates:
        row = connection.execute(
            f"SELECT {column} FROM {table} WHERE {column} LIKE %s LIMIT 1",
            (f"{ENCRYPTION_PREFIX}%",),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    return ""


def prove_data_key_matches_server(connection, data_key):
    sample = _encrypted_sample(connection)
    if not sample:
        return False
    token = sample[len(ENCRYPTION_PREFIX) :]
    try:
        make_fernet(data_key).decrypt(token.encode("ascii"))
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise ValueError(
            "此單機帳號的資料金鑰與家中伺服器不相符，未匯入任何資料。"
        ) from exc
    return True


def import_recovery_account(package_path, password, dsn):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("伺服器缺少 PostgreSQL 驅動程式。") from exc

    account = load_recovery_package(package_path)
    data_key = unwrap_account_data_key(account, password)
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (741_202_607,))
        matched_sample = prove_data_key_matches_server(connection, data_key)
        existing = connection.execute(
            """
            SELECT id, username, password_salt, password_hash,
                   encryption_salt, wrapped_data_key
            FROM users WHERE lower(username) = lower(%s)
            """,
            (account["username"],),
        ).fetchall()
        if len(existing) > 1:
            raise ValueError("伺服器存在名稱重複的帳號，已停止匯入。")
        if existing:
            row = existing[0]
            same_credentials = tuple(row[2:]) == (
                account["password_salt"],
                account["password_hash"],
                account["encryption_salt"],
                account["wrapped_data_key"],
            )
            if not same_credentials:
                raise ValueError(
                    f"伺服器已存在不同的帳號 {row[1]}，未覆蓋原帳號。"
                )
            return {
                "status": "already_imported",
                "username": str(row[1]),
                "role": account["role"],
                "data_key_verified": matched_sample,
            }
        connection.execute(
            """
            INSERT INTO users (
                username, display_name, role, active, password_salt,
                password_hash, encryption_salt, wrapped_data_key,
                created_at, last_login_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                account["username"],
                account["display_name"],
                account["role"],
                account["active"],
                account["password_salt"],
                account["password_hash"],
                account["encryption_salt"],
                account["wrapped_data_key"],
                account["created_at"],
            ),
        )
    return {
        "status": "imported",
        "username": account["username"],
        "role": account["role"],
        "data_key_verified": matched_sample,
    }


def recover_admin_password(
    dsn,
    recovery_username,
    recovery_password,
    new_admin_password,
):
    """Reset admin locally after proving another active account owns the data key."""

    if len(str(new_admin_password)) < 10:
        raise ValueError("新的 admin 密碼至少需要 10 個字元。")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("伺服器缺少 PostgreSQL 驅動程式。") from exc

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (741_202_607,))
        rows = connection.execute(
            """
            SELECT id, username, role, active, password_salt, password_hash,
                   encryption_salt, wrapped_data_key
            FROM users WHERE lower(username) = lower(%s)
            """,
            (str(recovery_username).strip(),),
        ).fetchall()
        if len(rows) != 1 or not bool(rows[0][3]):
            raise ValueError("驗證帳號不存在或未啟用，未修改 admin 密碼。")
        row = rows[0]
        account = validate_account(
            {
                "username": row[1],
                "display_name": "",
                "role": row[2],
                "active": row[3],
                "password_salt": row[4],
                "password_hash": row[5],
                "encryption_salt": row[6],
                "wrapped_data_key": row[7],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        data_key = unwrap_account_data_key(account, recovery_password)
        matched_sample = prove_data_key_matches_server(connection, data_key)
        admin_rows = connection.execute(
            "SELECT id FROM users WHERE lower(username) = 'admin'"
        ).fetchall()
        if len(admin_rows) > 1:
            raise ValueError("伺服器存在多個 admin 帳號，未進行修改。")
        password_salt, password_hash = hash_password(new_admin_password)
        encryption_salt = os.urandom(16).hex()
        wrapped_data_key = make_fernet(
            derive_encryption_key(new_admin_password, encryption_salt)
        ).encrypt(data_key).decode("ascii")
        if admin_rows:
            connection.execute(
                """
                UPDATE users
                SET password_salt=%s, password_hash=%s, encryption_salt=%s,
                    wrapped_data_key=%s, role='admin', active=TRUE
                WHERE id=%s
                """,
                (
                    password_salt,
                    password_hash,
                    encryption_salt,
                    wrapped_data_key,
                    admin_rows[0][0],
                ),
            )
            recovery_status = "admin_password_reset"
            recovery_summary = "家中主機離線重設 admin 密碼"
        else:
            connection.execute(
                """
                INSERT INTO users (
                    username, display_name, role, active, password_salt,
                    password_hash, encryption_salt, wrapped_data_key
                ) VALUES ('admin', %s, 'admin', TRUE, %s, %s, %s, %s)
                """,
                (
                    "系統管理員",
                    password_salt,
                    password_hash,
                    encryption_salt,
                    wrapped_data_key,
                ),
            )
            recovery_status = "admin_account_created"
            recovery_summary = "家中主機離線建立 admin 帳號"
        connection.execute(
            """
            INSERT INTO operation_logs (
                action_type, summary, detail, actor_username
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                "admin_password_recovery",
                recovery_summary,
                "已驗證既有帳號與資料金鑰；未修改客戶或土地資料。",
                str(row[1]),
            ),
        )
    return {
        "status": recovery_status,
        "username": "admin",
        "verified_by": str(row[1]),
        "data_key_verified": matched_sample,
    }
