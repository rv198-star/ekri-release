"""EKRI v1.0 P2 derived Architecture View and round-trip parity proof.

P2 consumes the P1 non-authoritative shadow substrate.  It does not change the
current Architecture Memory writer or promote the shadow/view to semantic authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase1_snapshot import VerifiedPhase1Snapshot, verify_phase1_snapshot
from .shadow_semantic_substrate import (
    AUTHORITY_MODE as SHADOW_AUTHORITY_MODE,
    compile_phase1_architecture_shadow,
    persist_shadow_payload,
    shadow_output_path,
    validate_shadow_payload,
)


ARCHITECTURE_VIEW_SCHEMA_VERSION = "ekri.architecture-view.v1"
PARITY_REPORT_SCHEMA_VERSION = "ekri.architecture-roundtrip-parity.v1"
VIEW_GENERATOR_VERSION = "ekri.architecture-view-generator.v0.1"
VIEW_STATUS = "derived-shadow-view"
VIEW_AUTHORITY_MODE = "derived-non-authoritative"
PARITY_STATUS = "architecture-roundtrip-evaluated"
PARITY_PASS = "pass"
PARITY_FAIL = "fail"
VIEW_FILENAME = "architecture-view.json"
PARITY_FILENAME = "architecture-roundtrip-parity.json"

_FAMILIES = (
    "system_architecture_tree",
    "module_responsibility_map",
    "implementation_intent_summary",
    "validation_assurance_ownership",
    "constraints",
    "unknowns",
)


class ArchitectureRoundTripError(RuntimeError):
    """Raised when a derived Architecture View violates the P2 contract."""


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
        raise ArchitectureRoundTripError(f"{label} must not be empty")
    return text


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArchitectureRoundTripError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArchitectureRoundTripError(f"{label} must be a list")
    return value


def _common_source_row(row: Mapping[str, Any], family: str) -> dict[str, Any]:
    row_id = _text(row.get("id"), f"{family} id")
    evidence_refs = sorted(
        _text(ref, f"{family}:{row_id} evidence ref")
        for ref in _array(row.get("evidence_refs"), f"{family}:{row_id} evidence_refs")
    )
    return {
        "id": row_id,
        "knowledge_state": _text(row.get("knowledge_state"), f"{family}:{row_id} knowledge_state"),
        "confidence": _text(row.get("confidence"), f"{family}:{row_id} confidence"),
        "rationale": _text(row.get("rationale"), f"{family}:{row_id} rationale"),
        "evidence_refs": evidence_refs,
    }


def _source_semantic_content(snapshot: VerifiedPhase1Snapshot) -> dict[str, Any]:
    """Normalize current Phase-1 semantic content independently of shadow reconstruction."""
    memory = _object(snapshot.architecture_memory, "verified Architecture Memory")

    architecture_rows: list[dict[str, Any]] = []
    for raw in _array(memory.get("system_architecture_tree"), "system_architecture_tree"):
        row = _object(raw, "system_architecture_tree row")
        normalized = _common_source_row(row, "system_architecture_tree")
        normalized.update(
            {
                "name": _text(row.get("name"), f"architecture:{normalized['id']} name"),
                "kind": _text(row.get("kind"), f"architecture:{normalized['id']} kind"),
                "parent_id": str(row.get("parent_id") or "").strip() or None,
                "responsibility": _text(
                    row.get("responsibility"),
                    f"architecture:{normalized['id']} responsibility",
                ),
                "non_responsibilities": sorted(
                    _text(value, f"architecture:{normalized['id']} non-responsibility")
                    for value in _array(
                        row.get("non_responsibilities"),
                        f"architecture:{normalized['id']} non_responsibilities",
                    )
                ),
            }
        )
        architecture_rows.append(normalized)

    responsibility_rows: list[dict[str, Any]] = []
    for raw in _array(memory.get("module_responsibility_map"), "module_responsibility_map"):
        row = _object(raw, "module_responsibility_map row")
        normalized = _common_source_row(row, "module_responsibility_map")
        normalized.update(
            {
                "subject": _text(row.get("subject"), f"responsibility:{normalized['id']} subject"),
                "owner": _text(row.get("owner"), f"responsibility:{normalized['id']} owner"),
                "responsibility": _text(
                    row.get("responsibility"),
                    f"responsibility:{normalized['id']} responsibility",
                ),
                "non_responsibilities": sorted(
                    _text(value, f"responsibility:{normalized['id']} non-responsibility")
                    for value in _array(
                        row.get("non_responsibilities"),
                        f"responsibility:{normalized['id']} non_responsibilities",
                    )
                ),
            }
        )
        responsibility_rows.append(normalized)

    def statement_rows(family: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in _array(memory.get(family), family):
            row = _object(raw, f"{family} row")
            normalized = _common_source_row(row, family)
            normalized.update(
                {
                    "subject": _text(row.get("subject"), f"{family}:{normalized['id']} subject"),
                    "statement": _text(row.get("statement"), f"{family}:{normalized['id']} statement"),
                }
            )
            rows.append(normalized)
        return sorted(rows, key=lambda item: item["id"])

    assurance_rows: list[dict[str, Any]] = []
    for raw in _array(
        memory.get("validation_assurance_ownership"),
        "validation_assurance_ownership",
    ):
        row = _object(raw, "validation_assurance_ownership row")
        normalized = _common_source_row(row, "validation_assurance_ownership")
        normalized.update(
            {
                "subject": _text(row.get("subject"), f"assurance:{normalized['id']} subject"),
                "owner": _text(row.get("owner"), f"assurance:{normalized['id']} owner"),
                "responsibility": _text(
                    row.get("responsibility"),
                    f"assurance:{normalized['id']} responsibility",
                ),
            }
        )
        assurance_rows.append(normalized)

    return {
        "system_architecture_tree": sorted(architecture_rows, key=lambda item: item["id"]),
        "module_responsibility_map": sorted(responsibility_rows, key=lambda item: item["id"]),
        "implementation_intent_summary": statement_rows("implementation_intent_summary"),
        "validation_assurance_ownership": sorted(assurance_rows, key=lambda item: item["id"]),
        "constraints": statement_rows("constraints"),
        "unknowns": statement_rows("unknowns"),
        "claim_ceiling": _text(memory.get("claim_ceiling"), "Architecture Memory claim_ceiling"),
    }


def _view_source_from_snapshot(snapshot: VerifiedPhase1Snapshot) -> dict[str, Any]:
    memory = _object(snapshot.architecture_memory, "verified Architecture Memory")
    return {
        "profile_id": _text(memory.get("profile_id"), "Architecture Memory profile_id"),
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "snapshot_id": snapshot.snapshot_id,
        "architecture_memory_schema_version": _text(
            memory.get("schema_version"),
            "Architecture Memory schema_version",
        ),
        "evidence_ref_count": len(snapshot.evidence_refs),
    }


def _view_semantic_fingerprint(
    source: Mapping[str, Any],
    semantic_content: Mapping[str, Any],
) -> str:
    return _digest(
        {
            "source": source,
            "semantic_content": semantic_content,
            "semantic_modality_policy": "source-preserved",
            "normative_posture_policy": "source-unspecified",
        }
    )


def build_source_architecture_baseline_view(
    snapshot: VerifiedPhase1Snapshot,
) -> dict[str, Any]:
    """Build a direct normalized baseline for parity comparison only."""
    if not isinstance(snapshot, VerifiedPhase1Snapshot):
        raise ArchitectureRoundTripError("source baseline requires a VerifiedPhase1Snapshot")
    source = _view_source_from_snapshot(snapshot)
    semantic_content = _source_semantic_content(snapshot)
    payload: dict[str, Any] = {
        "schema_version": ARCHITECTURE_VIEW_SCHEMA_VERSION,
        "status": "source-baseline-view",
        "authority_mode": "comparison-only-non-authoritative",
        "source": source,
        "provenance": {
            "derivation": "direct-verified-phase1-baseline",
            "generator_version": VIEW_GENERATOR_VERSION,
        },
        "qualification_policy": {
            "semantic_modality": "source-preserved",
            "normative_posture": "source-unspecified",
        },
        "semantic_content": semantic_content,
        "summary": _view_summary(semantic_content),
    }
    payload["semantic_fingerprint"] = _view_semantic_fingerprint(source, semantic_content)
    payload["projection_fingerprint"] = _digest(payload)
    return validate_architecture_view(payload)


def _group_assertions(shadow: Mapping[str, Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {family: {} for family in _FAMILIES}
    for raw in _array(shadow.get("assertions"), "shadow assertions"):
        assertion = _object(raw, "shadow assertion")
        binding = _object(assertion.get("source_binding"), "shadow assertion source_binding")
        family = _text(binding.get("family"), "shadow assertion family")
        record_id = _text(binding.get("source_record_id"), "shadow assertion source record id")
        if family not in grouped:
            raise ArchitectureRoundTripError(f"unexpected shadow source family: {family}")
        grouped[family].setdefault(record_id, []).append(assertion)
    return grouped


def _assertion_common(
    assertions: Sequence[Mapping[str, Any]],
    *,
    family: str,
    record_id: str,
) -> dict[str, Any]:
    if not assertions:
        raise ArchitectureRoundTripError(f"{family}:{record_id} has no Assertions")
    first = assertions[0]
    first_qualifications = _object(first.get("qualifications"), "Assertion qualifications")
    expected = {
        "knowledge_state": _text(
            first_qualifications.get("source_knowledge_state"),
            f"{family}:{record_id} source_knowledge_state",
        ),
        "confidence": _text(
            first_qualifications.get("confidence"),
            f"{family}:{record_id} confidence",
        ),
        "rationale": _text(first.get("rationale"), f"{family}:{record_id} rationale"),
        "evidence_refs": sorted(
            _text(ref, f"{family}:{record_id} evidence ref")
            for ref in _array(first.get("evidence_refs"), f"{family}:{record_id} evidence refs")
        ),
    }
    for assertion in assertions[1:]:
        qualifications = _object(assertion.get("qualifications"), "Assertion qualifications")
        current = {
            "knowledge_state": _text(
                qualifications.get("source_knowledge_state"),
                f"{family}:{record_id} source_knowledge_state",
            ),
            "confidence": _text(
                qualifications.get("confidence"),
                f"{family}:{record_id} confidence",
            ),
            "rationale": _text(assertion.get("rationale"), f"{family}:{record_id} rationale"),
            "evidence_refs": sorted(
                _text(ref, f"{family}:{record_id} evidence ref")
                for ref in _array(
                    assertion.get("evidence_refs"),
                    f"{family}:{record_id} evidence refs",
                )
            ),
        }
        if current != expected:
            raise ArchitectureRoundTripError(
                f"{family}:{record_id} Assertions disagree on source qualifications/evidence"
            )
    return {"id": record_id, **expected}


def _exact_predicates(
    assertions: Sequence[Mapping[str, Any]],
    predicate: str,
) -> list[dict[str, Any]]:
    return [dict(row) for row in assertions if row.get("predicate") == predicate]


def _single_predicate(
    assertions: Sequence[Mapping[str, Any]],
    predicate: str,
    *,
    family: str,
    record_id: str,
) -> dict[str, Any]:
    matches = _exact_predicates(assertions, predicate)
    if len(matches) != 1:
        raise ArchitectureRoundTripError(
            f"{family}:{record_id} requires exactly one {predicate} Assertion"
        )
    return matches[0]


def _value_from_assertion(
    assertion: Mapping[str, Any],
    *,
    label: str,
) -> Any:
    object_value = _object(assertion.get("object"), f"{label} object")
    if object_value.get("kind") != "value" or "value" not in object_value:
        raise ArchitectureRoundTripError(f"{label} must carry a literal/structured value")
    return object_value["value"]


def _source_term_from_assertion(assertion: Mapping[str, Any], *, label: str) -> str:
    subject = _object(assertion.get("subject"), f"{label} subject")
    if subject.get("kind") != "source-term":
        raise ArchitectureRoundTripError(f"{label} must preserve a source-term subject")
    return _text(subject.get("term"), f"{label} subject term")


def _derived_semantic_content(shadow: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_shadow_payload(shadow)
    grouped = _group_assertions(validated)
    object_by_semantic_id = {
        str(row["semantic_id"]): row
        for row in _array(validated.get("objects"), "shadow objects")
        if isinstance(row, dict) and row.get("identity_source") == "phase1-architecture-node-id"
    }

    architecture_rows: list[dict[str, Any]] = []
    for record_id, rows in sorted(grouped["system_architecture_tree"].items()):
        common = _assertion_common(
            rows,
            family="system_architecture_tree",
            record_id=record_id,
        )
        if record_id not in object_by_semantic_id:
            raise ArchitectureRoundTripError(
                f"Architecture semantic Object missing for source record: {record_id}"
            )
        allowed_predicates = {
            "hasName",
            "hasSourceKind",
            "hasResponsibility",
            "partOf",
            "excludesResponsibility",
        }
        if any(str(row.get("predicate")) not in allowed_predicates for row in rows):
            raise ArchitectureRoundTripError(
                f"Architecture source record {record_id} contains an invalid predicate"
            )
        name = _text(
            _value_from_assertion(
                _single_predicate(
                    rows,
                    "hasName",
                    family="system_architecture_tree",
                    record_id=record_id,
                ),
                label=f"architecture:{record_id} hasName",
            ),
            f"architecture:{record_id} name",
        )
        kind = _text(
            _value_from_assertion(
                _single_predicate(
                    rows,
                    "hasSourceKind",
                    family="system_architecture_tree",
                    record_id=record_id,
                ),
                label=f"architecture:{record_id} hasSourceKind",
            ),
            f"architecture:{record_id} kind",
        )
        source_facets = _object(
            object_by_semantic_id[record_id].get("source_facets"),
            f"architecture:{record_id} source_facets",
        )
        if source_facets.get("kind") != kind:
            raise ArchitectureRoundTripError(
                f"Architecture source-kind Assertion disagrees with Object facet: {record_id}"
            )
        responsibility = _text(
            _value_from_assertion(
                _single_predicate(
                    rows,
                    "hasResponsibility",
                    family="system_architecture_tree",
                    record_id=record_id,
                ),
                label=f"architecture:{record_id} responsibility",
            ),
            f"architecture:{record_id} responsibility",
        )
        parents = _exact_predicates(rows, "partOf")
        if len(parents) > 1:
            raise ArchitectureRoundTripError(
                f"Architecture source record {record_id} has multiple parent Assertions"
            )
        parent_id: str | None = None
        if parents:
            parent_object = _object(parents[0].get("object"), "Architecture parent object")
            if parent_object.get("kind") != "object-ref":
                raise ArchitectureRoundTripError(
                    f"Architecture parent must be an Object reference: {record_id}"
                )
            parent_id = _text(parent_object.get("ref"), f"architecture:{record_id} parent")
        non_responsibilities = sorted(
            _text(
                _value_from_assertion(
                    row,
                    label=f"architecture:{record_id} excludesResponsibility",
                ),
                f"architecture:{record_id} non-responsibility",
            )
            for row in _exact_predicates(rows, "excludesResponsibility")
        )
        architecture_rows.append(
            {
                **common,
                "name": name,
                "kind": kind,
                "parent_id": parent_id,
                "responsibility": responsibility,
                "non_responsibilities": non_responsibilities,
            }
        )

    responsibility_rows: list[dict[str, Any]] = []
    for record_id, rows in sorted(grouped["module_responsibility_map"].items()):
        common = _assertion_common(
            rows,
            family="module_responsibility_map",
            record_id=record_id,
        )
        allowed_predicates = {"responsibleFor", "excludesResponsibility"}
        if any(str(row.get("predicate")) not in allowed_predicates for row in rows):
            raise ArchitectureRoundTripError(
                f"Responsibility source record {record_id} contains an invalid predicate"
            )
        primary = _single_predicate(
            rows,
            "responsibleFor",
            family="module_responsibility_map",
            record_id=record_id,
        )
        owner = _source_term_from_assertion(
            primary,
            label=f"responsibility:{record_id}",
        )
        primary_value = _object(
            _value_from_assertion(primary, label=f"responsibility:{record_id}"),
            f"responsibility:{record_id} value",
        )
        subject = _text(primary_value.get("scope_term"), f"responsibility:{record_id} scope")
        responsibility = _text(
            primary_value.get("responsibility"),
            f"responsibility:{record_id} responsibility",
        )
        non_responsibilities: list[str] = []
        for row in _exact_predicates(rows, "excludesResponsibility"):
            if _source_term_from_assertion(row, label=f"responsibility:{record_id} exclusion") != owner:
                raise ArchitectureRoundTripError(
                    f"Responsibility exclusion owner diverges: {record_id}"
                )
            value = _object(
                _value_from_assertion(row, label=f"responsibility:{record_id} exclusion"),
                f"responsibility:{record_id} exclusion value",
            )
            if _text(value.get("scope_term"), f"responsibility:{record_id} exclusion scope") != subject:
                raise ArchitectureRoundTripError(
                    f"Responsibility exclusion scope diverges: {record_id}"
                )
            non_responsibilities.append(
                _text(
                    value.get("responsibility"),
                    f"responsibility:{record_id} exclusion responsibility",
                )
            )
        responsibility_rows.append(
            {
                **common,
                "subject": subject,
                "owner": owner,
                "responsibility": responsibility,
                "non_responsibilities": sorted(non_responsibilities),
            }
        )

    def derived_statement_rows(family: str, predicate: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record_id, rows in sorted(grouped[family].items()):
            common = _assertion_common(rows, family=family, record_id=record_id)
            if len(rows) != 1 or rows[0].get("predicate") != predicate:
                raise ArchitectureRoundTripError(
                    f"{family}:{record_id} must contain exactly one {predicate} Assertion"
                )
            result.append(
                {
                    **common,
                    "subject": _source_term_from_assertion(
                        rows[0],
                        label=f"{family}:{record_id}",
                    ),
                    "statement": _text(
                        _value_from_assertion(
                            rows[0],
                            label=f"{family}:{record_id}",
                        ),
                        f"{family}:{record_id} statement",
                    ),
                }
            )
        return result

    assurance_rows: list[dict[str, Any]] = []
    for record_id, rows in sorted(grouped["validation_assurance_ownership"].items()):
        common = _assertion_common(
            rows,
            family="validation_assurance_ownership",
            record_id=record_id,
        )
        primary = _single_predicate(
            rows,
            "responsibleForAssurance",
            family="validation_assurance_ownership",
            record_id=record_id,
        )
        if len(rows) != 1:
            raise ArchitectureRoundTripError(
                f"Assurance source record {record_id} must contain one Assertion"
            )
        value = _object(
            _value_from_assertion(primary, label=f"assurance:{record_id}"),
            f"assurance:{record_id} value",
        )
        assurance_rows.append(
            {
                **common,
                "subject": _text(value.get("scope_term"), f"assurance:{record_id} subject"),
                "owner": _source_term_from_assertion(primary, label=f"assurance:{record_id}"),
                "responsibility": _text(
                    value.get("responsibility"),
                    f"assurance:{record_id} responsibility",
                ),
            }
        )

    return {
        "system_architecture_tree": architecture_rows,
        "module_responsibility_map": responsibility_rows,
        "implementation_intent_summary": derived_statement_rows(
            "implementation_intent_summary",
            "hasImplementationIntent",
        ),
        "validation_assurance_ownership": assurance_rows,
        "constraints": derived_statement_rows("constraints", "hasConstraint"),
        "unknowns": derived_statement_rows("unknowns", "hasUnresolvedStatement"),
        "claim_ceiling": _text(
            _object(validated.get("reliance"), "shadow reliance").get("claim_ceiling"),
            "shadow claim ceiling",
        ),
    }


def _view_summary(semantic_content: Mapping[str, Any]) -> dict[str, int]:
    return {
        "architecture_node_count": len(_array(semantic_content.get("system_architecture_tree"), "architecture rows")),
        "responsibility_count": len(_array(semantic_content.get("module_responsibility_map"), "responsibility rows")),
        "implementation_intent_count": len(_array(semantic_content.get("implementation_intent_summary"), "intent rows")),
        "assurance_count": len(_array(semantic_content.get("validation_assurance_ownership"), "assurance rows")),
        "constraint_count": len(_array(semantic_content.get("constraints"), "constraint rows")),
        "unknown_count": len(_array(semantic_content.get("unknowns"), "unknown rows")),
    }


def derive_architecture_view(shadow: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_shadow_payload(shadow)
    source_shadow = _object(validated.get("source"), "shadow source")
    source = {
        "profile_id": _text(source_shadow.get("profile_id"), "shadow profile_id"),
        "source_commit": _text(source_shadow.get("source_commit"), "shadow source commit"),
        "source_tree": _text(source_shadow.get("source_tree"), "shadow source tree"),
        "snapshot_id": _text(source_shadow.get("snapshot_id"), "shadow snapshot id"),
        "architecture_memory_schema_version": _text(
            source_shadow.get("architecture_memory_schema_version"),
            "shadow source Architecture Memory schema",
        ),
        "evidence_ref_count": int(source_shadow.get("evidence_ref_count", -1)),
    }
    semantic_content = _derived_semantic_content(validated)
    payload: dict[str, Any] = {
        "schema_version": ARCHITECTURE_VIEW_SCHEMA_VERSION,
        "status": VIEW_STATUS,
        "authority_mode": VIEW_AUTHORITY_MODE,
        "source": source,
        "provenance": {
            "derivation": "shadow-substrate",
            "generator_version": VIEW_GENERATOR_VERSION,
            "shadow_authority_mode": validated.get("authority_mode"),
            "shadow_semantic_fingerprint": validated.get("semantic_fingerprint"),
            "shadow_projection_fingerprint": validated.get("projection_fingerprint"),
        },
        "qualification_policy": {
            "semantic_modality": "source-preserved",
            "normative_posture": "source-unspecified",
        },
        "semantic_content": semantic_content,
        "summary": _view_summary(semantic_content),
    }
    payload["semantic_fingerprint"] = _view_semantic_fingerprint(source, semantic_content)
    payload["projection_fingerprint"] = _digest(payload)
    return validate_architecture_view(payload)


def validate_architecture_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != ARCHITECTURE_VIEW_SCHEMA_VERSION:
        raise ArchitectureRoundTripError("unsupported Architecture View schema")
    status = str(payload.get("status") or "")
    authority_mode = str(payload.get("authority_mode") or "")
    if status not in {VIEW_STATUS, "source-baseline-view"}:
        raise ArchitectureRoundTripError("unexpected Architecture View status")
    expected_authority = (
        VIEW_AUTHORITY_MODE
        if status == VIEW_STATUS
        else "comparison-only-non-authoritative"
    )
    if authority_mode != expected_authority:
        raise ArchitectureRoundTripError(
            "Architecture View status/authority combination attempted to escape its derived role"
        )
    source = _object(payload.get("source"), "Architecture View source")
    source_commit = _text(source.get("source_commit"), "Architecture View source commit")
    source_tree = _text(source.get("source_tree"), "Architecture View source tree")
    snapshot_id = _text(source.get("snapshot_id"), "Architecture View snapshot id")
    if source_tree not in snapshot_id:
        raise ArchitectureRoundTripError("Architecture View snapshot identity does not bind its source tree")
    if int(source.get("evidence_ref_count", -1)) < 1:
        raise ArchitectureRoundTripError("Architecture View source evidence denominator is invalid")
    provenance = _object(payload.get("provenance"), "Architecture View provenance")
    if provenance.get("generator_version") != VIEW_GENERATOR_VERSION:
        raise ArchitectureRoundTripError("Architecture View generator provenance is invalid")
    if status == VIEW_STATUS:
        if provenance.get("derivation") != "shadow-substrate":
            raise ArchitectureRoundTripError("derived Architecture View lacks shadow derivation provenance")
        if provenance.get("shadow_authority_mode") != SHADOW_AUTHORITY_MODE:
            raise ArchitectureRoundTripError("derived Architecture View references an invalid shadow authority mode")
        for key in ("shadow_semantic_fingerprint", "shadow_projection_fingerprint"):
            value = _text(provenance.get(key), f"Architecture View {key}")
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ArchitectureRoundTripError(f"Architecture View {key} is invalid")
    else:
        if provenance != {
            "derivation": "direct-verified-phase1-baseline",
            "generator_version": VIEW_GENERATOR_VERSION,
        }:
            raise ArchitectureRoundTripError("source baseline view contains derived or unexpected provenance")
    qualification_policy = _object(
        payload.get("qualification_policy"),
        "Architecture View qualification_policy",
    )
    if qualification_policy != {
        "semantic_modality": "source-preserved",
        "normative_posture": "source-unspecified",
    }:
        raise ArchitectureRoundTripError("Architecture View qualification policy drifted")
    semantic_content = _object(payload.get("semantic_content"), "Architecture View semantic_content")
    for family in _FAMILIES:
        rows = [_object(row, f"Architecture View {family} row") for row in _array(semantic_content.get(family), family)]
        ids = [_text(row.get("id"), f"Architecture View {family} id") for row in rows]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ArchitectureRoundTripError(
                f"Architecture View {family} identities are duplicate or nondeterministically ordered"
            )
        for row in rows:
            state = _text(
                row.get("knowledge_state"),
                f"Architecture View {family}:{row['id']} knowledge_state",
            )
            if state not in {"observed-fact", "inferred-knowledge", "unknown", "conflicting"}:
                raise ArchitectureRoundTripError(
                    f"Architecture View {family}:{row['id']} knowledge_state is unsupported"
                )
            refs = [
                _text(ref, f"Architecture View {family}:{row['id']} evidence ref")
                for ref in _array(
                    row.get("evidence_refs"),
                    f"Architecture View {family} evidence refs",
                )
            ]
            if refs != sorted(refs) or len(refs) != len(set(refs)):
                raise ArchitectureRoundTripError(
                    f"Architecture View {family}:{row['id']} evidence refs are duplicate or nondeterministically ordered"
                )
            if state == "conflicting" and len(refs) < 2:
                raise ArchitectureRoundTripError(
                    f"Architecture View {family}:{row['id']} conflicting posture requires at least two evidence refs"
                )
    architecture_rows = _array(
        semantic_content.get("system_architecture_tree"),
        "Architecture View architecture rows",
    )
    architecture_ids = {
        _text(row.get("id"), "Architecture View architecture id")
        for row in architecture_rows
        if isinstance(row, dict)
    }
    for row in architecture_rows:
        architecture_row = _object(row, "Architecture View architecture row")
        parent_id = architecture_row.get("parent_id")
        if parent_id is not None and _text(parent_id, "Architecture View parent id") not in architecture_ids:
            raise ArchitectureRoundTripError("Architecture View contains an unknown parent identity")
    unknowns = _array(semantic_content.get("unknowns"), "Architecture View unknowns")
    if any(row.get("knowledge_state") != "unknown" for row in unknowns if isinstance(row, dict)):
        raise ArchitectureRoundTripError("Architecture View silently upgraded an unknown")
    _text(semantic_content.get("claim_ceiling"), "Architecture View claim ceiling")
    summary = _object(payload.get("summary"), "Architecture View summary")
    expected_summary = _view_summary(semantic_content)
    if summary != expected_summary:
        raise ArchitectureRoundTripError("Architecture View summary does not match semantic content")
    expected_semantic = _view_semantic_fingerprint(source, semantic_content)
    if payload.get("semantic_fingerprint") != expected_semantic:
        raise ArchitectureRoundTripError("Architecture View semantic fingerprint mismatch")
    expected_projection = _digest(
        {key: value for key, value in payload.items() if key != "projection_fingerprint"}
    )
    if payload.get("projection_fingerprint") != expected_projection:
        raise ArchitectureRoundTripError("Architecture View projection fingerprint mismatch")
    return dict(payload)


def validate_parity_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != PARITY_REPORT_SCHEMA_VERSION:
        raise ArchitectureRoundTripError("unsupported Architecture parity report schema")
    if payload.get("status") != PARITY_STATUS:
        raise ArchitectureRoundTripError("unexpected Architecture parity report status")
    if payload.get("authority_mode") != "comparison-only-non-authoritative":
        raise ArchitectureRoundTripError("Architecture parity report attempted to become authority")
    verdict = str(payload.get("verdict") or "")
    if verdict not in {PARITY_PASS, PARITY_FAIL}:
        raise ArchitectureRoundTripError("Architecture parity report verdict is invalid")
    dimensions = _object(payload.get("dimensions"), "Architecture parity dimensions")
    expected_dimensions = {
        "source_context",
        "architecture_identity_structure",
        "responsibility_non_responsibility",
        "implementation_intent",
        "assurance_ownership",
        "constraints",
        "unknown_posture",
        "claim_ceiling",
        "evidence_bindings",
        "semantic_fingerprint",
    }
    if set(dimensions) != expected_dimensions or any(
        not isinstance(value, bool) for value in dimensions.values()
    ):
        raise ArchitectureRoundTripError("Architecture parity dimensions are incomplete or invalid")
    mismatch_count = payload.get("mismatch_count")
    mismatch_paths = _array(payload.get("mismatch_paths"), "Architecture parity mismatch_paths")
    if not isinstance(mismatch_count, int) or mismatch_count < 0:
        raise ArchitectureRoundTripError("Architecture parity mismatch_count is invalid")
    if mismatch_count < len(mismatch_paths):
        raise ArchitectureRoundTripError("Architecture parity mismatch_count is smaller than retained paths")
    should_pass = all(dimensions.values()) and mismatch_count == 0
    if (verdict == PARITY_PASS) != should_pass:
        raise ArchitectureRoundTripError("Architecture parity verdict is inconsistent with evidence")
    baseline_fp = _text(
        payload.get("baseline_view_semantic_fingerprint"),
        "baseline Architecture View semantic fingerprint",
    )
    derived_fp = _text(
        payload.get("derived_view_semantic_fingerprint"),
        "derived Architecture View semantic fingerprint",
    )
    if dimensions["semantic_fingerprint"] != (baseline_fp == derived_fp):
        raise ArchitectureRoundTripError("Architecture parity semantic-fingerprint dimension is inconsistent")
    baseline_summary = _object(payload.get("baseline_summary"), "Architecture parity baseline summary")
    derived_summary = _object(payload.get("derived_summary"), "Architecture parity derived summary")
    required_summary_keys = {
        "architecture_node_count",
        "responsibility_count",
        "implementation_intent_count",
        "assurance_count",
        "constraint_count",
        "unknown_count",
    }
    if set(baseline_summary) != required_summary_keys or set(derived_summary) != required_summary_keys:
        raise ArchitectureRoundTripError("Architecture parity summary contract is invalid")
    _text(payload.get("source_commit"), "Architecture parity source commit")
    _text(payload.get("source_tree"), "Architecture parity source tree")
    _text(payload.get("shadow_semantic_fingerprint"), "Architecture parity shadow fingerprint")
    _text(payload.get("claim_ceiling"), "Architecture parity claim ceiling")
    return dict(payload)


def _diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [f"{path}:type"]
    if isinstance(left, dict):
        differences: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append(f"{path}.{key}:missing")
            else:
                differences.extend(_diff_paths(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [f"{path}:length"]
        differences: list[str] = []
        for index, (left_value, right_value) in enumerate(zip(left, right)):
            differences.extend(_diff_paths(left_value, right_value, f"{path}[{index}]"))
        return differences
    return [] if left == right else [path]


def _family_evidence_projection(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (
            str(row["id"]),
            tuple(sorted(str(ref) for ref in row.get("evidence_refs", []))),
        )
        for row in rows
    ]


def compare_architecture_roundtrip(
    snapshot: VerifiedPhase1Snapshot,
    shadow: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(snapshot, VerifiedPhase1Snapshot):
        raise ArchitectureRoundTripError("round-trip comparison requires a VerifiedPhase1Snapshot")
    baseline = build_source_architecture_baseline_view(snapshot)
    derived = derive_architecture_view(shadow)
    baseline_content = _object(baseline.get("semantic_content"), "baseline semantic content")
    derived_content = _object(derived.get("semantic_content"), "derived semantic content")

    dimensions = {
        "source_context": baseline["source"] == derived["source"],
        "architecture_identity_structure": (
            baseline_content["system_architecture_tree"]
            == derived_content["system_architecture_tree"]
        ),
        "responsibility_non_responsibility": (
            baseline_content["module_responsibility_map"]
            == derived_content["module_responsibility_map"]
        ),
        "implementation_intent": (
            baseline_content["implementation_intent_summary"]
            == derived_content["implementation_intent_summary"]
        ),
        "assurance_ownership": (
            baseline_content["validation_assurance_ownership"]
            == derived_content["validation_assurance_ownership"]
        ),
        "constraints": baseline_content["constraints"] == derived_content["constraints"],
        "unknown_posture": baseline_content["unknowns"] == derived_content["unknowns"],
        "claim_ceiling": baseline_content["claim_ceiling"] == derived_content["claim_ceiling"],
        "evidence_bindings": all(
            _family_evidence_projection(baseline_content[family])
            == _family_evidence_projection(derived_content[family])
            for family in _FAMILIES
        ),
        "semantic_fingerprint": (
            baseline["semantic_fingerprint"] == derived["semantic_fingerprint"]
        ),
    }
    mismatch_paths = _diff_paths(
        {"source": baseline["source"], "semantic_content": baseline_content},
        {"source": derived["source"], "semantic_content": derived_content},
    )
    verdict = PARITY_PASS if all(dimensions.values()) and not mismatch_paths else PARITY_FAIL
    report = {
        "schema_version": PARITY_REPORT_SCHEMA_VERSION,
        "status": PARITY_STATUS,
        "verdict": verdict,
        "authority_mode": "comparison-only-non-authoritative",
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "shadow_semantic_fingerprint": shadow.get("semantic_fingerprint"),
        "baseline_view_semantic_fingerprint": baseline["semantic_fingerprint"],
        "derived_view_semantic_fingerprint": derived["semantic_fingerprint"],
        "dimensions": dimensions,
        "mismatch_count": len(mismatch_paths),
        "mismatch_paths": mismatch_paths[:100],
        "baseline_summary": baseline["summary"],
        "derived_summary": derived["summary"],
        "claim_ceiling": (
            "This report proves only bounded semantic round-trip parity between the current verified "
            "Phase-1 Architecture Memory and a non-authoritative derived Architecture View through the "
            "P1 shadow substrate. It does not make the shadow/view authoritative, migrate Capability "
            "queries, prove Flow, authorize semantic cutover, or prove universal Architecture completeness."
        ),
    }
    return validate_parity_report(report)


def _safe_shadow_artifact_path(
    repository_root: str | Path,
    source_tree: str,
    filename: str,
) -> Path:
    root = Path(repository_root).expanduser().resolve(strict=False)
    shadow_file = shadow_output_path(root, source_tree)
    parent = shadow_file.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ArchitectureRoundTripError(f"shadow runtime directory is unsafe: {parent}")
    output = parent / filename
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise ArchitectureRoundTripError(f"shadow derived output is unsafe: {output}")
    return output


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise ArchitectureRoundTripError(f"shadow temporary output is unsafe: {temporary}")
        temporary.unlink()
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _serialized_shadow_roundtrip(shadow: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(
        json.dumps(shadow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return validate_shadow_payload(payload)


def run_architecture_roundtrip(
    repository_root: str | Path,
    *,
    source_tree: str,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Compile/reopen the P1 shadow, derive the Architecture View, and evaluate parity."""
    root = Path(repository_root).expanduser().resolve(strict=False)
    snapshot = verify_phase1_snapshot(root, source_tree=source_tree)
    compiled_shadow = compile_phase1_architecture_shadow(snapshot)
    if compiled_shadow.get("authority_mode") != SHADOW_AUTHORITY_MODE:
        raise ArchitectureRoundTripError("P2 received an authoritative or unknown shadow mode")

    if write_outputs:
        shadow_path = persist_shadow_payload(root, compiled_shadow)
        if shadow_path.is_symlink() or not shadow_path.is_file():
            raise ArchitectureRoundTripError("persisted P1 shadow is unsafe")
        try:
            reopened = json.loads(shadow_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchitectureRoundTripError(f"persisted P1 shadow cannot be reopened: {exc}") from exc
        shadow = validate_shadow_payload(reopened, allowed_evidence_refs=snapshot.evidence_refs)
    else:
        shadow = validate_shadow_payload(
            _serialized_shadow_roundtrip(compiled_shadow),
            allowed_evidence_refs=snapshot.evidence_refs,
        )

    view = derive_architecture_view(shadow)
    report = compare_architecture_roundtrip(snapshot, shadow)
    if write_outputs:
        view_path = _safe_shadow_artifact_path(root, source_tree, VIEW_FILENAME)
        report_path = _safe_shadow_artifact_path(root, source_tree, PARITY_FILENAME)
        _write_json(view_path, view)
        _write_json(report_path, report)
    else:
        view_path = None
        report_path = None

    return {
        "schema_version": "ekri.architecture-roundtrip-run.v1",
        "status": PARITY_STATUS,
        "verdict": report["verdict"],
        "authority_mode": VIEW_AUTHORITY_MODE,
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "shadow_semantic_fingerprint": shadow["semantic_fingerprint"],
        "architecture_view_semantic_fingerprint": view["semantic_fingerprint"],
        "architecture_view_projection_fingerprint": view["projection_fingerprint"],
        "dimensions": report["dimensions"],
        "mismatch_count": report["mismatch_count"],
        "view_output": str(view_path) if view_path is not None else "",
        "parity_output": str(report_path) if report_path is not None else "",
        "claim_ceiling": report["claim_ceiling"],
    }
