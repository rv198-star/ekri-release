"""EKRI v1.0 P4 repository authority-firewall stress projection.

This module consumes already-validated v0.9 Repository Asset Identity,
Repository Ownership Boundary, and Repository Lifecycle Observation outputs.
It projects stable identity / evidence posture into the shared Engineering
Knowledge Model while deliberately retaining high-cardinality structural edges
as raw rebuildable observations rather than semantic Assertions.

The output is a non-authoritative stress View.  It never writes back into the
v0.9 source models and it cannot authorize ownership, retirement, physical
separation, removal, or deletion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .repository_asset_identity import (
    validate_repository_asset_knowledge_map,
)
from .repository_lifecycle_observation import (
    validate_repository_lifecycle_observation_snapshot,
)
from .repository_ownership_boundary import (
    validate_repository_ownership_boundary_map,
)
from .shadow_semantic_substrate import MODEL_VERSION


VIEW_SCHEMA_VERSION = "ekri.repository-firewall-stress-view.v1"
VIEW_STATUS = "repository-firewalls-stress-projected"
AUTHORITY_MODE = "derived-non-authoritative"
MATERIALIZATION_CLASS = "rebuildable-derived-view"
RAW_OBSERVATION_CLASS = "raw-rebuildable-structural-observation"
COMPILER_VERSION = "ekri.repository-firewall-stress-compiler.v0.1"
OUTPUT_FILENAME = "repository-firewall-stress-view.json"

OBJECT_TYPES = frozenset(
    {
        "Context",
        "RepositorySnapshot",
        "Artifact",
        "RepositoryAsset",
        "CompatibilitySurface",
    }
)
ROLES = frozenset({"SourceContext", "RepositoryAsset", "CompatibilitySurface"})
PREDICATES = frozenset(
    {
        "hasLifecycleObservationStatus",
        "hasOwnershipEvidenceStatus",
        "hasOwnerEvidenceLabel",
        "hasPresenceObservation",
        "hasObservationClass",
        "hasGovernanceObservation",
        "hasObservedLOC",
    }
)
FORBIDDEN_AUTHORITY_PREDICATES = frozenset(
    {
        "authoritativeFor",
        "ownsCapability",
        "ownsAsset",
        "retired",
        "safeDelete",
        "deletionAuthorized",
        "removalAuthorized",
    }
)


class RepositoryFirewallStressError(RuntimeError):
    """Raised when source or projected repository firewalls are contaminated."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RepositoryFirewallStressError(f"{label} must be an object")
    return dict(value)


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RepositoryFirewallStressError(f"{label} must be a list")
    return value


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RepositoryFirewallStressError(f"{label} must not be empty")
    return text


def _record_id(prefix: str, value: object) -> str:
    return f"{prefix}:{_digest(value)[:32]}"


def _context_id(tree: str) -> str:
    return f"context:git-tree:{tree}"


