"""Evidence-only repository lifecycle observation snapshots.

This module observes already-known V1.9.1 repository assets and compatibility
surfaces.  It does not assign deprecation, retirement, removal eligibility, or
deletion authority.
"""

from __future__ import annotations

from collections import defaultdict
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .git_evidence import AdmittedGitReader
from .observation_boundary import _absolute_path, _tree_entries, evaluate_observation_boundary, utc_now_iso
from .repository_asset_identity import (
    evidence_paths_from_pack_root,
    exact_textual_references,
    stable_asset_id,
)
from .repository_ownership_boundary import python_module_aliases


SNAPSHOT_SCHEMA_VERSION = "ekri.repository-lifecycle-observation-snapshot.v1"
SNAPSHOT_STATUS = "repository-lifecycle-observation-recorded"
COMPARISON_SCHEMA_VERSION = "ekri.repository-lifecycle-observation-comparison.v1"
COMPARISON_STATUS = "repository-lifecycle-observation-compared"

FORBIDDEN_GOVERNANCE_KEYS = frozenset(
    {
        "deprecated",
        "deprecation_state",
        "retirement_candidate",
        "retirement_ready",
        "removal_eligible",
        "safe_delete",
        "deletion_authorized",
        "retirement_authorized",
    }
)

OBSERVATION_CLASSES = frozenset(
    {
        "active-distribution-observed",
        "non-test-import-observed",
        "compatibility-import-observed",
        "test-import-observed",
        "reference-only-observed",
        "present-no-positive-use-observed",
        "absent-current-tree",
    }
)


class RepositoryLifecycleObservationError(RuntimeError):
    """Raised when a lifecycle observation snapshot violates its evidence ceiling."""


