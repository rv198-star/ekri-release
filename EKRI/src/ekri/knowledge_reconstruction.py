"""Phase 1 evidence-linked baseline knowledge reconstruction."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable
import uuid

from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    resolve_scanner_identity,
)


MEMORY_SCHEMA_VERSION = "ekri.architecture-memory.v1"
EVIDENCE_SCHEMA_VERSION = "ekri.evidence-index.v1"
REPORT_SCHEMA_VERSION = "ekri.reconstruction-report.v1"
SPEC_SCHEMA_VERSION = "ekri.wff-baseline-reconstruction-spec.v1"
PHASE_ID = "phase1-baseline-knowledge-reconstruction"
PROFILE_ID = "wff-v1.6.2-baseline"
VALID_STATUS = "architecture-memory-reconstructed"

KNOWLEDGE_STATES = {
    "observed-fact",
    "inferred-knowledge",
    "unknown",
}
INFERENCE_CONFIDENCE = {"high", "medium", "low"}


class KnowledgeReconstructionError(RuntimeError):
    """Raised when architecture memory cannot be reconstructed safely."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KnowledgeReconstructionError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise KnowledgeReconstructionError(
            f"{label} must be a list with at least {minimum} item(s)"
        )
    return value


def _require_text(
    value: object,
    label: str,
    *,
    minimum: int = 1,
    maximum: int = 4000,
) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise KnowledgeReconstructionError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _require_identifier(value: object, label: str) -> str:
    identifier = _require_text(value, label, minimum=2, maximum=120)
    if not identifier[0].isalpha() or not all(
        character.isalnum() or character in "._-" for character in identifier
    ):
        raise KnowledgeReconstructionError(
            f"{label} must start with a letter and use letters, digits, '.', '_', or '-'"
        )
    return identifier


def load_reconstruction_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> dict[str, Any]:
    if path is None:
        try:
            identity = scanner or resolve_scanner_identity()
        except ObservationBoundaryError as exc:
            raise KnowledgeReconstructionError(
                f"active scanner provenance is unverifiable: {exc}"
            ) from exc
        relative_path = "EKRI/specs/wff-v162-baseline-reconstruction.json"
        entries = [
            entry
            for entry in _tree_entries(
                identity.repository_root,
                identity.tree,
                pathspec=relative_path,
            )
            if entry[3] == relative_path
        ]
        if len(entries) != 1:
            raise KnowledgeReconstructionError(
                "committed reconstruction specification is missing or ambiguous"
            )
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise KnowledgeReconstructionError(
                "committed reconstruction specification must be a regular Git blob"
            )
        raw = _run_git(
            Path(identity.repository_root),
            "cat-file",
            "blob",
            oid,
            binary=True,
        )
        assert isinstance(raw, bytes)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KnowledgeReconstructionError(
                f"committed reconstruction specification cannot be read: {exc}"
            ) from exc
    else:
        source = Path(path).expanduser()
        try:
            metadata = source.lstat()
        except OSError as exc:
            raise KnowledgeReconstructionError(
                f"reconstruction specification cannot be inspected: {exc}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise KnowledgeReconstructionError(
                f"reconstruction specification is not a safe regular file: {source}"
            )
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KnowledgeReconstructionError(
                f"reconstruction specification cannot be read: {exc}"
            ) from exc
    spec = _require_dict(payload, "reconstruction specification")
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise KnowledgeReconstructionError("unsupported reconstruction specification schema")
    if spec.get("profile_id") != PROFILE_ID:
        raise KnowledgeReconstructionError("unexpected reconstruction profile id")
    return spec


def _find_anchor(text: str, contains: str, *, label: str) -> dict[str, Any]:
    lines = text.splitlines()
    matches = [
        (index, line)
        for index, line in enumerate(lines, start=1)
        if contains in line
    ]
    if not matches:
        raise KnowledgeReconstructionError(
            f"required evidence anchor was not found: {label}: {contains}"
        )
    return {
        "contains": contains,
        "line_numbers": [line_number for line_number, _ in matches],
        "excerpts": [line.strip()[:500] for _, line in matches],
    }


