#!/usr/bin/env python3
"""CLI for EKRI Phase 0 formal Git-tree observation validation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SCRIPT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.observation_boundary import (  # noqa: E402
    ObservationBoundaryError,
    evaluate_observation_boundary,
    manifest_json,
    rejected_manifest_copy,
    write_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a formal Git commit/tree with replacement objects disabled, "
            "exclude EKRI/** and .EKRI/** before target blob reads, and persist "
            "the validated Phase 0 manifest through the fixed .EKRI layout."
        )
    )
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Git repository top-level root",
    )
    parser.add_argument(
        "--target-ref",
        default="HEAD",
        help="commit-ish to observe; defaults to HEAD",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="emit the evaluated manifest without persisting it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = evaluate_observation_boundary(
        repository_root=args.repository_root,
        target_ref=args.target_ref,
    )

    if not manifest["boundary"]["valid"]:
        sys.stdout.write(manifest_json(manifest))
        return 2
    if args.no_write:
        sys.stdout.write(manifest_json(manifest))
        return 0

    try:
        write_manifest(args.repository_root, manifest)
    except (OSError, ObservationBoundaryError) as exc:
        rejected = rejected_manifest_copy(
            manifest,
            code="manifest-persistence-failed",
            reason=str(exc),
            check="manifest-persistence",
        )
        sys.stdout.write(manifest_json(rejected))
        return 3

    sys.stdout.write(manifest_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
