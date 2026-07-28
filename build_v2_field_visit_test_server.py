"""Build a non-formal v2 field-visit test server package.

This package intentionally excludes databases, credentials, certificates,
attachments, and backups. The home-server launcher continues to use the
existing PostgreSQL database and settings under the Windows user profile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from build_postgresql_release import (
    PRIMARY_LAUNCHER,
    ROOT,
    SERVER_DIST,
    SUPPORT_FILES,
    audit_server_bundle,
    build_server,
    copy_primary_launcher,
)
from customer_version import APP_VERSION


OUTPUT_DIRECTORY = ROOT / "test-artifacts"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def package_test_server() -> tuple[Path, Path, Path]:
    if not SERVER_DIST.is_dir():
        raise FileNotFoundError("LandCustomerServer build output is missing")

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_name = f"LandCustomerSystem-v2-FieldVisit-TestServer-{timestamp}"

    with tempfile.TemporaryDirectory(prefix="v2-field-visit-", dir=OUTPUT_DIRECTORY) as temporary:
        bundle = Path(temporary) / package_name
        bundle.mkdir()
        shutil.copytree(SERVER_DIST, bundle / "LandCustomerServer")
        copy_primary_launcher(bundle / PRIMARY_LAUNCHER)

        support = bundle / "_server_support"
        support.mkdir()
        for name in SUPPORT_FILES:
            shutil.copy2(ROOT / name, support / name)

        instructions = (
            "土地資料系統 v2 外勤功能測試伺服器\n"
            "\n"
            "1. 請先關閉舊的家中伺服器視窗。\n"
            "2. 將整個資料夾解壓縮到新位置，不要覆蓋舊伺服器資料夾。\n"
            f"3. 執行「{PRIMARY_LAUNCHER}」。\n"
            "4. 手機重新開啟 /mobile/，登入後再測試「加入今日行程」。\n"
            "\n"
            "此測試包不含資料庫、帳號密碼、憑證、附件或備份。\n"
            "它會沿用目前 Windows 使用者設定與既有 PostgreSQL 資料庫。\n"
        )
        (bundle / "測試版使用說明.txt").write_text(instructions, encoding="utf-8-sig")

        manifest = {
            "product": "LandCustomerSystem",
            "channel": "v2-field-visit-test",
            "formal_release": False,
            "source_baseline": APP_VERSION,
            "mobile_asset_version": 14,
            "packaged_at": datetime.now().astimezone().isoformat(),
            "server_executable": "LandCustomerServer/LandCustomerServer.exe",
            "primary_launcher": PRIMARY_LAUNCHER,
            "database_included": False,
            "credentials_included": False,
            "certificates_included": False,
            "attachments_included": False,
            "backups_included": False,
            "uses_existing_postgresql_database": True,
        }
        (bundle / "test-package-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        audit_server_bundle(bundle)
        permanent_directory = OUTPUT_DIRECTORY / package_name
        shutil.copytree(bundle, permanent_directory)
        zip_path = OUTPUT_DIRECTORY / f"{package_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(package_name) / path.relative_to(bundle))

    checksum_path = zip_path.with_suffix(".sha256.txt")
    checksum_path.write_text(
        f"{sha256_file(zip_path)}  {zip_path.name}\n",
        encoding="ascii",
    )
    return permanent_directory, zip_path, checksum_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the v2 field-visit test server package")
    parser.add_argument("--skip-server-build", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.skip_server_build:
        build_server(sys.executable)
    directory, zip_path, checksum_path = package_test_server()
    print(
        json.dumps(
            {
                "package_directory": str(directory),
                "package_zip": str(zip_path),
                "checksum": str(checksum_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