def _context_object(source: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    tree = _text(source.get("tree"), f"{role} source tree")
    commit = _text(source.get("commit"), f"{role} source commit")
    return {
        "semantic_id": _context_id(tree),
        "types": ["Context", "RepositorySnapshot"],
        "roles": ["SourceContext"],
        "identity": {"commit": commit, "tree": tree, "source_roles": [role]},
        "contexts": [_context_id(tree)],
        "manifestations": [],
    }


def _asset_object(asset: Mapping[str, Any], *, context_id: str) -> dict[str, Any]:
    asset_id = _text(asset.get("asset_id"), "asset_id")
    identity = _mapping(asset.get("identity_basis"), f"asset {asset_id} identity_basis")
    paths = _array(asset.get("current_paths"), f"asset {asset_id} current_paths")
    if len(paths) != 1:
        raise RepositoryFirewallStressError(f"asset {asset_id} must have one current path")
    return {
        "semantic_id": asset_id,
        "types": ["Artifact", "RepositoryAsset"],
        "roles": ["RepositoryAsset"],
        "identity": {
            "namespace": str(identity.get("namespace") or ""),
            "baseline_path": str(identity.get("baseline_path") or ""),
        },
        "facets": {
            "repository_asset_type": str(asset.get("asset_type") or ""),
            "observed_roles": sorted(str(role) for role in asset.get("observed_roles", [])),
        },
        "contexts": [context_id],
        "manifestations": [
            {
                "context_ref": context_id,
                "path": str(paths[0]),
                "git_identity": _copy(asset.get("git_identity", {})),
                "presence": "present",
            }
        ],
    }


def _surface_object(surface: Mapping[str, Any], *, context_id: str) -> dict[str, Any]:
    surface_id = _text(surface.get("surface_id"), "compatibility surface id")
    path = _text(surface.get("path"), f"surface {surface_id} path")
    return {
        "semantic_id": surface_id,
        "types": ["Artifact", "CompatibilitySurface"],
        "roles": ["CompatibilitySurface"],
        "identity": {
            "path_identity": path,
            "origin": str(surface.get("origin") or ""),
        },
        "facets": {
            "surface_origin": str(surface.get("origin") or ""),
        },
        "contexts": [context_id],
        "manifestations": [
            {
                "context_ref": context_id,
                "path": path,
                "presence": str(surface.get("presence") or ""),
                "current_loc": int(surface.get("current_loc") or 0),
            }
        ],
    }


def _qualifications(
    *,
    context_ref: str,
    source_family: str,
    epistemic: str = "observed",
    normative: str = "not-specified",
    reliance: str = "evidence-only",
) -> dict[str, Any]:
    return {
        "semantic_modality": "descriptive" if normative == "not-specified" else "normative-ceiling",
        "epistemic_posture": epistemic,
        "normative_posture": normative,
        "validity": "source-context-bound",
        "scope": "repository-authority-firewall-stress",
        "completeness": "bounded-source-projection",
        "reliance": reliance,
        "authority_mode": AUTHORITY_MODE,
        "semantic_authority": False,
        "context_ref": context_ref,
        "source_family": source_family,
    }


def _assertion(
    subject_ref: str,
    predicate: str,
    *,
    context_ref: str,
    source_family: str,
    value: Any,
    epistemic: str = "observed",
    normative: str = "not-specified",
    reliance: str = "evidence-only",
) -> dict[str, Any]:
    if predicate not in PREDICATES:
        raise RepositoryFirewallStressError(f"unsupported repository predicate: {predicate}")
    body = {
        "subject_ref": subject_ref,
        "predicate": predicate,
        "value": _copy(value),
        "qualifications": _qualifications(
            context_ref=context_ref,
            source_family=source_family,
            epistemic=epistemic,
            normative=normative,
            reliance=reliance,
        ),
    }
    return {
        "record_id": _record_id("assertion", body),
        **body,
    }


def _semantic_view_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    basis = {
        key: _copy(value)
        for key, value in payload.items()
        if key not in {
            "structural_observations",
            "structural_observation_fingerprint",
            "semantic_fingerprint",
            "projection_fingerprint",
        }
    }
    source = _mapping(basis.get("source"), "repository firewall semantic source")
    for value in source.values():
        if isinstance(value, dict):
            value.pop("projection_source_fingerprint", None)
    return basis


def _semantic_source_fingerprint(
    asset_map: Mapping[str, Any],
    ownership_map: Mapping[str, Any],
    lifecycle_snapshot: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "asset_identity": _digest(
            {
                "source": asset_map.get("source"),
                "identity_policy": asset_map.get("identity_policy"),
                "assets": asset_map.get("assets"),
                "claim_ceiling": asset_map.get("claim_ceiling"),
            }
        ),
        "ownership_semantics": _digest(
            {
                "source": ownership_map.get("source"),
                "authority_boundary": ownership_map.get("authority_boundary"),
                "assets": ownership_map.get("assets"),
                "claim_ceiling": ownership_map.get("claim_ceiling"),
            }
        ),
        "lifecycle_observation": _digest(
            {
                "source": lifecycle_snapshot.get("source"),
                "authority_boundary": lifecycle_snapshot.get("authority_boundary"),
                "tracked_assets": lifecycle_snapshot.get("tracked_assets"),
                "compatibility_surfaces": lifecycle_snapshot.get("compatibility_surfaces"),
                "claim_ceiling": lifecycle_snapshot.get("claim_ceiling"),
            }
        ),
    }


def _raw_structural_observations(
    ownership_map: Mapping[str, Any],
    *,
    context_ref: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in _array(ownership_map.get("structural_edges"), "ownership structural_edges"):
        edge = _mapping(raw, "structural edge")
        if edge.get("semantic_authority") is not False:
            raise RepositoryFirewallStressError("structural edge attempted semantic authority promotion")
        body = {
            "observation_kind": _text(edge.get("edge_type"), "structural edge type"),
            "subject_ref": _text(edge.get("source_asset_id"), "structural source asset"),
            "object_ref": _text(edge.get("target_asset_id"), "structural target asset"),
            "source_path": str(edge.get("source_path") or ""),
            "target_path": str(edge.get("target_path") or ""),
            "evidence": str(edge.get("evidence") or ""),
            "knowledge_state": str(edge.get("knowledge_state") or "observed-structural-fact"),
            "context_ref": context_ref,
            "materialization_class": RAW_OBSERVATION_CLASS,
            "semantic_authority": False,
            "reliance": "candidate-expansion-only",
        }
        result.append({"observation_id": _record_id("structural", body), **body})
    return sorted(result, key=lambda row: row["observation_id"])


def _source_assertions(
    asset_map: Mapping[str, Any],
    ownership_map: Mapping[str, Any],
    lifecycle_snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    asset_context = _context_id(str(asset_map["source"]["tree"]))
    lifecycle_context = _context_id(str(lifecycle_snapshot["source"]["tree"]))
    assertions: list[dict[str, Any]] = []

    for raw in asset_map["assets"]:
        asset = _mapping(raw, "asset")
        asset_id = _text(asset.get("asset_id"), "asset id")
        assertions.append(_assertion(asset_id, "hasLifecycleObservationStatus", context_ref=asset_context, source_family="repository-asset-identity", value=str(asset.get("lifecycle_observation_status") or "")))
        assertions.append(_assertion(asset_id, "hasOwnershipEvidenceStatus", context_ref=asset_context, source_family="repository-asset-identity", value=str(asset.get("ownership_observation_status") or ""), reliance="owner-evidence-only"))
        for label in asset.get("owner_evidence_labels", []):
            assertions.append(_assertion(asset_id, "hasOwnerEvidenceLabel", context_ref=asset_context, source_family="repository-asset-identity", value=str(label), reliance="owner-evidence-only"))

    for raw in lifecycle_snapshot["tracked_assets"]:
        row = _mapping(raw, "lifecycle tracked asset")
        asset_id = _text(row.get("asset_id"), "lifecycle asset id")
        assertions.extend(
            [
                _assertion(asset_id, "hasPresenceObservation", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("presence") or "")),
                _assertion(asset_id, "hasObservationClass", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("observation_class") or "")),
                _assertion(asset_id, "hasGovernanceObservation", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("governance_decision") or ""), reliance="observation-not-governance"),
                _assertion(asset_id, "hasObservedLOC", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=int(row.get("current_loc") or 0)),
            ]
        )

    for raw in lifecycle_snapshot["compatibility_surfaces"]:
        row = _mapping(raw, "compatibility surface")
        surface_id = _text(row.get("surface_id"), "surface id")
        assertions.extend(
            [
                _assertion(surface_id, "hasPresenceObservation", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("presence") or "")),
                _assertion(surface_id, "hasObservationClass", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("observation_class") or "")),
                _assertion(surface_id, "hasGovernanceObservation", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=str(row.get("governance_decision") or ""), reliance="observation-not-governance"),
                _assertion(surface_id, "hasObservedLOC", context_ref=lifecycle_context, source_family="repository-lifecycle-observation", value=int(row.get("current_loc") or 0)),
            ]
        )

    return sorted(assertions, key=lambda row: row["record_id"])


