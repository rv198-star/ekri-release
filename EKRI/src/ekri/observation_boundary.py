#!/usr/bin/env python3
"""Phase 0 trust boundary for formal EKRI observations.

Formal observations are keyed by immutable Git commit/tree identities. The
active EKRI implementation and local runtime state are removed from the target
path corpus before any target blob may be read. Scanner provenance is resolved
independently from the target, Git replacement objects are disabled, and valid
manifests are persisted only after semantic revalidation through no-follow,
atomic filesystem operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any
import uuid


SCHEMA_VERSION = "ekri.observation-manifest.v2"
SCANNER_VERSION = "0.8.0"
SUPPORTED_SCANNER_VERSIONS = frozenset({"0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0", "0.8.0"})
EXCLUSION_POLICY_ID = "ekri-protected-paths-v2"
PHASE_ID = "phase0-observation-independence"
VALID_VERDICT = "formal-corpus-valid"
REJECTED_VERDICT = "rejected"

# Permanent, non-configurable trust boundary. Callers cannot replace or weaken
# these values. The evaluation oracle is nested below EKRI/ and is recorded
# separately so its exclusion remains explicit in provenance evidence.
ACTIVE_SCANNER_PATH_PREFIXES: tuple[str, ...] = ("EKRI/",)
RUNTIME_STATE_PATH_PREFIXES: tuple[str, ...] = (".EKRI/",)
ORACLE_PATH_PREFIXES: tuple[str, ...] = ("EKRI/evaluation-oracle/",)
PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    *ACTIVE_SCANNER_PATH_PREFIXES,
    *RUNTIME_STATE_PATH_PREFIXES,
)

_OID_RE = re.compile(r"^[0-9a-f]+$")
_EXPECTED_OID_LENGTH = {"sha1": 40, "sha256": 64}


@dataclass(frozen=True)
class GitTargetIdentity:
    repository_root: str
    requested_ref: str
    commit: str
    tree: str
    object_format: str


@dataclass(frozen=True)
class ScannerIdentity:
    repository_root: str
    implementation_root: str
    commit: str
    tree: str
    object_format: str
    surface_tree_sha256: str
    surface_path_count: int
    runtime_matches_commit: bool


class ObservationBoundaryError(RuntimeError):
    """Raised when a formal observation target cannot be proven safe."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _absolute_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _run_git(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    proc = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *arguments],
        capture_output=True,
        text=not binary,
        check=False,
        env=_git_environment(),
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace") if binary else proc.stderr
        stdout = proc.stdout.decode(errors="replace") if binary else proc.stdout
        detail = str(stderr).strip() or str(stdout).strip() or "git command failed"
        raise ObservationBoundaryError(detail)
    return proc.stdout


def _validate_oid(value: str, object_format: str, *, label: str) -> str:
    expected_length = _EXPECTED_OID_LENGTH.get(object_format)
    if expected_length is None:
        raise ObservationBoundaryError(
            f"unsupported Git object format for {label}: {object_format}"
        )
    if len(value) != expected_length or _OID_RE.fullmatch(value) is None:
        raise ObservationBoundaryError(f"invalid {label} object identity: {value}")
    return value


def resolve_git_target(
    repository_root: str | Path,
    *,
    target_ref: str = "HEAD",
) -> GitTargetIdentity:
    declared_root = _absolute_path(repository_root)
    if not declared_root.is_dir():
        raise ObservationBoundaryError(
            f"repository root is not a directory: {declared_root}"
        )

    actual_root = _absolute_path(
        str(_run_git(declared_root, "rev-parse", "--show-toplevel")).strip()
    )
    if actual_root != declared_root:
        raise ObservationBoundaryError(
            "declared repository root is not the Git top level: "
            f"declared={declared_root}, actual={actual_root}"
        )

    requested_ref = str(target_ref).strip()
    if not requested_ref:
        raise ObservationBoundaryError("target ref must not be empty")

    object_format = str(
        _run_git(declared_root, "rev-parse", "--show-object-format")
    ).strip()
    commit = str(
        _run_git(
            declared_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{requested_ref}^{{commit}}",
        )
    ).strip()
    commit = _validate_oid(commit, object_format, label="commit")
    tree = str(
        _run_git(
            declared_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{commit}^{{tree}}",
        )
    ).strip()
    tree = _validate_oid(tree, object_format, label="tree")

    return GitTargetIdentity(
        repository_root=str(actual_root),
        requested_ref=requested_ref,
        commit=commit,
        tree=tree,
        object_format=object_format,
    )


