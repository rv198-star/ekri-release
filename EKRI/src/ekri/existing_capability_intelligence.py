"""Legacy v0.9 Capability compatibility projections over v1.0 authority.

P7 retires the original Architecture->Capability Catalog semantic writer and
Before Generate evaluator. This module now owns only backward-compatible
projection/render/persistence plus the historical entry point. Capability
semantics are owned by `capability_authority`; recommendation policy lives in
`capability_contract`; normal consumption uses `capability_query`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import uuid

from .capability_contract import (
    AUDIT_SCHEMA_VERSION,
    CATALOG_SCHEMA_VERSION,
    PHASE_ID,
    REPORT_SCHEMA_VERSION,
    SPEC_PROFILE_ID,
    VALID_STATUS,
    CapabilityCheckRequest,
    CapabilitySpecIdentity,
    ExistingCapabilityError,
    _json_bytes,
    _object,
    _request_id,
    _request_payload,
    _sha256,
    _text,
    build_request,
    load_capability_spec,
    normalize_capability_alias,
    utc_now_iso,
)
from .observation_boundary import (
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
)


def render_before_generate_markdown(report: dict[str, Any]) -> str:
    answers = report["answers"]
    resolution = report["resolution"]
    lines = [
        "# Before Generate — Existing Capability Check",
        "",
        f"- Request ID: `{report['request_id']}`",
        f"- Source commit: `{report['source']['commit']}`",
        f"- Source tree: `{report['source']['tree']}`",
        f"- Query: `{report['request']['capability_query']}`",
        f"- Resolution: `{resolution['status']}`",
        f"- Matched capability: `{resolution['matched_capability_id'] or 'none'}`",
        "",
        "## 1. Does the capability already exist?",
        "",
        f"- Status: `{answers['capability_exists']['status']}`",
        f"- Knowledge state: `{answers['capability_exists']['knowledge_state']}`",
        f"- Confidence: `{answers['capability_exists']['confidence']}`",
        "",
        "## 2. Where does it exist?",
        "",
    ]
    if answers["where_it_exists"]["locations"]:
        for location in answers["where_it_exists"]["locations"]:
            lines.append(f"- `{location}`")
    else:
        lines.append("- No unique evidence-backed location resolved.")
    if answers["where_it_exists"]["owners"]:
        lines.append("- Owners: " + "; ".join(answers["where_it_exists"]["owners"]))
    lines.extend(
        [
            "",
            "## 3. Why may reuse be limited?",
            "",
            answers["why_reuse_may_be_limited"]["conclusion"],
            "",
        ]
    )
    for item in answers["why_reuse_may_be_limited"]["items"]:
        lines.append(
            f"- `{item['kind']}` / `{item['source_id']}`: {item['statement']}"
        )
    if not answers["why_reuse_may_be_limited"]["items"]:
        lines.append("- No evidence-backed limitation available.")
    if answers["why_reuse_may_be_limited"]["caller_supplied_non_reuse_reason"]:
        lines.append(
            "- Caller-supplied non-reuse reason: "
            + answers["why_reuse_may_be_limited"]["caller_supplied_non_reuse_reason"]
        )
    lines.extend(
        [
            "",
            "## 4. What triggered the proposed change?",
            "",
            f"- Basis: `{answers['trigger_basis']['basis']}`",
            f"- Classification: `{answers['trigger_basis']['classification']}`",
            f"- Reference: `{answers['trigger_basis']['reference'] or 'none'}`",
            f"- Policy: {answers['trigger_basis']['replacement_policy']}",
            "",
            "## 5. Does it affect the WFF mainline?",
            "",
            f"- Classification: `{answers['wff_mainline_impact']['classification']}`",
            f"- Knowledge state: `{answers['wff_mainline_impact']['knowledge_state']}`",
            f"- Confidence: `{answers['wff_mainline_impact']['confidence']}`",
            f"- Rationale: {answers['wff_mainline_impact']['rationale']}",
            "",
            "## 6. Reuse recommendation",
            "",
            f"- Posture: `{answers['reuse_recommendation']['posture']}`",
            f"- Reason: {answers['reuse_recommendation']['reason']}",
            f"- Architecture decision required: `{str(answers['reuse_recommendation']['requires_architecture_decision']).lower()}`",
            f"- Decision status: `{answers['reuse_recommendation']['decision_status']}`",
        ]
    )
    if answers["reuse_recommendation"]["decision_reference"]:
        lines.append(
            f"- Decision reference: `{answers['reuse_recommendation']['decision_reference']}`"
        )
        lines.append(
            "- Decision acceptance verification: `"
            + answers["reuse_recommendation"]["decision_acceptance_verification"]
            + "`"
        )
    if answers["reuse_recommendation"]["warning"]:
        lines.append(f"- Warning: {answers['reuse_recommendation']['warning']}")
    refs = sorted(
        set(answers["capability_exists"]["evidence_refs"])
        | set(answers["where_it_exists"]["evidence_refs"])
        | set(answers["wff_mainline_impact"]["evidence_refs"])
    )
    lines.extend(["", "## Evidence", ""])
    if refs:
        for ref in refs:
            lines.append(f"- `{ref}`")
    else:
        lines.append("- No unique evidence set resolved.")
    lines.extend(["", "## Claim Ceiling", "", report["claim_ceiling"], ""])
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
        os.replace(
            temporary,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        created = False
        os.fsync(parent_fd)
    except OSError as exc:
        raise ExistingCapabilityError(
            f"failed to persist Capability compatibility output {filename}: {exc}"
        ) from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _persist_outputs(
    repository_root: Path,
    *,
    catalog: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, str]:
    catalog_bytes = _json_bytes(catalog)
    if catalog.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise ExistingCapabilityError(
            "cannot persist an unsupported capability catalog compatibility view"
        )
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ExistingCapabilityError(
            "cannot persist an unsupported Before Generate compatibility report"
        )
    if report.get("source", {}).get("tree") != catalog.get("source", {}).get("tree"):
        raise ExistingCapabilityError("catalog and report source trees diverge")
    if report.get("source", {}).get("catalog_sha256") != _sha256(catalog_bytes):
        raise ExistingCapabilityError("report catalog digest does not match catalog payload")
    expected_request_id = _request_id(
        _object(report.get("request"), "report request"),
        _text(report.get("source", {}).get("tree"), "report source tree"),
    )
    if report.get("request_id") != expected_request_id:
        raise ExistingCapabilityError(
            "report request id does not match its canonical request"
        )
    report_bytes = _json_bytes(report)
    markdown_bytes = render_before_generate_markdown(report).encode("utf-8")
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "created_at": utc_now_iso(),
        "request_id": report["request_id"],
        "source_tree": report["source"]["tree"],
        "status": "phase2-output-persisted",
        "output_digests": {
            "capability-catalog.json": _sha256(catalog_bytes),
            f"{report['request_id']}.json": _sha256(report_bytes),
            f"{report['request_id']}.md": _sha256(markdown_bytes),
        },
        "checks": [
            {
                "check": "catalog-report-binding",
                "status": "passed",
                "detail": "report catalog digest matches the derived compatibility catalog payload",
            },
            {
                "check": "ontology-authority-source",
                "status": "passed",
                "detail": "compatibility outputs derive from the P6 ontology-authoritative Capability slice",
            },
            {
                "check": "no-follow-atomic-persistence",
                "status": "passed",
                "detail": "outputs were written through real-directory descriptors and atomic replacement",
            },
        ],
        "claim_ceiling": (
            "Persistence and digest checks prove compatibility-output integrity only; "
            "Capability semantic authority remains in .EKRI/semantic and this audit cannot strengthen the recommendation."
        ),
    }
    audit_bytes = _json_bytes(audit)

    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "intelligence", report["source"]["tree"]):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        _secure_atomic_write(parent_fd, "capability-catalog.json", catalog_bytes)
        checks_fd = _open_or_create_directory(parent_fd, "checks")
        opened.append(checks_fd)
        _secure_atomic_write(
            checks_fd,
            f"{report['request_id']}.json",
            report_bytes,
        )
        _secure_atomic_write(
            checks_fd,
            f"{report['request_id']}.md",
            markdown_bytes,
        )
        audits_fd = _open_or_create_directory(parent_fd, "audits")
        opened.append(audits_fd)
        _secure_atomic_write(
            audits_fd,
            f"{report['request_id']}.json",
            audit_bytes,
        )
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = (
        repository_root / ".EKRI" / "intelligence" / report["source"]["tree"]
    )
    return {
        "output_root": str(output_root),
        "catalog": str(output_root / "capability-catalog.json"),
        "report": str(
            output_root / "checks" / f"{report['request_id']}.json"
        ),
        "human_report": str(
            output_root / "checks" / f"{report['request_id']}.md"
        ),
        "audit": str(
            output_root / "audits" / f"{report['request_id']}.json"
        ),
    }


def project_legacy_capability_catalog(service: object) -> dict[str, Any]:
    """Project the sole Capability authority into the v0.9 catalog schema."""
    authority = getattr(service, "authority", None)
    index = getattr(service, "index", None)
    if not isinstance(authority, dict) or not isinstance(index, dict):
        raise ExistingCapabilityError(
            "legacy Capability projection requires verified Capability authority"
        )
    if authority.get("authority_mode") != "ontology-authoritative":
        raise ExistingCapabilityError(
            "legacy Capability projection source is not ontology-authoritative"
        )
    source = _object(authority.get("source"), "Capability authority source")
    human_sha = _text(
        source.get("phase1_human_projection_sha256"),
        "Capability authority Phase1 human projection digest",
        minimum=64,
        maximum=64,
    )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "profile_id": SPEC_PROFILE_ID,
        "created_at": utc_now_iso(),
        "status": "capability-catalog-built",
        "source": {
            "snapshot_id": source["snapshot_id"],
            "commit": source["commit"],
            "tree": source["tree"],
            "phase1_human_projection_sha256": human_sha,
        },
        "specification": dict(authority["specification"]),
        "capability_count": authority["capability_count"],
        "capabilities": json.loads(
            json.dumps(authority["capabilities"], ensure_ascii=False)
        ),
        "alias_index": json.loads(
            json.dumps(index["alias_index"], ensure_ascii=False)
        ),
        "ambiguous_aliases": json.loads(
            json.dumps(index["ambiguous_aliases"], ensure_ascii=False)
        ),
        "checks": [
            {
                "check": "ontology-authority-cutover",
                "status": "passed",
                "detail": "legacy Capability Catalog is derived from the sole ontology-authoritative Capability semantic slice",
            },
            {
                "check": "architecture-view-provenance",
                "status": "passed",
                "detail": "Capability authority is bound to its verified Architecture View",
            },
            {
                "check": "evidence-reference-closure",
                "status": "passed",
                "detail": "Capability authority preserves verified evidence references",
            },
            {
                "check": "alias-index-derived",
                "status": "passed",
                "detail": (
                    f"derived {len(index['alias_index'])} exact normalized aliases; "
                    f"{len(index['ambiguous_aliases'])} are ambiguous"
                ),
            },
        ],
        "claim_ceiling": (
            "This v0.9 Capability Catalog is a derived compatibility projection from the ontology-authoritative Capability semantic slice. "
            "It is not peer semantic authority and does not prove exhaustive absence."
        ),
    }


def project_legacy_before_generate_report(
    *,
    request: CapabilityCheckRequest,
    catalog: dict[str, Any],
    query_answer: dict[str, Any],
) -> dict[str, Any]:
    """Project the named P6 answer into the v0.9 Before Generate schema."""
    if query_answer.get("query_kind") != "before-generate":
        raise ExistingCapabilityError(
            "legacy Before Generate projection requires before-generate answer"
        )
    resolution = _object(
        query_answer.get("resolution"), "Capability query resolution"
    )
    answer = _object(query_answer.get("answer"), "Capability query answer")
    request_payload = _request_payload(request)
    request_id = _request_id(request_payload, catalog["source"]["tree"])
    recommendation = _object(
        answer.get("reuse_recommendation"), "Capability query recommendation"
    )
    mainline_answer = _object(
        answer.get("wff_mainline_impact"), "Capability query mainline impact"
    )
    decision_allowed = recommendation.get("posture") != "insufficient-evidence"
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "created_at": utc_now_iso(),
        "status": VALID_STATUS,
        "request_id": request_id,
        "source": {
            "snapshot_id": catalog["source"]["snapshot_id"],
            "commit": catalog["source"]["commit"],
            "tree": catalog["source"]["tree"],
            "catalog_sha256": _sha256(_json_bytes(catalog)),
        },
        "request": request_payload,
        "resolution": {
            "status": resolution["status"],
            "candidate_capability_ids": list(
                resolution["candidate_capability_ids"]
            ),
            "matched_capability_id": resolution["matched_capability_id"],
            "matched_capability_name": resolution["matched_capability_name"],
        },
        "answers": {
            "capability_exists": dict(answer["capability_exists"]),
            "where_it_exists": dict(answer["where_it_exists"]),
            "why_reuse_may_be_limited": dict(
                answer["why_reuse_may_be_limited"]
            ),
            "trigger_basis": dict(answer["trigger_basis"]),
            "wff_mainline_impact": dict(mainline_answer),
            "reuse_recommendation": dict(recommendation),
        },
        "boundary": {
            "decision_allowed": decision_allowed,
            "decision_status": (
                "actionable"
                if decision_allowed
                else "blocked-insufficient-evidence"
            ),
            "checks": [
                {
                    "check": "capability-authority-cutover",
                    "status": "passed",
                    "detail": "Before Generate consumed the ontology-authoritative Capability slice through the named query facade",
                },
                {
                    "check": "deterministic-alias-resolution",
                    "status": (
                        "passed"
                        if resolution["status"] == "matched"
                        else "blocked"
                    ),
                    "detail": f"resolution status: {resolution['status']}",
                },
                {
                    "check": "trigger-basis-explicit",
                    "status": "passed",
                    "detail": f"trigger basis: {request.trigger_basis}",
                },
                {
                    "check": "replacement-policy",
                    "status": (
                        "passed"
                        if recommendation["posture"] != "insufficient-evidence"
                        or request.change_mode != "behavior-replacement"
                        else "blocked"
                    ),
                    "detail": recommendation["reason"],
                },
                {
                    "check": "mainline-impact-explicit",
                    "status": (
                        "passed"
                        if mainline_answer["classification"] != "unknown"
                        else "blocked"
                    ),
                    "detail": mainline_answer["rationale"],
                },
            ],
        },
        "claim_ceiling": (
            "This Before Generate report is a derived compatibility projection over the ontology-authoritative Capability slice. "
            "It preserves the v0.9 recommendation boundary without becoming peer authority or proving exhaustive absence, implementation fitness, production readiness, or complete impact."
        ),
    }


def run_existing_capability_check(
    repository_root: str | Path,
    request: CapabilityCheckRequest,
    *,
    write_outputs: bool = True,
    project_asset_id: str | None = None,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    from .capability_query import CapabilityQueryService

    source_tree = ""
    if project_asset_id is None:
        spec, _ = load_capability_spec()
        target = _object(spec.get("target"), "capability specification target")
        source_tree = _text(target.get("tree"), "target tree")
    try:
        service = CapabilityQueryService.from_repository(
            root,
            source_tree=source_tree,
            project_asset_id=project_asset_id,
        )
    except Exception as exc:
        raise ExistingCapabilityError(
            f"ontology-authoritative Capability service could not be established: {exc}"
        ) from exc

    catalog = project_legacy_capability_catalog(service)
    query_answer = service.before_generate(request)
    report = project_legacy_before_generate_report(
        request=request,
        catalog=catalog,
        query_answer=query_answer,
    )
    authority = service.authority
    result = {
        "schema_version": "ekri.existing-capability-run.v1",
        "status": VALID_STATUS,
        "authority_source": {
            "mode": "ontology-authoritative-capability-slice",
            "input_mode": service.input_mode,
            "project_asset_id": service.project_asset_id,
            "snapshot_id": authority["source"]["snapshot_id"],
            "source_commit": authority["source"]["commit"],
            "source_tree": authority["source"]["tree"],
            "semantic_fingerprint": authority["semantic_fingerprint"],
            "projection_fingerprint": authority["projection_fingerprint"],
            "legacy_catalog_posture": "derived-compatibility-view",
        },
        "catalog": catalog,
        "report": report,
        "outputs": {},
    }
    if write_outputs:
        authority_path = service.persist_authority(root)
        outputs = _persist_outputs(root, catalog=catalog, report=report)
        outputs["authority"] = str(authority_path)
        result["outputs"] = outputs
    return result
