#!/usr/bin/env python3
"""Compile a verified EKRI Phase-1 snapshot into the v1.0 shadow substrate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.phase1_snapshot import Phase1SnapshotError  # noqa: E402
from ekri.shadow_semantic_substrate import (  # noqa: E402
    ShadowSemanticSubstrateError,
    run_phase1_architecture_shadow,
)


DEFAULT_SOURCE_TREE = "e7bd7082e1674cce1f2d2e2f11f5978555f973b1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile an already-verified Phase-1 Architecture Memory snapshot into "
            "the EKRI v1.0 read-only shadow semantic substrate."
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
        result = run_phase1_architecture_shadow(
            root,
            source_tree=args.source_tree,
            write_outputs=not args.no_write,
        )
    except (Phase1SnapshotError, ShadowSemanticSubstrateError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.architecture-shadow-compiler-cli-error.v1",
                    "status": "blocked",
                    "authority_mode": "shadow-non-authoritative",
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
