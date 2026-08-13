#!/usr/bin/env python3
"""Run the EKRI v1.0 P5 bounded Flow/Handoff named query."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.flow_query import FlowQueryError, FlowQueryService  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trace one bounded EKRI Flow/Handoff fixture without creating a Flow truth store"
    )
    parser.add_argument(
        "--fixture",
        required=True,
        help="Path to an ekri.flow-conformance-fixture.v1 JSON file",
    )
    parser.add_argument(
        "--repository-root",
        default=str(EKRI_ROOT.parent),
        help="Repository root used for WFF source/Architecture identity verification",
    )
    parser.add_argument(
        "--level",
        default="L1",
        choices=("L0", "L1", "L2", "L3"),
        help="Progressive disclosure level",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=64,
        help="Bounded traversal depth (1..256)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.repository_root).expanduser().resolve(strict=False)
    fixture = Path(args.fixture).expanduser().resolve(strict=False)
    try:
        service = FlowQueryService.from_fixture_path(
            fixture,
            repository_root=root,
        )
        answer = service.trace_flow(
            disclosure_level=args.level,
            max_depth=args.max_depth,
        )
    except FlowQueryError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.flow-query-cli-error.v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(answer, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
