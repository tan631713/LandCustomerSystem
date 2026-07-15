import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from customer_error_handler import install_exception_handler


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
    api_url = str(payload.get("api_url") or "").strip().rstrip("/")
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port != 8732:
        raise ValueError("Company client API URL must use HTTPS port 8732")
    address = ipaddress.ip_address(parsed.hostname)
    if address.version != 4 or address not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("Company client API host must be a NetBird IPv4 address")

    bundle_directory = runtime_directory.parent.resolve()
    ca_path = (runtime_directory / str(payload.get("ca_certificate") or "")).resolve()
    try:
        ca_path.relative_to(bundle_directory)
    except ValueError as exc:
        raise ValueError("Company client CA path escaped the bundle") from exc
    if not ca_path.is_file():
        raise ValueError(f"Company client CA certificate does not exist: {ca_path}")

    os.environ["LAND_CUSTOMER_DESKTOP_BACKEND"] = "postgresql"
    os.environ["LAND_CUSTOMER_API_URL"] = api_url
    os.environ["LAND_CUSTOMER_API_CA_CERT"] = str(ca_path)
    return {"api_url": api_url, "ca_certificate": str(ca_path)}


def entrypoint():
    install_exception_handler(get_runtime_directory())
    apply_company_client_config()
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
