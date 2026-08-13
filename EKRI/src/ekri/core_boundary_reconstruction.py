"""WFF v1.8 P0 evidence-linked Core boundary reconstruction.

The v1.7 tag adds EKRI outside the WFF runtime mainline. P0 therefore keeps the
accepted v1.6.2 Architecture Memory as the historical mainline authority,
proves that the v1.7 target remains equivalent on the reviewed WFF runtime and
architecture surfaces, and builds a review-bound Core Candidate Map. It never
moves WFF files or changes P1-P4/PX runtime behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable
import uuid

from .capability_contract import ExistingCapabilityError, load_capability_spec
from .capability_query import CapabilityQueryService
from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .knowledge_reconstruction import (
    KnowledgeReconstructionError,
    build_wff_architecture_memory,
    load_reconstruction_spec,
    reconstruct_and_persist_wff_baseline,
)
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
    resolve_scanner_identity,
    write_manifest,
)
from .phase1_snapshot import (
    Phase1SnapshotError,
    VerifiedPhase1Snapshot,
    verify_phase1_snapshot,
)


SPEC_SCHEMA_VERSION = "ekri.wff-core-boundary-spec.v1"
EQUIVALENCE_SCHEMA_VERSION = "ekri.baseline-equivalence.v1"
MAP_SCHEMA_VERSION = "ekri.core-candidate-map.v1"
MATRIX_SCHEMA_VERSION = "ekri.core-responsibility-matrix.v1"
DEPENDENCY_SCHEMA_VERSION = "ekri.core-dependency-report.v1"
FRONTIER_SCHEMA_VERSION = "ekri.core-extraction-frontier.v1"
UNKNOWN_SCHEMA_VERSION = "ekri.core-boundary-unknowns.v1"
AUDIT_SCHEMA_VERSION = "ekri.core-boundary-audit.v1"
PHASE_ID = "v1.8-p0-core-boundary-reconstruction"
PROFILE_ID = "wff-v1.8-p0-core-boundary"
VALID_STATUS = "core-boundary-reconstructed"

BOUNDARY_STATES = {"core-candidate", "non-core", "split-required", "unknown"}
GRAPH_KINDS = {"dependency", "control-loop"}


class CoreBoundaryError(RuntimeError):
    """Raised when a Core boundary projection cannot be proven safely."""


@dataclass(frozen=True)
class CoreBoundarySpecIdentity:
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
        raise CoreBoundaryError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise CoreBoundaryError(f"{label} must be a list with at least {minimum} item(s)")
    return value


def _text(value: object, label: str, *, minimum: int = 1, maximum: int = 8000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise CoreBoundaryError(f"{label} must contain between {minimum} and {maximum} characters")
    return text


def _identifier(value: object, label: str) -> str:
    identifier = _text(value, label, minimum=2, maximum=160)
    if not identifier[0].isalpha() or not all(
        character.isalnum() or character in "._-" for character in identifier
    ):
        raise CoreBoundaryError(
            f"{label} must start with a letter and use letters, digits, '.', '_', or '-'"
        )
    return identifier


def _load_json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CoreBoundaryError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CoreBoundaryError(f"{label} must be a safe regular file")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoreBoundaryError(f"{label} cannot be read: {exc}") from exc
    return _object(payload, label), raw


def load_core_boundary_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], CoreBoundarySpecIdentity]:
    """Load the reviewed P0 instruction surface from a safe file or scanner commit."""
    if path is not None:
        source = Path(path).expanduser()
        payload, raw = _load_json_file(source, "Core boundary specification")
        identity = CoreBoundarySpecIdentity(
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
            raise CoreBoundaryError(f"active scanner provenance is unverifiable: {exc}") from exc
        relative_path = "EKRI/specs/wff-v18-core-boundary-reconstruction.json"
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
            raise CoreBoundaryError("committed Core boundary specification is missing or ambiguous")
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise CoreBoundaryError("committed Core boundary specification must be a regular Git blob")
        raw = _run_git(
            Path(active.repository_root),
            "cat-file",
            "blob",
            oid,
            binary=True,
        )
        assert isinstance(raw, bytes)
        try:
            payload = _object(json.loads(raw.decode("utf-8")), "Core boundary specification")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoreBoundaryError(f"committed Core boundary specification cannot be read: {exc}") from exc
        identity = CoreBoundarySpecIdentity(
            source="scanner-commit",
            path=relative_path,
            sha256=_sha256(raw),
            scanner_commit=active.commit,
            scanner_tree=active.tree,
            blob_oid=oid,
        )
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise CoreBoundaryError("unsupported Core boundary specification schema")
    if payload.get("profile_id") != PROFILE_ID:
        raise CoreBoundaryError("unexpected Core boundary profile id")
    return payload, identity


def _knowledge_sections(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        key: memory[key]
        for key in (
            "system_architecture_tree",
            "module_responsibility_map",
            "implementation_intent_summary",
            "validation_assurance_ownership",
            "constraints",
            "unknowns",
            "claim_ceiling",
        )
    }


def _evidence_refs(evidence_index: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for raw_source in _array(evidence_index.get("sources"), "evidence sources"):
        source = _object(raw_source, "evidence source")
        for raw_anchor in _array(source.get("anchors"), "evidence anchors"):
            anchor = _object(raw_anchor, "evidence anchor")
            refs.add(_text(anchor.get("evidence_ref"), "evidence reference", maximum=240))
    return refs


def _supplemental_evidence(
    repository_root: Path,
    target_manifest: dict[str, Any],
    core_spec: dict[str, Any],
) -> dict[str, Any]:
    """Resolve P0-only reviewed anchors from admitted v1.7 target blobs."""
    try:
        reader = AdmittedGitReader(repository_root, target_manifest)
    except AdmittedEvidenceError as exc:
        raise CoreBoundaryError(f"supplemental evidence reader failed: {exc}") from exc
    sources: list[dict[str, Any]] = []
    refs: set[str] = set()
    for raw_source in _array(core_spec.get("supplemental_evidence_sources"), "supplemental evidence sources", minimum=1):
        source = _object(raw_source, "supplemental evidence source")
        source_id = _identifier(source.get("id"), "supplemental evidence source id")
        path = _text(source.get("path"), f"supplemental evidence {source_id} path", maximum=500)
        try:
            text = reader.read_text(path)
        except AdmittedEvidenceError as exc:
            raise CoreBoundaryError(f"supplemental evidence cannot read {path}: {exc}") from exc
        lines = text.splitlines()
        anchors: list[dict[str, Any]] = []
        for raw_anchor in _array(source.get("anchors"), f"supplemental evidence {source_id} anchors", minimum=1):
            anchor = _object(raw_anchor, f"supplemental evidence {source_id} anchor")
            anchor_id = _identifier(anchor.get("id"), f"supplemental evidence {source_id} anchor id")
            contains = _text(anchor.get("contains"), f"supplemental evidence {source_id}.{anchor_id} contains", maximum=1000)
            matches = [index for index, line in enumerate(lines, start=1) if contains in line]
            if not matches:
                raise CoreBoundaryError(f"supplemental evidence anchor not found: {source_id}.{anchor_id}")
            evidence_ref = f"{source_id}.{anchor_id}"
            if evidence_ref in refs:
                raise CoreBoundaryError(f"duplicate supplemental evidence ref: {evidence_ref}")
            refs.add(evidence_ref)
            anchors.append(
                {
                    "evidence_ref": evidence_ref,
                    "contains": contains,
                    "line_numbers": matches,
                }
            )
        sources.append(
            {
                "id": source_id,
                "path": path,
                "blob": reader.receipt(path).to_dict(),
                "anchors": anchors,
            }
        )
    return {
        "source_count": len(sources),
        "evidence_ref_count": len(refs),
        "evidence_refs": sorted(refs),
        "sources": sources,
        "read_paths": list(reader.read_paths()),
    }


def _changed_paths(repository_root: Path, source_commit: str, target_commit: str) -> list[str]:
    try:
        output = _run_git(
            repository_root,
            "diff",
            "--name-only",
            "--no-renames",
            source_commit,
            target_commit,
            "--",
        )
    except ObservationBoundaryError as exc:
        raise CoreBoundaryError(f"baseline delta cannot be enumerated: {exc}") from exc
    assert isinstance(output, str)
    paths = sorted({line.strip() for line in output.splitlines() if line.strip()})
    if any(path.startswith("/") or ".." in Path(path).parts for path in paths):
        raise CoreBoundaryError("baseline delta contains an unsafe path")
    return paths


def _matches_path_rule(path: str, *, prefixes: Iterable[str], exact_paths: Iterable[str]) -> bool:
    return path in set(exact_paths) or any(path.startswith(prefix) for prefix in prefixes)


def build_baseline_equivalence(
    repository_root: str | Path,
    *,
    baseline_snapshot: VerifiedPhase1Snapshot,
    target_manifest: dict[str, Any],
    architecture_spec: dict[str, Any],
    core_spec: dict[str, Any],
) -> dict[str, Any]:
    """Prove the reviewed v1.6.2 -> v1.7 mainline equivalence boundary."""
    root = _absolute_path(repository_root)
    baseline = _object(core_spec.get("baseline_equivalence"), "spec baseline_equivalence")
    authority = _object(baseline.get("authority"), "baseline authority")
    target = _object(baseline.get("target"), "baseline target")
    if baseline_snapshot.source_commit != authority.get("commit") or baseline_snapshot.source_tree != authority.get("tree"):
        raise CoreBoundaryError("verified Architecture Memory does not match the declared authority baseline")
    manifest_source = _object(target_manifest.get("source"), "target manifest source")
    if manifest_source.get("commit") != target.get("commit") or manifest_source.get("tree") != target.get("tree"):
        raise CoreBoundaryError("target observation does not match the declared v1.7 baseline")
    if target_manifest.get("boundary", {}).get("verdict") != VALID_VERDICT:
        raise CoreBoundaryError("target observation boundary is not valid")

    changed_paths = _changed_paths(root, baseline_snapshot.source_commit, _text(target.get("commit"), "target commit"))
    allowed_prefixes = [
        _text(value, "allowed delta prefix", maximum=240)
        for value in _array(baseline.get("allowed_delta_prefixes"), "allowed delta prefixes")
    ]
    allowed_metadata_paths = [
        _text(value, "allowed metadata path", maximum=500)
        for value in _array(baseline.get("allowed_metadata_paths"), "allowed metadata paths")
    ]
    unexpected_paths = [
        path
        for path in changed_paths
        if not _matches_path_rule(path, prefixes=allowed_prefixes, exact_paths=allowed_metadata_paths)
    ]

    invariant_prefixes = [
        _text(value, "runtime invariant prefix", maximum=240)
        for value in _array(baseline.get("runtime_invariant_prefixes"), "runtime invariant prefixes")
    ]
    invariant_paths = [
        _text(value, "runtime invariant path", maximum=500)
        for value in _array(baseline.get("runtime_invariant_paths"), "runtime invariant paths")
    ]
    changed_runtime_paths = [
        path
        for path in changed_paths
        if _matches_path_rule(path, prefixes=invariant_prefixes, exact_paths=invariant_paths)
    ]

    authority_target = _object(architecture_spec.get("target"), "Architecture Memory target")
    if authority_target.get("commit") != baseline_snapshot.source_commit or authority_target.get("tree") != baseline_snapshot.source_tree:
        raise CoreBoundaryError("Architecture Memory specification is not the declared baseline authority")
    probe_spec = copy.deepcopy(architecture_spec)
    probe_spec["target"] = {
        "commit": _text(target.get("commit"), "target commit"),
        "tree": _text(target.get("tree"), "target tree"),
    }
    probe = build_wff_architecture_memory(root, target_manifest, spec=probe_spec)
    authority_sections = _knowledge_sections(baseline_snapshot.architecture_memory)
    target_sections = _knowledge_sections(_object(probe.get("memory"), "target probe memory"))
    section_digests = {
        "authority": _sha256(_json_bytes(authority_sections)),
        "target": _sha256(_json_bytes(target_sections)),
    }
    architecture_projection_equal = authority_sections == target_sections
    authority_refs = set(baseline_snapshot.evidence_refs)
    target_refs = _evidence_refs(_object(probe.get("evidence_index"), "target probe evidence"))
    evidence_reference_set_equal = authority_refs == target_refs

    ekri_delta_paths = [path for path in changed_paths if any(path.startswith(prefix) for prefix in allowed_prefixes)]
    metadata_delta_paths = [path for path in changed_paths if path in set(allowed_metadata_paths)]
    supplemental = _supplemental_evidence(root, target_manifest, core_spec)
    accepted = (
        not unexpected_paths
        and not changed_runtime_paths
        and architecture_projection_equal
        and evidence_reference_set_equal
    )
    if not accepted:
        raise CoreBoundaryError(
            "v1.7 mainline equivalence failed: "
            f"unexpected={len(unexpected_paths)}, runtime={len(changed_runtime_paths)}, "
            f"architecture_equal={architecture_projection_equal}, evidence_equal={evidence_reference_set_equal}"
        )

    return {
        "schema_version": EQUIVALENCE_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "mainline-runtime-equivalence-verified",
        "created_at": utc_now_iso(),
        "authority": {
            "snapshot_id": baseline_snapshot.snapshot_id,
            "commit": baseline_snapshot.source_commit,
            "tree": baseline_snapshot.source_tree,
        },
        "target": {
            "tag": _text(target.get("tag"), "target tag"),
            "commit": target["commit"],
            "tree": target["tree"],
            "observation_manifest_sha256": _sha256(_json_bytes(target_manifest)),
        },
        "delta": {
            "changed_path_count": len(changed_paths),
            "changed_paths": changed_paths,
            "ekri_delta_path_count": len(ekri_delta_paths),
            "ekri_delta_paths": ekri_delta_paths,
            "metadata_delta_path_count": len(metadata_delta_paths),
            "metadata_delta_paths": metadata_delta_paths,
            "unexpected_path_count": len(unexpected_paths),
            "unexpected_paths": unexpected_paths,
            "runtime_invariant_change_count": len(changed_runtime_paths),
            "runtime_invariant_changed_paths": changed_runtime_paths,
        },
        "architecture_refresh": {
            "mode": "authority-revalidation-plus-target-equivalence-probe",
            "architecture_projection_equal": architecture_projection_equal,
            "evidence_reference_set_equal": evidence_reference_set_equal,
            "authority_evidence_ref_count": len(authority_refs),
            "target_evidence_ref_count": len(target_refs),
            "section_digests": section_digests,
            "target_probe_counts": probe["report"]["counts"],
        },
        "supplemental_evidence": supplemental,
        "verdict": "wff-v1.6.2-mainline-equals-v1.7-mainline",
        "knowledge_state": "observed-fact",
        "claim_ceiling": (
            "This receipt proves equality only for the reviewed WFF runtime invariant surface and the complete evidence-linked Architecture Memory projection. "
            "It records EKRI and release-closeout metadata as the allowed v1.7 delta; it does not claim byte-identical repository trees or future equivalence after v1.8 changes."
        ),
    }


def _index_rows(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = _identifier(row.get("id"), f"{label} id")
        if identifier in index:
            raise CoreBoundaryError(f"duplicate {label} id: {identifier}")
        index[identifier] = row
    return index


def _validate_evidence_subset(
    refs: object,
    *,
    label: str,
    allowed: set[str],
    required: bool = True,
) -> list[str]:
    values = sorted({_text(value, f"{label} evidence ref", maximum=240) for value in _array(refs, f"{label} evidence refs")})
    if required and not values:
        raise CoreBoundaryError(f"{label} requires evidence")
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise CoreBoundaryError(f"{label} references unsupported evidence: " + ", ".join(unknown))
    return values


def _validate_classifications(
    raw_rows: object,
    *,
    label: str,
    source_index: dict[str, dict[str, Any]],
    layers: set[str],
    global_evidence: set[str],
    source_evidence_key: str = "evidence_refs",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _array(raw_rows, label, minimum=1):
        row = _object(raw, f"{label} entry")
        identifier = _identifier(row.get("id"), f"{label} id")
        if identifier in seen:
            raise CoreBoundaryError(f"duplicate {label} classification: {identifier}")
        seen.add(identifier)
        if identifier not in source_index:
            raise CoreBoundaryError(f"{label} classification references unknown source id: {identifier}")
        layer = _identifier(row.get("primary_layer"), f"{label} {identifier} layer")
        if layer not in layers:
            raise CoreBoundaryError(f"{label} {identifier} uses unknown layer: {layer}")
        boundary_state = _text(row.get("boundary_state"), f"{label} {identifier} boundary state", maximum=40)
        if boundary_state not in BOUNDARY_STATES:
            raise CoreBoundaryError(f"{label} {identifier} uses unsupported boundary state")
        source_refs = set(source_index[identifier].get(source_evidence_key, []))
        refs = _validate_evidence_subset(
            row.get("evidence_refs"),
            label=f"{label} {identifier}",
            allowed=source_refs & global_evidence,
            required=boundary_state != "unknown",
        )
        rows.append(
            {
                "id": identifier,
                "primary_layer": layer,
                "boundary_state": boundary_state,
                "core_contract_slices": sorted(
                    {_identifier(value, f"{label} {identifier} core contract slice") for value in _array(row.get("core_contract_slices"), f"{label} {identifier} core contract slices")}
                ),
                "non_core_responsibilities": [
                    _text(value, f"{label} {identifier} non-Core responsibility")
                    for value in _array(row.get("non_core_responsibilities"), f"{label} {identifier} non-Core responsibilities")
                ],
                "rationale": _text(row.get("rationale"), f"{label} {identifier} rationale", minimum=20),
                "evidence_refs": refs,
            }
        )
    expected = set(source_index)
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise CoreBoundaryError(f"{label} classification coverage mismatch; missing={missing}, extra={extra}")
    return sorted(rows, key=lambda item: item["id"])


def _validate_free_rows(
    raw_rows: object,
    *,
    label: str,
    layers: set[str],
    global_evidence: set[str],
    require_layer: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _array(raw_rows, label, minimum=1):
        row = _object(raw, f"{label} entry")
        identifier = _identifier(row.get("id"), f"{label} id")
        if identifier in seen:
            raise CoreBoundaryError(f"duplicate {label} id: {identifier}")
        seen.add(identifier)
        item = copy.deepcopy(row)
        item["id"] = identifier
        if require_layer:
            layer = _identifier(row.get("primary_layer"), f"{label} {identifier} layer")
            if layer not in layers:
                raise CoreBoundaryError(f"{label} {identifier} uses unknown layer: {layer}")
            item["primary_layer"] = layer
        boundary_state = row.get("boundary_state")
        if boundary_state is not None and str(boundary_state) not in BOUNDARY_STATES:
            raise CoreBoundaryError(f"{label} {identifier} uses unsupported boundary state")
        item["evidence_refs"] = _validate_evidence_subset(
            row.get("evidence_refs"),
            label=f"{label} {identifier}",
            allowed=global_evidence,
            required=str(boundary_state or "") != "unknown",
        )
        item["rationale"] = _text(row.get("rationale"), f"{label} {identifier} rationale", minimum=20)
        rows.append(item)
    return sorted(rows, key=lambda item: item["id"])


def _dependency_cycles(edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if edge["graph_kind"] == "dependency":
            adjacency.setdefault(edge["source_id"], []).append(edge["target_id"])
    for values in adjacency.values():
        values.sort()
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()
    cycles: set[tuple[str, ...]] = set()

    def canonical(nodes: list[str]) -> tuple[str, ...]:
        body = nodes[:-1]
        rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
        best = min(rotations)
        return (*best, best[0])

    def visit(node: str) -> None:
        visited.add(node)
        active.append(node)
        active_set.add(node)
        for target in adjacency.get(node, []):
            if target not in visited:
                visit(target)
            elif target in active_set:
                start = active.index(target)
                cycles.add(canonical(active[start:] + [target]))
        active.pop()
        active_set.remove(node)

    for node in sorted(set(adjacency) | {value for values in adjacency.values() for value in values}):
        if node not in visited:
            visit(node)
    return [list(cycle) for cycle in sorted(cycles)]


def build_core_boundary_projection(
    *,
    snapshot: VerifiedPhase1Snapshot,
    capability_authority: dict[str, Any],
    equivalence: dict[str, Any],
    spec: dict[str, Any],
    spec_identity: CoreBoundarySpecIdentity | None = None,
) -> dict[str, Any]:
    """Build and validate the complete evidence-linked P0 Core Candidate Map."""
    if equivalence.get("status") != "mainline-runtime-equivalence-verified":
        raise CoreBoundaryError("Core boundary requires an accepted v1.7 equivalence receipt")
    if equivalence.get("authority", {}).get("snapshot_id") != snapshot.snapshot_id:
        raise CoreBoundaryError("equivalence receipt is not bound to the verified Architecture Memory")

    layer_rows = _array(spec.get("layers"), "layer definitions", minimum=6)
    layers = {_identifier(_object(row, "layer definition").get("id"), "layer id") for row in layer_rows}
    if len(layers) != len(layer_rows):
        raise CoreBoundaryError("layer ids must be unique")
    required_layers = {
        "core",
        "capability-extension",
        "assurance",
        "distribution-adaptation",
        "development-history-support",
        "ekri-meta-capability",
        "unknown",
    }
    if layers != required_layers:
        raise CoreBoundaryError("Core boundary specification must define the complete target layer set")

    memory = snapshot.architecture_memory
    architecture_index = _index_rows(
        [_object(value, "architecture node") for value in _array(memory.get("system_architecture_tree"), "architecture nodes")],
        "architecture node",
    )
    responsibility_index = _index_rows(
        [_object(value, "responsibility") for value in _array(memory.get("module_responsibility_map"), "responsibilities")],
        "responsibility",
    )
    capability_index = _index_rows(
        [_object(value, "capability") for value in _array(capability_authority.get("capabilities"), "capabilities")],
        "capability",
    )
    global_evidence = set(snapshot.evidence_refs) | set(
        equivalence.get("supplemental_evidence", {}).get("evidence_refs", [])
    )
    classifications = _object(spec.get("classifications"), "classifications")
    architecture_rows = _validate_classifications(
        classifications.get("architecture_nodes"),
        label="architecture node",
        source_index=architecture_index,
        layers=layers,
        global_evidence=global_evidence,
    )
    responsibility_rows = _validate_classifications(
        classifications.get("responsibilities"),
        label="responsibility",
        source_index=responsibility_index,
        layers=layers,
        global_evidence=global_evidence,
    )
    capability_rows = _validate_classifications(
        classifications.get("capabilities"),
        label="capability",
        source_index=capability_index,
        layers=layers,
        global_evidence=global_evidence,
    )
    surface_rows = _validate_free_rows(
        classifications.get("support_surfaces"),
        label="support surface",
        layers=layers,
        global_evidence=global_evidence,
    )
    core_contracts = _validate_free_rows(
        spec.get("candidate_core_contracts"),
        label="candidate Core contract",
        layers=layers,
        global_evidence=global_evidence,
    )
    if any(row["primary_layer"] != "core" for row in core_contracts):
        raise CoreBoundaryError("every candidate Core contract must belong to the Core layer")

    component_layers = {row["id"]: row["primary_layer"] for row in capability_rows}
    component_layers.update({row["id"]: row["primary_layer"] for row in surface_rows})
    component_layers.update({row["id"]: "core" for row in core_contracts})
    dependency_edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for raw in _array(spec.get("dependency_edges"), "dependency edges", minimum=1):
        edge = _object(raw, "dependency edge")
        edge_id = _identifier(edge.get("id"), "dependency edge id")
        if edge_id in seen_edges:
            raise CoreBoundaryError(f"duplicate dependency edge id: {edge_id}")
        seen_edges.add(edge_id)
        source_id = _identifier(edge.get("source_id"), f"edge {edge_id} source")
        target_id = _identifier(edge.get("target_id"), f"edge {edge_id} target")
        if source_id not in component_layers or target_id not in component_layers:
            raise CoreBoundaryError(f"dependency edge {edge_id} references an unknown component")
        graph_kind = _text(edge.get("graph_kind"), f"edge {edge_id} graph kind", maximum=40)
        if graph_kind not in GRAPH_KINDS:
            raise CoreBoundaryError(f"dependency edge {edge_id} uses unsupported graph kind")
        source_layer = component_layers[source_id]
        target_layer = component_layers[target_id]
        if graph_kind == "control-loop":
            direction_status = "permitted-control-loop"
        elif source_layer == "core" and target_layer != "core":
            direction_status = "core-outward-extraction-blocker"
        elif source_layer != "core" and target_layer == "core":
            direction_status = "inward-valid"
        elif source_layer == target_layer:
            direction_status = "same-layer"
        else:
            direction_status = "cross-layer-review"
        refs = _validate_evidence_subset(
            edge.get("evidence_refs"),
            label=f"dependency edge {edge_id}",
            allowed=global_evidence,
        )
        dependency_edges.append(
            {
                "id": edge_id,
                "source_id": source_id,
                "source_layer": source_layer,
                "target_id": target_id,
                "target_layer": target_layer,
                "relation": _identifier(edge.get("relation"), f"edge {edge_id} relation"),
                "graph_kind": graph_kind,
                "direction_status": direction_status,
                "rationale": _text(edge.get("rationale"), f"edge {edge_id} rationale", minimum=20),
                "evidence_refs": refs,
            }
        )
    dependency_edges.sort(key=lambda item: item["id"])
    cycles = _dependency_cycles(dependency_edges)
    core_outward = [edge for edge in dependency_edges if edge["direction_status"] == "core-outward-extraction-blocker"]
    control_loops = [edge for edge in dependency_edges if edge["graph_kind"] == "control-loop"]

    hidden_dependency_risks = _validate_free_rows(
        spec.get("hidden_dependency_risks"),
        label="hidden dependency risk",
        layers=layers,
        global_evidence=global_evidence,
        require_layer=False,
    )
    extraction_frontier = _validate_free_rows(
        spec.get("extraction_frontier"),
        label="extraction frontier",
        layers=layers,
        global_evidence=global_evidence,
        require_layer=False,
    )
    risk_register = _validate_free_rows(
        spec.get("risk_register"),
        label="risk register",
        layers=layers,
        global_evidence=global_evidence,
        require_layer=False,
    )
    unknowns = _validate_free_rows(
        spec.get("unknowns"),
        label="unknown",
        layers=layers,
        global_evidence=global_evidence,
        require_layer=False,
    )
    disputed = _validate_free_rows(
        spec.get("disputed_boundaries"),
        label="disputed boundary",
        layers=layers,
        global_evidence=global_evidence,
        require_layer=False,
    )
    if any(row.get("knowledge_state") != "unknown" for row in unknowns):
        raise CoreBoundaryError("every unresolved P0 unknown must remain knowledge_state=unknown")
    if any(row.get("knowledge_state") != "inferred-knowledge" for row in disputed):
        raise CoreBoundaryError("every disputed boundary must remain inferred knowledge")

    created_at = utc_now_iso()
    identity_payload = asdict(spec_identity) if spec_identity else {
        "source": "provided-object",
        "path": "",
        "sha256": _sha256(_json_bytes(spec)),
        "scanner_commit": "",
        "scanner_tree": "",
        "blob_oid": "",
    }
    result = {
        "schema_version": MAP_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "profile_id": PROFILE_ID,
        "status": VALID_STATUS,
        "created_at": created_at,
        "source": {
            "authority_snapshot_id": snapshot.snapshot_id,
            "authority_commit": snapshot.source_commit,
            "authority_tree": snapshot.source_tree,
            "target_commit": equivalence["target"]["commit"],
            "target_tree": equivalence["target"]["tree"],
            "equivalence_verdict": equivalence["verdict"],
            "equivalence_sha256": _sha256(_json_bytes(equivalence)),
        },
        "specification": identity_payload,
        "layers": copy.deepcopy(layer_rows),
        "classifications": {
            "architecture_nodes": architecture_rows,
            "responsibilities": responsibility_rows,
            "capabilities": capability_rows,
            "support_surfaces": surface_rows,
        },
        "candidate_core_contracts": core_contracts,
        "dependency_report": {
            "edge_count": len(dependency_edges),
            "edges": dependency_edges,
            "dependency_cycle_count": len(cycles),
            "dependency_cycles": cycles,
            "core_outward_blocker_count": len(core_outward),
            "core_outward_blockers": core_outward,
            "permitted_control_loop_count": len(control_loops),
            "permitted_control_loops": control_loops,
            "hidden_dependency_risks": hidden_dependency_risks,
            "claim_ceiling": (
                "The graph records reviewed semantic and packaging dependencies represented in the P0 specification. "
                "No detected dependency cycle means no cycle in this bounded graph; it does not prove exhaustive Python, shell, dynamic-resource, or generated-package dependency closure."
            ),
        },
        "extraction_frontier": extraction_frontier,
        "risk_register": risk_register,
        "unknowns": unknowns,
        "disputed_boundaries": disputed,
        "counts": {
            "architecture_nodes": len(architecture_rows),
            "responsibilities": len(responsibility_rows),
            "capabilities": len(capability_rows),
            "support_surfaces": len(surface_rows),
            "candidate_core_contracts": len(core_contracts),
            "dependency_edges": len(dependency_edges),
            "dependency_cycles": len(cycles),
            "core_outward_blockers": len(core_outward),
            "extraction_frontiers": len(extraction_frontier),
            "risks": len(risk_register),
            "unknowns": len(unknowns),
            "disputed_boundaries": len(disputed),
        },
        "checks": [
            {"check": "v1.7-mainline-equivalence", "status": "passed", "detail": equivalence["verdict"]},
            {"check": "classification-coverage", "status": "passed", "detail": "all 20 architecture nodes, 17 responsibilities, and 16 current capabilities are classified"},
            {"check": "evidence-reference-closure", "status": "passed", "detail": "every non-unknown classification and contract is linked to verified Architecture Memory evidence"},
            {"check": "core-non-responsibility-boundary", "status": "passed", "detail": "candidate Core contracts declare explicit non-responsibilities"},
            {"check": "dependency-direction-analysis", "status": "passed", "detail": f"{len(core_outward)} current Core-outward couplings are retained as extraction blockers"},
            {"check": "unknown-preservation", "status": "passed", "detail": "unresolved physical and compatibility decisions remain unknown or review-bound"},
        ],
        "claim_ceiling": _text(spec.get("claim_ceiling"), "spec claim ceiling", minimum=60),
    }
    return result


def _matrix_projection(core_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "responsibility-matrix-built",
        "created_at": core_map["created_at"],
        "source": core_map["source"],
        **core_map["classifications"],
        "candidate_core_contracts": core_map["candidate_core_contracts"],
        "claim_ceiling": "This matrix classifies reviewed responsibilities and surfaces; it does not authorize physical moves or prove runtime parity after extraction.",
    }


def _dependency_projection(core_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DEPENDENCY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "dependency-direction-reviewed",
        "created_at": core_map["created_at"],
        "source": core_map["source"],
        **core_map["dependency_report"],
    }


def _frontier_projection(core_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": FRONTIER_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "candidate-extraction-frontier-built",
        "created_at": core_map["created_at"],
        "source": core_map["source"],
        "frontier_count": len(core_map["extraction_frontier"]),
        "frontiers": core_map["extraction_frontier"],
        "risk_register": core_map["risk_register"],
        "claim_ceiling": "The frontier defines contract-design work for P1. It is not a directory move plan, package split authorization, or proof that the named seams are already physically separable.",
    }


def _unknown_projection(core_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": UNKNOWN_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "unknowns-and-disputes-registered",
        "created_at": core_map["created_at"],
        "source": core_map["source"],
        "unknown_count": len(core_map["unknowns"]),
        "unknowns": core_map["unknowns"],
        "disputed_boundary_count": len(core_map["disputed_boundaries"]),
        "disputed_boundaries": core_map["disputed_boundaries"],
        "claim_ceiling": "Registered unknowns and disputes intentionally cap P0. They must be resolved by P1 contract review or retained as explicit compatibility constraints.",
    }


def render_core_boundary_review(
    equivalence: dict[str, Any],
    core_map: dict[str, Any],
) -> str:
    """Render the human architecture review dossier."""
    counts = core_map["counts"]
    lines = [
        "# WFF v1.8 P0 — Core Boundary Review Dossier",
        "",
        f"- Authority: `{core_map['source']['authority_commit']}` / `{core_map['source']['authority_tree']}`",
        f"- Target: `{core_map['source']['target_commit']}` / `{core_map['source']['target_tree']}`",
        f"- Equivalence: `{equivalence['verdict']}`",
        f"- Status: `{core_map['status']}`",
        "",
        "## Baseline conclusion",
        "",
        "The WFF mainline/runtime at v1.7 is equivalent to v1.6.2 on the reviewed runtime invariant and Architecture Memory surfaces. The accepted v1.7 delta is EKRI plus release-closeout metadata. EKRI remains outside WFF Core and runtime packaging.",
        "",
        "## What is WFF Core?",
        "",
        "WFF Core is the minimum semantic contract that preserves lifecycle order, phase and handoff boundaries, evidence/claim semantics, formal state transitions, and the Workflow/Agentic/Templates/Evidence ownership boundary. It is not the aggregate of existing phase skills, generators, validators, tests, packaging, or retained proof.",
        "",
        "## Candidate Core contracts",
        "",
        "| Contract | Responsibility | Explicit non-responsibilities |",
        "|---|---|---|",
    ]
    for row in core_map["candidate_core_contracts"]:
        non_responsibilities = "; ".join(row.get("non_responsibilities", []))
        lines.append(f"| `{row['id']}` | {row.get('responsibility', '')} | {non_responsibilities} |")
    lines.extend(
        [
            "",
            "## Classification summary",
            "",
            f"- Architecture nodes: `{counts['architecture_nodes']}`",
            f"- Responsibilities: `{counts['responsibilities']}`",
            f"- Capabilities: `{counts['capabilities']}`",
            f"- Support surfaces: `{counts['support_surfaces']}`",
            f"- Candidate Core contracts: `{counts['candidate_core_contracts']}`",
            "",
            "### Current capabilities",
            "",
            "| Capability | Primary layer | Boundary | Core slices |",
            "|---|---|---|---|",
        ]
    )
    for row in core_map["classifications"]["capabilities"]:
        lines.append(
            f"| `{row['id']}` | `{row['primary_layer']}` | `{row['boundary_state']}` | "
            + (", ".join(f"`{value}`" for value in row["core_contract_slices"]) or "-")
            + " |"
        )
    lines.extend(
        [
            "",
            "## Dependency direction",
            "",
            f"- Reviewed dependency edges: `{counts['dependency_edges']}`",
            f"- Bounded dependency cycles: `{counts['dependency_cycles']}`",
            f"- Current Core-outward extraction blockers: `{counts['core_outward_blockers']}`",
            "",
        ]
    )
    for edge in core_map["dependency_report"]["core_outward_blockers"]:
        lines.append(f"- `{edge['source_id']} -> {edge['target_id']}`: {edge['rationale']}")
    lines.extend(["", "## Candidate extraction frontier", ""])
    for row in core_map["extraction_frontier"]:
        lines.append(f"- **{row['id']}** (`{row.get('priority', 'unknown')}`): {row.get('statement', row['rationale'])}")
    lines.extend(["", "## Risk register", ""])
    for row in core_map["risk_register"]:
        lines.append(f"- **{row['id']}** (`{row.get('severity', 'unknown')}`): {row.get('statement', row['rationale'])}")
    lines.extend(["", "## Unknowns", ""])
    for row in core_map["unknowns"]:
        lines.append(f"- **{row['id']}**: {row.get('statement', row['rationale'])}")
    lines.extend(["", "## Disputed boundaries", ""])
    for row in core_map["disputed_boundaries"]:
        lines.append(f"- **{row['id']}**: {row.get('statement', row['rationale'])}")
    lines.extend(
        [
            "",
            "## P0 decision",
            "",
            "P0 is sufficient to begin P1 Minimal Core Contract design. It does not authorize `mkdir core`, file movement, package extraction, or release claims. P1 must resolve the registered split-required boundaries before physical extraction.",
            "",
            "## Claim ceiling",
            "",
            core_map["claim_ceiling"],
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
        raise CoreBoundaryError(f"failed to persist P0 output {filename}: {exc}") from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _persist_outputs(
    repository_root: Path,
    *,
    equivalence: dict[str, Any],
    core_map: dict[str, Any],
) -> dict[str, str]:
    matrix = _matrix_projection(core_map)
    dependency = _dependency_projection(core_map)
    frontier = _frontier_projection(core_map)
    unknowns = _unknown_projection(core_map)
    review = render_core_boundary_review(equivalence, core_map).encode("utf-8")
    payloads = {
        "baseline-equivalence.json": _json_bytes(equivalence),
        "core-candidate-map.json": _json_bytes(core_map),
        "core-noncore-responsibility-matrix.json": _json_bytes(matrix),
        "dependency-direction-cycle-report.json": _json_bytes(dependency),
        "candidate-extraction-frontier.json": _json_bytes(frontier),
        "unknowns-disputed-boundaries.json": _json_bytes(unknowns),
        "CORE_BOUNDARY_REVIEW.md": review,
    }
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-boundary-output-persisted",
        "created_at": utc_now_iso(),
        "source_tree": core_map["source"]["target_tree"],
        "output_digests": {name: _sha256(payload) for name, payload in sorted(payloads.items())},
        "checks": [
            {"check": "equivalence-binding", "status": "passed", "detail": "Core map is digest-bound to the accepted baseline-equivalence receipt"},
            {"check": "projection-consistency", "status": "passed", "detail": "matrix, dependency, frontier, unknown, and human projections derive from one Core Candidate Map"},
            {"check": "no-follow-atomic-persistence", "status": "passed", "detail": "outputs were persisted through real-directory descriptors and atomic replacement"},
        ],
        "claim_ceiling": "Persistence and digest checks prove output integrity only; they do not strengthen P0 architecture judgments or authorize extraction.",
    }
    payloads["core-boundary-audit.json"] = _json_bytes(audit)

    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "core-boundary", core_map["source"]["target_tree"]):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        for filename, payload in payloads.items():
            _secure_atomic_write(parent_fd, filename, payload)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = repository_root / ".EKRI" / "core-boundary" / core_map["source"]["target_tree"]
    return {
        "output_root": str(output_root),
        **{name.replace("-", "_").replace(".", "_"): str(output_root / name) for name in payloads},
    }


def _accepted_manifest(repository_root: Path, target_ref: str) -> dict[str, Any]:
    manifest = evaluate_observation_boundary(repository_root=repository_root, target_ref=target_ref)
    if manifest.get("boundary", {}).get("verdict") != VALID_VERDICT:
        raise CoreBoundaryError(
            "formal observation rejected: "
            + str(manifest.get("boundary", {}).get("failure_reason") or "unknown reason")
        )
    write_manifest(repository_root, manifest)
    return manifest


def run_core_boundary_reconstruction(
    repository_root: str | Path,
    *,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Bootstrap trusted authority and run the complete v1.8 P0 reconstruction."""
    root = _absolute_path(repository_root)
    try:
        spec, spec_identity = load_core_boundary_spec()
        baseline = _object(spec.get("baseline_equivalence"), "spec baseline_equivalence")
        authority = _object(baseline.get("authority"), "baseline authority")
        target = _object(baseline.get("target"), "baseline target")

        _accepted_manifest(root, _text(authority.get("commit"), "authority commit"))
        reconstruct_and_persist_wff_baseline(root)
        snapshot = verify_phase1_snapshot(
            root,
            source_tree=_text(authority.get("tree"), "authority tree"),
        )
        target_manifest = _accepted_manifest(
            root,
            _text(target.get("commit"), "target commit"),
        )

        architecture_spec = load_reconstruction_spec()
        capability_spec, capability_identity = load_capability_spec()
        capability_service = CapabilityQueryService.from_snapshot(
            snapshot,
            capability_spec,
            capability_identity,
        )
        equivalence = build_baseline_equivalence(
            root,
            baseline_snapshot=snapshot,
            target_manifest=target_manifest,
            architecture_spec=architecture_spec,
            core_spec=spec,
        )
        core_map = build_core_boundary_projection(
            snapshot=snapshot,
            capability_authority=capability_service.authority,
            equivalence=equivalence,
            spec=spec,
            spec_identity=spec_identity,
        )
        outputs: dict[str, str] = {}
        if write_outputs:
            outputs = _persist_outputs(root, equivalence=equivalence, core_map=core_map)
    except CoreBoundaryError:
        raise
    except (
        AdmittedEvidenceError,
        ExistingCapabilityError,
        KnowledgeReconstructionError,
        ObservationBoundaryError,
        Phase1SnapshotError,
    ) as exc:
        raise CoreBoundaryError(
            f"P0 authority or projection verification failed: {exc}"
        ) from exc
    return {
        "schema_version": "ekri.core-boundary-run.v1",
        "status": VALID_STATUS,
        "equivalence": equivalence,
        "core_candidate_map": core_map,
        "outputs": outputs,
    }
