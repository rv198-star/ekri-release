"""EKRI v1.0 P8 product-level non-WFF conformance proof.

The conformance harness verifies one unrelated software-delivery fixture from
exact Git blobs, projects its evidence-bound Architecture knowledge through the
same Architecture View contract used by the v1.0 migration, builds the same
ontology-authoritative Capability slice and L0-L3 named-query facade, and runs
the same general Flow/Handoff query contract.

It deliberately does not use WFF P1/P2/P3/P4/PX concepts or the WFF-specific
Before Generate compatibility query.  The output is a conformance report, not a
new semantic authority store.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .architecture_roundtrip import (
    build_source_architecture_baseline_view,
    validate_architecture_view,
)
from .capability_contract import CapabilitySpecIdentity
from .capability_query import CapabilityQueryService
from .flow_query import FlowQueryService
from .observation_boundary import (
    ObservationBoundaryError,
    _run_git,
    _tree_entries,
    resolve_scanner_identity,
)
from .phase1_snapshot import VerifiedPhase1Snapshot


FIXTURE_SCHEMA_VERSION = "ekri.nonwff-conformance-fixture.v1"
REPORT_SCHEMA_VERSION = "ekri.nonwff-conformance-report.v1"
REPORT_STATUS = "nonwff-product-conformance-passed"
CONFORMANCE_VERSION = "ekri.nonwff-conformance.v0.1"
DEFAULT_FIXTURE_PATH = "EKRI/specs/nonwff-conformance/mercury-ci.json"
GENERAL_QUERY_KINDS = (
    "find-capability",
    "get-realizations",
    "explain-authority",
    "get-evidence",
    "trace-flow",
)
WFF_PROFILE_ONLY_SURFACES = (
    "before-generate",
    "run_existing_capability_check",
    ".EKRI/intelligence/**",
    "verified-local-phase1 WFF convenience loader",
)
FORBIDDEN_GENERAL_PROFILE_TOKENS = frozenset({"wff", "p1", "p2", "p3", "p4", "px"})


class NonWffConformanceError(RuntimeError):
    """Raised when a non-WFF fixture cannot satisfy the supported general model."""


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
        raise NonWffConformanceError(f"{label} must not be empty")
    return text


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NonWffConformanceError(f"{label} must be an object")
    return json.loads(json.dumps(dict(value), ensure_ascii=False))


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise NonWffConformanceError(f"{label} must be a list")
    return value


def _committed_blob(
    repository_root: Path,
    *,
    scanner_tree: str,
    relative_path: str,
) -> tuple[bytes, dict[str, str]]:
    entries = [
        row
        for row in _tree_entries(repository_root, scanner_tree, pathspec=relative_path)
        if row[3] == relative_path
    ]
    if len(entries) != 1:
        raise NonWffConformanceError(
            f"committed conformance source is missing or ambiguous: {relative_path}"
        )
    mode, object_type, oid, _ = entries[0]
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise NonWffConformanceError(
            f"conformance source must be a regular Git blob: {relative_path}"
        )
    raw = _run_git(repository_root, "cat-file", "blob", oid, binary=True)
    assert isinstance(raw, bytes)
    return raw, {
        "path": relative_path,
        "mode": mode,
        "blob_oid": oid,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def load_nonwff_fixture(
    repository_root: str | Path,
    *,
    fixture_path: str = DEFAULT_FIXTURE_PATH,
) -> tuple[dict[str, Any], dict[str, str], object]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise NonWffConformanceError(
            f"non-WFF conformance requires exact scanner provenance: {exc}"
        ) from exc
    if Path(scanner.repository_root).resolve() != root:
        raise NonWffConformanceError(
            "non-WFF conformance repository_root does not match the active scanner repository"
        )
    raw, receipt = _committed_blob(
        root,
        scanner_tree=scanner.tree,
        relative_path=fixture_path,
    )
    try:
        fixture = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NonWffConformanceError(f"non-WFF fixture cannot be decoded: {exc}") from exc
    if not isinstance(fixture, dict):
        raise NonWffConformanceError("non-WFF fixture must contain an object")
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise NonWffConformanceError("unsupported non-WFF fixture schema")
    if fixture.get("status") != "bounded-product-conformance-fixture":
        raise NonWffConformanceError("non-WFF fixture is not marked for bounded conformance")
    receipt.update(
        {
            "scanner_commit": scanner.commit,
            "scanner_tree": scanner.tree,
            "fixture_id": _text(fixture.get("fixture_id"), "fixture_id"),
        }
    )
    return fixture, receipt, scanner


def _verify_fixture_sources(
    repository_root: Path,
    fixture: Mapping[str, Any],
    scanner: object,
) -> tuple[str, dict[str, Any], frozenset[str]]:
    target_root = _text(fixture.get("target_root"), "fixture target_root")
    try:
        target_tree = str(
            _run_git(
                repository_root,
                "rev-parse",
                f"{scanner.commit}:{target_root}",
            )
        ).strip()
    except ObservationBoundaryError as exc:
        raise NonWffConformanceError(f"fixture target tree cannot be resolved: {exc}") from exc
    if len(target_tree) != 40:
        raise NonWffConformanceError("fixture target tree identity is invalid")

    sources: list[dict[str, Any]] = []
    evidence_refs: set[str] = set()
    for raw_source in _array(fixture.get("evidence_sources"), "fixture evidence_sources"):
        source = _mapping(raw_source, "fixture evidence source")
        source_id = _text(source.get("id"), "fixture evidence source id")
        relative = _text(source.get("path"), f"fixture source {source_id} path")
        full_path = f"{target_root}/{relative}"
        raw, blob = _committed_blob(
            repository_root,
            scanner_tree=scanner.tree,
            relative_path=full_path,
        )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NonWffConformanceError(
                f"fixture evidence source must be UTF-8 text: {full_path}"
            ) from exc
        anchors: list[dict[str, Any]] = []
        for raw_anchor in _array(source.get("anchors"), f"fixture source {source_id} anchors"):
            anchor = _mapping(raw_anchor, f"fixture source {source_id} anchor")
            anchor_id = _text(anchor.get("id"), f"fixture source {source_id} anchor id")
            contains = _text(anchor.get("contains"), f"fixture source {source_id}.{anchor_id} contains")
            if contains not in text:
                raise NonWffConformanceError(
                    f"fixture evidence anchor is not present in exact Git blob: {source_id}.{anchor_id}"
                )
            evidence_ref = f"{source_id}.{anchor_id}"
            if evidence_ref in evidence_refs:
                raise NonWffConformanceError(f"duplicate fixture evidence ref: {evidence_ref}")
            evidence_refs.add(evidence_ref)
            anchors.append(
                {
                    "id": anchor_id,
                    "evidence_ref": evidence_ref,
                    "contains": contains,
                }
            )
        sources.append(
            {
                "id": source_id,
                "path": relative,
                "git": blob,
                "anchors": anchors,
            }
        )
    if not sources or not evidence_refs:
        raise NonWffConformanceError("non-WFF fixture must provide exact evidence sources")
    return target_tree, {"sources": sources}, frozenset(evidence_refs)


def _fixture_snapshot(
    repository_root: Path,
    fixture: Mapping[str, Any],
    scanner: object,
    *,
    target_tree: str,
    evidence_index: Mapping[str, Any],
    evidence_refs: frozenset[str],
) -> VerifiedPhase1Snapshot:
    memory = _mapping(fixture.get("architecture_memory"), "fixture architecture_memory")
    fixture_id = _text(fixture.get("fixture_id"), "fixture_id")
    human_sha = _digest(memory)
    return VerifiedPhase1Snapshot(
        repository_root=str(repository_root),
        source_commit=scanner.commit,
        source_tree=target_tree,
        snapshot_id=f"nonwff:{fixture_id}:{target_tree}",
        architecture_memory=memory,
        evidence_index=dict(evidence_index),
        reconstruction_report={
            "schema_version": "ekri.nonwff-conformance-reconstruction-receipt.v1",
            "output_digests": {"ARCHITECTURE_MEMORY.md": human_sha},
        },
        human_projection_sha256=human_sha,
        evidence_refs=evidence_refs,
    )


def _capability_service(
    fixture: Mapping[str, Any],
    fixture_receipt: Mapping[str, str],
    scanner: object,
    *,
    target_tree: str,
    architecture_view: Mapping[str, Any],
    human_projection_sha256: str,
) -> CapabilityQueryService:
    profile = _mapping(fixture.get("capability_profile"), "fixture capability_profile")
    if profile.get("schema_version") != "ekri.capability-profile.v1":
        raise NonWffConformanceError("unsupported generic Capability profile schema")
    specification = dict(profile)
    specification["target"] = {
        "commit": scanner.commit,
        "tree": target_tree,
    }
    identity = CapabilitySpecIdentity(
        source="scanner-commit-nonwff-conformance-fixture",
        path=str(fixture_receipt["path"]),
        sha256=str(fixture_receipt["sha256"]),
        scanner_commit=scanner.commit,
        scanner_tree=scanner.tree,
        blob_oid=str(fixture_receipt["blob_oid"]),
    )
    return CapabilityQueryService.from_view(
        architecture_view,
        specification,
        identity,
        input_mode="provided-verified-view",
        phase1_human_projection_sha256=human_projection_sha256,
    )


def _general_profile_token_violations(
    architecture_view: Mapping[str, Any],
    service: CapabilityQueryService,
    flow_model: Mapping[str, Any],
) -> list[str]:
    semantic = _mapping(architecture_view.get("semantic_content"), "Architecture View semantic_content")
    tokens: list[str] = []
    for family, rows in semantic.items():
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if isinstance(raw, Mapping):
                tokens.extend(str(raw.get(key) or "") for key in ("id", "kind") if key in raw)
    tokens.extend(str(row.get("id") or "") for row in service.authority["capabilities"])
    vocabulary = flow_model.get("vocabulary", {})
    if isinstance(vocabulary, Mapping):
        for value in vocabulary.values():
            if isinstance(value, list):
                tokens.extend(str(item) for item in value)
            elif isinstance(value, str):
                tokens.append(value)
    violations: list[str] = []
    for token in tokens:
        normalized = token.lower().replace("_", "-").replace("/", "-")
        components = {part for part in normalized.split("-") if part}
        forbidden = sorted(components & FORBIDDEN_GENERAL_PROFILE_TOKENS)
        if forbidden:
            violations.append(f"{token}: {','.join(forbidden)}")
    return sorted(set(violations))


def _assert_no_raw_kernel_answer(answer: Mapping[str, Any], label: str) -> None:
    encoded = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    for forbidden in ('"objects"', '"occurrences"', '"assertions"'):
        if forbidden in encoded:
            raise NonWffConformanceError(
                f"{label} leaked raw Object/Occurrence/Assertion traversal"
            )


def run_nonwff_conformance(
    repository_root: str | Path,
    *,
    fixture_path: str = DEFAULT_FIXTURE_PATH,
) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    fixture, fixture_receipt, scanner = load_nonwff_fixture(
        root,
        fixture_path=fixture_path,
    )
    target_tree, evidence_index, evidence_refs = _verify_fixture_sources(
        root,
        fixture,
        scanner,
    )
    snapshot = _fixture_snapshot(
        root,
        fixture,
        scanner,
        target_tree=target_tree,
        evidence_index=evidence_index,
        evidence_refs=evidence_refs,
    )
    architecture_view = build_source_architecture_baseline_view(snapshot)
    validate_architecture_view(architecture_view)
    service = _capability_service(
        fixture,
        fixture_receipt,
        scanner,
        target_tree=target_tree,
        architecture_view=architecture_view,
        human_projection_sha256=snapshot.human_projection_sha256,
    )

    expectations = _mapping(fixture.get("expectations"), "fixture expectations")
    if architecture_view["summary"]["architecture_node_count"] != int(
        expectations.get("architecture_node_count", -1)
    ):
        raise NonWffConformanceError("non-WFF Architecture denominator drifted")
    if service.authority["capability_count"] != int(expectations.get("capability_count", -1)):
        raise NonWffConformanceError("non-WFF Capability denominator drifted")

    build_answer = service.find_capability("build artifact")
    conflict_id = _text(expectations.get("conflicting_capability_id"), "conflicting capability id")
    conflict_answer = service.find_capability(conflict_id)
    conflict_authority = service.explain_authority(conflict_id)
    conflict_evidence = service.get_evidence(conflict_id)
    missing_answer = service.find_capability("capability that does not exist in fixture")
    realization_answer = service.get_realizations("artifact-build")

    if build_answer["answer"]["existence"] != "confirmed-existing":
        raise NonWffConformanceError("observed non-WFF capability did not remain confirmed")
    if conflict_answer["answer"]["knowledge_state"] != "conflicting":
        raise NonWffConformanceError("conflicting non-WFF Capability posture was lost")
    if conflict_answer["answer"]["existence"] != "unknown":
        raise NonWffConformanceError("conflicting Capability was incorrectly treated as confirmed")
    if set(conflict_authority["answer"]["owners"]) != {
        "Platform Operations",
        "Release Automation",
    }:
        raise NonWffConformanceError("conflicting owner alternatives were collapsed")
    if missing_answer["answer"]["absence_proven"] is not False:
        raise NonWffConformanceError("non-WFF Capability miss incorrectly proved absence")
    if realization_answer["answer"]["realization_posture"] != "semantic-authority-derived-realization":
        raise NonWffConformanceError("non-WFF realization escaped the general query contract")
    if conflict_evidence["answer"]["exact_source_expansion"] != "resolve-through-verified-evidence-index":
        raise NonWffConformanceError("non-WFF evidence query used a profile-specific expansion contract")
    unknown_refs = sorted(set(conflict_evidence["answer"]["evidence_refs"]) - set(evidence_refs))
    if unknown_refs:
        raise NonWffConformanceError(
            "non-WFF Capability query emitted unresolved evidence refs: " + ", ".join(unknown_refs)
        )

    unknown_id = _text(expectations.get("unknown_id"), "unknown id")
    unknown_rows = {
        str(row["id"]): row
        for row in architecture_view["semantic_content"]["unknowns"]
    }
    if unknown_id not in unknown_rows or unknown_rows[unknown_id]["knowledge_state"] != "unknown":
        raise NonWffConformanceError("non-WFF source unknown was lost or upgraded")

    flow_fixture = _text(fixture.get("flow_fixture"), "flow_fixture")
    flow_service = FlowQueryService.from_fixture_path(
        root / flow_fixture,
        repository_root=root,
    )
    flow_answer = flow_service.trace_flow(disclosure_level="L2")
    flow_summary = _mapping(flow_answer.get("answer"), "non-WFF Flow answer").get("summary")
    flow_summary = _mapping(flow_summary, "non-WFF Flow summary")
    if flow_summary["visited_occurrence_count"] != int(
        expectations.get("flow_occurrence_count", -1)
    ):
        raise NonWffConformanceError("non-WFF Flow occurrence denominator drifted")
    if flow_summary["truncated"] is not False:
        raise NonWffConformanceError("non-WFF Flow query unexpectedly truncated")

    for label, answer in (
        ("find-capability", build_answer),
        ("conflicting-capability", conflict_answer),
        ("explain-authority", conflict_authority),
        ("get-evidence", conflict_evidence),
        ("get-realizations", realization_answer),
        ("trace-flow", flow_answer),
    ):
        _assert_no_raw_kernel_answer(answer, label)

    profile_violations = _general_profile_token_violations(
        architecture_view,
        service,
        flow_service.model,
    )
    if profile_violations:
        raise NonWffConformanceError(
            "general semantic surface contains WFF profile vocabulary: "
            + "; ".join(profile_violations)
        )

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": REPORT_STATUS,
        "conformance_version": CONFORMANCE_VERSION,
        "authority_mode": "conformance-evidence-only",
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "profile_id": fixture["profile_id"],
            "fixture_receipt": fixture_receipt,
            "source_commit": scanner.commit,
            "source_tree": target_tree,
            "evidence_source_count": len(evidence_index["sources"]),
            "evidence_ref_count": len(evidence_refs),
        },
        "supported_general_surfaces": {
            "architecture_view": architecture_view["schema_version"],
            "capability_authority": service.authority["schema_version"],
            "capability_queries": list(GENERAL_QUERY_KINDS[:-1]),
            "flow_query": GENERAL_QUERY_KINDS[-1],
            "progressive_disclosure": ["L0", "L1", "L2", "L3"],
        },
        "profile_specific_compatibility_surfaces": list(WFF_PROFILE_ONLY_SURFACES),
        "semantic_identity": {
            "architecture_view": architecture_view["semantic_fingerprint"],
            "capability_authority": service.authority["semantic_fingerprint"],
            "capability_query_index": service.index["semantic_fingerprint"],
            "flow_model": flow_service.model["semantic_fingerprint"],
        },
        "checks": [
            {"check": "exact-git-fixture-trust", "status": "passed", "detail": "fixture specification and three evidence sources were read from exact scanner-commit Git blobs"},
            {"check": "architecture-view-contract", "status": "passed", "detail": f"{architecture_view['summary']['architecture_node_count']} architecture nodes passed the same Architecture View validator"},
            {"check": "capability-authority-contract", "status": "passed", "detail": f"{service.authority['capability_count']} capabilities use the same ontology-authoritative Capability contract"},
            {"check": "conflict-preservation", "status": "passed", "detail": "deployment-admission remains conflicting/unknown with both owner claims visible"},
            {"check": "unknown-preservation", "status": "passed", "detail": "production approval remains explicit unknown rather than silently improving"},
            {"check": "evidence-closure", "status": "passed", "detail": "L3 capability evidence resolves only to exact admitted fixture evidence refs"},
            {"check": "false-absence-firewall", "status": "passed", "detail": "unmatched capability query keeps absence_proven=false"},
            {"check": "flow-query-contract", "status": "passed", "detail": f"generic CI trace_flow visited {flow_summary['visited_occurrence_count']} bounded handoffs without a Flow truth store"},
            {"check": "no-raw-kernel-consumer", "status": "passed", "detail": "normal non-WFF query answers expose no raw objects/occurrences/assertions arrays"},
            {"check": "no-wff-meta-kernel-dependency", "status": "passed", "detail": "general semantic IDs/types/kinds/predicates require no WFF P1/P2/P3/P4/PX vocabulary"},
        ],
        "query_observations": {
            "build_existence": build_answer["answer"]["existence"],
            "deployment_knowledge_state": conflict_answer["answer"]["knowledge_state"],
            "deployment_existence": conflict_answer["answer"]["existence"],
            "deployment_owners": conflict_authority["answer"]["owners"],
            "missing_absence_proven": missing_answer["answer"]["absence_proven"],
            "flow_occurrence_count": flow_summary["visited_occurrence_count"],
        },
        "claim_ceiling": _text(fixture.get("claim_ceiling"), "fixture claim_ceiling"),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_nonwff_conformance_report(report)


def validate_nonwff_conformance_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(payload, "non-WFF conformance report")
    if data.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise NonWffConformanceError("unsupported non-WFF conformance report schema")
    if data.get("status") != REPORT_STATUS:
        raise NonWffConformanceError("non-WFF conformance did not pass")
    if data.get("authority_mode") != "conformance-evidence-only":
        raise NonWffConformanceError("non-WFF conformance report attempted semantic authority")
    checks = _array(data.get("checks"), "non-WFF conformance checks")
    if len(checks) < 10 or any(
        not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks
    ):
        raise NonWffConformanceError("non-WFF conformance checks are incomplete")
    surfaces = _mapping(data.get("supported_general_surfaces"), "supported general surfaces")
    if tuple(surfaces.get("capability_queries", [])) != GENERAL_QUERY_KINDS[:-1]:
        raise NonWffConformanceError("supported general Capability query set drifted")
    if surfaces.get("flow_query") != "trace-flow":
        raise NonWffConformanceError("supported general Flow query drifted")
    if "before-generate" not in _array(
        data.get("profile_specific_compatibility_surfaces"),
        "profile-specific surfaces",
    ):
        raise NonWffConformanceError("WFF Before Generate profile boundary was lost")
    fingerprint = _text(data.get("report_fingerprint"), "report_fingerprint")
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise NonWffConformanceError("non-WFF conformance report fingerprint mismatch")
    return data
