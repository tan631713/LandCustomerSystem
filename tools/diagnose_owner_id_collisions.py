"""Run the read-only owner identity collision report from source.

    python tools\\diagnose_owner_id_collisions.py [--report-dir PATH]

Same as ``LandCustomerServer.exe --diagnose-owner-ids`` in the server package:
asks for the administrator password, only SELECTs (READ ONLY transaction),
prints and saves counts -- never names or identity numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    from start_api_server import build_parser, run_owner_id_diagnostics

    args = build_parser().parse_args(["--diagnose-owner-ids", *(argv or sys.argv[1:])])
    return run_owner_id_diagnostics(args)


if __name__ == "__main__":
    raise SystemExit(main())
