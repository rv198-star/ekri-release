#!/usr/bin/env python3
"""Reconstruct and persist the fixed WFF v1.6.2 architecture memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SCRIPT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.knowledge_reconstruction import (  # noqa: E402
    KnowledgeReconstructionError,
    reconstruct_and_persist_wff_baseline,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Consume the valid Phase 0 manifest for the fixed WFF v1.6.2 tree, "
            "read admitted Git blobs only, and persist evidence-linked "
            "architecture memory below .EKRI/knowledge/<tree>/."
        )
    )
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Git repository top-level root containing the target objects and .EKRI manifest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = reconstruct_and_persist_wff_baseline(args.repository_root)
    except (KnowledgeReconstructionError, OSError) as exc:
        payload = {
            "schema_version": "ekri.reconstruction-cli-result.v1",
            "status": "rejected",
            "failure_reason": str(exc),
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return 2

    payload = {
        "schema_version": "ekri.reconstruction-cli-result.v1",
        "status": summary["status"],
        "profile_id": summary["profile_id"],
        "source_commit": summary["source_commit"],
        "source_tree": summary["source_tree"],
        "counts": summary["counts"],
        "outputs": summary["outputs"],
        "claim_ceiling": summary["claim_ceiling"],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
