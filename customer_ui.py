import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from customer_client_connection import normalize_server_api_url
from customer_error_handler import install_exception_handler, install_native_crash_tracer


def get_runtime_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def apply_company_client_config():
    """Force remote API mode when the EXE belongs to a company-client bundle."""

    runtime_directory = get_runtime_directory()
    config_path = runtime_directory / "company-client-config.json"
    if not config_path.is_file():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    configured_api_url = str(os.environ.get("LAND_CUSTOMER_API_URL") or "").strip()
    packaged_api_url = str(payload.get("api_url") or "").strip()
    api_url = normalize_server_api_url(configured_api_url or packaged_api_url) if (
        configured_api_url or packaged_api_url
    ) else ""

    bundle_directory = runtime_directory.parent.resolve()
    configured_ca = str(payload.get("ca_certificate") or "").strip()
    ca_path = None
    if configured_ca:
        ca_path = (runtime_directory / configured_ca).resolve()
        try:
            ca_path.relative_to(bundle_directory)
        except ValueError as exc:
            raise ValueError("Company client CA path escaped the bundle") from exc
        if not ca_path.is_file():
            raise ValueError(f"Company client CA certificate does not exist: {ca_path}")

    os.environ["LAND_CUSTOMER_DESKTOP_BACKEND"] = "postgresql"
    if api_url:
        os.environ["LAND_CUSTOMER_API_URL"] = api_url
    else:
        os.environ.pop("LAND_CUSTOMER_API_URL", None)
    if ca_path is not None:
        os.environ["LAND_CUSTOMER_API_CA_CERT"] = str(ca_path)
    else:
        os.environ.pop("LAND_CUSTOMER_API_CA_CERT", None)
    return {
        "api_url": api_url,
        "ca_certificate": str(ca_path or ""),
        "requires_server_ip_input": not bool(api_url),
    }


def run_company_client_health_check(report_path):
    """Validate the packaged client connection without opening the desktop UI."""

    from customer_desktop_api import DesktopApiClient, DesktopApiError

    destination = Path(report_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "api_url": os.environ.get("LAND_CUSTOMER_API_URL", ""),
    }
    try:
        client = DesktopApiClient(
            report["api_url"],
            timeout_seconds=6,
            read_retry_count=1,
            retry_delay_seconds=0.25,
        )
        health = client.health()
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise DesktopApiError("家中 API 健康檢查未回傳正常狀態。")
        if health.get("backend") != "postgresql":
            raise DesktopApiError("連線目標不是 PostgreSQL 正式伺服器。")
        if int(health.get("schema_version") or 0) < 3:
            raise DesktopApiError("家中伺服器資料結構版本過舊，請先更新伺服器端。")
        report.update(
            {
                "status": "ok",
                "backend": "postgresql",
                "server_version": str(health.get("version") or ""),
                "schema_version": int(health.get("schema_version") or 0),
                "record_count": int(health.get("record_count") or 0),
            }
        )
        exit_code = 0
    except (DesktopApiError, ValueError, OSError) as exc:
        report["message"] = str(exc)
        exit_code = 1
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return exit_code


def entrypoint():
    install_exception_handler(get_runtime_directory())
    install_native_crash_tracer(get_runtime_directory())
    apply_company_client_config()
    if "--client-health-report" in sys.argv:
        argument_index = sys.argv.index("--client-health-report")
        report_path = (
            sys.argv[argument_index + 1]
            if argument_index + 1 < len(sys.argv)
            else Path(os.environ.get("LOCALAPPDATA", Path.home()))
            / "LandCustomerSystem"
            / "client-network-diagnostics.json"
        )
        return run_company_client_health_check(report_path)
    if "--release-smoke-report" in sys.argv:
        argument_index = sys.argv.index("--release-smoke-report")
        report_path = (
            sys.argv[argument_index + 1]
            if argument_index + 1 < len(sys.argv)
            else "release-acceptance-report.json"
        )
        from release_acceptance import main as acceptance_main

        return acceptance_main(report_path)

    from customer_ui_qt import main

    return main()


if __name__ == "__main__":
    raise SystemExit(entrypoint())