def _json_digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_surface_id(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or PurePosixPath(normalized).is_absolute() or ".." in PurePosixPath(normalized).parts:
        raise RepositoryLifecycleObservationError(f"invalid compatibility surface path: {path!r}")
    digest = hashlib.sha256(f"compatibility-surface\0{normalized}".encode("utf-8")).hexdigest()[:24]
    return f"surface-{digest}"


def priority_asset_specs(
    p0_summary: Mapping[str, Any],
    p3_plan: Mapping[str, Any],
    *,
    asset_namespace: str = "wff-v1.9",
) -> list[dict[str, str]]:
    cohort = p0_summary.get("p1_priority_repository_only_python_cohort", [])
    if not isinstance(cohort, list) or not cohort:
        raise RepositoryLifecycleObservationError("P0 priority cohort is missing")
    migration_rows = p3_plan.get("first_migration_batch", [])
    if not isinstance(migration_rows, list):
        raise RepositoryLifecycleObservationError("P3 first_migration_batch must be a list")
    moved_by_old: dict[str, dict[str, Any]] = {
        str(row.get("old_path") or ""): row for row in migration_rows if isinstance(row, dict)
    }
    unresolved = set(str(path) for path in p3_plan.get("deferred_due_unresolved_identity", []) if str(path))
    unknown = set(str(path) for path in p3_plan.get("deferred_due_unknown_lifecycle", []) if str(path))
    compatibility = set(str(path) for path in p3_plan.get("deferred_compatibility_assets", []) if str(path))
    wave_a = set(str(path) for path in p3_plan.get("keep_in_place_compatibility_wave_a", []) if str(path))
    next_micro = p3_plan.get("next_micro_wave", {}) if isinstance(p3_plan.get("next_micro_wave"), dict) else {}
    next_micro_path = str(next_micro.get("path") or "")

    result: list[dict[str, str]] = []
    for raw_path in cohort:
        baseline_path = str(raw_path)
        moved = moved_by_old.get(baseline_path)
        asset_id = stable_asset_id(asset_namespace, baseline_path)
        current_path = baseline_path
        category = "priority-residual"
        if moved:
            expected_id = str(moved.get("asset_id") or "")
            if expected_id and expected_id != asset_id:
                raise RepositoryLifecycleObservationError(
                    f"P3 carried asset ID does not match P1 stable identity: {baseline_path}"
                )
            current_path = str(moved.get("canonical_path") or "")
            category = "physically-separated-maintenance-implementation"
        elif baseline_path in wave_a:
            category = "preexisting-compatibility-surface"
        elif baseline_path in unresolved:
            category = "unresolved-residual"
        elif baseline_path in unknown:
            category = "lifecycle-unknown-residual"
        elif baseline_path in compatibility:
            category = "deferred-compatibility-residual"
        elif baseline_path == next_micro_path:
            category = "historical-residual"
        result.append(
            {
                "asset_id": asset_id,
                "baseline_path": baseline_path,
                "current_path": current_path,
                "observation_group": category,
            }
        )
    return result


def compatibility_surface_specs(p3_plan: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    wave_a = p3_plan.get("keep_in_place_compatibility_wave_a", [])
    if not isinstance(wave_a, list):
        raise RepositoryLifecycleObservationError("P3 compatibility wave A must be a list")
    for path in wave_a:
        normalized = str(path)
        result.append(
            {
                "surface_id": stable_surface_id(normalized),
                "path": normalized,
                "origin": "preexisting-compatibility-surface",
            }
        )
    migrations = p3_plan.get("first_migration_batch", [])
    if not isinstance(migrations, list):
        raise RepositoryLifecycleObservationError("P3 first migration batch must be a list")
    for row in migrations:
        if not isinstance(row, dict):
            continue
        path = str(row.get("old_path") or "")
        if not path:
            continue
        result.append(
            {
                "surface_id": stable_surface_id(path),
                "path": path,
                "origin": "p3-generated-compatibility-shim",
            }
        )
    result = sorted(result, key=lambda row: row["path"])
    if len({row["surface_id"] for row in result}) != len(result):
        raise RepositoryLifecycleObservationError("duplicate compatibility surface identity")
    return result


def _python_module_index(paths: Iterable[str]) -> dict[str, str]:
    candidates: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if not str(path).endswith(".py"):
            continue
        for alias in python_module_aliases(str(path)):
            candidates[alias].append(str(path))
    return {alias: rows[0] for alias, rows in candidates.items() if len(rows) == 1}


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
    parts = source_module.split(".")
    if PurePosixPath(source_path).name != "__init__.py":
        parts = parts[:-1]
    climb = level - 1
    if climb > len(parts):
        return ""
    base = parts[: len(parts) - climb]
    if module:
        base.extend(str(module).split("."))
    return ".".join(base)


def focused_python_import_consumers(
    reader: AdmittedGitReader,
    target_paths: Sequence[str],
    *,
    focus_paths: set[str],
) -> dict[str, list[dict[str, str]]]:
    module_index = _python_module_index(target_paths)
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for source_path in target_paths:
        if not source_path.endswith(".py"):
            continue
        try:
            tree = ast.parse(reader.read_text(source_path), filename=source_path)
        except Exception:
            continue
        import_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_names.update(alias.name for alias in node.names if alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = _relative_import_module(source_path, node.module, int(node.level or 0))
                if base:
                    import_names.add(base)
                    for alias in node.names:
                        if alias.name and alias.name != "*":
                            candidate = f"{base}.{alias.name}"
                            if candidate in module_index:
                                import_names.add(candidate)
        for name in sorted(import_names):
            target = module_index.get(name)
            if not target or target not in focus_paths or target == source_path:
                continue
            result[target].append(
                {
                    "source_path": source_path,
                    "evidence": name,
                }
            )
    return {path: sorted(rows, key=lambda row: (row["source_path"], row["evidence"])) for path, rows in result.items()}


def _source_role(
    path: str,
    *,
    formal_union: set[str],
    maintainer_paths: set[str],
    compatibility_surface_paths: set[str],
) -> str:
    if path.startswith("tests/"):
        return "test"
    if path in compatibility_surface_paths:
        return "compatibility-surface"
    if path.startswith("release-cases/proof-snapshots/") or path.startswith("archive/"):
        return "proof-history"
    if path in formal_union:
        return "formal-distribution"
    if path in maintainer_paths:
        return "maintainer-distribution"
    return "other"


def _role_counts(
    sources: Iterable[str],
    *,
    formal_union: set[str],
    maintainer_paths: set[str],
    compatibility_surface_paths: set[str],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for path in sources:
        counts[
            _source_role(
                path,
                formal_union=formal_union,
                maintainer_paths=maintainer_paths,
                compatibility_surface_paths=compatibility_surface_paths,
            )
        ] += 1
    return dict(sorted(counts.items()))


def _text_loc(reader: AdmittedGitReader, path: str) -> int:
    try:
        return len(reader.read_text(path).splitlines())
    except Exception:
        return 0


def _observation_class(
    *,
    present: bool,
    formal_profiles: Sequence[str],
    import_role_counts: Mapping[str, int],
    reference_count: int,
) -> str:
    if not present:
        return "absent-current-tree"
    if formal_profiles:
        return "active-distribution-observed"
    non_test_imports = sum(
        int(import_role_counts.get(key, 0))
        for key in ("formal-distribution", "maintainer-distribution", "proof-history", "other")
    )
    if non_test_imports:
        return "non-test-import-observed"
    if int(import_role_counts.get("compatibility-surface", 0)):
        return "compatibility-import-observed"
    if int(import_role_counts.get("test", 0)):
        return "test-import-observed"
    if reference_count:
        return "reference-only-observed"
    return "present-no-positive-use-observed"


def _membership_from_pack_roots(
    target_paths: set[str],
    formal_pack_roots: Mapping[str, str | Path],
    maintainer_bundle_root: str | Path | None,
) -> tuple[dict[str, list[str]], set[str], set[str]]:
    membership: dict[str, list[str]] = defaultdict(list)
    formal_union: set[str] = set()
    for profile_id, root in formal_pack_roots.items():
        paths = evidence_paths_from_pack_root(root, target_paths)
        formal_union.update(paths)
        for path in paths:
            membership[path].append(profile_id)
    maintainer_paths: set[str] = set()
    if maintainer_bundle_root:
        maintainer_paths = evidence_paths_from_pack_root(maintainer_bundle_root, target_paths)
    return (
        {path: sorted(set(ids)) for path, ids in membership.items()},
        formal_union,
        maintainer_paths,
    )


def build_repository_lifecycle_observation_snapshot(
    repository_root: str | Path,
    *,
    target_ref: str,
    p0_summary: Mapping[str, Any],
    p3_plan: Mapping[str, Any],
    formal_pack_roots: Mapping[str, str | Path] | None = None,
    maintainer_bundle_root: str | Path | None = None,
    evidence_input_receipts: Mapping[str, Any] | None = None,
    write_outputs: bool = False,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    manifest = evaluate_observation_boundary(repository_root=root, target_ref=target_ref)
    if not manifest.get("boundary", {}).get("valid"):
        raise RepositoryLifecycleObservationError("formal observation boundary rejected")
    target_paths = tuple(str(path) for path in manifest["corpus"]["paths"])
    target_set = set(target_paths)
    reader = AdmittedGitReader(root, manifest)

    asset_specs = priority_asset_specs(p0_summary, p3_plan)
    surface_specs = compatibility_surface_specs(p3_plan)
    focus_paths = {row["current_path"] for row in asset_specs} | {row["path"] for row in surface_specs}
    membership, formal_union, maintainer_paths = _membership_from_pack_roots(
        target_set,
        formal_pack_roots or {},
        maintainer_bundle_root,
    )
    import_consumers = focused_python_import_consumers(reader, target_paths, focus_paths=focus_paths & target_set)
    text_refs = exact_textual_references(reader, target_paths, focus_paths=focus_paths & target_set)
    compatibility_surface_paths = {row["path"] for row in surface_specs}
    entries = {
        path: {"mode": mode, "object_type": kind, "blob_oid": oid}
        for mode, kind, oid, path in _tree_entries(root, str(manifest["source"]["tree"]))
        if path in focus_paths
    }

    tracked_assets: list[dict[str, Any]] = []
    for spec in asset_specs:
        path = spec["current_path"]
        present = path in target_set
        imports = import_consumers.get(path, [])
        refs = text_refs.get(path, [])
        import_counts = _role_counts(
            [row["source_path"] for row in imports],
            formal_union=formal_union,
            maintainer_paths=maintainer_paths,
            compatibility_surface_paths=compatibility_surface_paths,
        )
        reference_counts = _role_counts(
            refs,
            formal_union=formal_union,
            maintainer_paths=maintainer_paths,
            compatibility_surface_paths=compatibility_surface_paths,
        )
        profiles = membership.get(path, [])
        tracked_assets.append(
            {
                **spec,
                "presence": "present" if present else "absent",
                "git_identity": entries.get(path, {"mode": "", "object_type": "", "blob_oid": ""}),
                "current_loc": _text_loc(reader, path) if present else 0,
                "formal_profile_membership": profiles,
                "maintainer_bundle_member": path in maintainer_paths,
                "python_import_consumer_count": len(imports),
                "python_import_consumer_role_counts": import_counts,
                "python_import_consumer_samples": [row["source_path"] for row in imports[:20]],
                "exact_path_reference_count": len(refs),
                "exact_path_reference_role_counts": reference_counts,
                "exact_path_reference_samples": refs[:20],
                "observation_class": _observation_class(
                    present=present,
                    formal_profiles=profiles,
                    import_role_counts=import_counts,
                    reference_count=len(refs),
                ),
                "governance_decision": "not-evaluated-in-v1.9.1",
            }
        )

    compatibility_surfaces: list[dict[str, Any]] = []
    for spec in surface_specs:
        path = spec["path"]
        present = path in target_set
        imports = import_consumers.get(path, [])
        refs = text_refs.get(path, [])
        import_counts = _role_counts(
            [row["source_path"] for row in imports],
            formal_union=formal_union,
            maintainer_paths=maintainer_paths,
            compatibility_surface_paths=compatibility_surface_paths,
        )
        reference_counts = _role_counts(
            refs,
            formal_union=formal_union,
            maintainer_paths=maintainer_paths,
            compatibility_surface_paths=compatibility_surface_paths,
        )
        profiles = membership.get(path, [])
        compatibility_surfaces.append(
            {
                **spec,
                "presence": "present" if present else "absent",
                "current_loc": _text_loc(reader, path) if present else 0,
                "formal_profile_membership": profiles,
                "maintainer_bundle_member": path in maintainer_paths,
                "python_import_consumer_count": len(imports),
                "python_import_consumer_role_counts": import_counts,
                "python_import_consumer_samples": [row["source_path"] for row in imports[:20]],
                "exact_path_reference_count": len(refs),
                "exact_path_reference_role_counts": reference_counts,
                "exact_path_reference_samples": refs[:20],
                "observation_class": _observation_class(
                    present=present,
                    formal_profiles=profiles,
                    import_role_counts=import_counts,
                    reference_count=len(refs),
                ),
                "governance_decision": "not-evaluated-in-v1.9.1",
            }
        )

    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "status": SNAPSHOT_STATUS,
        "created_at": utc_now_iso(),
        "source": {
            "requested_ref": str(manifest["source"]["requested_ref"]),
            "commit": str(manifest["source"]["commit"]),
            "tree": str(manifest["source"]["tree"]),
            "self_scan_verdict": str(manifest["boundary"]["self_scan_verdict"]),
        },
        "authority_boundary": {
            "observation_only": True,
            "lifecycle_governance_authority": False,
            "retirement_decisions_allowed": False,
            "deletion_decisions_allowed": False,
            "rule": "Observation presence, usage, or absence cannot create lifecycle governance authority.",
        },
        "summary": {
            "tracked_asset_count": len(tracked_assets),
            "tracked_asset_present_count": sum(row["presence"] == "present" for row in tracked_assets),
            "tracked_implementation_loc": sum(int(row["current_loc"]) for row in tracked_assets),
            "compatibility_surface_count": len(compatibility_surfaces),
            "compatibility_surface_present_count": sum(row["presence"] == "present" for row in compatibility_surfaces),
            "compatibility_surface_loc": sum(int(row["current_loc"]) for row in compatibility_surfaces),
            "observation_class_counts": dict(
                sorted(
                    {
                        klass: sum(
                            row["observation_class"] == klass
                            for row in [*tracked_assets, *compatibility_surfaces]
                        )
                        for klass in OBSERVATION_CLASSES
                    }.items()
                )
            ),
            "formal_profile_membership_asset_count": sum(bool(row["formal_profile_membership"]) for row in tracked_assets),
            "maintainer_bundle_membership_asset_count": sum(bool(row["maintainer_bundle_member"]) for row in tracked_assets),
        },
        "tracked_assets": tracked_assets,
        "compatibility_surfaces": compatibility_surfaces,
        "evidence_input_receipts": dict(evidence_input_receipts or {}),
        "claim_ceiling": (
            "This snapshot records bounded current-tree observation evidence for known V1.9.1 repository assets and compatibility surfaces. "
            "It does not prove exhaustive usage absence, semantic ownership, deprecation, retirement eligibility, removal eligibility, deletion safety, or authorization to change lifecycle state."
        ),
    }
    validate_repository_lifecycle_observation_snapshot(payload)
    if write_outputs:
        output = root / ".EKRI" / "lifecycle-observations" / str(manifest["source"]["tree"]) / "repository-lifecycle-observation-snapshot.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["output"] = str(output)
    return payload


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def validate_repository_lifecycle_observation_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise RepositoryLifecycleObservationError("unsupported lifecycle observation snapshot schema")
    if payload.get("status") != SNAPSHOT_STATUS:
        raise RepositoryLifecycleObservationError("unexpected lifecycle observation snapshot status")
    forbidden = sorted(set(_walk_keys(payload)) & FORBIDDEN_GOVERNANCE_KEYS)
    if forbidden:
        raise RepositoryLifecycleObservationError("snapshot contains forbidden governance key(s): " + ", ".join(forbidden))
    authority = payload.get("authority_boundary")
    if not isinstance(authority, dict):
        raise RepositoryLifecycleObservationError("authority_boundary must be an object")
    if authority.get("lifecycle_governance_authority") is not False:
        raise RepositoryLifecycleObservationError("P5 cannot gain lifecycle governance authority")
    if authority.get("retirement_decisions_allowed") is not False or authority.get("deletion_decisions_allowed") is not False:
        raise RepositoryLifecycleObservationError("P5 cannot authorize retirement or deletion")
    assets = payload.get("tracked_assets")
    surfaces = payload.get("compatibility_surfaces")
    if not isinstance(assets, list) or not isinstance(surfaces, list):
        raise RepositoryLifecycleObservationError("tracked_assets and compatibility_surfaces must be lists")
    asset_ids = [str(row.get("asset_id") or "") for row in assets if isinstance(row, dict)]
    surface_ids = [str(row.get("surface_id") or "") for row in surfaces if isinstance(row, dict)]
    if len(asset_ids) != len(set(asset_ids)) or any(not item.startswith("asset-") for item in asset_ids):
        raise RepositoryLifecycleObservationError("tracked asset identities must be unique stable asset IDs")
    if len(surface_ids) != len(set(surface_ids)) or any(not item.startswith("surface-") for item in surface_ids):
        raise RepositoryLifecycleObservationError("compatibility surface identities must be unique")
    for row in [*assets, *surfaces]:
        if not isinstance(row, dict):
            raise RepositoryLifecycleObservationError("observation row must be an object")
        if row.get("observation_class") not in OBSERVATION_CLASSES:
            raise RepositoryLifecycleObservationError("invalid observation class")
        if row.get("governance_decision") != "not-evaluated-in-v1.9.1":
            raise RepositoryLifecycleObservationError("P5 observation row contains a governance decision")
    summary = payload.get("summary")
    if not isinstance(summary, dict) or int(summary.get("tracked_asset_count", -1)) != len(assets):
        raise RepositoryLifecycleObservationError("tracked asset denominator mismatch")
    if int(summary.get("compatibility_surface_count", -1)) != len(surfaces):
        raise RepositoryLifecycleObservationError("compatibility surface denominator mismatch")
    return dict(payload)


def _signal_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(row.get("current_path") or row.get("path") or ""),
        "presence": row.get("presence"),
        "current_loc": row.get("current_loc"),
        "formal_profile_membership": row.get("formal_profile_membership", []),
        "maintainer_bundle_member": row.get("maintainer_bundle_member"),
        "python_import_consumer_count": row.get("python_import_consumer_count"),
        "exact_path_reference_count": row.get("exact_path_reference_count"),
        "observation_class": row.get("observation_class"),
    }


def compare_observation_snapshots(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    validate_repository_lifecycle_observation_snapshot(previous)
    validate_repository_lifecycle_observation_snapshot(current)
    changes: list[dict[str, Any]] = []
    for collection, identity_key in (("tracked_assets", "asset_id"), ("compatibility_surfaces", "surface_id")):
        old_rows = {str(row[identity_key]): row for row in previous[collection]}
        new_rows = {str(row[identity_key]): row for row in current[collection]}
        for identity in sorted(set(old_rows) | set(new_rows)):
            old = old_rows.get(identity)
            new = new_rows.get(identity)
            if old is None:
                changes.append({"identity": identity, "collection": collection, "change": "observation-row-added"})
                continue
            if new is None:
                changes.append({"identity": identity, "collection": collection, "change": "observation-row-missing"})
                continue
            old_projection = _signal_projection(old)
            new_projection = _signal_projection(new)
            for field in sorted(old_projection):
                if old_projection[field] != new_projection[field]:
                    changes.append(
                        {
                            "identity": identity,
                            "collection": collection,
                            "change": "observation-signal-changed",
                            "field": field,
                            "previous": old_projection[field],
                            "current": new_projection[field],
                        }
                    )
    payload = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": COMPARISON_STATUS,
        "created_at": utc_now_iso(),
        "previous_source": dict(previous.get("source", {})),
        "current_source": dict(current.get("source", {})),
        "change_count": len(changes),
        "changes": changes,
        "authority_boundary": {
            "observation_only": True,
            "lifecycle_governance_authority": False,
            "rule": "Snapshot differences describe evidence changes only and cannot authorize lifecycle transitions.",
        },
        "claim_ceiling": (
            "This comparison reports changes in observed evidence signals only. It does not infer deprecation, retirement eligibility, removal eligibility, deletion safety, or lifecycle approval from added, removed, or absent signals."
        ),
    }
    forbidden = sorted(set(_walk_keys(payload)) & FORBIDDEN_GOVERNANCE_KEYS)
    if forbidden:
        raise RepositoryLifecycleObservationError("comparison contains forbidden governance key(s): " + ", ".join(forbidden))
    return payload


def file_receipt(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise RepositoryLifecycleObservationError(f"evidence file missing: {resolved}")
    return {"path": str(resolved), "sha256": _file_sha256(resolved), "size_bytes": resolved.stat().st_size}
