"""WFF v1.8 P1 versioned Minimal Core Contract definition.

P1 consumes the accepted P0 Core Candidate Map, verifies its persisted audit
and digest bindings, then projects a versioned semantic contract.  It does not
create a physical Core package, move WFF runtime files, or introduce a generic
plugin framework.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable
import uuid

from .core_boundary_reconstruction import (
    AUDIT_SCHEMA_VERSION as P0_AUDIT_SCHEMA_VERSION,
    MAP_SCHEMA_VERSION as P0_MAP_SCHEMA_VERSION,
    CoreBoundaryError,
    run_core_boundary_reconstruction,
)
from .knowledge_reconstruction import _safe_read_runtime_file
from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    resolve_scanner_identity,
)


SPEC_SCHEMA_VERSION = "ekri.wff-core-contract-spec.v1"
CONTRACT_SCHEMA_VERSION = "wff.core-contract.v1"
PUBLIC_API_SCHEMA_VERSION = "wff.core-public-api.v1"
INTERNAL_API_SCHEMA_VERSION = "wff.core-internal-api.v1"
EXTENSION_SCHEMA_VERSION = "wff.core-extension-interface.v1"
COMPATIBILITY_SCHEMA_VERSION = "wff.core-compatibility-matrix.v1"
DECISION_SCHEMA_VERSION = "wff.core-migration-decisions.v1"
CONFORMANCE_SCHEMA_VERSION = "wff.core-contract-conformance.v1"
AUDIT_SCHEMA_VERSION = "ekri.core-contract-audit.v1"
PHASE_ID = "v1.8-p1-minimal-core-contract"
PROFILE_ID = "wff-v1.8-p1-minimal-core-contract"
VALID_STATUS = "minimal-core-contract-defined"

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
ALLOWED_POSTURES = {
    "split-contract-and-implementation",
    "extension-consumer",
    "assurance-consumer",
    "distribution-adapter",
}
FORBIDDEN_EXECUTABLE_KEYS = {
    "implementation_path",
    "module_path",
    "module",
    "loader",
    "load_hook",
    "entrypoint",
    "executable",
    "command",
    "callback",
}
REQUIRED_EXTENSION_DESCRIPTOR_FIELDS = {
    "extension_id",
    "extension_kind",
    "core_contract_range",
    "route_keys",
    "phase_ids",
    "consumes_contracts",
    "produces_contracts",
    "truth_owner",
    "compatibility_aliases",
    "failure_policy",
}
REQUIRED_FORBIDDEN_DEPENDENCIES = {
    "skills/**",
    "scripts/phase1/**",
    "scripts/phase2/**",
    "scripts/phase3/**",
    "scripts/phase4/**",
    "scripts/phasex/**",
    "scripts/release/**",
    "tests/**",
    "release-cases/**",
    "EKRI/**",
    ".EKRI/**",
}


class MinimalCoreContractError(RuntimeError):
    """Raised when P1 cannot establish a trustworthy Core contract."""


@dataclass(frozen=True)
class CoreContractSpecIdentity:
    source: str
    path: str
    sha256: str
    scanner_commit: str
    scanner_tree: str
    blob_oid: str


@dataclass(frozen=True)
class VerifiedP0Authority:
    target_tree: str
    core_map: dict[str, Any]
    equivalence: dict[str, Any]
    audit: dict[str, Any]
    core_map_sha256: str
    equivalence_sha256: str
    audit_sha256: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MinimalCoreContractError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise MinimalCoreContractError(
            f"{label} must be a list with at least {minimum} item(s)"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    minimum: int = 1,
    maximum: int = 8000,
) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise MinimalCoreContractError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _identifier(value: object, label: str) -> str:
    identifier = _text(value, label, maximum=160)
    if IDENTIFIER_RE.fullmatch(identifier) is None:
        raise MinimalCoreContractError(f"{label} is not a valid identifier: {identifier}")
    return identifier


def _read_json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MinimalCoreContractError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise MinimalCoreContractError(f"{label} must be a safe regular file")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MinimalCoreContractError(f"{label} cannot be read: {exc}") from exc
    return _object(payload, label), raw


def load_core_contract_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], CoreContractSpecIdentity]:
    """Load the reviewed P1 specification from a safe file or scanner commit."""
    if path is not None:
        source = Path(path).expanduser()
        payload, raw = _read_json_file(source, "Core contract specification")
        identity = CoreContractSpecIdentity(
            source="external-file",
            path=str(source),
            sha256=_sha256(raw),
            scanner_commit="",
            scanner_tree="",
            blob_oid="",
        )
    else:
        try:
            active = scanner or resolve_scanner_identity()
        except ObservationBoundaryError as exc:
            raise MinimalCoreContractError(
                f"active scanner provenance is unverifiable: {exc}"
            ) from exc
        relative_path = "EKRI/specs/wff-v18-minimal-core-contract.json"
        entries = [
            entry
            for entry in _tree_entries(
                Path(active.repository_root),
                active.tree,
                pathspec=relative_path,
            )
            if entry[3] == relative_path
        ]
        if len(entries) != 1:
            raise MinimalCoreContractError(
                "committed Minimal Core Contract specification is missing or ambiguous"
            )
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise MinimalCoreContractError(
                "committed Minimal Core Contract specification must be a regular Git blob"
            )
        raw = _run_git(
            Path(active.repository_root),
            "cat-file",
            "blob",
            oid,
            binary=True,
        )
        assert isinstance(raw, bytes)
        try:
            payload = _object(
                json.loads(raw.decode("utf-8")),
                "Core contract specification",
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MinimalCoreContractError(
                f"committed Minimal Core Contract specification cannot be read: {exc}"
            ) from exc
        identity = CoreContractSpecIdentity(
            source="scanner-commit",
            path=relative_path,
            sha256=_sha256(raw),
            scanner_commit=active.commit,
            scanner_tree=active.tree,
            blob_oid=oid,
        )
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise MinimalCoreContractError("unsupported Core contract specification schema")
    if payload.get("profile_id") != PROFILE_ID:
        raise MinimalCoreContractError("unexpected Core contract profile id")
    return payload, identity


def _decode_runtime_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(raw.decode("utf-8")), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MinimalCoreContractError(f"{label} is not valid UTF-8 JSON: {exc}") from exc


def verify_p0_authority(
    repository_root: str | Path,
    spec: dict[str, Any],
) -> VerifiedP0Authority:
    """Revalidate persisted P0 outputs and bind them to the P1 specification."""
    root = _absolute_path(repository_root)
    authority = _object(spec.get("p0_authority"), "spec p0_authority")
    target_tree = _text(authority.get("target_tree"), "P0 target tree", maximum=80)
    components = (".EKRI", "core-boundary", target_tree)
    try:
        map_raw = _safe_read_runtime_file(root, components, "core-candidate-map.json")
        equivalence_raw = _safe_read_runtime_file(root, components, "baseline-equivalence.json")
        audit_raw = _safe_read_runtime_file(root, components, "core-boundary-audit.json")
    except Exception as exc:
        raise MinimalCoreContractError(f"P0 authority cannot be read safely: {exc}") from exc

    core_map = _decode_runtime_json(map_raw, "P0 core-candidate-map.json")
    equivalence = _decode_runtime_json(equivalence_raw, "P0 baseline-equivalence.json")
    audit = _decode_runtime_json(audit_raw, "P0 core-boundary-audit.json")
    if core_map.get("schema_version") != authority.get("map_schema_version"):
        raise MinimalCoreContractError("P0 Core Candidate Map schema does not match P1 authority")
    if audit.get("schema_version") != authority.get("audit_schema_version"):
        raise MinimalCoreContractError("P0 audit schema does not match P1 authority")
    if audit.get("schema_version") != P0_AUDIT_SCHEMA_VERSION:
        raise MinimalCoreContractError("unsupported P0 audit schema")
    if core_map.get("schema_version") != P0_MAP_SCHEMA_VERSION:
        raise MinimalCoreContractError("unsupported P0 Core Candidate Map schema")
    if core_map.get("status") != "core-boundary-reconstructed":
        raise MinimalCoreContractError("P0 Core Candidate Map is not accepted")
    if audit.get("status") != "core-boundary-output-persisted":
        raise MinimalCoreContractError("P0 output audit is not accepted")
    if audit.get("source_tree") != target_tree:
        raise MinimalCoreContractError("P0 audit target tree does not match P1 authority")
    source = _object(core_map.get("source"), "P0 Core Candidate Map source")
    if source.get("target_tree") != target_tree:
        raise MinimalCoreContractError("P0 Core Candidate Map target tree does not match P1 authority")

    digests = _object(audit.get("output_digests"), "P0 audit output_digests")
    core_map_sha = _sha256(map_raw)
    equivalence_sha = _sha256(equivalence_raw)
    if digests.get("core-candidate-map.json") != core_map_sha:
        raise MinimalCoreContractError("P0 Core Candidate Map digest does not match its audit")
    if digests.get("baseline-equivalence.json") != equivalence_sha:
        raise MinimalCoreContractError("P0 equivalence digest does not match its audit")
    if source.get("equivalence_sha256") != equivalence_sha:
        raise MinimalCoreContractError("P0 Core Candidate Map is not digest-bound to equivalence")
    if equivalence.get("status") != "mainline-runtime-equivalence-verified":
        raise MinimalCoreContractError("P0 mainline equivalence is not verified")

    counts = _object(core_map.get("counts"), "P0 counts")
    for key, expected in _object(authority.get("required_counts"), "P0 required_counts").items():
        if counts.get(key) != expected:
            raise MinimalCoreContractError(
                f"P0 count mismatch for {key}: expected {expected}, received {counts.get(key)}"
            )
    p0_contract_ids = {
        _identifier(row.get("id"), "P0 candidate contract id")
        for row in _array(core_map.get("candidate_core_contracts"), "P0 candidate contracts")
        if isinstance(row, dict)
    }
    expected_contract_ids = {
        _identifier(value, "required P0 contract id")
        for value in _array(authority.get("required_candidate_contract_ids"), "required P0 contract ids")
    }
    if p0_contract_ids != expected_contract_ids:
        raise MinimalCoreContractError("P0 candidate contract identity set changed")
    capability_rows = _object(core_map.get("classifications"), "P0 classifications").get("capabilities")
    p0_capability_ids = {
        _identifier(row.get("id"), "P0 capability id")
        for row in _array(capability_rows, "P0 capabilities")
        if isinstance(row, dict)
    }
    expected_capability_ids = {
        _identifier(value, "required P0 capability id")
        for value in _array(authority.get("required_capability_ids"), "required P0 capability ids")
    }
    if p0_capability_ids != expected_capability_ids:
        raise MinimalCoreContractError("P0 capability identity set changed")

    return VerifiedP0Authority(
        target_tree=target_tree,
        core_map=core_map,
        equivalence=equivalence,
        audit=audit,
        core_map_sha256=core_map_sha,
        equivalence_sha256=equivalence_sha,
        audit_sha256=_sha256(audit_raw),
    )


def _index_rows(rows: object, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _array(rows, label, minimum=1):
        row = _object(raw, f"{label} entry")
        identifier = _identifier(row.get("id"), f"{label} id")
        if identifier in result:
            raise MinimalCoreContractError(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result


def _text_list(value: object, label: str, *, minimum: int = 0) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_array(value, label, minimum=minimum), start=1):
        text = _text(raw, f"{label}[{index}]", maximum=1000)
        if text in result:
            raise MinimalCoreContractError(f"duplicate {label} value: {text}")
        result.append(text)
    return result


def _require_refs(values: object, allowed: set[str], label: str, *, minimum: int = 1) -> list[str]:
    refs = _text_list(values, label, minimum=minimum)
    unknown = sorted(set(refs) - allowed)
    if unknown:
        raise MinimalCoreContractError(f"{label} references unknown ids: " + ", ".join(unknown))
    return refs


def _contains_forbidden_executable_key(value: object) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_EXECUTABLE_KEYS:
                return str(key)
            nested = _contains_forbidden_executable_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _contains_forbidden_executable_key(item)
            if nested:
                return nested
    return ""


def _validate_spec_semantics(
    spec: dict[str, Any],
    authority: VerifiedP0Authority,
) -> dict[str, Any]:
    contract_version = _text(spec.get("contract_version"), "contract version", maximum=40)
    if SEMVER_RE.fullmatch(contract_version) is None:
        raise MinimalCoreContractError("contract_version must be strict semantic versioning")
    contract_id = _identifier(spec.get("contract_id"), "contract id")
    status = _text(spec.get("status"), "contract status", maximum=80)
    if status != "review-candidate":
        raise MinimalCoreContractError("P1 specification must be a review-candidate")

    p0_contracts = _index_rows(
        authority.core_map.get("candidate_core_contracts"),
        "P0 candidate contracts",
    )
    contracts = _index_rows(spec.get("contracts"), "Core contracts")
    if set(contracts) != set(p0_contracts):
        raise MinimalCoreContractError("P1 contracts must cover every and only P0 candidate contract")
    public_types = _index_rows(spec.get("public_types"), "public types")
    operations = _index_rows(spec.get("public_operations"), "public operations")
    invariants = _index_rows(spec.get("invariants"), "Core invariants")

    used_types: set[str] = set()
    used_operations: set[str] = set()
    used_invariants: set[str] = set()
    for contract_id_value, row in contracts.items():
        if _identifier(row.get("id"), "contract id") != contract_id_value:
            raise MinimalCoreContractError("contract identity changed during indexing")
        type_ids = _require_refs(
            row.get("public_type_ids"),
            set(public_types),
            f"contract {contract_id_value} public_type_ids",
        )
        operation_ids = _require_refs(
            row.get("operation_ids"),
            set(operations),
            f"contract {contract_id_value} operation_ids",
        )
        invariant_ids = _require_refs(
            row.get("invariant_ids"),
            set(invariants),
            f"contract {contract_id_value} invariant_ids",
        )
        p0_refs = set(_text_list(p0_contracts[contract_id_value].get("evidence_refs"), "P0 evidence refs", minimum=1))
        _require_refs(
            row.get("p0_evidence_refs"),
            p0_refs,
            f"contract {contract_id_value} p0_evidence_refs",
        )
        _text_list(row.get("non_responsibilities"), f"contract {contract_id_value} non_responsibilities", minimum=1)
        used_types.update(type_ids)
        used_operations.update(operation_ids)
        used_invariants.update(invariant_ids)

    for type_id, row in public_types.items():
        contract_ref = _identifier(row.get("contract_id"), f"public type {type_id} contract_id")
        if contract_ref not in contracts:
            raise MinimalCoreContractError(f"public type {type_id} references unknown contract")
        if row.get("stability") != "public":
            raise MinimalCoreContractError(f"public type {type_id} must have public stability")
        semantic = _text(
            row.get("semantic"),
            f"public type {type_id} semantic",
            minimum=24,
            maximum=1200,
        )
        if semantic == "Versioned contract field.":
            raise MinimalCoreContractError(f"public type {type_id} semantic is a placeholder")
        fields = _array(row.get("fields"), f"public type {type_id} fields", minimum=1)
        names: set[str] = set()
        for raw_field in fields:
            field = _object(raw_field, f"public type {type_id} field")
            name = _identifier(field.get("name"), f"public type {type_id} field name")
            if name in names:
                raise MinimalCoreContractError(f"duplicate field in {type_id}: {name}")
            names.add(name)
            if not isinstance(field.get("required"), bool):
                raise MinimalCoreContractError(f"public type {type_id} field {name} requires boolean required")
            kind = _text(field.get("kind"), f"public type {type_id} field {name} kind", maximum=80)
            field_semantic = _text(
                field.get("semantic"),
                f"public type {type_id} field {name} semantic",
                minimum=24,
                maximum=1200,
            )
            if field_semantic == "Versioned contract field.":
                raise MinimalCoreContractError(
                    f"public type {type_id} field {name} semantic is a placeholder"
                )
            if kind == "enum":
                _text_list(field.get("allowed"), f"public type {type_id} field {name} allowed", minimum=1)

    for operation_id, row in operations.items():
        contract_ref = _identifier(row.get("contract_id"), f"operation {operation_id} contract_id")
        if contract_ref not in contracts:
            raise MinimalCoreContractError(f"operation {operation_id} references unknown contract")
        _require_refs(row.get("input_type_ids"), set(public_types), f"operation {operation_id} input types")
        _require_refs(row.get("output_type_ids"), set(public_types), f"operation {operation_id} output types")
        _text_list(row.get("failure_outcomes"), f"operation {operation_id} failure outcomes", minimum=1)
        _text(row.get("semantic_owner"), f"operation {operation_id} semantic owner", minimum=3)
        _text(row.get("semantic_effect"), f"operation {operation_id} semantic effect", minimum=12)

    if used_types != set(public_types):
        raise MinimalCoreContractError("every public type must be assigned to a Core contract")
    if used_operations != set(operations):
        raise MinimalCoreContractError("every public operation must be assigned to a Core contract")
    if used_invariants != set(invariants):
        missing = sorted(set(invariants) - used_invariants)
        raise MinimalCoreContractError("unreferenced Core invariants: " + ", ".join(missing))

    public_api = _object(spec.get("public_api"), "public_api")
    if set(_text_list(public_api.get("type_ids"), "public_api type_ids")) != set(public_types):
        raise MinimalCoreContractError("public_api type_ids do not match public type registry")
    if set(_text_list(public_api.get("operation_ids"), "public_api operation_ids")) != set(operations):
        raise MinimalCoreContractError("public_api operation_ids do not match operation registry")
    forbidden_dependencies = set(
        _text_list(public_api.get("forbidden_dependencies"), "public_api forbidden_dependencies")
    )
    if not REQUIRED_FORBIDDEN_DEPENDENCIES <= forbidden_dependencies:
        missing = sorted(REQUIRED_FORBIDDEN_DEPENDENCIES - forbidden_dependencies)
        raise MinimalCoreContractError("public_api misses forbidden dependencies: " + ", ".join(missing))

    internal_api = _object(spec.get("internal_api"), "internal_api")
    internal_surfaces = _index_rows(internal_api.get("surfaces"), "internal API surfaces")
    if set(internal_surfaces) & (set(public_types) | set(operations)):
        raise MinimalCoreContractError("internal API identities overlap public API identities")
    _text_list(internal_api.get("non_guarantees"), "internal API non_guarantees", minimum=1)

    extension = _object(spec.get("extension_interface"), "extension_interface")
    descriptor_type = _identifier(extension.get("descriptor_type_id"), "extension descriptor type")
    operation_ref = _identifier(extension.get("registration_operation_id"), "extension registration operation")
    if descriptor_type not in public_types or operation_ref not in operations:
        raise MinimalCoreContractError("extension interface references unknown public surface")
    descriptor_fields = {
        _identifier(field.get("name"), "extension descriptor field name")
        for field in _array(
            public_types[descriptor_type].get("fields"),
            "extension descriptor fields",
            minimum=1,
        )
        if isinstance(field, dict)
    }
    if not REQUIRED_EXTENSION_DESCRIPTOR_FIELDS <= descriptor_fields:
        missing = sorted(REQUIRED_EXTENSION_DESCRIPTOR_FIELDS - descriptor_fields)
        raise MinimalCoreContractError(
            "extension descriptor misses required declarative fields: " + ", ".join(missing)
        )
    forbidden_key = _contains_forbidden_executable_key(extension)
    if forbidden_key:
        raise MinimalCoreContractError(
            f"extension interface contains forbidden executable-loading field: {forbidden_key}"
        )
    prohibited_features = " ".join(
        _text_list(extension.get("prohibited_features"), "extension prohibited_features", minimum=3)
    ).casefold()
    for required_phrase in ("executable", "dynamic", "plugin", "installation"):
        if required_phrase not in prohibited_features:
            raise MinimalCoreContractError(
                f"extension interface must explicitly prohibit {required_phrase} behavior"
            )

    p0_capability_rows = _index_rows(
        _object(authority.core_map.get("classifications"), "P0 classifications").get("capabilities"),
        "P0 capabilities",
    )
    compatibility_rows: dict[str, dict[str, Any]] = {}
    for raw in _array(spec.get("capability_compatibility"), "capability compatibility", minimum=1):
        row = _object(raw, "capability compatibility entry")
        capability_id = _identifier(row.get("capability_id"), "compatibility capability_id")
        if capability_id in compatibility_rows:
            raise MinimalCoreContractError(f"duplicate compatibility capability: {capability_id}")
        compatibility_rows[capability_id] = row
    if set(compatibility_rows) != set(p0_capability_rows):
        raise MinimalCoreContractError("compatibility matrix must cover every P0 capability exactly once")
    for capability_id, row in compatibility_rows.items():
        posture = _text(row.get("posture"), f"compatibility {capability_id} posture", maximum=80)
        if posture not in ALLOWED_POSTURES:
            raise MinimalCoreContractError(f"unsupported compatibility posture: {posture}")
        p0_row = p0_capability_rows[capability_id]
        layer = p0_row.get("primary_layer")
        boundary = p0_row.get("boundary_state")
        if layer == "distribution-adaptation" and posture != "distribution-adapter":
            raise MinimalCoreContractError(f"distribution capability {capability_id} has wrong posture")
        if layer == "assurance" and posture != "assurance-consumer":
            raise MinimalCoreContractError(f"assurance capability {capability_id} has wrong posture")
        if boundary == "non-core" and layer == "capability-extension" and posture != "extension-consumer":
            raise MinimalCoreContractError(f"non-Core capability {capability_id} has wrong posture")
        if boundary == "split-required" and layer != "assurance" and posture != "split-contract-and-implementation":
            raise MinimalCoreContractError(f"split-required capability {capability_id} has wrong posture")
        consumed = _require_refs(
            row.get("consumes_contract_ids"),
            set(contracts),
            f"compatibility {capability_id} consumes_contract_ids",
        )
        if not consumed:
            raise MinimalCoreContractError(f"compatibility {capability_id} consumes no Core contract")
        _text_list(
            row.get("current_compatibility_surfaces"),
            f"compatibility {capability_id} current surfaces",
            minimum=1,
        )
        _text(row.get("migration_action"), f"compatibility {capability_id} migration_action", minimum=20)
        _text(row.get("compatibility_commitment"), f"compatibility {capability_id} commitment", minimum=20)
        forbidden = _text(row.get("forbidden_dependency"), f"compatibility {capability_id} forbidden dependency", minimum=20)
        if "Core" not in forbidden or "import" not in forbidden:
            raise MinimalCoreContractError(f"compatibility {capability_id} must prohibit Core imports")

    decisions = _index_rows(spec.get("migration_decisions"), "migration decisions")
    p0_unknown_ids = {
        _identifier(row.get("id"), "P0 unknown id")
        for row in _array(authority.core_map.get("unknowns"), "P0 unknowns")
        if isinstance(row, dict)
    }
    p0_dispute_ids = {
        _identifier(row.get("id"), "P0 disputed boundary id")
        for row in _array(authority.core_map.get("disputed_boundaries"), "P0 disputes")
        if isinstance(row, dict)
    }
    resolved: set[str] = set()
    retained_unknowns: set[str] = set()
    for decision_id, row in decisions.items():
        _text(row.get("decision"), f"decision {decision_id} decision", minimum=20)
        _text_list(row.get("consequences"), f"decision {decision_id} consequences", minimum=1)
        resolved.update(_text_list(row.get("resolves", []), f"decision {decision_id} resolves"))
        retained_unknowns.update(
            _text_list(row.get("retains_unknowns", []), f"decision {decision_id} retains_unknowns")
        )
    unknown_coverage = (resolved & p0_unknown_ids) | retained_unknowns
    if unknown_coverage != p0_unknown_ids:
        missing = sorted(p0_unknown_ids - unknown_coverage)
        extra = sorted(unknown_coverage - p0_unknown_ids)
        raise MinimalCoreContractError(
            f"P0 unknown coverage mismatch; missing={missing}, extra={extra}"
        )
    if not p0_dispute_ids <= resolved:
        missing = sorted(p0_dispute_ids - resolved)
        raise MinimalCoreContractError("unresolved P0 disputed boundaries: " + ", ".join(missing))

    conformance = _index_rows(spec.get("conformance_rules"), "conformance rules")
    if len(conformance) < 8:
        raise MinimalCoreContractError("P1 requires at least eight explicit conformance rules")
    versioning = _object(spec.get("versioning_policy"), "versioning_policy")
    if versioning.get("scheme") != "semantic-versioning":
        raise MinimalCoreContractError("Core contract versioning must use semantic versioning")
    _text(versioning.get("v18_compatibility_rule"), "v1.8 compatibility rule", minimum=40)

    return {
        "contract_id": contract_id,
        "contract_version": contract_version,
        "status": status,
        "contracts": contracts,
        "public_types": public_types,
        "operations": operations,
        "invariants": invariants,
        "public_api": public_api,
        "internal_api": internal_api,
        "extension_interface": extension,
        "compatibility_rows": compatibility_rows,
        "decisions": decisions,
        "conformance": conformance,
        "versioning": versioning,
        "retained_unknowns": sorted(retained_unknowns),
        "resolved_p0_items": sorted(resolved),
    }


def build_minimal_core_contract(
    authority: VerifiedP0Authority,
    spec: dict[str, Any],
    *,
    spec_identity: CoreContractSpecIdentity | None = None,
) -> dict[str, Any]:
    """Build the complete P1 contract projection from verified P0 authority."""
    if not isinstance(authority, VerifiedP0Authority):
        raise MinimalCoreContractError("P1 requires a VerifiedP0Authority")
    validated = _validate_spec_semantics(spec, authority)
    created_at = utc_now_iso()
    identity_payload = asdict(spec_identity) if spec_identity else {
        "source": "provided-object",
        "path": "",
        "sha256": _sha256(_json_bytes(spec)),
        "scanner_commit": "",
        "scanner_tree": "",
        "blob_oid": "",
    }
    contract_rows = [copy.deepcopy(validated["contracts"][key]) for key in sorted(validated["contracts"])]
    type_rows = [copy.deepcopy(validated["public_types"][key]) for key in sorted(validated["public_types"])]
    operation_rows = [copy.deepcopy(validated["operations"][key]) for key in sorted(validated["operations"])]
    invariant_rows = [copy.deepcopy(validated["invariants"][key]) for key in sorted(validated["invariants"])]
    compatibility_rows = [
        copy.deepcopy(validated["compatibility_rows"][key])
        for key in sorted(validated["compatibility_rows"])
    ]
    decision_rows = [copy.deepcopy(validated["decisions"][key]) for key in sorted(validated["decisions"])]
    conformance_rows = [copy.deepcopy(validated["conformance"][key]) for key in sorted(validated["conformance"])]
    result = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "profile_id": PROFILE_ID,
        "status": VALID_STATUS,
        "created_at": created_at,
        "contract_id": validated["contract_id"],
        "contract_version": validated["contract_version"],
        "source": {
            "p0_target_tree": authority.target_tree,
            "p0_core_map_sha256": authority.core_map_sha256,
            "p0_equivalence_sha256": authority.equivalence_sha256,
            "p0_audit_sha256": authority.audit_sha256,
            "p0_equivalence_verdict": authority.equivalence.get("verdict"),
        },
        "specification": identity_payload,
        "versioning_policy": copy.deepcopy(validated["versioning"]),
        "contracts": contract_rows,
        "public_types": type_rows,
        "public_operations": operation_rows,
        "invariants": invariant_rows,
        "public_api": copy.deepcopy(validated["public_api"]),
        "internal_api": copy.deepcopy(validated["internal_api"]),
        "extension_interface": copy.deepcopy(validated["extension_interface"]),
        "capability_compatibility": compatibility_rows,
        "migration_decisions": decision_rows,
        "retained_p0_unknowns": validated["retained_unknowns"],
        "resolved_p0_items": validated["resolved_p0_items"],
        "conformance_rules": conformance_rows,
        "counts": {
            "contracts": len(contract_rows),
            "public_types": len(type_rows),
            "public_operations": len(operation_rows),
            "invariants": len(invariant_rows),
            "internal_surfaces": len(validated["internal_api"]["surfaces"]),
            "capability_compatibility": len(compatibility_rows),
            "migration_decisions": len(decision_rows),
            "conformance_rules": len(conformance_rows),
            "retained_p0_unknowns": len(validated["retained_unknowns"]),
        },
        "checks": [
            {"check": "p0-authority-revalidated", "status": "passed", "detail": "P0 Core Candidate Map and equivalence digests match the persisted P0 audit"},
            {"check": "candidate-contract-coverage", "status": "passed", "detail": "all nine P0 candidate Core contracts have one versioned P1 definition"},
            {"check": "minimal-contract-surface", "status": "passed", "detail": "nine Core contracts are smaller than both the twenty-node P0 architecture projection and the sixteen-capability implementation surface"},
            {"check": "public-reference-closure", "status": "passed", "detail": "all public operations, types, contracts, and invariants form a closed reference set"},
            {"check": "extension-inversion", "status": "passed", "detail": "extension registration is declarative and Core-outward implementation imports are forbidden"},
            {"check": "capability-compatibility-coverage", "status": "passed", "detail": "all sixteen current capabilities have one explicit migration/compatibility posture"},
            {"check": "p0-unknown-dispute-disposition", "status": "passed", "detail": "every P0 unknown is resolved or explicitly retained and every disputed boundary has a P1 decision"},
            {"check": "semantic-authority-boundary", "status": "passed", "detail": "conformance remains structural/dependency-focused and cannot create product, architecture, implementation, or release truth"},
        ],
        "claim_ceiling": _text(spec.get("claim_ceiling"), "spec claim ceiling", minimum=80),
    }
    return result


def _public_api_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PUBLIC_API_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "public-core-api-defined",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "public_api": contract["public_api"],
        "types": contract["public_types"],
        "operations": contract["public_operations"],
        "invariants": contract["invariants"],
        "claim_ceiling": "This is a stable semantic API for WFF components, not a network API, executable plugin SDK, or proof that a physical Core package already exists.",
    }


def _internal_api_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": INTERNAL_API_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "internal-core-api-bounded",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "internal_api": contract["internal_api"],
        "claim_ceiling": "Internal surfaces are implementation guidance for P2 and may change without becoming extension dependencies or semantic authority.",
    }


def _extension_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": EXTENSION_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "declarative-extension-interface-defined",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "extension_interface": contract["extension_interface"],
        "descriptor_type": next(
            row for row in contract["public_types"]
            if row["id"] == contract["extension_interface"]["descriptor_type_id"]
        ),
        "registration_operation": next(
            row for row in contract["public_operations"]
            if row["id"] == contract["extension_interface"]["registration_operation_id"]
        ),
        "claim_ceiling": "This interface defines only the metadata needed by current WFF routes/capabilities. It is not a generic plugin framework, loader, installer, marketplace, or runtime invocation protocol.",
    }


def _compatibility_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "current-capability-compatibility-defined",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "versioning_policy": contract["versioning_policy"],
        "capability_count": len(contract["capability_compatibility"]),
        "capabilities": contract["capability_compatibility"],
        "claim_ceiling": "Compatibility postures are migration obligations. They do not prove parity until P2-P4 extraction, package audits, and the mandatory final multi-scenario validation pass.",
    }


def _decision_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-migration-decisions-recorded",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "decision_count": len(contract["migration_decisions"]),
        "decisions": contract["migration_decisions"],
        "retained_p0_unknowns": contract["retained_p0_unknowns"],
        "claim_ceiling": "These decisions constrain P2 extraction but do not select a physical package or authorize runtime migration before independent review.",
    }


def _conformance_projection(contract: dict[str, Any]) -> dict[str, Any]:
    verification_by_id = {
        "C-001": "The verified P0 contract-id set equals the nine versioned P1 contract ids.",
        "C-002": "Contract build validated closed references among public operations, public types, contracts, and invariants.",
        "C-003": "The verified P0 capability-id set equals the sixteen compatibility rows and each row consumes at least one contract.",
        "C-004": "The public API declares the complete required forbidden-dependency pattern set; physical import/resource conformance is explicitly deferred.",
        "C-005": "The descriptor contains every required declarative field and no executable-loading key; prohibited features explicitly cover executable, dynamic, plugin, and installation behavior.",
        "C-006": "Evidence and claim contracts reference the ownership and weakest-evidence invariants; this verifies declared boundaries, not output truth.",
        "C-007": "Artifact contracts reference document-authority, storage-neutrality, and derived-index invariants.",
        "C-008": "All sixteen capability rows carry a v1.8 compatibility commitment and the versioning policy preserves current public surfaces.",
        "C-009": "Migration decisions retain physical Core home and exhaustive dynamic closure as unresolved P2/P4 obligations and authorize no move.",
        "C-010": "Every conformance result is capped to structural-reference-and-dependency-contract-only.",
    }
    results = [
        {
            **copy.deepcopy(row),
            "status": "passed",
            "verification": verification_by_id[row["id"]],
            "proof_boundary": "structural-reference-and-dependency-contract-only",
        }
        for row in contract["conformance_rules"]
    ]
    return {
        "schema_version": CONFORMANCE_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "contract-conformance-passed",
        "created_at": contract["created_at"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "source": contract["source"],
        "rule_count": len(results),
        "passed_count": len(results),
        "results": results,
        "claim_ceiling": "Conformance proves contract shape, reference closure, compatibility coverage, and forbidden dependency direction. It does not prove semantic output quality, runtime parity after extraction, or release readiness.",
    }


def render_core_contract_review(contract: dict[str, Any]) -> str:
    counts = contract["counts"]
    lines = [
        "# WFF v1.8 P1 — Minimal Core Contract Review Dossier",
        "",
        f"- Contract: `{contract['contract_id']}`",
        f"- Version: `{contract['contract_version']}`",
        f"- P0 target tree: `{contract['source']['p0_target_tree']}`",
        f"- Status: `{contract['status']}`",
        "",
        "## Decision",
        "",
        "WFF Core is a versioned semantic contract, not a preselected directory. It owns lifecycle order, public phase/handoff/identity/evidence/claim/control-boundary contracts, declarative extension registration, and bounded return/re-entry semantics. It does not own P1-P4/PX content truth, assurance execution, distribution, history, or EKRI.",
        "",
        "## Contract surface",
        "",
        f"- Core contracts: `{counts['contracts']}`",
        f"- Public semantic types: `{counts['public_types']}`",
        f"- Public operations: `{counts['public_operations']}`",
        f"- Cross-cutting invariants: `{counts['invariants']}`",
        f"- Internal non-contractual surfaces: `{counts['internal_surfaces']}`",
        "",
        "| Contract | Responsibility | Public types | Operations |",
        "|---|---|---|---|",
    ]
    for row in contract["contracts"]:
        lines.append(
            f"| `{row['id']}` | {row['summary']} | "
            + ", ".join(f"`{value}`" for value in row["public_type_ids"])
            + " | "
            + ", ".join(f"`{value}`" for value in row["operation_ids"])
            + " |"
        )
    lines.extend(["", "## Public versus internal API", ""])
    lines.append(f"- Public: {contract['public_api']['claim']}")
    lines.append("- Internal surfaces are registry storage, route indexing, structural validation, and compatibility alias indexing. Their paths and algorithms are not extension API.")
    lines.extend(["", "## Extension boundary", ""])
    lines.append("The extension descriptor is declarative. It contains identity, kind, contract range, route/phase bindings, consumed/produced contracts, truth owner, compatibility aliases, and failure policy.")
    lines.append("It explicitly excludes executable loading, dynamic imports by Core, hot reload, lifecycle callbacks, marketplace discovery, and installation/package resolution.")
    lines.extend(["", "## Compatibility matrix", "", "| Capability | Posture | Core contracts consumed |", "|---|---|---|"])
    for row in contract["capability_compatibility"]:
        lines.append(
            f"| `{row['capability_id']}` | `{row['posture']}` | "
            + ", ".join(f"`{value}`" for value in row["consumes_contract_ids"])
            + " |"
        )
    lines.extend(["", "## Migration decisions", ""])
    for row in contract["migration_decisions"]:
        lines.append(f"- **{row['id']} — {row['title']}** (`{row['status']}`): {row['decision']}")
    lines.extend(["", "## Retained P0 unknowns", ""])
    if contract["retained_p0_unknowns"]:
        for identifier in contract["retained_p0_unknowns"]:
            lines.append(f"- `{identifier}`")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## P1 extraction gate",
            "",
            "P1 authorizes P2 extraction design only after independent contract review. It does not authorize file movement, package creation, public identifier removal, or release claims. P2 must register every physical change through EKRI and prove Core has no outward dependency on capability, assurance, distribution, history, or EKRI implementations.",
            "",
            "## Claim ceiling",
            "",
            contract["claim_ceiling"],
            "",
        ]
    )
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
        raise MinimalCoreContractError(f"failed to persist P1 output {filename}: {exc}") from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _persist_outputs(repository_root: Path, contract: dict[str, Any]) -> dict[str, str]:
    public_api = _public_api_projection(contract)
    internal_api = _internal_api_projection(contract)
    extension = _extension_projection(contract)
    compatibility = _compatibility_projection(contract)
    decisions = _decision_projection(contract)
    conformance = _conformance_projection(contract)
    review = render_core_contract_review(contract).encode("utf-8")
    payloads = {
        "wff-core-contract.json": _json_bytes(contract),
        "core-public-api.json": _json_bytes(public_api),
        "core-internal-api.json": _json_bytes(internal_api),
        "extension-interface.json": _json_bytes(extension),
        "capability-compatibility-matrix.json": _json_bytes(compatibility),
        "migration-decisions.json": _json_bytes(decisions),
        "contract-conformance-report.json": _json_bytes(conformance),
        "CORE_CONTRACT_REVIEW.md": review,
    }
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-contract-output-persisted",
        "created_at": utc_now_iso(),
        "source_tree": contract["source"]["p0_target_tree"],
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "output_digests": {
            name: _sha256(payload) for name, payload in sorted(payloads.items())
        },
        "checks": [
            {"check": "p0-binding", "status": "passed", "detail": "contract records the verified P0 map/equivalence/audit digests"},
            {"check": "projection-consistency", "status": "passed", "detail": "public/internal/extension/compatibility/decision/conformance projections derive from one contract payload"},
            {"check": "no-follow-atomic-persistence", "status": "passed", "detail": "outputs were written through real-directory descriptors and atomic replacement"},
        ],
        "claim_ceiling": "Persistence and digest checks prove output integrity only; they do not strengthen P1 semantic decisions or authorize physical extraction.",
    }
    payloads["core-contract-audit.json"] = _json_bytes(audit)

    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "core-contract", contract["source"]["p0_target_tree"]):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        for filename, payload in payloads.items():
            _secure_atomic_write(parent_fd, filename, payload)
    except ObservationBoundaryError as exc:
        raise MinimalCoreContractError(str(exc)) from exc
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = repository_root / ".EKRI" / "core-contract" / contract["source"]["p0_target_tree"]
    return {
        "output_root": str(output_root),
        **{
            name.replace("-", "_").replace(".", "_"): str(output_root / name)
            for name in payloads
        },
    }


def run_minimal_core_contract(
    repository_root: str | Path,
    *,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Regenerate P0 authority and define the complete P1 contract surface."""
    root = _absolute_path(repository_root)
    if not root.is_dir():
        raise MinimalCoreContractError(f"repository root is not a directory: {root}")
    try:
        p0 = run_core_boundary_reconstruction(root, write_outputs=True)
        if p0.get("status") != "core-boundary-reconstructed":
            raise MinimalCoreContractError("P0 reconstruction did not reach an accepted state")
        spec, identity = load_core_contract_spec()
        authority = verify_p0_authority(root, spec)
        contract = build_minimal_core_contract(
            authority,
            spec,
            spec_identity=identity,
        )
        outputs: dict[str, str] = {}
        if write_outputs:
            outputs = _persist_outputs(root, contract)
        return {
            "schema_version": "ekri.minimal-core-contract-run.v1",
            "status": VALID_STATUS,
            "contract": contract,
            "outputs": outputs,
        }
    except MinimalCoreContractError:
        raise
    except (CoreBoundaryError, ObservationBoundaryError) as exc:
        raise MinimalCoreContractError(f"P1 authority validation failed: {exc}") from exc
    except Exception as exc:
        raise MinimalCoreContractError(f"P1 failed closed: {exc}") from exc
