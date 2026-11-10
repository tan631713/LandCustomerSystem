"""Read-only check: are different people sharing one owner because of 5-character IDs?

``customer_postgres_keys.owner_key_for`` builds the owner key from the
identity number alone whenever one is filled in.  The owner data mostly keeps
5-character identity numbers (前4碼＋末碼, e.g. H2211), and within one region
those collide, so different people may have been merged into one owner row.

This report only counts.  It never prints a name or an identity number, and
it never writes: every statement is a SELECT inside a READ ONLY transaction,
and the administrator login is checked here without the normal login's
``last_login_at`` update.

Run on the home server:  LandCustomerServer.exe --diagnose-owner-ids
(or from source: python tools\\diagnose_owner_id_collisions.py)
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from customer_owner_match import identity_match_key, normalize_identity, normalize_owner_name
from customer_security import (
    DECRYPTION_ERROR_TEXT,
    decrypt_value,
    derive_encryption_key,
    make_fernet,
    verify_password,
)

READ_ONLY_STATEMENT = re.compile(r"^\s*(SELECT|SHOW)\b", re.IGNORECASE)

USER_QUERY = """
    SELECT id, username, role, active, password_salt, password_hash,
           encryption_salt, wrapped_data_key
    FROM users WHERE username = %s
"""
OWNER_QUERY = "SELECT id, owner_name, external_id FROM owners"
OWNERSHIP_QUERY = """
    SELECT id, owner_id, owner_name_override, external_id_override
    FROM ownerships
"""


class DiagnosticError(RuntimeError):
    """Shown to the person running the check as is."""


class ReadOnlyConnection:
    """Refuses anything but SELECT / SHOW before it reaches the database."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        if not READ_ONLY_STATEMENT.match(str(sql)):
            raise DiagnosticError("診斷工具只允許 SELECT 查詢。")
        return self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)


def admin_data_key(conn, username, password):
    """The administrator's data key, checked without writing anything."""

    row = conn.execute(USER_QUERY, (str(username),)).fetchone()
    if row is None or not row["active"] or not verify_password(
        password, row["password_salt"], row["password_hash"]
    ):
        raise DiagnosticError("帳號或密碼不正確。")
    if str(row["role"] or "") != "admin":
        raise DiagnosticError("需要管理員（admin）帳號才能解密統計。")
    wrapping_key = derive_encryption_key(password, row["encryption_salt"])
    if not row["wrapped_data_key"]:
        return bytes(wrapping_key)
    try:
        return bytes(
            make_fernet(wrapping_key).decrypt(row["wrapped_data_key"].encode("ascii"))
        )
    except Exception as exc:  # noqa: BLE001 - any failure means a wrong key
        raise DiagnosticError("無法解開資料金鑰，請確認帳號密碼。") from exc


def identity_length_bucket(value):
    text = normalize_identity(value)
    if not text:
        return "blank"
    if len(text) == 5:
        return "five"
    if len(text) == 10:
        return "ten"
    return "other"


def collect_statistics(conn, data_key):
    """Counts only; no name or identity number leaves this function."""

    fernet = make_fernet(data_key)
    owners = {}
    decryption_failures = 0
    for row in conn.execute(OWNER_QUERY).fetchall():
        name = decrypt_value(fernet, row.get("owner_name")) or ""
        identity = decrypt_value(fernet, row.get("external_id")) or ""
        if DECRYPTION_ERROR_TEXT in (name, identity):
            decryption_failures += 1
        owners[int(row["id"])] = (name, identity)

    length_counts = {"blank": 0, "five": 0, "ten": 0, "other": 0}
    for _name, identity in owners.values():
        length_counts[identity_length_bucket(identity)] += 1

    names_by_owner = defaultdict(set)
    ownerships_by_owner = defaultdict(int)
    names_by_key = defaultdict(set)
    ownerships_by_key = defaultdict(int)
    ownership_total = 0
    for row in conn.execute(OWNERSHIP_QUERY).fetchall():
        ownership_total += 1
        owner_id = int(row["owner_id"])
        owner_name, owner_identity = owners.get(owner_id, ("", ""))
        name = decrypt_value(fernet, row.get("owner_name_override")) or owner_name
        identity = decrypt_value(fernet, row.get("external_id_override")) or owner_identity
        normalized_name = normalize_owner_name(name)
        ownerships_by_owner[owner_id] += 1
        if normalized_name:
            names_by_owner[owner_id].add(normalized_name)
        key = identity_match_key(identity)
        if key is not None:
            ownerships_by_key[key] += 1
            if normalized_name:
                names_by_key[key].add(normalized_name)

    mixed_owners = [owner_id for owner_id, names in names_by_owner.items() if len(names) >= 2]
    colliding_keys = [key for key, names in names_by_key.items() if len(names) >= 2]
    return {
        "owner_total": len(owners),
        "owners_with_land": len(ownerships_by_owner),
        "ownership_total": ownership_total,
        "decryption_failures": decryption_failures,
        "identity_lengths": length_counts,
        "owners_with_several_names": len(mixed_owners),
        "ownerships_of_those_owners": sum(ownerships_by_owner[o] for o in mixed_owners),
        "five_key_groups_with_several_names": len(colliding_keys),
        "ownerships_in_those_groups": sum(ownerships_by_key[k] for k in colliding_keys),
    }


