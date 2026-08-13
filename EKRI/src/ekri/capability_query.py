"""EKRI v1.0 named Capability queries over the shared semantic substrate.

P3 introduced a rebuildable lookup index without a peer Capability store. P6
establishes one `ontology-authoritative` Capability semantic slice from the
proven-equivalent Architecture View plus the committed Capability specification.
The query index remains derived/non-authoritative and is fingerprint-bound to
that authority; v0.9 Capability Catalog/Before Generate outputs are compatibility
projections only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .architecture_roundtrip import (
    build_source_architecture_baseline_view,
    derive_architecture_view,
    validate_architecture_view,
)
from .capability_authority import (
    AUTHORITY_MODE as CAPABILITY_AUTHORITY_MODE,
    CapabilityAuthorityError,
    AUTHORITY_SCHEMA_VERSION as CAPABILITY_AUTHORITY_SCHEMA_VERSION,
    build_capability_semantic_authority,
    build_capability_semantic_authority_from_verified_catalog,
    persist_capability_semantic_authority,
    validate_capability_semantic_authority,
)
from .capability_contract import (
    CapabilityCheckRequest,
    CapabilitySpecIdentity,
    RECOMMENDATION_POSTURES,
    _recommendation,
    load_capability_spec,
    normalize_capability_alias,
)
from .phase1_snapshot import VerifiedPhase1Snapshot, verify_phase1_snapshot
from .project_assets import (
    ProjectAssetError,
    VerifiedProjectAsset,
    find_v1_project_asset_id_for_target_tree,
    verify_project_asset,
)
from .shadow_semantic_substrate import compile_phase1_architecture_shadow


INDEX_SCHEMA_VERSION = "ekri.capability-query-index.v1"
ANSWER_SCHEMA_VERSION = "ekri.capability-query-answer.v1"
INDEX_STATUS = "capability-query-index-built"
INDEX_AUTHORITY_MODE = "derived-non-authoritative"
INDEX_MATERIALIZATION_CLASS = "rebuildable-derived-index"
INDEX_FILENAME = "capability-query-index.json"
QUERY_LEVELS = {"L0", "L1", "L2", "L3"}
QUERY_KINDS = {
    "find-capability",
    "get-realizations",
    "explain-authority",
    "get-evidence",
    "before-generate",
}


class CapabilityQueryError(RuntimeError):
    """Raised when a P3 query/index violates the shared-substrate contract."""


def _snapshot_from_verified_project_asset(
    repository_root: Path,
    asset: VerifiedProjectAsset,
) -> VerifiedPhase1Snapshot:
    """Adapt independently verified portable knowledge into the P1 read contract.

    `verify_project_asset` already reopens the named target Git tree, checks every
    artifact digest and evidence blob, and closes evidence references. The adapter
    does not read the portable Capability Catalog as query truth; it carries only
    Architecture/Evidence/Reconstruction inputs into the shared substrate.
    """
    target = asset.manifest.get("target")
    if not isinstance(target, Mapping):
        raise CapabilityQueryError("verified project asset target must be an object")
    source_commit = _text(target.get("commit"), "verified project asset commit")
    source_tree = _text(target.get("tree"), "verified project asset tree")
    memory = _copy_object(asset.architecture_memory, "verified project Architecture Memory")
    evidence = _copy_object(asset.evidence_index, "verified project Evidence Index")
    report = _copy_object(asset.reconstruction_report, "verified project reconstruction report")
    evidence_refs = frozenset(
        _text(anchor.get("evidence_ref"), "verified project evidence ref")
        for raw_source in _array(evidence.get("sources"), "verified project evidence sources")
        if isinstance(raw_source, Mapping)
        for anchor in _array(raw_source.get("anchors"), "verified project evidence anchors")
        if isinstance(anchor, Mapping)
    )
    output_digests = report.get("output_digests")
    catalog_source = asset.capability_catalog.get("source")
    if not isinstance(catalog_source, Mapping):
        raise CapabilityQueryError("verified project Capability Catalog source must be an object")
    human_sha = _text(
        (
            output_digests.get("ARCHITECTURE_MEMORY.md")
            if isinstance(output_digests, Mapping)
            else catalog_source.get("phase1_human_projection_sha256")
        ),
        "verified project human Architecture projection digest",
    )
    if not isinstance(output_digests, Mapping):
        artifact_rows = asset.manifest.get("artifacts")
        if not isinstance(artifact_rows, list):
            raise CapabilityQueryError("verified project manifest lacks artifact receipts")
        receipts = {
            str(row.get("kind") or ""): str(row.get("sha256") or "")
            for row in artifact_rows
            if isinstance(row, Mapping)
        }
        architecture_sha = receipts.get("architecture-memory", "")
        evidence_sha = receipts.get("evidence-index", "")
        for label, value in (
            ("architecture-memory", architecture_sha),
            ("evidence-index", evidence_sha),
            ("human projection", human_sha),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise CapabilityQueryError(
                    f"verified project {label} projection receipt is invalid"
                )
        report["output_digests"] = {
            "architecture-memory.json": architecture_sha,
            "evidence-index.json": evidence_sha,
            "ARCHITECTURE_MEMORY.md": human_sha,
        }
    return VerifiedPhase1Snapshot(
        repository_root=str(repository_root),
        source_commit=source_commit,
        source_tree=source_tree,
        snapshot_id=_text(memory.get("snapshot_id"), "verified project snapshot_id"),
        architecture_memory=memory,
        evidence_index=evidence,
        reconstruction_report=report,
        human_projection_sha256=human_sha,
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True)
class CapabilityQueryService:
    """Verified, non-authoritative named-query facade over one Architecture View."""

    architecture_view: dict[str, Any]
    specification: dict[str, Any]
    specification_identity: CapabilitySpecIdentity
    authority: dict[str, Any]
    index: dict[str, Any]
    input_mode: str
    project_asset_id: str

    @classmethod
    def from_view(
        cls,
        architecture_view: Mapping[str, Any],
        specification: Mapping[str, Any],
        specification_identity: CapabilitySpecIdentity,
        *,
        input_mode: str = "provided-verified-view",
        project_asset_id: str = "",
        phase1_human_projection_sha256: str = "",
    ) -> "CapabilityQueryService":
        view = validate_architecture_view(architecture_view)
        spec = _copy_object(specification, "capability specification")
        try:
            authority = build_capability_semantic_authority(
                view,
                spec,
                specification_identity,
                input_mode=input_mode,
                project_asset_id=project_asset_id,
                phase1_human_projection_sha256=phase1_human_projection_sha256,
            )
        except CapabilityAuthorityError as exc:
            raise CapabilityQueryError(str(exc)) from exc
        index = build_capability_query_index(
            view,
            spec,
            specification_identity,
            input_mode=input_mode,
            project_asset_id=project_asset_id,
            capability_authority=authority,
        )
        return cls(
            view,
            spec,
            specification_identity,
            authority,
            index,
            input_mode,
            project_asset_id,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: VerifiedPhase1Snapshot,
        specification: Mapping[str, Any],
        specification_identity: CapabilitySpecIdentity,
        *,
        input_mode: str = "verified-local-phase1",
        project_asset_id: str = "",
    ) -> "CapabilityQueryService":
        if not isinstance(snapshot, VerifiedPhase1Snapshot):
            raise CapabilityQueryError("CapabilityQueryService.from_snapshot requires verified Phase1 authority")
        shadow = compile_phase1_architecture_shadow(snapshot)
        view = derive_architecture_view(shadow)
        return cls.from_view(
            view,
            specification,
            specification_identity,
            input_mode=input_mode,
            project_asset_id=project_asset_id,
            phase1_human_projection_sha256=snapshot.human_projection_sha256,
        )

    @classmethod
    def from_repository(
        cls,
        repository_root: str | Path,
        *,
        source_tree: str = "",
        project_asset_id: str | None = None,
    ) -> "CapabilityQueryService":
        root = Path(repository_root).expanduser().resolve(strict=False)
        input_mode = "verified-local-phase1"
        selected_asset_id = ""
        selected_asset: VerifiedProjectAsset | None = None
        snapshot: VerifiedPhase1Snapshot
        resolved_asset_id = project_asset_id
        if resolved_asset_id is None and source_tree:
            try:
                resolved_asset_id = find_v1_project_asset_id_for_target_tree(
                    root,
                    source_tree=source_tree,
                )
            except ProjectAssetError as project_exc:
                raise CapabilityQueryError(
                    f"tracked project knowledge target-tree resolution failed: {project_exc}"
                ) from project_exc

        if resolved_asset_id is None:
            if not source_tree:
                raise CapabilityQueryError(
                    "source_tree is required when no verified project asset is selected"
                )
            snapshot = verify_phase1_snapshot(root, source_tree=source_tree)
        else:
            try:
                asset = verify_project_asset(root, asset_id=resolved_asset_id)
            except ProjectAssetError as project_exc:
                if project_asset_id is not None:
                    raise CapabilityQueryError(
                        f"tracked project knowledge verification failed: {project_exc}"
                    ) from project_exc
                snapshot = verify_phase1_snapshot(root, source_tree=source_tree)
            else:
                target = asset.manifest.get("target", {})
                asset_tree = str(target.get("tree") or "")
                if source_tree and asset_tree != source_tree:
                    if project_asset_id is not None:
                        raise CapabilityQueryError(
                            "selected project asset target does not match requested source_tree"
                        )
                    snapshot = verify_phase1_snapshot(root, source_tree=source_tree)
                else:
                    source_tree = asset_tree
                    snapshot = _snapshot_from_verified_project_asset(root, asset)
                    input_mode = "verified-project-asset"
                    selected_asset_id = str(asset.manifest.get("asset_id") or "")
                    selected_asset = asset
        if selected_asset is not None and project_asset_id is not None:
            view = build_source_architecture_baseline_view(snapshot)
            authority = build_capability_semantic_authority_from_verified_catalog(
                view,
                selected_asset.capability_catalog,
                project_asset_id=selected_asset_id,
            )
            spec_identity = CapabilitySpecIdentity(**authority["specification"])
            index = build_capability_query_index(
                view,
                {},
                spec_identity,
                input_mode=input_mode,
                project_asset_id=selected_asset_id,
                capability_authority=authority,
            )
            return cls(
                view,
                {},
                spec_identity,
                authority,
                index,
                input_mode,
                selected_asset_id,
            )

        spec, identity = load_capability_spec()
        target = spec.get("target")
        spec_matches = (
            isinstance(target, Mapping)
            and str(target.get("commit") or "") == snapshot.source_commit
            and str(target.get("tree") or "") == snapshot.source_tree
        )
        if not spec_matches:
            raise CapabilityQueryError(
                "no Capability specification matches the verified source context"
            )
        shadow = compile_phase1_architecture_shadow(snapshot)
        view = derive_architecture_view(shadow)
        return cls.from_view(
            view,
            spec,
            identity,
            input_mode=input_mode,
            project_asset_id=selected_asset_id,
            phase1_human_projection_sha256=snapshot.human_projection_sha256,
        )

    def find_capability(self, query: str) -> dict[str, Any]:
        return find_capability(self, query)

    def get_realizations(self, capability_id: str) -> dict[str, Any]:
        return get_realizations(self, capability_id)

    def explain_authority(self, capability_id: str) -> dict[str, Any]:
        return explain_authority(self, capability_id)

    def get_evidence(self, capability_id: str) -> dict[str, Any]:
        return get_evidence(self, capability_id)

    def before_generate(self, request: CapabilityCheckRequest) -> dict[str, Any]:
        return evaluate_capability_before_generate(self, request)

    def persist_authority(self, repository_root: str | Path) -> Path:
        return persist_capability_semantic_authority(repository_root, self.authority)

    def persist_index(self, repository_root: str | Path) -> Path:
        return persist_capability_query_index(repository_root, self.index)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _copy_object(value: Mapping[str, Any] | object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityQueryError(f"{label} must be an object")
    return json.loads(json.dumps(dict(value), ensure_ascii=False))


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CapabilityQueryError(f"{label} must not be empty")
    return text


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapabilityQueryError(f"{label} must be a list")
    return value


def _source(view: Mapping[str, Any]) -> dict[str, str]:
    raw = view.get("source")
    if not isinstance(raw, Mapping):
        raise CapabilityQueryError("Architecture View source must be an object")
    return {
        "snapshot_id": _text(raw.get("snapshot_id"), "Architecture View snapshot_id"),
        "commit": _text(raw.get("source_commit"), "Architecture View source_commit"),
        "tree": _text(raw.get("source_tree"), "Architecture View source_tree"),
    }


def _spec_identity_payload(identity: CapabilitySpecIdentity) -> dict[str, str]:
    return {key: str(value) for key, value in asdict(identity).items()}


def build_capability_query_index(
    architecture_view: Mapping[str, Any],
    specification: Mapping[str, Any],
    specification_identity: CapabilitySpecIdentity,
    *,
    input_mode: str = "provided-verified-view",
    project_asset_id: str = "",
    capability_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    view = validate_architecture_view(architecture_view)
    try:
        if capability_authority is None:
            authority = build_capability_semantic_authority(
                view,
                specification,
                specification_identity,
                input_mode=input_mode,
                project_asset_id=project_asset_id,
            )
        else:
            authority = validate_capability_semantic_authority(capability_authority)
    except CapabilityAuthorityError as exc:
        raise CapabilityQueryError(str(exc)) from exc
    source = _source(view)
    if (
        authority["source"]["commit"] != source["commit"]
        or authority["source"]["tree"] != source["tree"]
        or authority["source"]["architecture_view_semantic_fingerprint"] != view["semantic_fingerprint"]
    ):
        raise CapabilityQueryError("Capability authority does not match Architecture View source")

    alias_index: dict[str, list[str]] = {}
    capabilities: list[dict[str, Any]] = []
    for capability in authority["capabilities"]:
        capability_id = str(capability["id"])
        aliases = list(capability["aliases"])
        capabilities.append({
            "capability_id": capability_id,
            "normalized_aliases": aliases,
        })
        for alias in aliases:
            alias_index.setdefault(alias, []).append(capability_id)

    normalized_alias_index = {
        alias: sorted(set(ids))
        for alias, ids in sorted(alias_index.items())
    }
    ambiguous_aliases = {
        alias: ids
        for alias, ids in normalized_alias_index.items()
        if len(ids) > 1
    }
    stable_content = {
        "source_tree": source["tree"],
        "capability_authority_semantic_fingerprint": authority["semantic_fingerprint"],
        "specification_sha256": str(authority["specification"]["sha256"]),
        "capabilities": sorted(capabilities, key=lambda item: item["capability_id"]),
        "alias_index": normalized_alias_index,
        "ambiguous_aliases": ambiguous_aliases,
    }
    semantic_fingerprint = _digest(stable_content)
    if input_mode not in {"provided-verified-view", "verified-local-phase1", "verified-project-asset"}:
        raise CapabilityQueryError(f"unsupported capability query input_mode: {input_mode}")
    if input_mode != "verified-project-asset" and project_asset_id:
        raise CapabilityQueryError("project_asset_id is only valid for verified-project-asset input")
    if input_mode == "verified-project-asset" and not project_asset_id:
        raise CapabilityQueryError("verified-project-asset input requires project_asset_id")
    projection_fingerprint = _digest({
        "semantic_fingerprint": semantic_fingerprint,
        "capability_authority_projection_fingerprint": authority["projection_fingerprint"],
        "architecture_view_projection_fingerprint": view["projection_fingerprint"],
        "specification": dict(authority["specification"]),
        "input_mode": input_mode,
        "project_asset_id": project_asset_id,
    })
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "status": INDEX_STATUS,
        "authority_mode": INDEX_AUTHORITY_MODE,
        "materialization_class": INDEX_MATERIALIZATION_CLASS,
        "source": {
            **source,
            "input_mode": input_mode,
            "project_asset_id": project_asset_id,
            "architecture_view_schema_version": view["schema_version"],
            "architecture_view_semantic_fingerprint": view["semantic_fingerprint"],
            "architecture_view_projection_fingerprint": view["projection_fingerprint"],
            "capability_authority_schema_version": authority["schema_version"],
            "capability_authority_semantic_fingerprint": authority["semantic_fingerprint"],
            "capability_authority_projection_fingerprint": authority["projection_fingerprint"],
        },
        "specification": dict(authority["specification"]),
        "capability_count": len(capabilities),
        "capabilities": sorted(capabilities, key=lambda item: item["capability_id"]),
        "alias_index": normalized_alias_index,
        "ambiguous_aliases": ambiguous_aliases,
        "semantic_fingerprint": semantic_fingerprint,
        "projection_fingerprint": projection_fingerprint,
        "claim_ceiling": (
            "This is a rebuildable alias/capability lookup index derived from the ontology-authoritative Capability semantic slice. "
            "It contains no peer Capability semantic authority, does not prove exhaustive capability absence, and may be deleted/rebuilt without semantic knowledge loss."
        ),
    }
    return validate_capability_query_index(payload)


def validate_capability_query_index(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _copy_object(payload, "capability query index")
    if data.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise CapabilityQueryError("unsupported capability query index schema")
    if data.get("status") != INDEX_STATUS:
        raise CapabilityQueryError("unexpected capability query index status")
    if data.get("authority_mode") != INDEX_AUTHORITY_MODE:
        raise CapabilityQueryError("capability query index must remain derived-non-authoritative")
    if data.get("materialization_class") != INDEX_MATERIALIZATION_CLASS:
        raise CapabilityQueryError("capability query index must remain rebuildable-derived-index")
    source = data.get("source")
    if not isinstance(source, Mapping):
        raise CapabilityQueryError("capability query index source must be an object")
    expected_index_source_keys = {
        "snapshot_id",
        "commit",
        "tree",
        "input_mode",
        "project_asset_id",
        "architecture_view_schema_version",
        "architecture_view_semantic_fingerprint",
        "architecture_view_projection_fingerprint",
        "capability_authority_schema_version",
        "capability_authority_semantic_fingerprint",
        "capability_authority_projection_fingerprint",
    }
    if set(source) != expected_index_source_keys:
        raise CapabilityQueryError("capability query index source fields are not canonical")
    for key in expected_index_source_keys - {"project_asset_id"}:
        _text(source.get(key), f"capability query index source {key}")
    if source.get("input_mode") not in {"provided-verified-view", "verified-local-phase1", "verified-project-asset"}:
        raise CapabilityQueryError("capability query index input_mode is invalid")
    project_asset_id = str(source.get("project_asset_id") or "")
    if source.get("input_mode") == "verified-project-asset" and not project_asset_id:
        raise CapabilityQueryError("verified-project-asset index requires project_asset_id")
    if source.get("input_mode") != "verified-project-asset" and project_asset_id:
        raise CapabilityQueryError("project_asset_id is invalid for non-project-asset query input")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise CapabilityQueryError("capability query index capabilities must be a non-empty list")
    ids: list[str] = []
    rebuilt_aliases: dict[str, list[str]] = {}
    for raw in capabilities:
        if not isinstance(raw, Mapping):
            raise CapabilityQueryError("capability query index entry must be an object")
        if set(raw) != {"capability_id", "normalized_aliases"}:
            raise CapabilityQueryError("capability query index entry may contain only capability_id and normalized_aliases")
        capability_id = _text(raw.get("capability_id"), "capability query index capability_id")
        if capability_id in ids:
            raise CapabilityQueryError(f"duplicate capability query index id: {capability_id}")
        ids.append(capability_id)
        aliases = raw.get("normalized_aliases")
        if not isinstance(aliases, list) or not aliases:
            raise CapabilityQueryError(f"capability query aliases must be a non-empty list: {capability_id}")
        if aliases != sorted(set(str(value) for value in aliases)):
            raise CapabilityQueryError(f"capability query aliases must be sorted/unique: {capability_id}")
        for alias in aliases:
            rebuilt_aliases.setdefault(str(alias), []).append(capability_id)
    if data.get("capability_count") != len(ids):
        raise CapabilityQueryError("capability query index capability_count mismatch")
    rebuilt_aliases = {key: sorted(set(value)) for key, value in sorted(rebuilt_aliases.items())}
    if data.get("alias_index") != rebuilt_aliases:
        raise CapabilityQueryError("capability query index alias_index mismatch")
    expected_ambiguous = {key: value for key, value in rebuilt_aliases.items() if len(value) > 1}
    if data.get("ambiguous_aliases") != expected_ambiguous:
        raise CapabilityQueryError("capability query index ambiguous_aliases mismatch")
    spec = data.get("specification")
    if not isinstance(spec, Mapping):
        raise CapabilityQueryError("capability query index specification identity must be an object")
    for key in ("source", "path", "sha256", "scanner_commit", "scanner_tree", "blob_oid"):
        if key not in spec:
            raise CapabilityQueryError(f"capability query index specification missing {key}")
    for key in ("semantic_fingerprint", "projection_fingerprint"):
        value = _text(data.get(key), f"capability query index {key}")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise CapabilityQueryError(f"capability query index {key} must be sha256")
    stable_content = {
        "source_tree": str(source["tree"]),
        "capability_authority_semantic_fingerprint": str(source["capability_authority_semantic_fingerprint"]),
        "specification_sha256": str(spec["sha256"]),
        "capabilities": capabilities,
        "alias_index": rebuilt_aliases,
        "ambiguous_aliases": expected_ambiguous,
    }
    expected_semantic = _digest(stable_content)
    if data["semantic_fingerprint"] != expected_semantic:
        raise CapabilityQueryError("capability query index semantic_fingerprint mismatch")
    expected_projection = _digest({
        "semantic_fingerprint": expected_semantic,
        "capability_authority_projection_fingerprint": str(source["capability_authority_projection_fingerprint"]),
        "architecture_view_projection_fingerprint": str(source["architecture_view_projection_fingerprint"]),
        "specification": dict(spec),
        "input_mode": str(source["input_mode"]),
        "project_asset_id": project_asset_id,
    })
    if data["projection_fingerprint"] != expected_projection:
        raise CapabilityQueryError("capability query index projection_fingerprint mismatch")
    return data


def _verify_service(service: CapabilityQueryService) -> None:
    if not isinstance(service, CapabilityQueryService):
        raise CapabilityQueryError("named capability query requires a verified CapabilityQueryService")
    view = validate_architecture_view(service.architecture_view)
    authority = validate_capability_semantic_authority(service.authority)
    index = validate_capability_query_index(service.index)
    source = _source(view)
    index_source = index["source"]
    if (
        index_source["snapshot_id"] != source["snapshot_id"]
        or index_source["commit"] != source["commit"]
        or index_source["tree"] != source["tree"]
        or index_source["architecture_view_semantic_fingerprint"] != view["semantic_fingerprint"]
        or index_source["architecture_view_projection_fingerprint"] != view["projection_fingerprint"]
        or index_source["capability_authority_schema_version"] != authority["schema_version"]
        or index_source["capability_authority_semantic_fingerprint"] != authority["semantic_fingerprint"]
        or index_source["capability_authority_projection_fingerprint"] != authority["projection_fingerprint"]
        or index_source["input_mode"] != service.input_mode
        or index_source["project_asset_id"] != service.project_asset_id
    ):
        raise CapabilityQueryError("CapabilityQueryService index/view identity mismatch")
    spec_identity = _spec_identity_payload(service.specification_identity)
    if index["specification"] != spec_identity:
        raise CapabilityQueryError("CapabilityQueryService specification identity mismatch")
    authority_source = authority["source"]
    if (
        authority_source["snapshot_id"] != source["snapshot_id"]
        or authority_source["commit"] != source["commit"]
        or authority_source["tree"] != source["tree"]
        or authority_source["architecture_view_semantic_fingerprint"] != view["semantic_fingerprint"]
        or authority_source["architecture_view_projection_fingerprint"] != view["projection_fingerprint"]
        or authority_source["input_mode"] != service.input_mode
        or authority_source["project_asset_id"] != service.project_asset_id
        or authority["specification"] != spec_identity
    ):
        raise CapabilityQueryError("CapabilityQueryService authority/view identity mismatch")
    source_mode = str(authority_source.get("semantic_source_mode") or "")
    if source_mode == "architecture-view-plus-capability-spec":
        expected_authority = build_capability_semantic_authority(
            view,
            service.specification,
            service.specification_identity,
            input_mode=service.input_mode,
            project_asset_id=service.project_asset_id,
            phase1_human_projection_sha256=str(
                authority_source.get("phase1_human_projection_sha256") or ""
            ),
        )
        if (
            expected_authority["semantic_fingerprint"] != authority["semantic_fingerprint"]
            or expected_authority["projection_fingerprint"] != authority["projection_fingerprint"]
        ):
            raise CapabilityQueryError("CapabilityQueryService authority does not match source semantics")
    elif source_mode == "verified-portable-capability-seed":
        if service.specification != {}:
            raise CapabilityQueryError("portable Capability seed service must not retain a replay specification")
        if service.input_mode != "verified-project-asset" or not service.project_asset_id:
            raise CapabilityQueryError("portable Capability seed requires verified project-asset identity")
    else:
        raise CapabilityQueryError("CapabilityQueryService semantic source mode is unsupported")


def _materialize_capability(service: CapabilityQueryService, capability_id: str) -> dict[str, Any]:
    _verify_service(service)
    identifier = _text(capability_id, "capability id")
    for raw in service.authority["capabilities"]:
        if str(raw.get("id") or "") == identifier:
            return _copy_object(raw, f"Capability authority {identifier}")
    raise CapabilityQueryError(f"unknown capability id: {identifier}")


def _resolution(service: CapabilityQueryService, query: str) -> tuple[str, list[str], dict[str, Any] | None]:
    _verify_service(service)
    normalized = normalize_capability_alias(_text(query, "capability query"))
    alias_index = service.index["alias_index"]
    candidates = list(alias_index.get(normalized, []))
    if len(candidates) == 1:
        return "matched", candidates, _materialize_capability(service, candidates[0])
    if len(candidates) > 1:
        return "ambiguous", candidates, None
    return "not-found", [], None


def _query_source(service: CapabilityQueryService) -> dict[str, Any]:
    return {
        "snapshot_id": service.index["source"]["snapshot_id"],
        "commit": service.index["source"]["commit"],
        "tree": service.index["source"]["tree"],
        "input_mode": service.index["source"]["input_mode"],
        "project_asset_id": service.index["source"]["project_asset_id"],
        "architecture_view_semantic_fingerprint": service.index["source"]["architecture_view_semantic_fingerprint"],
        "capability_authority_semantic_fingerprint": service.authority["semantic_fingerprint"],
        "query_index_semantic_fingerprint": service.index["semantic_fingerprint"],
        "specification_sha256": service.index["specification"]["sha256"],
    }


def _answer_envelope(
    service: CapabilityQueryService,
    *,
    query_kind: str,
    disclosure_level: str,
    resolution: Mapping[str, Any],
    answer: Mapping[str, Any],
    claim_ceiling: str,
) -> dict[str, Any]:
    if query_kind not in QUERY_KINDS:
        raise CapabilityQueryError(f"unsupported capability query kind: {query_kind}")
    if disclosure_level not in QUERY_LEVELS:
        raise CapabilityQueryError(f"unsupported disclosure level: {disclosure_level}")
    payload = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": "capability-query-answered",
        "authority_mode": INDEX_AUTHORITY_MODE,
        "query_kind": query_kind,
        "disclosure_level": disclosure_level,
        "source": _query_source(service),
        "resolution": dict(resolution),
        "answer": dict(answer),
        "claim_ceiling": claim_ceiling,
    }
    return validate_capability_query_answer(payload)


def validate_capability_query_answer(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _copy_object(payload, "capability query answer")
    if data.get("schema_version") != ANSWER_SCHEMA_VERSION:
        raise CapabilityQueryError("unsupported capability query answer schema")
    if data.get("status") != "capability-query-answered":
        raise CapabilityQueryError("unexpected capability query answer status")
    if data.get("authority_mode") != INDEX_AUTHORITY_MODE:
        raise CapabilityQueryError("capability query answer must remain derived-non-authoritative")
    query_kind = str(data.get("query_kind") or "")
    if query_kind not in QUERY_KINDS:
        raise CapabilityQueryError("unsupported capability query answer kind")
    disclosure_level = str(data.get("disclosure_level") or "")
    expected_levels = {
        "find-capability": "L0",
        "get-realizations": "L1",
        "explain-authority": "L2",
        "get-evidence": "L3",
        "before-generate": "L2",
    }
    if disclosure_level != expected_levels[query_kind]:
        raise CapabilityQueryError("capability query disclosure level does not match query kind")
    source = data.get("source")
    if not isinstance(source, Mapping):
        raise CapabilityQueryError("capability query answer source must be an object")
    expected_source_keys = {
        "snapshot_id",
        "commit",
        "tree",
        "input_mode",
        "project_asset_id",
        "architecture_view_semantic_fingerprint",
        "capability_authority_semantic_fingerprint",
        "query_index_semantic_fingerprint",
        "specification_sha256",
    }
    if set(source) != expected_source_keys:
        raise CapabilityQueryError("capability query answer source fields are not canonical")
    for key in sorted(expected_source_keys - {"project_asset_id"}):
        _text(source.get(key), f"capability query answer source {key}")
    if source.get("input_mode") not in {"provided-verified-view", "verified-local-phase1", "verified-project-asset"}:
        raise CapabilityQueryError("capability query answer input_mode is invalid")
    project_asset_id = str(source.get("project_asset_id") or "")
    if source.get("input_mode") == "verified-project-asset" and not project_asset_id:
        raise CapabilityQueryError("verified-project-asset answer requires project_asset_id")
    if source.get("input_mode") != "verified-project-asset" and project_asset_id:
        raise CapabilityQueryError("capability query answer project_asset_id is invalid")
    resolution = data.get("resolution")
    if not isinstance(resolution, Mapping):
        raise CapabilityQueryError("capability query answer resolution must be an object")
    expected_resolution_keys = {
        "status",
        "normalized_query",
        "candidate_capability_ids",
        "matched_capability_id",
        "matched_capability_name",
    }
    if set(resolution) != expected_resolution_keys:
        raise CapabilityQueryError("capability query answer resolution fields are not canonical")
    if resolution.get("status") not in {"matched", "ambiguous", "not-found"}:
        raise CapabilityQueryError("capability query answer resolution status is invalid")
    if not isinstance(resolution.get("candidate_capability_ids"), list):
        raise CapabilityQueryError("capability query answer candidates must be a list")
    answer = data.get("answer")
    if not isinstance(answer, Mapping):
        raise CapabilityQueryError("capability query answer answer must be an object")
    expected_answer_keys = {
        "find-capability": {
            "existence",
            "knowledge_state",
            "confidence",
            "owners",
            "locations",
            "mainline_impact",
            "absence_proven",
        },
        "get-realizations": {
            "architecture_nodes",
            "locations",
            "implementation_intents",
            "realization_posture",
        },
        "explain-authority": {
            "owners",
            "responsibilities",
            "reuse_limitations",
            "constraints",
            "assurance_ownership",
            "mainline_impact",
            "authority_posture",
        },
        "get-evidence": {
            "evidence_refs",
            "evidence_refs_by_semantic_family",
            "source_commit",
            "source_tree",
            "exact_source_expansion",
        },
        "before-generate": {
            "capability_exists",
            "where_it_exists",
            "why_reuse_may_be_limited",
            "trigger_basis",
            "wff_mainline_impact",
            "reuse_recommendation",
            "boundary",
        },
    }[query_kind]
    if set(answer) != expected_answer_keys:
        raise CapabilityQueryError("capability query answer fields do not match query contract")
    if query_kind == "find-capability":
        if answer.get("absence_proven") is not False:
            raise CapabilityQueryError("find-capability must never claim absence proof")
        if answer.get("knowledge_state") not in {
            "observed-fact",
            "inferred-knowledge",
            "unknown",
            "conflicting",
        }:
            raise CapabilityQueryError("find-capability knowledge_state is invalid")
        if answer.get("knowledge_state") in {"unknown", "conflicting"} and answer.get("existence") != "unknown":
            raise CapabilityQueryError("find-capability uncertain/conflicting knowledge cannot claim confirmed existence")
        if not isinstance(answer.get("owners"), list) or not isinstance(answer.get("locations"), list):
            raise CapabilityQueryError("find-capability owners/locations must be lists")
    elif query_kind == "get-realizations":
        if answer.get("realization_posture") != "semantic-authority-derived-realization":
            raise CapabilityQueryError("get-realizations posture is invalid")
        for key in ("architecture_nodes", "locations", "implementation_intents"):
            if not isinstance(answer.get(key), list):
                raise CapabilityQueryError(f"get-realizations {key} must be a list")
    elif query_kind == "explain-authority":
        if answer.get("authority_posture") != "ontology-authoritative-capability-slice":
            raise CapabilityQueryError("explain-authority posture is invalid")
        for key in ("owners", "responsibilities", "reuse_limitations", "constraints", "assurance_ownership"):
            if not isinstance(answer.get(key), list):
                raise CapabilityQueryError(f"explain-authority {key} must be a list")
        if not isinstance(answer.get("mainline_impact"), Mapping):
            raise CapabilityQueryError("explain-authority mainline_impact must be an object")
    elif query_kind == "get-evidence":
        if answer.get("exact_source_expansion") != "resolve-through-verified-evidence-index":
            raise CapabilityQueryError("get-evidence source-expansion posture is invalid")
        if not isinstance(answer.get("evidence_refs"), list) or not isinstance(answer.get("evidence_refs_by_semantic_family"), Mapping):
            raise CapabilityQueryError("get-evidence evidence fields are invalid")
    else:
        recommendation = answer.get("reuse_recommendation")
        boundary = answer.get("boundary")
        if not isinstance(recommendation, Mapping) or recommendation.get("posture") not in RECOMMENDATION_POSTURES:
            raise CapabilityQueryError("before-generate recommendation is invalid")
        if not isinstance(boundary, Mapping) or set(boundary) != {"decision_allowed", "decision_status"}:
            raise CapabilityQueryError("before-generate boundary is invalid")
    _text(data.get("claim_ceiling"), "capability query answer claim_ceiling")
    return data


def find_capability(service: CapabilityQueryService, query: str) -> dict[str, Any]:
    status, candidates, capability = _resolution(service, query)
    resolution = {
        "status": status,
        "normalized_query": normalize_capability_alias(query),
        "candidate_capability_ids": candidates,
        "matched_capability_id": candidates[0] if len(candidates) == 1 else "",
        "matched_capability_name": capability["name"] if capability else "",
    }
    if capability is None:
        answer = {
            "existence": "unknown",
            "knowledge_state": "unknown",
            "confidence": "not-applicable",
            "owners": [],
            "locations": [],
            "mainline_impact": "unknown",
            "absence_proven": False,
        }
    else:
        owners = sorted({str(row["owner"]) for row in capability["responsibilities"]})
        answer = {
            "existence": capability["existence"],
            "knowledge_state": capability["knowledge_state"],
            "confidence": capability["confidence"],
            "owners": owners,
            "locations": capability["locations"],
            "mainline_impact": capability["mainline_impact"]["classification"],
            "absence_proven": False,
        }
    return _answer_envelope(
        service,
        query_kind="find-capability",
        disclosure_level="L0",
        resolution=resolution,
        answer=answer,
        claim_ceiling=(
            "L0 answers exact-alias capability orientation only. A not-found result remains unknown and never proves capability absence; expand to L1-L3 for realization, authority, and evidence detail."
        ),
    )


def _matched_resolution(capability: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "matched",
        "normalized_query": normalize_capability_alias(str(capability["id"])),
        "candidate_capability_ids": [str(capability["id"])],
        "matched_capability_id": str(capability["id"]),
        "matched_capability_name": str(capability["name"]),
    }


def get_realizations(service: CapabilityQueryService, capability_id: str) -> dict[str, Any]:
    capability = _materialize_capability(service, capability_id)
    return _answer_envelope(
        service,
        query_kind="get-realizations",
        disclosure_level="L1",
        resolution=_matched_resolution(capability),
        answer={
            "architecture_nodes": [
                {"id": row["id"], "name": row["name"], "kind": row["kind"]}
                for row in capability["architecture_nodes"]
            ],
            "locations": capability["locations"],
            "implementation_intents": capability["implementation_intents"],
            "realization_posture": "semantic-authority-derived-realization",
        },
        claim_ceiling=(
            "L1 exposes the current v0.9 Architecture/location realization projection. It does not prove executable implementation realization, runtime behavior, or exhaustive physical locations."
        ),
    )


def explain_authority(service: CapabilityQueryService, capability_id: str) -> dict[str, Any]:
    capability = _materialize_capability(service, capability_id)
    owners = sorted({str(row["owner"]) for row in capability["responsibilities"]})
    return _answer_envelope(
        service,
        query_kind="explain-authority",
        disclosure_level="L2",
        resolution=_matched_resolution(capability),
        answer={
            "owners": owners,
            "responsibilities": capability["responsibilities"],
            "reuse_limitations": capability["reuse_limitations"],
            "constraints": capability["constraints"],
            "assurance_ownership": capability["assurance_ownership"],
            "mainline_impact": capability["mainline_impact"],
            "authority_posture": "ontology-authoritative-capability-slice",
        },
        claim_ceiling=(
            "L2 explains current evidence-linked responsibility/constraint/assurance posture. Structural or query-index topology never creates semantic ownership or governance authority."
        ),
    )


def get_evidence(service: CapabilityQueryService, capability_id: str) -> dict[str, Any]:
    capability = _materialize_capability(service, capability_id)
    grouped = {
        "architecture": sorted({ref for row in capability["architecture_nodes"] for ref in row["evidence_refs"]}),
        "responsibility": sorted({ref for row in capability["responsibilities"] for ref in row["evidence_refs"]}),
        "constraint": sorted({ref for row in capability["constraints"] for ref in row["evidence_refs"]}),
        "implementation_intent": sorted({ref for row in capability["implementation_intents"] for ref in row["evidence_refs"]}),
        "assurance": sorted({ref for row in capability["assurance_ownership"] for ref in row["evidence_refs"]}),
        "mainline_impact": list(capability["mainline_impact"]["evidence_refs"]),
    }
    return _answer_envelope(
        service,
        query_kind="get-evidence",
        disclosure_level="L3",
        resolution=_matched_resolution(capability),
        answer={
            "evidence_refs": capability["evidence_refs"],
            "evidence_refs_by_semantic_family": grouped,
            "source_commit": service.index["source"]["commit"],
            "source_tree": service.index["source"]["tree"],
            "exact_source_expansion": "resolve-through-verified-evidence-index",
        },
        claim_ceiling=(
            "L3 returns exact evidence-reference identities and source context preserved by the shared Architecture View. Source blob/anchor expansion remains governed by the verified Phase-1 Evidence Index; the query index is not evidence authority."
        ),
    )


def evaluate_capability_before_generate(
    service: CapabilityQueryService,
    request: CapabilityCheckRequest,
) -> dict[str, Any]:
    status, candidates, capability = _resolution(service, request.capability_query)
    recommendation = _recommendation(
        match_status=status,
        capability=capability,
        request=request,
    )
    if recommendation["posture"] not in RECOMMENDATION_POSTURES:
        raise CapabilityQueryError("invalid Before Generate recommendation posture")

    if capability is None:
        existence_answer = {
            "status": "unknown",
            "knowledge_state": "unknown",
            "confidence": "not-applicable",
            "evidence_refs": [],
        }
        where_answer = {"locations": [], "owners": [], "architecture_nodes": [], "evidence_refs": []}
        limitation_answer = {
            "conclusion": "No evidence-backed non-reuse conclusion is available because no unique capability was resolved.",
            "items": [],
            "caller_supplied_non_reuse_reason": request.non_reuse_reason,
        }
        mainline_answer = {
            "classification": "unknown",
            "knowledge_state": "unknown",
            "confidence": "not-applicable",
            "rationale": "Mainline impact cannot be classified without a unique capability match.",
            "evidence_refs": [],
        }
    else:
        owners = sorted({str(row["owner"]) for row in capability["responsibilities"]})
        existence_answer = {
            "status": capability["existence"],
            "knowledge_state": capability["knowledge_state"],
            "confidence": capability["confidence"],
            "evidence_refs": capability["evidence_refs"],
        }
        where_answer = {
            "locations": capability["locations"],
            "owners": owners,
            "architecture_nodes": [
                {"id": row["id"], "name": row["name"], "kind": row["kind"]}
                for row in capability["architecture_nodes"]
            ],
            "evidence_refs": capability["evidence_refs"],
        }
        limitation_answer = {
            "conclusion": "Architecture Memory establishes explicit ownership limits and constraints, but it does not by itself prove that reuse is impossible.",
            "items": capability["reuse_limitations"],
            "caller_supplied_non_reuse_reason": request.non_reuse_reason,
        }
        mainline_answer = capability["mainline_impact"]

    trigger_answer = {
        "basis": request.trigger_basis,
        "reference": request.trigger_reference,
        "classification": (
            "observed-pressure"
            if request.trigger_basis == "observed-failure"
            else "declared-pressure"
            if request.trigger_basis == "declared-requirement"
            else "hypothetical-only"
        ),
        "replacement_policy": (
            "hypothetical risk alone cannot justify replacement"
            if request.trigger_basis == "hypothetical-risk"
            else "trigger pressure does not replace an explicit architecture decision"
        ),
    }
    decision_allowed = recommendation["posture"] != "insufficient-evidence"
    resolution = {
        "status": status,
        "normalized_query": normalize_capability_alias(request.capability_query),
        "candidate_capability_ids": candidates,
        "matched_capability_id": candidates[0] if len(candidates) == 1 else "",
        "matched_capability_name": capability["name"] if capability else "",
    }
    answer = {
        "capability_exists": existence_answer,
        "where_it_exists": where_answer,
        "why_reuse_may_be_limited": limitation_answer,
        "trigger_basis": trigger_answer,
        "wff_mainline_impact": mainline_answer,
        "reuse_recommendation": recommendation,
        "boundary": {
            "decision_allowed": decision_allowed,
            "decision_status": "actionable" if decision_allowed else "blocked-insufficient-evidence",
        },
    }
    return _answer_envelope(
        service,
        query_kind="before-generate",
        disclosure_level="L2",
        resolution=resolution,
        answer=answer,
        claim_ceiling=(
            "This Before Generate answer preserves the current v0.9 exact-alias, ambiguity, false-absence, trigger, and replacement policy over a shared-substrate query path. It does not prove exhaustive capability absence, implementation fitness, accepted architecture approval, production readiness, or change-impact completeness."
        ),
    )


def capability_query_index_path(repository_root: str | Path, source_tree: str) -> Path:
    return Path(repository_root).expanduser().resolve(strict=False) / ".EKRI" / "shadow" / source_tree / INDEX_FILENAME


def persist_capability_query_index(
    repository_root: str | Path,
    index: Mapping[str, Any],
) -> Path:
    payload = validate_capability_query_index(index)
    root = Path(repository_root).expanduser().resolve(strict=False)
    source_tree = str(payload["source"]["tree"])
    output = capability_query_index_path(root, source_tree)
    current = root
    for component in (".EKRI", "shadow", source_tree):
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise CapabilityQueryError(
                    f"capability query index output directory is unsafe: {current}"
                )
        else:
            current.mkdir()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise CapabilityQueryError(f"capability query index output file is unsafe: {output}")
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise CapabilityQueryError(
                f"capability query index temporary output is unsafe: {temporary}"
            )
        temporary.unlink()
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def run_capability_query(
    repository_root: str | Path,
    *,
    source_tree: str,
    query_kind: str,
    capability_query: str = "",
    capability_id: str = "",
    request: CapabilityCheckRequest | None = None,
    write_index: bool = False,
) -> dict[str, Any]:
    service = CapabilityQueryService.from_repository(repository_root, source_tree=source_tree)
    output = ""
    if write_index:
        output = str(service.persist_index(repository_root))
    if query_kind == "find-capability":
        result = service.find_capability(capability_query)
    elif query_kind == "get-realizations":
        result = service.get_realizations(capability_id)
    elif query_kind == "explain-authority":
        result = service.explain_authority(capability_id)
    elif query_kind == "get-evidence":
        result = service.get_evidence(capability_id)
    elif query_kind == "before-generate":
        if request is None:
            raise CapabilityQueryError("before-generate query requires CapabilityCheckRequest")
        result = service.before_generate(request)
    else:
        raise CapabilityQueryError(f"unsupported capability query kind: {query_kind}")
    return {
        "schema_version": "ekri.capability-query-run.v1",
        "status": "capability-query-complete",
        "query_kind": query_kind,
        "index_output": output,
        "index_semantic_fingerprint": service.index["semantic_fingerprint"],
        "answer": result,
    }
