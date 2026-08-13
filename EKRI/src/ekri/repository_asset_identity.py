"""Evidence-bound repository asset identity reconstruction.

Repository Asset Identity is a traceability/intelligence layer over an immutable
Git target.  It does not decide retirement or deletion and it does not replace
Architecture Memory, capability ownership, package ownership, or Evidence/Gate
authority.

The formal target corpus always comes from the existing EKRI observation
boundary, so ``EKRI/**`` and ``.EKRI/**`` remain excluded under No Active
Self-Scan.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping, Sequence

from .git_evidence import AdmittedGitReader
from .observation_boundary import (
    ObservationBoundaryError,
    _absolute_path,
    _tree_entries,
    evaluate_observation_boundary,
    utc_now_iso,
)


MAP_SCHEMA_VERSION = "ekri.repository-asset-knowledge-map.v1"
MAP_STATUS = "repository-asset-identity-reconstructed"

ASSET_TYPES = frozenset(
    {
        "code",
        "test",
        "package-asset",
        "proof-asset",
        "historical-asset",
        "documentation-asset",
        "configuration-asset",
        "other",
    }
)

OBSERVED_ROLES = frozenset(
    {
        "active-formal-distribution",
        "active-maintainer",
        "active-analysis-internal",
        "assurance",
        "proof-retained",
        "historical",
        "compatibility",
        "external-or-reference",
    }
)

LIFECYCLE_OBSERVATION_STATUSES = frozenset(
    {"single-role-observed", "mixed-role-observed", "unknown"}
)

OWNERSHIP_OBSERVATION_STATUSES = frozenset(
    {"single-owner-evidence", "multi-owner-evidence", "unresolved"}
)

TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".cjs",
        ".json",
        ".md",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".csv",
        ".html",
        ".css",
        ".sql",
        ".sh",
        ".template",
    }
)

_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+\-]+)+")


class RepositoryAssetIdentityError(RuntimeError):
    """Raised when repository asset identity evidence is unsafe or malformed."""


def _json_digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_path(value: object, label: str = "repository path") -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RepositoryAssetIdentityError(f"{label} must be a canonical repository-relative path: {text!r}")
    normalized = path.as_posix()
    if normalized != text:
        raise RepositoryAssetIdentityError(f"{label} is not canonical: {text!r}")
    return normalized


def stable_asset_id(namespace: str, baseline_path: str) -> str:
    """Return a stable ID seeded once from the P1 baseline path.

    Later repository moves must carry this ID forward from the persisted map;
    callers must not regenerate a moved asset ID from its new path.
    """
    ns = str(namespace or "").strip()
    if not ns:
        raise RepositoryAssetIdentityError("asset namespace must not be empty")
    path = _normalize_path(baseline_path, "baseline_path")
    digest = hashlib.sha256(f"{ns}\0{path}".encode("utf-8")).hexdigest()[:24]
    return f"asset-{digest}"


def classify_asset_type(path: str) -> str:
    """Mechanically classify repository shape without inferring ownership."""
    normalized = _normalize_path(path)
    lower = normalized.casefold()
    suffix = PurePosixPath(normalized).suffix.casefold()

    if normalized.startswith("tests/"):
        return "test"
    if normalized.startswith("release-cases/proof-snapshots/"):
        return "proof-asset"
    if normalized.startswith("archive/"):
        return "historical-asset"
    if normalized.startswith("docs/") or lower.endswith(("readme.md", "agents.md")):
        return "documentation-asset"
    if normalized.startswith("config/") or PurePosixPath(normalized).name in {
        "pyproject.toml",
        "pytest.ini",
        "requirements.txt",
        "requirements.lock.txt",
    }:
        return "configuration-asset"
    if normalized.startswith(("skills/", "templates/", "reference-packages/", "runtime-deps/", "sources/", "external-projects/", "release-cases/")):
        return "package-asset"
    if suffix in {".py", ".pyi", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh"}:
        return "code"
    return "other"


def _path_matches_example(path: str, example: str) -> tuple[bool, str]:
    normalized = _normalize_path(path)
    raw = str(example or "").strip().replace("\\", "/")
    if raw.endswith("/**"):
        prefix = raw[:-3].rstrip("/")
        return (normalized == prefix or normalized.startswith(prefix + "/"), "prefix")
    try:
        expected = _normalize_path(raw, "responsibility example")
    except RepositoryAssetIdentityError:
        return False, ""
    return normalized == expected, "exact"


def responsibility_refs_for_path(
    path: str,
    responsibility_map: Mapping[str, Any] | None,
    *,
    source_ref: str,
) -> list[dict[str, str]]:
    if not responsibility_map:
        return []
    rows = responsibility_map.get("responsibility_families", [])
    if not isinstance(rows, list):
        raise RepositoryAssetIdentityError("responsibility map responsibility_families must be a list")
    result: list[dict[str, str]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        family_id = str(raw.get("id") or "").strip()
        owner = str(raw.get("owner") or "").strip()
        primary_class = str(raw.get("primary_class") or "").strip()
        examples = raw.get("examples", [])
        if not family_id or not isinstance(examples, list):
            continue
        match_kind = ""
        for example in examples:
            matched, kind = _path_matches_example(path, str(example))
            if matched:
                match_kind = kind
                break
        if not match_kind:
            continue
        result.append(
            {
                "responsibility_family_id": family_id,
                "owner": owner,
                "primary_class": primary_class,
                "match": match_kind,
                "source_ref": source_ref,
                "knowledge_state": "decision-support-evidence",
            }
        )
    return sorted(result, key=lambda row: (row["responsibility_family_id"], row["owner"]))


def capability_refs_for_path(
    path: str,
    capability_catalog: Mapping[str, Any] | None,
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    if not capability_catalog:
        return []
    capabilities = capability_catalog.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise RepositoryAssetIdentityError("capability catalog capabilities must be a list")
    normalized = _normalize_path(path)
    result: list[dict[str, Any]] = []
    for raw in capabilities:
        if not isinstance(raw, dict):
            continue
        capability_id = str(raw.get("id") or "").strip()
        locations = raw.get("locations", [])
        if not capability_id or not isinstance(locations, list):
            continue
        if normalized not in {str(item).strip().replace("\\", "/") for item in locations}:
            continue
        owners: list[str] = []
        for responsibility in raw.get("responsibilities", []):
            if isinstance(responsibility, dict):
                owner = str(responsibility.get("owner") or "").strip()
                if owner and owner not in owners:
                    owners.append(owner)
        result.append(
            {
                "capability_id": capability_id,
                "owners": sorted(owners),
                "confidence": str(raw.get("confidence") or "").strip(),
                "source_ref": source_ref,
                "knowledge_state": "verified-project-knowledge",
            }
        )
    return sorted(result, key=lambda row: row["capability_id"])


def roles_from_path_and_responsibility(
    path: str,
    responsibility_refs: Sequence[Mapping[str, str]],
) -> set[str]:
    normalized = _normalize_path(path)
    roles: set[str] = set()
    if normalized.startswith("tests/"):
        roles.add("assurance")
    if normalized.startswith("release-cases/proof-snapshots/"):
        roles.add("proof-retained")
    if normalized.startswith("archive/"):
        roles.add("historical")
    if normalized.startswith(("external-projects/", "reference-packages/", "runtime-deps/", "sources/")):
        roles.add("external-or-reference")
    classes = {str(row.get("primary_class") or "") for row in responsibility_refs}
    if "compatibility-only" in classes:
        roles.add("compatibility")
    if "historical-evaluation" in classes:
        roles.add("historical")
    if "assurance-only" in classes:
        roles.add("assurance")
    return roles


def lifecycle_observation_status(roles: Iterable[str]) -> str:
    unique = {str(role).strip() for role in roles if str(role).strip()}
    unknown = sorted(unique - OBSERVED_ROLES)
    if unknown:
        raise RepositoryAssetIdentityError("unknown observed role(s): " + ", ".join(unknown))
    if not unique:
        return "unknown"
    if len(unique) == 1:
        return "single-role-observed"
    return "mixed-role-observed"


def _iter_runtime_asset_values(value: object) -> Iterable[str]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                yield item.strip()
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_runtime_asset_values(item)


def evidence_paths_from_pack_root(pack_root: str | Path, target_paths: set[str]) -> set[str]:
    """Intersect an actual built pack/bundle file tree with target Git paths."""
    root = Path(pack_root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise RepositoryAssetIdentityError(f"pack/bundle root is not a directory: {root}")
    result: set[str] = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative in target_paths:
            result.add(relative)
    return result


def declared_analysis_membership(
    profile_config: Mapping[str, Any] | None,
    target_paths: set[str],
) -> dict[str, list[str]]:
    """Return exact/prefix declarations for analysis-only/internal profiles.

    This is configuration evidence only.  Resource-module closure is not
    reconstructed here and these declarations never become runtime proof.
    """
    if not profile_config:
        return {}
    profiles = profile_config.get("profiles", [])
    if not isinstance(profiles, list):
        raise RepositoryAssetIdentityError("profile config profiles must be a list")
    result: dict[str, list[str]] = defaultdict(list)
    exact_fields = (
        "explicit_scripts",
        "explicit_docs",
        "explicit_templates",
        "explicit_root_files",
    )
    prefix_fields = (
        "skills",
        "explicit_reference_package_dirs",
        "explicit_release_case_dirs",
        "explicit_runtime_dep_dirs",
    )
    for raw in profiles:
        if not isinstance(raw, dict) or str(raw.get("status") or "") != "analysis-only":
            continue
        profile_id = str(raw.get("id") or "").strip()
        if not profile_id:
            continue
        declared_exact: set[str] = set()
        declared_prefixes: set[str] = set()
        for field in exact_fields:
            for value in raw.get(field, []) if isinstance(raw.get(field, []), list) else []:
                try:
                    declared_exact.add(_normalize_path(value, f"{profile_id}.{field}"))
                except RepositoryAssetIdentityError:
                    continue
        for field in prefix_fields:
            for value in raw.get(field, []) if isinstance(raw.get(field, []), list) else []:
                text = str(value or "").strip().replace("\\", "/").rstrip("/")
                if not text:
                    continue
                if field == "skills" and not text.startswith("skills/"):
                    text = f"skills/{text}"
                try:
                    declared_prefixes.add(_normalize_path(text, f"{profile_id}.{field}"))
                except RepositoryAssetIdentityError:
                    continue
        for path in target_paths:
            if path in declared_exact or any(path == prefix or path.startswith(prefix + "/") for prefix in declared_prefixes):
                result[path].append(profile_id)
    return {path: sorted(set(ids)) for path, ids in result.items()}


def exact_textual_references(
    reader: AdmittedGitReader,
    target_paths: Sequence[str],
    *,
    focus_paths: Iterable[str],
) -> dict[str, list[str]]:
    """Collect exact repository-path textual references for a bounded focus set.

    This deliberately does not claim import/call/config dependency completeness.
    Structural discovery remains a separate evidence provider.
    """
    focus = {_normalize_path(path, "focus path") for path in focus_paths}
    focus &= set(target_paths)
    if not focus:
        return {}
    refs: dict[str, set[str]] = {path: set() for path in focus}
    for source_path in target_paths:
        suffix = PurePosixPath(source_path).suffix.casefold()
        if suffix not in TEXT_SUFFIXES and PurePosixPath(source_path).name not in {"README", "LICENSE", "Dockerfile"}:
            continue
        try:
            text = reader.read_text(source_path)
        except Exception:  # binary/encoding/read ceiling: no textual evidence from this blob
            continue
        observed_tokens = {match.group(0).rstrip(".,:;)") for match in _PATH_TOKEN_RE.finditer(text)}
        for token in observed_tokens & focus:
            if token != source_path:
                refs[token].add(source_path)
    return {path: sorted(values) for path, values in refs.items() if values}


def build_repository_asset_knowledge_map(
    repository_root: str | Path,
    *,
    target_ref: str,
    asset_namespace: str,
    formal_profile_paths: Mapping[str, set[str]] | None = None,
    maintainer_paths: set[str] | None = None,
    analysis_membership: Mapping[str, Sequence[str]] | None = None,
    responsibility_map: Mapping[str, Any] | None = None,
    responsibility_source_ref: str = "",
    capability_catalog: Mapping[str, Any] | None = None,
    capability_source_ref: str = "",
    focus_reference_paths: Iterable[str] = (),
    write_outputs: bool = False,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    manifest = evaluate_observation_boundary(repository_root=root, target_ref=target_ref)
    if not manifest.get("boundary", {}).get("valid"):
        raise RepositoryAssetIdentityError(
            "formal observation boundary rejected: "
            + str(manifest.get("boundary", {}).get("failure_reason") or "unknown failure")
        )
    target_paths = tuple(str(path) for path in manifest["corpus"]["paths"])
    target_set = set(target_paths)
    tree = str(manifest["source"]["tree"])
    entries = {path: {"mode": mode, "object_type": kind, "blob_oid": oid} for mode, kind, oid, path in _tree_entries(root, tree) if path in target_set}

    formal_profile_paths = formal_profile_paths or {}
    maintainer_paths = maintainer_paths or set()
    analysis_membership = analysis_membership or {}

    reader = AdmittedGitReader(root, manifest)
    text_refs = exact_textual_references(reader, target_paths, focus_paths=focus_reference_paths)

    assets: list[dict[str, Any]] = []
    role_counts: dict[str, int] = defaultdict(int)
    type_counts: dict[str, int] = defaultdict(int)
    lifecycle_counts: dict[str, int] = defaultdict(int)
    unknown_owner_count = 0
    mixed_role_count = 0
    ownership_status_counts: dict[str, int] = defaultdict(int)

    for path in target_paths:
        responsibility_refs = responsibility_refs_for_path(
            path,
            responsibility_map,
            source_ref=responsibility_source_ref,
        )
        capability_refs = capability_refs_for_path(
            path,
            capability_catalog,
            source_ref=capability_source_ref,
        )
        roles = roles_from_path_and_responsibility(path, responsibility_refs)
        formal_profiles = sorted(profile_id for profile_id, paths in formal_profile_paths.items() if path in paths)
        if formal_profiles:
            roles.add("active-formal-distribution")
        if path in maintainer_paths:
            roles.add("active-maintainer")
        analysis_profiles = sorted(set(analysis_membership.get(path, ())))
        if analysis_profiles:
            roles.add("active-analysis-internal")

        lifecycle_status = lifecycle_observation_status(roles)
        asset_type = classify_asset_type(path)
        ownership_refs = [dict(row) for row in responsibility_refs]
        owners = sorted({row["owner"] for row in responsibility_refs if row.get("owner")})
        if not owners and capability_refs:
            owners = sorted({owner for row in capability_refs for owner in row.get("owners", [])})
        if not owners:
            ownership_status = "unresolved"
            unknown_owner_count += 1
        elif len(owners) == 1:
            ownership_status = "single-owner-evidence"
        else:
            ownership_status = "multi-owner-evidence"
        ownership_status_counts[ownership_status] += 1
        if lifecycle_status == "mixed-role-observed":
            mixed_role_count += 1

        dependency_refs: list[dict[str, Any]] = []
        for profile_id in formal_profiles:
            dependency_refs.append({"kind": "formal-profile-membership", "source": profile_id})
        if path in maintainer_paths:
            dependency_refs.append({"kind": "maintainer-bundle-membership", "source": "fresh-maintainer-bundle"})
        for profile_id in analysis_profiles:
            dependency_refs.append({"kind": "analysis-profile-declaration", "source": profile_id})
        for source_path in text_refs.get(path, []):
            dependency_refs.append({"kind": "exact-textual-reference", "source": source_path})

        unknowns: list[str] = []
        if ownership_status == "unresolved":
            unknowns.append("current-owner-unresolved")
        elif ownership_status == "multi-owner-evidence":
            unknowns.append("ownership-boundary-mixed")
        if lifecycle_status == "unknown":
            unknowns.append("lifecycle-purpose-unresolved")
        if not dependency_refs:
            unknowns.append("dependency-purpose-unresolved")
        if path in text_refs and not formal_profiles and path not in maintainer_paths:
            unknowns.append("referenced-outside-active-closure")

        evidence_refs: list[dict[str, str]] = []
        if responsibility_refs:
            evidence_refs.append({"kind": "responsibility-map", "ref": responsibility_source_ref})
        if capability_refs:
            evidence_refs.append({"kind": "verified-capability-catalog", "ref": capability_source_ref})
        if formal_profiles:
            evidence_refs.append({"kind": "formal-pack-file-intersection", "ref": ",".join(formal_profiles)})
        if path in maintainer_paths:
            evidence_refs.append({"kind": "maintainer-bundle-file-intersection", "ref": "fresh-maintainer-bundle"})
        if analysis_profiles:
            evidence_refs.append({"kind": "analysis-profile-config-declaration", "ref": ",".join(analysis_profiles)})
        if path in text_refs:
            evidence_refs.append({"kind": "exact-path-text-scan", "ref": f"{len(text_refs[path])}-source(s)"})

        entry = entries.get(path, {})
        asset = {
            "asset_id": stable_asset_id(asset_namespace, path),
            "identity_basis": {"namespace": asset_namespace, "baseline_path": path},
            "current_paths": [path],
            "asset_type": asset_type,
            "git_identity": {
                "mode": str(entry.get("mode") or ""),
                "object_type": str(entry.get("object_type") or ""),
                "blob_oid": str(entry.get("blob_oid") or ""),
            },
            "observed_roles": sorted(roles),
            "lifecycle_observation_status": lifecycle_status,
            "formal_profile_membership": formal_profiles,
            "analysis_profile_declarations": analysis_profiles,
            "maintainer_bundle_member": path in maintainer_paths,
            "ownership_refs": ownership_refs,
            "owner_evidence_labels": owners,
            "ownership_observation_status": ownership_status,
            "capability_refs": capability_refs,
            "dependency_refs": dependency_refs,
            "evidence_refs": evidence_refs,
            "unknowns": unknowns,
            "retirement_authorized": False,
        }
        assets.append(asset)
        type_counts[asset_type] += 1
        lifecycle_counts[lifecycle_status] += 1
        for role in roles:
            role_counts[role] += 1

    source = {
        "requested_ref": str(manifest["source"]["requested_ref"]),
        "commit": str(manifest["source"]["commit"]),
        "tree": tree,
        "observation_manifest_sha256": _json_digest(manifest),
        "accepted_path_count": len(target_paths),
        "self_scan_verdict": str(manifest["boundary"]["self_scan_verdict"]),
    }
    payload: dict[str, Any] = {
        "schema_version": MAP_SCHEMA_VERSION,
        "status": MAP_STATUS,
        "created_at": utc_now_iso(),
        "source": source,
        "control_plane_boundary": {
            "protected_prefixes": list(manifest["exclusions"]["protected_path_prefixes"]),
            "excluded_path_count": int(manifest["corpus"]["excluded_path_count"]),
            "policy": "EKRI control-plane paths are excluded from target asset facts under No Active Self-Scan.",
        },
        "identity_policy": {
            "asset_namespace": asset_namespace,
            "stable_id_rule": "sha256(namespace + NUL + baseline_path) truncated to 24 hex; later moves preserve persisted asset_id",
            "ownership_rule": "owner labels require explicit responsibility/capability evidence; absence never establishes no-owner truth",
            "lifecycle_rule": "observed roles may be mixed; no retirement/deprecation/unused state is allowed in P1",
            "dependency_rule": "profile/bundle/config membership and bounded exact textual references are evidence only, not complete dependency knowledge",
        },
        "summary": {
            "asset_count": len(assets),
            "asset_type_counts": dict(sorted(type_counts.items())),
            "observed_role_counts": dict(sorted(role_counts.items())),
            "lifecycle_observation_counts": dict(sorted(lifecycle_counts.items())),
            "mixed_role_asset_count": mixed_role_count,
            "owner_unresolved_count": unknown_owner_count,
            "ownership_observation_counts": dict(sorted(ownership_status_counts.items())),
            "focus_text_reference_asset_count": len(text_refs),
        },
        "assets": assets,
        "claim_ceiling": (
            "Repository Asset Identity reconstructs evidence-bound asset identity, observed roles, and explicit ownership/capability references for the admitted immutable Git target. "
            "It does not prove exhaustive dependency closure, current semantic ownership where evidence is absent, redundancy, retirement eligibility, safe deletion, runtime equivalence after a move, or production behavior."
        ),
    }
    if write_outputs:
        output = root / ".EKRI" / "repository-assets" / tree / "repository-asset-knowledge-map.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["output"] = str(output)
    return payload


def validate_repository_asset_knowledge_map(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != MAP_SCHEMA_VERSION:
        raise RepositoryAssetIdentityError("unsupported repository asset map schema")
    if payload.get("status") != MAP_STATUS:
        raise RepositoryAssetIdentityError("unexpected repository asset map status")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RepositoryAssetIdentityError("repository asset map assets must be a list")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for raw in assets:
        if not isinstance(raw, dict):
            raise RepositoryAssetIdentityError("repository asset entry must be an object")
        asset_id = str(raw.get("asset_id") or "")
        if not re.fullmatch(r"asset-[0-9a-f]{24}", asset_id):
            raise RepositoryAssetIdentityError(f"invalid asset_id: {asset_id}")
        if asset_id in seen_ids:
            raise RepositoryAssetIdentityError(f"duplicate asset_id: {asset_id}")
        seen_ids.add(asset_id)
        paths = raw.get("current_paths")
        if not isinstance(paths, list) or len(paths) != 1:
            raise RepositoryAssetIdentityError(f"P1 asset must have exactly one current path: {asset_id}")
        path = _normalize_path(paths[0])
        if path in seen_paths:
            raise RepositoryAssetIdentityError(f"duplicate current path: {path}")
        seen_paths.add(path)
        asset_type = str(raw.get("asset_type") or "")
        if asset_type not in ASSET_TYPES:
            raise RepositoryAssetIdentityError(f"invalid asset_type: {asset_type}")
        roles = raw.get("observed_roles")
        if not isinstance(roles, list) or any(str(role) not in OBSERVED_ROLES for role in roles):
            raise RepositoryAssetIdentityError(f"invalid observed roles for {asset_id}")
        expected_status = lifecycle_observation_status(roles)
        if raw.get("lifecycle_observation_status") != expected_status:
            raise RepositoryAssetIdentityError(f"lifecycle observation mismatch for {asset_id}")
        ownership_status = str(raw.get("ownership_observation_status") or "")
        if ownership_status not in OWNERSHIP_OBSERVATION_STATUSES:
            raise RepositoryAssetIdentityError(f"invalid ownership observation for {asset_id}")
        owner_labels = raw.get("owner_evidence_labels")
        if not isinstance(owner_labels, list):
            raise RepositoryAssetIdentityError(f"owner evidence labels must be a list: {asset_id}")
        expected_ownership_status = (
            "unresolved" if not owner_labels else "single-owner-evidence" if len(set(owner_labels)) == 1 else "multi-owner-evidence"
        )
        if ownership_status != expected_ownership_status:
            raise RepositoryAssetIdentityError(f"ownership observation mismatch for {asset_id}")
        if raw.get("retirement_authorized") is not False:
            raise RepositoryAssetIdentityError(f"P1 cannot authorize retirement: {asset_id}")
    source = payload.get("source")
    if not isinstance(source, dict) or int(source.get("accepted_path_count", -1)) != len(assets):
        raise RepositoryAssetIdentityError("source accepted_path_count does not match asset denominator")
    return dict(payload)
