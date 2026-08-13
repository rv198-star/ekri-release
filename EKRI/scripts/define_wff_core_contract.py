#!/usr/bin/env python3
"""Define and persist the WFF v1.8 Minimal Core Contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

EKRI_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = EKRI_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ekri.minimal_core_contract import (  # noqa: E402
    MinimalCoreContractError,
    run_minimal_core_contract,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the accepted P0 Core Candidate Map, define the versioned "
            "WFF Minimal Core Contract, and persist its public/internal API, extension, "
            "compatibility, migration, conformance, review, and audit projections."
        )
    )
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Git repository top-level root containing WFF and EKRI",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Evaluate the P1 contract without persisting P1 outputs (P0 authority is refreshed)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_minimal_core_contract(
            args.repository_root,
            write_outputs=not args.no_write,
        )
    except MinimalCoreContractError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.minimal-core-contract-cli-error.v1",
                    "status": "rejected",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
