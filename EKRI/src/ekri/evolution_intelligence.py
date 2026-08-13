"""Phase 3 incremental reconstruction, evolution, and change-impact intelligence.

The supported entry point is :func:`run_phase3_evolution_analysis`. It keeps
registered intent separate from observed Git facts, reads only admitted regular
Git blobs in a bounded change frontier, and persists an evidence-linked
architecture-evolution overlay without rewriting Phase 1 Architecture Memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Sequence
import uuid

from .capability_contract import ExistingCapabilityError, load_capability_spec
from .capability_query import CapabilityQueryService
from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .knowledge_reconstruction import (
    KnowledgeReconstructionError,
    _json_bytes,
    load_fixed_observation_manifest,
    load_reconstruction_spec,
)
from .observation_boundary import (
    ObservationBoundaryError,
    _absolute_path,
    _directory_open_flags,
    _normalize_tree_path,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    evaluate_observation_boundary,
    is_protected_path,
    resolve_git_target,
    write_manifest,
)
from .phase1_snapshot import (
    Phase1SnapshotError,
    VerifiedPhase1Snapshot,
    verify_phase1_snapshot,
)


PHASE_ID = "phase3-evolution-and-impact-intelligence"
REGISTRATION_SCHEMA_VERSION = "ekri.change-registration.v1"
SCAN_SCHEMA_VERSION = "ekri.incremental-reconstruction.v1"
EVOLUTION_SCHEMA_VERSION = "ekri.architecture-evolution-map.v1"
IMPACT_SCHEMA_VERSION = "ekri.change-impact-map.v1"
SNAPSHOT_SCHEMA_VERSION = "ekri.architecture-evolution-snapshot.v1"
AUDIT_SCHEMA_VERSION = "ekri.phase3-evolution-audit.v1"
RUN_SCHEMA_VERSION = "ekri.phase3-evolution-run.v1"
VALID_STATUS = "phase3-evolution-analysis-complete"

CHANGE_STATES = ("registered", "planned", "observed", "verified", "archived")
CHANGE_KINDS = {
    "capability-addition",
    "capability-replacement",
    "capability-removal",
    "responsibility-migration",
    "validation-ownership-change",
    "architecture-boundary-change",
}
SCAN_MODES = {"baseline", "local-change", "drift"}
VERIFICATION_TRIGGERS = {
    "capability-consumption",
    "design-decision",
    "explicit-request",
    "release-verification",
}
IMPACT_LEVELS = {
    "direct",
    "conditional",
    "supporting",
    "outside-runtime",
    "unknown",
}
_REGULAR_BLOB_MODES = {"100644", "100755"}


class EvolutionIntelligenceError(RuntimeError):
    """Raised when Phase 3 cannot produce a bounded, trustworthy result."""


@dataclass(frozen=True)
class ChangeRegistration:
    change_id: str
    capability_id: str
    change_kind: str
    summary: str
    expected_paths: tuple[str, ...] = ()
    state: str = "registered"
    decision_reference: str = ""
    registered_at: str = ""


@dataclass(frozen=True)
class ChangeImpactRequest:
    change_id: str
    capability_id: str
    affected_capability_ids: tuple[str, ...]
    classification: str
    rationale: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class _VerifiedIncrementalScan:
    payload: dict[str, Any]
    snapshot: VerifiedPhase1Snapshot
    capability_catalog: dict[str, Any]
    capability_ids: frozenset[str]


@dataclass(frozen=True)
class _VerifiedEvolutionEvent:
    payload: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    return _sha256(_json_bytes(value))


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvolutionIntelligenceError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvolutionIntelligenceError(f"{label} must be a list")
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
        raise EvolutionIntelligenceError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _optional_text(value: object, label: str, *, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise EvolutionIntelligenceError(f"{label} exceeds {maximum} characters")
    return text


def _identifier(value: object, label: str) -> str:
    identifier = _text(value, label, minimum=2, maximum=120)
    if not identifier[0].isalpha() or not all(
        character.isalnum() or character in "._-" for character in identifier
    ):
        raise EvolutionIntelligenceError(
            f"{label} must start with a letter and use letters, digits, '.', '_', or '-'"
        )
    return identifier


def _canonical_path(value: object, label: str) -> str:
    raw = _text(value, label, maximum=1000)
    try:
        path = _normalize_tree_path(raw)
    except ObservationBoundaryError as exc:
        raise EvolutionIntelligenceError(str(exc)) from exc
    if is_protected_path(path):
        raise EvolutionIntelligenceError(
            f"{label} enters the permanent protected EKRI/.EKRI surface: {path}"
        )
    return path


def build_change_registration(
    *,
    change_id: str,
    capability_id: str,
    change_kind: str,
    summary: str,
    expected_paths: Sequence[str] = (),
    state: str = "registered",
    decision_reference: str = "",
    registered_at: str = "",
) -> ChangeRegistration:
    """Build one intent record without changing architecture truth."""
    identifier = _identifier(change_id, "change_id")
    capability = _identifier(capability_id, "capability_id")
    kind = _text(change_kind, "change_kind", maximum=80)
    if kind not in CHANGE_KINDS:
        raise EvolutionIntelligenceError("unsupported change_kind")
    normalized_state = _text(state, "state", maximum=40)
    if normalized_state not in {"registered", "planned"}:
        raise EvolutionIntelligenceError(
            "caller registrations may start only in registered or planned state"
        )
    normalized_paths: list[str] = []
    for index, raw in enumerate(expected_paths, start=1):
        path = _canonical_path(raw, f"expected_paths[{index}]")
        if path not in normalized_paths:
            normalized_paths.append(path)
    timestamp = _optional_text(registered_at, "registered_at", maximum=80) or utc_now_iso()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvolutionIntelligenceError("registered_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EvolutionIntelligenceError("registered_at must include a timezone")
    return ChangeRegistration(
        change_id=identifier,
        capability_id=capability,
        change_kind=kind,
        summary=_text(summary, "summary", minimum=8, maximum=2000),
        expected_paths=tuple(sorted(normalized_paths)),
        state=normalized_state,
        decision_reference=_optional_text(
            decision_reference, "decision_reference", maximum=500
        ),
        registered_at=timestamp,
    )


def register_change(
    *,
    change_id: str,
    capability_id: str,
    description: str,
    change_kind: str = "architecture-boundary-change",
    expected_paths: Sequence[str] = (),
    decision_reference: str = "",
) -> ChangeRegistration:
    """Compatibility alias for building a registered change intent."""
    return build_change_registration(
        change_id=change_id,
        capability_id=capability_id,
        change_kind=change_kind,
        summary=description,
        expected_paths=expected_paths,
        decision_reference=decision_reference,
    )


def _validated_registration_input(
    registration: ChangeRegistration,
) -> ChangeRegistration:
    """Rebuild caller input and reject dataclass/API bypasses.

    Repository observation owns ``observed`` and ``verified``. Callers may
    supply only intent states that can be reproduced by the public builder.
    """
    if not isinstance(registration, ChangeRegistration):
        raise EvolutionIntelligenceError("registration must be a ChangeRegistration")
    if registration.state not in {"registered", "planned"}:
        raise EvolutionIntelligenceError(
            "caller registrations may contain only registered or planned intent; "
            "observed and verified states are scanner-owned"
        )
    rebuilt = build_change_registration(
        change_id=registration.change_id,
        capability_id=registration.capability_id,
        change_kind=registration.change_kind,
        summary=registration.summary,
        expected_paths=registration.expected_paths,
        state=registration.state,
        decision_reference=registration.decision_reference,
        registered_at=registration.registered_at,
    )
    if rebuilt != registration:
        raise EvolutionIntelligenceError(
            "change registration does not match the canonical builder contract"
        )
    return rebuilt


def transition_change_registration(
    registration: ChangeRegistration,
    *,
    next_state: str,
) -> ChangeRegistration:
    canonical = _validated_registration_input(registration)
    target = _text(next_state, "next_state", maximum=40)
    if canonical.state != "registered" or target != "planned":
        raise EvolutionIntelligenceError(
            "caller-managed registration transition is limited to registered -> planned; "
            "later states are scanner-owned"
        )
    return replace(canonical, state="planned")


def deferred_verification_needed(
    registration: ChangeRegistration,
    *,
    requested_capability: str = "",
    trigger: str = "capability-consumption",
) -> bool:
    """Return whether a pending registration should be verified now."""
    if not isinstance(registration, ChangeRegistration):
        raise EvolutionIntelligenceError("registration must be a ChangeRegistration")
    normalized_trigger = _text(trigger, "trigger", maximum=80)
    if normalized_trigger not in VERIFICATION_TRIGGERS:
        raise EvolutionIntelligenceError("unsupported verification trigger")
    if registration.state not in {"registered", "planned", "observed"}:
        return False
    if normalized_trigger in {"explicit-request", "release-verification"}:
        return True
    capability = _optional_text(
        requested_capability, "requested_capability", maximum=120
    )
    return bool(capability and capability == registration.capability_id)


def build_change_impact_request(
    *,
    change_id: str,
    capability_id: str,
    affected_capability_ids: Sequence[str],
    classification: str,
    rationale: str,
    evidence_refs: Sequence[str],
) -> ChangeImpactRequest:
    impact = _text(classification, "classification", maximum=80)
    if impact not in IMPACT_LEVELS:
        raise EvolutionIntelligenceError("unsupported impact classification")
    affected: list[str] = []
    for index, raw in enumerate(affected_capability_ids, start=1):
        identifier = _identifier(raw, f"affected_capability_ids[{index}]")
        if identifier not in affected:
            affected.append(identifier)
    refs: list[str] = []
    for index, raw in enumerate(evidence_refs, start=1):
        ref = _text(raw, f"evidence_refs[{index}]", maximum=240)
        if ref not in refs:
            refs.append(ref)
    if impact != "unknown" and not refs:
        raise EvolutionIntelligenceError(
            "non-unknown change impact requires baseline evidence refs"
        )
    return ChangeImpactRequest(
        change_id=_identifier(change_id, "change_id"),
        capability_id=_identifier(capability_id, "capability_id"),
        affected_capability_ids=tuple(sorted(affected)),
        classification=impact,
        rationale=_text(rationale, "rationale", minimum=12, maximum=2000),
        evidence_refs=tuple(sorted(refs)),
    )


def _decode_name_status(raw: bytes) -> list[tuple[str, str, str]]:
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    result: list[tuple[str, str, str]] = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise EvolutionIntelligenceError("Git diff status is not ASCII") from exc
        index += 1
        if not status:
            raise EvolutionIntelligenceError("Git diff returned an empty status")
        code = status[0]
        path_count = 2 if code in {"R", "C"} else 1
        if index + path_count > len(fields):
            raise EvolutionIntelligenceError("Git diff name-status stream is truncated")
        try:
            paths = [fields[index + offset].decode("utf-8") for offset in range(path_count)]
        except UnicodeDecodeError as exc:
            raise EvolutionIntelligenceError("Git diff contains a non-UTF-8 path") from exc
        index += path_count
        old_path = paths[0]
        new_path = paths[-1]
        result.append((status, old_path, new_path))
    return result


def _tree_index(repository_root: Path, tree: str) -> dict[str, tuple[str, str, str]]:
    return {
        path: (mode, object_type, oid)
        for mode, object_type, oid, path in _tree_entries(repository_root, tree)
    }


def _change_records(
    repository_root: Path,
    *,
    baseline_commit: str,
    baseline_tree: str,
    target_commit: str,
    target_tree: str,
    baseline_paths: frozenset[str],
    target_paths: frozenset[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = _run_git(
        repository_root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        baseline_commit,
        target_commit,
        "--",
        binary=True,
    )
    assert isinstance(raw, bytes)
    baseline_index = _tree_index(repository_root, baseline_tree)
    target_index = _tree_index(repository_root, target_tree)
    admitted: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    for status, old_raw, new_raw in _decode_name_status(raw):
        try:
            old_path = _normalize_tree_path(old_raw)
            new_path = _normalize_tree_path(new_raw)
        except ObservationBoundaryError as exc:
            raise EvolutionIntelligenceError(str(exc)) from exc
        before = baseline_index.get(old_path)
        after = target_index.get(new_path)
        record = {
            "status": status,
            "change_type": {
                "A": "added",
                "D": "deleted",
                "M": "modified",
                "T": "type-changed",
                "R": "renamed",
                "C": "copied",
            }.get(status[0], "other"),
            "old_path": old_path,
            "new_path": new_path,
            "before": {
                "mode": before[0] if before else "",
                "object_type": before[1] if before else "",
                "oid": before[2] if before else "",
                "admitted": old_path in baseline_paths,
            },
            "after": {
                "mode": after[0] if after else "",
                "object_type": after[1] if after else "",
                "oid": after[2] if after else "",
                "admitted": new_path in target_paths,
            },
        }
        if is_protected_path(old_path) or is_protected_path(new_path):
            protected.append(record)
        elif record["before"]["admitted"] or record["after"]["admitted"]:
            admitted.append(record)
    return admitted, protected


def _evidence_path_index(snapshot: VerifiedPhase1Snapshot) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_source in _array(snapshot.evidence_index.get("sources"), "evidence sources"):
        source = _object(raw_source, "evidence source")
        path = _text(source.get("path"), "evidence source path", maximum=1000)
        for raw_anchor in _array(source.get("anchors"), f"evidence anchors: {path}"):
            anchor = _object(raw_anchor, f"evidence anchor: {path}")
            ref = _text(anchor.get("evidence_ref"), "evidence ref", maximum=240)
            result[ref] = path
    return result


def _capability_neighborhood(
    catalog: dict[str, Any],
    snapshot: VerifiedPhase1Snapshot,
    changed_paths: set[str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    evidence_paths = _evidence_path_index(snapshot)
    capability_ids: set[str] = set()
    dependency_paths: set[str] = set()
    ownership_ids: set[str] = set()
    mapped_changed: set[str] = set()
    for raw in _array(catalog.get("capabilities"), "catalog capabilities"):
        capability = _object(raw, "catalog capability")
        capability_id = _identifier(capability.get("id"), "catalog capability id")
        paths = {
            _text(item, f"capability {capability_id} location", maximum=1000)
            for item in _array(capability.get("locations"), "capability locations")
        }
        for raw_ref in _array(capability.get("evidence_refs"), "capability evidence refs"):
            ref = _text(raw_ref, "capability evidence ref", maximum=240)
            if ref in evidence_paths:
                paths.add(evidence_paths[ref])
        intersections = paths & changed_paths
        if intersections:
            capability_ids.add(capability_id)
            dependency_paths.update(paths)
            mapped_changed.update(intersections)
            for row in _array(capability.get("responsibilities"), "capability responsibilities"):
                ownership_ids.add(_identifier(_object(row, "responsibility").get("id"), "responsibility id"))
            for row in _array(capability.get("architecture_nodes"), "capability architecture nodes"):
                ownership_ids.add(_identifier(_object(row, "architecture node").get("id"), "architecture node id"))
    return capability_ids, dependency_paths, ownership_ids, mapped_changed


def _read_frontier_receipts(
    baseline_reader: AdmittedGitReader,
    target_reader: AdmittedGitReader,
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    before_receipts: list[dict[str, Any]] = []
    after_receipts: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for record in records:
        before = _object(record.get("before"), "change before")
        after = _object(record.get("after"), "change after")
        old_path = _text(record.get("old_path"), "old_path", maximum=1000)
        new_path = _text(record.get("new_path"), "new_path", maximum=1000)
        if before.get("admitted") and before.get("mode") in _REGULAR_BLOB_MODES:
            try:
                baseline_reader.read_bytes(old_path)
                before_receipts.append(baseline_reader.receipt(old_path).to_dict())
            except AdmittedEvidenceError as exc:
                raise EvolutionIntelligenceError(
                    f"baseline frontier evidence cannot be read: {old_path}: {exc}"
                ) from exc
        elif before.get("admitted"):
            skipped.append({"path": old_path, "side": "before", "reason": "not-regular-blob"})
        if after.get("admitted") and after.get("mode") in _REGULAR_BLOB_MODES:
            try:
                target_reader.read_bytes(new_path)
                after_receipts.append(target_reader.receipt(new_path).to_dict())
            except AdmittedEvidenceError as exc:
                raise EvolutionIntelligenceError(
                    f"target frontier evidence cannot be read: {new_path}: {exc}"
                ) from exc
        elif after.get("admitted"):
            skipped.append({"path": new_path, "side": "after", "reason": "not-regular-blob"})
    return {
        "before": sorted(before_receipts, key=lambda item: item["path"]),
        "after": sorted(after_receipts, key=lambda item: item["path"]),
        "skipped_non_regular": sorted(skipped, key=lambda item: (item["path"], item["side"])),
        "before_read_paths": list(baseline_reader.read_paths()),
        "after_read_paths": list(target_reader.read_paths()),
    }


def _load_phase3_authority(
    repository_root: Path,
) -> tuple[
    VerifiedPhase1Snapshot,
    dict[str, Any],
    frozenset[str],
    dict[str, Any],
]:
    try:
        reconstruction_spec = load_reconstruction_spec()
        baseline_target = _object(reconstruction_spec.get("target"), "reconstruction target")
        baseline_tree = _text(baseline_target.get("tree"), "baseline tree", maximum=80)
        snapshot = verify_phase1_snapshot(repository_root, source_tree=baseline_tree)
        capability_spec, spec_identity = load_capability_spec()
        capability_service = CapabilityQueryService.from_snapshot(
            snapshot,
            capability_spec,
            spec_identity,
        )
        capability_authority = capability_service.authority
        baseline_manifest = load_fixed_observation_manifest(
            repository_root, tree=baseline_tree
        )
        AdmittedGitReader(repository_root, baseline_manifest)
    except (
        KnowledgeReconstructionError,
        Phase1SnapshotError,
        ExistingCapabilityError,
        AdmittedEvidenceError,
    ) as exc:
        raise EvolutionIntelligenceError(
            f"Phase 3 input authority cannot be verified: {exc}"
        ) from exc
    capability_ids = frozenset(
        _identifier(_object(item, "catalog capability").get("id"), "capability id")
        for item in _array(capability_authority.get("capabilities"), "Capability authority rows")
    )
    return snapshot, capability_authority, capability_ids, baseline_manifest


def _build_incremental_scan(
    repository_root: Path,
    *,
    snapshot: VerifiedPhase1Snapshot,
    catalog: dict[str, Any],
    capability_ids: frozenset[str],
    baseline_manifest: dict[str, Any],
    target_ref: str,
    scan_mode: str,
    seed_paths: Sequence[str],
    registered_seed_paths: Sequence[str],
    persist_target_manifest: bool,
) -> _VerifiedIncrementalScan:
    mode = _text(scan_mode, "scan_mode", maximum=40)
    if mode not in SCAN_MODES:
        raise EvolutionIntelligenceError("unsupported scan_mode")
    try:
        target_identity = resolve_git_target(repository_root, target_ref=target_ref)
    except ObservationBoundaryError as exc:
        raise EvolutionIntelligenceError(f"target identity cannot be resolved: {exc}") from exc
    if mode == "baseline" and target_identity.tree != snapshot.source_tree:
        raise EvolutionIntelligenceError("baseline scan requires the verified Phase 1 source tree")

    if target_identity.tree == snapshot.source_tree:
        if target_identity.commit != snapshot.source_commit:
            raise EvolutionIntelligenceError(
                "same-tree alternate commits are not persisted under the tree-keyed Phase 0 layout"
            )
        target_manifest = baseline_manifest
    else:
        target_manifest = evaluate_observation_boundary(
            repository_root=repository_root,
            target_ref=target_identity.commit,
        )
        boundary = _object(target_manifest.get("boundary"), "target boundary")
        if boundary.get("valid") is not True:
            raise EvolutionIntelligenceError(
                "target observation boundary rejected: "
                + str(boundary.get("failure_reason", "unknown failure"))
            )
        if persist_target_manifest:
            try:
                write_manifest(repository_root, target_manifest)
            except ObservationBoundaryError as exc:
                raise EvolutionIntelligenceError(
                    f"target observation manifest cannot be persisted: {exc}"
                ) from exc

    try:
        baseline_reader = AdmittedGitReader(repository_root, baseline_manifest)
        target_reader = AdmittedGitReader(repository_root, target_manifest)
    except AdmittedEvidenceError as exc:
        raise EvolutionIntelligenceError(
            f"incremental scan manifest revalidation failed: {exc}"
        ) from exc

    records, protected_records = _change_records(
        repository_root,
        baseline_commit=snapshot.source_commit,
        baseline_tree=snapshot.source_tree,
        target_commit=target_identity.commit,
        target_tree=target_identity.tree,
        baseline_paths=frozenset(baseline_manifest["corpus"]["paths"]),
        target_paths=frozenset(target_manifest["corpus"]["paths"]),
    )
    changed_paths = {
        path
        for record in records
        for path in (str(record["old_path"]), str(record["new_path"]))
    }
    explicit_seeds = {
        _canonical_path(raw, f"seed_paths[{index}]")
        for index, raw in enumerate(seed_paths, start=1)
    }
    registration_candidates = {
        _canonical_path(raw, f"registered_seed_paths[{index}]")
        for index, raw in enumerate(registered_seed_paths, start=1)
    }
    if mode == "local-change" and not explicit_seeds and not registration_candidates:
        raise EvolutionIntelligenceError(
            "local-change scan requires explicit seed paths or a registration selected for verification"
        )
    unknown_explicit_seeds = sorted(explicit_seeds - changed_paths)
    if unknown_explicit_seeds:
        raise EvolutionIntelligenceError(
            "explicit local scan seeds are not changed in the target delta: "
            + ", ".join(unknown_explicit_seeds)
        )
    deferred_unobserved_registration_paths = sorted(
        registration_candidates - changed_paths
    )
    normalized_seeds = explicit_seeds | (registration_candidates & changed_paths)

    affected_capabilities, dependency_paths, ownership_ids, mapped_changed = (
        _capability_neighborhood(catalog, snapshot, changed_paths)
    )
    if mode == "baseline":
        frontier_records: list[dict[str, Any]] = []
    elif mode == "drift":
        frontier_records = records
    else:
        seed_capabilities, seed_dependencies, seed_owners, seed_mapped = (
            _capability_neighborhood(catalog, snapshot, normalized_seeds)
        )
        affected_capabilities = seed_capabilities
        dependency_paths = seed_dependencies
        ownership_ids = seed_owners
        mapped_changed = seed_mapped
        frontier_paths = normalized_seeds | (changed_paths & dependency_paths)
        frontier_records = [
            record
            for record in records
            if str(record["old_path"]) in frontier_paths
            or str(record["new_path"]) in frontier_paths
        ]

    receipts = _read_frontier_receipts(
        baseline_reader,
        target_reader,
        frontier_records,
    )
    unmapped_changed = sorted(changed_paths - mapped_changed)
    hidden_reasons = [
        "Architecture Memory is bounded and does not contain a complete dependency graph.",
        "Path and evidence co-membership identifies a review neighborhood but cannot prove all runtime dependencies.",
    ]
    if mode == "local-change":
        hidden_reasons.append(
            "Paths outside the explicit local frontier were not read; use drift mode when a release or broad architecture decision requires a full admitted delta."
        )
    created_at = utc_now_iso()
    scan_basis = {
        "baseline_tree": snapshot.source_tree,
        "target_tree": target_identity.tree,
        "mode": mode,
        "seed_paths": sorted(normalized_seeds),
        "deferred_unobserved_registration_paths": deferred_unobserved_registration_paths,
        "frontier_changes": frontier_records,
    }
    scan_id = _digest(scan_basis)
    payload = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "incremental-reconstruction-complete",
        "created_at": created_at,
        "scan_id": scan_id,
        "scan_mode": mode,
        "baseline": {
            "snapshot_id": snapshot.snapshot_id,
            "commit": snapshot.source_commit,
            "tree": snapshot.source_tree,
            "manifest_sha256": _digest(baseline_manifest),
        },
        "target": {
            "requested_ref": target_ref,
            "commit": target_identity.commit,
            "tree": target_identity.tree,
            "manifest_sha256": _digest(target_manifest),
            "self_scan_verdict": target_manifest["boundary"]["self_scan_verdict"],
        },
        "delta": {
            "admitted_change_count": len(records),
            "protected_excluded_change_count": len(protected_records),
            "changes": records,
            "protected_excluded_changes": protected_records,
        },
        "frontier": {
            "seed_paths": sorted(normalized_seeds),
            "deferred_unobserved_registration_paths": deferred_unobserved_registration_paths,
            "changed_frontier_paths": sorted(
                {
                    path
                    for record in frontier_records
                    for path in (str(record["old_path"]), str(record["new_path"]))
                }
            ),
            "dependency_neighborhood_paths": sorted(dependency_paths),
            "ownership_neighborhood_ids": sorted(ownership_ids),
            "capability_neighborhood_ids": sorted(affected_capabilities),
            "unmapped_changed_paths": unmapped_changed,
            "hidden_dependency_risk": {
                "status": "managed-not-eliminated",
                "reasons": hidden_reasons,
            },
        },
        "blob_reads": receipts,
        "checks": [
            {
                "check": "phase1-authority-revalidated",
                "status": "passed",
                "detail": "Phase 1 snapshot, evidence index, catalog, and baseline manifest were revalidated before the scan",
            },
            {
                "check": "target-observation-boundary",
                "status": "passed",
                "detail": "target commit/tree and protected-path exclusions were formally evaluated before target blob reads",
            },
            {
                "check": "protected-change-exclusion",
                "status": "passed",
                "detail": f"excluded {len(protected_records)} EKRI/.EKRI change records from the admitted delta",
            },
            {
                "check": "bounded-frontier-reads",
                "status": "passed",
                "detail": f"read {len(receipts['before'])} baseline and {len(receipts['after'])} target regular blobs in the selected frontier",
            },
            {
                "check": "hidden-dependency-risk-explicit",
                "status": "passed",
                "detail": "dependency completeness is not claimed and residual hidden-dependency risk remains visible",
            },
        ],
        "claim_ceiling": (
            "This scan proves the named immutable Git path delta and the receipts for regular blobs read inside the selected frontier. "
            "It does not prove semantic architecture change, complete dependency coverage, runtime behavior, or production readiness."
        ),
    }
    return _VerifiedIncrementalScan(
        payload=payload,
        snapshot=snapshot,
        capability_catalog=catalog,
        capability_ids=capability_ids,
    )


def _matching_change_records(
    registration: ChangeRegistration,
    scan: _VerifiedIncrementalScan,
) -> tuple[list[dict[str, Any]], list[str]]:
    records = _array(scan.payload.get("delta", {}).get("changes"), "scan changes")
    matched: list[dict[str, Any]] = []
    matched_paths: set[str] = set()
    expected = set(registration.expected_paths)
    for raw in records:
        record = _object(raw, "scan change")
        paths = {str(record.get("old_path", "")), str(record.get("new_path", ""))}
        intersections = expected & paths
        if intersections:
            matched.append(record)
            matched_paths.update(intersections)
    return matched, sorted(expected - matched_paths)


def verify_registered_change(
    registration: ChangeRegistration,
    *,
    scan: _VerifiedIncrementalScan,
    verification_trigger: str,
    requested_capability: str = "",
) -> _VerifiedEvolutionEvent:
    """Create a repository-surface evolution event from an internally verified scan."""
    if not isinstance(scan, _VerifiedIncrementalScan):
        raise EvolutionIntelligenceError(
            "change verification requires an internally verified incremental scan"
        )
    if registration.capability_id not in scan.capability_ids:
        raise EvolutionIntelligenceError(
            f"registration references an unknown baseline capability: {registration.capability_id}"
        )
    if not registration.expected_paths:
        raise EvolutionIntelligenceError(
            "registration has no expected paths and cannot be verified by repository observation"
        )
    if not deferred_verification_needed(
        registration,
        requested_capability=requested_capability,
        trigger=verification_trigger,
    ):
        raise EvolutionIntelligenceError(
            "the selected trigger does not require verification of this registration"
        )
    matched, missing = _matching_change_records(registration, scan)
    if missing:
        raise EvolutionIntelligenceError(
            "registered expected paths were not all observed: " + ", ".join(missing)
        )
    target_tree = _text(scan.payload.get("target", {}).get("tree"), "target tree", maximum=80)
    evidence = [
        {
            "evidence_ref": f"git-delta:{scan.payload['scan_id']}:{path}",
            "path": path,
            "scan_id": scan.payload["scan_id"],
        }
        for path in registration.expected_paths
    ]
    payload = {
        "event_id": _digest(
            {
                "change_id": registration.change_id,
                "target_tree": target_tree,
                "paths": registration.expected_paths,
            }
        ),
        "change_id": registration.change_id,
        "capability_id": registration.capability_id,
        "state": "verified",
        "verification_scope": "repository-surface",
        "observed_fact": {
            "knowledge_state": "observed-fact",
            "statement": "Every registered expected path changed in the admitted Git delta.",
            "matched_path_count": len(registration.expected_paths),
        },
        "registered_intent": {
            "change_kind": registration.change_kind,
            "summary": registration.summary,
            "knowledge_state": "registered-change",
            "semantic_claim_state": "not-independently-proven",
        },
        "decision_reference": registration.decision_reference,
        "baseline_tree": scan.payload["baseline"]["tree"],
        "target_tree": target_tree,
        "matched_changes": matched,
        "evidence": evidence,
        "verified_at": utc_now_iso(),
        "claim_ceiling": (
            "The scanner verified that every registered expected path changed in the admitted Git delta. "
            "It did not independently prove the caller's semantic intent, runtime behavior, or business acceptance."
        ),
    }
    return _VerifiedEvolutionEvent(payload=payload)


def _registration_ledger(
    registrations: Sequence[ChangeRegistration],
    scan: _VerifiedIncrementalScan,
    *,
    verification_trigger: str,
    requested_capability: str,
) -> tuple[dict[str, Any], list[_VerifiedEvolutionEvent]]:
    identifiers: set[str] = set()
    entries: list[dict[str, Any]] = []
    events: list[_VerifiedEvolutionEvent] = []
    for raw_registration in registrations:
        registration = _validated_registration_input(raw_registration)
        if registration.change_id in identifiers:
            raise EvolutionIntelligenceError(
                f"duplicate change registration id: {registration.change_id}"
            )
        identifiers.add(registration.change_id)
        if registration.capability_id not in scan.capability_ids:
            raise EvolutionIntelligenceError(
                f"registration references an unknown baseline capability: {registration.capability_id}"
            )
        matched, missing = _matching_change_records(registration, scan)
        verification_requested = deferred_verification_needed(
            registration,
            requested_capability=requested_capability,
            trigger=verification_trigger,
        )
        event: _VerifiedEvolutionEvent | None = None
        if verification_requested and registration.expected_paths and not missing:
            event = verify_registered_change(
                registration,
                scan=scan,
                verification_trigger=verification_trigger,
                requested_capability=requested_capability,
            )
            events.append(event)
            effective_state = "verified"
            verification_status = "verified"
            reason = "all registered expected paths were observed in the admitted Git delta"
        elif matched:
            effective_state = "observed"
            verification_status = "pending"
            reason = (
                "some expected paths were observed but verification remains deferred or incomplete"
            )
        else:
            effective_state = registration.state
            verification_status = "pending"
            reason = "no registered expected path was observed in this scan"
        entries.append(
            {
                **asdict(registration),
                "expected_paths": list(registration.expected_paths),
                "effective_state": effective_state,
                "verification": {
                    "requested": verification_requested,
                    "status": verification_status,
                    "reason": reason,
                    "matched_paths": sorted(
                        {
                            path
                            for record in matched
                            for path in (
                                str(record.get("old_path", "")),
                                str(record.get("new_path", "")),
                            )
                            if path in registration.expected_paths
                        }
                    ),
                    "missing_expected_paths": missing,
                    "event_id": event.payload["event_id"] if event else "",
                },
            }
        )
    ledger = {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "change-register-evaluated",
        "created_at": utc_now_iso(),
        "source_tree": scan.payload["target"]["tree"],
        "registrations": entries,
        "counts": {
            "total": len(entries),
            "verified": sum(item["effective_state"] == "verified" for item in entries),
            "observed_pending": sum(item["effective_state"] == "observed" for item in entries),
            "unobserved_pending": sum(
                item["effective_state"] in {"registered", "planned"} for item in entries
            ),
        },
        "claim_ceiling": (
            "Registrations are intent signals. Only entries linked to an internally verified repository-surface event enter the Architecture Evolution Map."
        ),
    }
    return ledger, events


def build_architecture_evolution_map(
    scan: _VerifiedIncrementalScan,
    verified_events: Sequence[_VerifiedEvolutionEvent],
    registration_ledger: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(scan, _VerifiedIncrementalScan):
        raise EvolutionIntelligenceError(
            "Architecture Evolution requires an internally verified incremental scan"
        )
    events: list[dict[str, Any]] = []
    for event in verified_events:
        if not isinstance(event, _VerifiedEvolutionEvent):
            raise EvolutionIntelligenceError(
                "Architecture Evolution accepts only internally verified events"
            )
        observed_fact = _object(event.payload.get("observed_fact"), "event observed_fact")
        registered_intent = _object(
            event.payload.get("registered_intent"), "event registered_intent"
        )
        if (
            event.payload.get("state") != "verified"
            or observed_fact.get("knowledge_state") != "observed-fact"
            or registered_intent.get("knowledge_state") != "registered-change"
        ):
            raise EvolutionIntelligenceError("invalid verified evolution event")
        events.append(event.payload)
    return {
        "schema_version": EVOLUTION_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "architecture-evolution-map-built",
        "created_at": utc_now_iso(),
        "source": {
            "baseline_commit": scan.payload["baseline"]["commit"],
            "baseline_tree": scan.payload["baseline"]["tree"],
            "target_commit": scan.payload["target"]["commit"],
            "target_tree": scan.payload["target"]["tree"],
            "scan_id": scan.payload["scan_id"],
        },
        "verified_event_count": len(events),
        "architecture_evolution": sorted(events, key=lambda item: item["change_id"]),
        "pending_registration_count": registration_ledger["counts"]["total"]
        - registration_ledger["counts"]["verified"],
        "claim_ceiling": (
            "This map contains only repository-surface changes verified against registered expected paths. "
            "It is not a Git-log summary and does not prove complete semantic architecture history or runtime behavior."
        ),
    }


def build_change_impact_map(
    scan: _VerifiedIncrementalScan,
    requests: Sequence[ChangeImpactRequest],
    registration_ledger: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(scan, _VerifiedIncrementalScan):
        raise EvolutionIntelligenceError(
            "Change Impact requires an internally verified incremental scan"
        )
    registration_ids = {
        str(item["change_id"])
        for item in _array(registration_ledger.get("registrations"), "registrations")
    }
    impacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, ChangeImpactRequest):
            raise EvolutionIntelligenceError(
                "impact requests must contain ChangeImpactRequest values"
            )
        if request.change_id not in registration_ids:
            raise EvolutionIntelligenceError(
                f"impact request references an unknown change registration: {request.change_id}"
            )
        capability_references = {
            request.capability_id,
            *request.affected_capability_ids,
        }
        unknown_capabilities = sorted(capability_references - set(scan.capability_ids))
        if unknown_capabilities:
            raise EvolutionIntelligenceError(
                "impact request references unknown capabilities: "
                + ", ".join(unknown_capabilities)
            )
        unknown_evidence = sorted(
            set(request.evidence_refs) - set(scan.snapshot.evidence_refs)
        )
        if unknown_evidence:
            raise EvolutionIntelligenceError(
                "impact request references unknown baseline evidence: "
                + ", ".join(unknown_evidence)
            )
        impact_id = _digest(asdict(request))
        if impact_id in seen:
            raise EvolutionIntelligenceError("duplicate change impact request")
        seen.add(impact_id)
        impacts.append(
            {
                "impact_id": impact_id,
                "change_id": request.change_id,
                "capability_id": request.capability_id,
                "affected_capability_ids": list(request.affected_capability_ids),
                "classification": request.classification,
                "knowledge_state": (
                    "unknown"
                    if request.classification == "unknown"
                    else "inferred-knowledge"
                ),
                "confidence": (
                    "not-applicable"
                    if request.classification == "unknown"
                    else "medium"
                ),
                "rationale": request.rationale,
                "evidence_refs": list(request.evidence_refs),
                "truth_boundary": "prediction-not-architecture-fact",
            }
        )
    return {
        "schema_version": IMPACT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "change-impact-map-built",
        "created_at": utc_now_iso(),
        "source": {
            "baseline_tree": scan.payload["baseline"]["tree"],
            "target_tree": scan.payload["target"]["tree"],
            "scan_id": scan.payload["scan_id"],
        },
        "impact_count": len(impacts),
        "change_impacts": sorted(impacts, key=lambda item: item["impact_id"]),
        "claim_ceiling": (
            "Change Impact predicts possible future effects from baseline evidence and caller reasoning. "
            "It never becomes observed architecture truth, implementation proof, or acceptance authority."
        ),
    }


def _build_snapshot_refresh(
    scan: _VerifiedIncrementalScan,
    registration_ledger: dict[str, Any],
    evolution_map: dict[str, Any],
    *,
    release_verification: bool,
    release_reference: str,
) -> dict[str, Any]:
    if release_verification:
        if scan.payload["scan_mode"] != "drift":
            raise EvolutionIntelligenceError(
                "release verification requires a full admitted drift scan"
            )
        reference = _text(release_reference, "release_reference", minimum=2, maximum=240)
        try:
            release_identity = resolve_git_target(
                scan.snapshot.repository_root,
                target_ref=reference,
            )
        except ObservationBoundaryError as exc:
            raise EvolutionIntelligenceError(
                f"release reference cannot be resolved: {exc}"
            ) from exc
        if release_identity.commit != scan.payload["target"]["commit"]:
            raise EvolutionIntelligenceError(
                "release reference does not resolve to the scanned target commit"
            )
        refresh_status = "release-snapshot-refresh-complete"
    else:
        reference = ""
        refresh_status = "incremental-snapshot-refresh-complete"
    pending = [
        item["change_id"]
        for item in registration_ledger["registrations"]
        if item["effective_state"] != "verified"
    ]
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": refresh_status,
        "created_at": utc_now_iso(),
        "base_snapshot_id": scan.snapshot.snapshot_id,
        "source": {
            "baseline_commit": scan.payload["baseline"]["commit"],
            "baseline_tree": scan.payload["baseline"]["tree"],
            "target_commit": scan.payload["target"]["commit"],
            "target_tree": scan.payload["target"]["tree"],
            "target_manifest_sha256": scan.payload["target"]["manifest_sha256"],
            "scan_id": scan.payload["scan_id"],
        },
        "release_verification": {
            "requested": release_verification,
            "release_reference": reference,
            "policy": "project-governance-post-release-refresh",
        },
        "verified_evolution_event_ids": [
            item["event_id"] for item in evolution_map["architecture_evolution"]
        ],
        "pending_registration_ids": sorted(pending),
        "unmapped_changed_paths": scan.payload["frontier"]["unmapped_changed_paths"],
        "overlay_model": "verified-evolution-over-phase1-baseline",
        "claim_ceiling": (
            "This refresh binds the verified Phase 1 baseline to the named target tree and verified evolution overlay. "
            "It does not silently rewrite the original Architecture Memory or claim exhaustive reconstruction of every changed semantic."
        ),
    }


def render_phase3_markdown(
    scan: dict[str, Any],
    registration_ledger: dict[str, Any],
    evolution_map: dict[str, Any],
    impact_map: dict[str, Any],
    snapshot_refresh: dict[str, Any],
) -> str:
    lines = [
        "# EKRI Phase 3 — Evolution and Impact",
        "",
        f"- Baseline commit: `{scan['baseline']['commit']}`",
        f"- Baseline tree: `{scan['baseline']['tree']}`",
        f"- Target commit: `{scan['target']['commit']}`",
        f"- Target tree: `{scan['target']['tree']}`",
        f"- Scan mode: `{scan['scan_mode']}`",
        f"- Admitted changes: `{scan['delta']['admitted_change_count']}`",
        f"- Protected changes excluded: `{scan['delta']['protected_excluded_change_count']}`",
        "",
        "## Incremental Reconstruction Frontier",
        "",
        "- Seed paths: "
        + (", ".join(f"`{item}`" for item in scan["frontier"]["seed_paths"]) or "none"),
        "- Capability neighborhood: "
        + (", ".join(f"`{item}`" for item in scan["frontier"]["capability_neighborhood_ids"]) or "none"),
        "- Hidden dependency risk: `managed-not-eliminated`",
        "",
        "## Change Register",
        "",
        f"- Total: `{registration_ledger['counts']['total']}`",
        f"- Verified: `{registration_ledger['counts']['verified']}`",
        f"- Observed pending: `{registration_ledger['counts']['observed_pending']}`",
        f"- Unobserved pending: `{registration_ledger['counts']['unobserved_pending']}`",
        "",
        "## Architecture Evolution Map",
        "",
    ]
    if evolution_map["architecture_evolution"]:
        for event in evolution_map["architecture_evolution"]:
            lines.append(
                f"- `{event['change_id']}` / `{event['capability_id']}` / "
                f"`{event['registered_intent']['change_kind']}`: repository-surface verified; "
                f"semantic intent remains `{event['registered_intent']['knowledge_state']}`"
            )
    else:
        lines.append("- No registration reached verified evolution state.")
    lines.extend(["", "## Change Impact Map", ""])
    if impact_map["change_impacts"]:
        for impact in impact_map["change_impacts"]:
            lines.append(
                f"- `{impact['change_id']}` -> `{impact['classification']}` / "
                f"`{impact['knowledge_state']}`: {impact['rationale']}"
            )
    else:
        lines.append("- No future-impact inference supplied.")
    lines.extend(
        [
            "",
            "## Snapshot Refresh",
            "",
            f"- Status: `{snapshot_refresh['status']}`",
            f"- Overlay model: `{snapshot_refresh['overlay_model']}`",
            f"- Pending registrations: `{len(snapshot_refresh['pending_registration_ids'])}`",
            "",
            "## Claim Ceiling",
            "",
            evolution_map["claim_ceiling"],
            "",
            impact_map["claim_ceiling"],
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
        raise EvolutionIntelligenceError(
            f"failed to atomically persist Phase 3 output {filename}: {exc}"
        ) from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _build_audit(
    scan: dict[str, Any],
    registration_ledger: dict[str, Any],
    evolution_map: dict[str, Any],
    impact_map: dict[str, Any],
    snapshot_refresh: dict[str, Any],
    markdown: str,
) -> dict[str, Any]:
    payloads = {
        "incremental-reconstruction.json": _json_bytes(scan),
        "change-register.json": _json_bytes(registration_ledger),
        "architecture-evolution-map.json": _json_bytes(evolution_map),
        "change-impact-map.json": _json_bytes(impact_map),
        "architecture-snapshot-refresh.json": _json_bytes(snapshot_refresh),
        "PHASE3_EVOLUTION.md": markdown.encode("utf-8"),
    }
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "phase3-output-audit-complete",
        "created_at": utc_now_iso(),
        "source_tree": scan["target"]["tree"],
        "bindings": {
            "scan_id": scan["scan_id"],
            "baseline_manifest_sha256": scan["baseline"]["manifest_sha256"],
            "target_manifest_sha256": scan["target"]["manifest_sha256"],
            "evolution_map_sha256": _digest(evolution_map),
            "impact_map_sha256": _digest(impact_map),
            "snapshot_refresh_sha256": _digest(snapshot_refresh),
        },
        "output_digests": {
            name: _sha256(raw) for name, raw in sorted(payloads.items())
        },
        "checks": [
            {
                "check": "intent-fact-separation",
                "status": "passed",
                "detail": "unverified registrations remain outside Architecture Evolution",
            },
            {
                "check": "manifest-evidence-chain",
                "status": "passed",
                "detail": "baseline and target observation-manifest digests bind the incremental scan",
            },
            {
                "check": "impact-truth-boundary",
                "status": "passed",
                "detail": "all non-unknown impact entries remain inferred knowledge",
            },
            {
                "check": "no-follow-atomic-persistence",
                "status": "passed",
                "detail": "outputs are written through real-directory descriptors and atomic replacement",
            },
        ],
        "claim_ceiling": (
            "This audit proves output binding and persistence integrity. It does not raise the semantic claim ceiling of reconstruction, evolution, or impact results."
        ),
    }


def _persist_outputs(
    repository_root: Path,
    *,
    scan: dict[str, Any],
    registration_ledger: dict[str, Any],
    evolution_map: dict[str, Any],
    impact_map: dict[str, Any],
    snapshot_refresh: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    target_tree = _text(scan.get("target", {}).get("tree"), "target tree", maximum=80)
    if any(
        payload.get("source", {}).get("target_tree", target_tree) != target_tree
        for payload in (evolution_map, impact_map, snapshot_refresh)
    ):
        raise EvolutionIntelligenceError("Phase 3 output target-tree identities diverge")
    markdown = render_phase3_markdown(
        scan,
        registration_ledger,
        evolution_map,
        impact_map,
        snapshot_refresh,
    )
    audit = _build_audit(
        scan,
        registration_ledger,
        evolution_map,
        impact_map,
        snapshot_refresh,
        markdown,
    )
    files = {
        "incremental-reconstruction.json": _json_bytes(scan),
        "change-register.json": _json_bytes(registration_ledger),
        "architecture-evolution-map.json": _json_bytes(evolution_map),
        "change-impact-map.json": _json_bytes(impact_map),
        "architecture-snapshot-refresh.json": _json_bytes(snapshot_refresh),
        "PHASE3_EVOLUTION.md": markdown.encode("utf-8"),
        "phase3-audit.json": _json_bytes(audit),
    }
    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "evolution", target_tree):
            try:
                descriptor = _open_or_create_directory(parent_fd, component)
            except ObservationBoundaryError as exc:
                raise EvolutionIntelligenceError(
                    f"Phase 3 output directory is unsafe: {exc}"
                ) from exc
            opened.append(descriptor)
            parent_fd = descriptor
        for filename, payload in files.items():
            _secure_atomic_write(parent_fd, filename, payload)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)
    output_root = repository_root / ".EKRI" / "evolution" / target_tree
    return (
        {
            "output_root": str(output_root),
            **{name: str(output_root / name) for name in files},
        },
        audit,
    )


def run_phase3_evolution_analysis(
    repository_root: str | Path,
    *,
    target_ref: str,
    registrations: Sequence[ChangeRegistration] = (),
    impact_requests: Sequence[ChangeImpactRequest] = (),
    scan_mode: str = "local-change",
    seed_paths: Sequence[str] = (),
    verification_trigger: str = "explicit-request",
    requested_capability: str = "",
    release_verification: bool = False,
    release_reference: str = "",
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Run the controlled Phase 3 scan, evolution, impact, refresh, and audit path."""
    root = _absolute_path(repository_root)
    if not root.is_dir():
        raise EvolutionIntelligenceError(f"repository root is not a directory: {root}")
    trigger = _text(verification_trigger, "verification_trigger", maximum=80)
    if trigger not in VERIFICATION_TRIGGERS:
        raise EvolutionIntelligenceError("unsupported verification_trigger")
    if release_verification != (trigger == "release-verification"):
        raise EvolutionIntelligenceError(
            "release_verification and verification_trigger=release-verification must be selected together"
        )
    canonical_registrations = tuple(
        _validated_registration_input(registration) for registration in registrations
    )
    registration_seeds = {
        path
        for registration in canonical_registrations
        if deferred_verification_needed(
            registration,
            requested_capability=requested_capability,
            trigger=trigger,
        )
        for path in registration.expected_paths
    }
    snapshot, catalog, capability_ids, baseline_manifest = _load_phase3_authority(root)
    scan = _build_incremental_scan(
        root,
        snapshot=snapshot,
        catalog=catalog,
        capability_ids=capability_ids,
        baseline_manifest=baseline_manifest,
        target_ref=target_ref,
        scan_mode=scan_mode,
        seed_paths=seed_paths,
        registered_seed_paths=tuple(sorted(registration_seeds)),
        persist_target_manifest=write_outputs,
    )
    registration_ledger, verified_events = _registration_ledger(
        canonical_registrations,
        scan,
        verification_trigger=trigger,
        requested_capability=requested_capability,
    )
    evolution_map = build_architecture_evolution_map(
        scan,
        verified_events,
        registration_ledger,
    )
    impact_map = build_change_impact_map(
        scan,
        impact_requests,
        registration_ledger,
    )
    snapshot_refresh = _build_snapshot_refresh(
        scan,
        registration_ledger,
        evolution_map,
        release_verification=release_verification,
        release_reference=release_reference,
    )
    markdown = render_phase3_markdown(
        scan.payload,
        registration_ledger,
        evolution_map,
        impact_map,
        snapshot_refresh,
    )
    audit = _build_audit(
        scan.payload,
        registration_ledger,
        evolution_map,
        impact_map,
        snapshot_refresh,
        markdown,
    )
    outputs: dict[str, str] = {}
    if write_outputs:
        outputs, audit = _persist_outputs(
            root,
            scan=scan.payload,
            registration_ledger=registration_ledger,
            evolution_map=evolution_map,
            impact_map=impact_map,
            snapshot_refresh=snapshot_refresh,
        )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": VALID_STATUS,
        "scan": scan.payload,
        "change_register": registration_ledger,
        "architecture_evolution_map": evolution_map,
        "change_impact_map": impact_map,
        "snapshot_refresh": snapshot_refresh,
        "audit": audit,
        "outputs": outputs,
        "claim_ceiling": (
            "Phase 3 provides bounded incremental Git evidence, repository-surface evolution verification, deferred registration state, and inferred impact. "
            "It does not prove exhaustive architecture history, complete dependency impact, semantic implementation correctness, release readiness, or production behavior."
        ),
    }