def format_report(stats, *, version="", now=None):
    now = now or datetime.now()
    lengths = stats["identity_lengths"]
    lines = [
        "土地資料系統：地主身分證撞號診斷（唯讀，只有數字）",
        f"產生時間：{now:%Y-%m-%d %H:%M:%S}" + (f"　伺服器版本：v{version}" if version else ""),
        "",
        f"地主總數（owners）：{stats['owner_total']}",
        f"　其中名下有土地的地主：{stats['owners_with_land']}",
        f"持分總筆數（ownerships）：{stats['ownership_total']}",
        "",
        "地主身分證長度分佈：",
        f"　空白：{lengths['blank']}",
        f"　5 碼：{lengths['five']}",
        f"　10 碼：{lengths['ten']}",
        f"　其他長度：{lengths['other']}",
        "",
        f"名下持分出現 2 種以上不同姓名的地主（疑似被錯誤合併）：{stats['owners_with_several_names']}",
        f"　這些地主名下的持分筆數：{stats['ownerships_of_those_owners']}",
        f"「前4碼＋末碼」相同但姓名不同的群組數：{stats['five_key_groups_with_several_names']}",
        f"　這些群組牽涉的持分筆數：{stats['ownerships_in_those_groups']}",
    ]
    if stats["decryption_failures"]:
        lines += ["", f"注意：有 {stats['decryption_failures']} 位地主資料無法解密，未納入姓名比較。"]
    lines += [
        "",
        "說明：姓名比較前會去掉空白、全半形與台/臺差異；稱呼（○小姐、○先生）與全名算不同姓名，",
        "所以第一項包含同一人用不同稱呼的情況，數字是上限，需要再人工抽查。",
        "本報告只用 SELECT 查詢、交易設為唯讀，沒有修改任何資料。",
    ]
    return "\n".join(lines) + "\n"


def run_diagnostics(dsn, username, password, *, output_dir, connect=None, version=""):
    """Connect read-only, check the admin, count, write the txt; returns its path."""

    if connect is None:
        import psycopg
        from psycopg.rows import dict_row

        def connect(target):
            return psycopg.connect(target, row_factory=dict_row, connect_timeout=5)

    if not str(dsn or "").strip():
        raise DiagnosticError("找不到這台主機的 PostgreSQL 設定，請在家中伺服器上執行。")
    raw = connect(dsn)
    try:
        if hasattr(raw, "read_only"):
            raw.read_only = True
        conn = ReadOnlyConnection(raw)
        state = conn.execute("SHOW transaction_read_only").fetchone()
        value = state.get("transaction_read_only") if isinstance(state, dict) else None
        if str(value).lower() not in {"on", "true"}:
            raise DiagnosticError("無法把資料庫連線設成唯讀，已停止。")
        data_key = admin_data_key(conn, username, password)
        stats = collect_statistics(conn, data_key)
    finally:
        try:
            raw.rollback()
        finally:
            raw.close()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = output_dir / f"owner-id-diagnostics-{now:%Y%m%d-%H%M%S}.txt"
    path.write_text(format_report(stats, version=version, now=now), encoding="utf-8-sig")
    return path, stats
