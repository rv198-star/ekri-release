#!/usr/bin/env python3
"""Run EKRI Phase 3 incremental reconstruction and evolution analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
from typing import Any


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.evolution_intelligence import (  # noqa: E402
    EvolutionIntelligenceError,
    build_change_impact_request,
    build_change_registration,
    run_phase3_evolution_analysis,
)


def _load_array(path_value: str, label: str) -> list[dict[str, Any]]:
    if not path_value:
        return []
    path = Path(path_value).expanduser()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvolutionIntelligenceError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise EvolutionIntelligenceError(f"{label} must be a safe regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvolutionIntelligenceError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise EvolutionIntelligenceError(f"{label} must contain a JSON array of objects")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bounded incremental reconstruction, evolution, and impact analysis."
    )
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--target-ref", required=True)
    parser.add_argument(
        "--scan-mode",
        choices=("baseline", "local-change", "drift"),
        default="local-change",
    )
    parser.add_argument("--seed-path", action="append", default=[])
    parser.add_argument("--registrations", default="")
    parser.add_argument("--impacts", default="")
    parser.add_argument(
        "--verification-trigger",
        choices=(
            "capability-consumption",
            "design-decision",
            "explicit-request",
            "release-verification",
        ),
        default="explicit-request",
    )
    parser.add_argument("--requested-capability", default="")
    parser.add_argument("--release-verification", action="store_true")
    parser.add_argument("--release-reference", default="")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        registrations = tuple(
            build_change_registration(
                change_id=item.get("change_id", ""),
                capability_id=item.get("capability_id", ""),
                change_kind=item.get("change_kind", ""),
                summary=item.get("summary", ""),
                expected_paths=item.get("expected_paths", ()),
                state=item.get("state", "registered"),
                decision_reference=item.get("decision_reference", ""),
                registered_at=item.get("registered_at", ""),
            )
            for item in _load_array(args.registrations, "registrations")
        )
        impacts = tuple(
            build_change_impact_request(
                change_id=item.get("change_id", ""),
                capability_id=item.get("capability_id", ""),
                affected_capability_ids=item.get("affected_capability_ids", ()),
                classification=item.get("classification", ""),
                rationale=item.get("rationale", ""),
                evidence_refs=item.get("evidence_refs", ()),
            )
            for item in _load_array(args.impacts, "impacts")
        )
        result = run_phase3_evolution_analysis(
            args.repository_root,
            target_ref=args.target_ref,
            registrations=registrations,
            impact_requests=impacts,
            scan_mode=args.scan_mode,
            seed_paths=args.seed_path,
            verification_trigger=args.verification_trigger,
            requested_capability=args.requested_capability,
            release_verification=args.release_verification,
            release_reference=args.release_reference,
            write_outputs=not args.no_write,
        )
    except EvolutionIntelligenceError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
