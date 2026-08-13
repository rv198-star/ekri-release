"""Portable, tracked EKRI project knowledge assets.

Local EKRI runtime state remains repository-root-bound under ``.EKRI``.  This
module promotes only content-addressed, repository-relative knowledge into
``.EKRI/project`` and verifies it against the named Git tree before use.
Tracked project knowledge remains excluded from every formal observation corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable
import uuid

from .observation_boundary import (
    PROTECTED_PATH_PREFIXES,
    _absolute_path,
    _run_git,
    _tree_entries,
)


PROJECT_ASSET_SCHEMA_VERSION = "ekri.project-knowledge-asset.v1"
PROJECT_ASSET_STATUS = "portable-project-knowledge-ready"
PROJECT_ROOT_TOKEN = "${REPOSITORY_ROOT}"
PROJECT_ASSET_MANIFEST = "PROJECT_KNOWLEDGE_MANIFEST.json"
PROJECT_ASSET_ROOT = Path(".EKRI/project")
RUNTIME_HYDRATION_ROOT = Path(".EKRI/runtime/project-assets")

ARTIFACT_FILES = {
    "architecture-memory": "architecture-memory.json",
    "evidence-index": "evidence-index.json",
    "reconstruction-report": "reconstruction-report.json",
    "capability-catalog": "capability-catalog.json",
}


class ProjectAssetError(RuntimeError):
    """Raised when portable project knowledge cannot be trusted."""


@dataclass(frozen=True)
class VerifiedProjectAsset:
    asset_dir: Path
    manifest: dict[str, Any]
    architecture_memory: dict[str, Any]
    evidence_index: dict[str, Any]
    reconstruction_report: dict[str, Any]
    capability_catalog: dict[str, Any]


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectAssetError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ProjectAssetError(f"{label} must be a list with at least {minimum} item(s)")
    return value


def _text(value: object, label: str, *, minimum: int = 1, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise ProjectAssetError(f"{label} must contain between {minimum} and {maximum} characters")
    return text


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise ProjectAssetError(f"{label} must be a safe regular file: {path}")
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectAssetError(f"{label} cannot be read: {exc}") from exc


def _portableize(value: object, repository_root: Path) -> object:
    root = str(repository_root.resolve())
    if isinstance(value, dict):
        return {str(key): _portableize(item, repository_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portableize(item, repository_root) for item in value]
    if isinstance(value, str):
        if value == root:
            return PROJECT_ROOT_TOKEN
        if value.startswith(root + os.sep):
            suffix = value[len(root) :].replace(os.sep, "/")
            return PROJECT_ROOT_TOKEN + suffix
    return value


def _hydrate_value(value: object, repository_root: Path) -> object:
    if isinstance(value, dict):
        return {str(key): _hydrate_value(item, repository_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_hydrate_value(item, repository_root) for item in value]
    if isinstance(value, str) and value.startswith(PROJECT_ROOT_TOKEN):
        suffix = value[len(PROJECT_ROOT_TOKEN) :].lstrip("/")
        return str(repository_root / Path(suffix)) if suffix else str(repository_root)
    return value


def _walk_strings(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def _is_absolute_literal(value: str) -> bool:
    text = str(value).strip()
    if text.startswith(PROJECT_ROOT_TOKEN):
        return False
    return bool(text.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("file://"))


def _safe_relative_path(value: str, label: str) -> str:
    text = _text(value, label, maximum=500)
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ProjectAssetError(f"{label} must be a canonical repository-relative path: {text}")
    normalized = path.as_posix()
    if normalized != text.replace("\\", "/"):
        raise ProjectAssetError(f"{label} is not canonical: {text}")
    return normalized


def _protected_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def _assert_no_symlink_path(root: Path, path: Path) -> None:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ProjectAssetError(f"project asset path escapes repository: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ProjectAssetError(f"project asset path crosses symlink: {current}")


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _artifact_payloads(
    repository_root: Path,
    *,
    source_tree: str,
) -> dict[str, dict[str, Any]]:
    knowledge_root = repository_root / ".EKRI" / "knowledge" / source_tree
    intelligence_root = repository_root / ".EKRI" / "intelligence" / source_tree
    sources = {
        "architecture-memory": knowledge_root / "architecture-memory.json",
        "evidence-index": knowledge_root / "evidence-index.json",
        "reconstruction-report": knowledge_root / "reconstruction-report.json",
        "capability-catalog": intelligence_root / "capability-catalog.json",
    }
    return {
        kind: _object(_portableize(_load_json(path, kind), repository_root), kind)
        for kind, path in sources.items()
    }


def promote_project_asset(
    repository_root: str | Path,
    *,
    source_tree: str,
    asset_id: str,
) -> dict[str, Any]:
    """Promote verified local runtime knowledge into a portable tracked asset."""
    root = _absolute_path(repository_root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]+", asset_id):
        raise ProjectAssetError("asset_id must use lowercase letters, digits, '.', '_' or '-'")
    payloads = _artifact_payloads(root, source_tree=source_tree)
    memory = payloads["architecture-memory"]
    evidence = payloads["evidence-index"]
    report = payloads["reconstruction-report"]
    catalog = payloads["capability-catalog"]
    memory_source = _object(memory.get("source"), "architecture memory source")
    if memory_source.get("tree") != source_tree:
        raise ProjectAssetError("architecture memory tree does not match requested source_tree")
    target_commit = _text(memory_source.get("commit"), "target commit", minimum=40, maximum=64)
    admitted_digest = _text(
        memory_source.get("admitted_path_set_sha256"),
        "admitted path-set digest",
        minimum=64,
        maximum=64,
    )
    asset_dir = root / PROJECT_ASSET_ROOT / asset_id
    _assert_no_symlink_path(root, asset_dir)
    artifact_rows: list[dict[str, str]] = []
    for kind, filename in ARTIFACT_FILES.items():
        raw = _json_bytes(payloads[kind])
        _atomic_write(asset_dir / filename, raw)
        artifact_rows.append({"kind": kind, "path": filename, "sha256": _sha256(raw)})
    manifest = {
        "schema_version": PROJECT_ASSET_SCHEMA_VERSION,
        "status": PROJECT_ASSET_STATUS,
        "asset_id": asset_id,
        "profile_id": _text(memory.get("profile_id"), "profile_id"),
        "target": {
            "commit": target_commit,
            "tree": source_tree,
            "admitted_path_set_sha256": admitted_digest,
        },
        "portability": {
            "repository_root_token": PROJECT_ROOT_TOKEN,
            "formal_corpus_exclusions": ["EKRI/", ".EKRI/"],
            "runtime_hydration_root": RUNTIME_HYDRATION_ROOT.as_posix(),
        },
        "artifacts": artifact_rows,
        "capability_profile": {
            "capability_count": int(catalog.get("capability_count") or 0),
            "alias_count": len(_object(catalog.get("alias_index"), "catalog alias index")),
            "ambiguous_alias_count": len(_object(catalog.get("ambiguous_aliases"), "catalog ambiguous aliases")),
        },
        "claim_ceiling": (
            "This tracked asset is a portable, content-addressed projection of the named EKRI baseline. "
            "It must be reverified against the named Git tree before use and does not prove current-tree completeness, reuse fitness, release readiness, or semantic acceptance."
        ),
    }
    _atomic_write(asset_dir / PROJECT_ASSET_MANIFEST, _json_bytes(manifest))
    verified = verify_project_asset(root, asset_id=asset_id)
    return {
        "status": "project-asset-promoted",
        "asset_dir": str(verified.asset_dir),
        "manifest": verified.manifest,
    }


def _manifest_artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in _array(manifest.get("artifacts"), "project artifacts", minimum=4):
        row = _object(raw, "project artifact")
        kind = _text(row.get("kind"), "project artifact kind", maximum=80)
        if kind not in ARTIFACT_FILES or kind in result:
            raise ProjectAssetError(f"unexpected or duplicate project artifact kind: {kind}")
        path = _safe_relative_path(str(row.get("path") or ""), f"{kind} path")
        if path != ARTIFACT_FILES[kind]:
            raise ProjectAssetError(f"unexpected filename for {kind}: {path}")
        digest = _text(row.get("sha256"), f"{kind} digest", minimum=64, maximum=64)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProjectAssetError(f"invalid SHA-256 for {kind}")
        result[kind] = {"kind": kind, "path": path, "sha256": digest}
    if set(result) != set(ARTIFACT_FILES):
        raise ProjectAssetError("project asset artifact set is incomplete")
    return result


def _evidence_ref_set(evidence_index: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for raw_source in _array(evidence_index.get("sources"), "evidence sources", minimum=1):
        source = _object(raw_source, "evidence source")
        for raw_anchor in _array(source.get("anchors"), "evidence anchors", minimum=1):
            anchor = _object(raw_anchor, "evidence anchor")
            refs.add(_text(anchor.get("evidence_ref"), "evidence ref", maximum=240))
    return refs


def _collect_declared_evidence_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_refs" and isinstance(item, list):
                refs.update(str(ref).strip() for ref in item if str(ref).strip())
            else:
                refs.update(_collect_declared_evidence_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_collect_declared_evidence_refs(item))
    return refs


def _verify_target_blob(
    repository_root: Path,
    *,
    tree: str,
    source: dict[str, Any],
) -> None:
    path = _safe_relative_path(str(source.get("path") or ""), "evidence source path")
    blob = _object(source.get("blob"), f"evidence blob {path}")
    blob_path = _safe_relative_path(str(blob.get("path") or ""), "evidence blob path")
    if path != blob_path:
        raise ProjectAssetError(f"evidence source/blob path mismatch: {path} != {blob_path}")
    if _protected_path(path):
        raise ProjectAssetError(f"tracked project asset references protected formal-corpus path: {path}")
    rows = [entry for entry in _tree_entries(repository_root, tree, pathspec=path) if entry[3] == path]
    if len(rows) != 1:
        raise ProjectAssetError(f"evidence path is missing or ambiguous in target tree: {path}")
    mode, object_type, oid, _ = rows[0]
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise ProjectAssetError(f"evidence path is not a regular Git blob: {path}")
    if oid != str(blob.get("blob_oid") or ""):
        raise ProjectAssetError(f"evidence blob OID mismatch: {path}")
    raw = _run_git(repository_root, "cat-file", "blob", oid, binary=True)
    assert isinstance(raw, bytes)
    if _sha256(raw) != str(blob.get("sha256") or ""):
        raise ProjectAssetError(f"evidence blob SHA-256 mismatch: {path}")


def resolve_project_asset_dir(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> Path:
    root = _absolute_path(repository_root)
    project_root = root / PROJECT_ASSET_ROOT
    if asset_id:
        candidate = project_root / asset_id
        if not candidate.is_dir():
            raise ProjectAssetError(f"project asset does not exist: {asset_id}")
        return candidate
    candidates = sorted(
        path for path in project_root.iterdir() if path.is_dir() and (path / PROJECT_ASSET_MANIFEST).is_file()
    ) if project_root.is_dir() else []
    if len(candidates) != 1:
        raise ProjectAssetError(
            f"expected exactly one tracked project asset, found {len(candidates)}; select asset_id explicitly"
        )
    return candidates[0]


def find_v1_project_asset_id_for_target_tree(
    repository_root: str | Path,
    *,
    source_tree: str,
) -> str | None:
    """Resolve one legacy v1 asset by its explicit target-tree identity.

    This is intentionally narrower than the generic no-id resolver. Multiple
    project-asset eras/formats may coexist; a semantic consumer that already
    knows its source tree may select the unique matching v1 authority without
    guessing by directory order or product version.
    """
    root = _absolute_path(repository_root)
    tree = _text(source_tree, "project asset source tree", minimum=40, maximum=64)
    project_root = root / PROJECT_ASSET_ROOT
    candidates: list[str] = []
    if project_root.is_dir():
        for path in sorted(project_root.iterdir()):
            manifest_path = path / PROJECT_ASSET_MANIFEST
            if not path.is_dir() or not manifest_path.is_file():
                continue
            manifest = _load_json(manifest_path, f"project asset manifest: {path.name}")
            if manifest.get("schema_version") != PROJECT_ASSET_SCHEMA_VERSION:
                continue
            target = manifest.get("target")
            if isinstance(target, dict) and str(target.get("tree") or "") == tree:
                candidates.append(path.name)
    if len(candidates) > 1:
        raise ProjectAssetError(
            f"multiple v1 project assets match source tree {tree}; select asset_id explicitly"
        )
    return candidates[0] if candidates else None


def verify_project_asset(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> VerifiedProjectAsset:
    root = _absolute_path(repository_root)
    asset_dir = resolve_project_asset_dir(root, asset_id=asset_id)
    _assert_no_symlink_path(root, asset_dir)
    manifest = _load_json(asset_dir / PROJECT_ASSET_MANIFEST, "project asset manifest")
    if manifest.get("schema_version") != PROJECT_ASSET_SCHEMA_VERSION:
        raise ProjectAssetError("unsupported project asset schema")
    if manifest.get("status") != PROJECT_ASSET_STATUS:
        raise ProjectAssetError("project asset is not marked ready")
    target = _object(manifest.get("target"), "project asset target")
    commit = _text(target.get("commit"), "project asset commit", minimum=40, maximum=64)
    tree = _text(target.get("tree"), "project asset tree", minimum=40, maximum=64)
    resolved_commit = str(_run_git(root, "rev-parse", f"{commit}^{{commit}}")).strip()
    resolved_tree = str(_run_git(root, "rev-parse", f"{commit}^{{tree}}")).strip()
    if resolved_commit != commit or resolved_tree != tree:
        raise ProjectAssetError("project asset target commit/tree identity mismatch")
    portability = _object(manifest.get("portability"), "project asset portability")
    if portability.get("repository_root_token") != PROJECT_ROOT_TOKEN:
        raise ProjectAssetError("project asset repository-root token is invalid")
    if portability.get("formal_corpus_exclusions") != ["EKRI/", ".EKRI/"]:
        raise ProjectAssetError("project asset formal-corpus exclusions changed")
    artifact_rows = _manifest_artifact_map(manifest)
    payloads: dict[str, dict[str, Any]] = {}
    for kind, row in artifact_rows.items():
        path = asset_dir / row["path"]
        raw = path.read_bytes()
        if _sha256(raw) != row["sha256"]:
            raise ProjectAssetError(f"project artifact digest mismatch: {kind}")
        payload = _load_json(path, kind)
        absolute_literals = sorted({value for value in _walk_strings(payload) if _is_absolute_literal(value)})
        if absolute_literals:
            raise ProjectAssetError(
                f"project artifact contains absolute machine path ({kind}): {absolute_literals[0]}"
            )
        payloads[kind] = payload

    memory = payloads["architecture-memory"]
    evidence = payloads["evidence-index"]
    report = payloads["reconstruction-report"]
    catalog = payloads["capability-catalog"]
    for label, payload in (("architecture memory", memory), ("evidence index", evidence)):
        source = _object(payload.get("source"), f"{label} source")
        if source.get("commit") != commit or source.get("tree") != tree:
            raise ProjectAssetError(f"{label} target identity mismatch")
        if source.get("repository_root") != PROJECT_ROOT_TOKEN:
            raise ProjectAssetError(f"{label} is not repository-root portable")
    scanner = _object(memory.get("scanner"), "architecture memory scanner")
    if scanner.get("repository_root") != PROJECT_ROOT_TOKEN:
        raise ProjectAssetError("architecture memory scanner root is not portable")
    if scanner.get("implementation_root") != f"{PROJECT_ROOT_TOKEN}/EKRI":
        raise ProjectAssetError("architecture memory implementation root is not portable")

    for raw_source in _array(evidence.get("sources"), "evidence sources", minimum=1):
        _verify_target_blob(root, tree=tree, source=_object(raw_source, "evidence source"))
    evidence_refs = _evidence_ref_set(evidence)
    unknown_memory_refs = sorted(_collect_declared_evidence_refs(memory) - evidence_refs)
    unknown_catalog_refs = sorted(_collect_declared_evidence_refs(catalog) - evidence_refs)
    if unknown_memory_refs:
        raise ProjectAssetError("architecture memory references unknown evidence: " + ", ".join(unknown_memory_refs[:5]))
    if unknown_catalog_refs:
        raise ProjectAssetError("capability catalog references unknown evidence: " + ", ".join(unknown_catalog_refs[:5]))
    catalog_source = _object(catalog.get("source"), "capability catalog source")
    if catalog_source.get("commit") != commit or catalog_source.get("tree") != tree:
        raise ProjectAssetError("capability catalog target identity mismatch")
    profile = _object(manifest.get("capability_profile"), "capability profile")
    actual_profile = {
        "capability_count": int(catalog.get("capability_count") or 0),
        "alias_count": len(_object(catalog.get("alias_index"), "catalog alias index")),
        "ambiguous_alias_count": len(_object(catalog.get("ambiguous_aliases"), "catalog ambiguous aliases")),
    }
    if profile != actual_profile:
        raise ProjectAssetError("capability profile does not match catalog")
    if int(report.get("counts", {}).get("architecture_nodes", 0) or 0) != len(memory.get("system_architecture_tree", [])):
        raise ProjectAssetError("reconstruction report does not match Architecture Memory node count")
    return VerifiedProjectAsset(
        asset_dir=asset_dir,
        manifest=manifest,
        architecture_memory=memory,
        evidence_index=evidence,
        reconstruction_report=report,
        capability_catalog=catalog,
    )


def hydrate_project_asset(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> dict[str, Any]:
    """Hydrate a verified tracked asset into ignored, repository-root-bound runtime state."""
    root = _absolute_path(repository_root)
    verified = verify_project_asset(root, asset_id=asset_id)
    selected_id = _text(verified.manifest.get("asset_id"), "asset id", maximum=160)
    destination = root / RUNTIME_HYDRATION_ROOT / selected_id
    _assert_no_symlink_path(root, destination)
    payloads = {
        "architecture-memory.json": verified.architecture_memory,
        "evidence-index.json": verified.evidence_index,
        "reconstruction-report.json": verified.reconstruction_report,
        "capability-catalog.json": verified.capability_catalog,
    }
    output_digests: dict[str, str] = {}
    for filename, payload in payloads.items():
        raw = _json_bytes(_hydrate_value(payload, root))
        _atomic_write(destination / filename, raw)
        output_digests[filename] = _sha256(raw)
    manifest_raw = (verified.asset_dir / PROJECT_ASSET_MANIFEST).read_bytes()
    receipt = {
        "schema_version": "ekri.project-knowledge-hydration.v1",
        "status": "project-knowledge-hydrated",
        "asset_id": selected_id,
        "source_manifest_sha256": _sha256(manifest_raw),
        "target": verified.manifest["target"],
        "repository_root": str(root),
        "output_digests": output_digests,
        "claim_ceiling": (
            "Hydration proves only that the verified portable project asset was rebound to this repository root. "
            "It does not make the baseline current for a changed tree or independently prove semantic acceptance."
        ),
    }
    _atomic_write(destination / "HYDRATION_RECEIPT.json", _json_bytes(receipt))
    return {"output_root": str(destination), "receipt": receipt}


def load_verified_project_catalog(
    repository_root: str | Path,
    *,
    asset_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    verified = verify_project_asset(repository_root, asset_id=asset_id)
    return verified.capability_catalog, verified.manifest