def _normalize_tree_path(raw: str) -> str:
    if not raw:
        raise ObservationBoundaryError("Git tree contains an empty path")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ObservationBoundaryError(f"Git tree contains an unsafe path: {raw}")
    normalized = path.as_posix()
    if normalized != raw:
        raise ObservationBoundaryError(
            f"Git tree path is not canonical: raw={raw}, normalized={normalized}"
        )
    return normalized


def _tree_entries(
    repository_root: str | Path,
    tree: str,
    *,
    pathspec: str | None = None,
) -> tuple[tuple[str, str, str, str], ...]:
    root = _absolute_path(repository_root)
    arguments = ["ls-tree", "-r", "-z", "--full-tree", tree]
    if pathspec is not None:
        arguments.extend(["--", pathspec])
    raw = _run_git(root, *arguments, binary=True)
    assert isinstance(raw, bytes)

    entries: list[tuple[str, str, str, str]] = []
    for value in raw.split(b"\0"):
        if not value:
            continue
        try:
            metadata, path_bytes = value.split(b"\t", 1)
            mode_bytes, type_bytes, oid_bytes = metadata.split(b" ", 2)
            mode = mode_bytes.decode("ascii")
            object_type = type_bytes.decode("ascii")
            oid = oid_bytes.decode("ascii")
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ObservationBoundaryError(
                "Git tree contains an invalid or non-UTF-8 entry"
            ) from exc
        entries.append((mode, object_type, oid, _normalize_tree_path(path)))

    paths = [entry[3] for entry in entries]
    if len(paths) != len(set(paths)):
        raise ObservationBoundaryError("Git tree contains duplicate normalized paths")
    return tuple(entries)


def enumerate_tree_paths(repository_root: str | Path, tree: str) -> tuple[str, ...]:
    """Enumerate names from a Git tree without reading target blob content."""
    return tuple(entry[3] for entry in _tree_entries(repository_root, tree))


def _scanner_implementation_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _validate_scanner_surface_entries(
    entries: tuple[tuple[str, str, str, str], ...]
) -> None:
    unsafe = [
        path
        for mode, object_type, _, path in entries
        if object_type != "blob" or mode not in {"100644", "100755"}
    ]
    if unsafe:
        raise ObservationBoundaryError(
            "scanner implementation surface contains symlink, gitlink, or non-regular entry: "
            + ", ".join(unsafe[:10])
        )


