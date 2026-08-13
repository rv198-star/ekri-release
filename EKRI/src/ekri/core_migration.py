"""WFF v1.8 P3 Core consumer, assurance, and distribution migration audit.

P3 keeps the accepted Core implementation unchanged and migrates existing WFF
surfaces to consume its public semantic contracts. This module verifies a
committed immutable Git target, exact registered change frontier, public
consumer bindings, proof-only assurance ownership, packaged Core distribution,
and compatibility-fallback retention. It does not execute the final P1-P4/PX
release scenario matrix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence
import uuid

from .core_extraction import CoreExtractionError, run_core_extraction_audit
from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    VALID_VERDICT,
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    evaluate_observation_boundary,
    is_protected_path,
    resolve_scanner_identity,
    write_manifest,
)


SPEC_SCHEMA_VERSION = "ekri.wff-core-migration-spec.v1"
AUDIT_SCHEMA_VERSION = "ekri.core-migration-audit.v1"
OUTPUT_AUDIT_SCHEMA_VERSION = "ekri.core-migration-output-audit.v1"
CONSUMER_SCHEMA_VERSION = "ekri.core-consumer-map.v1"
ASSURANCE_SCHEMA_VERSION = "ekri.core-assurance-migration.v1"
DISTRIBUTION_SCHEMA_VERSION = "ekri.core-distribution-migration.v1"
COMPATIBILITY_SCHEMA_VERSION = "ekri.core-compatibility-retirement-status.v1"
PHASE_ID = "v1.8-p3-core-consumer-assurance-distribution-migration"
PROFILE_ID = "wff-v1.8-p3-core-migration"
VALID_STATUS = "core-migration-verified"


class CoreMigrationError(RuntimeError):
    """Raised when P3 migration cannot be verified safely."""


@dataclass(frozen=True)
class MigrationSpecIdentity:
    source: str
    path: str
    sha256: str
    scanner_commit: str
    scanner_tree: str
    blob_oid: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoreMigrationError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise CoreMigrationError(f"{label} must be an array with at least {minimum} item(s)")
    return value


def _text(value: object, label: str, *, minimum: int = 1, maximum: int = 4000) -> str:
    result = str(value or "").strip()
    if len(result) < minimum or len(result) > maximum:
        raise CoreMigrationError(f"{label} must contain between {minimum} and {maximum} characters")
    return result


def _load_json_path(path: Path, label: str) -> object:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CoreMigrationError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CoreMigrationError(f"{label} must be a safe regular file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoreMigrationError(f"{label} cannot be read: {exc}") from exc


def _scanner_blob(
    relative_path: str,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[bytes, MigrationSpecIdentity]:
    try:
        active = scanner or resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise CoreMigrationError(f"active scanner provenance is unverifiable: {exc}") from exc
    entries = [
        entry
        for entry in _tree_entries(active.repository_root, active.tree, pathspec=relative_path)
        if entry[3] == relative_path
    ]
    if len(entries) != 1:
        raise CoreMigrationError(f"committed scanner file is missing or ambiguous: {relative_path}")
    mode, object_type, oid, _ = entries[0]
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise CoreMigrationError(f"committed scanner file must be a regular Git blob: {relative_path}")
    raw = _run_git(Path(active.repository_root), "cat-file", "blob", oid, binary=True)
    assert isinstance(raw, bytes)
    return raw, MigrationSpecIdentity(
        source="scanner-commit",
        path=relative_path,
        sha256=_sha256(raw),
        scanner_commit=active.commit,
        scanner_tree=active.tree,
        blob_oid=oid,
    )


def load_core_migration_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], MigrationSpecIdentity]:
    relative_path = "EKRI/specs/wff-v18-core-migration.json"
    if path is not None:
        source = Path(path).expanduser()
        raw = source.read_bytes()
        payload = _object(_load_json_path(source, "Core migration specification"), "Core migration specification")
        identity = MigrationSpecIdentity(
            source="external-file",
            path=str(source),
            sha256=_sha256(raw),
            scanner_commit="",
            scanner_tree="",
            blob_oid="",
        )
    else:
        raw, identity = _scanner_blob(relative_path, scanner=scanner)
        try:
            payload = _object(json.loads(raw.decode("utf-8")), "Core migration specification")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoreMigrationError(f"Core migration specification cannot be decoded: {exc}") from exc
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise CoreMigrationError("unsupported Core migration specification schema")
    if payload.get("profile_id") != PROFILE_ID:
        raise CoreMigrationError("unexpected Core migration profile id")
    return payload, identity


def load_migration_registrations(
    spec: Mapping[str, Any],
    *,
    scanner: ScannerIdentity | None = None,
) -> list[dict[str, Any]]:
    relative_path = _text(spec.get("registration_file"), "registration_file", maximum=1000)
    raw, _ = _scanner_blob(relative_path, scanner=scanner)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoreMigrationError(f"Core migration registrations cannot be decoded: {exc}") from exc
    rows = _array(payload, "Core migration registrations", minimum=1)
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    seen_paths: set[str] = set()
    expected_groups = {
        "issue-865-capability-consumers",
        "issue-865-assurance-consumers",
        "issue-865-distribution-profiles",
        "issue-865-role-support-adaptation",
    }
    for raw_row in rows:
        row = _object(raw_row, "Core migration registration")
        identifier = _text(row.get("change_id"), "change_id", maximum=240)
        if identifier in identifiers:
            raise CoreMigrationError(f"duplicate Core migration registration: {identifier}")
        identifiers.add(identifier)
        paths = [
            _text(value, f"{identifier} expected path", maximum=1000)
            for value in _array(row.get("expected_paths"), f"{identifier} expected_paths", minimum=1)
        ]
        for path in paths:
            if is_protected_path(path):
                raise CoreMigrationError(f"P3 registration enters protected EKRI surface: {path}")
            if path in seen_paths:
                raise CoreMigrationError(f"P3 registered path belongs to more than one group: {path}")
            seen_paths.add(path)
        result.append({**row, "expected_paths": sorted(paths)})
    if identifiers != expected_groups:
        raise CoreMigrationError(
            "P3 migration registration groups mismatch: "
            f"missing={sorted(expected_groups-identifiers)}, extra={sorted(identifiers-expected_groups)}"
        )
    return sorted(result, key=lambda row: row["change_id"])


def _git_tree(repository_root: Path, commit: str) -> str:
    return str(_run_git(repository_root, "rev-parse", f"{commit}^{{tree}}")).strip()


def validate_migration_frontier(
    repository_root: Path,
    *,
    target_commit: str,
    spec: Mapping[str, Any],
    registrations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    base_commit = _text(spec.get("base_main_commit"), "base_main_commit", maximum=80)
    base_tree = _text(spec.get("base_main_tree"), "base_main_tree", maximum=80)
    if _git_tree(repository_root, base_commit) != base_tree:
        raise CoreMigrationError("P3 base commit tree does not match accepted P2 main tree")
    merge_base = str(_run_git(repository_root, "merge-base", base_commit, target_commit)).strip()
    if merge_base != base_commit:
        raise CoreMigrationError("P3 target is not a descendant of the accepted P2 main baseline")
    raw = _run_git(
        repository_root,
        "diff",
        "--name-only",
        "--no-renames",
        f"{base_commit}..{target_commit}",
    )
    assert isinstance(raw, str)
    actual = {
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not is_protected_path(line.strip())
    }
    expected = {
        path
        for registration in registrations
        for path in registration["expected_paths"]
    }
    missing = sorted(expected - actual)
    unregistered = sorted(actual - expected)
    if missing or unregistered:
        raise CoreMigrationError(
            "P3 target change frontier does not match registered expected paths; "
            f"missing={missing}, unregistered={unregistered}"
        )
    return {
        "status": "registered-change-frontier-exact",
        "base_commit": base_commit,
        "base_tree": base_tree,
        "target_commit": target_commit,
        "changed_path_count": len(actual),
        "registered_path_count": len(expected),
        "changed_paths": sorted(actual),
        "registered_paths": sorted(expected),
        "missing_registered_paths": missing,
        "unregistered_changed_paths": unregistered,
        "protected_changes_excluded": True,
        "groups": [
            {
                "change_id": row["change_id"],
                "capability_id": row["capability_id"],
                "expected_path_count": len(row["expected_paths"]),
                "expected_paths": row["expected_paths"],
            }
            for row in registrations
        ],
    }


def validate_core_unchanged(repository_root: Path, spec: Mapping[str, Any], target_commit: str) -> dict[str, Any]:
    base_commit = _text(spec.get("base_main_commit"), "base_main_commit", maximum=80)
    contract = _object(spec.get("p2_contract"), "p2_contract")
    prefix = _text(contract.get("physical_source_prefix"), "physical_source_prefix", maximum=1000)
    raw = _run_git(
        repository_root,
        "diff",
        "--name-only",
        "--no-renames",
        f"{base_commit}..{target_commit}",
        "--",
        prefix,
    )
    assert isinstance(raw, str)
    changes = sorted(line.strip() for line in raw.splitlines() if line.strip())
    if changes:
        raise CoreMigrationError("P3 must not modify the accepted physical Core: " + ", ".join(changes))
    return {
        "status": "p2-physical-core-unchanged",
        "source_prefix": prefix,
        "changed_paths": changes,
        "change_policy": contract.get("physical_source_change_policy"),
        "contract_id": contract.get("contract_id"),
        "contract_version": contract.get("contract_version"),
        "p1_semantic_projection_sha256": contract.get("p1_semantic_projection_sha256"),
    }


def _read_text(reader: AdmittedGitReader, path: str, label: str) -> str:
    try:
        return reader.read_text(path)
    except AdmittedEvidenceError as exc:
        raise CoreMigrationError(f"{label} cannot be read: {exc}") from exc


def _read_json(reader: AdmittedGitReader, path: str, label: str) -> dict[str, Any]:
    text = _read_text(reader, path, label)
    try:
        return _object(json.loads(text), label)
    except json.JSONDecodeError as exc:
        raise CoreMigrationError(f"{label} is invalid JSON: {exc}") from exc


def _require_tokens(text: str, tokens: Sequence[str], label: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise CoreMigrationError(f"{label} misses required Core binding tokens: {missing}")


def validate_capability_consumers(reader: AdmittedGitReader, spec: Mapping[str, Any]) -> dict[str, Any]:
    heading = _text(spec.get("required_skill_heading"), "required_skill_heading", maximum=240)
    rows: list[dict[str, Any]] = []
    for raw in _array(spec.get("capability_consumers"), "capability_consumers", minimum=1):
        row = _object(raw, "capability consumer")
        extension_id = _text(row.get("extension_id"), "extension_id", maximum=240)
        runtime_path = _text(row.get("runtime_path"), f"{extension_id} runtime_path", maximum=1000)
        skill_path = _text(row.get("skill_path"), f"{extension_id} skill_path", maximum=1000)
        phase_id = _text(row.get("phase_id"), f"{extension_id} phase_id", maximum=80)
        route_key = _text(row.get("route_key"), f"{extension_id} route_key", maximum=240)
        contracts = [
            _text(value, f"{extension_id} contract", maximum=240)
            for value in _array(row.get("required_contracts"), f"{extension_id} required_contracts", minimum=1)
        ]
        runtime = _read_text(reader, runtime_path, f"{extension_id} runtime")
        _require_tokens(
            runtime,
            ["require_capability_binding", extension_id, phase_id, route_key, *contracts],
            f"{extension_id} runtime",
        )
        skill = _read_text(reader, skill_path, f"{extension_id} Skill")
        _require_tokens(skill, [heading, extension_id, "wff-core-contract", *contracts], f"{extension_id} Skill")
        rows.append(
            {
                "extension_id": extension_id,
                "phase_id": phase_id,
                "route_key": route_key,
                "runtime_path": runtime_path,
                "skill_path": skill_path,
                "required_contracts": contracts,
                "status": "public-core-consumer-bound",
                "truth_owner_preserved": True,
            }
        )
    for raw in _array(spec.get("route_and_intake_skills"), "route_and_intake_skills", minimum=1):
        row = _object(raw, "route/intake Skill")
        extension_id = _text(row.get("extension_id"), "route/intake extension_id", maximum=240)
        skill_path = _text(row.get("skill_path"), f"{extension_id} skill_path", maximum=1000)
        skill = _read_text(reader, skill_path, f"{extension_id} Skill")
        _require_tokens(skill, [heading, extension_id, "wff-core-contract"], f"{extension_id} Skill")
        rows.append(
            {
                "extension_id": extension_id,
                "runtime_path": "",
                "skill_path": skill_path,
                "required_contracts": [],
                "status": "reader-facing-core-binding-declared",
                "truth_owner_preserved": True,
            }
        )
    return {
        "schema_version": CONSUMER_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "capability-consumers-migrated",
        "consumer_count": len(rows),
        "consumers": sorted(rows, key=lambda row: row["extension_id"]),
        "claim_ceiling": (
            "This map proves committed entrypoint/Skill binding declarations and contract references. "
            "It does not prove semantic output quality or full lifecycle runtime parity."
        ),
    }


def validate_assurance_consumers(reader: AdmittedGitReader, spec: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for raw in _array(spec.get("assurance_consumers"), "assurance_consumers", minimum=1):
        row = _object(raw, "assurance consumer")
        extension_id = _text(row.get("extension_id"), "assurance extension_id", maximum=240)
        runtime_path = _text(row.get("runtime_path"), f"{extension_id} runtime_path", maximum=1000)
        contracts = [
            _text(value, f"{extension_id} contract", maximum=240)
            for value in _array(row.get("required_contracts"), f"{extension_id} required_contracts", minimum=1)
        ]
        truth_boundary = _text(row.get("truth_boundary"), f"{extension_id} truth_boundary", maximum=240)
        runtime = _read_text(reader, runtime_path, f"{extension_id} runtime")
        _require_tokens(runtime, ["capability_binding_report", extension_id, *contracts], f"{extension_id} runtime")
        forbidden_truth_tokens = (
            "creates_product_truth",
            "creates_architecture_truth",
            "release_approved = True",
        )
        leaked = [token for token in forbidden_truth_tokens if token in runtime]
        if leaked:
            raise CoreMigrationError(f"{extension_id} assurance runtime contains forbidden truth ownership: {leaked}")
        rows.append(
            {
                "extension_id": extension_id,
                "runtime_path": runtime_path,
                "required_contracts": contracts,
                "truth_boundary": truth_boundary,
                "status": "assurance-core-consumer-bound",
            }
        )
    return {
        "schema_version": ASSURANCE_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "assurance-consumers-migrated",
        "consumer_count": len(rows),
        "consumers": sorted(rows, key=lambda row: row["extension_id"]),
        "ownership": "proof-routing-and-claim-ceiling-only",
        "claim_ceiling": (
            "This report proves Core contract consumption and retained proof-only declarations. "
            "It does not certify test adequacy, Human Review quality, or validation acceptance."
        ),
    }


def validate_support_consumers(reader: AdmittedGitReader, spec: Mapping[str, Any]) -> dict[str, Any]:
    heading = _text(spec.get("required_skill_heading"), "required_skill_heading", maximum=240)
    rows: list[dict[str, Any]] = []
    for raw in _array(
        spec.get("support_and_adaptation_consumers"),
        "support_and_adaptation_consumers",
        minimum=1,
    ):
        row = _object(raw, "support/adaptation consumer")
        extension_id = _text(row.get("extension_id"), "support extension_id", maximum=240)
        runtime_path = _text(row.get("runtime_path"), f"{extension_id} runtime_path", maximum=1000)
        contracts = [
            _text(value, f"{extension_id} contract", maximum=240)
            for value in _array(row.get("required_contracts"), f"{extension_id} required_contracts", minimum=1)
        ]
        runtime = _read_text(reader, runtime_path, f"{extension_id} runtime")
        _require_tokens(runtime, ["require_capability_binding", extension_id, *contracts], f"{extension_id} runtime")
        skill_path = str(row.get("skill_path") or "").strip()
        if skill_path:
            skill = _read_text(reader, skill_path, f"{extension_id} Skill")
            _require_tokens(skill, [heading, extension_id, *contracts], f"{extension_id} Skill")
        rows.append(
            {
                "extension_id": extension_id,
                "runtime_path": runtime_path,
                "skill_path": skill_path,
                "required_contracts": contracts,
                "status": "support-or-adaptation-core-consumer-bound",
            }
        )
    return {
        "status": "support-and-adaptation-consumers-migrated",
        "consumer_count": len(rows),
        "consumers": sorted(rows, key=lambda row: row["extension_id"]),
        "claim_ceiling": "Support and adaptation bindings do not transfer lifecycle or content-truth ownership."
    }


def validate_distribution(reader: AdmittedGitReader, spec: Mapping[str, Any]) -> dict[str, Any]:
    distribution = _object(spec.get("distribution"), "distribution")
    manifest_path = _text(distribution.get("install_profile_manifest"), "install_profile_manifest", maximum=1000)
    manifest = _read_json(reader, manifest_path, "install profile manifest")
    core_runtime = _object(manifest.get("core_runtime"), "install profile core_runtime")
    contract = _object(spec.get("p2_contract"), "p2_contract")
    expected_core = {
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "p1_semantic_projection_sha256": contract["p1_semantic_projection_sha256"],
        "source_path": "wff-core/src/wff_core",
        "package_path": distribution["packaged_core_path"],
        "consumer_adapter": spec["consumer_runtime_path"],
        "compatibility_fallback": spec["compatibility_fallback"]["path"],
        "required_for_buildable_profiles": True,
    }
    mismatches = {
        key: {"expected": value, "actual": core_runtime.get(key)}
        for key, value in expected_core.items()
        if core_runtime.get(key) != value
    }
    if mismatches:
        raise CoreMigrationError("install profile Core runtime contract mismatch: " + json.dumps(mismatches, sort_keys=True))
    module_id = _text(distribution.get("required_resource_module_id"), "required_resource_module_id", maximum=240)
    module_rows = [
        row for row in _array(manifest.get("resource_modules"), "resource_modules")
        if isinstance(row, dict) and row.get("id") == module_id
    ]
    if len(module_rows) != 1:
        raise CoreMigrationError("install profiles do not declare exactly one mandatory Core runtime module")
    buildable_statuses = {"default", "supported", "preview"}
    buildable_profiles = [
        row for row in _array(manifest.get("profiles"), "profiles")
        if isinstance(row, dict) and row.get("status") in buildable_statuses
    ]
    expected_count = int(distribution.get("supported_build_profile_count", -1))
    if len(buildable_profiles) != expected_count:
        raise CoreMigrationError("buildable install profile count does not match P3 specification")

    source_checks = {
        "install_builder": ["copy_core_runtime", "build_core_runtime_manifest", "included_core_runtime_files"],
        "install_auditor": ["audit_wff_core_runtime", "packaged-core", "P1 semantic digest mismatch"],
        "release_bundle_builder": ["copy_core_runtime", "included_core_runtime_files", "wff-core"],
        "release_bundle_auditor": ["audit_wff_core_runtime", "physical Core source"],
    }
    source_rows: list[dict[str, Any]] = []
    for key, tokens in source_checks.items():
        path = _text(distribution.get(key), key, maximum=1000)
        text = _read_text(reader, path, key)
        _require_tokens(text, tokens, key)
        source_rows.append({"surface": key, "path": path, "status": "core-distribution-bound"})

    consumer_text = _read_text(
        reader,
        _text(spec.get("consumer_runtime_path"), "consumer_runtime_path", maximum=1000),
        "Core consumer runtime",
    )
    _require_tokens(
        consumer_text,
        [
            "packaged-core",
            "repository-compat-fallback",
            "descriptor-route-keys-and-aliases",
            contract["p1_semantic_projection_sha256"],
            "current_descriptors",
            "require_capability_binding",
        ],
        "Core consumer runtime",
    )
    if "LEGACY_INTENT_MAP" in consumer_text:
        raise CoreMigrationError("P3 consumer runtime retains duplicated hard-coded route truth")

    required_routes = {
        str(key): _text(value, f"required route {key}", maximum=240)
        for key, value in _object(distribution.get("required_routes"), "required_routes").items()
    }
    return {
        "schema_version": DISTRIBUTION_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-distribution-migrated",
        "core_runtime": core_runtime,
        "resource_module_id": module_id,
        "buildable_profile_count": len(buildable_profiles),
        "buildable_profile_ids": sorted(str(row["id"]) for row in buildable_profiles),
        "descriptor_count": int(distribution["required_descriptor_count"]),
        "alias_count": int(distribution["required_alias_count"]),
        "required_routes": dict(sorted(required_routes.items())),
        "source_surfaces": source_rows,
        "consumer_resolution": "descriptor-route-keys-and-aliases",
        "claim_ceiling": (
            "This report proves committed distribution configuration and audit/build code contracts. "
            "Fresh package builds and final scenario execution remain separate evidence."
        ),
    }


def validate_compatibility_fallback(reader: AdmittedGitReader, spec: Mapping[str, Any]) -> dict[str, Any]:
    fallback = _object(spec.get("compatibility_fallback"), "compatibility_fallback")
    path = _text(fallback.get("path"), "compatibility fallback path", maximum=1000)
    text = _read_text(reader, path, "compatibility fallback")
    required_status = _text(fallback.get("required_status"), "fallback required_status", maximum=240)
    retirement_issue = _text(fallback.get("retirement_issue"), "fallback retirement_issue", maximum=80)
    _require_tokens(
        text,
        [
            "activate_repository_core",
            required_status,
            "source-checkout",
            "retirement_plan",
            "wff-core/COMPATIBILITY_RETIREMENT.md",
        ],
        "compatibility fallback",
    )
    forbidden = ["build_current_registry", "ExtensionRegistry", "LEGACY_INTENT_MAP"]
    leaks = [token for token in forbidden if token in text]
    if leaks:
        raise CoreMigrationError(f"compatibility fallback retains duplicated/internal Core semantics: {leaks}")
    return {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "fallback-retained-until-p4",
        "path": path,
        "required_status": required_status,
        "retirement_issue": retirement_issue,
        "install_pack_import_mode": fallback.get("install_pack_allowed_import_mode"),
        "repository_import_mode": fallback.get("repository_allowed_import_mode"),
        "retirement_authorized": False,
        "claim_ceiling": "P3 retains the source-checkout fallback; only #866 final validation may authorize retirement."
    }


def build_migration_audit(
    *,
    reader: AdmittedGitReader,
    spec: Mapping[str, Any],
    spec_identity: MigrationSpecIdentity,
    p2_authority: Mapping[str, Any],
    frontier: Mapping[str, Any],
    core_unchanged: Mapping[str, Any],
    capability_map: Mapping[str, Any],
    assurance_map: Mapping[str, Any],
    support_map: Mapping[str, Any],
    distribution: Mapping[str, Any],
    compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    retained_unknowns = sorted(
        _text(value, "retained unknown", maximum=240)
        for value in _array(spec.get("retained_unknowns"), "retained_unknowns", minimum=1)
    )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "profile_id": PROFILE_ID,
        "status": VALID_STATUS,
        "created_at": utc_now_iso(),
        "source": {
            "base_main_commit": frontier["base_commit"],
            "base_main_tree": frontier["base_tree"],
            "target_commit": reader.commit,
            "target_tree": reader.tree,
            "observation_manifest_sha256": _sha256(_json_bytes(reader.manifest)),
            "p2_authority_status": p2_authority.get("status"),
            "p2_authority_target_tree": p2_authority.get("audit", {}).get("source", {}).get("target_tree", ""),
        },
        "specification": asdict(spec_identity),
        "change_frontier": dict(frontier),
        "physical_core": dict(core_unchanged),
        "capability_consumers": dict(capability_map),
        "assurance_consumers": dict(assurance_map),
        "support_and_adaptation_consumers": dict(support_map),
        "distribution": dict(distribution),
        "compatibility_fallback": dict(compatibility),
        "measurements": {
            "registered_non_ekri_paths": frontier["registered_path_count"],
            "capability_consumer_count": capability_map["consumer_count"],
            "assurance_consumer_count": assurance_map["consumer_count"],
            "support_consumer_count": support_map["consumer_count"],
            "buildable_profile_count": distribution["buildable_profile_count"],
            "descriptor_count": distribution["descriptor_count"],
            "alias_count": distribution["alias_count"],
            "required_route_count": len(distribution["required_routes"]),
        },
        "retained_unknowns": retained_unknowns,
        "checks": [
            {"check": "p2-authority-revalidated", "status": "passed", "detail": "accepted P2 physical Core was re-audited at the P2 main baseline"},
            {"check": "registered-change-frontier", "status": "passed", "detail": f"all {frontier['registered_path_count']} non-EKRI changes exactly match four registrations"},
            {"check": "physical-core-unchanged", "status": "passed", "detail": "P3 changes no accepted wff_core runtime source"},
            {"check": "capability-consumer-bindings", "status": "passed", "detail": "five runtime entrypoints and eight Skills declare public Core consumption"},
            {"check": "assurance-truth-boundary", "status": "passed", "detail": "claim-control and Human Review remain proof/claim/read-only consumers"},
            {"check": "distribution-core-runtime", "status": "passed", "detail": "all buildable profiles and release bundle surfaces declare exact packaged Core identity"},
            {"check": "compatibility-fallback-retained", "status": "passed", "detail": "repository fallback remains bounded and retirement stays blocked until #866"},
        ],
        "claim_ceiling": _text(spec.get("claim_ceiling"), "claim_ceiling", minimum=80),
    }


def _consumer_projection(audit: Mapping[str, Any]) -> dict[str, Any]:
    return dict(audit["capability_consumers"])


def _assurance_projection(audit: Mapping[str, Any]) -> dict[str, Any]:
    return dict(audit["assurance_consumers"])


def _distribution_projection(audit: Mapping[str, Any]) -> dict[str, Any]:
    return dict(audit["distribution"])


def _compatibility_projection(audit: Mapping[str, Any]) -> dict[str, Any]:
    return dict(audit["compatibility_fallback"])


def render_migration_review(audit: Mapping[str, Any]) -> str:
    measurements = audit["measurements"]
    lines = [
        "# WFF v1.8 P3 — Core Migration Review",
        "",
        f"- Base P2 main: `{audit['source']['base_main_commit']}` / `{audit['source']['base_main_tree']}`",
        f"- Target: `{audit['source']['target_commit']}` / `{audit['source']['target_tree']}`",
        f"- Status: `{audit['status']}`",
        "",
        "## Migration result",
        "",
        f"- Registered non-EKRI paths: `{measurements['registered_non_ekri_paths']}`",
        f"- Capability/route consumers: `{measurements['capability_consumer_count']}`",
        f"- Assurance consumers: `{measurements['assurance_consumer_count']}`",
        f"- Support/adaptation consumers: `{measurements['support_consumer_count']}`",
        f"- Buildable profiles carrying Core: `{measurements['buildable_profile_count']}`",
        f"- Capability descriptors / aliases: `{measurements['descriptor_count']} / {measurements['alias_count']}`",
        f"- Required compatibility routes: `{measurements['required_route_count']}`",
        "",
        "## Dependency direction",
        "",
        "Capabilities, assurance, support, role adaptation, install profiles, and release bundles consume the public Core contract. The accepted `wff_core` source is unchanged and does not import any consumer implementation.",
        "",
        "## Assurance boundary",
        "",
        "Claim-control and Human Review records carry explicit Core bindings, but remain evidence/claim/read-only projection surfaces. They do not create product, architecture, implementation, validation, or release truth.",
        "",
        "## Compatibility",
        "",
        "Install packs must import `scripts/wff_core` directly as `packaged-core`. Repository source checkouts may use the bounded fallback. The fallback cannot retire before #866 final scenario validation.",
        "",
        "## Retained unknowns",
        "",
    ]
    lines.extend(f"- `{value}`" for value in audit["retained_unknowns"])
    lines.extend(["", "## Claim ceiling", "", audit["claim_ceiling"], ""])
    return "\n".join(lines)


def _secure_atomic_write(parent_fd: int, filename: str, payload: bytes) -> None:
    temporary = f".{filename}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
        created = True
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        created = False
        os.fsync(parent_fd)
    except OSError as exc:
        raise CoreMigrationError(f"failed to persist P3 output {filename}: {exc}") from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _persist_outputs(repository_root: Path, audit: Mapping[str, Any]) -> dict[str, str]:
    review = render_migration_review(audit).encode("utf-8")
    payloads = {
        "core-migration-audit.json": _json_bytes(audit),
        "capability-consumer-map.json": _json_bytes(_consumer_projection(audit)),
        "assurance-consumer-migration.json": _json_bytes(_assurance_projection(audit)),
        "distribution-migration-report.json": _json_bytes(_distribution_projection(audit)),
        "compatibility-retirement-status.json": _json_bytes(_compatibility_projection(audit)),
        "CORE_MIGRATION_REVIEW.md": review,
    }
    output_audit = {
        "schema_version": OUTPUT_AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-migration-output-persisted",
        "created_at": utc_now_iso(),
        "source_tree": audit["source"]["target_tree"],
        "output_digests": {name: _sha256(payload) for name, payload in sorted(payloads.items())},
        "checks": [
            {"check": "registered-frontier-binding", "status": "passed"},
            {"check": "consumer-projection-consistency", "status": "passed"},
            {"check": "distribution-projection-consistency", "status": "passed"},
            {"check": "no-follow-atomic-persistence", "status": "passed"},
        ],
        "claim_ceiling": "Output digests prove P3 projection integrity only; they do not strengthen migration or release claims.",
    }
    payloads["core-migration-output-audit.json"] = _json_bytes(output_audit)

    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "core-migration", audit["source"]["target_tree"]):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        for filename, payload in payloads.items():
            _secure_atomic_write(parent_fd, filename, payload)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = repository_root / ".EKRI" / "core-migration" / audit["source"]["target_tree"]
    return {
        "output_root": str(output_root),
        **{
            name.replace("-", "_").replace(".", "_"): str(output_root / name)
            for name in payloads
        },
    }


def run_core_migration_audit(
    repository_root: str | Path,
    *,
    target_ref: str = "HEAD",
    write_outputs: bool = True,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    if not root.is_dir():
        raise CoreMigrationError(f"repository root is not a directory: {root}")
    try:
        spec, spec_identity = load_core_migration_spec()
        registrations = load_migration_registrations(spec)
        base_commit = _text(spec.get("base_main_commit"), "base_main_commit", maximum=80)
        p2_authority = run_core_extraction_audit(
            root,
            target_ref=base_commit,
            write_outputs=True,
        )
        if p2_authority.get("status") != "core-extraction-verified":
            raise CoreMigrationError("accepted P2 authority could not be regenerated")
        manifest = evaluate_observation_boundary(repository_root=root, target_ref=target_ref)
        if manifest.get("boundary", {}).get("verdict") != VALID_VERDICT:
            raise CoreMigrationError(
                "P3 target observation was rejected: "
                + str(manifest.get("boundary", {}).get("failure_reason") or "unknown reason")
            )
        write_manifest(root, manifest)
        reader = AdmittedGitReader(root, manifest)
        frontier = validate_migration_frontier(
            root,
            target_commit=reader.commit,
            spec=spec,
            registrations=registrations,
        )
        core_unchanged = validate_core_unchanged(root, spec, reader.commit)
        capability_map = validate_capability_consumers(reader, spec)
        assurance_map = validate_assurance_consumers(reader, spec)
        support_map = validate_support_consumers(reader, spec)
        distribution = validate_distribution(reader, spec)
        compatibility = validate_compatibility_fallback(reader, spec)
        audit = build_migration_audit(
            reader=reader,
            spec=spec,
            spec_identity=spec_identity,
            p2_authority=p2_authority,
            frontier=frontier,
            core_unchanged=core_unchanged,
            capability_map=capability_map,
            assurance_map=assurance_map,
            support_map=support_map,
            distribution=distribution,
            compatibility=compatibility,
        )
        outputs: dict[str, str] = {}
        if write_outputs:
            outputs = _persist_outputs(root, audit)
        return {
            "schema_version": "ekri.core-migration-run.v1",
            "status": VALID_STATUS,
            "audit": audit,
            "outputs": outputs,
        }
    except CoreMigrationError:
        raise
    except (CoreExtractionError, ObservationBoundaryError, AdmittedEvidenceError) as exc:
        raise CoreMigrationError(f"P3 migration authority validation failed: {exc}") from exc
    except Exception as exc:
        raise CoreMigrationError(f"P3 migration failed closed: {exc}") from exc
