"""EKRI v1.0 Release Candidate gate.

The P9 gate verifies the exact source state of the first supported Engineering
Knowledge System architecture release.  It is deliberately read-only: it does
not create a tag, GitHub Release, release pack, semantic authority, or project
runtime state.

Release-pack construction/audit and independent-worktree execution are separate
P9 evidence lanes over the same exact candidate.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any, Mapping

from .architecture_roundtrip import VIEW_AUTHORITY_MODE
from .capability_authority import AUTHORITY_MODE as CAPABILITY_AUTHORITY_MODE
from .capability_query import INDEX_AUTHORITY_MODE
from .flow_query import AUTHORITY_MODE as FLOW_AUTHORITY_MODE
from .nonwff_conformance import run_nonwff_conformance
from .observation_boundary import ObservationBoundaryError, resolve_scanner_identity
from .repository_firewall_stress import AUTHORITY_MODE as FIREWALL_VIEW_AUTHORITY_MODE


GATE_SCHEMA_VERSION = "ekri.v100-release-gate.v1"
GATE_STATUS = "v100-release-candidate-ready"
GATE_VERSION = "ekri.v100-release-gate.v0.1"
PRODUCT_VERSION = "1.0.0"

M0_METRICS = {
    "product_metadata_version": "0.8.0",
    "schema_files": 28,
    "test_modules": 12,
    "src_modules": 16,
    "src_loc": 12431,
    "cli_scripts": 13,
    "public_exports": 55,
    "selected_general_semantic_loc": 5815,
    "major_semantic_writer_paths": 6,
    "primary_semantic_output_families": 7,
    "named_reconciliation_paths": 5,
}

WRITER_INVENTORY = (
    {
        "writer_id": "architecture",
        "module": "knowledge_reconstruction.py",
        "symbol": "reconstruct_and_persist_wff_baseline",
        "families": ["Architecture"],
        "authority_posture": "accepted-architecture-authority",
    },
    {
        "writer_id": "capability",
        "module": "capability_authority.py",
        "symbol": "build_capability_semantic_authority",
        "families": ["Capability"],
        "authority_posture": "ontology-authoritative",
    },
    {
        "writer_id": "repository-asset-identity",
        "module": "repository_asset_identity.py",
        "symbol": "build_repository_asset_knowledge_map",
        "families": ["Asset Identity"],
        "authority_posture": "evidence-bounded",
    },
    {
        "writer_id": "repository-ownership-boundary",
        "module": "repository_ownership_boundary.py",
        "symbol": "build_repository_ownership_boundary_map",
        "families": ["Ownership Boundary"],
        "authority_posture": "evidence-bounded-ownership-firewall",
    },
    {
        "writer_id": "repository-lifecycle-observation",
        "module": "repository_lifecycle_observation.py",
        "symbol": "build_repository_lifecycle_observation_snapshot",
        "families": ["Lifecycle Observation"],
        "authority_posture": "observation-only",
    },
    {
        "writer_id": "evolution-impact",
        "module": "evolution_intelligence.py",
        "symbol": "run_phase3_evolution_analysis",
        "families": ["Evolution", "Impact"],
        "authority_posture": "evolution-authoritative-impact-predictive",
    },
)

RECONCILIATION_LEDGER = (
    {
        "m0_path": "Architecture Memory -> Capability Catalog",
        "v100_status": "retired-demoted",
        "v100_path": "Architecture authority -> Architecture View -> Capability Authority -> derived legacy Catalog",
        "evidence": "P6 cutover + P7 retired private Catalog writer/evaluator",
    },
    {
        "m0_path": "Architecture/Capability -> Asset Identity",
        "v100_status": "retained-bounded",
        "v100_path": "Architecture/Capability authority evidence -> Asset Identity",
        "evidence": "retained because repository asset identity remains an independently bounded semantic slice",
    },
    {
        "m0_path": "Asset Identity -> Ownership Boundary",
        "v100_status": "retained-safety-boundary",
        "v100_path": "Asset Identity -> Ownership Boundary",
        "evidence": "retained to preserve structural-evidence-vs-semantic-ownership firewall",
    },
    {
        "m0_path": "Asset Identity -> Lifecycle Observation",
        "v100_status": "retained-safety-boundary",
        "v100_path": "Asset Identity -> Lifecycle Observation",
        "evidence": "retained to preserve observation-vs-retirement/deletion firewall",
    },
    {
        "m0_path": "Architecture/Capability -> Evolution / Impact",
        "v100_status": "source-rebound-partially-converged",
        "v100_path": "Architecture authority + Capability Authority -> Evolution / predictive Impact",
        "evidence": "Evolution consumes Capability Authority directly; legacy Capability Catalog reconstruction removed",
    },
)

RETIRED_CAPABILITY_SYMBOLS = frozenset(
    {
        "_VerifiedCapabilityCatalog",
        "_build_verified_capability_catalog",
        "_evaluate_before_generate",
    }
)

FORBIDDEN_PUBLIC_INTERNAL_EXPORTS = frozenset(
    {
        "compile_phase1_architecture_shadow",
        "derive_architecture_view",
        "build_capability_semantic_authority",
        "build_capability_query_index",
        "run_repository_firewall_stress",
        "run_nonwff_conformance",
    }
)

EXPECTED_SUPPORTED_GENERAL = frozenset(
    {
        "observation-trust-boundary",
        "engineering-architecture-view",
        "capability-semantic-authority",
        "capability-named-queries",
        "bounded-flow-handoff-query",
        "repository-asset-identity",
        "repository-ownership-boundary",
        "repository-lifecycle-observation",
        "evolution-impact-intelligence",
        "portable-project-knowledge",
    }
)
EXPECTED_WFF_PROFILE = frozenset(
    {
        "wff-before-generate",
        "wff-core-analysis",
        "wff-fixed-baseline-reconstruction",
    }
)
EXPECTED_INTERNAL = frozenset(
    {
        "raw-ooa-substrate",
        "architecture-roundtrip-tooling",
        "repository-firewall-stress",
        "nonwff-conformance-harness",
    }
)

SELECTED_CURRENT_GENERAL_MODULES = (
    "knowledge_reconstruction.py",
    "capability_contract.py",
    "capability_authority.py",
    "capability_query.py",
    "flow_query.py",
    "evolution_intelligence.py",
    "repository_asset_identity.py",
    "repository_ownership_boundary.py",
    "repository_lifecycle_observation.py",
)


class V100ReleaseGateError(RuntimeError):
    """Raised when the v1.0 RC source state violates a release-gate invariant."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise V100ReleaseGateError(f"{label} must not be empty")
    return text


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V100ReleaseGateError(f"{label} must be an object")
    return dict(value)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V100ReleaseGateError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise V100ReleaseGateError(f"{label} must contain an object")
    return value


