#!/usr/bin/env python3
"""Rebuild the ignored Phase 0/1 authority required by Phase 3 audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.audit_bootstrap import (  # noqa: E402
    Phase3AuditBootstrapError,
    bootstrap_phase3_audit_runtime,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct Phase 0/1 runtime authority in a clean worktree and "
            "compare it with the committed Phase 3 audit fixture."
        )
    )
    parser.add_argument(
        "--repository-root",
        default=str(EKRI_ROOT.parent),
        help="Git repository root (default: parent of EKRI)",
    )
    parser.add_argument(
        "--fixture",
        default="",
        help="Optional external fixture path for tests; default uses the committed fixture",
    )
    parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist .EKRI/audit/phase3-bootstrap.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = bootstrap_phase3_audit_runtime(
            args.repository_root,
            fixture_path=args.fixture or None,
            write_report=not args.no_write_report,
        )
    except Phase3AuditBootstrapError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
