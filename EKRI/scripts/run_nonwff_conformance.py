#!/usr/bin/env python3
"""Run EKRI v1.0 P8 product-level non-WFF conformance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.nonwff_conformance import (  # noqa: E402
    DEFAULT_FIXTURE_PATH,
    NonWffConformanceError,
    run_nonwff_conformance,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EKRI v1.0 non-WFF conformance")
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_nonwff_conformance(
            args.repository_root,
            fixture_path=args.fixture,
        )
    except NonWffConformanceError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.nonwff-conformance-cli-error.v1",
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
