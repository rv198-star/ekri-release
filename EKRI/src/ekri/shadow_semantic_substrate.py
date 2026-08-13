"""Read-only EKRI v1.0 shadow semantic substrate for verified Phase-1 knowledge.

This module is intentionally non-authoritative.  It compiles already-verified
EKRI knowledge into the v1.0 Engineering Knowledge Model normal form without
rescanning source code or changing any current v0.9 semantic writer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .phase1_snapshot import VerifiedPhase1Snapshot, verify_phase1_snapshot


SHADOW_SCHEMA_VERSION = "ekri.engineering-knowledge-shadow.v1"
MODEL_VERSION = "ekri.engineering-knowledge-model.v0.1"
COMPILER_VERSION = "ekri.architecture-shadow-compiler.v0.1"
RUN_SCHEMA_VERSION = "ekri.architecture-shadow-compiler-run.v1"
AUTHORITY_MODE = "shadow-non-authoritative"
SHADOW_STATUS = "shadow-compiled"
OUTPUT_FILENAME = "engineering-knowledge-shadow.json"

_KNOWLEDGE_STATE_TO_EPISTEMIC = {
    "observed-fact": "observed",
    "inferred-knowledge": "inferred",
    "unknown": "unknown",
}

_ARCHITECTURE_FAMILY = "system_architecture_tree"
_SOURCE_FAMILIES = (
    _ARCHITECTURE_FAMILY,
    "module_responsibility_map",
    "implementation_intent_summary",
    "validation_assurance_ownership",
    "constraints",
    "unknowns",
)
P1_OBJECT_TYPES = frozenset({"Context", "RepositorySnapshot", "SystemElement"})
P1_ROLES = frozenset({"ArchitectureElement", "SourceContext"})
P1_PREDICATES = frozenset(
    {
        "excludesResponsibility",
        "hasConstraint",
        "hasImplementationIntent",
        "hasName",
        "hasResponsibility",
        "hasSourceKind",
        "hasUnresolvedStatement",
        "partOf",
        "responsibleFor",
        "responsibleForAssurance",
    }
)
P1_QUALIFICATION_DIMENSIONS = (
    "semantic_modality",
    "epistemic_posture",
    "normative_posture",
    "validity",
    "scope",
    "completeness",
    "reliance",
    "authority_mode",
)


class ShadowSemanticSubstrateError(RuntimeError):
    """Raised when a shadow semantic projection violates the frozen P1 contract."""


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
        raise ShadowSemanticSubstrateError(f"{label} must not be empty")
    return text


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShadowSemanticSubstrateError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ShadowSemanticSubstrateError(f"{label} must be a list")
    return value


def _context_id(source_tree: str) -> str:
    return f"context:git-tree:{source_tree}"


def _record_id(prefix: str, value: object) -> str:
    return f"{prefix}:{_digest(value)[:32]}"


def _semantic_fingerprint_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    source = _object(payload.get("source"), "shadow source")
    return {
        "schema_version": payload.get("schema_version"),
        "model_version": payload.get("model_version"),
        "authority_mode": payload.get("authority_mode"),
        "source": {
            "profile_id": source.get("profile_id"),
            "source_commit": source.get("source_commit"),
            "source_tree": source.get("source_tree"),
            "snapshot_id": source.get("snapshot_id"),
            "architecture_memory_schema_version": source.get(
                "architecture_memory_schema_version"
            ),
            "evidence_ref_count": source.get("evidence_ref_count"),
        },
        "context": payload.get("context"),
        "vocabulary": payload.get("vocabulary"),
        "objects": payload.get("objects"),
        "occurrences": payload.get("occurrences"),
        "assertions": payload.get("assertions"),
        "reliance": payload.get("reliance"),
        "summary": payload.get("summary"),
    }


def _projection_fingerprint_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"semantic_fingerprint", "projection_fingerprint"}
    }


def _source_binding(family: str, row_id: str, projection_key: str) -> dict[str, str]:
    return {
        "family": family,
        "source_record_id": row_id,
        "projection_key": projection_key,
    }


def _source_qualifications(row: Mapping[str, Any]) -> dict[str, str]:
    knowledge_state = _text(row.get("knowledge_state"), "source knowledge_state")
    if knowledge_state not in _KNOWLEDGE_STATE_TO_EPISTEMIC:
        raise ShadowSemanticSubstrateError(
            f"unsupported source knowledge_state: {knowledge_state}"
        )
    confidence = _text(row.get("confidence"), "source confidence")
    return {
        "semantic_modality": "source-unspecified",
        "epistemic_posture": _KNOWLEDGE_STATE_TO_EPISTEMIC[knowledge_state],
        "source_knowledge_state": knowledge_state,
        "confidence": confidence,
        "normative_posture": "not-specified",
        "validity": "source-context-bound",
        "scope": "phase1-architecture-memory",
        "completeness": "bounded-source-projection",
        "reliance": "shadow-only",
        "authority_mode": AUTHORITY_MODE,
    }


def _subject_ref(semantic_id: str) -> dict[str, str]:
    return {"kind": "object-ref", "ref": semantic_id}


def _subject_term(term: str) -> dict[str, str]:
    return {"kind": "source-term", "term": _text(term, "subject term")}


def _object_ref(semantic_id: str) -> dict[str, str]:
    return {"kind": "object-ref", "ref": semantic_id}


def _value(value: object) -> dict[str, object]:
    return {"kind": "value", "value": value}


def _make_assertion(
    *,
    context_id: str,
    family: str,
    source_row: Mapping[str, Any],
    projection_key: str,
    subject: dict[str, str],
    predicate: str,
    object_value: dict[str, object] | dict[str, str],
    allowed_evidence_refs: frozenset[str],
) -> dict[str, Any]:
    source_row_id = _text(source_row.get("id"), f"{family} row id")
    evidence_refs = sorted(
        _text(ref, f"{family}:{source_row_id} evidence ref")
        for ref in _array(source_row.get("evidence_refs"), f"{family}:{source_row_id} evidence_refs")
    )
    unknown_refs = sorted(set(evidence_refs) - set(allowed_evidence_refs))
    if unknown_refs:
        raise ShadowSemanticSubstrateError(
            f"{family}:{source_row_id} references evidence outside the verified snapshot: "
            + ", ".join(unknown_refs)
        )

    statement = {
        "subject": subject,
        "predicate": _text(predicate, "predicate"),
        "object": object_value,
    }
    statement_key = f"statement:{_digest(statement)}"
    qualifications = _source_qualifications(source_row)
    source_binding = _source_binding(family, source_row_id, projection_key)
    exact_identity = {
        "statement_key": statement_key,
        "context_ref": context_id,
        "source_binding": source_binding,
        "qualifications": qualifications,
        "evidence_refs": evidence_refs,
        "rationale": _text(source_row.get("rationale"), f"{family}:{source_row_id} rationale"),
    }
    return {
        "record_id": _record_id("assertion", exact_identity),
        "statement_key": statement_key,
        "source_binding": source_binding,
        "subject": subject,
        "predicate": statement["predicate"],
        "object": object_value,
        "context_ref": context_id,
        "qualifications": qualifications,
        "evidence_refs": evidence_refs,
        "rationale": exact_identity["rationale"],
    }


def _make_context_object(snapshot: VerifiedPhase1Snapshot) -> dict[str, Any]:
    semantic_id = _context_id(snapshot.source_tree)
    source_binding = {
        "family": "verified-phase1-snapshot",
        "source_record_id": snapshot.snapshot_id,
    }
    return {
        "record_id": _record_id(
            "object-record",
            {
                "semantic_id": semantic_id,
                "source_binding": source_binding,
                "source_commit": snapshot.source_commit,
                "source_tree": snapshot.source_tree,
            },
        ),
        "semantic_id": semantic_id,
        "identity_source": "trusted-git-tree-context",
        "types": ["Context", "RepositorySnapshot"],
        "roles": ["SourceContext"],
        "context_ref": None,
        "source_binding": source_binding,
        "source_facets": {},
        "source_epistemic_posture": "observed",
        "authority_mode": AUTHORITY_MODE,
    }


def _make_architecture_object(
    node: Mapping[str, Any],
    *,
    context_id: str,
) -> dict[str, Any]:
    semantic_id = _text(node.get("id"), "architecture node id")
    source_binding = {
        "family": _ARCHITECTURE_FAMILY,
        "source_record_id": semantic_id,
    }
    qualifications = _source_qualifications(node)
    return {
        "record_id": _record_id(
            "object-record",
            {
                "semantic_id": semantic_id,
                "context_ref": context_id,
                "source_binding": source_binding,
            },
        ),
        "semantic_id": semantic_id,
        "identity_source": "phase1-architecture-node-id",
        "types": ["SystemElement"],
        "roles": ["ArchitectureElement"],
        "context_ref": context_id,
        "source_binding": source_binding,
        "source_facets": {
            "kind": _text(node.get("kind"), f"architecture node {semantic_id} kind"),
        },
        "source_epistemic_posture": qualifications["epistemic_posture"],
        "authority_mode": AUTHORITY_MODE,
    }


def _sorted_source_rows(memory: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    rows = [
        _object(row, f"architecture memory {family} row")
        for row in _array(memory.get(family), f"architecture memory {family}")
    ]
    return sorted(rows, key=lambda row: _text(row.get("id"), f"{family} row id"))


def _architecture_assertions(
    nodes: list[dict[str, Any]],
    *,
    context_id: str,
    evidence_refs: frozenset[str],
) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    semantic_ids = {_text(node.get("id"), "architecture node id") for node in nodes}
    for node in nodes:
        node_id = _text(node.get("id"), "architecture node id")
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family=_ARCHITECTURE_FAMILY,
                source_row=node,
                projection_key="name",
                subject=_subject_ref(node_id),
                predicate="hasName",
                object_value=_value(_text(node.get("name"), f"architecture node {node_id} name")),
                allowed_evidence_refs=evidence_refs,
            )
        )
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family=_ARCHITECTURE_FAMILY,
                source_row=node,
                projection_key="source-kind",
                subject=_subject_ref(node_id),
                predicate="hasSourceKind",
                object_value=_value(_text(node.get("kind"), f"architecture node {node_id} kind")),
                allowed_evidence_refs=evidence_refs,
            )
        )
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family=_ARCHITECTURE_FAMILY,
                source_row=node,
                projection_key="responsibility",
                subject=_subject_ref(node_id),
                predicate="hasResponsibility",
                object_value=_value(
                    _text(node.get("responsibility"), f"architecture node {node_id} responsibility")
                ),
                allowed_evidence_refs=evidence_refs,
            )
        )
        parent_id = str(node.get("parent_id") or "").strip()
        if parent_id:
            if parent_id not in semantic_ids:
                raise ShadowSemanticSubstrateError(
                    f"architecture node {node_id} references unknown parent: {parent_id}"
                )
            assertions.append(
                _make_assertion(
                    context_id=context_id,
                    family=_ARCHITECTURE_FAMILY,
                    source_row=node,
                    projection_key="parent",
                    subject=_subject_ref(node_id),
                    predicate="partOf",
                    object_value=_object_ref(parent_id),
                    allowed_evidence_refs=evidence_refs,
                )
            )
        non_responsibilities = sorted(
            _text(value, f"architecture node {node_id} non-responsibility")
            for value in _array(
                node.get("non_responsibilities"),
                f"architecture node {node_id} non_responsibilities",
            )
        )
        for value in non_responsibilities:
            assertions.append(
                _make_assertion(
                    context_id=context_id,
                    family=_ARCHITECTURE_FAMILY,
                    source_row=node,
                    projection_key=f"non-responsibility:{_digest(value)[:16]}",
                    subject=_subject_ref(node_id),
                    predicate="excludesResponsibility",
                    object_value=_value(value),
                    allowed_evidence_refs=evidence_refs,
                )
            )
    return assertions


def _responsibility_assertions(
    rows: list[dict[str, Any]],
    *,
    context_id: str,
    evidence_refs: frozenset[str],
) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    for row in rows:
        row_id = _text(row.get("id"), "responsibility row id")
        owner = _text(row.get("owner"), f"responsibility {row_id} owner")
        scope_term = _text(row.get("subject"), f"responsibility {row_id} subject")
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family="module_responsibility_map",
                source_row=row,
                projection_key="responsibility",
                subject=_subject_term(owner),
                predicate="responsibleFor",
                object_value=_value(
                    {
                        "scope_term": scope_term,
                        "responsibility": _text(
                            row.get("responsibility"),
                            f"responsibility {row_id} responsibility",
                        ),
                    }
                ),
                allowed_evidence_refs=evidence_refs,
            )
        )
        for value in sorted(
            _text(item, f"responsibility {row_id} non-responsibility")
            for item in _array(
                row.get("non_responsibilities"),
                f"responsibility {row_id} non_responsibilities",
            )
        ):
            assertions.append(
                _make_assertion(
                    context_id=context_id,
                    family="module_responsibility_map",
                    source_row=row,
                    projection_key=f"non-responsibility:{_digest(value)[:16]}",
                    subject=_subject_term(owner),
                    predicate="excludesResponsibility",
                    object_value=_value(
                        {
                            "scope_term": scope_term,
                            "responsibility": value,
                        }
                    ),
                    allowed_evidence_refs=evidence_refs,
                )
            )
    return assertions


def _statement_assertions(
    rows: list[dict[str, Any]],
    *,
    family: str,
    predicate: str,
    context_id: str,
    evidence_refs: frozenset[str],
) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    for row in rows:
        row_id = _text(row.get("id"), f"{family} row id")
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family=family,
                source_row=row,
                projection_key="statement",
                subject=_subject_term(_text(row.get("subject"), f"{family}:{row_id} subject")),
                predicate=predicate,
                object_value=_value(_text(row.get("statement"), f"{family}:{row_id} statement")),
                allowed_evidence_refs=evidence_refs,
            )
        )
    return assertions


def _assurance_assertions(
    rows: list[dict[str, Any]],
    *,
    context_id: str,
    evidence_refs: frozenset[str],
) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    for row in rows:
        row_id = _text(row.get("id"), "assurance row id")
        assertions.append(
            _make_assertion(
                context_id=context_id,
                family="validation_assurance_ownership",
                source_row=row,
                projection_key="assurance-responsibility",
                subject=_subject_term(_text(row.get("owner"), f"assurance {row_id} owner")),
                predicate="responsibleForAssurance",
                object_value=_value(
                    {
                        "scope_term": _text(row.get("subject"), f"assurance {row_id} subject"),
                        "responsibility": _text(
                            row.get("responsibility"),
                            f"assurance {row_id} responsibility",
                        ),
                    }
                ),
                allowed_evidence_refs=evidence_refs,
            )
        )
    return assertions


def compile_phase1_architecture_shadow(snapshot: VerifiedPhase1Snapshot) -> dict[str, Any]:
    """Compile one fully verified Phase-1 snapshot into deterministic shadow knowledge.

    The function performs no source scan, writes nothing, and creates no semantic
    authority.  The only durable semantic IDs allocated from the Phase-1 slice are
    already-existing architecture node IDs plus a trusted Git-tree Context ID.
    """
    if not isinstance(snapshot, VerifiedPhase1Snapshot):
        raise ShadowSemanticSubstrateError(
            "shadow compiler requires an internally verified Phase1 snapshot"
        )
    memory = _object(snapshot.architecture_memory, "verified architecture memory")
    context_id = _context_id(snapshot.source_tree)

    architecture_nodes = _sorted_source_rows(memory, _ARCHITECTURE_FAMILY)
    objects = [_make_context_object(snapshot)] + [
        _make_architecture_object(node, context_id=context_id)
        for node in architecture_nodes
    ]
    objects = sorted(objects, key=lambda row: row["record_id"])

    assertions: list[dict[str, Any]] = []
    assertions.extend(
        _architecture_assertions(
            architecture_nodes,
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions.extend(
        _responsibility_assertions(
            _sorted_source_rows(memory, "module_responsibility_map"),
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions.extend(
        _statement_assertions(
            _sorted_source_rows(memory, "implementation_intent_summary"),
            family="implementation_intent_summary",
            predicate="hasImplementationIntent",
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions.extend(
        _assurance_assertions(
            _sorted_source_rows(memory, "validation_assurance_ownership"),
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions.extend(
        _statement_assertions(
            _sorted_source_rows(memory, "constraints"),
            family="constraints",
            predicate="hasConstraint",
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions.extend(
        _statement_assertions(
            _sorted_source_rows(memory, "unknowns"),
            family="unknowns",
            predicate="hasUnresolvedStatement",
            context_id=context_id,
            evidence_refs=snapshot.evidence_refs,
        )
    )
    assertions = sorted(assertions, key=lambda row: row["record_id"])

    source_output_digests = _object(
        snapshot.reconstruction_report.get("output_digests"),
        "verified reconstruction output digests",
    )
    predicates = sorted({str(row["predicate"]) for row in assertions})
    source_record_count = sum(
        len(_array(memory.get(family), f"architecture memory {family}"))
        for family in _SOURCE_FAMILIES
    )
    projected_source_records = {
        (
            str(row["source_binding"]["family"]),
            str(row["source_binding"]["source_record_id"]),
        )
        for row in assertions
    }
    if len(projected_source_records) != source_record_count:
        raise ShadowSemanticSubstrateError(
            "shadow compiler did not project every Phase1 source record exactly into the coverage denominator"
        )
    projected_evidence_refs = {
        ref for row in assertions for ref in row["evidence_refs"]
    }
    semantic_object_ids = sorted(
        str(row["semantic_id"])
        for row in objects
        if row["identity_source"] == "phase1-architecture-node-id"
    )
    payload: dict[str, Any] = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "compiler_version": COMPILER_VERSION,
        "status": SHADOW_STATUS,
        "authority_mode": AUTHORITY_MODE,
        "source": {
            "compiler_input": "verified-phase1-snapshot",
            "profile_id": _text(memory.get("profile_id"), "architecture memory profile_id"),
            "source_commit": snapshot.source_commit,
            "source_tree": snapshot.source_tree,
            "snapshot_id": snapshot.snapshot_id,
            "architecture_memory_schema_version": _text(
                memory.get("schema_version"),
                "architecture memory schema_version",
            ),
            "source_output_digests": dict(sorted(source_output_digests.items())),
            "evidence_ref_count": len(snapshot.evidence_refs),
        },
        "context": {
            "context_id": context_id,
            "kind": "repository-snapshot",
            "source_commit": snapshot.source_commit,
            "source_tree": snapshot.source_tree,
            "snapshot_id": snapshot.snapshot_id,
        },
        "vocabulary": {
            "general_object_types": sorted(P1_OBJECT_TYPES),
            "general_roles": sorted(P1_ROLES),
            "predicates": predicates,
            "qualification_dimensions": list(P1_QUALIFICATION_DIMENSIONS),
            "profile_extension_policy": "source facets may preserve profile vocabulary but the meta-kernel requires no WFF term",
        },
        "objects": objects,
        "occurrences": [],
        "assertions": assertions,
        "reliance": {
            "claim_ceiling": _text(memory.get("claim_ceiling"), "architecture memory claim_ceiling"),
            "absence_posture": "index-or-projection-miss-does-not-prove-absence",
            "authority_posture": "shadow-output-cannot-establish-or-revise-source-truth",
            "authority_mode": AUTHORITY_MODE,
        },
        "summary": {
            "architecture_semantic_object_count": len(semantic_object_ids),
            "object_record_count": len(objects),
            "occurrence_record_count": 0,
            "assertion_record_count": len(assertions),
            "source_family_count": len(_SOURCE_FAMILIES),
            "source_record_count": source_record_count,
            "projected_source_record_count": len(projected_source_records),
            "source_evidence_ref_count": len(snapshot.evidence_refs),
            "projected_evidence_ref_count": len(projected_evidence_refs),
            "source_semantic_ids": semantic_object_ids,
        },
    }
    payload["semantic_fingerprint"] = _digest(_semantic_fingerprint_basis(payload))
    payload["projection_fingerprint"] = _digest(_projection_fingerprint_basis(payload))
    return validate_shadow_payload(payload, allowed_evidence_refs=snapshot.evidence_refs)


def validate_shadow_payload(
    payload: Mapping[str, Any],
    *,
    allowed_evidence_refs: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Validate the P1 shadow authority and identity invariants."""
    if payload.get("schema_version") != SHADOW_SCHEMA_VERSION:
        raise ShadowSemanticSubstrateError("unsupported shadow schema version")
    if payload.get("model_version") != MODEL_VERSION:
        raise ShadowSemanticSubstrateError("unsupported Engineering Knowledge Model version")
    if payload.get("compiler_version") != COMPILER_VERSION:
        raise ShadowSemanticSubstrateError("unexpected shadow compiler version")
    if payload.get("status") != SHADOW_STATUS:
        raise ShadowSemanticSubstrateError("unexpected shadow status")
    if payload.get("authority_mode") != AUTHORITY_MODE:
        raise ShadowSemanticSubstrateError("shadow authority mode must fail closed")

    source = _object(payload.get("source"), "shadow source")
    if source.get("compiler_input") != "verified-phase1-snapshot":
        raise ShadowSemanticSubstrateError("shadow source must be a verified Phase1 snapshot")
    source_tree = _text(source.get("source_tree"), "shadow source tree")
    context = _object(payload.get("context"), "shadow context")
    context_id = _text(context.get("context_id"), "shadow context id")
    if context_id != _context_id(source_tree):
        raise ShadowSemanticSubstrateError("shadow Context identity does not match source tree")
    if context.get("source_tree") != source_tree or context.get("source_commit") != source.get("source_commit"):
        raise ShadowSemanticSubstrateError("shadow Context source identity diverges")

    vocabulary = _object(payload.get("vocabulary"), "shadow vocabulary")
    if set(_array(vocabulary.get("general_object_types"), "shadow object vocabulary")) != set(P1_OBJECT_TYPES):
        raise ShadowSemanticSubstrateError("shadow Object vocabulary drifted from the governed P1 model")
    if set(_array(vocabulary.get("general_roles"), "shadow role vocabulary")) != set(P1_ROLES):
        raise ShadowSemanticSubstrateError("shadow role vocabulary drifted from the governed P1 model")
    if set(_array(vocabulary.get("predicates"), "shadow predicate vocabulary")) != set(P1_PREDICATES):
        raise ShadowSemanticSubstrateError("shadow predicate vocabulary drifted from the governed P1 model")
    if tuple(_array(vocabulary.get("qualification_dimensions"), "shadow qualification vocabulary")) != P1_QUALIFICATION_DIMENSIONS:
        raise ShadowSemanticSubstrateError("shadow qualification vocabulary drifted from the governed P1 model")

    objects = [_object(row, "shadow object") for row in _array(payload.get("objects"), "shadow objects")]
    semantic_ids: set[str] = set()
    object_record_ids: set[str] = set()
    context_objects = 0
    for row in objects:
        semantic_id = _text(row.get("semantic_id"), "shadow object semantic_id")
        record_id = _text(row.get("record_id"), "shadow object record_id")
        if semantic_id in semantic_ids:
            raise ShadowSemanticSubstrateError(f"duplicate shadow semantic_id: {semantic_id}")
        if record_id in object_record_ids:
            raise ShadowSemanticSubstrateError(f"duplicate shadow object record_id: {record_id}")
        semantic_ids.add(semantic_id)
        object_record_ids.add(record_id)
        if row.get("authority_mode") != AUTHORITY_MODE:
            raise ShadowSemanticSubstrateError("shadow Object escaped non-authoritative mode")
        object_types = set(_array(row.get("types"), "shadow Object types"))
        object_roles = set(_array(row.get("roles"), "shadow Object roles"))
        if not object_types or not object_types <= set(P1_OBJECT_TYPES):
            raise ShadowSemanticSubstrateError("shadow Object uses an ungoverned type")
        if not object_roles or not object_roles <= set(P1_ROLES):
            raise ShadowSemanticSubstrateError("shadow Object uses an ungoverned role")
        source_facets = _object(row.get("source_facets"), "shadow Object source_facets")
        if set(source_facets) - {"kind"}:
            raise ShadowSemanticSubstrateError("shadow Object source facets became an arbitrary metadata bag")
        source_binding = _object(row.get("source_binding"), "shadow Object source_binding")
        source_family = _text(source_binding.get("family"), "shadow Object source family")
        source_record_id = _text(
            source_binding.get("source_record_id"),
            "shadow Object source record id",
        )
        identity_source = _text(row.get("identity_source"), "shadow Object identity_source")
        if semantic_id == context_id:
            context_objects += 1
            if object_types != {"Context", "RepositorySnapshot"} or object_roles != {"SourceContext"}:
                raise ShadowSemanticSubstrateError("base Context object has an invalid governed type/role combination")
            if identity_source != "trusted-git-tree-context" or source_family != "verified-phase1-snapshot":
                raise ShadowSemanticSubstrateError("base Context object has an invalid identity/source binding")
            if row.get("context_ref") is not None:
                raise ShadowSemanticSubstrateError("base Context object cannot context-reference a generated peer")
        else:
            if object_types != {"SystemElement"} or object_roles != {"ArchitectureElement"}:
                raise ShadowSemanticSubstrateError("Architecture object has an invalid governed type/role combination")
            if identity_source != "phase1-architecture-node-id":
                raise ShadowSemanticSubstrateError("Architecture object semantic identity was not preserved from Phase1")
            if source_family != _ARCHITECTURE_FAMILY or source_record_id != semantic_id:
                raise ShadowSemanticSubstrateError("Architecture object source binding diverges from its preserved semantic ID")
            if row.get("context_ref") != context_id:
                raise ShadowSemanticSubstrateError("Architecture object escaped the verified source Context")
            _text(source_facets.get("kind"), "Architecture object source kind")
    if context_objects != 1:
        raise ShadowSemanticSubstrateError("shadow must contain exactly one base Context object")

    occurrences = _array(payload.get("occurrences"), "shadow occurrences")
    if occurrences:
        raise ShadowSemanticSubstrateError(
            "P1 Architecture shadow does not authorize an unconstrained Occurrence vocabulary"
        )

    assertions = [
        _object(row, "shadow assertion")
        for row in _array(payload.get("assertions"), "shadow assertions")
    ]
    assertion_ids: set[str] = set()
    allowed_refs = set(allowed_evidence_refs) if allowed_evidence_refs is not None else None
    for row in assertions:
        record_id = _text(row.get("record_id"), "shadow assertion record_id")
        if record_id in assertion_ids:
            raise ShadowSemanticSubstrateError(f"duplicate shadow assertion record_id: {record_id}")
        assertion_ids.add(record_id)
        if row.get("context_ref") != context_id:
            raise ShadowSemanticSubstrateError("shadow Assertion escaped source Context")
        qualifications = _object(row.get("qualifications"), "shadow assertion qualifications")
        if qualifications.get("authority_mode") != AUTHORITY_MODE or qualifications.get("reliance") != "shadow-only":
            raise ShadowSemanticSubstrateError("shadow Assertion escaped non-authoritative reliance")
        predicate = _text(row.get("predicate"), "shadow assertion predicate")
        if predicate not in P1_PREDICATES:
            raise ShadowSemanticSubstrateError(f"ungoverned P1 predicate: {predicate}")
        source_binding = _object(row.get("source_binding"), "shadow assertion source_binding")
        family = _text(source_binding.get("family"), "shadow assertion source family")
        _text(source_binding.get("source_record_id"), "shadow assertion source record id")
        _text(source_binding.get("projection_key"), "shadow assertion projection key")
        if family not in _SOURCE_FAMILIES:
            raise ShadowSemanticSubstrateError(f"unsupported P1 source family: {family}")
        subject = _object(row.get("subject"), "shadow assertion subject")
        if subject.get("kind") == "object-ref":
            if _text(subject.get("ref"), "shadow assertion subject ref") not in semantic_ids:
                raise ShadowSemanticSubstrateError("shadow Assertion references an unknown subject Object")
        elif subject.get("kind") == "source-term":
            _text(subject.get("term"), "shadow assertion subject term")
        else:
            raise ShadowSemanticSubstrateError("shadow Assertion subject kind is unsupported")
        object_value = _object(row.get("object"), "shadow assertion object")
        if object_value.get("kind") == "object-ref":
            if _text(object_value.get("ref"), "shadow assertion object ref") not in semantic_ids:
                raise ShadowSemanticSubstrateError("shadow Assertion references an unknown Object")
        elif object_value.get("kind") == "value":
            if "value" not in object_value:
                raise ShadowSemanticSubstrateError("shadow Assertion value is missing")
        else:
            raise ShadowSemanticSubstrateError("shadow Assertion object kind is unsupported")
        refs = [
            _text(ref, "shadow assertion evidence ref")
            for ref in _array(row.get("evidence_refs"), "shadow assertion evidence refs")
        ]
        if len(refs) != len(set(refs)):
            raise ShadowSemanticSubstrateError("shadow Assertion contains duplicate evidence refs")
        if allowed_refs is not None and not set(refs) <= allowed_refs:
            raise ShadowSemanticSubstrateError("shadow Assertion contains unverified evidence refs")
        if family == "unknowns" and qualifications.get("epistemic_posture") != "unknown":
            raise ShadowSemanticSubstrateError("source unknown was silently upgraded")

    reliance = _object(payload.get("reliance"), "shadow reliance")
    if reliance.get("authority_mode") != AUTHORITY_MODE:
        raise ShadowSemanticSubstrateError("shadow reliance escaped non-authoritative mode")
    _text(reliance.get("claim_ceiling"), "shadow claim ceiling")

    summary = _object(payload.get("summary"), "shadow summary")
    architecture_ids = [
        str(row["semantic_id"])
        for row in objects
        if row.get("identity_source") == "phase1-architecture-node-id"
    ]
    if summary.get("architecture_semantic_object_count") != len(architecture_ids):
        raise ShadowSemanticSubstrateError("shadow architecture semantic object count mismatch")
    if summary.get("object_record_count") != len(objects):
        raise ShadowSemanticSubstrateError("shadow object count mismatch")
    if summary.get("occurrence_record_count") != len(occurrences):
        raise ShadowSemanticSubstrateError("shadow occurrence count mismatch")
    if summary.get("assertion_record_count") != len(assertions):
        raise ShadowSemanticSubstrateError("shadow assertion count mismatch")
    projected_source_records = {
        (
            str(row["source_binding"]["family"]),
            str(row["source_binding"]["source_record_id"]),
        )
        for row in assertions
    }
    if summary.get("projected_source_record_count") != len(projected_source_records):
        raise ShadowSemanticSubstrateError("shadow projected source-record count mismatch")
    if summary.get("source_record_count") != summary.get("projected_source_record_count"):
        raise ShadowSemanticSubstrateError("shadow source-record coverage is incomplete")
    projected_evidence_refs = {
        ref for row in assertions for ref in row["evidence_refs"]
    }
    if summary.get("projected_evidence_ref_count") != len(projected_evidence_refs):
        raise ShadowSemanticSubstrateError("shadow projected evidence-ref count mismatch")
    if summary.get("source_evidence_ref_count") != source.get("evidence_ref_count"):
        raise ShadowSemanticSubstrateError("shadow source evidence-ref denominator mismatch")
    if int(summary.get("projected_evidence_ref_count", -1)) > int(summary.get("source_evidence_ref_count", -1)):
        raise ShadowSemanticSubstrateError("shadow projected evidence exceeds source evidence denominator")
    if sorted(summary.get("source_semantic_ids", [])) != sorted(architecture_ids):
        raise ShadowSemanticSubstrateError("shadow source semantic IDs were reminted or lost")

    expected_semantic_fingerprint = _digest(_semantic_fingerprint_basis(payload))
    if payload.get("semantic_fingerprint") != expected_semantic_fingerprint:
        raise ShadowSemanticSubstrateError("shadow semantic fingerprint mismatch")
    expected_projection_fingerprint = _digest(_projection_fingerprint_basis(payload))
    if payload.get("projection_fingerprint") != expected_projection_fingerprint:
        raise ShadowSemanticSubstrateError("shadow projection fingerprint mismatch")
    return dict(payload)