def _firewall_checks(
    asset_map: Mapping[str, Any],
    ownership_map: Mapping[str, Any],
    lifecycle_snapshot: Mapping[str, Any],
    raw_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    asset_by_id = {str(row["asset_id"]): row for row in asset_map["assets"]}
    ownership_by_id = {str(row["asset_id"]): row for row in ownership_map["assets"]}
    lifecycle_rows = list(lifecycle_snapshot["tracked_assets"])
    surfaces = list(lifecycle_snapshot["compatibility_surfaces"])

    owner_mutations = 0
    unresolved_with_neighborhood = 0
    unresolved_promoted = 0
    for asset_id, asset in asset_by_id.items():
        row = ownership_by_id.get(asset_id)
        if row is None:
            owner_mutations += 1
            continue
        if (
            row.get("p1_ownership_observation_status") != asset.get("ownership_observation_status")
            or row.get("p1_owner_evidence_labels") != asset.get("owner_evidence_labels")
        ):
            owner_mutations += 1
        if asset.get("ownership_observation_status") == "unresolved" and row.get("structural_owner_neighborhood"):
            unresolved_with_neighborhood += 1
            if row.get("p1_owner_evidence_labels"):
                unresolved_promoted += 1

    moved = 0
    identity_mismatch = 0
    for row in lifecycle_rows:
        asset_id = str(row.get("asset_id") or "")
        source = asset_by_id.get(asset_id)
        if source is None:
            identity_mismatch += 1
            continue
        baseline = str(row.get("baseline_path") or "")
        current = str(row.get("current_path") or "")
        if baseline != current:
            moved += 1
        if str(source.get("identity_basis", {}).get("baseline_path") or "") != baseline:
            identity_mismatch += 1

    asset_ids = set(asset_by_id)
    surface_ids = {str(row.get("surface_id") or "") for row in surfaces}
    surface_identity_collisions = len(asset_ids & surface_ids)
    baseline_paths = {
        str(row.get("identity_basis", {}).get("baseline_path") or ""): str(row.get("asset_id") or "")
        for row in asset_map["assets"]
    }
    same_path_distinct = 0
    same_path_collisions = 0
    for row in surfaces:
        path = str(row.get("path") or "")
        if path in baseline_paths:
            if str(row.get("surface_id") or "") == baseline_paths[path]:
                same_path_collisions += 1
            else:
                same_path_distinct += 1

    structural_authority_violations = sum(1 for row in raw_observations if row.get("semantic_authority") is not False)
    retirement_authorized = sum(1 for row in asset_map["assets"] if row.get("retirement_authorized") is not False)
    retirement_authorized += sum(1 for row in ownership_map["assets"] if row.get("retirement_authorized") is not False)
    physical_authorized = sum(1 for row in ownership_map["assets"] if row.get("physical_separation_authorized") is not False)
    forbidden_governance_values = [
        str(row.get("governance_decision") or "")
        for row in [*lifecycle_rows, *surfaces]
        if any(token in str(row.get("governance_decision") or "").lower() for token in ("retire", "delete", "remove", "safe-delete"))
    ]

    return {
        "asset_count": len(asset_by_id),
        "ownership_status_counts": _copy(asset_map.get("summary", {}).get("ownership_observation_counts", {})),
        "mixed_role_asset_count": int(asset_map.get("summary", {}).get("mixed_role_asset_count", 0) or 0),
        "structural_observation_count": len(raw_observations),
        "structural_semantic_authority_violation_count": structural_authority_violations,
        "owner_authority_mutation_count": owner_mutations,
        "unresolved_with_structural_neighborhood_count": unresolved_with_neighborhood,
        "unresolved_promoted_owner_count": unresolved_promoted,
        "retirement_authorization_violation_count": retirement_authorized,
        "physical_separation_authorization_violation_count": physical_authorized,
        "lifecycle_tracked_asset_count": len(lifecycle_rows),
        "moved_asset_count": moved,
        "moved_identity_mismatch_count": identity_mismatch,
        "compatibility_surface_count": len(surfaces),
        "compatibility_surface_identity_collision_count": surface_identity_collisions,
        "same_baseline_path_distinct_surface_identity_count": same_path_distinct,
        "same_baseline_path_identity_collision_count": same_path_collisions,
        "forbidden_lifecycle_governance_value_count": len(forbidden_governance_values),
        "lifecycle_governance_authority": bool(lifecycle_snapshot.get("authority_boundary", {}).get("lifecycle_governance_authority")),
        "lifecycle_retirement_decisions_allowed": bool(lifecycle_snapshot.get("authority_boundary", {}).get("retirement_decisions_allowed")),
        "lifecycle_deletion_decisions_allowed": bool(lifecycle_snapshot.get("authority_boundary", {}).get("deletion_decisions_allowed")),
    }


def compile_repository_firewall_stress_view(
    asset_map: Mapping[str, Any],
    ownership_map: Mapping[str, Any],
    lifecycle_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one non-authoritative repository firewall stress View."""
    try:
        validated_asset = validate_repository_asset_knowledge_map(asset_map)
        validated_ownership = validate_repository_ownership_boundary_map(
            ownership_map,
            p1_asset_map=validated_asset,
        )
        validated_lifecycle = validate_repository_lifecycle_observation_snapshot(lifecycle_snapshot)
    except Exception as exc:
        raise RepositoryFirewallStressError(f"source firewall model verification failed: {exc}") from exc

    asset_source = _mapping(validated_asset.get("source"), "asset source")
    ownership_source = _mapping(validated_ownership.get("source"), "ownership source")
    lifecycle_source = _mapping(validated_lifecycle.get("source"), "lifecycle source")
    if ownership_source.get("tree") != asset_source.get("tree"):
        raise RepositoryFirewallStressError("Asset and Ownership source tree identities differ")

    asset_context = _context_id(str(asset_source["tree"]))
    lifecycle_context = _context_id(str(lifecycle_source["tree"]))
    context_objects = {
        asset_context: _context_object(asset_source, role="asset-ownership"),
        lifecycle_context: _context_object(lifecycle_source, role="lifecycle-observation"),
    }
    objects: dict[str, dict[str, Any]] = dict(context_objects)
    for raw in validated_asset["assets"]:
        obj = _asset_object(raw, context_id=asset_context)
        objects[obj["semantic_id"]] = obj
    for raw in validated_lifecycle["tracked_assets"]:
        row = _mapping(raw, "lifecycle tracked asset")
        asset_id = _text(row.get("asset_id"), "lifecycle asset id")
        obj = objects.get(asset_id)
        if obj is None:
            raise RepositoryFirewallStressError(f"lifecycle asset is absent from accepted Asset Map: {asset_id}")
        if lifecycle_context not in obj["contexts"]:
            obj["contexts"].append(lifecycle_context)
        obj["manifestations"].append(
            {
                "context_ref": lifecycle_context,
                "path": str(row.get("current_path") or ""),
                "git_identity": _copy(row.get("git_identity", {})),
                "presence": str(row.get("presence") or ""),
                "current_loc": int(row.get("current_loc") or 0),
            }
        )
        obj["contexts"] = sorted(set(obj["contexts"]))
        obj["manifestations"] = sorted(obj["manifestations"], key=lambda item: (str(item.get("context_ref")), str(item.get("path"))))
    for raw in validated_lifecycle["compatibility_surfaces"]:
        obj = _surface_object(raw, context_id=lifecycle_context)
        if obj["semantic_id"] in objects:
            raise RepositoryFirewallStressError(f"compatibility surface identity collides with another Object: {obj['semantic_id']}")
        objects[obj["semantic_id"]] = obj

    raw_structural = _raw_structural_observations(validated_ownership, context_ref=asset_context)
    assertions = _source_assertions(validated_asset, validated_ownership, validated_lifecycle)
    checks = _firewall_checks(validated_asset, validated_ownership, validated_lifecycle, raw_structural)
    source_fingerprints = _semantic_source_fingerprint(validated_asset, validated_ownership, validated_lifecycle)
    structural_fingerprint = _digest(raw_structural)

    source = {
        "asset_identity": {
            "commit": str(asset_source.get("commit") or ""),
            "tree": str(asset_source.get("tree") or ""),
            "schema_version": str(validated_asset.get("schema_version") or ""),
            "semantic_source_fingerprint": source_fingerprints["asset_identity"],
            "projection_source_fingerprint": _digest(validated_asset),
        },
        "ownership_boundary": {
            "commit": str(ownership_source.get("commit") or ""),
            "tree": str(ownership_source.get("tree") or ""),
            "schema_version": str(validated_ownership.get("schema_version") or ""),
            "semantic_source_fingerprint": source_fingerprints["ownership_semantics"],
            "projection_source_fingerprint": _digest(validated_ownership),
        },
        "lifecycle_observation": {
            "commit": str(lifecycle_source.get("commit") or ""),
            "tree": str(lifecycle_source.get("tree") or ""),
            "schema_version": str(validated_lifecycle.get("schema_version") or ""),
            "semantic_source_fingerprint": source_fingerprints["lifecycle_observation"],
            "projection_source_fingerprint": _digest(validated_lifecycle),
        },
    }
    authority_ceiling = {
        "semantic_authority_source": "specialized-v0.9-models-preserved",
        "structural_observations_semantic_authority": False,
        "owner_evidence_is_authority": False,
        "structural_neighborhood_can_resolve_owner": False,
        "retirement_authorized": False,
        "physical_separation_authorized": False,
        "lifecycle_governance_authority": False,
        "deletion_decisions_allowed": False,
        "absence_can_authorize_retirement": False,
    }
    payload = {
        "schema_version": VIEW_SCHEMA_VERSION,
        "status": VIEW_STATUS,
        "model_version": MODEL_VERSION,
        "compiler_version": COMPILER_VERSION,
        "authority_mode": AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "source": source,
        "vocabulary": {
            "object_types": sorted(OBJECT_TYPES),
            "roles": sorted(ROLES),
            "predicates": sorted(PREDICATES),
            "structural_observation_class": RAW_OBSERVATION_CLASS,
        },
        "objects": sorted(objects.values(), key=lambda row: row["semantic_id"]),
        "assertions": assertions,
        "structural_observations": raw_structural,
        "authority_ceiling": authority_ceiling,
        "firewall_checks": checks,
        "summary": {
            "context_object_count": len(context_objects),
            "repository_asset_object_count": len(validated_asset["assets"]),
            "compatibility_surface_object_count": len(validated_lifecycle["compatibility_surfaces"]),
            "object_count": len(objects),
            "semantic_assertion_count": len(assertions),
            "raw_structural_observation_count": len(raw_structural),
        },
        "structural_observation_fingerprint": structural_fingerprint,
        "claim_ceiling": (
            "This P4 stress View proves only that accepted repository identity, owner-evidence, structural, lifecycle-observation, and authorization ceilings can coexist on the shared Engineering Knowledge Model without authority contamination. "
            "It does not make structural topology semantic ownership, does not prove dependency completeness or absence, and cannot authorize retirement, physical separation, removal, safe deletion, or production behavior."
        ),
    }
    payload["semantic_fingerprint"] = _digest(_semantic_view_basis(payload))
    payload["projection_fingerprint"] = _digest(
        {
            **payload,
            "semantic_fingerprint": payload["semantic_fingerprint"],
        }
    )
    return validate_repository_firewall_stress_view(payload)


def validate_repository_firewall_stress_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _copy(payload)
    if not isinstance(data, dict):
        raise RepositoryFirewallStressError("repository firewall stress view must be an object")
    if data.get("schema_version") != VIEW_SCHEMA_VERSION:
        raise RepositoryFirewallStressError("unsupported repository firewall stress schema")
    if data.get("status") != VIEW_STATUS:
        raise RepositoryFirewallStressError("unexpected repository firewall stress status")
    if data.get("model_version") != MODEL_VERSION:
        raise RepositoryFirewallStressError("repository firewall stress model_version drifted")
    if data.get("authority_mode") != AUTHORITY_MODE:
        raise RepositoryFirewallStressError("repository firewall stress view must remain non-authoritative")
    if data.get("materialization_class") != MATERIALIZATION_CLASS:
        raise RepositoryFirewallStressError("repository firewall stress view must remain rebuildable")

    vocabulary = _mapping(data.get("vocabulary"), "repository firewall vocabulary")
    if set(vocabulary.get("object_types", [])) != set(OBJECT_TYPES):
        raise RepositoryFirewallStressError("repository object vocabulary changed")
    if set(vocabulary.get("roles", [])) != set(ROLES):
        raise RepositoryFirewallStressError("repository role vocabulary changed")
    if set(vocabulary.get("predicates", [])) != set(PREDICATES):
        raise RepositoryFirewallStressError("repository predicate vocabulary changed")
    if vocabulary.get("structural_observation_class") != RAW_OBSERVATION_CLASS:
        raise RepositoryFirewallStressError("structural observation materialization class changed")

    object_ids: set[str] = set()
    for raw in _array(data.get("objects"), "repository objects"):
        row = _mapping(raw, "repository object")
        semantic_id = _text(row.get("semantic_id"), "repository object semantic_id")
        if semantic_id in object_ids:
            raise RepositoryFirewallStressError(f"duplicate repository object identity: {semantic_id}")
        object_ids.add(semantic_id)
        if not set(row.get("types", [])) <= OBJECT_TYPES:
            raise RepositoryFirewallStressError(f"unsupported repository Object type: {semantic_id}")
        if not set(row.get("roles", [])) <= ROLES:
            raise RepositoryFirewallStressError(f"unsupported repository Object role: {semantic_id}")
        if set(row) not in ({"semantic_id", "types", "roles", "identity", "contexts", "manifestations"}, {"semantic_id", "types", "roles", "identity", "facets", "contexts", "manifestations"}):
            raise RepositoryFirewallStressError(f"repository Object fields are not canonical: {semantic_id}")
        if "facets" in row and not isinstance(row.get("facets"), dict):
            raise RepositoryFirewallStressError(f"repository Object facets must be an object: {semantic_id}")

    assertion_ids: set[str] = set()
    for raw in _array(data.get("assertions"), "repository assertions"):
        row = _mapping(raw, "repository assertion")
        record_id = _text(row.get("record_id"), "repository assertion record_id")
        if record_id in assertion_ids:
            raise RepositoryFirewallStressError(f"duplicate repository assertion: {record_id}")
        assertion_ids.add(record_id)
        subject = _text(row.get("subject_ref"), "repository assertion subject_ref")
        if subject not in object_ids:
            raise RepositoryFirewallStressError(f"repository assertion references missing Object: {subject}")
        predicate = _text(row.get("predicate"), "repository assertion predicate")
        if predicate in FORBIDDEN_AUTHORITY_PREDICATES or predicate not in PREDICATES:
            raise RepositoryFirewallStressError(f"repository assertion predicate violates authority boundary: {predicate}")
        qualifications = _mapping(row.get("qualifications"), "repository assertion qualifications")
        if qualifications.get("authority_mode") != AUTHORITY_MODE or qualifications.get("semantic_authority") is not False:
            raise RepositoryFirewallStressError("repository assertion attempted semantic authority promotion")

    structural_ids: set[str] = set()
    for raw in _array(data.get("structural_observations"), "structural observations"):
        row = _mapping(raw, "structural observation")
        observation_id = _text(row.get("observation_id"), "structural observation id")
        if observation_id in structural_ids:
            raise RepositoryFirewallStressError(f"duplicate structural observation: {observation_id}")
        structural_ids.add(observation_id)
        if row.get("materialization_class") != RAW_OBSERVATION_CLASS:
            raise RepositoryFirewallStressError("structural edge was promoted out of raw observation class")
        if row.get("semantic_authority") is not False:
            raise RepositoryFirewallStressError("structural observation attempted semantic authority promotion")
        if row.get("subject_ref") not in object_ids or row.get("object_ref") not in object_ids:
            raise RepositoryFirewallStressError("structural observation references missing asset Object")

    ceiling = _mapping(data.get("authority_ceiling"), "repository authority ceiling")
    required_false = (
        "structural_observations_semantic_authority",
        "owner_evidence_is_authority",
        "structural_neighborhood_can_resolve_owner",
        "retirement_authorized",
        "physical_separation_authorized",
        "lifecycle_governance_authority",
        "deletion_decisions_allowed",
        "absence_can_authorize_retirement",
    )
    for key in required_false:
        if ceiling.get(key) is not False:
            raise RepositoryFirewallStressError(f"repository authority ceiling was raised: {key}")

    checks = _mapping(data.get("firewall_checks"), "repository firewall checks")
    zero_required = (
        "structural_semantic_authority_violation_count",
        "owner_authority_mutation_count",
        "unresolved_promoted_owner_count",
        "retirement_authorization_violation_count",
        "physical_separation_authorization_violation_count",
        "moved_identity_mismatch_count",
        "compatibility_surface_identity_collision_count",
        "same_baseline_path_identity_collision_count",
        "forbidden_lifecycle_governance_value_count",
    )
    for key in zero_required:
        if int(checks.get(key, -1)) != 0:
            raise RepositoryFirewallStressError(f"repository firewall check failed: {key}")
    for key in (
        "lifecycle_governance_authority",
        "lifecycle_retirement_decisions_allowed",
        "lifecycle_deletion_decisions_allowed",
    ):
        if checks.get(key) is not False:
            raise RepositoryFirewallStressError(f"lifecycle governance firewall failed: {key}")

    expected_structural = _digest(data["structural_observations"])
    if data.get("structural_observation_fingerprint") != expected_structural:
        raise RepositoryFirewallStressError("structural observation fingerprint mismatch")
    expected_semantic = _digest(_semantic_view_basis(data))
    if data.get("semantic_fingerprint") != expected_semantic:
        raise RepositoryFirewallStressError("repository firewall semantic fingerprint mismatch")
    expected_projection = _digest(
        {
            **{key: value for key, value in data.items() if key != "projection_fingerprint"},
        }
    )
    if data.get("projection_fingerprint") != expected_projection:
        raise RepositoryFirewallStressError("repository firewall projection fingerprint mismatch")
    return data


def repository_firewall_output_path(
    repository_root: str | Path,
    *,
    asset_tree: str,
    lifecycle_tree: str,
) -> Path:
    root = Path(repository_root).expanduser().resolve(strict=False)
    return root / ".EKRI" / "shadow" / "repository-firewall" / f"{asset_tree}--{lifecycle_tree}" / OUTPUT_FILENAME


def persist_repository_firewall_stress_view(
    repository_root: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    view = validate_repository_firewall_stress_view(payload)
    asset_tree = str(view["source"]["asset_identity"]["tree"])
    lifecycle_tree = str(view["source"]["lifecycle_observation"]["tree"])
    output = repository_firewall_output_path(repository_root, asset_tree=asset_tree, lifecycle_tree=lifecycle_tree)
    current = Path(repository_root).expanduser().resolve(strict=False)
    for component in (".EKRI", "shadow", "repository-firewall", f"{asset_tree}--{lifecycle_tree}"):
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise RepositoryFirewallStressError(f"repository firewall output directory is unsafe: {current}")
        else:
            current.mkdir()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise RepositoryFirewallStressError(f"repository firewall output is unsafe: {output}")
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise RepositoryFirewallStressError(f"repository firewall temporary output is unsafe: {temporary}")
        temporary.unlink()
    temporary.write_text(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output
