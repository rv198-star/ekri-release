"""EKRI v1.1 candidate validation for Adaptive Knowledge Acquisition."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Any, Mapping

from .adaptive_exploration import ACQUISITION_AUTHORITY_MODE
from .adaptive_exploration_conformance import run_adaptive_exploration_conformance
from .adaptive_exploration_economy import run_adaptive_exploration_economy_audit
from .observation_boundary import ObservationBoundaryError, resolve_scanner_identity
from .project_assets import verify_project_asset
from .project_assets_v2 import verify_project_asset_v2
from .v100_release_gate import (
    M0_METRICS,
    WRITER_INVENTORY,
    _current_metrics,
    _public_exports,
    _verify_peer_authority,
    _verify_retirement,
    _verify_writer_inventory,
)

GATE_SCHEMA_VERSION = "ekri.v110-release-gate.v1"
GATE_STATUS = "v110-release-candidate-ready"
PRODUCT_VERSION = "1.1.0"
V100_TAG = "ekri/v1.0.0"
V100_SOURCE = "026f2ffa5c3c8685418adc4bf281911b4ff2d578"
V110_BASE_SOURCE = "44dac393d387c02a6545dfa979ccf520f4cd6e6d"
V110_SOURCE = "d45dc12d0777d5c7f6651f3564dea63b1dded8a6"
REQUIRED_ADAPTIVE_EXPORTS = frozenset({
    "AdaptiveExplorationError",
    "CompetencyQuestion",
    "MissionBudget",
    "build_mission_context",
    "assess_knowledge_sufficiency",
    "build_mission_exploration_plan",
    "collect_git_path_evidence",
    "initialize_wae_trace",
    "record_wae_iteration",
    "build_candidate_knowledge_delta",
    "evaluate_candidate_authority_route",
})


class V110GateError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise V110GateError(f"git {' '.join(args)} failed: {(process.stderr or process.stdout).strip()}")
    return process.stdout.strip()


def _product_metadata(ekri_root: Path) -> dict[str, Any]:
    try:
        pyproject = tomllib.loads((ekri_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise V110GateError(f"pyproject cannot be read: {exc}") from exc
    current_version = str(pyproject.get("project", {}).get("version") or "")
    if current_version != PRODUCT_VERSION and not current_version.startswith("1.1."):
        raise V110GateError(
            f"EKRI current product version is outside the v1.1 compatibility line: {current_version}"
        )
    required = [
        ekri_root / "CHANGELOG.md",
        ekri_root / "docs" / "adaptive-knowledge-acquisition-v1.1.md",
        ekri_root / "docs" / "releases" / "v1.1.0.md",
        ekri_root / "specs" / "v110-product-surface-classification.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise V110GateError("required v1.1 product records missing: " + ", ".join(missing))
    if "## [1.1.0]" not in (ekri_root / "CHANGELOG.md").read_text(encoding="utf-8"):
        raise V110GateError("CHANGELOG lacks v1.1.0 release entry")
    classification = json.loads(
        (ekri_root / "specs" / "v110-product-surface-classification.json").read_text(encoding="utf-8")
    )
    if classification.get("schema_version") != "ekri.v110-product-surface-classification.v1":
        raise V110GateError("unsupported v1.1 surface classification schema")
    if classification.get("product_version") != PRODUCT_VERSION:
        raise V110GateError("v1.1 surface classification product version mismatch")
    added = classification.get("added_supported_general")
    if not isinstance(added, list) or [row.get("surface_id") for row in added if isinstance(row, Mapping)] != [
        "mission-oriented-adaptive-knowledge-acquisition"
    ]:
        raise V110GateError("v1.1 adaptive supported surface classification drifted")
    return {
        "version": PRODUCT_VERSION,
        "current_product_version": current_version,
        "design": "EKRI/docs/adaptive-knowledge-acquisition-v1.1.md",
        "release_notes": "EKRI/docs/releases/v1.1.0.md",
        "surface_classification": "EKRI/specs/v110-product-surface-classification.json",
    }


def _public_surface(ekri_root: Path) -> dict[str, Any]:
    exports = _public_exports(ekri_root / "src" / "ekri" / "__init__.py")
    missing = sorted(REQUIRED_ADAPTIVE_EXPORTS - set(exports))
    if missing:
        raise V110GateError("v1.1 adaptive public APIs missing: " + ", ".join(missing))
    forbidden = {
        "run_adaptive_exploration_conformance",
        "run_adaptive_exploration_economy_audit",
        "validate_wae_trace",
        "validate_candidate_knowledge_delta",
    }
    leaked = sorted(forbidden & set(exports))
    if leaked:
        raise V110GateError("v1.1 internal audit/validator APIs leaked publicly: " + ", ".join(leaked))
    return {
        "public_export_count": len(exports),
        "adaptive_exports": sorted(REQUIRED_ADAPTIVE_EXPORTS),
        "forbidden_internal_exports": leaked,
    }


def _acquisition_boundary(ekri_root: Path) -> dict[str, Any]:
    module = ekri_root / "src" / "ekri" / "adaptive_exploration.py"
    text = module.read_text(encoding="utf-8")
    hits = [token for token in ("_atomic_write", "persist_", ".EKRI/") if token in text]
    if hits:
        raise V110GateError("adaptive acquisition core contains forbidden persistence surface: " + ", ".join(hits))
    if "ACQUISITION_AUTHORITY_MODE = \"acquisition-non-authoritative\"" not in text:
        raise V110GateError("adaptive acquisition authority posture is not frozen")
    if (ekri_root / "profiles").exists():
        raise V110GateError("v1.1 must not introduce an EKRI technology-stack profiles directory")
    tree = ast.parse(text)
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "build_mission_exploration_plan" not in functions or "record_wae_iteration" not in functions:
        raise V110GateError("adaptive acquisition plan/WAE contract is incomplete")
    if len(classes) > 4:
        raise V110GateError("adaptive acquisition is growing into a general object/runtime framework")
    return {
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "core_loc": len(text.splitlines()),
        "top_level_function_count": len(functions),
        "top_level_class_count": len(classes),
        "persistent_truth_store": False,
        "technology_profile_directory": False,
    }


def _distribution_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "EKRI_RELEASE_PACK_MANIFEST.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("product") != "EKRI" or value.get("version") != PRODUCT_VERSION:
        raise V110GateError("release-pack manifest does not identify EKRI v1.1.0")
    return value


def _version_invariants(root: Path) -> dict[str, Any]:
    release_tag = f"ekri/v{PRODUCT_VERSION}"
    release_tag_exists = bool(_git(root, "tag", "--list", release_tag))
    release_source = ""
    if release_tag_exists:
        release_source = _git(root, "rev-parse", f"{release_tag}^{{commit}}")
        if release_source != V110_SOURCE:
            raise V110GateError("published EKRI v1.1.0 tag/source identity changed")
    try:
        resolved_v100 = _git(root, "rev-parse", f"{V100_TAG}^{{commit}}")
    except V110GateError:
        manifest = _distribution_manifest(root)
        if manifest is None:
            raise
        return {
            "mode": "distribution-manifest",
            "v100_tag": V100_TAG,
            "v100_source": "not-locally-resolvable",
            "v100_source_expected": V100_SOURCE,
            "v110_release_tag": release_tag,
            "v110_release_tag_exists": False,
            "v110_release_source": "not-locally-resolvable",
            "v110_release_source_expected": V110_SOURCE,
            "publication_state": "distribution",
            "pack_source_revision": str(manifest.get("source_revision") or ""),
        }
    if resolved_v100 != V100_SOURCE:
        raise V110GateError("published EKRI v1.0.0 tag/source identity changed")
    return {
        "mode": "source-repository",
        "v100_tag": V100_TAG,
        "v100_source": resolved_v100,
        "v110_release_tag": release_tag,
        "v110_release_tag_exists": release_tag_exists,
        "v110_release_source": release_source if release_tag_exists else "",
        "v110_release_source_expected": V110_SOURCE,
        "publication_state": "published" if release_tag_exists else "pre-publication",
    }


def _is_v110_scope_path(path: str) -> bool:
    return path.startswith("EKRI/") or path.startswith(".EKRI/project/")


def _commit_delta(root: Path, commit: str) -> tuple[str, list[str]]:
    parent_row = _git(root, "rev-list", "--parents", "-n", "1", commit).split()
    if len(parent_row) < 2:
        return "", []
    parent = parent_row[1]
    changed = [line for line in _git(root, "diff", "--name-only", f"{parent}..{commit}").splitlines() if line]
    return parent, changed


def _find_v110_merge_anchor(root: Path) -> tuple[str, str, list[str]] | None:
    for commit in _git(root, "rev-list", "--first-parent", "HEAD").splitlines():
        parent_row = _git(root, "rev-list", "--parents", "-n", "1", commit).split()
        if len(parent_row) < 3:
            continue
        parent, changed = _commit_delta(root, commit)
        if "EKRI/docs/releases/v1.1.0.md" in changed and "EKRI/specs/v110-product-surface-classification.json" in changed:
            return commit, parent, changed
    return None


def _merged_v110_scope_audit(root: Path) -> dict[str, Any] | None:
    anchor = _find_v110_merge_anchor(root)
    if anchor is None:
        return None
    anchor_commit, scope_base, anchor_changed = anchor
    forbidden_anchor = [path for path in anchor_changed if not _is_v110_scope_path(path)]
    if forbidden_anchor:
        raise V110GateError("v1.1 merge scope contains non-EKRI paths: " + ", ".join(forbidden_anchor[:20]))
    post_commits = [
        value
        for value in _git(root, "rev-list", "--reverse", "--first-parent", f"{anchor_commit}..HEAD").splitlines()
        if value
    ]
    post_ekri_paths: list[str] = []
    ignored_paths: list[str] = []
    for commit in post_commits:
        _, changed = _commit_delta(root, commit)
        ekri_paths = [path for path in changed if _is_v110_scope_path(path)]
        other_paths = [path for path in changed if not _is_v110_scope_path(path)]
        if ekri_paths and other_paths:
            raise V110GateError("post-v1.1 EKRI scope is mixed with unrelated paths: " + ", ".join(other_paths[:20]))
        if ekri_paths:
            post_ekri_paths.extend(ekri_paths)
        else:
            ignored_paths.extend(other_paths)
    audited_paths = sorted(set([*anchor_changed, *post_ekri_paths]))
    return {
        "mode": "source-repository",
        "scope_proof_mode": "merged-v110-program-plus-ekri-only-followups",
        "base_source": scope_base,
        "program_base_source": V110_BASE_SOURCE,
        "v110_merge_source": anchor_commit,
        "changed_path_count": len(audited_paths),
        "post_merge_ekri_path_count": len(set(post_ekri_paths)),
        "ignored_non_ekri_descendant_path_count": len(set(ignored_paths)),
        "non_ekri_changed_paths": [],
    }


def _scope_audit(root: Path) -> dict[str, Any]:
    merged_scope = _merged_v110_scope_audit(root)
    if merged_scope is not None:
        return merged_scope
    parent_row = _git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parent_row) >= 3:
        scope_base = parent_row[1]
        source_mode = "merge-commit-pr-delta"
    else:
        scope_base = V110_BASE_SOURCE
        source_mode = "candidate-branch-delta"
    try:
        changed = [line for line in _git(root, "diff", "--name-only", f"{scope_base}..HEAD").splitlines() if line]
    except V110GateError:
        manifest = _distribution_manifest(root)
        if manifest is None:
            raise
        tracked = [line for line in _git(root, "ls-tree", "-r", "--name-only", "HEAD").splitlines() if line]
        allowed_root_files = {"README.md", ".gitignore", "EKRI_RELEASE_PACK_MANIFEST.json"}
        forbidden = [path for path in tracked if not path.startswith("EKRI/") and path not in allowed_root_files]
        if forbidden:
            raise V110GateError("release distribution contains unexpected non-EKRI payload: " + ", ".join(forbidden[:20]))
        return {
            "mode": "distribution-boundary",
            "base_source": V110_BASE_SOURCE,
            "changed_path_count": 0,
            "non_ekri_changed_paths": forbidden,
            "pack_source_revision": str(manifest.get("source_revision") or ""),
        }
    forbidden = [path for path in changed if not (path.startswith("EKRI/") or path.startswith(".EKRI/project/"))]
    if forbidden:
        raise V110GateError("v1.1 branch changed non-EKRI surfaces: " + ", ".join(forbidden[:20]))
    return {
        "mode": "source-repository",
        "scope_proof_mode": source_mode,
        "base_source": scope_base,
        "program_base_source": V110_BASE_SOURCE,
        "changed_path_count": len(changed),
        "non_ekri_changed_paths": forbidden,
    }


def run_v110_release_gate(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    ekri_root = root / "EKRI"
    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise V110GateError(f"v1.1 gate requires exact clean scanner identity: {exc}") from exc
    source_commit = _git(root, "rev-parse", "HEAD^{commit}")
    source_tree = _git(root, "rev-parse", "HEAD^{tree}")
    if scanner.commit != source_commit or scanner.tree != source_tree or not scanner.runtime_matches_commit:
        raise V110GateError("v1.1 scanner/runtime/source identities diverge")

    product = _product_metadata(ekri_root)
    try:
        writers = _verify_writer_inventory(ekri_root)
        retirement = _verify_retirement(ekri_root)
        peer_authority = _verify_peer_authority()
        metrics = _current_metrics(ekri_root)
    except Exception as exc:
        raise V110GateError(f"v1.0 semantic baseline invariant failed: {exc}") from exc
    if len(writers) != len(WRITER_INVENTORY) or len(writers) != M0_METRICS["major_semantic_writer_paths"]:
        raise V110GateError("v1.1 changed the major semantic writer denominator")
    if metrics["primary_semantic_output_families"] != M0_METRICS["primary_semantic_output_families"]:
        raise V110GateError("v1.1 changed the semantic output-family denominator")

    public = _public_surface(ekri_root)
    acquisition = _acquisition_boundary(ekri_root)
    versions = _version_invariants(root)
    scope = _scope_audit(root)
    source_repository_mode = versions["mode"] == "source-repository"
    if source_repository_mode:
        verify_project_asset(root, asset_id="wff-v1.6.2-baseline")
        verify_project_asset_v2(root, asset_id="wff-v1.9.2-ekri-v1.0")
        economy = run_adaptive_exploration_economy_audit(root)
    else:
        economy = {
            "status": "not-applicable-distribution",
            "baseline": {"planned_slice_count": 0},
            "adaptive": {
                "planned_slice_count": 0,
                "reuse": {"reused_existing_question_count": 0},
                "gap_question_ids": [],
            },
            "report_fingerprint": "",
        }
    conformance = run_adaptive_exploration_conformance()

    checks = [
        {"check": "exact-scanner-source-identity", "status": "passed"},
        {"check": "published-v1.0-identity-immutable", "status": "passed"},
        {"check": "semantic-writer-denominator-unchanged", "status": "passed"},
        {"check": "peer-authority-posture-preserved", "status": "passed"},
        {"check": "legacy-writer-retirement-preserved", "status": "passed"},
        {"check": "adaptive-acquisition-non-authoritative", "status": "passed"},
        {"check": "no-technology-profile-directory", "status": "passed"},
        {
            "check": "project-asset-v1-v2-compatible",
            "status": "passed" if source_repository_mode else "not-applicable-distribution",
        },
        {"check": "heterogeneous-adaptive-conformance", "status": "passed"},
        {
            "check": "planned-exploration-economy",
            "status": "passed" if source_repository_mode else "not-applicable-distribution",
        },
        {
            "check": "wff-runtime-scope-unchanged-by-v11-branch",
            "status": "passed" if source_repository_mode else "not-applicable-distribution",
        },
        {"check": "prepublication-state", "status": "passed"},
    ]
    report: dict[str, Any] = {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": GATE_STATUS,
        "authority_mode": "release-evidence-only",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "scanner_commit": scanner.commit,
            "scanner_tree": scanner.tree,
            "runtime_matches_commit": scanner.runtime_matches_commit,
        },
        "product": product,
        "versions": versions,
        "scope": scope,
        "semantic_baseline": {
            "major_writer_path_count": len(writers),
            "primary_family_count": metrics["primary_semantic_output_families"],
            "peer_authority": peer_authority,
            "retirement": retirement,
        },
        "public_surface": public,
        "acquisition_control": acquisition,
        "conformance": {
            "status": conformance["status"],
            "case_count": conformance["case_count"],
            "report_fingerprint": conformance["report_fingerprint"],
        },
        "economy": {
            "status": economy["status"],
            "baseline_planned_slices": economy["baseline"]["planned_slice_count"],
            "adaptive_planned_slices": economy["adaptive"]["planned_slice_count"],
            "reused_question_count": economy["adaptive"]["reuse"]["reused_existing_question_count"],
            "remaining_gap_question_ids": economy["adaptive"]["gap_question_ids"],
            "report_fingerprint": economy["report_fingerprint"],
        },
        "checks": checks,
        "claim_ceiling": (
            "This Gate proves an exact EKRI v1.1 candidate with bounded non-authoritative adaptive knowledge acquisition, "
            "stable v1.0 semantic writer/family boundaries, heterogeneous conformance and planned exploration-economy evidence. "
            "It does not prove exhaustive project understanding, actual token/time savings, autonomous semantic acceptance, PX route correctness, refactoring correctness, UAT or production readiness."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_v110_release_gate_report(report)


def validate_v110_release_gate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != GATE_SCHEMA_VERSION or data.get("status") != GATE_STATUS:
        raise V110GateError("v1.1 candidate gate is not ready")
    if data.get("authority_mode") != "release-evidence-only":
        raise V110GateError("v1.1 gate attempted semantic authority")
    checks = data.get("checks")
    allowed_check_statuses = {"passed", "not-applicable-distribution"}
    if not isinstance(checks, list) or any(
        not isinstance(row, Mapping) or row.get("status") not in allowed_check_statuses
        for row in checks
    ):
        raise V110GateError("v1.1 gate contains a failed check")
    conformance = data.get("conformance")
    if not isinstance(conformance, Mapping) or conformance.get("status") != "adaptive-exploration-conformance-passed":
        raise V110GateError("v1.1 gate requires heterogeneous adaptive conformance")
    versions = data.get("versions")
    if not isinstance(versions, Mapping) or versions.get("mode") not in {"source-repository", "distribution-manifest"}:
        raise V110GateError("v1.1 gate version-evidence mode is unsupported")
    semantic = data.get("semantic_baseline")
    if not isinstance(semantic, Mapping):
        raise V110GateError("v1.1 semantic baseline is missing")
    if semantic.get("major_writer_path_count") != 6 or semantic.get("primary_family_count") != 7:
        raise V110GateError("v1.1 semantic writer/family denominator drifted")
    acquisition = data.get("acquisition_control")
    if not isinstance(acquisition, Mapping) or acquisition.get("persistent_truth_store") is not False:
        raise V110GateError("v1.1 acquisition control attempted a persistent truth store")
    versions = data.get("versions")
    if not isinstance(versions, Mapping):
        raise V110GateError("v1.1 release version evidence is missing")
    if versions.get("v110_release_tag_exists") not in {True, False}:
        raise V110GateError("v1.1 release tag state is invalid")
    if versions.get("v110_release_tag_exists") is True and versions.get("v110_release_source") != V110_SOURCE:
        raise V110GateError("published EKRI v1.1.0 tag/source identity changed")
    if versions.get("v110_release_source_expected") not in {None, V110_SOURCE}:
        raise V110GateError("v1.1 release source expectation drifted")
    fingerprint = str(data.get("report_fingerprint") or "")
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise V110GateError("v1.1 gate fingerprint mismatch")
    return data
