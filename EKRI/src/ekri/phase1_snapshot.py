"""Verified consumption of persisted EKRI Phase 1 architecture memory."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .knowledge_reconstruction import (
    EVIDENCE_SCHEMA_VERSION,
    MEMORY_SCHEMA_VERSION,
    PROFILE_ID,
    REPORT_SCHEMA_VERSION,
    VALID_STATUS,
    _json_bytes,
    _safe_read_runtime_file,
    load_fixed_observation_manifest,
)
from .observation_boundary import _absolute_path


class Phase1SnapshotError(RuntimeError):
    """Raised when persisted Phase 1 outputs cannot be trusted."""


@dataclass(frozen=True)
class VerifiedPhase1Snapshot:
    repository_root: str
    source_commit: str
    source_tree: str
    snapshot_id: str
    architecture_memory: dict[str, Any]
    evidence_index: dict[str, Any]
    reconstruction_report: dict[str, Any]
    human_projection_sha256: str
    evidence_refs: frozenset[str]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Phase1SnapshotError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Phase1SnapshotError(f"{label} must be a list")
    return value


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise Phase1SnapshotError(f"{label} must not be empty")
    return text


def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase1SnapshotError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return _object(value, label)


def _knowledge_rows(memory: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in (
        "system_architecture_tree",
        "module_responsibility_map",
        "implementation_intent_summary",
        "validation_assurance_ownership",
        "constraints",
        "unknowns",
    ):
        for raw in _array(memory.get(key), f"architecture memory {key}"):
            yield _object(raw, f"architecture memory {key} entry")


def _referenced_evidence(memory: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for row in _knowledge_rows(memory):
        raw_refs = _array(row.get("evidence_refs"), "knowledge entry evidence_refs")
        for raw in raw_refs:
            ref = _text(raw, "knowledge evidence ref")
            refs.add(ref)
    return refs


def _indexed_evidence(evidence: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    paths: list[str] = []
    sources = _array(evidence.get("sources"), "evidence index sources")
    for raw_source in sources:
        source = _object(raw_source, "evidence source")
        path = _text(source.get("path"), "evidence source path")
        if path in paths:
            raise Phase1SnapshotError(f"duplicate evidence source path: {path}")
        paths.append(path)
        blob = _object(source.get("blob"), f"evidence source blob: {path}")
        if blob.get("object_type") != "blob" or blob.get("mode") not in {
            "100644",
            "100755",
        }:
            raise Phase1SnapshotError(f"evidence source is not a regular Git blob: {path}")
        if blob.get("path") != path:
            raise Phase1SnapshotError(f"evidence blob path mismatch: {path}")
        for raw_anchor in _array(source.get("anchors"), f"evidence anchors: {path}"):
            anchor = _object(raw_anchor, f"evidence anchor: {path}")
            ref = _text(anchor.get("evidence_ref"), "evidence_ref")
            if ref in refs:
                raise Phase1SnapshotError(f"duplicate evidence ref: {ref}")
            refs.add(ref)
            line_numbers = _array(anchor.get("line_numbers"), f"line numbers: {ref}")
            if not line_numbers or any(not isinstance(item, int) or item < 1 for item in line_numbers):
                raise Phase1SnapshotError(f"invalid evidence line numbers: {ref}")
    declared_paths = [_text(item, "evidence read path") for item in _array(evidence.get("read_paths"), "evidence read_paths")]
    if len(declared_paths) != len(set(declared_paths)):
        raise Phase1SnapshotError("evidence read_paths contain duplicates")
    if set(declared_paths) != set(paths):
        raise Phase1SnapshotError("evidence read_paths do not match source paths")
    if evidence.get("read_blob_count") != len(sources):
        raise Phase1SnapshotError("evidence read_blob_count does not match sources")
    return refs


def _verify_git_evidence(
    repository_root: Path,
    observation_manifest: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    try:
        reader = AdmittedGitReader(repository_root, observation_manifest)
    except AdmittedEvidenceError as exc:
        raise Phase1SnapshotError(
            f"Phase 0 observation manifest cannot authorize Phase 1 evidence: {exc}"
        ) from exc

    for raw_source in _array(evidence.get("sources"), "evidence sources"):
        source = _object(raw_source, "evidence source")
        path = _text(source.get("path"), "evidence source path")
        try:
            text = reader.read_text(path)
            receipt = reader.receipt(path).to_dict()
        except AdmittedEvidenceError as exc:
            raise Phase1SnapshotError(
                f"Phase 1 evidence blob cannot be revalidated: {path}: {exc}"
            ) from exc
        if receipt != _object(source.get("blob"), f"evidence blob receipt: {path}"):
            raise Phase1SnapshotError(f"Phase 1 evidence blob receipt mismatch: {path}")
        lines = text.splitlines()
        if source.get("line_count") != len(lines):
            raise Phase1SnapshotError(f"Phase 1 evidence line count mismatch: {path}")
        for raw_anchor in _array(source.get("anchors"), f"evidence anchors: {path}"):
            anchor = _object(raw_anchor, f"evidence anchor: {path}")
            ref = _text(anchor.get("evidence_ref"), "evidence ref")
            contains = _text(anchor.get("contains"), f"anchor contains: {ref}")
            matches = [
                (index, line)
                for index, line in enumerate(lines, start=1)
                if contains in line
            ]
            expected_lines = [index for index, _ in matches]
            expected_excerpts = [line.strip()[:500] for _, line in matches]
            if not matches:
                raise Phase1SnapshotError(f"Phase 1 evidence anchor no longer resolves: {ref}")
            if anchor.get("line_numbers") != expected_lines:
                raise Phase1SnapshotError(f"Phase 1 evidence anchor line mismatch: {ref}")
            if anchor.get("excerpts") != expected_excerpts:
                raise Phase1SnapshotError(f"Phase 1 evidence anchor excerpt mismatch: {ref}")

    declared_paths = tuple(sorted(_text(item, "evidence read path") for item in _array(evidence.get("read_paths"), "evidence read_paths")))
    if reader.read_paths() != declared_paths:
        raise Phase1SnapshotError("Phase 1 evidence revalidation read-path closure failed")


def _count_actual(memory: dict[str, Any], evidence: dict[str, Any]) -> dict[str, int]:
    anchors = 0
    for raw_source in _array(evidence.get("sources"), "evidence sources"):
        anchors += len(_array(_object(raw_source, "evidence source").get("anchors"), "anchors"))
    return {
        "architecture_nodes": len(_array(memory.get("system_architecture_tree"), "architecture tree")),
        "responsibility_entries": len(_array(memory.get("module_responsibility_map"), "responsibility map")),
        "implementation_intents": len(_array(memory.get("implementation_intent_summary"), "implementation intents")),
        "assurance_entries": len(_array(memory.get("validation_assurance_ownership"), "assurance entries")),
        "constraints": len(_array(memory.get("constraints"), "constraints")),
        "unknowns": len(_array(memory.get("unknowns"), "unknowns")),
        "evidence_sources": len(_array(evidence.get("sources"), "evidence sources")),
        "evidence_anchors": anchors,
        "target_blob_reads": int(evidence.get("read_blob_count", -1)),
    }


def verify_phase1_snapshot(
    repository_root: str | Path,
    *,
    source_tree: str,
) -> VerifiedPhase1Snapshot:
    """Read and fully revalidate one persisted Phase 1 snapshot."""
    root = _absolute_path(repository_root)
    tree = _text(source_tree, "source tree")
    components = (".EKRI", "knowledge", tree)
    memory_raw = _safe_read_runtime_file(root, components, "architecture-memory.json")
    evidence_raw = _safe_read_runtime_file(root, components, "evidence-index.json")
    report_raw = _safe_read_runtime_file(root, components, "reconstruction-report.json")
    human_raw = _safe_read_runtime_file(root, components, "ARCHITECTURE_MEMORY.md")

    memory = _decode_json(memory_raw, "architecture-memory.json")
    evidence = _decode_json(evidence_raw, "evidence-index.json")
    report = _decode_json(report_raw, "reconstruction-report.json")

    if memory.get("schema_version") != MEMORY_SCHEMA_VERSION:
        raise Phase1SnapshotError("unsupported architecture-memory schema")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise Phase1SnapshotError("unsupported evidence-index schema")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise Phase1SnapshotError("unsupported reconstruction-report schema")
    if any(value.get("profile_id") != PROFILE_ID for value in (memory, evidence, report)):
        raise Phase1SnapshotError("Phase 1 profile identity mismatch")
    if memory.get("status") != VALID_STATUS or report.get("status") != VALID_STATUS:
        raise Phase1SnapshotError("Phase 1 snapshot is not reconstructed")

    source = _object(memory.get("source"), "architecture memory source")
    source_commit = _text(source.get("commit"), "source commit")
    source_tree_value = _text(source.get("tree"), "source tree")
    evidence_source = _object(evidence.get("source"), "evidence source identity")
    identities = {
        source_tree_value,
        _text(evidence_source.get("tree"), "evidence source tree"),
        _text(report.get("source_tree"), "report source tree"),
        tree,
    }
    if len(identities) != 1:
        raise Phase1SnapshotError("Phase 1 source tree identities diverge")
    commits = {
        source_commit,
        _text(evidence_source.get("commit"), "evidence source commit"),
        _text(report.get("source_commit"), "report source commit"),
    }
    if len(commits) != 1:
        raise Phase1SnapshotError("Phase 1 source commit identities diverge")

    digests = _object(report.get("output_digests"), "report output_digests")
    expected_digests = {
        "architecture-memory.json": _sha256(memory_raw),
        "evidence-index.json": _sha256(evidence_raw),
        "ARCHITECTURE_MEMORY.md": _sha256(human_raw),
    }
    if digests != expected_digests:
        raise Phase1SnapshotError("Phase 1 output digests do not match persisted files")

    actual_counts = _count_actual(memory, evidence)
    if _object(report.get("counts"), "report counts") != actual_counts:
        raise Phase1SnapshotError("Phase 1 report counts do not match persisted outputs")
    read_paths = [_text(item, "report target blob path") for item in _array(report.get("target_blob_read_paths"), "report target_blob_read_paths")]
    if read_paths != evidence.get("read_paths"):
        raise Phase1SnapshotError("Phase 1 report read paths do not match evidence index")

    indexed_refs = _indexed_evidence(evidence)
    referenced_refs = _referenced_evidence(memory)
    missing = sorted(referenced_refs - indexed_refs)
    if missing:
        raise Phase1SnapshotError("architecture memory references unknown evidence: " + ", ".join(missing))

    try:
        observation_manifest = load_fixed_observation_manifest(root, tree=tree)
    except Exception as exc:
        raise Phase1SnapshotError(
            f"Phase 0 observation manifest cannot be loaded: {exc}"
        ) from exc
    if source.get("observation_manifest_sha256") != _sha256(_json_bytes(observation_manifest)):
        raise Phase1SnapshotError("Phase 1 observation manifest digest does not match")
    if source.get("observation_manifest_schema") != observation_manifest.get("schema_version"):
        raise Phase1SnapshotError("Phase 1 observation manifest schema does not match")
    if source.get("admitted_path_set_sha256") != observation_manifest.get("corpus", {}).get("path_set_sha256"):
        raise Phase1SnapshotError("Phase 1 admitted path-set digest does not match")
    _verify_git_evidence(root, observation_manifest, evidence)

    snapshot_id = _text(memory.get("snapshot_id"), "snapshot id")
    expected_snapshot_id = f"{PROFILE_ID}:{tree}"
    if snapshot_id != expected_snapshot_id:
        raise Phase1SnapshotError("Phase 1 snapshot id does not match source tree")
    if memory.get("evidence_index_ref") != "evidence-index.json":
        raise Phase1SnapshotError("architecture memory evidence index reference is invalid")

    return VerifiedPhase1Snapshot(
        repository_root=str(root),
        source_commit=source_commit,
        source_tree=tree,
        snapshot_id=snapshot_id,
        architecture_memory=memory,
        evidence_index=evidence,
        reconstruction_report=report,
        human_projection_sha256=expected_digests["ARCHITECTURE_MEMORY.md"],
        evidence_refs=frozenset(indexed_refs),
    )
