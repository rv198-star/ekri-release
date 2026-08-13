"""Stable Capability request/specification/policy contract for EKRI v1.0.

P7 extracts these pure semantics from the retired v0.9 Capability Catalog
writer. They are shared by the ontology-authoritative Capability slice, named
queries, and the legacy compatibility adapter without recreating a peer writer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Iterable
import unicodedata

from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    _run_git,
    _tree_entries,
    resolve_scanner_identity,
)


PHASE_ID = "phase2-existing-capability-intelligence"
SPEC_SCHEMA_VERSION = "ekri.capability-intelligence-spec.v1"
SPEC_PROFILE_ID = "wff-v1.6.2-existing-capability"
CATALOG_SCHEMA_VERSION = "ekri.capability-catalog.v1"
REQUEST_SCHEMA_VERSION = "ekri.capability-check-request.v1"
REPORT_SCHEMA_VERSION = "ekri.before-generate-capability-check.v1"
AUDIT_SCHEMA_VERSION = "ekri.capability-intelligence-audit.v1"
VALID_STATUS = "existing-capability-intelligence-complete"

TRIGGER_BASES = {
    "observed-failure",
    "declared-requirement",
    "hypothetical-risk",
}
CHANGE_MODES = {
    "use-as-is",
    "additive-extension",
    "behavior-replacement",
    "new-capability",
}
DECISION_STATUSES = {"not-supplied", "accepted"}
RECOMMENDATION_POSTURES = {
    "reuse",
    "extend",
    "replace",
    "create-new",
    "insufficient-evidence",
}
MAINLINE_IMPACTS = {
    "direct-mainline",
    "conditional-mainline",
    "supporting-mainline",
    "outside-runtime-mainline",
    "unknown",
}


class ExistingCapabilityError(RuntimeError):
    """Raised when Capability contract/query compatibility cannot be proven."""


@dataclass(frozen=True)
class CapabilitySpecIdentity:
    source: str
    path: str
    sha256: str
    scanner_commit: str
    scanner_tree: str
    blob_oid: str


@dataclass(frozen=True)
class CapabilityCheckRequest:
    capability_query: str
    trigger_basis: str
    change_mode: str
    trigger_reference: str = ""
    decision_status: str = "not-supplied"
    decision_reference: str = ""
    non_reuse_reason: str = ""
    context_note: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExistingCapabilityError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ExistingCapabilityError(
            f"{label} must be a list with at least {minimum} item(s)"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    minimum: int = 1,
    maximum: int = 4000,
) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise ExistingCapabilityError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _optional_text(value: object, label: str, *, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ExistingCapabilityError(f"{label} exceeds {maximum} characters")
    return text


def _identifier(value: object, label: str) -> str:
    identifier = _text(value, label, minimum=2, maximum=120)
    if not identifier[0].isalpha() or not all(
        character.isalnum() or character in "._-" for character in identifier
    ):
        raise ExistingCapabilityError(
            f"{label} must start with a letter and use letters, digits, '.', '_', or '-'"
        )
    return identifier


def normalize_capability_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    characters = [
        character if character.isalnum() else " " for character in normalized
    ]
    return " ".join("".join(characters).split())


def build_request(
    *,
    capability_query: str,
    trigger_basis: str,
    change_mode: str,
    trigger_reference: str = "",
    decision_status: str = "not-supplied",
    decision_reference: str = "",
    non_reuse_reason: str = "",
    context_note: str = "",
) -> CapabilityCheckRequest:
    query = _text(capability_query, "capability_query", minimum=2, maximum=240)
    basis = _text(trigger_basis, "trigger_basis", maximum=80)
    mode = _text(change_mode, "change_mode", maximum=80)
    if basis not in TRIGGER_BASES:
        raise ExistingCapabilityError(
            "trigger_basis must be observed-failure, declared-requirement, or hypothetical-risk"
        )
    if mode not in CHANGE_MODES:
        raise ExistingCapabilityError(
            "change_mode must be use-as-is, additive-extension, behavior-replacement, or new-capability"
        )
    trigger_ref = _optional_text(
        trigger_reference, "trigger_reference", maximum=500
    )
    status = _text(decision_status, "decision_status", maximum=80)
    if status not in DECISION_STATUSES:
        raise ExistingCapabilityError(
            "decision_status must be not-supplied or accepted"
        )
    decision_ref = _optional_text(
        decision_reference, "decision_reference", maximum=500
    )
    non_reuse = _optional_text(
        non_reuse_reason, "non_reuse_reason", maximum=1200
    )
    note = _optional_text(context_note, "context_note", maximum=2000)
    if basis in {"observed-failure", "declared-requirement"} and len(trigger_ref) < 3:
        raise ExistingCapabilityError(
            f"trigger_reference is required for trigger basis {basis}"
        )
    if status == "accepted":
        if not decision_ref or not non_reuse:
            raise ExistingCapabilityError(
                "accepted decision_status requires decision_reference and non_reuse_reason"
            )
    elif decision_ref or non_reuse:
        raise ExistingCapabilityError(
            "decision_reference and non_reuse_reason require decision_status=accepted"
        )
    return CapabilityCheckRequest(
        capability_query=query,
        trigger_basis=basis,
        change_mode=mode,
        trigger_reference=trigger_ref,
        decision_status=status,
        decision_reference=decision_ref,
        non_reuse_reason=non_reuse,
        context_note=note,
    )


def _load_json_path(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ExistingCapabilityError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ExistingCapabilityError(f"{label} must be a safe regular file")
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExistingCapabilityError(f"{label} cannot be read: {exc}") from exc


def load_capability_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], CapabilitySpecIdentity]:
    if path is not None:
        source = Path(path).expanduser()
        payload = _load_json_path(source, "capability intelligence specification")
        raw = source.read_bytes()
        identity = CapabilitySpecIdentity(
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
            raise ExistingCapabilityError(
                f"active scanner provenance is unverifiable: {exc}"
            ) from exc
        relative_path = "EKRI/specs/wff-v162-capability-intelligence.json"
        entries = [
            entry
            for entry in _tree_entries(
                active.repository_root,
                active.tree,
                pathspec=relative_path,
            )
            if entry[3] == relative_path
        ]
        if len(entries) != 1:
            raise ExistingCapabilityError(
                "committed capability intelligence specification is missing or ambiguous"
            )
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ExistingCapabilityError(
                "committed capability intelligence specification must be a regular Git blob"
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
                "capability intelligence specification",
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExistingCapabilityError(
                f"committed capability intelligence specification cannot be read: {exc}"
            ) from exc
        identity = CapabilitySpecIdentity(
            source="scanner-commit",
            path=relative_path,
            sha256=_sha256(raw),
            scanner_commit=active.commit,
            scanner_tree=active.tree,
            blob_oid=oid,
        )
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ExistingCapabilityError(
            "unsupported capability intelligence specification schema"
        )
    if payload.get("profile_id") != SPEC_PROFILE_ID:
        raise ExistingCapabilityError("unexpected capability intelligence profile id")
    return payload, identity


def _row_projection(row: dict[str, Any], *, row_type: str) -> dict[str, Any]:
    projection = {
        "id": row["id"],
        "knowledge_state": row["knowledge_state"],
        "confidence": row["confidence"],
        "evidence_refs": list(row["evidence_refs"]),
    }
    if row_type == "architecture":
        projection.update(
            {
                "name": row["name"],
                "kind": row["kind"],
                "parent_id": row["parent_id"],
                "responsibility": row["responsibility"],
                "non_responsibilities": list(row.get("non_responsibilities", [])),
            }
        )
    elif row_type == "responsibility":
        projection.update(
            {
                "subject": row["subject"],
                "owner": row["owner"],
                "responsibility": row["responsibility"],
                "non_responsibilities": list(row.get("non_responsibilities", [])),
            }
        )
    elif row_type in {"constraint", "intent"}:
        projection.update(
            {
                "subject": row["subject"],
                "statement": row["statement"],
                "rationale": row["rationale"],
            }
        )
    elif row_type == "assurance":
        projection.update(
            {
                "subject": row["subject"],
                "responsibility": row["responsibility"],
                "rationale": row["rationale"],
            }
        )
    return projection


def _knowledge_posture(rows: Iterable[dict[str, Any]]) -> tuple[str, str]:
    states = {str(row.get("knowledge_state", "")) for row in rows}
    if "conflicting" in states:
        return "conflicting", "not-applicable"
    if "unknown" in states:
        return "unknown", "not-applicable"
    if "inferred-knowledge" in states:
        confidences = [
            str(row.get("confidence", ""))
            for row in rows
            if row.get("knowledge_state") == "inferred-knowledge"
        ]
        order = {"low": 0, "medium": 1, "high": 2}
        confidence = (
            min(confidences, key=lambda value: order.get(value, -1))
            if confidences
            else "low"
        )
        return "inferred-knowledge", confidence
    return "observed-fact", "verified"


def _reuse_limitations(
    architecture_rows: list[dict[str, Any]],
    responsibility_rows: list[dict[str, Any]],
    constraint_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in architecture_rows:
        for raw in row.get("non_responsibilities", []):
            text = _text(raw, "architecture non-responsibility")
            if text not in seen:
                items.append(
                    {
                        "kind": "non-responsibility",
                        "source_id": row["id"],
                        "statement": text,
                    }
                )
                seen.add(text)
    for row in responsibility_rows:
        for raw in row.get("non_responsibilities", []):
            text = _text(raw, "responsibility non-responsibility")
            if text not in seen:
                items.append(
                    {
                        "kind": "non-responsibility",
                        "source_id": row["id"],
                        "statement": text,
                    }
                )
                seen.add(text)
    for row in constraint_rows:
        text = _text(row.get("statement"), "constraint statement")
        if text not in seen:
            items.append(
                {"kind": "constraint", "source_id": row["id"], "statement": text}
            )
            seen.add(text)
    return items


def _request_payload(request: CapabilityCheckRequest) -> dict[str, str]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        **asdict(request),
        "normalized_query": normalize_capability_alias(request.capability_query),
    }


def _request_id(request_payload: dict[str, str], source_tree: str) -> str:
    basis = {"source_tree": source_tree, "request": request_payload}
    return hashlib.sha256(_json_bytes(basis)).hexdigest()


def _recommendation(
    *,
    match_status: str,
    capability: dict[str, Any] | None,
    request: CapabilityCheckRequest,
) -> dict[str, Any]:
    has_decision = bool(
        request.decision_status == "accepted"
        and request.decision_reference
        and request.non_reuse_reason
    )
    requires_architecture_decision = False
    warning = ""
    if match_status == "ambiguous":
        posture = "insufficient-evidence"
        reason = (
            "The query resolves to multiple capability entries; select one explicit capability id before generation."
        )
    elif match_status == "not-found":
        if request.change_mode == "new-capability" and has_decision:
            posture = "create-new"
            reason = (
                "An explicit decision authorizes new work, but the Architecture Memory lookup did not prove capability absence. "
                "The non-reuse decision must remain attached to the work."
            )
            warning = "create-new is decision-authorized, not absence-proven"
        else:
            posture = "insufficient-evidence"
            reason = (
                "No exact capability alias matched. Architecture Memory is bounded, so a miss cannot prove that the capability is absent."
            )
    else:
        if capability is None:
            raise ExistingCapabilityError("matched Capability recommendation requires a capability")
        if capability["knowledge_state"] == "conflicting":
            posture = "insufficient-evidence"
            reason = "The matched capability contains conflicting evidence or ownership posture that must be reconciled before action."
        elif capability["existence"] == "unknown":
            posture = "insufficient-evidence"
            reason = "The matched capability contains unknown ownership or existence state."
        elif request.change_mode == "use-as-is":
            posture = "reuse"
            reason = (
                "The capability exists in verified Architecture Memory and the requested mode does not require behavior change."
            )
        elif request.change_mode == "additive-extension":
            posture = "extend"
            reason = (
                "The capability exists; additive change should preserve its owner, non-responsibilities, and constraints."
            )
        elif request.change_mode == "behavior-replacement":
            if has_decision:
                posture = "replace"
                reason = (
                    "An explicit decision and non-reuse reason authorize replacement of the existing capability boundary."
                )
                warning = "replacement authorization does not raise the baseline claim ceiling"
            else:
                posture = "insufficient-evidence"
                requires_architecture_decision = True
                reason = (
                    "Hypothetical risk alone cannot justify replacement of an existing capability."
                    if request.trigger_basis == "hypothetical-risk"
                    else "Observed failure or declared requirement identifies pressure, but replacement still requires an explicit architecture decision and non-reuse reason."
                )
        elif request.change_mode == "new-capability":
            if has_decision:
                posture = "create-new"
                reason = (
                    "An explicit decision authorizes a separate capability despite an existing related capability."
                )
                warning = "the new capability must not silently duplicate the existing owner"
            else:
                posture = "extend"
                reason = (
                    "A related capability already exists; extend the existing owner unless a reviewed non-reuse decision proves separation is necessary."
                )
        else:
            posture = "insufficient-evidence"
            reason = "The requested change mode is unsupported."
    if posture not in RECOMMENDATION_POSTURES:
        raise ExistingCapabilityError(f"invalid recommendation posture: {posture}")
    return {
        "posture": posture,
        "reason": reason,
        "requires_architecture_decision": requires_architecture_decision,
        "decision_status": request.decision_status,
        "decision_reference": request.decision_reference,
        "decision_acceptance_verification": (
            "caller-asserted-accepted-not-independently-verified"
            if request.decision_status == "accepted"
            else "not-supplied"
        ),
        "non_reuse_reason": request.non_reuse_reason,
        "warning": warning,
    }