def _git(repository_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
        env={**dict(__import__("os").environ), "GIT_NO_REPLACE_OBJECTS": "1"},
    )
    if proc.returncode != 0:
        raise V100ReleaseGateError(
            f"git {' '.join(args)} failed: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _source_tree(path: Path) -> ast.AST:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise V100ReleaseGateError(f"cannot parse source module {path.name}: {exc}") from exc


def _source_definitions(path: Path) -> set[str]:
    tree = _source_tree(path)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _source_identifier_references(path: Path) -> set[str]:
    tree = _source_tree(path)
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            referenced.add(node.attr)
    return referenced


def _public_exports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise V100ReleaseGateError(f"cannot parse EKRI public package: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError) as exc:
            raise V100ReleaseGateError("EKRI __all__ must be a literal list") from exc
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise V100ReleaseGateError("EKRI __all__ must contain strings")
        return value
    raise V100ReleaseGateError("EKRI __all__ was not found")


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError as exc:
        raise V100ReleaseGateError(f"cannot count source lines: {path}") from exc


def _current_metrics(ekri_root: Path) -> dict[str, int]:
    source_root = ekri_root / "src" / "ekri"
    src_files = sorted(source_root.glob("*.py"))
    selected_paths = [source_root / name for name in SELECTED_CURRENT_GENERAL_MODULES]
    missing_selected = [path.name for path in selected_paths if not path.is_file()]
    if missing_selected:
        raise V100ReleaseGateError(
            "selected general semantic module missing: " + ", ".join(missing_selected)
        )
    return {
        "schema_files": len(list((ekri_root / "schemas").glob("*.json"))),
        "test_modules": len(list((ekri_root / "tests").glob("test_*.py"))),
        "src_modules": len(src_files),
        "src_loc": sum(_line_count(path) for path in src_files),
        "cli_scripts": len(list((ekri_root / "scripts").glob("*.py"))),
        "public_exports": len(_public_exports(source_root / "__init__.py")),
        "selected_general_semantic_loc": sum(_line_count(path) for path in selected_paths),
        "major_semantic_writer_paths": len(WRITER_INVENTORY),
        "primary_semantic_output_families": sum(len(row["families"]) for row in WRITER_INVENTORY),
    }


def _verify_writer_inventory(ekri_root: Path) -> list[dict[str, Any]]:
    source_root = ekri_root / "src" / "ekri"
    rows: list[dict[str, Any]] = []
    for expected in WRITER_INVENTORY:
        module = source_root / str(expected["module"])
        definitions = _source_definitions(module)
        symbol = str(expected["symbol"])
        if symbol not in definitions:
            raise V100ReleaseGateError(
                f"semantic writer missing from {module.name}: {symbol}"
            )
        rows.append(dict(expected))
    if len(rows) != M0_METRICS["major_semantic_writer_paths"]:
        raise V100ReleaseGateError("v1.0 major semantic writer-path denominator changed")
    if sum(len(row["families"]) for row in rows) != M0_METRICS["primary_semantic_output_families"]:
        raise V100ReleaseGateError("v1.0 semantic output-family denominator changed")
    return rows


def _verify_retirement(ekri_root: Path) -> dict[str, Any]:
    source_root = ekri_root / "src" / "ekri"
    definitions: set[str] = set()
    references: set[str] = set()
    for path in sorted(source_root.glob("*.py")):
        definitions.update(_source_definitions(path))
        references.update(_source_identifier_references(path))
    remaining_definitions = sorted(RETIRED_CAPABILITY_SYMBOLS & definitions)
    remaining_references = sorted(RETIRED_CAPABILITY_SYMBOLS & references)
    if remaining_definitions or remaining_references:
        raise V100ReleaseGateError(
            "retired Capability semantic writer/evaluator still exists: "
            + ", ".join(sorted(set(remaining_definitions + remaining_references)))
        )
    retired_paths = [
        row for row in RECONCILIATION_LEDGER if row["v100_status"] == "retired-demoted"
    ]
    if not retired_paths:
        raise V100ReleaseGateError("v1.0 has no proved reconciliation retirement")
    return {
        "retired_symbols": sorted(RETIRED_CAPABILITY_SYMBOLS),
        "remaining_definitions": remaining_definitions,
        "remaining_references": remaining_references,
        "retired_reconciliation_path_count": len(retired_paths),
    }


def _verify_peer_authority() -> dict[str, Any]:
    actual = {
        "architecture_view": VIEW_AUTHORITY_MODE,
        "capability_authority": CAPABILITY_AUTHORITY_MODE,
        "capability_query_index": INDEX_AUTHORITY_MODE,
        "flow_query_model": FLOW_AUTHORITY_MODE,
        "repository_firewall_stress": FIREWALL_VIEW_AUTHORITY_MODE,
    }
    expected = {
        "architecture_view": "derived-non-authoritative",
        "capability_authority": "ontology-authoritative",
        "capability_query_index": "derived-non-authoritative",
        "flow_query_model": "derived-non-authoritative",
        "repository_firewall_stress": "derived-non-authoritative",
    }
    if actual != expected:
        raise V100ReleaseGateError(
            f"peer-authority posture drifted: actual={actual!r}"
        )
    return actual


def _verify_product_metadata(ekri_root: Path) -> dict[str, Any]:
    try:
        pyproject = tomllib.loads((ekri_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise V100ReleaseGateError(f"pyproject cannot be read: {exc}") from exc
    project = _mapping(pyproject.get("project"), "pyproject project")
    version = _text(project.get("version"), "EKRI product version")
    if version != PRODUCT_VERSION:
        raise V100ReleaseGateError(
            f"EKRI product version is not {PRODUCT_VERSION}: {version}"
        )

    changelog_path = ekri_root / "CHANGELOG.md"
    release_notes_path = ekri_root / "docs" / "releases" / "v1.0.0.md"
    contract_path = ekri_root / "docs" / "v100-supported-product-contract-v1.0.md"
    classification_path = ekri_root / "specs" / "v100-product-surface-classification.json"
    for path in (changelog_path, release_notes_path, contract_path, classification_path):
        if not path.is_file():
            raise V100ReleaseGateError(f"required v1.0 product record missing: {path}")

    changelog = changelog_path.read_text(encoding="utf-8")
    release_notes = release_notes_path.read_text(encoding="utf-8")
    contract = contract_path.read_text(encoding="utf-8")
    if "## [1.0.0] - 2026-08-13" not in changelog:
        raise V100ReleaseGateError("CHANGELOG lacks the v1.0.0 release entry")
    if "not yet published/tagged" not in release_notes:
        raise V100ReleaseGateError("v1.0 release notes do not preserve pre-publication posture")
    for required in (
        "one semantic authority per knowledge slice/context",
        "conflicting",
        "peer dual-write",
        "EKRI/specs/v100-product-surface-classification.json",
    ):
        if required not in contract:
            raise V100ReleaseGateError(
                f"supported product contract lacks required invariant: {required}"
            )

    classification = _read_json(classification_path, "v1.0 product surface classification")
    if classification.get("schema_version") != "ekri.v100-product-surface-classification.v1":
        raise V100ReleaseGateError("unsupported v1.0 surface classification schema")
    if classification.get("product_version") != PRODUCT_VERSION:
        raise V100ReleaseGateError("surface classification product version mismatch")
    supported = {
        str(row.get("surface_id") or "")
        for row in classification.get("supported_general", [])
        if isinstance(row, Mapping)
    }
    wff_profile = {
        str(row.get("surface_id") or "")
        for row in classification.get("wff_profile_compatibility", [])
        if isinstance(row, Mapping)
    }
    internal = {
        str(row.get("surface_id") or "")
        for row in classification.get("experimental_internal", [])
        if isinstance(row, Mapping)
    }
    if supported != EXPECTED_SUPPORTED_GENERAL:
        raise V100ReleaseGateError("supported-general surface classification drifted")
    if wff_profile != EXPECTED_WFF_PROFILE:
        raise V100ReleaseGateError("WFF-profile surface classification drifted")
    if internal != EXPECTED_INTERNAL:
        raise V100ReleaseGateError("internal/experimental surface classification drifted")

    rollback = _mapping(classification.get("rollback_policy"), "rollback policy")
    forbidden = set(rollback.get("forbidden", []))
    required_forbidden = {
        "peer dual-write",
        "bidirectional semantic synchronization",
        "silent fallback between authoritative writers",
    }
    if forbidden != required_forbidden:
        raise V100ReleaseGateError("single-authority rollback forbidden set drifted")

    return {
        "version": version,
        "changelog": str(changelog_path.relative_to(ekri_root.parent)),
        "release_notes": str(release_notes_path.relative_to(ekri_root.parent)),
        "supported_product_contract": str(contract_path.relative_to(ekri_root.parent)),
        "surface_classification": str(classification_path.relative_to(ekri_root.parent)),
        "supported_general_count": len(supported),
        "wff_profile_compatibility_count": len(wff_profile),
        "internal_experimental_count": len(internal),
    }


def _verify_public_surface(ekri_root: Path) -> dict[str, Any]:
    exports = _public_exports(ekri_root / "src" / "ekri" / "__init__.py")
    leaked = sorted(FORBIDDEN_PUBLIC_INTERNAL_EXPORTS & set(exports))
    if leaked:
        raise V100ReleaseGateError(
            "internal/migration implementation leaked into public __all__: "
            + ", ".join(leaked)
        )
    required = {
        "CapabilityQueryService",
        "find_capability",
        "get_realizations",
        "explain_authority",
        "get_evidence",
        "FlowQueryService",
        "trace_flow",
        "run_phase3_evolution_analysis",
        "verify_project_asset",
    }
    missing = sorted(required - set(exports))
    if missing:
        raise V100ReleaseGateError(
            "supported public APIs missing from EKRI __all__: " + ", ".join(missing)
        )
    return {
        "public_export_count": len(exports),
        "required_supported_exports": sorted(required),
        "forbidden_internal_exports_present": leaked,
    }


def _verify_publication_state(repository_root: Path) -> dict[str, Any]:
    release_tag = f"ekri/v{PRODUCT_VERSION}"
    rc_tags = [
        line.strip()
        for line in _git(repository_root, "tag", "--list", f"{release_tag}-rc.*").splitlines()
        if line.strip()
    ]
    release_tags = [
        line.strip()
        for line in _git(repository_root, "tag", "--list", release_tag).splitlines()
        if line.strip()
    ]
    if release_tags or rc_tags:
        raise V100ReleaseGateError(
            "P9 source gate must run before v1.0 publication/tag creation"
        )
    return {
        "state": "not-published",
        "release_tag": release_tag,
        "release_tag_exists": False,
        "rc_tags": [],
        "publication_requires_explicit_approval": True,
    }


def run_v100_release_gate(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    ekri_root = root / "EKRI"
    if not ekri_root.is_dir():
        raise V100ReleaseGateError("repository root does not contain top-level EKRI")
    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise V100ReleaseGateError(
            f"v1.0 gate requires exact clean scanner identity: {exc}"
        ) from exc
    if Path(scanner.repository_root).resolve() != root:
        raise V100ReleaseGateError(
            "v1.0 gate repository_root does not match active scanner repository"
        )

    source_commit = _git(root, "rev-parse", "HEAD^{commit}")
    source_tree = _git(root, "rev-parse", "HEAD^{tree}")
    if scanner.commit != source_commit or scanner.tree != source_tree:
        raise V100ReleaseGateError("scanner and release candidate Git identities diverge")
    if not scanner.runtime_matches_commit:
        raise V100ReleaseGateError("active EKRI runtime does not match the release candidate commit")

    product = _verify_product_metadata(ekri_root)
    writer_inventory = _verify_writer_inventory(ekri_root)
    retirement = _verify_retirement(ekri_root)
    peer_authority = _verify_peer_authority()
    public_surface = _verify_public_surface(ekri_root)
    current_metrics = _current_metrics(ekri_root)
    publication = _verify_publication_state(root)
    nonwff = run_nonwff_conformance(root)
    if nonwff.get("status") != "nonwff-product-conformance-passed":
        raise V100ReleaseGateError("non-WFF conformance did not pass")

    retired_reconciliation_count = sum(
        row["v100_status"] == "retired-demoted" for row in RECONCILIATION_LEDGER
    )
    converged_reconciliation_count = sum(
        row["v100_status"] in {"retired-demoted", "source-rebound-partially-converged"}
        for row in RECONCILIATION_LEDGER
    )
    if retired_reconciliation_count < 1:
        raise V100ReleaseGateError("v1.0 migration did not retire a reconciliation path")
    if current_metrics["major_semantic_writer_paths"] > M0_METRICS["major_semantic_writer_paths"]:
        raise V100ReleaseGateError("v1.0 introduced a new peer semantic writer path")

    complexity_interpretation = {
        "overall_loc_reduction_claimed": False,
        "m0_src_loc": M0_METRICS["src_loc"],
        "v100_src_loc": current_metrics["src_loc"],
        "m0_selected_general_semantic_loc": M0_METRICS["selected_general_semantic_loc"],
        "v100_selected_general_semantic_loc": current_metrics["selected_general_semantic_loc"],
        "writer_path_count_m0": M0_METRICS["major_semantic_writer_paths"],
        "writer_path_count_v100": current_metrics["major_semantic_writer_paths"],
        "real_retirement_proved": True,
        "interpretation": (
            "v1.0 intentionally adds supported Engineering Knowledge Model/query/Flow/conformance capability, so total LOC growth is not treated as a complexity win. "
            "The release Gate requires no increase in peer semantic writer paths plus concrete retirement/demotion of duplicated Capability authority/reconciliation, which P6/P7 satisfy."
        ),
    }

    checks = [
        {"check": "exact-scanner-source-identity", "status": "passed", "detail": f"scanner/runtime exactly match {source_commit}"},
        {"check": "v100-product-metadata", "status": "passed", "detail": "pyproject, changelog, release notes, product contract and surface classification agree on v1.0.0"},
        {"check": "semantic-writer-denominator", "status": "passed", "detail": "six major writer paths still produce seven primary semantic families; no Flow/View peer writer was introduced"},
        {"check": "capability-single-authority", "status": "passed", "detail": "Capability Authority is ontology-authoritative while Query Index/legacy outputs are derived"},
        {"check": "legacy-capability-retirement", "status": "passed", "detail": "retired private Capability Catalog writer/evaluator definitions and references are absent"},
        {"check": "reconciliation-convergence", "status": "passed", "detail": f"{retired_reconciliation_count}/5 M0 reconciliation paths retired/demoted; {converged_reconciliation_count}/5 retired or source-rebound"},
        {"check": "peer-authority-firewall", "status": "passed", "detail": "Architecture View, Capability Query Index, Flow model and firewall stress View remain non-authoritative"},
        {"check": "public-api-boundary", "status": "passed", "detail": "supported normal-consumer APIs are exported while raw migration/conformance builders remain internal"},
        {"check": "nonwff-product-conformance", "status": "passed", "detail": f"Mercury conformance passed with report {nonwff['report_fingerprint']}"},
        {"check": "supported-experimental-classification", "status": "passed", "detail": "supported general, WFF-profile compatibility and internal/experimental surfaces are machine-classified"},
        {"check": "single-authority-rollback-policy", "status": "passed", "detail": "peer dual-write, bidirectional sync and silent authority fallback are explicitly forbidden"},
        {"check": "pre-publication-state", "status": "passed", "detail": "no ekri/v1.0.0 or v1.0.0 RC tag exists; publication remains blocked pending explicit approval"},
    ]

    report: dict[str, Any] = {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": GATE_STATUS,
        "gate_version": GATE_VERSION,
        "authority_mode": "release-evidence-only",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "scanner_commit": scanner.commit,
            "scanner_tree": scanner.tree,
            "runtime_matches_commit": scanner.runtime_matches_commit,
            "scanner_surface_path_count": scanner.surface_path_count,
        },
        "product": product,
        "m0_baseline": dict(M0_METRICS),
        "current_metrics": current_metrics,
        "semantic_writer_inventory": {
            "major_writer_path_count": len(writer_inventory),
            "primary_output_family_count": sum(len(row["families"]) for row in writer_inventory),
            "writers": writer_inventory,
        },
        "peer_authority_posture": peer_authority,
        "retirement": retirement,
        "reconciliation_ledger": list(RECONCILIATION_LEDGER),
        "complexity_interpretation": complexity_interpretation,
        "query_surface": {
            "general_named_queries": [
                "find-capability",
                "get-realizations",
                "explain-authority",
                "get-evidence",
                "trace-flow",
            ],
            "wff_profile_compatibility_query": "before-generate",
            "named_batch_intelligence": ["evolution-impact"],
            "raw_kernel_traversal_required": False,
        },
        "public_surface": public_surface,
        "nonwff_conformance": {
            "status": nonwff["status"],
            "fixture_id": nonwff["fixture"]["fixture_id"],
            "report_fingerprint": nonwff["report_fingerprint"],
            "query_observations": nonwff["query_observations"],
        },
        "publication": publication,
        "checks": checks,
        "claim_ceiling": (
            "This Gate proves an exact EKRI v1.0.0 Release Candidate source state with supported general model/query contracts, one-authority-per-slice semantics, one completed Capability cutover/retirement chain, preserved bounded authority firewalls and WFF plus non-WFF conformance. "
            "It does not create a tag/Release, prove universal ontology completeness, exhaustive absence/dependency knowledge, autonomous governance authority, host production readiness, or production approval. Publication requires explicit authorization after post-merge RC validation."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_v100_release_gate_report(report)


def validate_v100_release_gate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != GATE_SCHEMA_VERSION:
        raise V100ReleaseGateError("unsupported v1.0 release-gate schema")
    if data.get("status") != GATE_STATUS:
        raise V100ReleaseGateError("v1.0 release candidate is not ready")
    if data.get("authority_mode") != "release-evidence-only":
        raise V100ReleaseGateError("release gate attempted semantic authority")
    checks = data.get("checks")
    if not isinstance(checks, list) or len(checks) < 12:
        raise V100ReleaseGateError("v1.0 release-gate checks are incomplete")
    if any(not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks):
        raise V100ReleaseGateError("v1.0 release-gate contains failed checks")
    publication = _mapping(data.get("publication"), "publication")
    if publication.get("state") != "not-published" or publication.get("release_tag_exists") is not False:
        raise V100ReleaseGateError("release Gate must stop before publication")
    fingerprint = _text(data.get("report_fingerprint"), "release-gate report fingerprint")
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise V100ReleaseGateError("v1.0 release-gate fingerprint mismatch")
    return data
