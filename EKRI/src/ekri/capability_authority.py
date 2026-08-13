"""EKRI v1.0 P6 authoritative Capability semantic slice.

This module performs the first bounded EKRI v1.0 semantic-authority cutover.
Capability semantics are reconstructed from one verified/equivalent Architecture
View plus the committed Capability specification, normalized into one
`ontology-authoritative` slice, and optionally persisted below `.EKRI/semantic/`.

The v0.9 Capability Catalog is no longer a peer semantic authority once the
supported compatibility entry point is routed through this slice. Query indexes
and legacy catalogs remain derived projections.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .architecture_roundtrip import validate_architecture_view
from .capability_contract import (
    CATALOG_SCHEMA_VERSION,
    SPEC_PROFILE_ID,
    CapabilitySpecIdentity,
    _knowledge_posture,
    _reuse_limitations,
    _row_projection,
    normalize_capability_alias,
)


AUTHORITY_SCHEMA_VERSION = "ekri.capability-semantic-authority.v1"
AUTHORITY_STATUS = "capability-semantic-authority-established"
AUTHORITY_MODE = "ontology-authoritative"
MATERIALIZATION_CLASS = "reconstructable-semantic-authority"
AUTHORITY_FILENAME = "capability-semantic-authority.json"


class CapabilityAuthorityError(RuntimeError):
    """Raised when Capability semantic authority cannot be established safely."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _copy_object(value: Mapping[str, Any] | object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityAuthorityError(f"{label} must be an object")
    return json.loads(json.dumps(dict(value), ensure_ascii=False))


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CapabilityAuthorityError(f"{label} must not be empty")
    return text


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapabilityAuthorityError(f"{label} must be a list")
    return value


def _view_source(view: Mapping[str, Any]) -> dict[str, str]:
    source = view.get("source")
    if not isinstance(source, Mapping):
        raise CapabilityAuthorityError("Architecture View source must be an object")
    return {
        "snapshot_id": _text(source.get("snapshot_id"), "Architecture View snapshot_id"),
        "commit": _text(source.get("source_commit"), "Architecture View source_commit"),
        "tree": _text(source.get("source_tree"), "Architecture View source_tree"),
    }


def _spec_identity_payload(identity: CapabilitySpecIdentity) -> dict[str, str]:
    return {key: str(value) for key, value in asdict(identity).items()}


