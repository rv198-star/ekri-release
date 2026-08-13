"""Evidence-separated repository ownership and dependency boundary reconstruction.

This module consumes the immutable Repository Asset Knowledge Map produced by
V1.9.1 P1 and adds relationship knowledge.  Semantic ownership evidence is
never inferred from imports, profile membership, textual references, graph
proximity, or absence of consumers.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .git_evidence import AdmittedGitReader
from .observation_boundary import _absolute_path, evaluate_observation_boundary, utc_now_iso
from .repository_asset_identity import (
    RepositoryAssetIdentityError,
    exact_textual_references,
    validate_repository_asset_knowledge_map,
)


BOUNDARY_SCHEMA_VERSION = "ekri.repository-ownership-boundary-map.v1"
BOUNDARY_STATUS = "repository-ownership-boundary-reconstructed"

STRUCTURAL_EDGE_TYPES = frozenset(
    {
        "python-ast-import",
        "exact-path-reference",
        "profile-exclusion-reference",
        "profile-declaration-reference",
    }
)
BOUNDARY_FLAGS = frozenset(
    {
        "owner-unresolved",
        "multi-owner",
        "mixed-lifecycle",
        "active-historical-coupling",
        "active-proof-coupling",
        "active-assurance-coupling",
        "compatibility-boundary",
        "analysis-internal-boundary",
        "outside-active-closure",
        "active-inbound-import-consumers",
        "active-inbound-path-references",
        "profile-exclusion-metadata-reference",
        "profile-declaration-metadata-reference",
        "proof-or-history-inbound-references",
    }
)
ACTIVE_ROLES = frozenset({"active-formal-distribution", "active-maintainer", "active-analysis-internal"})
HISTORY_ROLES = frozenset({"historical", "proof-retained"})


class RepositoryOwnershipBoundaryError(RuntimeError):
    """Raised when P2 ownership/dependency evidence violates the boundary contract."""


def _json_digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _asset_path(asset: Mapping[str, Any]) -> str:
    paths = asset.get("current_paths")
    if not isinstance(paths, list) or len(paths) != 1:
        raise RepositoryOwnershipBoundaryError("P1 asset must expose exactly one current path")
    return str(paths[0])


def _asset_index(asset_map: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        validate_repository_asset_knowledge_map(asset_map)
    except RepositoryAssetIdentityError as exc:
        raise RepositoryOwnershipBoundaryError(f"P1 asset map rejected: {exc}") from exc
    by_path: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for raw in asset_map.get("assets", []):
        if not isinstance(raw, dict):
            raise RepositoryOwnershipBoundaryError("P1 asset entry must be an object")
        path = _asset_path(raw)
        asset_id = str(raw.get("asset_id") or "")
        if path in by_path or asset_id in by_id:
            raise RepositoryOwnershipBoundaryError("P1 asset map contains duplicate identity")
        by_path[path] = raw
        by_id[asset_id] = raw
    return by_path, by_id


def p1_authority_digest(asset: Mapping[str, Any]) -> str:
    """Digest only the P1 fields that P2 is forbidden to rewrite."""
    frozen = {
        "asset_id": asset.get("asset_id"),
        "current_paths": asset.get("current_paths"),
        "ownership_refs": asset.get("ownership_refs"),
        "owner_evidence_labels": asset.get("owner_evidence_labels"),
        "ownership_observation_status": asset.get("ownership_observation_status"),
        "capability_refs": asset.get("capability_refs"),
        "observed_roles": asset.get("observed_roles"),
        "lifecycle_observation_status": asset.get("lifecycle_observation_status"),
        "retirement_authorized": asset.get("retirement_authorized"),
    }
    return _json_digest(frozen)


def python_module_aliases(path: str) -> tuple[str, ...]:
    """Return deterministic import aliases for a target Python path."""
    normalized = str(path).replace("\\", "/")
    if not normalized.endswith(".py"):
        return ()
    posix = PurePosixPath(normalized)
    parts = list(posix.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    if not parts:
        return ()
    aliases = {".".join(parts)}
    if parts[0] == "scripts" and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    if len(parts) > 2 and parts[0] == "wff-core" and parts[1] == "src":
        aliases.add(".".join(parts[2:]))
    return tuple(sorted(alias for alias in aliases if alias))


def build_python_module_index(assets: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    candidates: dict[str, list[str]] = defaultdict(list)
    for asset in assets:
        path = _asset_path(asset)
        for alias in python_module_aliases(path):
            candidates[alias].append(path)
    return {alias: paths[0] for alias, paths in candidates.items() if len(paths) == 1}


def _canonical_source_module(path: str) -> str:
    aliases = python_module_aliases(path)
    if not aliases:
        return ""
    full = [alias for alias in aliases if alias.startswith("scripts.") or alias.startswith("tests.")]
    return sorted(full, key=len, reverse=True)[0] if full else sorted(aliases, key=len, reverse=True)[0]


def _relative_import_module(source_path: str, module: str | None, level: int) -> str:
    source_module = _canonical_source_module(source_path)
    if not source_module or level <= 0:
        return str(module or "")
    source_parts = source_module.split(".")
    if PurePosixPath(source_path).name != "__init__.py":
        source_parts = source_parts[:-1]
    climb = level - 1
    if climb > len(source_parts):
        return ""
    base = source_parts[: len(source_parts) - climb]
    if module:
        base.extend(str(module).split("."))
    return ".".join(base)


def python_import_edges(
    reader: AdmittedGitReader,
    assets: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, int]]:
    by_path = {_asset_path(asset): asset for asset in assets}
    module_index = build_python_module_index(assets)
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    parse_failures: list[dict[str, str]] = []
    import_observation_count = 0
    non_target_import_observation_count = 0
    for source_path, source_asset in by_path.items():
        if not source_path.endswith(".py"):
            continue
        try:
            text = reader.read_text(source_path)
            tree = ast.parse(text, filename=source_path)
        except Exception as exc:
            parse_failures.append(
                {
                    "source_path": source_path,
                    "import": "",
                    "reason": f"python-ast-unavailable:{type(exc).__name__}",
                }
            )
            continue
        import_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_names.update(alias.name for alias in node.names if alias.name)
            elif isinstance(node, ast.ImportFrom):
                name = _relative_import_module(source_path, node.module, int(node.level or 0))
                if name:
                    import_names.add(name)
                    for alias in node.names:
                        if alias.name and alias.name != "*":
                            submodule_name = f"{name}.{alias.name}"
                            if submodule_name in module_index:
                                import_names.add(submodule_name)
        for import_name in sorted(import_names):
            import_observation_count += 1
            target_path = module_index.get(import_name)
            if not target_path:
                non_target_import_observation_count += 1
                continue
            if target_path == source_path:
                continue
            target_asset = by_path[target_path]
            key = (str(source_asset["asset_id"]), str(target_asset["asset_id"]), "python-ast-import")
            edges[key] = {
                "source_asset_id": str(source_asset["asset_id"]),
                "source_path": source_path,
                "target_asset_id": str(target_asset["asset_id"]),
                "target_path": target_path,
                "edge_type": "python-ast-import",
                "evidence": import_name,
                "knowledge_state": "observed-structural-fact",
                "semantic_authority": False,
            }
    return (
        sorted(edges.values(), key=lambda row: (row["source_path"], row["target_path"], row["edge_type"])),
        parse_failures,
        {
            "python_import_observation_count": import_observation_count,
            "python_non_target_import_observation_count": non_target_import_observation_count,
            "python_ast_parse_failure_count": len(parse_failures),
        },
    )


def profile_config_reference_kinds(profile_config: Mapping[str, Any]) -> dict[str, str]:
    """Classify exact paths in install-profile config without calling exclusions consumers."""
    profiles = profile_config.get("profiles", [])
    if not isinstance(profiles, list):
        return {}
    result: dict[str, str] = {}
    declaration_fields = (
        "explicit_scripts",
        "explicit_docs",
        "explicit_templates",
        "explicit_root_files",
    )
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        for value in raw.get("excluded_scripts", []) if isinstance(raw.get("excluded_scripts", []), list) else []:
            path = str(value or "").strip().replace("\\", "/")
            if path:
                result[path] = "profile-exclusion-reference"
        for field in declaration_fields:
            values = raw.get(field, [])
            if not isinstance(values, list):
                continue
            for value in values:
                path = str(value or "").strip().replace("\\", "/")
                if path and path not in result:
                    result[path] = "profile-declaration-reference"
    return result


def path_reference_edges(
    reader: AdmittedGitReader,
    assets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_path = {_asset_path(asset): asset for asset in assets}
    paths = tuple(sorted(by_path))
    refs = exact_textual_references(reader, paths, focus_paths=paths)
    profile_kinds: dict[str, str] = {}
    profile_config_path = "config/wff-install-profiles.json"
    if profile_config_path in by_path:
        try:
            profile_config = json.loads(reader.read_text(profile_config_path))
            if isinstance(profile_config, dict):
                profile_kinds = profile_config_reference_kinds(profile_config)
        except Exception:
            profile_kinds = {}
    edges: list[dict[str, Any]] = []
    for target_path, source_paths in refs.items():
        target_asset = by_path[target_path]
        for source_path in source_paths:
            source_asset = by_path.get(source_path)
            if not source_asset or source_path == target_path:
                continue
            edge_type = "exact-path-reference"
            if source_path == profile_config_path:
                edge_type = profile_kinds.get(target_path, edge_type)
            edges.append(
                {
                    "source_asset_id": str(source_asset["asset_id"]),
                    "source_path": source_path,
                    "target_asset_id": str(target_asset["asset_id"]),
                    "target_path": target_path,
                    "edge_type": edge_type,
                    "evidence": target_path,
                    "knowledge_state": "observed-structural-fact",
                    "semantic_authority": False,
                }
            )
    unique = {
        (row["source_asset_id"], row["target_asset_id"], row["edge_type"]): row
        for row in edges
    }
    return sorted(unique.values(), key=lambda row: (row["source_path"], row["target_path"], row["edge_type"]))


def _owner_neighborhood(
    asset: Mapping[str, Any],
    *,
    incoming: Sequence[Mapping[str, Any]],
    outgoing: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    neighborhoods: dict[str, dict[str, Any]] = {}
    for direction, rows, neighbor_key in (
        ("inbound", incoming, "source_asset_id"),
        ("outbound", outgoing, "target_asset_id"),
    ):
        for edge in rows:
            neighbor = by_id.get(str(edge.get(neighbor_key) or ""))
            if not neighbor or neighbor.get("ownership_observation_status") != "single-owner-evidence":
                continue
            labels = neighbor.get("owner_evidence_labels", [])
            if not isinstance(labels, list) or len(labels) != 1:
                continue
            owner = str(labels[0])
            row = neighborhoods.setdefault(
                owner,
                {
                    "owner_evidence_label": owner,
                    "inbound_edge_count": 0,
                    "outbound_edge_count": 0,
                    "edge_types": set(),
                    "sample_neighbor_paths": set(),
                    "knowledge_state": "inferred-structural-neighborhood",
                    "semantic_authority": False,
                },
            )
            row[f"{direction}_edge_count"] += 1
            row["edge_types"].add(str(edge.get("edge_type") or ""))
            row["sample_neighbor_paths"].add(_asset_path(neighbor))
    result: list[dict[str, Any]] = []
    for owner, row in sorted(neighborhoods.items()):
        result.append(
            {
                "owner_evidence_label": owner,
                "inbound_edge_count": int(row["inbound_edge_count"]),
                "outbound_edge_count": int(row["outbound_edge_count"]),
                "edge_types": sorted(row["edge_types"]),
                "sample_neighbor_paths": sorted(row["sample_neighbor_paths"])[:10],
                "knowledge_state": row["knowledge_state"],
                "semantic_authority": False,
            }
        )
    return result


def _boundary_flags(
    asset: Mapping[str, Any],
    *,
    incoming: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    roles = set(str(item) for item in asset.get("observed_roles", []) if str(item))
    active = bool(roles & ACTIVE_ROLES)
    flags: set[str] = set()
    ownership_status = str(asset.get("ownership_observation_status") or "")
    if ownership_status == "unresolved":
        flags.add("owner-unresolved")
    elif ownership_status == "multi-owner-evidence":
        flags.add("multi-owner")
    if str(asset.get("lifecycle_observation_status") or "") == "mixed-role-observed":
        flags.add("mixed-lifecycle")
    if active and "historical" in roles:
        flags.add("active-historical-coupling")
    if active and "proof-retained" in roles:
        flags.add("active-proof-coupling")
    if active and "assurance" in roles:
        flags.add("active-assurance-coupling")
    if "compatibility" in roles:
        flags.add("compatibility-boundary")
    if "active-analysis-internal" in roles:
        flags.add("analysis-internal-boundary")
    if not roles.intersection({"active-formal-distribution", "active-maintainer"}):
        flags.add("outside-active-closure")

    active_import_inbound = False
    active_path_reference_inbound = False
    history_reference_inbound = False
    profile_exclusion_reference = False
    profile_declaration_reference = False
    for edge in incoming:
        edge_type = str(edge.get("edge_type") or "")
        source = by_id.get(str(edge.get("source_asset_id") or ""))
        if not source:
            continue
        source_roles = set(str(item) for item in source.get("observed_roles", []) if str(item))
        if edge_type == "python-ast-import" and source_roles & ACTIVE_ROLES:
            active_import_inbound = True
        if edge_type == "exact-path-reference" and source_roles & ACTIVE_ROLES:
            active_path_reference_inbound = True
        if edge_type in {"python-ast-import", "exact-path-reference", "profile-declaration-reference"} and source_roles & HISTORY_ROLES:
            history_reference_inbound = True
        if edge_type == "profile-exclusion-reference":
            profile_exclusion_reference = True
        if edge_type == "profile-declaration-reference":
            profile_declaration_reference = True
    if active_import_inbound:
        flags.add("active-inbound-import-consumers")
    if active_path_reference_inbound:
        flags.add("active-inbound-path-references")
    if profile_exclusion_reference:
        flags.add("profile-exclusion-metadata-reference")
    if profile_declaration_reference:
        flags.add("profile-declaration-metadata-reference")
    if history_reference_inbound:
        flags.add("proof-or-history-inbound-references")
    unknown = sorted(flags - BOUNDARY_FLAGS)
    if unknown:
        raise RepositoryOwnershipBoundaryError("unknown boundary flags: " + ", ".join(unknown))
    return sorted(flags)


def _incoming_consumer_counts(
    incoming: Sequence[Mapping[str, Any]],
    *,
    by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    counts = {
        "formal_import": 0,
        "maintainer_import": 0,
        "analysis_import": 0,
        "proof_history_import": 0,
        "formal_path_reference": 0,
        "maintainer_path_reference": 0,
        "analysis_path_reference": 0,
        "proof_history_path_reference": 0,
        "profile_exclusion_reference": 0,
        "profile_declaration_reference": 0,
    }
    for edge in incoming:
        source = by_id.get(str(edge.get("source_asset_id") or ""))
        if not source:
            continue
        roles = set(str(item) for item in source.get("observed_roles", []) if str(item))
        edge_type = str(edge.get("edge_type") or "")
        if edge_type == "python-ast-import":
            if "active-formal-distribution" in roles:
                counts["formal_import"] += 1
            if "active-maintainer" in roles:
                counts["maintainer_import"] += 1
            if "active-analysis-internal" in roles:
                counts["analysis_import"] += 1
            if roles & HISTORY_ROLES:
                counts["proof_history_import"] += 1
        elif edge_type == "exact-path-reference":
            if "active-formal-distribution" in roles:
                counts["formal_path_reference"] += 1
            if "active-maintainer" in roles:
                counts["maintainer_path_reference"] += 1
            if "active-analysis-internal" in roles:
                counts["analysis_path_reference"] += 1
            if roles & HISTORY_ROLES:
                counts["proof_history_path_reference"] += 1
        elif edge_type == "profile-exclusion-reference":
            counts["profile_exclusion_reference"] += 1
        elif edge_type == "profile-declaration-reference":
            counts["profile_declaration_reference"] += 1
    return counts


def _decoupling_requirements(
    asset: Mapping[str, Any],
    flags: Sequence[str],
    *,
    incoming: Sequence[Mapping[str, Any]],
    consumer_counts: Mapping[str, int],
) -> list[str]:
    roles = set(str(item) for item in asset.get("observed_roles", []) if str(item))
    requirements: set[str] = set()
    flags_set = set(flags)
    if "owner-unresolved" in flags_set or "multi-owner" in flags_set:
        requirements.add("resolve-owner-boundary-before-physical-move")
    if int(consumer_counts.get("formal_import", 0)) > 0:
        requirements.add("migrate-formal-import-consumers-before-separation")
    if int(consumer_counts.get("maintainer_import", 0)) > 0:
        requirements.add("migrate-maintainer-import-consumers-before-separation")
    if int(consumer_counts.get("analysis_import", 0)) > 0:
        requirements.add("migrate-analysis-import-consumers-before-separation")
    if int(consumer_counts.get("formal_path_reference", 0)) > 0:
        requirements.add("update-formal-path-references-before-separation")
    if int(consumer_counts.get("maintainer_path_reference", 0)) > 0:
        requirements.add("update-maintainer-path-references-before-separation")
    if int(consumer_counts.get("analysis_path_reference", 0)) > 0:
        requirements.add("update-analysis-path-references-before-separation")
    if int(consumer_counts.get("profile_exclusion_reference", 0)) > 0:
        requirements.add("update-profile-exclusion-metadata-after-move")
    if int(consumer_counts.get("profile_declaration_reference", 0)) > 0:
        requirements.add("update-profile-declaration-metadata-after-move")
    if int(consumer_counts.get("proof_history_import", 0)) > 0 or int(consumer_counts.get("proof_history_path_reference", 0)) > 0:
        requirements.add("preserve-or-update-proof-history-references-before-separation")
    if "proof-retained" in roles or "active-proof-coupling" in flags_set:
        requirements.add("preserve-or-relocate-proof-reference")
    if "historical" in roles or "active-historical-coupling" in flags_set:
        requirements.add("preserve-historical-reproduction-context")
    if "compatibility" in roles:
        requirements.add("replace-or-freeze-compatibility-contract")
    positive_incoming = sum(
        int(consumer_counts.get(key, 0))
        for key in (
            "formal_import",
            "maintainer_import",
            "analysis_import",
            "proof_history_import",
            "formal_path_reference",
            "maintainer_path_reference",
            "analysis_path_reference",
            "proof_history_path_reference",
            "profile_declaration_reference",
        )
    )
    if positive_incoming == 0 and not asset.get("dependency_refs"):
        requirements.add("dependency-absence-not-proven")
    return sorted(requirements)


def bounded_inbound_frontier(
    start_asset_id: str,
    edges: Sequence[Mapping[str, Any]],
    *,
    max_depth: int = 3,
    edge_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    if max_depth < 1 or max_depth > 6:
        raise RepositoryOwnershipBoundaryError("max_depth must be between 1 and 6")
    allowed = edge_types or set(STRUCTURAL_EDGE_TYPES)
    incoming_by_target: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if str(edge.get("edge_type") or "") not in allowed:
            continue
        incoming_by_target[str(edge.get("target_asset_id") or "")].append(str(edge.get("source_asset_id") or ""))
    seen = {start_asset_id}
    queue: deque[tuple[str, int]] = deque([(start_asset_id, 0)])
    result: list[dict[str, Any]] = []
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for source_id in sorted(set(incoming_by_target.get(current, []))):
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            next_depth = depth + 1
            result.append({"asset_id": source_id, "depth": next_depth})
            queue.append((source_id, next_depth))
    return sorted(result, key=lambda row: (int(row["depth"]), str(row["asset_id"])))


def build_repository_ownership_boundary_map(
    repository_root: str | Path,
    *,
    asset_map: Mapping[str, Any],
    target_ref: str,
    focus_paths: Iterable[str] = (),
    write_outputs: bool = False,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    by_path, by_id = _asset_index(asset_map)
    source = asset_map.get("source", {})
    if not isinstance(source, dict):
        raise RepositoryOwnershipBoundaryError("P1 asset map source must be an object")
    manifest = evaluate_observation_boundary(repository_root=root, target_ref=target_ref)
    if not manifest.get("boundary", {}).get("valid"):
        raise RepositoryOwnershipBoundaryError("formal observation boundary rejected")
    if str(manifest["source"]["commit"]) != str(source.get("commit") or "") or str(manifest["source"]["tree"]) != str(source.get("tree") or ""):
        raise RepositoryOwnershipBoundaryError("P2 target does not match immutable P1 asset-map target")

    reader = AdmittedGitReader(root, manifest)
    assets = list(by_path.values())
    import_edges, python_ast_parse_failures, python_import_stats = python_import_edges(reader, assets)
    textual_edges = path_reference_edges(reader, assets)
    edge_map = {
        (row["source_asset_id"], row["target_asset_id"], row["edge_type"]): row
        for row in [*import_edges, *textual_edges]
    }
    edges = sorted(edge_map.values(), key=lambda row: (row["source_path"], row["target_path"], row["edge_type"]))

    incoming_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        incoming_by_id[str(edge["target_asset_id"])].append(edge)
        outgoing_by_id[str(edge["source_asset_id"])].append(edge)

    rows: list[dict[str, Any]] = []
    flag_counts: dict[str, int] = defaultdict(int)
    requirement_counts: dict[str, int] = defaultdict(int)
    neighborhood_count = 0
    for path in sorted(by_path):
        asset = by_path[path]
        asset_id = str(asset["asset_id"])
        incoming = incoming_by_id.get(asset_id, [])
        outgoing = outgoing_by_id.get(asset_id, [])
        flags = _boundary_flags(asset, incoming=incoming, by_id=by_id)
        consumer_counts = _incoming_consumer_counts(incoming, by_id=by_id)
        requirements = _decoupling_requirements(
            asset,
            flags,
            incoming=incoming,
            consumer_counts=consumer_counts,
        )
        neighborhood = _owner_neighborhood(asset, incoming=incoming, outgoing=outgoing, by_id=by_id)
        if neighborhood:
            neighborhood_count += 1
        for flag in flags:
            flag_counts[flag] += 1
        for requirement in requirements:
            requirement_counts[requirement] += 1
        rows.append(
            {
                "asset_id": asset_id,
                "path": path,
                "p1_authority_digest": p1_authority_digest(asset),
                "p1_ownership_observation_status": str(asset.get("ownership_observation_status") or ""),
                "p1_owner_evidence_labels": list(asset.get("owner_evidence_labels", [])),
                "p1_capability_ids": sorted(
                    str(item.get("capability_id"))
                    for item in asset.get("capability_refs", [])
                    if isinstance(item, dict) and str(item.get("capability_id") or "")
                ),
                "p1_responsibility_family_ids": sorted(
                    str(item.get("responsibility_family_id"))
                    for item in asset.get("ownership_refs", [])
                    if isinstance(item, dict) and str(item.get("responsibility_family_id") or "")
                ),
                "observed_roles": list(asset.get("observed_roles", [])),
                "boundary_flags": flags,
                "boundary_state": "bounded-observed" if not flags else (flags[0] if len(flags) == 1 else "compound-boundary"),
                "incoming_structural_edge_count": len(incoming),
                "outgoing_structural_edge_count": len(outgoing),
                "incoming_active_import_consumer_count": sum(
                    1
                    for edge in incoming
                    if edge["edge_type"] == "python-ast-import"
                    and set(by_id[str(edge["source_asset_id"])].get("observed_roles", [])) & ACTIVE_ROLES
                ),
                "incoming_formal_import_consumer_count": consumer_counts["formal_import"],
                "incoming_maintainer_import_consumer_count": consumer_counts["maintainer_import"],
                "incoming_analysis_import_consumer_count": consumer_counts["analysis_import"],
                "incoming_proof_history_import_consumer_count": consumer_counts["proof_history_import"],
                "incoming_formal_path_reference_count": consumer_counts["formal_path_reference"],
                "incoming_maintainer_path_reference_count": consumer_counts["maintainer_path_reference"],
                "incoming_analysis_path_reference_count": consumer_counts["analysis_path_reference"],
                "incoming_proof_history_path_reference_count": consumer_counts["proof_history_path_reference"],
                "incoming_profile_exclusion_reference_count": consumer_counts["profile_exclusion_reference"],
                "incoming_profile_declaration_reference_count": consumer_counts["profile_declaration_reference"],
                "structural_owner_neighborhood": neighborhood,
                "decoupling_requirements": requirements,
                "physical_separation_authorized": False,
                "retirement_authorized": False,
            }
        )

    focus_set = {str(path).replace("\\", "/") for path in focus_paths if str(path).strip()}
    focus_frontiers: list[dict[str, Any]] = []
    for path in sorted(focus_set & set(by_path)):
        asset = by_path[path]
        reference_frontier = bounded_inbound_frontier(
            str(asset["asset_id"]),
            edges,
            max_depth=3,
            edge_types={"python-ast-import", "exact-path-reference", "profile-declaration-reference"},
        )
        import_frontier = bounded_inbound_frontier(
            str(asset["asset_id"]),
            edges,
            max_depth=3,
            edge_types={"python-ast-import"},
        )
        frontier_details = [
            {
                "asset_id": str(item["asset_id"]),
                "depth": int(item["depth"]),
                "path": _asset_path(by_id[str(item["asset_id"])]),
                "observed_roles": list(by_id[str(item["asset_id"])].get("observed_roles", [])),
                "ownership_observation_status": str(
                    by_id[str(item["asset_id"])].get("ownership_observation_status") or ""
                ),
            }
            for item in reference_frontier
        ]
        focus_frontiers.append(
            {
                "asset_id": str(asset["asset_id"]),
                "path": path,
                "reference_frontier": frontier_details,
                "reference_frontier_asset_count": len(frontier_details),
                "import_frontier": [
                    {
                        "asset_id": str(item["asset_id"]),
                        "depth": int(item["depth"]),
                        "path": _asset_path(by_id[str(item["asset_id"])]),
                        "observed_roles": list(by_id[str(item["asset_id"])].get("observed_roles", [])),
                    }
                    for item in import_frontier
                ],
                "import_frontier_asset_count": len(import_frontier),
                "active_reference_frontier_asset_count": sum(
                    1 for item in frontier_details if set(item["observed_roles"]) & ACTIVE_ROLES
                ),
                "formal_reference_frontier_asset_count": sum(
                    1 for item in frontier_details if "active-formal-distribution" in set(item["observed_roles"])
                ),
                "maintainer_reference_frontier_asset_count": sum(
                    1 for item in frontier_details if "active-maintainer" in set(item["observed_roles"])
                ),
                "analysis_reference_frontier_asset_count": sum(
                    1 for item in frontier_details if "active-analysis-internal" in set(item["observed_roles"])
                ),
                "proof_history_reference_frontier_asset_count": sum(
                    1 for item in frontier_details if set(item["observed_roles"]) & HISTORY_ROLES
                ),
                "formal_import_frontier_asset_count": sum(
                    1
                    for item in import_frontier
                    if "active-formal-distribution" in set(by_id[str(item["asset_id"])].get("observed_roles", []))
                ),
                "maintainer_import_frontier_asset_count": sum(
                    1
                    for item in import_frontier
                    if "active-maintainer" in set(by_id[str(item["asset_id"])].get("observed_roles", []))
                ),
            }
        )

    p1_summary = asset_map.get("summary", {}) if isinstance(asset_map.get("summary"), dict) else {}
    payload: dict[str, Any] = {
        "schema_version": BOUNDARY_SCHEMA_VERSION,
        "status": BOUNDARY_STATUS,
        "created_at": utc_now_iso(),
        "source": {
            "requested_ref": str(manifest["source"]["requested_ref"]),
            "commit": str(manifest["source"]["commit"]),
            "tree": str(manifest["source"]["tree"]),
            "self_scan_verdict": str(manifest["boundary"]["self_scan_verdict"]),
            "p1_asset_map_canonical_sha256": _json_digest(asset_map),
            "p1_asset_count": len(by_path),
        },
        "authority_boundary": {
            "rule": "P2 copies P1 authority evidence verbatim and never derives semantic ownership from structural edges or neighborhoods.",
            "p1_ownership_observation_counts": p1_summary.get("ownership_observation_counts", {}),
            "structural_owner_neighborhood_semantic_authority": False,
            "physical_separation_authorized": False,
            "retirement_authorized": False,
        },
        "summary": {
            "asset_count": len(rows),
            "structural_edge_count": len(edges),
            "python_import_edge_count": sum(row["edge_type"] == "python-ast-import" for row in edges),
            "exact_path_reference_edge_count": sum(row["edge_type"] == "exact-path-reference" for row in edges),
            "profile_exclusion_reference_edge_count": sum(
                row["edge_type"] == "profile-exclusion-reference" for row in edges
            ),
            "profile_declaration_reference_edge_count": sum(
                row["edge_type"] == "profile-declaration-reference" for row in edges
            ),
            "python_import_observation_count": python_import_stats["python_import_observation_count"],
            "python_non_target_import_observation_count": python_import_stats["python_non_target_import_observation_count"],
            "python_ast_parse_failure_count": python_import_stats["python_ast_parse_failure_count"],
            "boundary_flag_counts": dict(sorted(flag_counts.items())),
            "decoupling_requirement_counts": dict(sorted(requirement_counts.items())),
            "assets_with_structural_owner_neighborhood": neighborhood_count,
            "focus_frontier_count": len(focus_frontiers),
            "physical_separation_authorized_count": 0,
            "retirement_authorized_count": 0,
        },
        "assets": rows,
        "structural_edges": edges,
        "python_ast_parse_failure_records": python_ast_parse_failures,
        "focus_impact_frontiers": focus_frontiers,
        "claim_ceiling": (
            "Repository Ownership Boundary reconstructs authority-separated asset relationships and bounded structural dependency neighborhoods over the immutable P1 asset denominator. "
            "It does not prove exhaustive dependency closure, infer semantic ownership from graph topology, authorize physical moves, establish retirement eligibility, or prove deletion safety."
        ),
    }
    validate_repository_ownership_boundary_map(payload, p1_asset_map=asset_map)
    if write_outputs:
        output = root / ".EKRI" / "ownership-boundaries" / str(manifest["source"]["tree"]) / "repository-ownership-boundary-map.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["output"] = str(output)
    return payload


def validate_repository_ownership_boundary_map(
    payload: Mapping[str, Any],
    *,
    p1_asset_map: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if payload.get("schema_version") != BOUNDARY_SCHEMA_VERSION:
        raise RepositoryOwnershipBoundaryError("unsupported ownership boundary schema")
    if payload.get("status") != BOUNDARY_STATUS:
        raise RepositoryOwnershipBoundaryError("unexpected ownership boundary status")
    rows = payload.get("assets")
    if not isinstance(rows, list):
        raise RepositoryOwnershipBoundaryError("ownership boundary assets must be a list")
    if payload.get("authority_boundary", {}).get("physical_separation_authorized") is not False:
        raise RepositoryOwnershipBoundaryError("P2 cannot authorize physical separation")
    if payload.get("authority_boundary", {}).get("retirement_authorized") is not False:
        raise RepositoryOwnershipBoundaryError("P2 cannot authorize retirement")
    p1_by_id: dict[str, Mapping[str, Any]] = {}
    if p1_asset_map is not None:
        _, p1_by_id_raw = _asset_index(p1_asset_map)
        p1_by_id = p1_by_id_raw
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RepositoryOwnershipBoundaryError("ownership boundary asset row must be an object")
        asset_id = str(row.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            raise RepositoryOwnershipBoundaryError("ownership boundary asset IDs must be unique")
        seen.add(asset_id)
        if row.get("physical_separation_authorized") is not False or row.get("retirement_authorized") is not False:
            raise RepositoryOwnershipBoundaryError(f"asset {asset_id} exceeds P2 authority")
        flags = row.get("boundary_flags")
        if not isinstance(flags, list) or any(str(flag) not in BOUNDARY_FLAGS for flag in flags):
            raise RepositoryOwnershipBoundaryError(f"invalid boundary flags for {asset_id}")
        neighborhood = row.get("structural_owner_neighborhood")
        if not isinstance(neighborhood, list) or any(item.get("semantic_authority") is not False for item in neighborhood if isinstance(item, dict)):
            raise RepositoryOwnershipBoundaryError(f"structural owner neighborhood gained authority for {asset_id}")
        if p1_by_id:
            source_asset = p1_by_id.get(asset_id)
            if source_asset is None:
                raise RepositoryOwnershipBoundaryError(f"P2 asset missing from P1 denominator: {asset_id}")
            if str(row.get("p1_authority_digest") or "") != p1_authority_digest(source_asset):
                raise RepositoryOwnershipBoundaryError(f"P1 authority evidence changed in P2: {asset_id}")
            if list(row.get("p1_owner_evidence_labels", [])) != list(source_asset.get("owner_evidence_labels", [])):
                raise RepositoryOwnershipBoundaryError(f"P1 owner labels changed in P2: {asset_id}")
    edges = payload.get("structural_edges")
    if not isinstance(edges, list):
        raise RepositoryOwnershipBoundaryError("structural_edges must be a list")
    for edge in edges:
        if not isinstance(edge, dict) or str(edge.get("edge_type") or "") not in STRUCTURAL_EDGE_TYPES:
            raise RepositoryOwnershipBoundaryError("invalid structural edge")
        if edge.get("semantic_authority") is not False:
            raise RepositoryOwnershipBoundaryError("structural edge cannot carry semantic authority")
        if str(edge.get("source_asset_id") or "") not in seen or str(edge.get("target_asset_id") or "") not in seen:
            raise RepositoryOwnershipBoundaryError("structural edge references unknown asset")
    return dict(payload)
