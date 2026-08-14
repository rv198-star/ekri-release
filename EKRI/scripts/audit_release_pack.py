#!/usr/bin/env python3
"""Audit an extracted independent EKRI release pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MANIFEST_NAME = "EKRI_RELEASE_PACK_MANIFEST.json"
REQUIRED_FILES = {
    ".gitignore",
    "README.md",
    MANIFEST_NAME,
    "EKRI/README.md",
    "EKRI/CHANGELOG.md",
    "EKRI/pyproject.toml",
    "EKRI/src/ekri/__init__.py",
    "EKRI/scripts/validate_observation_boundary.py",
    "EKRI/schemas/observation-manifest.schema.json",
    "EKRI/specs/wff-v162-baseline-reconstruction.json",
    "EKRI/audit-fixtures/wff-v162-phase3-baseline.json",
}
V100_REQUIRED_FILES = {
    "EKRI/docs/v100-supported-product-contract-v1.0.md",
    "EKRI/docs/releases/v1.0.0.md",
    "EKRI/docs/versioning-changelog-release-governance-v0.1.md",
    "EKRI/specs/v100-product-surface-classification.json",
}
V110_REQUIRED_FILES = {
    "EKRI/docs/adaptive-knowledge-acquisition-v1.1.md",
    "EKRI/docs/releases/v1.1.0.md",
    "EKRI/specs/v110-product-surface-classification.json",
    "EKRI/specs/adaptive-exploration-conformance.json",
}
V111_REQUIRED_FILES = {
    "EKRI/docs/releases/v1.1.1.md",
    "EKRI/specs/v111-skill-surface-classification.json",
    "EKRI/specs/version-compatibility.json",
    "EKRI/scripts/install_ekri_skills.py",
    "EKRI/scripts/check_version_compatibility.py",
    "EKRI/scripts/audit_v111_gate.py",
    "EKRI/skills/using-ekri/SKILL.md",
    "EKRI/skills/ekri-init/SKILL.md",
    "EKRI/skills/ekri-refresh/SKILL.md",
    "EKRI/skills/ekri-query/SKILL.md",
}
FORBIDDEN_PREFIXES = (
    "EKRI/tests/",
    "EKRI/registrations/",
    "EKRI/.pytest_cache/",
    ".EKRI/",
    "skills/",
    "scripts/",
    "runtime-deps/",
    "reference-packages/",
    "release-cases/",
)
FORBIDDEN_PARTS = ("/__pycache__/", "/.git/", "/.pytest_cache/")
FORBIDDEN_SUFFIXES = (".pyc", ".pyo")
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "settings.local.json",
    "id_rsa",
    "id_ed25519",
}
SECRET_PATTERNS = (
    re.compile(rb"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"ghp_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class EKRIReleasePackAuditError(RuntimeError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_manifest(pack_root: Path) -> dict[str, Any]:
    path = pack_root / MANIFEST_NAME
    if not path.is_file():
        raise EKRIReleasePackAuditError(f"manifest missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EKRIReleasePackAuditError(f"manifest cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise EKRIReleasePackAuditError("manifest must be a JSON object")
    return value


def audit_release_pack(pack_root: Path) -> dict[str, Any]:
    pack_root = pack_root.resolve()
    manifest = _load_manifest(pack_root)
    failures: list[str] = []

    if manifest.get("schema_version") != "ekri.release-pack.v1":
        failures.append("unsupported release-pack manifest schema")
    if manifest.get("product") != "EKRI":
        failures.append("manifest product must be EKRI")
    version = str(manifest.get("version") or "")
    if not version:
        failures.append("manifest version is missing")
    if str(manifest.get("package_name") or "") != pack_root.name:
        failures.append("package_name does not match extracted root directory")
    if manifest.get("installation_model") != "git-committed-top-level-EKRI-scanner-control-repository":
        failures.append("unexpected EKRI installation model")

    actual_files = sorted(
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*")
        if path.is_file()
    )
    actual_set = set(actual_files)
    required_files = set(REQUIRED_FILES)
    if version.startswith("1."):
        required_files.update(V100_REQUIRED_FILES)
    if version.startswith("1.1"):
        required_files.update(V110_REQUIRED_FILES)
    if version.startswith("1.1.1"):
        required_files.update(V111_REQUIRED_FILES)
    missing_required = sorted(required_files - actual_set)
    if missing_required:
        failures.append("required package files missing: " + ", ".join(missing_required))

    forbidden = sorted(
        path
        for path in actual_files
        if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
        or any(part in f"/{path}" for part in FORBIDDEN_PARTS)
        or path.endswith(FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        failures.append("forbidden release-pack paths present: " + ", ".join(forbidden[:20]))

    sensitive = sorted(path for path in actual_files if Path(path).name in SENSITIVE_NAMES)
    if sensitive:
        failures.append("sensitive local files present: " + ", ".join(sensitive))

    manifest_rows = manifest.get("files")
    if not isinstance(manifest_rows, list):
        failures.append("manifest files must be a list")
        manifest_rows = []
    manifest_map: dict[str, dict[str, Any]] = {}
    for raw in manifest_rows:
        if not isinstance(raw, dict):
            failures.append("manifest file row must be an object")
            continue
        path = str(raw.get("path") or "")
        if not path or path in manifest_map:
            failures.append(f"manifest file path missing or duplicated: {path!r}")
            continue
        manifest_map[path] = raw

    content_files = actual_set - {MANIFEST_NAME}
    manifest_files = set(manifest_map)
    missing_from_manifest = sorted(content_files - manifest_files)
    unexpected_manifest = sorted(manifest_files - content_files)
    if missing_from_manifest:
        failures.append("package files missing from manifest: " + ", ".join(missing_from_manifest[:20]))
    if unexpected_manifest:
        failures.append("manifest references missing files: " + ", ".join(unexpected_manifest[:20]))

    digest_failures: list[str] = []
    secret_hits: list[str] = []
    total_bytes = 0
    for path in sorted(content_files & manifest_files):
        file_path = pack_root / path
        raw = file_path.read_bytes()
        total_bytes += len(raw)
        row = manifest_map[path]
        if int(row.get("size", -1)) != len(raw) or str(row.get("sha256") or "") != _sha256(raw):
            digest_failures.append(path)
        for pattern in SECRET_PATTERNS:
            if pattern.search(raw):
                secret_hits.append(path)
                break
    if digest_failures:
        failures.append("file size/digest mismatch: " + ", ".join(digest_failures[:20]))
    if secret_hits:
        failures.append("secret-like content present: " + ", ".join(secret_hits[:20]))

    if int(manifest.get("included_file_count", -1)) != len(manifest_rows):
        failures.append("included_file_count does not match manifest rows")
    if int(manifest.get("included_total_bytes", -1)) != total_bytes:
        failures.append("included_total_bytes does not match extracted content")

    pyproject = pack_root / "EKRI" / "pyproject.toml"
    if pyproject.is_file() and version:
        match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if not match or match.group(1) != version:
            failures.append("pyproject version does not match release-pack manifest")

    return {
        "schema_version": "ekri.release-pack-audit.v1",
        "status": "pass" if not failures else "fail",
        "pack_root": str(pack_root),
        "version": version,
        "source_revision": str(manifest.get("source_revision") or ""),
        "packager_revision": str(manifest.get("packager_revision") or ""),
        "file_count": len(actual_files),
        "content_file_count": len(content_files),
        "content_total_bytes": total_bytes,
        "forbidden_paths": forbidden,
        "sensitive_paths": sensitive,
        "secret_like_paths": secret_hits,
        "digest_failures": digest_failures,
        "hard_failures": failures,
        "claim_ceiling": (
            "This audit verifies the extracted EKRI release-pack boundary and file integrity only; "
            "it does not raise EKRI semantic, completeness, governance, or host-release claims."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit an extracted independent EKRI release pack")
    parser.add_argument("--pack-root", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = audit_release_pack(Path(args.pack_root))
    except EKRIReleasePackAuditError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
