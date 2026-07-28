"""Create the local application role/database without storing the admin password."""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
from pathlib import Path
from urllib.parse import quote

from customer_api.local_postgres import (
    default_protected_dsn_path,
    load_postgres_dsn,
    save_postgres_dsn,
)


PROJECT_DIR = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_DIR / "local-postgres-setup-report.json"
APP_ROLE = "land_customer_app"
APP_DATABASE = "land_customer"


def build_dsn(password, *, host="127.0.0.1", port=5432):
    encoded_password = quote(str(password), safe="")
    return (
        f"postgresql://{APP_ROLE}:{encoded_password}@{host}:{int(port)}/"
        f"{APP_DATABASE}"
    )


def _stored_connection_works(psycopg, dsn):
    if not dsn:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def setup_database(admin_password, *, host="127.0.0.1", port=5432, rotate=False):
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("請先安裝 requirements-server.txt") from exc

    protected_path = default_protected_dsn_path()
    try:
        stored_dsn = load_postgres_dsn(protected_path)
    except OSError:
        stored_dsn = ""
    reuse_stored = not rotate and _stored_connection_works(psycopg, stored_dsn)

    with psycopg.connect(
        dbname="postgres",
        user="postgres",
        password=admin_password,
        host=host,
        port=int(port),
        connect_timeout=5,
        autocommit=True,
    ) as admin:
        server_version = admin.execute("SHOW server_version").fetchone()[0]
        listen_addresses = admin.execute("SHOW listen_addresses").fetchone()[0]
        role_exists = bool(
            admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
            ).fetchone()
        )

        app_password = None
        if not role_exists:
            app_password = secrets.token_urlsafe(32)
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_ROLE), sql.Literal(app_password)
                )
            )
        elif not reuse_stored:
            app_password = secrets.token_urlsafe(32)
            admin.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_ROLE), sql.Literal(app_password)
                )
            )

        database_exists = bool(
            admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (APP_DATABASE,)
            ).fetchone()
        )
        if not database_exists:
            admin.execute(
                sql.SQL(
                    "CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0"
                ).format(sql.Identifier(APP_DATABASE), sql.Identifier(APP_ROLE))
            )
        else:
            admin.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(APP_DATABASE), sql.Identifier(APP_ROLE)
                )
            )

    dsn = stored_dsn if reuse_stored else build_dsn(
        app_password, host=host, port=port
    )
    with psycopg.connect(dsn, connect_timeout=5) as app_connection:
        app_connection.execute("SELECT 1").fetchone()
    destination = save_postgres_dsn(dsn, protected_path)
    return {
        "status": "ok",
        "server_version": str(server_version),
        "listen_addresses": str(listen_addresses),
        "host": str(host),
        "port": int(port),
        "database": APP_DATABASE,
        "role": APP_ROLE,
        "database_created": not database_exists,
        "role_created": not role_exists,
        "credential_rotated": bool(role_exists and not reuse_stored),
        "protected_config": str(destination),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="設定土地資料系統本機 PostgreSQL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--rotate", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    password = getpass.getpass("請輸入安裝 PostgreSQL 時設定的管理密碼：")
    if not password:
        raise SystemExit("未輸入密碼，未進行任何變更。")
    try:
        result = setup_database(
            password,
            host=args.host,
            port=args.port,
            rotate=args.rotate,
        )
    except Exception as exc:
        failure = {"status": "error", "message": str(exc)}
        REPORT_PATH.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise SystemExit(f"設定失敗：{exc}") from None
    REPORT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("本機 PostgreSQL 專案資料庫設定完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
