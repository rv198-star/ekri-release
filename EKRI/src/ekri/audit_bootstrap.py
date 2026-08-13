"""Reproducible Phase 3 audit-runtime bootstrap.

A clean independent worktree has no ignored ``.EKRI`` state. This module
rebuilds Phase 0 and Phase 1 from the immutable WFF v1.6.2 Git tree, compares
stable semantic fingerprints with a committed audit expectation fixture, and
proves that Phase 2 can consume the reconstructed snapshot before Phase 3
independent audit begins.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
import uuid

from .capability_contract import ExistingCapabilityError, build_request
from .existing_capability_intelligence import run_existing_capability_check
from .knowledge_reconstruction import (
    KnowledgeReconstructionError,
    _json_bytes,
    reconstruct_and_persist_wff_baseline,
)
from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    evaluate_observation_boundary,
    resolve_scanner_identity,
    write_manifest,
)
from .phase1_snapshot import Phase1SnapshotError, verify_phase1_snapshot


FIXTURE_SCHEMA_VERSION = "ekri.phase3-audit-fixture.v1"
REPORT_SCHEMA_VERSION = "ekri.phase3-audit-bootstrap.v1"
DEFAULT_FIXTURE_PATH = "EKRI/audit-fixtures/wff-v162-phase3-baseline.json"


class Phase3AuditBootstrapError(RuntimeError):
    """Raised when a clean audit runtime cannot be reconstructed exactly."""


@dataclass(frozen=True)
class AuditFixtureIdentity:
    source: str
    path: str
    sha256: str
    scanner_commit: str
    scanner_tree: str
    blob_oid: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Phase3AuditBootstrapError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Phase3AuditBootstrapError(f"{label} must be a list")
    return value


def _text(value: object, label: str, *, minimum: int = 1, maximum: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise Phase3AuditBootstrapError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _decode_fixture(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase3AuditBootstrapError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    fixture = _object(payload, label)
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise Phase3AuditBootstrapError("unsupported Phase 3 audit fixture schema")
    baseline = _object(fixture.get("baseline"), "fixture baseline")
    _text(baseline.get("commit"), "fixture baseline commit", minimum=40, maximum=64)
    _text(baseline.get("tree"), "fixture baseline tree", minimum=40, maximum=64)
    observation = _object(fixture.get("observation"), "fixture observation")
    if not isinstance(observation.get("accepted_path_count"), int):
        raise Phase3AuditBootstrapError("fixture accepted_path_count must be an integer")
    _text(observation.get("path_set_sha256"), "fixture path-set digest", minimum=64, maximum=64)
    phase1 = _object(fixture.get("phase1"), "fixture Phase 1")
    _object(phase1.get("counts"), "fixture Phase 1 counts")
    fingerprints = _object(phase1.get("semantic_fingerprints"), "fixture semantic fingerprints")
    for key in (
        "architecture_memory",
        "evidence_index",
        "reconstruction_report",
        "human_projection",
        "evidence_read_paths",
    ):
        _text(fingerprints.get(key), f"fixture fingerprint {key}", minimum=64, maximum=64)
    phase2 = _object(fixture.get("phase2"), "fixture Phase 2")
    for key in ("capability_count", "alias_count", "ambiguous_alias_count"):
        if not isinstance(phase2.get(key), int):
            raise Phase3AuditBootstrapError(f"fixture Phase 2 {key} must be an integer")
    return fixture


def _load_external_fixture(path: Path) -> tuple[dict[str, Any], AuditFixtureIdentity]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise Phase3AuditBootstrapError(f"audit fixture cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise Phase3AuditBootstrapError("audit fixture must be a safe regular file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase3AuditBootstrapError(f"audit fixture cannot be read: {exc}") from exc
    return _decode_fixture(raw, "audit fixture"), AuditFixtureIdentity(
        source="external-file",
        path=str(path),
        sha256=_sha256(raw),
        scanner_commit="",
        scanner_tree="",
        blob_oid="",
    )


def load_phase3_audit_fixture(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], AuditFixtureIdentity]:
    """Load the committed expectation fixture or an explicit test fixture."""
    if path is not None:
        return _load_external_fixture(Path(path).expanduser())
    try:
        identity = scanner or resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise Phase3AuditBootstrapError(
            f"active scanner provenance is unverifiable: {exc}"
        ) from exc
    entries = [
        entry
        for entry in _tree_entries(
            identity.repository_root,
            identity.tree,
            pathspec=DEFAULT_FIXTURE_PATH,
        )
        if entry[3] == DEFAULT_FIXTURE_PATH
    ]
    if len(entries) != 1:
        raise Phase3AuditBootstrapError(
            "committed Phase 3 audit fixture is missing or ambiguous"
        )
    mode, object_type, oid, _ = entries[0]
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise Phase3AuditBootstrapError(
            "committed Phase 3 audit fixture must be a regular Git blob"
        )
    raw = _run_git(
        Path(identity.repository_root),
        "cat-file",
        "blob",
        oid,
        binary=True,
    )
    assert isinstance(raw, bytes)
    fixture = _decode_fixture(raw, "committed Phase 3 audit fixture")
    return fixture, AuditFixtureIdentity(
        source="scanner-commit",
        path=DEFAULT_FIXTURE_PATH,
        sha256=_sha256(raw),
        scanner_commit=identity.commit,
        scanner_tree=identity.tree,
        blob_oid=oid,
    )


def _semantic_clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def phase1_semantic_fingerprints(
    architecture_memory: dict[str, Any],
    evidence_index: dict[str, Any],
    reconstruction_report: dict[str, Any],
    *,
    human_projection_sha256: str,
) -> dict[str, str]:
    """Return root-, scanner-, and timestamp-independent Phase 1 fingerprints."""
    memory = _semantic_clone(architecture_memory)
    memory.pop("created_at", None)
    memory.pop("scanner", None)
    memory_source = _object(memory.get("source"), "architecture memory source")
    memory_source.pop("repository_root", None)
    memory_source.pop("observation_manifest_sha256", None)

    evidence = _semantic_clone(evidence_index)
    evidence.pop("created_at", None)
    evidence_source = _object(evidence.get("source"), "evidence index source")
    evidence_source.pop("repository_root", None)

    report = _semantic_clone(reconstruction_report)
    report.pop("created_at", None)
    report.pop("output_digests", None)

    read_paths = _array(evidence.get("read_paths"), "evidence read paths")
    return {
        "architecture_memory": _sha256(_json_bytes(memory)),
        "evidence_index": _sha256(_json_bytes(evidence)),
        "reconstruction_report": _sha256(_json_bytes(report)),
        "human_projection": _text(
            human_projection_sha256,
            "human projection digest",
            minimum=64,
            maximum=64,
        ),
        "evidence_read_paths": _sha256(_json_bytes(read_paths)),
    }


def _compare(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise Phase3AuditBootstrapError(
            f"audit bootstrap mismatch for {label}: expected={expected!r}, actual={actual!r}"
        )


def _secure_atomic_write(repository_root: Path, report: dict[str, Any]) -> Path:
    payload = _json_bytes(report)
    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    temporary = f".phase3-bootstrap.{uuid.uuid4().hex}.tmp"
    created = False
    try:
        parent_fd = root_fd
        for component in (".EKRI", "audit"):
            try:
                descriptor = _open_or_create_directory(parent_fd, component)
            except ObservationBoundaryError as exc:
                raise Phase3AuditBootstrapError(
                    f"audit output directory is unsafe: {exc}"
                ) from exc
            opened.append(descriptor)
            parent_fd = descriptor
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
        created = True
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            "phase3-bootstrap.json",
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        created = False
        os.fsync(parent_fd)
    except OSError as exc:
        raise Phase3AuditBootstrapError(
            f"failed to persist Phase 3 audit bootstrap report: {exc}"
        ) from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=opened[-1] if opened else root_fd)
            except FileNotFoundError:
                pass
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)
    return repository_root / ".EKRI" / "audit" / "phase3-bootstrap.json"


def bootstrap_phase3_audit_runtime(
    repository_root: str | Path,
    *,
    fixture_path: str | Path | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    """Reconstruct and verify the ignored authority required by Phase 3 audit."""
    root = _absolute_path(repository_root)
    if not root.is_dir():
        raise Phase3AuditBootstrapError(f"repository root is not a directory: {root}")
    try:
        scanner = resolve_scanner_identity()
        fixture, fixture_identity = load_phase3_audit_fixture(
            fixture_path,
            scanner=scanner,
        )
        baseline = _object(fixture.get("baseline"), "fixture baseline")
        commit = _text(baseline.get("commit"), "baseline commit", minimum=40, maximum=64)
        tree = _text(baseline.get("tree"), "baseline tree", minimum=40, maximum=64)

        manifest = evaluate_observation_boundary(
            repository_root=root,
            target_ref=commit,
        )
        boundary = _object(manifest.get("boundary"), "observation boundary")
        if boundary.get("valid") is not True:
            raise Phase3AuditBootstrapError(
                "baseline observation boundary rejected: "
                + str(boundary.get("failure_reason", "unknown failure"))
            )
        _compare("baseline commit", manifest["source"]["commit"], commit)
        _compare("baseline tree", manifest["source"]["tree"], tree)
        expected_observation = _object(fixture.get("observation"), "fixture observation")
        _compare(
            "accepted path count",
            manifest["corpus"]["accepted_path_count"],
            expected_observation["accepted_path_count"],
        )
        _compare(
            "admitted path-set digest",
            manifest["corpus"]["path_set_sha256"],
            expected_observation["path_set_sha256"],
        )
        write_manifest(root, manifest)

        reconstruct_and_persist_wff_baseline(root)
        snapshot = verify_phase1_snapshot(root, source_tree=tree)
        actual_counts = snapshot.reconstruction_report["counts"]
        expected_phase1 = _object(fixture.get("phase1"), "fixture Phase 1")
        _compare("Phase 1 counts", actual_counts, expected_phase1["counts"])
        fingerprints = phase1_semantic_fingerprints(
            snapshot.architecture_memory,
            snapshot.evidence_index,
            snapshot.reconstruction_report,
            human_projection_sha256=snapshot.human_projection_sha256,
        )
        _compare(
            "Phase 1 semantic fingerprints",
            fingerprints,
            expected_phase1["semantic_fingerprints"],
        )

        phase2_request = build_request(
            capability_query="traceability",
            trigger_basis="hypothetical-risk",
            change_mode="use-as-is",
        )
        phase2_run = run_existing_capability_check(
            root,
            phase2_request,
            write_outputs=False,
        )
        catalog = _object(phase2_run.get("catalog"), "Phase 2 catalog")
        actual_phase2 = {
            "capability_count": catalog["capability_count"],
            "alias_count": len(catalog["alias_index"]),
            "ambiguous_alias_count": len(catalog["ambiguous_aliases"]),
        }
        expected_phase2 = _object(fixture.get("phase2"), "fixture Phase 2")
        _compare("Phase 2 catalog profile", actual_phase2, expected_phase2)
    except (
        ObservationBoundaryError,
        KnowledgeReconstructionError,
        Phase1SnapshotError,
        ExistingCapabilityError,
    ) as exc:
        raise Phase3AuditBootstrapError(str(exc)) from exc

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "phase3-audit-runtime-ready",
        "created_at": _now(),
        "repository_root": str(root),
        "fixture": asdict(fixture_identity),
        "scanner": {
            "commit": scanner.commit,
            "tree": scanner.tree,
            "surface_tree_sha256": scanner.surface_tree_sha256,
            "surface_path_count": scanner.surface_path_count,
            "runtime_matches_commit": scanner.runtime_matches_commit,
        },
        "baseline": {"commit": commit, "tree": tree},
        "observation": {
            "accepted_path_count": manifest["corpus"]["accepted_path_count"],
            "path_set_sha256": manifest["corpus"]["path_set_sha256"],
            "self_scan_verdict": manifest["boundary"]["self_scan_verdict"],
        },
        "phase1": {
            "counts": actual_counts,
            "semantic_fingerprints": fingerprints,
        },
        "phase2": actual_phase2,
        "checks": [
            {"check": "clean-scanner-authority", "status": "passed", "detail": "the active EKRI surface matched its recorded scanner commit"},
            {"check": "fresh-phase0-reconstruction", "status": "passed", "detail": "the fixed baseline corpus was regenerated for this worktree instead of copying absolute-path runtime state"},
            {"check": "fresh-phase1-reconstruction", "status": "passed", "detail": "Phase 1 semantic fingerprints and counts match the committed audit fixture"},
            {"check": "phase2-consumption", "status": "passed", "detail": "Phase 2 rebuilt the expected capability catalog from the fresh Phase 1 snapshot"},
        ],
        "claim_ceiling": (
            "This bootstrap proves that a clean worktree can reconstruct the fixed Phase 0/1 authority and reproduce the expected Phase 2 catalog profile. "
            "It does not audit Phase 3 behavior or raise any architecture, release, or production claim."
        ),
        "output": (
            str(root / ".EKRI" / "audit" / "phase3-bootstrap.json")
            if write_report
            else ""
        ),
    }
    if write_report:
        _secure_atomic_write(root, report)
    return report