def _surface_digest(entries: tuple[tuple[str, str, str, str], ...]) -> str:
    digest = hashlib.sha256()
    for mode, object_type, oid, path in entries:
        for value in (mode, object_type, oid, path):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def resolve_scanner_identity() -> ScannerIdentity:
    implementation_root = _scanner_implementation_root()
    repository_root = _absolute_path(
        str(_run_git(implementation_root, "rev-parse", "--show-toplevel")).strip()
    )
    try:
        relative_implementation_root = implementation_root.relative_to(repository_root)
    except ValueError as exc:
        raise ObservationBoundaryError(
            "scanner implementation is outside its declared Git repository"
        ) from exc
    if relative_implementation_root.as_posix() != "EKRI":
        raise ObservationBoundaryError(
            "formal scanner implementation root must be the top-level EKRI directory"
        )

    identity = resolve_git_target(repository_root, target_ref="HEAD")
    entries = _tree_entries(repository_root, identity.tree, pathspec="EKRI")
    if not entries:
        raise ObservationBoundaryError(
            "scanner commit does not contain the active EKRI implementation surface"
        )
    _validate_scanner_surface_entries(entries)

    status = str(
        _run_git(
            repository_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "EKRI",
        )
    ).strip()
    if status:
        raise ObservationBoundaryError(
            "active EKRI scanner surface does not match its recorded scanner commit"
        )

    return ScannerIdentity(
        repository_root=str(repository_root),
        implementation_root=str(implementation_root),
        commit=identity.commit,
        tree=identity.tree,
        object_format=identity.object_format,
        surface_tree_sha256=_surface_digest(entries),
        surface_path_count=len(entries),
        runtime_matches_commit=True,
    )


