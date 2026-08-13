#!/usr/bin/env python3
"""Run the EKRI v1.0 Release Candidate source Gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.v100_release_gate import V100ReleaseGateError, run_v100_release_gate  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit an exact EKRI v1.0 Release Candidate source state")
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_v100_release_gate(args.repository_root)
    except V100ReleaseGateError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.v100-release-gate-cli-error.v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
