"""Versioned, partial Project Knowledge Asset v2 verification.

Project Knowledge Asset v2 is intentionally manifest-first.  It packages
bounded portable projections and evidence receipts from already-verified EKRI
semantic families without creating a new peer semantic writer.  Families may
be native, bounded overlays, legacy-migration compatible, blocked by source
contract drift, or derived conformance evidence.

The v1 project-asset contract remains unchanged in :mod:`ekri.project_assets`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from .observation_boundary import ObservationBoundaryError, _run_git
from .project_assets import (
    PROJECT_ASSET_MANIFEST,
    PROJECT_ROOT_TOKEN,
    ProjectAssetError,
    _absolute_path,
    _array,
    _assert_no_symlink_path,
    _is_absolute_literal,
    _load_json,
    _object,
    _safe_relative_path,
    _sha256,
    _text,
    _walk_strings,
    resolve_project_asset_dir,
    verify_project_asset,
)


PROJECT_ASSET_V2_SCHEMA_VERSION = "ekri.project-knowledge-asset.v2"
PROJECT_ASSET_V2_STATUS = "portable-project-knowledge-partial-ready"
FAMILY_ARTIFACT_SCHEMA_VERSION = "ekri.project-knowledge-family-artifact.v2"
KNOWLEDGE_MODEL_CONTRACT_ID = "ekri.engineering-knowledge-model.v1"

AVAILABILITY_TO_ROLE = {
    "native-bounded": "bounded-portable-projection",
    "bounded-overlay": "bounded-portable-projection",
    "migration-supported-legacy": "migration-evidence",
    "blocked-source-contract-drift": "evidence-only",
    "derived-conformance": "conformance-evidence",
}


@dataclass(frozen=True)
class VerifiedProjectAssetV2:
    asset_dir: Path
    manifest: dict[str, Any]
    family_payloads: dict[str, dict[str, Any]]


def _git_blob(repository_root: Path, revision: str, path: str) -> bytes:
    canonical = _safe_relative_path(path, "source contract path")
    try:
        raw = _run_git(repository_root, "show", f"{revision}:{canonical}", binary=True)
    except ObservationBoundaryError as exc:
        raise ProjectAssetError(
            f"project v2 Git blob cannot be resolved: {revision}:{canonical}: {exc}"
        ) from exc
    assert isinstance(raw, bytes)
    return raw


def _git_text(repository_root: Path, *arguments: str) -> str:
    try:
        return str(_run_git(repository_root, *arguments)).strip()
    except ObservationBoundaryError as exc:
        raise ProjectAssetError(
            f"project v2 Git identity cannot be resolved ({' '.join(arguments)}): {exc}"
        ) from exc


def _resolve_identity(repository_root: Path, commit: str, tree: str, label: str) -> None:
    resolved_commit = _git_text(repository_root, "rev-parse", f"{commit}^{{commit}}")
    resolved_tree = _git_text(repository_root, "rev-parse", f"{commit}^{{tree}}")
    if resolved_commit != commit or resolved_tree != tree:
        raise ProjectAssetError(f"{label} commit/tree identity mismatch")


def _verify_source_contract(
    repository_root: Path,
    contract: dict[str, Any],
    *,
    expected_revision: str,
) -> None:
    revision = _text(contract.get("source_revision"), "source contract revision", minimum=40, maximum=64)
    if revision != expected_revision:
        raise ProjectAssetError("project v2 source contract revision does not match producer")
    path = _safe_relative_path(str(contract.get("path") or ""), "source contract path")
    expected_sha = _text(contract.get("sha256"), "source contract sha256", minimum=64, maximum=64)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ProjectAssetError("project v2 source contract sha256 is invalid")
    if _sha256(_git_blob(repository_root, revision, path)) != expected_sha:
        raise ProjectAssetError(f"project v2 source contract digest mismatch: {path}")


def _verify_producer(repository_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    producer = _object(manifest.get("producer"), "project v2 producer")
    if producer.get("product") != "EKRI":
        raise ProjectAssetError("project v2 producer must be EKRI")
    version = _text(producer.get("product_version"), "project v2 producer version", maximum=40)
    release_tag = _text(producer.get("release_tag"), "project v2 producer release tag", maximum=80)
    commit = _text(producer.get("source_revision"), "project v2 producer revision", minimum=40, maximum=64)
    tree = _text(producer.get("source_tree"), "project v2 producer tree", minimum=40, maximum=64)
    _resolve_identity(repository_root, commit, tree, "project v2 producer")
    resolved_tag = _git_text(repository_root, "rev-parse", f"{release_tag}^{{commit}}")
    if resolved_tag != commit:
        raise ProjectAssetError("project v2 producer release tag does not resolve to source revision")
    pyproject = tomllib.loads(_git_blob(repository_root, commit, "EKRI/pyproject.toml").decode("utf-8"))
    if str(pyproject.get("project", {}).get("version") or "") != version:
        raise ProjectAssetError("project v2 producer version does not match producer source")

    knowledge_model = _object(manifest.get("knowledge_model"), "project v2 knowledge model")
    if knowledge_model.get("contract_id") != KNOWLEDGE_MODEL_CONTRACT_ID:
        raise ProjectAssetError("project v2 knowledge-model contract id is unsupported")
    contract_path = _safe_relative_path(
        str(knowledge_model.get("contract_path") or ""),
        "project v2 knowledge-model contract path",
    )
    contract_sha = _text(
        knowledge_model.get("contract_sha256"),
        "project v2 knowledge-model contract sha256",
        minimum=64,
        maximum=64,
    )
    if _sha256(_git_blob(repository_root, commit, contract_path)) != contract_sha:
        raise ProjectAssetError("project v2 knowledge-model contract digest mismatch")
    return producer


def _verify_architecture_drift(
    repository_root: Path,
    *,
    source_contract: dict[str, Any],
    target: dict[str, Any],
    content: dict[str, Any],
) -> None:
    raw_spec = _git_blob(
        repository_root,
        str(source_contract["source_revision"]),
        str(source_contract["path"]),
    )
    try:
        spec = json.loads(raw_spec.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectAssetError(f"project v2 Architecture source contract cannot be decoded: {exc}") from exc
    sources = _array(spec.get("evidence_sources"), "Architecture source-contract evidence sources", minimum=1)
    source_path_count = 0
    anchor_count = 0
    matched = 0
    missing_refs: list[str] = []
    target_commit = str(target["commit"])
    for raw_source in sources:
        source = _object(raw_source, "Architecture evidence source")
        source_id = _text(source.get("id"), "Architecture evidence source id", maximum=120)
        path = _safe_relative_path(str(source.get("path") or ""), "Architecture evidence source path")
        source_path_count += 1
        try:
            text = _git_blob(repository_root, target_commit, path).decode("utf-8")
        except (UnicodeDecodeError, ProjectAssetError) as exc:
            raise ProjectAssetError(f"Architecture replay source cannot be read: {path}: {exc}") from exc
        for raw_anchor in _array(source.get("anchors"), f"Architecture anchors: {source_id}", minimum=1):
            anchor = _object(raw_anchor, "Architecture evidence anchor")
            anchor_id = _text(anchor.get("id"), "Architecture anchor id", maximum=120)
            contains = _text(anchor.get("contains"), "Architecture anchor contains", maximum=800)
            anchor_count += 1
            if contains in text:
                matched += 1
            else:
                missing_refs.append(f"{source_id}.{anchor_id}")
    expected = {
        "source_path_count": source_path_count,
        "missing_source_path_count": 0,
        "evidence_anchor_count": anchor_count,
        "evidence_anchor_match_count": matched,
        "evidence_anchor_drift_count": anchor_count - matched,
        "missing_anchor_refs": sorted(missing_refs),
    }
    observed = {
        key: content.get(key)
        for key in expected
    }
    if observed != expected:
        raise ProjectAssetError("project v2 Architecture drift evidence does not replay against target")
    if expected["evidence_anchor_drift_count"] < 1:
        raise ProjectAssetError("blocked Architecture family requires actual source-contract drift")


def _verify_target_contract(repository_root: Path, target: dict[str, Any], content: dict[str, Any]) -> None:
    raw = content.get("target_contract")
    if not isinstance(raw, dict):
        return
    path = _safe_relative_path(str(raw.get("path") or ""), "target contract path")
    expected_sha = _text(raw.get("sha256"), "target contract sha256", minimum=64, maximum=64)
    actual = _sha256(_git_blob(repository_root, str(target["commit"]), path))
    if actual != expected_sha:
        raise ProjectAssetError(f"project v2 target contract digest mismatch: {path}")
    required_tokens = raw.get("required_tokens", [])
    if not isinstance(required_tokens, list):
        raise ProjectAssetError("project v2 target contract required_tokens must be a list")
    text = _git_blob(repository_root, str(target["commit"]), path).decode("utf-8")
    missing = [str(token) for token in required_tokens if str(token) not in text]
    if missing:
        raise ProjectAssetError("project v2 target contract required token missing: " + ", ".join(missing))


def verify_project_asset_v2(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> VerifiedProjectAssetV2:
    root = _absolute_path(repository_root)
    asset_dir = resolve_project_asset_dir(root, asset_id=asset_id)
    _assert_no_symlink_path(root, asset_dir)
    manifest = _load_json(asset_dir / PROJECT_ASSET_MANIFEST, "project v2 manifest")
    if manifest.get("schema_version") != PROJECT_ASSET_V2_SCHEMA_VERSION:
        raise ProjectAssetError("unsupported project v2 asset schema")
    if manifest.get("status") != PROJECT_ASSET_V2_STATUS:
        raise ProjectAssetError("project v2 asset is not marked partial-ready")
    selected_id = _text(manifest.get("asset_id"), "project v2 asset id", maximum=160)
    if selected_id != asset_dir.name:
        raise ProjectAssetError("project v2 asset id does not match asset directory")

    producer = _verify_producer(root, manifest)
    target = _object(manifest.get("target"), "project v2 target")
    target_commit = _text(target.get("commit"), "project v2 target commit", minimum=40, maximum=64)
    target_tree = _text(target.get("tree"), "project v2 target tree", minimum=40, maximum=64)
    _resolve_identity(root, target_commit, target_tree, "project v2 target")
    accepted_count = int(target.get("accepted_path_count", 0) or 0)
    admitted_digest = _text(
        target.get("admitted_path_set_sha256"),
        "project v2 target admitted path-set digest",
        minimum=64,
        maximum=64,
    )
    if accepted_count < 1 or not re.fullmatch(r"[0-9a-f]{64}", admitted_digest):
        raise ProjectAssetError("project v2 target corpus identity is invalid")

    identity = _object(manifest.get("identity"), "project v2 identity")
    _text(identity.get("repository_asset_namespace"), "project v2 repository asset namespace", maximum=120)
    if identity.get("namespace_policy") != "stable-across-target-patch-and-producer-version":
        raise ProjectAssetError("project v2 semantic identity namespace policy is unsupported")
    portability = _object(manifest.get("portability"), "project v2 portability")
    if portability.get("repository_root_token") != PROJECT_ROOT_TOKEN:
        raise ProjectAssetError("project v2 repository-root token is invalid")
    if portability.get("formal_corpus_exclusions") != ["EKRI/", ".EKRI/"]:
        raise ProjectAssetError("project v2 formal-corpus exclusions changed")
    if portability.get("explicit_asset_selection_required") is not True:
        raise ProjectAssetError("project v2 must require explicit asset selection when multiple assets exist")

    family_rows = _array(manifest.get("families"), "project v2 families", minimum=1)
    family_payloads: dict[str, dict[str, Any]] = {}
    family_ids: set[str] = set()
    for raw_family in family_rows:
        family = _object(raw_family, "project v2 family")
        family_id = _text(family.get("family_id"), "project v2 family id", maximum=120)
        if family_id in family_ids:
            raise ProjectAssetError(f"duplicate project v2 family: {family_id}")
        family_ids.add(family_id)
        availability = _text(family.get("availability"), f"project v2 {family_id} availability", maximum=80)
        expected_role = AVAILABILITY_TO_ROLE.get(availability)
        if expected_role is None:
            raise ProjectAssetError(f"unsupported project v2 family availability: {availability}")
        contract = _object(family.get("source_contract"), f"project v2 {family_id} source contract")
        _verify_source_contract(root, contract, expected_revision=str(producer["source_revision"]))
        artifact = _object(family.get("artifact"), f"project v2 {family_id} artifact")
        if artifact.get("role") != expected_role:
            raise ProjectAssetError(f"project v2 {family_id} artifact role does not match availability")
        path = _safe_relative_path(str(artifact.get("path") or ""), f"project v2 {family_id} artifact path")
        artifact_path = asset_dir / path
        _assert_no_symlink_path(root, artifact_path)
        raw = artifact_path.read_bytes()
        digest = _text(artifact.get("sha256"), f"project v2 {family_id} artifact sha256", minimum=64, maximum=64)
        if _sha256(raw) != digest:
            raise ProjectAssetError(f"project v2 artifact digest mismatch: {family_id}")
        payload = _load_json(artifact_path, f"project v2 family artifact: {family_id}")
        absolute_literals = sorted({value for value in _walk_strings(payload) if _is_absolute_literal(value)})
        if absolute_literals:
            raise ProjectAssetError(
                f"project v2 artifact contains absolute machine path ({family_id}): {absolute_literals[0]}"
            )
        if payload.get("schema_version") != FAMILY_ARTIFACT_SCHEMA_VERSION:
            raise ProjectAssetError(f"project v2 family artifact schema mismatch: {family_id}")
        if payload.get("asset_id") != selected_id or payload.get("family_id") != family_id:
            raise ProjectAssetError(f"project v2 family artifact identity mismatch: {family_id}")
        if payload.get("availability") != availability or payload.get("artifact_role") != expected_role:
            raise ProjectAssetError(f"project v2 family artifact posture mismatch: {family_id}")
        if payload.get("semantic_authority") is not False:
            raise ProjectAssetError(f"project v2 family artifact attempted peer semantic authority: {family_id}")
        payload_producer = _object(payload.get("producer"), f"project v2 {family_id} artifact producer")
        if (
            payload_producer.get("product") != "EKRI"
            or payload_producer.get("product_version") != producer["product_version"]
            or payload_producer.get("source_revision") != producer["source_revision"]
        ):
            raise ProjectAssetError(f"project v2 family producer mismatch: {family_id}")
        payload_target = _object(payload.get("target"), f"project v2 {family_id} artifact target")
        if (
            payload_target.get("product") != target.get("product")
            or payload_target.get("product_version") != target.get("product_version")
            or payload_target.get("commit") != target_commit
            or payload_target.get("tree") != target_tree
        ):
            raise ProjectAssetError(f"project v2 family target mismatch: {family_id}")
        if payload.get("source_contract") != contract:
            raise ProjectAssetError(f"project v2 family source-contract receipt mismatch: {family_id}")
        content = _object(payload.get("content"), f"project v2 {family_id} content")
        if family_id == "architecture" and availability == "blocked-source-contract-drift":
            _verify_architecture_drift(root, source_contract=contract, target=target, content=content)
        if availability == "migration-supported-legacy":
            legacy_id = _text(content.get("legacy_project_asset_id"), f"project v2 {family_id} legacy asset id", maximum=160)
            verify_project_asset(root, asset_id=legacy_id)
        _verify_target_contract(root, target, content)
        family_payloads[family_id] = payload

    derived = manifest.get("derived_surfaces")
    if not isinstance(derived, list):
        raise ProjectAssetError("project v2 derived_surfaces must be a list")
    for raw_surface in derived:
        surface = _object(raw_surface, "project v2 derived surface")
        _text(surface.get("surface_id"), "project v2 derived surface id", maximum=160)
        if surface.get("promoted_as_truth") is not False:
            raise ProjectAssetError("project v2 derived surface cannot be promoted as truth")
        if surface.get("posture") not in {"rebuildable-derived", "conformance-only"}:
            raise ProjectAssetError("project v2 derived surface posture is unsupported")

    _text(manifest.get("claim_ceiling"), "project v2 claim ceiling", minimum=80)
    return VerifiedProjectAssetV2(
        asset_dir=asset_dir,
        manifest=manifest,
        family_payloads=family_payloads,
    )


def verify_project_asset_any(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> VerifiedProjectAssetV2 | Any:
    """Verify a v1 or v2 asset without changing the existing v1 API contract."""
    root = _absolute_path(repository_root)
    asset_dir = resolve_project_asset_dir(root, asset_id=asset_id)
    manifest = _load_json(asset_dir / PROJECT_ASSET_MANIFEST, "project asset manifest")
    schema = str(manifest.get("schema_version") or "")
    if schema == PROJECT_ASSET_V2_SCHEMA_VERSION:
        return verify_project_asset_v2(root, asset_id=asset_dir.name)
    return verify_project_asset(root, asset_id=asset_dir.name)
