"""Export one SQLite login account for safe import on the home server."""

import argparse
import json

from customer_recovery_account import write_recovery_package


def build_parser():
    parser = argparse.ArgumentParser(description="匯出單機版帳號恢復檔")
    parser.add_argument("--source", required=True, help="單機版 customers.db 路徑")
    parser.add_argument("--username", required=True, help="要匯出的帳號")
    parser.add_argument("--output", required=True, help="輸出的 .lcs-account 路徑")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    destination = write_recovery_package(
        args.source,
        args.username,
        args.output,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "status": "exported",
                "username": args.username,
                "recovery_file": str(destination),
                "contains_plaintext_password": False,
                "contains_plaintext_data_key": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
