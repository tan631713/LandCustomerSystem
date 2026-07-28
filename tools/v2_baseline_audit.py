"""Generate a read-only v2 planning baseline without opening production data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_migrations import LATEST_SCHEMA_VERSION as SQLITE_SCHEMA_VERSION
from customer_version import APP_VERSION, BUILD_DATE, DESKTOP_CLIENT_VERSION


DEFAULT_OUTPUT = ROOT / "docs" / "v2" / "baseline" / "v1.8.9-baseline.json"
POSTGRES_SCHEMA = ROOT / "postgres" / "schema.sql"
LINE_BOT_ROOT = ROOT.parents[1] / "line_bot_test"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def postgres_inventory():
    text = POSTGRES_SCHEMA.read_text(encoding="utf-8")
    versions = [int(value) for value in re.findall(
        r"VALUES\s*\(\s*(\d+)\s*,\s*'[^']+'\s*\)", text, flags=re.IGNORECASE
    )]
    tables = sorted(set(re.findall(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        text,
        flags=re.IGNORECASE,
    )))
    return {"schema_version": max(versions, default=0), "tables": tables}


def route_inventory():
    app = create_app(settings=ApiSettings(), data_source=Mock())
    rows = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        if not methods:
            continue
        rows.append({
            "methods": methods,
            "path": route.path,
            "name": route.name,
            "api_family": "v1" if route.path.startswith("/api/v1/") else "system",
        })
    rows.sort(key=lambda item: (item["path"], item["methods"]))
    operational = [
        row for row in rows
        if row["path"] not in {"/openapi.json", "/docs", "/docs/oauth2-redirect"}
    ]
    return {
        "method_route_count": len(rows),
        "operational_route_count": len(operational),
        "api_v1_route_count": sum(row["api_family"] == "v1" for row in rows),
        "routes": rows,
    }


def client_endpoint_references(path: Path):
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"/api/v1/[A-Za-z0-9_{}$\-/]+", text)
    normalized = []
    for value in matches:
        value = re.sub(r"\$\{[^}]+\}", "{id}", value)
        value = re.sub(r"\{int\([^}]+\)\}", "{id}", value)
        normalized.append(value.rstrip("/"))
    return sorted(set(normalized))


def line_bot_release():
    latest = LINE_BOT_ROOT / "releases" / "LATEST.txt"
    manifests = sorted((LINE_BOT_ROOT / "releases").glob(
        "LandCustomerLineBotServer-v*/release-manifest.json"
    ))
    result = {"root_found": LINE_BOT_ROOT.is_dir(), "latest_text": "", "version": None}
    if latest.is_file():
        result["latest_text"] = latest.read_text(encoding="utf-8").strip()
    if manifests:
        manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
        result.update({"version": manifest.get("version"), "manifest": str(manifests[-1])})
    repository = LINE_BOT_ROOT / "line_bot" / "home_api_repository.py"
    result["api_v1_references"] = client_endpoint_references(repository) if repository.is_file() else []
    return result


def build_report():
    protected_files = [
        ROOT / "customer_version.py",
        ROOT / "customer_api" / "app.py",
        ROOT / "postgres" / "schema.sql",
        ROOT / "customer_desktop_api.py",
        ROOT / "customer_mobile_web" / "app.js",
    ]
    return {
        "report_type": "v2_planning_read_only_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_data_opened": False,
        "versions": {
            "server": APP_VERSION,
            "desktop_client": DESKTOP_CLIENT_VERSION,
            "build_date": BUILD_DATE,
            "line_bot": line_bot_release(),
        },
        "schemas": {
            "postgresql": postgres_inventory(),
            "sqlite_compatibility": {"schema_version": SQLITE_SCHEMA_VERSION},
        },
        "api": route_inventory(),
        "client_endpoint_references": {
            "desktop": client_endpoint_references(ROOT / "customer_desktop_api.py"),
            "mobile_pwa": client_endpoint_references(ROOT / "customer_mobile_web" / "app.js"),
        },
        "file_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
            for path in protected_files
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_report(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
