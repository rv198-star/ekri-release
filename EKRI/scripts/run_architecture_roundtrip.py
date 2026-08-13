#!/usr/bin/env python3
"""Run EKRI v1.0 P2 Architecture round-trip parity through the P1 shadow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.architecture_roundtrip import (  # noqa: E402
    ArchitectureRoundTripError,
    run_architecture_roundtrip,
)
from ekri.phase1_snapshot import Phase1SnapshotError  # noqa: E402
from ekri.shadow_semantic_substrate import ShadowSemanticSubstrateError  # noqa: E402


DEFAULT_SOURCE_TREE = "e7bd7082e1674cce1f2d2e2f11f5978555f973b1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a Phase-1 Architecture Memory snapshot, compile/reopen the P1 "
            "shadow substrate, derive a non-authoritative Architecture View, and "
            "evaluate semantic round-trip parity."
        )
    )
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--source-tree", default=DEFAULT_SOURCE_TREE)
    parser.add_argument("--no-write", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.repository_root).expanduser().resolve(strict=False)
    try:
        result = run_architecture_roundtrip(
            root,
            source_tree=args.source_tree,
            write_outputs=not args.no_write,
        )
    except (
        Phase1SnapshotError,
        ShadowSemanticSubstrateError,
        ArchitectureRoundTripError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.architecture-roundtrip-cli-error.v1",
                    "status": "blocked",
                    "authority_mode": "derived-non-authoritative",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("verdict") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