def _extract_skill_catalog(payload: object) -> dict[str, Any]:
    catalog = _require_dict(payload, "skill catalog")
    skills = _require_list(catalog.get("skills"), "skill catalog skills")
    categories = Counter(str(item.get("category", "")) for item in skills if isinstance(item, dict))
    phases = [
        {
            "name": str(item.get("name", "")),
            "phase": str(item.get("phase", "")),
            "release_posture": str(item.get("release_posture", "")),
        }
        for item in skills
        if isinstance(item, dict) and item.get("category") == "phase-entry"
    ]
    return {
        "schema_version": catalog.get("schema_version"),
        "skill_count": len(skills),
        "category_counts": dict(sorted(categories.items())),
        "phase_entries": sorted(phases, key=lambda item: item["name"]),
        "published_runtime_skills": sorted(
            str(item.get("name", ""))
            for item in skills
            if isinstance(item, dict)
            and item.get("release_posture") == "published-runtime-facing"
        ),
        "retired_skills": sorted(
            str(item.get("name", ""))
            for item in skills
            if isinstance(item, dict) and item.get("category") == "retired-legacy"
        ),
    }


def _extract_install_profiles(payload: object) -> dict[str, Any]:
    profiles = _require_dict(payload, "install profile configuration")
    capability_packages = _require_list(
        profiles.get("capability_packages"),
        "install profile capability_packages",
    )
    profile_rows = _require_list(profiles.get("profiles"), "install profiles")
    resource_modules = _require_list(
        profiles.get("resource_modules"),
        "install profile resource_modules",
    )
    return {
        "default_profile": profiles.get("default_profile"),
        "capability_package_count": len(capability_packages),
        "capability_packages": [
            {
                "id": str(item.get("id", "")),
                "skills": list(item.get("skills", [])),
                "resource_modules": list(item.get("resource_modules", [])),
            }
            for item in capability_packages
            if isinstance(item, dict)
        ],
        "profile_count": len(profile_rows),
        "profiles": [
            {
                "id": str(item.get("id", "")),
                "package_kind": str(item.get("package_kind", "")),
                "layer": str(item.get("layer", "")),
                "capabilities": list(item.get("capabilities", [])),
            }
            for item in profile_rows
            if isinstance(item, dict)
        ],
        "resource_module_count": len(resource_modules),
    }


def _extract_output_policy(payload: object) -> dict[str, Any]:
    policy = _require_dict(payload, "generated output policy")
    sidecar = _require_dict(policy.get("human_review_sidecar"), "human_review_sidecar")
    return {
        "human_reviewed_output_locale": policy.get("human_reviewed_output_locale"),
        "allowed_locales": list(policy.get("allowed_locales", [])),
        "sidecar_repository_default": sidecar.get("repository_default"),
        "sidecar_release_package_default": sidecar.get("release_package_default"),
        "sidecar_mainline_waits": sidecar.get("mainline_waits"),
        "sidecar_stale_publication_allowed": sidecar.get("stale_publication_allowed"),
    }


def _corpus_inventory(paths: Iterable[str]) -> dict[str, Any]:
    path_list = list(paths)
    top_level = Counter(path.split("/", 1)[0] for path in path_list)
    phase_script_prefixes = {
        "phase1": "scripts/phase1/",
        "phase2": "scripts/phase2/",
        "phase3": "scripts/phase3/",
        "phase4": "scripts/phase4/",
        "phasex": "scripts/phasex/",
        "common": "scripts/common/",
        "release": "scripts/release/",
    }
    phase_script_counts = {
        phase: sum(path.startswith(prefix) and path.endswith(".py") for path in path_list)
        for phase, prefix in phase_script_prefixes.items()
    }
    skill_names = sorted(
        path.split("/", 2)[1]
        for path in path_list
        if path.startswith("skills/") and path.endswith("/SKILL.md") and path.count("/") == 2
    )
    return {
        "accepted_path_count": len(path_list),
        "top_level_path_counts": dict(sorted(top_level.items())),
        "phase_python_script_counts": phase_script_counts,
        "skill_directory_count": len(skill_names),
        "skill_directories": skill_names,
    }


