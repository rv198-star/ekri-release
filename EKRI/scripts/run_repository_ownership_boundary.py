#!/usr/bin/env python3
"""Run EKRI V1.9.1 P2 repository ownership/dependency boundary reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.repository_asset_identity import validate_repository_asset_knowledge_map  # noqa: E402
from ekri.repository_ownership_boundary import (  # noqa: E402
    RepositoryOwnershipBoundaryError,
    build_repository_ownership_boundary_map,
    validate_repository_ownership_boundary_map,
)


def _load_json(path_value: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path_value).expanduser().resolve(strict=False)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RepositoryOwnershipBoundaryError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise RepositoryOwnershipBoundaryError(f"{label} must be a safe regular JSON file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryOwnershipBoundaryError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryOwnershipBoundaryError(f"{label} must contain a JSON object")
    return value, {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _focus_paths(p0_summary: dict[str, Any] | None) -> list[str]:
    if not p0_summary:
        return []
    cohort = p0_summary.get("p1_priority_repository_only_python_cohort", [])
    if not isinstance(cohort, list):
        raise RepositoryOwnershipBoundaryError("P0 priority cohort must be a list")
    return sorted({str(item).strip().replace("\\", "/") for item in cohort if str(item).strip()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconstruct EKRI repository ownership/dependency boundaries")
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--asset-map", required=True, help="P1 Repository Asset Knowledge Map JSON")
    parser.add_argument("--target-ref", default="v1.9")
    parser.add_argument("--p0-summary", default="", help="Optional #967 P0 summary for the 23-path priority frontier")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        asset_map, asset_receipt = _load_json(args.asset_map, "P1 asset map")
        validate_repository_asset_knowledge_map(asset_map)
        p0_summary: dict[str, Any] | None = None
        p0_receipt: dict[str, Any] = {}
        if args.p0_summary:
            p0_summary, p0_receipt = _load_json(args.p0_summary, "P0 summary")

        payload = build_repository_ownership_boundary_map(
            args.repository_root,
            asset_map=asset_map,
            target_ref=args.target_ref,
            focus_paths=_focus_paths(p0_summary),
            write_outputs=False,
        )
        payload["evidence_input_receipts"] = {
            "p1_asset_map": asset_receipt,
            "p0_summary": p0_receipt,
            "structural_evidence_policy": "Python AST imports and exact repository-path textual references are structural facts only; they never establish semantic ownership.",
        }
        root = Path(args.repository_root).expanduser().resolve(strict=False)
        output = root / ".EKRI" / "ownership-boundaries" / str(payload["source"]["tree"]) / "repository-ownership-boundary-map.json"
        payload["output"] = str(output)
        validate_repository_ownership_boundary_map(payload, p1_asset_map=asset_map)
        if not args.no_write:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except RepositoryOwnershipBoundaryError as exc:
        print(json.dumps({"schema_version": "ekri.repository-ownership-boundary-cli-error.v1", "status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        print(json.dumps({"schema_version": "ekri.repository-ownership-boundary-cli-error.v1", "status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
