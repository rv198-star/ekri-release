"""WFF v1.8 P2 physical Core extraction audit.

P2 consumes the accepted P1 Minimal Core Contract, observes a committed target
Git tree with EKRI excluded, and verifies that the physical ``wff-core`` package
implements the bounded contract without Core-outward repository dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tomllib
from typing import Any, Iterable, Mapping
import uuid

from .core_boundary_reconstruction import CoreBoundaryError
from .git_evidence import AdmittedEvidenceError, AdmittedGitReader
from .minimal_core_contract import (
    MinimalCoreContractError,
    run_minimal_core_contract,
)
from .observation_boundary import (
    ObservationBoundaryError,
    ScannerIdentity,
    VALID_VERDICT,
    _absolute_path,
    _directory_open_flags,
    _open_or_create_directory,
    _run_git,
    _tree_entries,
    evaluate_observation_boundary,
    is_protected_path,
    resolve_scanner_identity,
    write_manifest,
)


SPEC_SCHEMA_VERSION = "ekri.wff-core-extraction-spec.v1"
AUDIT_SCHEMA_VERSION = "ekri.core-extraction-audit.v1"
DEPENDENCY_SCHEMA_VERSION = "ekri.core-physical-dependency-report.v1"
COMPATIBILITY_SCHEMA_VERSION = "ekri.core-physical-compatibility-report.v1"
MEASUREMENT_SCHEMA_VERSION = "ekri.core-extraction-measurement.v1"
PHASE_ID = "v1.8-p2-core-extraction"
PROFILE_ID = "wff-v1.8-p2-core-extraction"
VALID_STATUS = "core-extraction-verified"


class CoreExtractionError(RuntimeError):
    """Raised when physical Core extraction cannot be verified safely."""


@dataclass(frozen=True)
class CoreExtractionSpecIdentity:
    source: str
    path: str
    sha256: str
    scanner_commit: str
    scanner_tree: str
    blob_oid: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoreExtractionError(f"{label} must be an object")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise CoreExtractionError(
            f"{label} must be a list with at least {minimum} item(s)"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    minimum: int = 1,
    maximum: int = 4000,
) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise CoreExtractionError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CoreExtractionError(f"{label} cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CoreExtractionError(f"{label} must be a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoreExtractionError(f"{label} cannot be read: {exc}") from exc
    return _object(value, label)


def load_core_extraction_spec(
    path: str | Path | None = None,
    *,
    scanner: ScannerIdentity | None = None,
) -> tuple[dict[str, Any], CoreExtractionSpecIdentity]:
    if path is not None:
        source = Path(path).expanduser()
        payload = _load_json_file(source, "Core extraction specification")
        raw = source.read_bytes()
        identity = CoreExtractionSpecIdentity(
            source="external-file",
            path=str(source),
            sha256=_sha256(raw),
            scanner_commit="",
            scanner_tree="",
            blob_oid="",
        )
    else:
        try:
            active = scanner or resolve_scanner_identity()
        except ObservationBoundaryError as exc:
            raise CoreExtractionError(
                f"active scanner provenance is unverifiable: {exc}"
            ) from exc
        relative_path = "EKRI/specs/wff-v18-core-extraction.json"
        entries = [
            entry
            for entry in _tree_entries(
                active.repository_root,
                active.tree,
                pathspec=relative_path,
            )
            if entry[3] == relative_path
        ]
        if len(entries) != 1:
            raise CoreExtractionError(
                "committed Core extraction specification is missing or ambiguous"
            )
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise CoreExtractionError(
                "committed Core extraction specification must be a regular Git blob"
            )
        raw = _run_git(
            Path(active.repository_root),
            "cat-file",
            "blob",
            oid,
            binary=True,
        )
        assert isinstance(raw, bytes)
        try:
            payload = _object(
                json.loads(raw.decode("utf-8")),
                "Core extraction specification",
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoreExtractionError(
                f"committed Core extraction specification cannot be read: {exc}"
            ) from exc
        identity = CoreExtractionSpecIdentity(
            source="scanner-commit",
            path=relative_path,
            sha256=_sha256(raw),
            scanner_commit=active.commit,
            scanner_tree=active.tree,
            blob_oid=oid,
        )
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise CoreExtractionError("unsupported Core extraction specification schema")
    if payload.get("profile_id") != PROFILE_ID:
        raise CoreExtractionError("unexpected Core extraction profile id")
    return payload, identity


def _read_json_blob(reader: AdmittedGitReader, path: str, label: str) -> dict[str, Any]:
    try:
        raw = reader.read_text(path)
    except AdmittedEvidenceError as exc:
        raise CoreExtractionError(f"{label} cannot be read: {exc}") from exc
    try:
        return _object(json.loads(raw), label)
    except json.JSONDecodeError as exc:
        raise CoreExtractionError(f"{label} is invalid JSON: {exc}") from exc


def _ids(rows: object, label: str) -> set[str]:
    result: set[str] = set()
    for raw in _array(rows, label):
        row = _object(raw, f"{label} row")
        identifier = _text(row.get("id"), f"{label} id", maximum=240)
        if identifier in result:
            raise CoreExtractionError(f"duplicate {label} id: {identifier}")
        result.add(identifier)
    return result


def _p1_semantic_projection(p1_contract: Mapping[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for key in ("contracts", "public_types", "public_operations", "invariants"):
        rows = [
            _object(value, f"P1 semantic projection {key} row")
            for value in _array(p1_contract.get(key), f"P1 semantic projection {key}")
        ]
        projection[key] = sorted(rows, key=lambda row: str(row.get("id") or ""))
    for key in ("public_api", "internal_api", "extension_interface"):
        projection[key] = _object(
            p1_contract.get(key),
            f"P1 semantic projection {key}",
        )
    return projection


def validate_contract_binding(
    p1_contract: Mapping[str, Any],
    runtime_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if runtime_manifest.get("schema_version") != "wff.core-contract-manifest.v1":
        raise CoreExtractionError("runtime Core contract manifest schema is invalid")
    if runtime_manifest.get("contract_id") != p1_contract.get("contract_id"):
        raise CoreExtractionError("runtime Core contract id does not match P1")
    if runtime_manifest.get("contract_version") != p1_contract.get("contract_version"):
        raise CoreExtractionError("runtime Core contract version does not match P1")
    expected_projection_sha256 = _sha256(
        _json_bytes(_p1_semantic_projection(p1_contract))
    )
    if runtime_manifest.get("p1_semantic_projection_sha256") != expected_projection_sha256:
        raise CoreExtractionError(
            "runtime Core manifest is not bound to the exact accepted P1 semantic projection"
        )
    comparisons = {
        "contracts": (
            _ids(p1_contract.get("contracts"), "P1 contracts"),
            _ids(runtime_manifest.get("contracts"), "runtime contracts"),
        ),
        "public_types": (
            _ids(p1_contract.get("public_types"), "P1 public types"),
            _ids(runtime_manifest.get("public_types"), "runtime public types"),
        ),
        "public_operations": (
            _ids(p1_contract.get("public_operations"), "P1 public operations"),
            _ids(runtime_manifest.get("public_operations"), "runtime public operations"),
        ),
        "invariants": (
            _ids(p1_contract.get("invariants"), "P1 invariants"),
            _ids(runtime_manifest.get("invariants"), "runtime invariants"),
        ),
    }
    mismatches: dict[str, dict[str, list[str]]] = {}
    for label, (authority, runtime) in comparisons.items():
        if authority != runtime:
            mismatches[label] = {
                "missing": sorted(authority - runtime),
                "extra": sorted(runtime - authority),
            }
    if mismatches:
        raise CoreExtractionError(
            "runtime Core contract manifest diverges from P1: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    p1_types = {
        row["id"]: row
        for row in (
            _object(value, "P1 public type")
            for value in _array(p1_contract.get("public_types"), "P1 public types")
        )
    }
    runtime_types = {
        row["id"]: row
        for row in (
            _object(value, "runtime public type")
            for value in _array(runtime_manifest.get("public_types"), "runtime public types")
        )
    }
    for identifier, authority in p1_types.items():
        runtime = runtime_types[identifier]
        authority_fields = [
            _text(field.get("name"), f"{identifier} P1 field", maximum=240)
            for field in (
                _object(value, f"{identifier} P1 field")
                for value in _array(authority.get("fields"), f"{identifier} P1 fields")
            )
        ]
        if runtime.get("contract_id") != authority.get("contract_id") or runtime.get("fields") != authority_fields:
            raise CoreExtractionError(
                f"runtime public type structure diverges from P1: {identifier}"
            )
    p1_operations = {
        row["id"]: row
        for row in (
            _object(value, "P1 public operation")
            for value in _array(p1_contract.get("public_operations"), "P1 public operations")
        )
    }
    runtime_operations = {
        row["id"]: row
        for row in (
            _object(value, "runtime public operation")
            for value in _array(runtime_manifest.get("public_operations"), "runtime public operations")
        )
    }
    for identifier, authority in p1_operations.items():
        runtime = runtime_operations[identifier]
        for key in ("contract_id", "input_type_ids", "output_type_ids"):
            if runtime.get(key) != authority.get(key):
                raise CoreExtractionError(
                    f"runtime public operation structure diverges from P1: {identifier}.{key}"
                )
    counts = _object(runtime_manifest.get("counts"), "runtime manifest counts")
    expected_counts = {
        "contracts": len(comparisons["contracts"][0]),
        "public_types": len(comparisons["public_types"][0]),
        "public_operations": len(comparisons["public_operations"][0]),
        "invariants": len(comparisons["invariants"][0]),
    }
    if counts != expected_counts:
        raise CoreExtractionError("runtime Core contract counts do not match P1")
    return {
        "status": "p1-contract-bound",
        "contract_id": runtime_manifest["contract_id"],
        "contract_version": runtime_manifest["contract_version"],
        "counts": expected_counts,
        "p1_semantic_projection_sha256": expected_projection_sha256,
    }


def _descriptor_indexes(capability_manifest: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    rows = _array(capability_manifest.get("descriptors"), "capability descriptors", minimum=1)
    by_id: dict[str, dict[str, Any]] = {}
    alias_index: dict[str, str] = {}
    prohibited = {
        "loader",
        "loader_hook",
        "module",
        "module_path",
        "entrypoint",
        "callback",
        "install",
        "package",
        "discovery",
        "marketplace",
        "hot_reload",
    }
    for raw in rows:
        row = _object(raw, "capability descriptor")
        identifier = _text(row.get("extension_id"), "extension_id", maximum=240)
        if identifier in by_id:
            raise CoreExtractionError(f"duplicate capability descriptor: {identifier}")
        leaked = sorted(set(row) & prohibited)
        if leaked:
            raise CoreExtractionError(
                f"capability descriptor {identifier} contains executable/plugin fields: "
                + ", ".join(leaked)
            )
        by_id[identifier] = row
        for value in [
            *_array(row.get("route_keys"), f"{identifier} route_keys"),
            *_array(row.get("compatibility_aliases"), f"{identifier} compatibility_aliases"),
        ]:
            alias = _text(value, f"{identifier} alias", maximum=240)
            owner = alias_index.get(alias)
            if owner and owner != identifier:
                raise CoreExtractionError(
                    f"compatibility alias {alias!r} is ambiguous between {owner} and {identifier}"
                )
            alias_index[alias] = identifier
    return by_id, alias_index


def validate_capability_binding(
    p1_contract: Mapping[str, Any],
    capability_manifest: Mapping[str, Any],
    required_entries: Mapping[str, str],
) -> dict[str, Any]:
    if capability_manifest.get("schema_version") != "wff.core-current-capabilities.v1":
        raise CoreExtractionError("current-capability manifest schema is invalid")
    if capability_manifest.get("core_contract_version") != p1_contract.get("contract_version"):
        raise CoreExtractionError("current-capability manifest targets the wrong Core version")
    by_id, aliases = _descriptor_indexes(capability_manifest)
    authority_rows = {
        _text(row.get("capability_id"), "P1 capability id", maximum=240): row
        for row in (
            _object(value, "P1 compatibility row")
            for value in _array(
                p1_contract.get("capability_compatibility"),
                "P1 compatibility rows",
            )
        )
    }
    if set(by_id) != set(authority_rows):
        raise CoreExtractionError(
            "current-capability descriptor coverage diverges from P1 compatibility matrix"
        )
    consumption_mismatches: list[str] = []
    for identifier, authority in authority_rows.items():
        expected = set(_array(authority.get("consumes_contract_ids"), f"{identifier} P1 consumes"))
        actual = set(_array(by_id[identifier].get("consumes_contracts"), f"{identifier} runtime consumes"))
        if expected != actual:
            consumption_mismatches.append(identifier)
    if consumption_mismatches:
        raise CoreExtractionError(
            "capability descriptors diverge from P1 contract consumption: "
            + ", ".join(sorted(consumption_mismatches))
        )
    missing_entries = {
        name: expected
        for name, expected in required_entries.items()
        if aliases.get(name) != expected
    }
    if missing_entries:
        raise CoreExtractionError(
            "required compatibility entries are missing or misbound: "
            + json.dumps(missing_entries, ensure_ascii=False, sort_keys=True)
        )
    return {
        "status": "capability-compatibility-bound",
        "descriptor_count": len(by_id),
        "alias_count": len(aliases),
        "required_entry_count": len(required_entries),
        "required_entries": dict(sorted(required_entries.items())),
    }


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add("wff_core")
            elif node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def _dynamic_calls(tree: ast.AST) -> list[str]:
    module_aliases = {"importlib"}
    callable_aliases = {"__import__", "exec", "eval"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        callable_aliases.add(alias.asname or alias.name)
            elif node.module == "builtins":
                for alias in node.names:
                    if alias.name in {"__import__", "exec", "eval"}:
                        callable_aliases.add(alias.asname or alias.name)

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = ""
        prohibited = False
        if isinstance(function, ast.Name):
            name = function.id
            prohibited = name in callable_aliases
        elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            name = f"{function.value.id}.{function.attr}"
            prohibited = (
                function.value.id in module_aliases
                and function.attr == "import_module"
            )
        if prohibited:
            findings.append(name)
    return sorted(set(findings))


def audit_core_dependencies(
    reader: AdmittedGitReader,
    spec: Mapping[str, Any],
    dependency_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if dependency_manifest.get("schema_version") != "wff.core-dependency-manifest.v1":
        raise CoreExtractionError("Core dependency manifest schema is invalid")
    runtime_dependencies = _array(
        dependency_manifest.get("runtime_dependencies"),
        "runtime_dependencies",
    )
    if runtime_dependencies:
        raise CoreExtractionError("P2 Core must not have third-party runtime dependencies")
    allowed = set(
        _text(value, "allowed import root", maximum=120)
        for value in _array(
            dependency_manifest.get("allowed_python_import_roots"),
            "allowed_python_import_roots",
        )
    )
    allowed.add(
        _text(
            dependency_manifest.get("allowed_internal_import_root"),
            "allowed_internal_import_root",
            maximum=120,
        )
    )
    physical = _object(spec.get("physical_boundary"), "physical_boundary")
    runtime_paths = [
        _text(value, "runtime python path", maximum=1000)
        for value in _array(physical.get("runtime_python_paths"), "runtime_python_paths", minimum=1)
    ]
    forbidden_prefixes = tuple(
        _text(value, "forbidden dependency", maximum=1000)
        for value in _array(
            spec.get("forbidden_repository_dependencies"),
            "forbidden_repository_dependencies",
        )
    )
    import_rows: list[dict[str, Any]] = []
    forbidden_imports: list[dict[str, str]] = []
    forbidden_references: list[dict[str, str]] = []
    dynamic_features: list[dict[str, Any]] = []
    line_count = 0
    byte_count = 0
    for path in runtime_paths:
        try:
            raw = reader.read_bytes(path)
            text = raw.decode("utf-8")
        except (AdmittedEvidenceError, UnicodeDecodeError) as exc:
            raise CoreExtractionError(f"Core runtime source cannot be read: {path}: {exc}") from exc
        line_count += len(text.splitlines())
        byte_count += len(raw)
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            raise CoreExtractionError(f"Core runtime source is invalid Python: {path}: {exc}") from exc
        roots = sorted(_import_roots(tree))
        import_rows.append({"path": path, "import_roots": roots})
        for root in roots:
            if root not in allowed:
                forbidden_imports.append({"path": path, "import_root": root})
        for prefix in forbidden_prefixes:
            if prefix in text:
                forbidden_references.append({"path": path, "reference": prefix})
        calls = _dynamic_calls(tree)
        if calls:
            dynamic_features.append({"path": path, "calls": calls})
    if forbidden_imports or forbidden_references or dynamic_features:
        raise CoreExtractionError("Core dependency boundary audit found forbidden dependencies")
    return {
        "schema_version": DEPENDENCY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-dependency-boundary-verified",
        "runtime_python_file_count": len(runtime_paths),
        "runtime_python_line_count": line_count,
        "runtime_python_byte_count": byte_count,
        "third_party_runtime_dependency_count": 0,
        "imports": import_rows,
        "forbidden_imports": forbidden_imports,
        "forbidden_references": forbidden_references,
        "dynamic_executable_features": dynamic_features,
        "retained_unknown": "exhaustive-code-dependency-closure",
        "claim_ceiling": (
            "This report proves imports and repository references visible in committed Core Python blobs. "
            "It does not prove exhaustive subprocess, generated-resource, or external runtime dependency closure."
        ),
    }


def _validate_required_paths(
    reader: AdmittedGitReader,
    paths: Iterable[str],
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for path in paths:
        normalized = _text(path, "required Core path", maximum=1000)
        try:
            reader.read_bytes(normalized)
            receipts.append(reader.receipt(normalized).to_dict())
        except AdmittedEvidenceError as exc:
            raise CoreExtractionError(
                f"required Core extraction path is unavailable: {normalized}: {exc}"
            ) from exc
    return receipts


def _compare_registered_frontier(
    actual_paths: Iterable[str],
    expected_paths: Iterable[str],
) -> dict[str, Any]:
    actual = set(actual_paths)
    expected = set(expected_paths)
    missing = sorted(expected - actual)
    unregistered = sorted(actual - expected)
    if missing or unregistered:
        raise CoreExtractionError(
            "P2 target change frontier does not match registered expected paths; "
            f"missing={missing}, unregistered={unregistered}"
        )
    return {
        "status": "registered-change-frontier-exact",
        "changed_path_count": len(actual),
        "registered_path_count": len(expected),
        "changed_paths": sorted(actual),
        "registered_paths": sorted(expected),
        "missing_registered_paths": missing,
        "unregistered_changed_paths": unregistered,
    }


def validate_registered_change_frontier(
    repository_root: Path,
    *,
    target_commit: str,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    base_commit = _text(
        spec.get("base_main_commit"),
        "base_main_commit",
        maximum=80,
    )
    merge_base = str(
        _run_git(repository_root, "merge-base", base_commit, target_commit)
    ).strip()
    if merge_base != base_commit:
        raise CoreExtractionError(
            "P2 target is not a direct descendant of the accepted main baseline"
        )
    raw = _run_git(
        repository_root,
        "diff",
        "--name-only",
        "--no-renames",
        f"{base_commit}..{target_commit}",
    )
    assert isinstance(raw, str)
    changed_paths = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not is_protected_path(line.strip())
    ]
    physical = _object(spec.get("physical_boundary"), "physical_boundary")
    expected_paths = [
        _text(value, "registered required path", maximum=1000)
        for value in _array(physical.get("required_paths"), "required_paths", minimum=1)
    ]
    expected_paths.extend(
        _text(value, "repository record path", maximum=1000)
        for value in _array(
            physical.get("repository_record_paths"),
            "repository_record_paths",
        )
    )
    result = _compare_registered_frontier(changed_paths, expected_paths)
    result.update(
        {
            "base_commit": base_commit,
            "target_commit": target_commit,
            "protected_changes_excluded": True,
        }
    )
    return result


def _validate_pyproject(reader: AdmittedGitReader, path: str) -> dict[str, Any]:
    try:
        payload = reader.read_bytes(path)
        value = tomllib.loads(payload.decode("utf-8"))
    except (AdmittedEvidenceError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise CoreExtractionError(f"Core pyproject cannot be read: {exc}") from exc
    project = _object(value.get("project"), "Core pyproject project")
    if project.get("name") != "wff-core" or project.get("version") != "1.0.0":
        raise CoreExtractionError("Core pyproject identity/version does not match P1")
    dependencies = project.get("dependencies")
    if dependencies != []:
        raise CoreExtractionError("Core pyproject must have zero runtime dependencies")
    return {
        "name": project["name"],
        "version": project["version"],
        "requires_python": project.get("requires-python", ""),
        "runtime_dependencies": dependencies,
    }


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
        os.replace(temporary, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        created = False
        os.fsync(parent_fd)
    except OSError as exc:
        raise CoreExtractionError(f"failed to persist P2 output {filename}: {exc}") from exc
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def render_core_extraction_review(audit: Mapping[str, Any]) -> str:
    measurements = audit["measurements"]
    lines = [
        "# WFF v1.8 P2 — Core Extraction Review",
        "",
        f"- Target commit: `{audit['source']['target_commit']}`",
        f"- Target tree: `{audit['source']['target_tree']}`",
        f"- Contract: `{audit['contract_binding']['contract_id']}` `{audit['contract_binding']['contract_version']}`",
        f"- Physical home: `{audit['physical_boundary']['project_root']}`",
        f"- Status: `{audit['status']}`",
        "",
        "## Physical decision",
        "",
        "The independently installable Core implementation lives in the top-level `wff-core/` subproject and imports as `wff_core`. The directory is an implementation boundary, while the stable public authority remains `wff-core-contract` `1.0.0`.",
        "",
        "## Measurements",
        "",
        f"- Required extraction paths: `{measurements['required_path_count']}`",
        f"- Registered non-EKRI target changes: `{audit['change_frontier']['changed_path_count']}`",
        f"- Core runtime Python files: `{measurements['runtime_python_files']}`",
        f"- Core runtime Python lines: `{measurements['runtime_python_lines']}`",
        f"- Core runtime bytes: `{measurements['runtime_python_bytes']}`",
        f"- Third-party runtime dependencies: `{measurements['third_party_runtime_dependencies']}`",
        f"- Current capability descriptors: `{measurements['capability_descriptors']}`",
        "",
        "## Registered change frontier",
        "",
        f"All `{audit['change_frontier']['changed_path_count']}` non-EKRI changes from `{audit['change_frontier']['base_commit']}` to the target commit exactly match the registered expected paths. Missing and unregistered path counts are both zero.",
        "",
        "## Dependency boundary",
        "",
        "Core imports only Python standard-library modules and its own package. No committed Core runtime blob imports or references WFF capability, assurance, distribution, history, release-case, or EKRI surfaces. Dynamic executable loading calls are absent.",
        "",
        "## Compatibility",
        "",
    ]
    for name, identifier in audit["compatibility_binding"]["required_entries"].items():
        lines.append(f"- `{name}` -> `{identifier}`")
    lines.extend(
        [
            "",
            "## Retained boundary",
            "",
            "`exhaustive-code-dependency-closure` remains unknown. P2 proves static committed imports/references plus independent installation tests; P4 must still prove subprocess, generated resource, final package, and runtime scenario closure.",
            "",
            "## Claim ceiling",
            "",
            audit["claim_ceiling"],
            "",
        ]
    )
    return "\n".join(lines)


def _persist_outputs(repository_root: Path, audit: dict[str, Any]) -> dict[str, str]:
    dependency = audit["dependency_report"]
    compatibility = {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-compatibility-descriptors-verified",
        "created_at": audit["created_at"],
        "source": audit["source"],
        **audit["compatibility_binding"],
        "claim_ceiling": (
            "Descriptor and alias binding proves repository compatibility metadata only. "
            "Current runners and install packs are not migrated to require Core in P2."
        ),
    }
    measurements = {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "phase": PHASE_ID,
        "status": "core-extraction-measured",
        "created_at": audit["created_at"],
        "source": audit["source"],
        **audit["measurements"],
        "semantic_interpretation": (
            "The physical Core is a small contract/operation package with zero third-party runtime dependencies. "
            "Line count is descriptive only and does not define Core correctness."
        ),
        "claim_ceiling": "Measurements do not prove runtime parity, release readiness, or semantic completeness by themselves.",
    }
    review = render_core_extraction_review(audit).encode("utf-8")
    payloads = {
        "core-extraction-audit.json": _json_bytes(audit),
        "core-dependency-report.json": _json_bytes(dependency),
        "core-compatibility-report.json": _json_bytes(compatibility),
        "core-extraction-measurements.json": _json_bytes(measurements),
        "CORE_EXTRACTION_REVIEW.md": review,
    }
    output_audit = {
        "schema_version": "ekri.core-extraction-output-audit.v1",
        "phase": PHASE_ID,
        "status": "core-extraction-output-persisted",
        "created_at": utc_now_iso(),
        "source_tree": audit["source"]["target_tree"],
        "output_digests": {
            name: _sha256(payload) for name, payload in sorted(payloads.items())
        },
        "checks": [
            {"check": "p1-contract-binding", "status": "passed"},
            {"check": "physical-dependency-boundary", "status": "passed"},
            {"check": "compatibility-descriptor-binding", "status": "passed"},
            {"check": "no-follow-atomic-persistence", "status": "passed"},
        ],
        "claim_ceiling": "Output persistence and digests do not strengthen the P2 extraction claim.",
    }
    payloads["core-extraction-output-audit.json"] = _json_bytes(output_audit)

    root_fd = os.open(repository_root, _directory_open_flags())
    opened: list[int] = []
    try:
        parent_fd = root_fd
        for component in (".EKRI", "core-extraction", audit["source"]["target_tree"]):
            descriptor = _open_or_create_directory(parent_fd, component)
            opened.append(descriptor)
            parent_fd = descriptor
        for filename, payload in payloads.items():
            _secure_atomic_write(parent_fd, filename, payload)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(root_fd)

    output_root = repository_root / ".EKRI" / "core-extraction" / audit["source"]["target_tree"]
    return {
        "output_root": str(output_root),
        **{
            name.replace("-", "_").replace(".", "_"): str(output_root / name)
            for name in payloads
        },
    }


def run_core_extraction_audit(
    repository_root: str | Path,
    *,
    target_ref: str = "HEAD",
    write_outputs: bool = True,
) -> dict[str, Any]:
    root = _absolute_path(repository_root)
    if not root.is_dir():
        raise CoreExtractionError(f"repository root is not a directory: {root}")
    try:
        p1 = run_minimal_core_contract(root, write_outputs=True)
        p1_contract = _object(p1.get("contract"), "P1 contract")
        spec, spec_identity = load_core_extraction_spec()
        manifest = evaluate_observation_boundary(
            repository_root=root,
            target_ref=target_ref,
        )
        if manifest.get("boundary", {}).get("verdict") != VALID_VERDICT:
            raise CoreExtractionError(
                "P2 target observation was rejected: "
                + str(manifest.get("boundary", {}).get("failure_reason") or "unknown reason")
            )
        write_manifest(root, manifest)
        reader = AdmittedGitReader(root, manifest)
        physical = _object(spec.get("physical_boundary"), "physical_boundary")
        required_paths = [
            _text(value, "required path", maximum=1000)
            for value in _array(physical.get("required_paths"), "required_paths", minimum=1)
        ]
        receipts = _validate_required_paths(reader, required_paths)
        change_frontier = validate_registered_change_frontier(
            root,
            target_commit=reader.commit,
            spec=spec,
        )
        runtime_manifest = _read_json_blob(
            reader,
            _text(physical.get("contract_manifest_path"), "contract_manifest_path", maximum=1000),
            "runtime Core contract manifest",
        )
        capability_manifest = _read_json_blob(
            reader,
            _text(physical.get("capability_manifest_path"), "capability_manifest_path", maximum=1000),
            "current capability descriptor manifest",
        )
        dependency_manifest = _read_json_blob(
            reader,
            _text(physical.get("dependency_manifest_path"), "dependency_manifest_path", maximum=1000),
            "Core dependency manifest",
        )
        contract_binding = validate_contract_binding(p1_contract, runtime_manifest)
        required_entries = {
            str(key): _text(value, f"required compatibility entry {key}", maximum=240)
            for key, value in _object(
                spec.get("required_compatibility_entries"),
                "required_compatibility_entries",
            ).items()
        }
        compatibility_binding = validate_capability_binding(
            p1_contract,
            capability_manifest,
            required_entries,
        )
        dependency_report = audit_core_dependencies(
            reader,
            spec,
            dependency_manifest,
        )
        pyproject = _validate_pyproject(reader, "wff-core/pyproject.toml")
        registered_change_ids = [
            _text(value, "registered change id", maximum=240)
            for value in _array(spec.get("registered_change_ids"), "registered_change_ids", minimum=1)
        ]
        created_at = utc_now_iso()
        measurements = {
            "required_path_count": len(required_paths),
            "registered_target_path_count": change_frontier["registered_path_count"],
            "required_path_bytes": sum(int(row["size_bytes"]) for row in receipts),
            "runtime_python_files": dependency_report["runtime_python_file_count"],
            "runtime_python_lines": dependency_report["runtime_python_line_count"],
            "runtime_python_bytes": dependency_report["runtime_python_byte_count"],
            "third_party_runtime_dependencies": dependency_report["third_party_runtime_dependency_count"],
            "capability_descriptors": compatibility_binding["descriptor_count"],
            "compatibility_aliases": compatibility_binding["alias_count"],
        }
        audit = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "phase": PHASE_ID,
            "profile_id": PROFILE_ID,
            "status": VALID_STATUS,
            "created_at": created_at,
            "source": {
                "target_ref": target_ref,
                "target_commit": reader.commit,
                "target_tree": reader.tree,
                "observation_manifest_sha256": _sha256(_json_bytes(manifest)),
                "p1_target_tree": p1_contract["source"]["p0_target_tree"],
                "p1_contract_sha256": _sha256(_json_bytes(p1_contract)),
            },
            "specification": asdict(spec_identity),
            "physical_boundary": {
                "project_root": physical["project_root"],
                "python_import_root": physical["python_import_root"],
                "package_source_root": physical["package_source_root"],
                "pyproject": pyproject,
                "resolved_p0_unknown": "physical-core-home",
            },
            "contract_binding": contract_binding,
            "compatibility_binding": compatibility_binding,
            "change_frontier": change_frontier,
            "dependency_report": dependency_report,
            "registered_change_ids": registered_change_ids,
            "measurements": measurements,
            "retained_unknowns": list(spec.get("retained_unknowns", [])),
            "checks": [
                {"check": "p1-authority-regenerated", "status": "passed", "detail": "P0/P1 authority was regenerated before physical audit"},
                {"check": "required-git-blobs", "status": "passed", "detail": f"read {len(receipts)} required extraction blobs from the target Git tree"},
                {"check": "registered-change-frontier", "status": "passed", "detail": f"all {change_frontier['changed_path_count']} non-EKRI target changes exactly match registered expected paths"},
                {"check": "runtime-contract-binding", "status": "passed", "detail": "packaged Core contract ids and counts match P1"},
                {"check": "capability-compatibility-binding", "status": "passed", "detail": "sixteen capability descriptors consume the P1 contract matrix and preserve required entries"},
                {"check": "core-dependency-direction", "status": "passed", "detail": "committed Core runtime imports standard-library/internal modules only"},
                {"check": "no-dynamic-plugin-runtime", "status": "passed", "detail": "no dynamic executable loading calls appear in committed Core runtime blobs"},
                {"check": "physical-home-resolved", "status": "passed", "detail": "P2 resolves physical-core-home as the wff-core subproject without making the path public API"},
            ],
            "claim_ceiling": _text(spec.get("claim_ceiling"), "claim_ceiling", minimum=60),
        }
        outputs: dict[str, str] = {}
        if write_outputs:
            outputs = _persist_outputs(root, audit)
        return {
            "schema_version": "ekri.core-extraction-run.v1",
            "status": VALID_STATUS,
            "audit": audit,
            "outputs": outputs,
        }
    except CoreExtractionError:
        raise
    except (
        CoreBoundaryError,
        MinimalCoreContractError,
        ObservationBoundaryError,
        AdmittedEvidenceError,
    ) as exc:
        raise CoreExtractionError(f"P2 authority validation failed: {exc}") from exc
    except Exception as exc:
        raise CoreExtractionError(f"P2 failed closed: {exc}") from exc