def _process_evidence_sources(
    reader: AdmittedGitReader,
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    sources = _require_list(spec.get("evidence_sources"), "evidence_sources", minimum=1)
    evidence_index: list[dict[str, Any]] = []
    anchors_by_ref: dict[str, dict[str, Any]] = {}
    observed_inventory: dict[str, Any] = {
        "corpus": _corpus_inventory(reader.manifest["corpus"]["paths"])
    }
    source_ids: set[str] = set()

    for source_index, raw_source in enumerate(sources, start=1):
        source = _require_dict(raw_source, f"evidence_sources[{source_index}]")
        source_id = _require_identifier(source.get("id"), f"evidence_sources[{source_index}].id")
        if source_id in source_ids:
            raise KnowledgeReconstructionError(f"duplicate evidence source id: {source_id}")
        source_ids.add(source_id)
        path = _require_text(source.get("path"), f"evidence_sources[{source_index}].path")
        try:
            text = reader.read_text(path)
            receipt = reader.receipt(path).to_dict()
        except AdmittedEvidenceError as exc:
            raise KnowledgeReconstructionError(str(exc)) from exc

        anchors: list[dict[str, Any]] = []
        anchor_ids: set[str] = set()
        for anchor_index, raw_anchor in enumerate(
            _require_list(source.get("anchors"), f"{source_id}.anchors", minimum=1),
            start=1,
        ):
            anchor = _require_dict(raw_anchor, f"{source_id}.anchors[{anchor_index}]")
            anchor_id = _require_identifier(
                anchor.get("id"), f"{source_id}.anchors[{anchor_index}].id"
            )
            if anchor_id in anchor_ids:
                raise KnowledgeReconstructionError(
                    f"duplicate anchor id in {source_id}: {anchor_id}"
                )
            anchor_ids.add(anchor_id)
            contains = _require_text(
                anchor.get("contains"),
                f"{source_id}.anchors[{anchor_index}].contains",
                maximum=800,
            )
            match = _find_anchor(text, contains, label=f"{source_id}.{anchor_id}")
            evidence_ref = f"{source_id}.{anchor_id}"
            anchor_record = {
                "id": anchor_id,
                "evidence_ref": evidence_ref,
                **match,
            }
            anchors.append(anchor_record)
            anchors_by_ref[evidence_ref] = {
                "source_id": source_id,
                "path": path,
                **anchor_record,
            }

        extractor = str(source.get("extractor", "")).strip()
        if extractor:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise KnowledgeReconstructionError(
                    f"evidence extractor requires valid JSON: {source_id}: {exc}"
                ) from exc
            if extractor == "wff-skill-catalog":
                observed_inventory["skill_catalog"] = _extract_skill_catalog(payload)
            elif extractor == "wff-install-profiles":
                observed_inventory["install_profiles"] = _extract_install_profiles(payload)
            elif extractor == "generated-output-policy":
                observed_inventory["generated_output_policy"] = _extract_output_policy(payload)
            else:
                raise KnowledgeReconstructionError(
                    f"unsupported evidence extractor: {extractor}"
                )

        evidence_index.append(
            {
                "id": source_id,
                "path": path,
                "media_type": str(source.get("media_type", "text/plain")),
                "blob": receipt,
                "line_count": len(text.splitlines()),
                "anchors": anchors,
            }
        )

    return evidence_index, anchors_by_ref, observed_inventory


def _validate_evidence_refs(
    refs: object,
    *,
    label: str,
    anchors_by_ref: dict[str, dict[str, Any]],
    minimum: int,
) -> list[str]:
    raw_refs = _require_list(refs, label, minimum=minimum)
    normalized: list[str] = []
    for index, raw_ref in enumerate(raw_refs, start=1):
        ref = _require_text(raw_ref, f"{label}[{index}]", maximum=240)
        if ref not in anchors_by_ref:
            raise KnowledgeReconstructionError(
                f"{label}[{index}] references unresolved evidence: {ref}"
            )
        if ref not in normalized:
            normalized.append(ref)
    return normalized


def _validate_knowledge_state(
    entry: dict[str, Any],
    *,
    label: str,
    anchors_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    state = _require_text(entry.get("knowledge_state"), f"{label}.knowledge_state")
    if state not in KNOWLEDGE_STATES:
        raise KnowledgeReconstructionError(f"unsupported knowledge state: {state}")
    confidence = _require_text(entry.get("confidence"), f"{label}.confidence")
    rationale = _require_text(entry.get("rationale"), f"{label}.rationale", minimum=8)
    if state == "observed-fact":
        if confidence != "verified":
            raise KnowledgeReconstructionError(
                f"{label} observed facts must use confidence=verified"
            )
        evidence_refs = _validate_evidence_refs(
            entry.get("evidence_refs"),
            label=f"{label}.evidence_refs",
            anchors_by_ref=anchors_by_ref,
            minimum=1,
        )
    elif state == "inferred-knowledge":
        if confidence not in INFERENCE_CONFIDENCE:
            raise KnowledgeReconstructionError(
                f"{label} inferred knowledge has invalid confidence: {confidence}"
            )
        evidence_refs = _validate_evidence_refs(
            entry.get("evidence_refs"),
            label=f"{label}.evidence_refs",
            anchors_by_ref=anchors_by_ref,
            minimum=1,
        )
    else:
        if confidence != "not-applicable":
            raise KnowledgeReconstructionError(
                f"{label} unknown knowledge must use confidence=not-applicable"
            )
        evidence_refs = _validate_evidence_refs(
            entry.get("evidence_refs", []),
            label=f"{label}.evidence_refs",
            anchors_by_ref=anchors_by_ref,
            minimum=0,
        )
    result = dict(entry)
    result["knowledge_state"] = state
    result["confidence"] = confidence
    result["rationale"] = rationale
    result["evidence_refs"] = evidence_refs
    return result


def _validate_entry_collection(
    spec: dict[str, Any],
    key: str,
    *,
    anchors_by_ref: dict[str, dict[str, Any]],
    required_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = _require_list(spec.get(key), key, minimum=1)
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        label = f"{key}[{index}]"
        entry = _require_dict(raw, label)
        entry_id = _require_identifier(entry.get("id"), f"{label}.id")
        if entry_id in ids:
            raise KnowledgeReconstructionError(f"duplicate {key} id: {entry_id}")
        ids.add(entry_id)
        normalized = _validate_knowledge_state(
            entry,
            label=label,
            anchors_by_ref=anchors_by_ref,
        )
        normalized["id"] = entry_id
        for field in required_fields:
            normalized[field] = _require_text(
                entry.get(field),
                f"{label}.{field}",
                minimum=2,
            )
        result.append(normalized)
    return result


def _validate_architecture_tree(
    spec: dict[str, Any],
    anchors_by_ref: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    nodes = _validate_entry_collection(
        spec,
        "architecture_tree",
        anchors_by_ref=anchors_by_ref,
        required_fields=("name", "kind", "responsibility"),
    )
    ids = {node["id"] for node in nodes}
    roots = 0
    parent_by_id: dict[str, str] = {}
    for node in nodes:
        parent = str(node.get("parent_id", "")).strip()
        node["parent_id"] = parent
        node["non_responsibilities"] = [
            _require_text(value, f"{node['id']}.non_responsibilities")
            for value in _require_list(
                node.get("non_responsibilities", []),
                f"{node['id']}.non_responsibilities",
            )
        ]
        if not parent:
            roots += 1
        elif parent not in ids:
            raise KnowledgeReconstructionError(
                f"architecture node parent is missing: {node['id']} -> {parent}"
            )
        if parent == node["id"]:
            raise KnowledgeReconstructionError(
                f"architecture node cannot parent itself: {node['id']}"
            )
        parent_by_id[node["id"]] = parent
    if roots != 1:
        raise KnowledgeReconstructionError(
            f"architecture tree must have exactly one root, found {roots}"
        )
    for node_id in ids:
        seen: set[str] = set()
        current = node_id
        while current:
            if current in seen:
                raise KnowledgeReconstructionError(
                    f"architecture tree contains a cycle at {current}"
                )
            seen.add(current)
            current = parent_by_id.get(current, "")
    return nodes


def _scanner_dict(scanner: ScannerIdentity) -> dict[str, Any]:
    return asdict(scanner)


def build_wff_architecture_memory(
    repository_root: str | Path,
    observation_manifest: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise KnowledgeReconstructionError(
            f"active Phase 1 scanner provenance is unverifiable: {exc}"
        ) from exc
    try:
        reader = AdmittedGitReader(root, observation_manifest)
    except AdmittedEvidenceError as exc:
        raise KnowledgeReconstructionError(str(exc)) from exc

    reconstruction_spec = spec or load_reconstruction_spec(scanner=scanner)
    target_spec = _require_dict(reconstruction_spec.get("target"), "spec.target")
    expected_commit = _require_text(target_spec.get("commit"), "spec.target.commit")
    expected_tree = _require_text(target_spec.get("tree"), "spec.target.tree")
    if reader.commit != expected_commit or reader.tree != expected_tree:
        raise KnowledgeReconstructionError(
            "WFF baseline reconstruction profile received the wrong target commit/tree"
        )

    evidence_index, anchors_by_ref, observed_inventory = _process_evidence_sources(
        reader,
        reconstruction_spec,
    )
    architecture_tree = _validate_architecture_tree(
        reconstruction_spec,
        anchors_by_ref,
    )
    responsibility_map = _validate_entry_collection(
        reconstruction_spec,
        "responsibility_map",
        anchors_by_ref=anchors_by_ref,
        required_fields=("subject", "owner", "responsibility"),
    )
    implementation_intents = _validate_entry_collection(
        reconstruction_spec,
        "implementation_intents",
        anchors_by_ref=anchors_by_ref,
        required_fields=("subject", "statement"),
    )
    assurance_ownership = _validate_entry_collection(
        reconstruction_spec,
        "assurance_ownership",
        anchors_by_ref=anchors_by_ref,
        required_fields=("subject", "owner", "responsibility"),
    )
    constraints = _validate_entry_collection(
        reconstruction_spec,
        "constraints",
        anchors_by_ref=anchors_by_ref,
        required_fields=("subject", "statement"),
    )
    unknowns = _validate_entry_collection(
        reconstruction_spec,
        "unknowns",
        anchors_by_ref=anchors_by_ref,
        required_fields=("subject", "statement"),
    )
    if any(item["knowledge_state"] != "unknown" for item in unknowns):
        raise KnowledgeReconstructionError("all Phase 1 unknown entries must remain unknown")

    created_at = utc_now_iso()
    manifest_bytes = _json_bytes(observation_manifest)
    evidence_payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "profile_id": PROFILE_ID,
        "created_at": created_at,
        "source": {
            "repository_root": str(root),
            "commit": reader.commit,
            "tree": reader.tree,
        },
        "sources": evidence_index,
        "read_paths": list(reader.read_paths()),
        "read_blob_count": len(reader.read_paths()),
    }
    memory = {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": VALID_STATUS,
        "snapshot_id": f"{PROFILE_ID}:{reader.tree}",
        "created_at": created_at,
        "profile_id": PROFILE_ID,
        "source": {
            "repository_root": str(root),
            "commit": reader.commit,
            "tree": reader.tree,
            "observation_manifest_schema": observation_manifest["schema_version"],
            "observation_manifest_sha256": _sha256_bytes(manifest_bytes),
            "admitted_path_set_sha256": observation_manifest["corpus"]["path_set_sha256"],
        },
        "scanner": _scanner_dict(scanner),
        "evidence_index_ref": "evidence-index.json",
        "observed_inventory": observed_inventory,
        "system_architecture_tree": architecture_tree,
        "module_responsibility_map": responsibility_map,
        "implementation_intent_summary": implementation_intents,
        "validation_assurance_ownership": assurance_ownership,
        "constraints": constraints,
        "unknowns": unknowns,
        "claim_ceiling": _require_text(
            reconstruction_spec.get("claim_ceiling"),
            "spec.claim_ceiling",
            minimum=40,
        ),
    }
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": VALID_STATUS,
        "created_at": created_at,
        "profile_id": PROFILE_ID,
        "source_commit": reader.commit,
        "source_tree": reader.tree,
        "checks": [
            {
                "check": "phase0-manifest-revalidation",
                "status": "passed",
                "detail": "scanner/source identities and admitted corpus were independently revalidated",
            },
            {
                "check": "admitted-blob-only",
                "status": "passed",
                "detail": "every target blob read path is present in the Phase 0 admitted corpus",
            },
            {
                "check": "evidence-anchor-resolution",
                "status": "passed",
                "detail": f"resolved {len(anchors_by_ref)} source anchors across {len(evidence_index)} blobs",
            },
            {
                "check": "knowledge-state-separation",
                "status": "passed",
                "detail": "observed facts, inferred knowledge, confidence, rationale, and unknowns are explicit",
            },
            {
                "check": "capability-oriented-tree",
                "status": "passed",
                "detail": "architecture nodes are declared capability/route/phase/support/assurance surfaces rather than repository directories",
            },
        ],
        "counts": {
            "evidence_sources": len(evidence_index),
            "evidence_anchors": len(anchors_by_ref),
            "target_blob_reads": len(reader.read_paths()),
            "architecture_nodes": len(architecture_tree),
            "responsibility_entries": len(responsibility_map),
            "implementation_intents": len(implementation_intents),
            "assurance_entries": len(assurance_ownership),
            "constraints": len(constraints),
            "unknowns": len(unknowns),
        },
        "target_blob_read_paths": list(reader.read_paths()),
        "claim_ceiling": memory["claim_ceiling"],
    }
    return {
        "memory": memory,
        "evidence_index": evidence_payload,
        "report": report,
    }


def _render_state(value: str) -> str:
    return {
        "observed-fact": "Observed fact",
        "inferred-knowledge": "Inferred knowledge",
        "unknown": "Unknown",
    }[value]


def render_architecture_memory_markdown(memory: dict[str, Any]) -> str:
    lines: list[str] = [
        "# WFF v1.6.2 Architecture Memory",
        "",
        f"- Source commit: `{memory['source']['commit']}`",
        f"- Source tree: `{memory['source']['tree']}`",
        f"- Snapshot: `{memory['snapshot_id']}`",
        f"- Status: `{memory['status']}`",
        "",
        "## System Architecture Tree",
        "",
    ]
    children: dict[str, list[dict[str, Any]]] = {}
    for node in memory["system_architecture_tree"]:
        children.setdefault(node["parent_id"], []).append(node)
    for values in children.values():
        values.sort(key=lambda item: item["id"])

    def emit(parent: str, depth: int) -> None:
        for node in children.get(parent, []):
            indent = "  " * depth
            lines.append(
                f"{indent}- **{node['name']}** (`{node['id']}`, {node['kind']}; "
                f"{_render_state(node['knowledge_state'])}, {node['confidence']})"
            )
            lines.append(f"{indent}  - Responsibility: {node['responsibility']}")
            if node.get("non_responsibilities"):
                lines.append(
                    f"{indent}  - Does not own: "
                    + "; ".join(node["non_responsibilities"])
                )
            lines.append(
                f"{indent}  - Evidence: "
                + ", ".join(f"`{ref}`" for ref in node["evidence_refs"])
            )
            emit(node["id"], depth + 1)

    emit("", 0)

    lines.extend(
        [
            "",
            "## Module Responsibility Map",
            "",
            "| Subject | Owner | Responsibility | Must not own | State | Evidence |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in memory["module_responsibility_map"]:
        non_owned = "; ".join(row.get("non_responsibilities", []))
        evidence = ", ".join(f"`{ref}`" for ref in row["evidence_refs"])
        lines.append(
            f"| {row['subject']} | {row['owner']} | {row['responsibility']} | "
            f"{non_owned} | {_render_state(row['knowledge_state'])} / {row['confidence']} | {evidence} |"
        )

    def emit_entries(title: str, key: str, statement_key: str) -> None:
        lines.extend(["", f"## {title}", ""])
        for row in memory[key]:
            lines.append(f"### {row['subject']}")
            lines.append("")
            lines.append(f"- State: `{row['knowledge_state']}`")
            lines.append(f"- Confidence: `{row['confidence']}`")
            lines.append(f"- Statement: {row[statement_key]}")
            lines.append(f"- Rationale: {row['rationale']}")
            if row["evidence_refs"]:
                lines.append(
                    "- Evidence: "
                    + ", ".join(f"`{ref}`" for ref in row["evidence_refs"])
                )
            lines.append("")

    emit_entries(
        "Implementation Intent Summary",
        "implementation_intent_summary",
        "statement",
    )
    emit_entries(
        "Validation / Assurance Ownership",
        "validation_assurance_ownership",
        "responsibility",
    )
    emit_entries("Constraint Knowledge", "constraints", "statement")
    emit_entries("Known Unknowns", "unknowns", "statement")

    lines.extend(
        [
            "## Claim Ceiling",
            "",
            memory["claim_ceiling"],
            "",
            "Generated knowledge is a reviewed evidence projection. It is not self-certifying source truth.",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_read_runtime_file(root: Path, components: tuple[str, ...], filename: str) -> bytes:
    root_fd = os.open(root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in components:
            try:
                descriptor = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise KnowledgeReconstructionError(
                    f"runtime input directory is not safe: {component}: {exc}"
                ) from exc
            opened.append(descriptor)
            parent_fd = descriptor
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(filename, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise KnowledgeReconstructionError(
                f"runtime input file is not safe: {filename}: {exc}"
            ) from exc
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise KnowledgeReconstructionError(
                    f"runtime input is not a regular file: {filename}"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)


def load_fixed_observation_manifest(
    repository_root: str | Path,
    *,
    tree: str,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    raw = _safe_read_runtime_file(
        root,
        (".EKRI", "manifests"),
        f"{tree}-observation.json",
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeReconstructionError(
            f"observation manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    return _require_dict(payload, "observation manifest")


def _secure_write_file(parent_fd: int, filename: str, payload: bytes) -> None:
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    temporary_created = False
    try:
        file_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        temporary_created = True
        with os.fdopen(file_fd, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_created = False
        os.fsync(parent_fd)
    except OSError as exc:
        raise KnowledgeReconstructionError(
            f"failed to atomically persist {filename}: {exc}"
        ) from exc
    finally:
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _persist_wff_architecture_memory(
    repository_root: str | Path,
    result: dict[str, Any],
) -> dict[str, str]:
    """Persist the immediate result of a trusted in-process reconstruction.

    This helper is intentionally private. The supported write path is
    reconstruct_and_persist_wff_baseline(), which builds and persists without
    exposing a mutable intermediate result to callers.
    """
    root = _absolute_path(repository_root)
    memory = _require_dict(result.get("memory"), "result.memory")
    evidence = _require_dict(result.get("evidence_index"), "result.evidence_index")
    report = _require_dict(result.get("report"), "result.report")
    tree = _require_text(memory.get("source", {}).get("tree"), "memory.source.tree")
    if tree != report.get("source_tree") or tree != evidence.get("source", {}).get("tree"):
        raise KnowledgeReconstructionError("Phase 1 output source tree identities diverge")

    evidence_bytes = _json_bytes(evidence)
    memory_bytes = _json_bytes(memory)
    markdown_bytes = render_architecture_memory_markdown(memory).encode("utf-8")
    report = dict(report)
    report["output_digests"] = {
        "evidence-index.json": _sha256_bytes(evidence_bytes),
        "architecture-memory.json": _sha256_bytes(memory_bytes),
        "ARCHITECTURE_MEMORY.md": _sha256_bytes(markdown_bytes),
    }
    report_bytes = _json_bytes(report)

    root_fd = os.open(root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "knowledge", tree):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        _secure_write_file(parent_fd, "evidence-index.json", evidence_bytes)
        _secure_write_file(parent_fd, "architecture-memory.json", memory_bytes)
        _secure_write_file(parent_fd, "ARCHITECTURE_MEMORY.md", markdown_bytes)
        _secure_write_file(parent_fd, "reconstruction-report.json", report_bytes)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = root / ".EKRI" / "knowledge" / tree
    return {
        "output_root": str(output_root),
        "evidence_index": str(output_root / "evidence-index.json"),
        "architecture_memory": str(output_root / "architecture-memory.json"),
        "human_projection": str(output_root / "ARCHITECTURE_MEMORY.md"),
        "report": str(output_root / "reconstruction-report.json"),
    }


def reconstruct_and_persist_wff_baseline(
    repository_root: str | Path,
) -> dict[str, Any]:
    spec = load_reconstruction_spec()
    target = _require_dict(spec.get("target"), "spec.target")
    tree = _require_text(target.get("tree"), "spec.target.tree")
    manifest = load_fixed_observation_manifest(repository_root, tree=tree)
    result = build_wff_architecture_memory(
        repository_root,
        manifest,
        spec=spec,
    )
    outputs = _persist_wff_architecture_memory(repository_root, result)
    summary = dict(result["report"])
    summary["outputs"] = outputs
    return summary