def is_protected_path(path: str) -> bool:
    normalized = _normalize_tree_path(path)
    return any(normalized.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def _matching_paths(paths: tuple[str, ...], prefixes: tuple[str, ...]) -> list[str]:
    return [path for path in paths if any(path.startswith(prefix) for prefix in prefixes)]


def _corpus_digest(paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _new_manifest(repository_root: Path, target_ref: str) -> dict[str, Any]:
    output_root = repository_root / ".EKRI"
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE_ID,
        "created_at": utc_now_iso(),
        "observation_mode": "formal-git-tree",
        "source": {
            "repository_root": str(repository_root),
            "requested_ref": target_ref,
            "commit": "",
            "tree": "",
            "object_format": "",
            "replace_objects_disabled": True,
        },
        "scanner": {
            "repository_root": "",
            "implementation_root": "",
            "commit": "",
            "tree": "",
            "object_format": "",
            "implementation_version": SCANNER_VERSION,
            "surface_tree_sha256": "",
            "surface_path_count": 0,
            "runtime_matches_commit": False,
            "exclusion_policy_id": EXCLUSION_POLICY_ID,
            "exclusion_policy_sha256": hashlib.sha256(
                "\0".join(PROTECTED_PATH_PREFIXES).encode("utf-8")
            ).hexdigest(),
            "target_blob_reads_performed": False,
        },
        "output": {
            "root": str(output_root),
            "manifest_path": "",
            "knowledge_root": "",
            "cache_root": str(output_root / "cache"),
            "logs_root": str(output_root / "logs"),
        },
        "exclusions": {
            "protected_path_prefixes": list(PROTECTED_PATH_PREFIXES),
            "active_scanner_path_prefixes": list(ACTIVE_SCANNER_PATH_PREFIXES),
            "runtime_state_path_prefixes": list(RUNTIME_STATE_PATH_PREFIXES),
            "oracle_path_prefixes": list(ORACLE_PATH_PREFIXES),
            "caller_overridable": False,
            "excluded_active_scanner_paths": [],
            "excluded_runtime_state_paths": [],
            "excluded_oracle_paths": [],
        },
        "corpus": {
            "candidate_path_count": 0,
            "excluded_path_count": 0,
            "accepted_path_count": 0,
            "path_set_sha256": "",
            "paths": [],
        },
        "boundary": {
            "valid": False,
            "verdict": REJECTED_VERDICT,
            "self_scan_verdict": "rejected",
            "failure_code": "",
            "failure_reason": "",
            "checks": [],
        },
    }


def _record_check(
    manifest: dict[str, Any], *, check: str, status: str, detail: str
) -> None:
    manifest["boundary"]["checks"].append(
        {"check": check, "status": status, "detail": detail}
    )


def _reject(
    manifest: dict[str, Any], *, code: str, reason: str, check: str
) -> dict[str, Any]:
    manifest["boundary"]["valid"] = False
    manifest["boundary"]["verdict"] = REJECTED_VERDICT
    manifest["boundary"]["self_scan_verdict"] = "rejected"
    manifest["boundary"]["failure_code"] = code
    manifest["boundary"]["failure_reason"] = reason
    _record_check(manifest, check=check, status="failed", detail=reason)
    return manifest


def rejected_manifest_copy(
    manifest: dict[str, Any], *, code: str, reason: str, check: str
) -> dict[str, Any]:
    clone = json.loads(json.dumps(manifest))
    return _reject(clone, code=code, reason=reason, check=check)


def _accept(manifest: dict[str, Any], *, self_scan_verdict: str) -> dict[str, Any]:
    manifest["boundary"]["valid"] = True
    manifest["boundary"]["verdict"] = VALID_VERDICT
    manifest["boundary"]["self_scan_verdict"] = self_scan_verdict
    manifest["boundary"]["failure_code"] = ""
    manifest["boundary"]["failure_reason"] = ""
    return manifest


def evaluate_observation_boundary(
    *,
    repository_root: str | Path,
    target_ref: str = "HEAD",
) -> dict[str, Any]:
    """Create a formal Phase 0 corpus manifest for one Git commit/tree."""
    root = _absolute_path(repository_root)
    normalized_ref = str(target_ref).strip()
    manifest = _new_manifest(root, normalized_ref)

    expected_contract = ("EKRI/", ".EKRI/")
    if PROTECTED_PATH_PREFIXES != expected_contract:
        return _reject(
            manifest,
            code="protected-prefix-invariant-broken",
            reason="the permanent EKRI/.EKRI exclusion invariant was modified",
            check="protected-prefix-contract",
        )
    _record_check(
        manifest,
        check="protected-prefix-contract",
        status="passed",
        detail="EKRI/** and .EKRI/** are fixed and caller-non-overridable",
    )

    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        return _reject(
            manifest,
            code="scanner-provenance-unverifiable",
            reason=str(exc),
            check="scanner-provenance",
        )
    manifest["scanner"].update(
        {
            "repository_root": scanner.repository_root,
            "implementation_root": scanner.implementation_root,
            "commit": scanner.commit,
            "tree": scanner.tree,
            "object_format": scanner.object_format,
            "surface_tree_sha256": scanner.surface_tree_sha256,
            "surface_path_count": scanner.surface_path_count,
            "runtime_matches_commit": scanner.runtime_matches_commit,
        }
    )
    _record_check(
        manifest,
        check="scanner-provenance",
        status="passed",
        detail="active scanner commit/tree and complete EKRI surface identity verified",
    )

    try:
        target = resolve_git_target(root, target_ref=normalized_ref)
    except ObservationBoundaryError as exc:
        return _reject(
            manifest,
            code="source-provenance-unverifiable",
            reason=str(exc),
            check="source-provenance",
        )

    manifest["source"].update(
        {
            "repository_root": target.repository_root,
            "requested_ref": target.requested_ref,
            "commit": target.commit,
            "tree": target.tree,
            "object_format": target.object_format,
        }
    )
    output_root = root / ".EKRI"
    manifest_path = output_root / "manifests" / f"{target.tree}-observation.json"
    manifest["output"]["manifest_path"] = str(manifest_path)
    manifest["output"]["knowledge_root"] = str(
        output_root / "knowledge" / target.tree
    )
    manifest["output"]["cache_root"] = str(output_root / "cache" / target.tree)
    _record_check(
        manifest,
        check="source-provenance",
        status="passed",
        detail="formal source commit/tree identity resolved with replacement objects disabled",
    )

    try:
        candidates = enumerate_tree_paths(root, target.tree)
    except ObservationBoundaryError as exc:
        return _reject(
            manifest,
            code="tree-enumeration-failed",
            reason=str(exc),
            check="tree-enumeration",
        )
    manifest["corpus"]["candidate_path_count"] = len(candidates)
    _record_check(
        manifest,
        check="tree-enumeration",
        status="passed",
        detail="candidate paths enumerated from Git tree metadata without target blob reads",
    )

    excluded_active = _matching_paths(candidates, ACTIVE_SCANNER_PATH_PREFIXES)
    excluded_runtime = _matching_paths(candidates, RUNTIME_STATE_PATH_PREFIXES)
    excluded_oracle = _matching_paths(candidates, ORACLE_PATH_PREFIXES)
    accepted = tuple(path for path in candidates if not is_protected_path(path))
    excluded_count = len(candidates) - len(accepted)
    manifest["exclusions"].update(
        {
            "excluded_active_scanner_paths": excluded_active,
            "excluded_runtime_state_paths": excluded_runtime,
            "excluded_oracle_paths": excluded_oracle,
        }
    )
    manifest["corpus"].update(
        {
            "excluded_path_count": excluded_count,
            "accepted_path_count": len(accepted),
            "path_set_sha256": _corpus_digest(accepted),
            "paths": list(accepted),
        }
    )

    leaked = tuple(path for path in accepted if is_protected_path(path))
    if leaked:
        return _reject(
            manifest,
            code="protected-path-in-corpus",
            reason="protected paths remain after filtering: " + ", ".join(leaked),
            check="final-corpus-validation",
        )
    _record_check(
        manifest,
        check="final-corpus-validation",
        status="passed",
        detail="final corpus contains no active EKRI, .EKRI runtime, or oracle path",
    )
    _record_check(
        manifest,
        check="content-read-ceiling",
        status="passed",
        detail="Phase 0 performed no target Git blob reads",
    )

    same_repository = target.repository_root == scanner.repository_root
    if same_repository:
        self_scan_verdict = "same-repository-protected-surfaces-excluded"
    else:
        self_scan_verdict = "external-repository-target"
    return _accept(manifest, self_scan_verdict=self_scan_verdict)


def manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _require_exact_keys(value: object, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ObservationBoundaryError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ObservationBoundaryError(
            f"{label} keys do not match the manifest contract: missing={missing}, extra={extra}"
        )
    return value


def _expected_valid_checks() -> list[dict[str, str]]:
    return [
        {
            "check": "protected-prefix-contract",
            "status": "passed",
            "detail": "EKRI/** and .EKRI/** are fixed and caller-non-overridable",
        },
        {
            "check": "scanner-provenance",
            "status": "passed",
            "detail": "active scanner commit/tree and complete EKRI surface identity verified",
        },
        {
            "check": "source-provenance",
            "status": "passed",
            "detail": "formal source commit/tree identity resolved with replacement objects disabled",
        },
        {
            "check": "tree-enumeration",
            "status": "passed",
            "detail": "candidate paths enumerated from Git tree metadata without target blob reads",
        },
        {
            "check": "final-corpus-validation",
            "status": "passed",
            "detail": "final corpus contains no active EKRI, .EKRI runtime, or oracle path",
        },
        {
            "check": "content-read-ceiling",
            "status": "passed",
            "detail": "Phase 0 performed no target Git blob reads",
        },
    ]


def validate_persisted_observation_manifest(
    repository_root: str | Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate a persisted Phase 0 manifest without trusting current scanner state.

    Phase 1 and later phases use this function before reading target blobs. The
    recorded historical scanner commit/tree is verified directly, while the
    target corpus, exclusions, counts, digest, output identity, and verdict are
    recomputed from immutable Git metadata with replacement objects disabled.
    """

    root = _absolute_path(repository_root)
    top = _require_exact_keys(
        manifest,
        {
            "schema_version",
            "phase",
            "created_at",
            "observation_mode",
            "source",
            "scanner",
            "output",
            "exclusions",
            "corpus",
            "boundary",
        },
        label="manifest",
    )
    if top["schema_version"] != SCHEMA_VERSION:
        raise ObservationBoundaryError("unsupported observation manifest schema")
    if top["phase"] != PHASE_ID or top["observation_mode"] != "formal-git-tree":
        raise ObservationBoundaryError("manifest phase or observation mode is invalid")
    created_at = str(top["created_at"])
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationBoundaryError("manifest created_at is not an ISO timestamp") from exc
    if parsed_created_at.tzinfo is None:
        raise ObservationBoundaryError("manifest created_at must include a timezone")

    scanner = _require_exact_keys(
        top["scanner"],
        {
            "repository_root",
            "implementation_root",
            "commit",
            "tree",
            "object_format",
            "implementation_version",
            "surface_tree_sha256",
            "surface_path_count",
            "runtime_matches_commit",
            "exclusion_policy_id",
            "exclusion_policy_sha256",
            "target_blob_reads_performed",
        },
        label="manifest.scanner",
    )
    scanner_root = _absolute_path(str(scanner["repository_root"]))
    scanner_identity = resolve_git_target(
        scanner_root,
        target_ref=str(scanner["commit"]),
    )
    expected_implementation_root = scanner_root / "EKRI"
    if _absolute_path(str(scanner["implementation_root"])) != expected_implementation_root:
        raise ObservationBoundaryError("manifest scanner implementation root is invalid")
    if (
        scanner_identity.commit != scanner["commit"]
        or scanner_identity.tree != scanner["tree"]
        or scanner_identity.object_format != scanner["object_format"]
    ):
        raise ObservationBoundaryError("manifest scanner commit/tree identity is invalid")
    scanner_entries = _tree_entries(scanner_root, scanner_identity.tree, pathspec="EKRI")
    if not scanner_entries:
        raise ObservationBoundaryError("manifest scanner commit has no EKRI surface")
    _validate_scanner_surface_entries(scanner_entries)
    if int(scanner["surface_path_count"]) != len(scanner_entries):
        raise ObservationBoundaryError("manifest scanner surface path count is invalid")
    if str(scanner["surface_tree_sha256"]) != _surface_digest(scanner_entries):
        raise ObservationBoundaryError("manifest scanner surface digest is invalid")
    if scanner["implementation_version"] not in SUPPORTED_SCANNER_VERSIONS:
        raise ObservationBoundaryError("manifest scanner version is unsupported")
    if scanner["runtime_matches_commit"] is not True:
        raise ObservationBoundaryError("manifest scanner runtime was not commit-matched")
    if scanner["exclusion_policy_id"] != EXCLUSION_POLICY_ID:
        raise ObservationBoundaryError("manifest exclusion policy id is invalid")
    expected_policy_digest = hashlib.sha256(
        "\0".join(PROTECTED_PATH_PREFIXES).encode("utf-8")
    ).hexdigest()
    if scanner["exclusion_policy_sha256"] != expected_policy_digest:
        raise ObservationBoundaryError("manifest exclusion policy digest is invalid")
    if scanner["target_blob_reads_performed"] is not False:
        raise ObservationBoundaryError("Phase 0 manifest reports target blob reads")

    source = _require_exact_keys(
        top["source"],
        {
            "repository_root",
            "requested_ref",
            "commit",
            "tree",
            "object_format",
            "replace_objects_disabled",
        },
        label="manifest.source",
    )
    if _absolute_path(str(source["repository_root"])) != root:
        raise ObservationBoundaryError("manifest source repository root is invalid")
    if not str(source["requested_ref"]).strip():
        raise ObservationBoundaryError("manifest requested ref is empty")
    target = resolve_git_target(root, target_ref=str(source["commit"]))
    if (
        target.commit != source["commit"]
        or target.tree != source["tree"]
        or target.object_format != source["object_format"]
    ):
        raise ObservationBoundaryError("manifest source commit/tree identity is invalid")
    if source["replace_objects_disabled"] is not True:
        raise ObservationBoundaryError("manifest did not disable Git replacement objects")

    output = _require_exact_keys(
        top["output"],
        {"root", "manifest_path", "knowledge_root", "cache_root", "logs_root"},
        label="manifest.output",
    )
    output_root = root / ".EKRI"
    expected_output = {
        "root": str(output_root),
        "manifest_path": str(
            output_root / "manifests" / f"{target.tree}-observation.json"
        ),
        "knowledge_root": str(output_root / "knowledge" / target.tree),
        "cache_root": str(output_root / "cache" / target.tree),
        "logs_root": str(output_root / "logs"),
    }
    if output != expected_output:
        raise ObservationBoundaryError("manifest output identity is invalid")

    exclusions = _require_exact_keys(
        top["exclusions"],
        {
            "protected_path_prefixes",
            "active_scanner_path_prefixes",
            "runtime_state_path_prefixes",
            "oracle_path_prefixes",
            "caller_overridable",
            "excluded_active_scanner_paths",
            "excluded_runtime_state_paths",
            "excluded_oracle_paths",
        },
        label="manifest.exclusions",
    )
    if exclusions["protected_path_prefixes"] != list(PROTECTED_PATH_PREFIXES):
        raise ObservationBoundaryError("manifest protected path prefixes are invalid")
    if exclusions["active_scanner_path_prefixes"] != list(ACTIVE_SCANNER_PATH_PREFIXES):
        raise ObservationBoundaryError("manifest active scanner prefixes are invalid")
    if exclusions["runtime_state_path_prefixes"] != list(RUNTIME_STATE_PATH_PREFIXES):
        raise ObservationBoundaryError("manifest runtime state prefixes are invalid")
    if exclusions["oracle_path_prefixes"] != list(ORACLE_PATH_PREFIXES):
        raise ObservationBoundaryError("manifest oracle prefixes are invalid")
    if exclusions["caller_overridable"] is not False:
        raise ObservationBoundaryError("manifest exclusions are caller-overridable")

    candidates = enumerate_tree_paths(root, target.tree)
    accepted = tuple(path for path in candidates if not is_protected_path(path))
    expected_excluded_active = _matching_paths(candidates, ACTIVE_SCANNER_PATH_PREFIXES)
    expected_excluded_runtime = _matching_paths(candidates, RUNTIME_STATE_PATH_PREFIXES)
    expected_excluded_oracle = _matching_paths(candidates, ORACLE_PATH_PREFIXES)
    if exclusions["excluded_active_scanner_paths"] != expected_excluded_active:
        raise ObservationBoundaryError("manifest active scanner exclusion evidence is invalid")
    if exclusions["excluded_runtime_state_paths"] != expected_excluded_runtime:
        raise ObservationBoundaryError("manifest runtime exclusion evidence is invalid")
    if exclusions["excluded_oracle_paths"] != expected_excluded_oracle:
        raise ObservationBoundaryError("manifest oracle exclusion evidence is invalid")

    corpus = _require_exact_keys(
        top["corpus"],
        {
            "candidate_path_count",
            "excluded_path_count",
            "accepted_path_count",
            "path_set_sha256",
            "paths",
        },
        label="manifest.corpus",
    )
    expected_corpus = {
        "candidate_path_count": len(candidates),
        "excluded_path_count": len(candidates) - len(accepted),
        "accepted_path_count": len(accepted),
        "path_set_sha256": _corpus_digest(accepted),
        "paths": list(accepted),
    }
    if corpus != expected_corpus:
        raise ObservationBoundaryError("manifest admitted corpus identity is invalid")

    boundary_state = _require_exact_keys(
        top["boundary"],
        {
            "valid",
            "verdict",
            "self_scan_verdict",
            "failure_code",
            "failure_reason",
            "checks",
        },
        label="manifest.boundary",
    )
    expected_self_scan = (
        "same-repository-protected-surfaces-excluded"
        if target.repository_root == scanner_identity.repository_root
        else "external-repository-target"
    )
    if boundary_state != {
        "valid": True,
        "verdict": VALID_VERDICT,
        "self_scan_verdict": expected_self_scan,
        "failure_code": "",
        "failure_reason": "",
        "checks": _expected_valid_checks(),
    }:
        raise ObservationBoundaryError("manifest boundary verdict or checks are invalid")

    return manifest


def _validated_manifest_for_persistence(
    repository_root: str | Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    if not isinstance(manifest, dict):
        raise ObservationBoundaryError("manifest must be an object")
    if manifest.get("boundary", {}).get("valid") is not True:
        raise ObservationBoundaryError("only a valid observation manifest may be persisted")

    source = manifest.get("source", {})
    commit = str(source.get("commit", ""))
    requested_ref = str(source.get("requested_ref", ""))
    created_at = str(manifest.get("created_at", ""))
    if not commit or not requested_ref or not created_at:
        raise ObservationBoundaryError(
            "manifest source identity and creation time must be complete"
        )

    rebuilt = evaluate_observation_boundary(
        repository_root=root,
        target_ref=commit,
    )
    if rebuilt.get("boundary", {}).get("valid") is not True:
        raise ObservationBoundaryError(
            "manifest could not be independently revalidated before persistence: "
            + str(rebuilt.get("boundary", {}).get("failure_reason", "unknown failure"))
        )
    rebuilt["created_at"] = created_at
    rebuilt["source"]["requested_ref"] = requested_ref
    if rebuilt != manifest:
        raise ObservationBoundaryError(
            "manifest content does not match a fresh formal boundary evaluation"
        )
    return rebuilt


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_or_create_directory(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise ObservationBoundaryError(
            f"output directory is not a safe real directory: {name}: {exc}"
        ) from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise ObservationBoundaryError(f"output component is not a directory: {name}")
    return descriptor


def _secure_atomic_write_manifest(
    repository_root: Path,
    *,
    tree: str,
    payload: bytes,
) -> Path:
    root_fd = os.open(repository_root, _directory_open_flags())
    output_fd = -1
    manifests_fd = -1
    temporary_name = f".{tree}.{uuid.uuid4().hex}.tmp"
    destination_name = f"{tree}-observation.json"
    temporary_created = False
    try:
        output_fd = _open_or_create_directory(root_fd, ".EKRI")
        manifests_fd = _open_or_create_directory(output_fd, "manifests")
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        file_flags |= getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(
            temporary_name,
            file_flags,
            0o600,
            dir_fd=manifests_fd,
        )
        temporary_created = True
        try:
            with os.fdopen(file_fd, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(
                temporary_name,
                destination_name,
                src_dir_fd=manifests_fd,
                dst_dir_fd=manifests_fd,
            )
            temporary_created = False
            os.fsync(manifests_fd)
        finally:
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=manifests_fd)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        raise ObservationBoundaryError(
            f"failed to persist manifest through the fixed .EKRI layout: {exc}"
        ) from exc
    finally:
        if manifests_fd >= 0:
            os.close(manifests_fd)
        if output_fd >= 0:
            os.close(output_fd)
        os.close(root_fd)

    return repository_root / ".EKRI" / "manifests" / destination_name


def write_manifest(
    repository_root: str | Path,
    manifest: dict[str, Any],
) -> Path:
    root = _absolute_path(repository_root)
    validated = _validated_manifest_for_persistence(root, manifest)
    tree = str(validated["source"]["tree"])
    destination = root / ".EKRI" / "manifests" / f"{tree}-observation.json"
    expected = str(validated["output"]["manifest_path"])
    if expected != str(destination):
        raise ObservationBoundaryError(
            "manifest output path does not match the fixed .EKRI layout"
        )
    return _secure_atomic_write_manifest(
        root,
        tree=tree,
        payload=manifest_json(validated).encode("utf-8"),
    )
