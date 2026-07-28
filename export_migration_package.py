"""Command-line exporter for a standalone-to-home-server migration package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from customer_migration_package import export_migration_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建立單機資料搬移包")
    parser.add_argument("--source", type=Path, required=True, help="單機 customers.db")
    parser.add_argument(
        "--output",
        type=Path,
        help="輸出資料夾，或以 .lcs-migration.zip 結尾的完整檔名",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = export_migration_package(args.source, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
