#!/usr/bin/env python3
"""Run EKRI v1.0 P3 named capability queries over the shared substrate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.architecture_roundtrip import ArchitectureRoundTripError  # noqa: E402
from ekri.capability_query import (  # noqa: E402
    CapabilityQueryError,
    run_capability_query,
)
from ekri.existing_capability_intelligence import (  # noqa: E402
    ExistingCapabilityError,
    build_request,
)
from ekri.phase1_snapshot import Phase1SnapshotError  # noqa: E402
from ekri.shadow_semantic_substrate import ShadowSemanticSubstrateError  # noqa: E402


DEFAULT_SOURCE_TREE = "e7bd7082e1674cce1f2d2e2f11f5978555f973b1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EKRI named capability query")
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--source-tree", default=DEFAULT_SOURCE_TREE)
    parser.add_argument(
        "--query-kind",
        required=True,
        choices=(
            "find-capability",
            "get-realizations",
            "explain-authority",
            "get-evidence",
            "before-generate",
        ),
    )
    parser.add_argument("--query", default="")
    parser.add_argument("--capability-id", default="")
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument(
        "--trigger-basis",
        choices=("observed-failure", "declared-requirement", "hypothetical-risk"),
        default="hypothetical-risk",
    )
    parser.add_argument("--trigger-reference", default="")
    parser.add_argument(
        "--change-mode",
        choices=("use-as-is", "additive-extension", "behavior-replacement", "new-capability"),
        default="use-as-is",
    )
    parser.add_argument(
        "--decision-status",
        choices=("not-supplied", "accepted"),
        default="not-supplied",
    )
    parser.add_argument("--decision-reference", default="")
    parser.add_argument("--non-reuse-reason", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        request = None
        if args.query_kind == "before-generate":
            request = build_request(
                capability_query=args.query,
                trigger_basis=args.trigger_basis,
                trigger_reference=args.trigger_reference,
                change_mode=args.change_mode,
                decision_status=args.decision_status,
                decision_reference=args.decision_reference,
                non_reuse_reason=args.non_reuse_reason,
            )
        result = run_capability_query(
            args.repository_root,
            source_tree=args.source_tree,
            query_kind=args.query_kind,
            capability_query=args.query,
            capability_id=args.capability_id,
            request=request,
            write_index=args.write_index,
        )
    except (
        CapabilityQueryError,
        ExistingCapabilityError,
        Phase1SnapshotError,
        ArchitectureRoundTripError,
        ShadowSemanticSubstrateError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "ekri.capability-query-cli-error.v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