def _capability_entries(specification: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = specification.get("capabilities")
    if not isinstance(raw, list) or not raw:
        raise CapabilityAuthorityError("capability specification requires capabilities")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        row = _copy_object(item, "capability specification entry")
        capability_id = _text(row.get("id"), "capability id")
        if capability_id in seen:
            raise CapabilityAuthorityError(f"duplicate capability id: {capability_id}")
        seen.add(capability_id)
        rows.append(row)
    return rows


def _normalized_aliases(capability: Mapping[str, Any]) -> list[str]:
    capability_id = _text(capability.get("id"), "capability id")
    name = _text(capability.get("name"), f"capability {capability_id} name")
    raw_aliases = capability.get("aliases")
    if not isinstance(raw_aliases, list) or not raw_aliases:
        raise CapabilityAuthorityError(f"capability {capability_id} aliases must be non-empty")
    values = [capability_id, name, *[str(value) for value in raw_aliases]]
    aliases: list[str] = []
    for raw in values:
        alias = normalize_capability_alias(raw)
        if not alias:
            raise CapabilityAuthorityError(f"capability {capability_id} alias normalizes to empty")
        if alias not in aliases:
            aliases.append(alias)
    return sorted(aliases)


def _family_index(view: Mapping[str, Any], family: str) -> dict[str, dict[str, Any]]:
    semantic_content = view.get("semantic_content")
    if not isinstance(semantic_content, Mapping):
        raise CapabilityAuthorityError("Architecture View semantic_content must be an object")
    rows = semantic_content.get(family)
    if not isinstance(rows, list):
        raise CapabilityAuthorityError(f"Architecture View {family} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = _copy_object(raw, f"Architecture View {family} row")
        identifier = _text(row.get("id"), f"Architecture View {family} id")
        if identifier in result:
            raise CapabilityAuthorityError(f"duplicate Architecture View {family} id: {identifier}")
        result[identifier] = row
    return result


def _view_indexes(view: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "architecture": _family_index(view, "system_architecture_tree"),
        "responsibility": _family_index(view, "module_responsibility_map"),
        "constraint": _family_index(view, "constraints"),
        "intent": _family_index(view, "implementation_intent_summary"),
        "assurance": _family_index(view, "validation_assurance_ownership"),
    }


def _selected_rows(
    capability: Mapping[str, Any],
    field: str,
    *,
    family: str,
    indexes: Mapping[str, Mapping[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    raw_ids = capability.get(field)
    if not isinstance(raw_ids, list):
        raise CapabilityAuthorityError(
            f"capability {capability.get('id')} {field} must be a list"
        )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = indexes[family]
    for raw in raw_ids:
        identifier = _text(raw, f"capability {capability.get('id')} {field} item")
        if identifier in seen:
            raise CapabilityAuthorityError(
                f"duplicate capability {capability.get('id')} {field}: {identifier}"
            )
        seen.add(identifier)
        row = index.get(identifier)
        if row is None:
            raise CapabilityAuthorityError(
                f"capability {capability.get('id')} references unknown {family}: {identifier}"
            )
        rows.append(row)
    return rows


def _view_evidence_refs(view: Mapping[str, Any]) -> set[str]:
    semantic_content = view.get("semantic_content")
    if not isinstance(semantic_content, Mapping):
        raise CapabilityAuthorityError("Architecture View semantic_content must be an object")
    refs: set[str] = set()
    for family in (
        "system_architecture_tree",
        "module_responsibility_map",
        "constraints",
        "implementation_intent_summary",
        "validation_assurance_ownership",
        "unknowns",
    ):
        rows = semantic_content.get(family)
        if not isinstance(rows, list):
            raise CapabilityAuthorityError(f"Architecture View {family} must be a list")
        for row in rows:
            if not isinstance(row, Mapping):
                raise CapabilityAuthorityError(f"Architecture View {family} row must be an object")
            raw_refs = row.get("evidence_refs", [])
            if not isinstance(raw_refs, list):
                raise CapabilityAuthorityError(f"Architecture View {family} evidence_refs must be a list")
            refs.update(_text(ref, f"Architecture View {family} evidence ref") for ref in raw_refs)
    return refs


def _validate_spec_against_view(
    view: Mapping[str, Any],
    specification: Mapping[str, Any],
) -> None:
    source = _view_source(view)
    target = specification.get("target")
    if not isinstance(target, Mapping):
        raise CapabilityAuthorityError("capability specification target must be an object")
    if str(target.get("commit") or "") != source["commit"] or str(target.get("tree") or "") != source["tree"]:
        raise CapabilityAuthorityError("capability specification target does not match Architecture View")
    indexes = _view_indexes(view)
    evidence_refs = _view_evidence_refs(view)
    for capability in _capability_entries(specification):
        _selected_rows(capability, "architecture_node_ids", family="architecture", indexes=indexes)
        _selected_rows(capability, "responsibility_ids", family="responsibility", indexes=indexes)
        _selected_rows(capability, "constraint_ids", family="constraint", indexes=indexes)
        _selected_rows(capability, "intent_ids", family="intent", indexes=indexes)
        _selected_rows(capability, "assurance_ids", family="assurance", indexes=indexes)
        for raw_ref in capability.get("mainline_evidence_refs", []):
            ref = _text(raw_ref, f"capability {capability.get('id')} mainline evidence ref")
            if ref not in evidence_refs:
                raise CapabilityAuthorityError(
                    f"capability {capability.get('id')} mainline evidence is outside shared Architecture View: {ref}"
                )


def _materialize_capability(
    view: Mapping[str, Any],
    specification_capability: Mapping[str, Any],
) -> dict[str, Any]:
    capability_id = _text(specification_capability.get("id"), "capability id")
    indexes = _view_indexes(view)
    architecture_rows = _selected_rows(
        specification_capability,
        "architecture_node_ids",
        family="architecture",
        indexes=indexes,
    )
    responsibility_rows = _selected_rows(
        specification_capability,
        "responsibility_ids",
        family="responsibility",
        indexes=indexes,
    )
    constraint_rows = _selected_rows(
        specification_capability,
        "constraint_ids",
        family="constraint",
        indexes=indexes,
    )
    intent_rows = _selected_rows(
        specification_capability,
        "intent_ids",
        family="intent",
        indexes=indexes,
    )
    assurance_rows = _selected_rows(
        specification_capability,
        "assurance_ids",
        family="assurance",
        indexes=indexes,
    )
    all_rows = [
        *architecture_rows,
        *responsibility_rows,
        *constraint_rows,
        *intent_rows,
        *assurance_rows,
    ]
    state, confidence = _knowledge_posture([*architecture_rows, *responsibility_rows])
    existence = (
        "unknown"
        if state in {"unknown", "conflicting"}
        else "inferred-existing"
        if state == "inferred-knowledge"
        else "confirmed-existing"
    )
    evidence_refs = {
        str(ref)
        for row in all_rows
        for ref in row.get("evidence_refs", [])
    }
    mainline_refs = {
        _text(ref, f"capability {capability_id} mainline evidence ref")
        for ref in specification_capability.get("mainline_evidence_refs", [])
    }
    return {
        "id": capability_id,
        "name": _text(specification_capability.get("name"), f"capability {capability_id} name"),
        "aliases": _normalized_aliases(specification_capability),
        "existence": existence,
        "knowledge_state": state,
        "confidence": confidence,
        "architecture_nodes": [
            _row_projection(row, row_type="architecture") for row in architecture_rows
        ],
        "responsibilities": [
            _row_projection(row, row_type="responsibility") for row in responsibility_rows
        ],
        "constraints": [
            _row_projection(row, row_type="constraint") for row in constraint_rows
        ],
        "implementation_intents": [
            _row_projection(row, row_type="intent") for row in intent_rows
        ],
        "assurance_ownership": [
            _row_projection(row, row_type="assurance") for row in assurance_rows
        ],
        "locations": list(
            dict.fromkeys(
                _text(value, f"capability {capability_id} location")
                for value in specification_capability.get("locations", [])
            )
        ),
        "reuse_limitations": _reuse_limitations(
            architecture_rows,
            responsibility_rows,
            constraint_rows,
        ),
        "mainline_impact": {
            "classification": _text(
                specification_capability.get("mainline_impact"),
                f"capability {capability_id} mainline impact",
            ),
            "knowledge_state": "inferred-knowledge",
            "confidence": "high",
            "rationale": _text(
                specification_capability.get("mainline_rationale"),
                f"capability {capability_id} mainline rationale",
            ),
            "evidence_refs": sorted(mainline_refs),
        },
        "evidence_refs": sorted(evidence_refs | mainline_refs),
    }


def _semantic_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = payload["source"]
    return {
        "source": {
            "snapshot_id": source["snapshot_id"],
            "commit": source["commit"],
            "tree": source["tree"],
            "architecture_view_semantic_fingerprint": source[
                "architecture_view_semantic_fingerprint"
            ],
        },
        "specification_sha256": payload["specification"]["sha256"],
        "capabilities": payload["capabilities"],
        "authority_mode": AUTHORITY_MODE,
    }


def _projection_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = payload["source"]
    return {
        "semantic_fingerprint": payload["semantic_fingerprint"],
        "input_mode": source["input_mode"],
        "project_asset_id": source["project_asset_id"],
        "semantic_source_mode": source["semantic_source_mode"],
        "phase1_human_projection_sha256": source[
            "phase1_human_projection_sha256"
        ],
        "architecture_view_projection_fingerprint": source[
            "architecture_view_projection_fingerprint"
        ],
        "specification": payload["specification"],
    }


def build_capability_semantic_authority(
    architecture_view: Mapping[str, Any],
    specification: Mapping[str, Any],
    specification_identity: CapabilitySpecIdentity,
    *,
    input_mode: str = "provided-verified-view",
    project_asset_id: str = "",
    phase1_human_projection_sha256: str = "",
) -> dict[str, Any]:
    """Establish the single Capability semantic authority for one source context."""
    view = validate_architecture_view(architecture_view)
    _validate_spec_against_view(view, specification)
    if input_mode not in {
        "provided-verified-view",
        "verified-local-phase1",
        "verified-project-asset",
    }:
        raise CapabilityAuthorityError(f"unsupported Capability authority input_mode: {input_mode}")
    if input_mode == "verified-project-asset" and not project_asset_id:
        raise CapabilityAuthorityError("verified-project-asset authority requires project_asset_id")
    if input_mode != "verified-project-asset" and project_asset_id:
        raise CapabilityAuthorityError("project_asset_id is invalid for non-project Capability authority")
    if phase1_human_projection_sha256:
        if len(phase1_human_projection_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in phase1_human_projection_sha256
        ):
            raise CapabilityAuthorityError("phase1_human_projection_sha256 must be sha256")

    source = _view_source(view)
    capabilities = [
        _materialize_capability(view, row)
        for row in _capability_entries(specification)
    ]
    capabilities.sort(key=lambda row: row["id"])
    payload: dict[str, Any] = {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "status": AUTHORITY_STATUS,
        "authority_mode": AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "source": {
            **source,
            "input_mode": input_mode,
            "project_asset_id": project_asset_id,
            "semantic_source_mode": "architecture-view-plus-capability-spec",
            "phase1_human_projection_sha256": phase1_human_projection_sha256,
            "architecture_view_schema_version": view["schema_version"],
            "architecture_view_semantic_fingerprint": view["semantic_fingerprint"],
            "architecture_view_projection_fingerprint": view["projection_fingerprint"],
        },
        "specification": _spec_identity_payload(specification_identity),
        "capability_count": len(capabilities),
        "capabilities": capabilities,
        "claim_ceiling": (
            "This ontology-authoritative Capability slice establishes the supported Capability semantics for the exact verified source context from the proven-equivalent Architecture View and committed Capability specification. It does not make the derived query index or legacy Capability Catalog authoritative, prove exhaustive capability absence, or raise Architecture/production claims."
        ),
    }
    payload["semantic_fingerprint"] = _digest(_semantic_basis(payload))
    payload["projection_fingerprint"] = _digest(_projection_basis(payload))
    return validate_capability_semantic_authority(payload)


def build_capability_semantic_authority_from_verified_catalog(
    architecture_view: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    project_asset_id: str,
) -> dict[str, Any]:
    """Migrate one independently verified portable Capability Catalog into authority.

    This is a one-way migration adapter for portable project knowledge that does
    not retain/replay a Capability specification. The verified catalog is a seed
    only; after this function returns, queries and compatibility outputs consume
    the new authority rather than the seed catalog.
    """
    view = validate_architecture_view(architecture_view)
    data = _copy_object(catalog, "verified portable Capability Catalog")
    if data.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CapabilityAuthorityError("portable Capability seed schema is unsupported")
    if data.get("profile_id") != SPEC_PROFILE_ID:
        raise CapabilityAuthorityError("portable Capability seed profile is unsupported")
    source = data.get("source")
    if not isinstance(source, Mapping):
        raise CapabilityAuthorityError("portable Capability seed source must be an object")
    view_source = _view_source(view)
    if str(source.get("commit") or "") != view_source["commit"] or str(source.get("tree") or "") != view_source["tree"]:
        raise CapabilityAuthorityError("portable Capability seed target does not match Architecture View")
    human_sha = _text(
        source.get("phase1_human_projection_sha256"),
        "portable Capability seed Phase1 human projection digest",
    )
    if len(human_sha) != 64 or any(char not in "0123456789abcdef" for char in human_sha):
        raise CapabilityAuthorityError("portable Capability seed human projection digest is invalid")
    specification = data.get("specification")
    if not isinstance(specification, Mapping):
        raise CapabilityAuthorityError("portable Capability seed specification identity must be an object")
    spec_identity = {key: str(specification.get(key) or "") for key in (
        "source",
        "path",
        "sha256",
        "scanner_commit",
        "scanner_tree",
        "blob_oid",
    )}
    if len(spec_identity["sha256"]) != 64 or any(
        char not in "0123456789abcdef" for char in spec_identity["sha256"]
    ):
        raise CapabilityAuthorityError("portable Capability seed specification sha256 is invalid")
    raw_capabilities = data.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise CapabilityAuthorityError("portable Capability seed requires semantic rows")
    allowed_evidence = _view_evidence_refs(view)
    architecture_ids = set(_view_indexes(view)["architecture"])
    capabilities: list[dict[str, Any]] = []
    for raw in raw_capabilities:
        row = _copy_object(raw, "portable Capability seed row")
        capability_id = _text(row.get("id"), "portable Capability seed id")
        aliases = row.get("aliases")
        if not isinstance(aliases, list) or aliases != sorted(set(str(value) for value in aliases)):
            raise CapabilityAuthorityError(
                f"portable Capability seed aliases must be normalized/sorted: {capability_id}"
            )
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not set(str(value) for value in refs) <= allowed_evidence:
            raise CapabilityAuthorityError(
                f"portable Capability seed evidence escapes verified Architecture View: {capability_id}"
            )
        for node in row.get("architecture_nodes", []):
            if not isinstance(node, Mapping) or str(node.get("id") or "") not in architecture_ids:
                raise CapabilityAuthorityError(
                    f"portable Capability seed references unknown Architecture node: {capability_id}"
                )
        capabilities.append(row)
    capabilities.sort(key=lambda row: str(row["id"]))
    payload: dict[str, Any] = {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "status": AUTHORITY_STATUS,
        "authority_mode": AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "source": {
            **view_source,
            "input_mode": "verified-project-asset",
            "project_asset_id": _text(project_asset_id, "portable Capability seed project_asset_id"),
            "semantic_source_mode": "verified-portable-capability-seed",
            "phase1_human_projection_sha256": human_sha,
            "architecture_view_schema_version": view["schema_version"],
            "architecture_view_semantic_fingerprint": view["semantic_fingerprint"],
            "architecture_view_projection_fingerprint": view["projection_fingerprint"],
        },
        "specification": spec_identity,
        "capability_count": len(capabilities),
        "capabilities": capabilities,
        "claim_ceiling": (
            "This ontology-authoritative Capability slice was migrated one-way from an independently verified portable Capability Catalog whose target/evidence identities are bound to the same Architecture View. The seed Catalog is not retained as peer authority, and the cutover does not prove exhaustive capability absence, Architecture authority migration, or production readiness."
        ),
    }
    payload["semantic_fingerprint"] = _digest(_semantic_basis(payload))
    payload["projection_fingerprint"] = _digest(_projection_basis(payload))
    return validate_capability_semantic_authority(payload)


def validate_capability_semantic_authority(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    data = _copy_object(payload, "Capability semantic authority")
    if data.get("schema_version") != AUTHORITY_SCHEMA_VERSION:
        raise CapabilityAuthorityError("unsupported Capability authority schema")
    if data.get("status") != AUTHORITY_STATUS:
        raise CapabilityAuthorityError("unexpected Capability authority status")
    if data.get("authority_mode") != AUTHORITY_MODE:
        raise CapabilityAuthorityError("Capability slice must be ontology-authoritative")
    if data.get("materialization_class") != MATERIALIZATION_CLASS:
        raise CapabilityAuthorityError("Capability authority materialization class changed")
    source = data.get("source")
    if not isinstance(source, Mapping):
        raise CapabilityAuthorityError("Capability authority source must be an object")
    expected_source_keys = {
        "snapshot_id",
        "commit",
        "tree",
        "input_mode",
        "project_asset_id",
        "semantic_source_mode",
        "phase1_human_projection_sha256",
        "architecture_view_schema_version",
        "architecture_view_semantic_fingerprint",
        "architecture_view_projection_fingerprint",
    }
    if set(source) != expected_source_keys:
        raise CapabilityAuthorityError("Capability authority source fields are not canonical")
    for key in expected_source_keys - {
        "project_asset_id",
        "phase1_human_projection_sha256",
    }:
        _text(source.get(key), f"Capability authority source {key}")
    if source.get("semantic_source_mode") not in {
        "architecture-view-plus-capability-spec",
        "verified-portable-capability-seed",
    }:
        raise CapabilityAuthorityError("Capability authority semantic_source_mode is invalid")
    if source.get("input_mode") not in {
        "provided-verified-view",
        "verified-local-phase1",
        "verified-project-asset",
    }:
        raise CapabilityAuthorityError("Capability authority input_mode is invalid")
    project_asset_id = str(source.get("project_asset_id") or "")
    if source.get("input_mode") == "verified-project-asset" and not project_asset_id:
        raise CapabilityAuthorityError("verified-project-asset authority requires project_asset_id")
    if source.get("input_mode") != "verified-project-asset" and project_asset_id:
        raise CapabilityAuthorityError("Capability authority project_asset_id is invalid")
    human_sha = str(source.get("phase1_human_projection_sha256") or "")
    if human_sha and (
        len(human_sha) != 64
        or any(char not in "0123456789abcdef" for char in human_sha)
    ):
        raise CapabilityAuthorityError("Capability authority human projection digest is invalid")
    spec = data.get("specification")
    if not isinstance(spec, Mapping):
        raise CapabilityAuthorityError("Capability authority specification must be an object")
    if set(spec) != {
        "source",
        "path",
        "sha256",
        "scanner_commit",
        "scanner_tree",
        "blob_oid",
    }:
        raise CapabilityAuthorityError("Capability authority specification identity is not canonical")
    spec_sha = _text(spec.get("sha256"), "Capability authority specification sha256")
    if len(spec_sha) != 64 or any(char not in "0123456789abcdef" for char in spec_sha):
        raise CapabilityAuthorityError("Capability authority specification sha256 is invalid")

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise CapabilityAuthorityError("Capability authority capabilities must be non-empty")
    ids: list[str] = []
    for raw in capabilities:
        if not isinstance(raw, Mapping):
            raise CapabilityAuthorityError("Capability authority entry must be an object")
        capability_id = _text(raw.get("id"), "Capability authority capability id")
        if capability_id in ids:
            raise CapabilityAuthorityError(f"duplicate Capability authority id: {capability_id}")
        ids.append(capability_id)
        aliases = raw.get("aliases")
        if not isinstance(aliases, list) or aliases != sorted(set(str(value) for value in aliases)):
            raise CapabilityAuthorityError(f"Capability authority aliases must be sorted/unique: {capability_id}")
        evidence_refs = raw.get("evidence_refs")
        if not isinstance(evidence_refs, list) or evidence_refs != sorted(set(str(value) for value in evidence_refs)):
            raise CapabilityAuthorityError(f"Capability authority evidence refs must be sorted/unique: {capability_id}")
        if raw.get("existence") not in {
            "confirmed-existing",
            "inferred-existing",
            "unknown",
        }:
            raise CapabilityAuthorityError(f"Capability authority existence is invalid: {capability_id}")
        knowledge_state = str(raw.get("knowledge_state") or "")
        if knowledge_state not in {"observed-fact", "inferred-knowledge", "unknown", "conflicting"}:
            raise CapabilityAuthorityError(f"Capability authority knowledge_state is invalid: {capability_id}")
        if knowledge_state in {"unknown", "conflicting"} and raw.get("existence") != "unknown":
            raise CapabilityAuthorityError(
                f"Capability authority uncertain/conflicting knowledge cannot claim confirmed existence: {capability_id}"
            )
        if not isinstance(raw.get("mainline_impact"), Mapping):
            raise CapabilityAuthorityError(f"Capability authority mainline impact missing: {capability_id}")
    if data.get("capability_count") != len(ids):
        raise CapabilityAuthorityError("Capability authority capability_count mismatch")
    if ids != sorted(ids):
        raise CapabilityAuthorityError("Capability authority capabilities must be sorted by id")

    for key in ("semantic_fingerprint", "projection_fingerprint"):
        value = _text(data.get(key), f"Capability authority {key}")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise CapabilityAuthorityError(f"Capability authority {key} must be sha256")
    if data["semantic_fingerprint"] != _digest(_semantic_basis(data)):
        raise CapabilityAuthorityError("Capability authority semantic_fingerprint mismatch")
    if data["projection_fingerprint"] != _digest(_projection_basis(data)):
        raise CapabilityAuthorityError("Capability authority projection_fingerprint mismatch")
    _text(data.get("claim_ceiling"), "Capability authority claim_ceiling")
    return data


def capability_authority_path(
    repository_root: str | Path,
    source_tree: str,
) -> Path:
    root = Path(repository_root).expanduser().resolve(strict=False)
    tree = _text(source_tree, "Capability authority source tree")
    return root / ".EKRI" / "semantic" / tree / AUTHORITY_FILENAME


def persist_capability_semantic_authority(
    repository_root: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Persist the sole Capability semantic authority below the protected .EKRI root."""
    validated = validate_capability_semantic_authority(payload)
    root = Path(repository_root).expanduser().resolve(strict=False)
    source_tree = str(validated["source"]["tree"])
    output = capability_authority_path(root, source_tree)
    current = root
    for component in (".EKRI", "semantic", source_tree):
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise CapabilityAuthorityError(
                    f"Capability authority output directory is unsafe: {current}"
                )
        else:
            current.mkdir()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise CapabilityAuthorityError(f"Capability authority output file is unsafe: {output}")
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise CapabilityAuthorityError(
                f"Capability authority temporary output is unsafe: {temporary}"
            )
        temporary.unlink()
    temporary.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output
