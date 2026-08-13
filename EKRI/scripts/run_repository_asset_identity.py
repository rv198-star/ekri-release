#!/usr/bin/env python3
"""Build an evidence-bound EKRI Repository Asset Knowledge Map."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.project_assets import load_verified_project_catalog  # noqa: E402
from ekri.repository_asset_identity import (  # noqa: E402
    RepositoryAssetIdentityError,
    build_repository_asset_knowledge_map,
    declared_analysis_membership,
    evidence_paths_from_pack_root,
    validate_repository_asset_knowledge_map,
)
from ekri.observation_boundary import evaluate_observation_boundary  # noqa: E402


def _load_json(path_value: str, label: str) -> tuple[dict[str, Any], dict[str, str]]:
    path = Path(path_value).expanduser().resolve(strict=False)
    if path.is_symlink() or not path.is_file():
        raise RepositoryAssetIdentityError(f"{label} must be a safe regular JSON file: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryAssetIdentityError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise RepositoryAssetIdentityError(f"{label} must contain a JSON object")
    return payload, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _pack_profile_id(pack_root: Path) -> tuple[str, dict[str, str]]:
    manifest, receipt = _load_json(str(pack_root / "SKILL_INSTALL_PACK_MANIFEST.json"), "install-pack manifest")
    profile_id = str(manifest.get("profile_id") or "").strip()
    if not profile_id:
        raise RepositoryAssetIdentityError(f"install-pack manifest lacks profile_id: {pack_root}")
    receipt["profile_id"] = profile_id
    receipt["source_revision"] = str(manifest.get("source_revision") or "").strip()
    return profile_id, receipt


def _bundle_receipt(bundle_root: Path) -> dict[str, str]:
    manifest, receipt = _load_json(str(bundle_root / "SKILL_BUNDLE_MANIFEST.json"), "maintainer bundle manifest")
    receipt["source_revision"] = str(manifest.get("source_revision") or "").strip()
    receipt["bundle_name"] = str(manifest.get("bundle_name") or "").strip()
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build EKRI Repository Asset Knowledge Map")
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--target-ref", default="v1.9")
    parser.add_argument("--asset-namespace", default="wff-v1.9")
    parser.add_argument("--formal-pack-root", action="append", default=[])
    parser.add_argument("--maintainer-bundle-root", default="")
    parser.add_argument("--profile-config", default="config/wff-install-profiles.json")
    parser.add_argument("--responsibility-map", default="docs/internal/audit-notes/issue-920-v19-p0-responsibility-map-v0.1.json")
    parser.add_argument("--p0-summary", default="docs/internal/audit-notes/issue-967-v191-p0-repository-decoupling-summary-v0.1.json")
    parser.add_argument("--project-asset-id", default="wff-v1.6.2-baseline")
    parser.add_argument("--focus-path", action="append", default=[])
    parser.add_argument("--no-p0-focus", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.repository_root).expanduser().resolve(strict=False)
    try:
        observation = evaluate_observation_boundary(repository_root=root, target_ref=args.target_ref)
        if not observation.get("boundary", {}).get("valid"):
            raise RepositoryAssetIdentityError(
                "formal observation boundary rejected: "
                + str(observation.get("boundary", {}).get("failure_reason") or "unknown failure")
            )
        target_paths = set(str(path) for path in observation["corpus"]["paths"])

        formal_profile_paths: dict[str, set[str]] = {}
        pack_receipts: list[dict[str, str]] = []
        for raw_root in args.formal_pack_root:
            pack_root = Path(raw_root).expanduser().resolve(strict=False)
            profile_id, receipt = _pack_profile_id(pack_root)
            if profile_id in formal_profile_paths:
                raise RepositoryAssetIdentityError(f"duplicate formal pack profile_id: {profile_id}")
            formal_profile_paths[profile_id] = evidence_paths_from_pack_root(pack_root, target_paths)
            receipt["matched_target_file_count"] = str(len(formal_profile_paths[profile_id]))
            pack_receipts.append(receipt)

        maintainer_paths: set[str] = set()
        maintainer_receipt: dict[str, str] = {}
        if args.maintainer_bundle_root:
            bundle_root = Path(args.maintainer_bundle_root).expanduser().resolve(strict=False)
            maintainer_paths = evidence_paths_from_pack_root(bundle_root, target_paths)
            maintainer_receipt = _bundle_receipt(bundle_root)
            maintainer_receipt["matched_target_file_count"] = str(len(maintainer_paths))

        profile_config, profile_receipt = _load_json(str(root / args.profile_config), "install-profile config")
        analysis_membership = declared_analysis_membership(profile_config, target_paths)

        responsibility_map, responsibility_receipt = _load_json(str(root / args.responsibility_map), "responsibility map")
        p0_summary, p0_receipt = _load_json(str(root / args.p0_summary), "P0 summary")
        capability_catalog, project_asset_manifest = load_verified_project_catalog(root, asset_id=args.project_asset_id)

        focus_paths = list(args.focus_path)
        if not args.no_p0_focus:
            cohort = p0_summary.get("p1_priority_repository_only_python_cohort", [])
            if isinstance(cohort, list):
                focus_paths.extend(str(path) for path in cohort)

        payload = build_repository_asset_knowledge_map(
            root,
            target_ref=args.target_ref,
            asset_namespace=args.asset_namespace,
            formal_profile_paths=formal_profile_paths,
            maintainer_paths=maintainer_paths,
            analysis_membership=analysis_membership,
            responsibility_map=responsibility_map,
            responsibility_source_ref=args.responsibility_map,
            capability_catalog=capability_catalog,
            capability_source_ref=f".EKRI/project/{args.project_asset_id}/capability-catalog.json",
            focus_reference_paths=focus_paths,
            write_outputs=False,
        )
        payload["evidence_input_receipts"] = {
            "formal_pack_manifests": sorted(pack_receipts, key=lambda row: row.get("profile_id", "")),
            "maintainer_bundle_manifest": maintainer_receipt,
            "profile_config": profile_receipt,
            "responsibility_map": responsibility_receipt,
            "p0_summary": p0_receipt,
            "project_asset": {
                "asset_id": args.project_asset_id,
                "target": project_asset_manifest.get("target", {}),
                "claim_ceiling": str(project_asset_manifest.get("claim_ceiling") or ""),
            },
            "analysis_profile_evidence": "configuration-declaration-only; analysis-only profiles are intentionally non-buildable",
        }
        validate_repository_asset_knowledge_map(payload)
        if not args.no_write:
            output = root / ".EKRI" / "repository-assets" / payload["source"]["tree"] / "repository-asset-knowledge-map.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            payload["output"] = str(output)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except RepositoryAssetIdentityError as exc:
        print(json.dumps({"schema_version": "ekri.repository-asset-identity-cli-error.v1", "status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
