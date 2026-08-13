#!/usr/bin/env python3
"""CLI for EKRI Phase 2 Existing Capability Intelligence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.existing_capability_intelligence import (  # noqa: E402
    ExistingCapabilityError,
    build_request,
    run_existing_capability_check,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check verified WFF Architecture Memory before generating a capability change."
    )
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument(
        "--trigger-basis",
        required=True,
        choices=["observed-failure", "declared-requirement", "hypothetical-risk"],
    )
    parser.add_argument(
        "--change-mode",
        required=True,
        choices=["use-as-is", "additive-extension", "behavior-replacement", "new-capability"],
    )
    parser.add_argument("--trigger-reference", default="")
    parser.add_argument(
        "--decision-status",
        default="not-supplied",
        choices=["not-supplied", "accepted"],
    )
    parser.add_argument("--decision-reference", default="")
    parser.add_argument("--non-reuse-reason", default="")
    parser.add_argument("--context-note", default="")
    parser.add_argument("--project-asset-id")
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = build_request(
            capability_query=args.capability,
            trigger_basis=args.trigger_basis,
            change_mode=args.change_mode,
            trigger_reference=args.trigger_reference,
            decision_status=args.decision_status,
            decision_reference=args.decision_reference,
            non_reuse_reason=args.non_reuse_reason,
            context_note=args.context_note,
        )
        result = run_existing_capability_check(
            args.repository_root,
            request,
            write_outputs=not args.no_write,
            project_asset_id=args.project_asset_id,
        )
    except ExistingCapabilityError as exc:
        payload = {
            "schema_version": "ekri.existing-capability-cli-error.v1",
            "status": "rejected",
            "failure_reason": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    payload = {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "request_id": result["report"]["request_id"],
        "authority_source": result["authority_source"],
        "resolution": result["report"]["resolution"],
        "answers": result["report"]["answers"],
        "boundary": result["report"]["boundary"],
        "outputs": result["outputs"],
        "claim_ceiling": result["report"]["claim_ceiling"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["report"]["boundary"]["decision_allowed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
