#!/usr/bin/env python3
"""Run the WFF v1.8 P0 Core boundary reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = EKRI_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ekri.core_boundary_reconstruction import (  # noqa: E402
    CoreBoundaryError,
    run_core_boundary_reconstruction,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Revalidate the accepted v1.6.2 Architecture Memory, prove the "
            "v1.7 mainline-equivalence boundary, and persist the evidence-linked "
            "v1.8 P0 Core Candidate Map without changing WFF runtime files."
        )
    )
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Git repository top-level root containing WFF and the ignored .EKRI state",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Build the P0 projection but do not persist Core-boundary outputs; authority bootstrap state is still refreshed under .EKRI",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_core_boundary_reconstruction(
            args.repository_root,
            write_outputs=not args.no_write,
        )
    except CoreBoundaryError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.core-boundary-cli-error.v1",
                    "status": "rejected",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