def shadow_output_path(repository_root: str | Path, source_tree: str) -> Path:
    root = Path(repository_root).expanduser().resolve(strict=False)
    tree = _text(source_tree, "source tree")
    return root / ".EKRI" / "shadow" / tree / OUTPUT_FILENAME


def persist_shadow_payload(
    repository_root: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Persist rebuildable shadow state without entering any v0.9 authority root."""
    validated = validate_shadow_payload(payload)
    source_tree = _text(
        _object(validated.get("source"), "shadow source").get("source_tree"),
        "shadow source tree",
    )
    root = Path(repository_root).expanduser().resolve(strict=False)
    output = shadow_output_path(root, source_tree)
    current = root
    for component in (".EKRI", "shadow", source_tree):
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ShadowSemanticSubstrateError(
                    f"shadow output directory is unsafe: {current}"
                )
        else:
            current.mkdir()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise ShadowSemanticSubstrateError(f"shadow output file is unsafe: {output}")
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise ShadowSemanticSubstrateError(
                f"shadow temporary output is unsafe: {temporary}"
            )
        temporary.unlink()
    temporary.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def run_phase1_architecture_shadow(
    repository_root: str | Path,
    *,
    source_tree: str,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Verify current Phase-1 authority, compile shadow state, and optionally persist it."""
    root = Path(repository_root).expanduser().resolve(strict=False)
    snapshot = verify_phase1_snapshot(root, source_tree=source_tree)
    payload = compile_phase1_architecture_shadow(snapshot)
    output = persist_shadow_payload(root, payload) if write_outputs else None
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": SHADOW_STATUS,
        "authority_mode": AUTHORITY_MODE,
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "semantic_fingerprint": payload["semantic_fingerprint"],
        "projection_fingerprint": payload["projection_fingerprint"],
        "object_record_count": payload["summary"]["object_record_count"],
        "occurrence_record_count": payload["summary"]["occurrence_record_count"],
        "assertion_record_count": payload["summary"]["assertion_record_count"],
        "output": str(output) if output is not None else "",
        "claim_ceiling": (
            "This run proves only a deterministic read-only shadow projection of an already-verified "
            "Phase-1 Architecture Memory snapshot. It does not make the shadow substrate authoritative, "
            "prove Architecture round-trip parity, migrate Capability queries, prove Flow, or authorize "
            "any EKRI/WFF semantic cutover."
        ),
    }
