#!/usr/bin/env python3
"""Build an independent EKRI release pack from an exact Git source ref."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


EKRI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = EKRI_ROOT.parent
MANIFEST_NAME = "EKRI_RELEASE_PACK_MANIFEST.json"
CHECKSUMS_NAME = "SHA256SUMS"
PACKAGE_README_NAME = "README.md"
PACKAGE_GITIGNORE_NAME = ".gitignore"

GENERAL_DOCS = {
    "EKRI/docs/engineering-knowledge-reconstruction-intelligence-v0.1.md",
    "EKRI/docs/phase0-observation-independence-v0.2.md",
    "EKRI/docs/phase1-wff-baseline-reconstruction-v0.1.md",
    "EKRI/docs/phase2-existing-capability-intelligence-v0.1.md",
    "EKRI/docs/phase3-evolution-and-impact-intelligence-v0.1.md",
    "EKRI/docs/project-knowledge-asset-boundary-v0.1.md",
    "EKRI/docs/v191-repository-asset-identity-model-v0.1.md",
    "EKRI/docs/v191-repository-ownership-boundary-model-v0.1.md",
    "EKRI/docs/v191-repository-lifecycle-observation-model-v0.1.md",
    "EKRI/docs/v100-supported-product-contract-v1.0.md",
    "EKRI/docs/releases/v1.0.0.md",
    "EKRI/docs/versioning-changelog-release-governance-v0.1.md",
}

REQUIRED_ROOT_FILES = {
    "EKRI/README.md",
    "EKRI/CHANGELOG.md",
    "EKRI/pyproject.toml",
}

INCLUDED_PREFIXES = (
    "EKRI/src/",
    "EKRI/scripts/",
    "EKRI/schemas/",
    "EKRI/specs/",
    "EKRI/audit-fixtures/",
    "EKRI/docs/releases/",
    "EKRI/docs/adaptive-",
)

EXCLUDED_PREFIXES = (
    "EKRI/tests/",
    "EKRI/registrations/",
    "EKRI/.pytest_cache/",
)


class EKRIReleasePackError(RuntimeError):
    pass


def _run_git(repository_root: Path, *args: str, binary: bool = False) -> str | bytes:
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=repository_root,
        capture_output=True,
        text=not binary,
        check=False,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if binary else proc.stderr
        raise EKRIReleasePackError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return proc.stdout


def _resolve_source(repository_root: Path, source_ref: str) -> tuple[str, str]:
    commit = str(_run_git(repository_root, "rev-parse", "--verify", f"{source_ref}^{{commit}}")).strip()
    tree = str(_run_git(repository_root, "rev-parse", "--verify", f"{commit}^{{tree}}")).strip()
    if len(commit) < 40 or len(tree) < 40:
        raise EKRIReleasePackError("source ref did not resolve to stable Git identities")
    return commit, tree


def _packager_revision(repository_root: Path) -> str:
    return str(_run_git(repository_root, "rev-parse", "HEAD")).strip()


def _tree_entries(repository_root: Path, source_tree: str) -> list[tuple[str, str, str]]:
    raw = _run_git(repository_root, "ls-tree", "-r", "-z", "--full-tree", source_tree, "--", "EKRI", binary=True)
    assert isinstance(raw, bytes)
    rows: list[tuple[str, str, str]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, oid = metadata.decode("ascii").split(" ", 2)
        path = raw_path.decode("utf-8")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise EKRIReleasePackError(f"unsupported EKRI source entry: {mode} {object_type} {path}")
        rows.append((mode, oid, path))
    return rows


def should_include(path: str) -> bool:
    if path in REQUIRED_ROOT_FILES or path in GENERAL_DOCS:
        return True
    if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return any(path.startswith(prefix) for prefix in INCLUDED_PREFIXES)


def _read_blob(repository_root: Path, oid: str) -> bytes:
    raw = _run_git(repository_root, "cat-file", "blob", oid, binary=True)
    assert isinstance(raw, bytes)
    return raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _version_from_pyproject(raw: bytes) -> str:
    text = raw.decode("utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        raise EKRIReleasePackError("EKRI/pyproject.toml does not declare [project].version")
    return match.group(1)


def _package_gitignore() -> bytes:
    return b".EKRI/\n**/__pycache__/\n*.pyc\n*.pyo\n.pytest_cache/\n"


def _package_readme(version: str, source_revision: str) -> bytes:
    text = f"""# EKRI v{version} Release Pack

This is the independent EKRI source/runtime distribution for product version `{version}`.

Source identity: `{source_revision}` (the formal release tag, when published, is `ekri/v{version}`).

## Layout

The package preserves a top-level `EKRI/` directory because EKRI Formal Scanner provenance requires the active implementation to live at `EKRI/` in its scanner-control Git repository.

## Install / activate the Formal Scanner

1. Extract this package into a directory that will act as the EKRI scanner-control repository.
2. Initialize Git if needed: `git init`.
3. Keep the package-root `.gitignore`; it excludes `.EKRI/` and Python cache artifacts that must not make the scanner surface dirty.
4. Add and commit the extracted `EKRI/` surface (and package metadata if desired).
5. Run EKRI against a target Git repository, for example:

```bash
python3 EKRI/scripts/validate_observation_boundary.py \\
  --repository-root /path/to/target-repository \\
  --target-ref HEAD
```

The scanner intentionally fails closed if its `EKRI/` implementation surface is dirty, uncommitted, outside a Git repository, or not rooted at top-level `EKRI/`.

This package preserves the Git-backed scanner-control trust model. It does not add a standalone-provenance fallback.

## Included

- Python implementation under `EKRI/src/ekri/`
- EKRI command-line scripts
- schemas and product/profile specs required by the selected EKRI version
- committed audit/conformance fixtures required by current supported capabilities
- bounded product/operation/release documentation
- `EKRI/README.md`, `EKRI/CHANGELOG.md`, and `EKRI/pyproject.toml`

## Excluded

- EKRI tests
- WFF change-registration history
- ontology exploration/audit history not listed as bounded product documentation
- repository-local runtime state (`.EKRI/**`)
- WFF runtime/install-pack content

See `{MANIFEST_NAME}` for exact file identities and the release claim ceiling.
"""
    return text.encode("utf-8")


def _write_file(path: Path, raw: bytes, mode: str = "100644") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o755 if mode == "100755" else 0o644)


def _zip_info(name: str, executable: bool = False) -> ZipInfo:
    info = ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    permissions = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | permissions) << 16
    return info


def _build_zip(pack_root: Path, archive_path: Path) -> None:
    if archive_path.exists():
        archive_path.unlink()
    root_name = pack_root.name
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(pack_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(pack_root).as_posix()
            executable = bool(path.stat().st_mode & stat.S_IXUSR)
            archive.writestr(
                _zip_info(f"{root_name}/{relative}", executable=executable),
                path.read_bytes(),
                compress_type=ZIP_DEFLATED,
                compresslevel=9,
            )


def build_release_pack(
    *,
    repository_root: Path,
    source_ref: str,
    version: str,
    output_root: Path,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    output_root = output_root.resolve()
    source_revision, source_tree = _resolve_source(repository_root, source_ref)
    packager_revision = _packager_revision(repository_root)
    entries = _tree_entries(repository_root, source_tree)
    selected = [(mode, oid, path) for mode, oid, path in entries if should_include(path)]
    selected_paths = {path for _, _, path in selected}
    missing = sorted(REQUIRED_ROOT_FILES - selected_paths)
    if missing:
        raise EKRIReleasePackError("required EKRI release files missing from source: " + ", ".join(missing))

    pyproject_oid = next(oid for _, oid, path in selected if path == "EKRI/pyproject.toml")
    source_version = _version_from_pyproject(_read_blob(repository_root, pyproject_oid))
    if source_version != version:
        raise EKRIReleasePackError(
            f"source product version mismatch: requested={version}, pyproject={source_version}"
        )

    pack_name = f"ekri-v{version}-release-pack"
    pack_root = output_root / pack_name
    if pack_root.exists():
        import shutil
        shutil.rmtree(pack_root)
    pack_root.mkdir(parents=True, exist_ok=True)

    file_rows: list[dict[str, object]] = []
    for mode, oid, path in selected:
        raw = _read_blob(repository_root, oid)
        _write_file(pack_root / path, raw, mode)
        file_rows.append(
            {
                "path": path,
                "size": len(raw),
                "sha256": _sha256(raw),
                "git_blob_oid": oid,
                "mode": mode,
            }
        )

    package_readme = _package_readme(version, source_revision)
    _write_file(pack_root / PACKAGE_README_NAME, package_readme)
    file_rows.append(
        {
            "path": PACKAGE_README_NAME,
            "size": len(package_readme),
            "sha256": _sha256(package_readme),
            "git_blob_oid": "",
            "mode": "100644",
            "generated": True,
        }
    )
    package_gitignore = _package_gitignore()
    _write_file(pack_root / PACKAGE_GITIGNORE_NAME, package_gitignore)
    file_rows.append(
        {
            "path": PACKAGE_GITIGNORE_NAME,
            "size": len(package_gitignore),
            "sha256": _sha256(package_gitignore),
            "git_blob_oid": "",
            "mode": "100644",
            "generated": True,
        }
    )

    excluded_source_paths = sorted(path for _, _, path in entries if path not in selected_paths)
    manifest: dict[str, object] = {
        "schema_version": "ekri.release-pack.v1",
        "product": "EKRI",
        "version": version,
        "source_ref": source_ref,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "packager_revision": packager_revision,
        "package_name": pack_name,
        "installation_model": "git-committed-top-level-EKRI-scanner-control-repository",
        "formal_scanner_requirement": (
            "EKRI Formal Scanner requires the active implementation to be committed as top-level EKRI/ "
            "inside its scanner-control Git repository; this package does not introduce a standalone provenance fallback."
        ),
        "included_file_count": len(file_rows),
        "included_total_bytes": sum(int(row["size"]) for row in file_rows),
        "files": sorted(file_rows, key=lambda row: str(row["path"])),
        "excluded_source_paths": excluded_source_paths,
        "excluded_families": [
            "EKRI/tests/**",
            "EKRI/registrations/**",
            "EKRI/.pytest_cache/**",
            "EKRI/docs ontology exploration/audit and historical validation records not listed as bounded product docs",
            ".EKRI/** runtime state",
            "WFF runtime/install-pack surfaces",
        ],
        "claim_ceiling": (
            "This release pack proves a bounded, source-identified EKRI distribution surface for the declared product version. "
            "Its semantic/product claims are limited by the included release notes and supported product contract. It does not prove "
            "exhaustive engineering knowledge, autonomous governance authority, host production readiness, or production approval."
        ),
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_file(pack_root / MANIFEST_NAME, manifest_bytes)

    archive_path = output_root / f"{pack_name}.zip"
    _build_zip(pack_root, archive_path)

    external_manifest_path = output_root / MANIFEST_NAME
    external_manifest_path.write_bytes(manifest_bytes)
    checksums_path = output_root / CHECKSUMS_NAME
    checksums = (
        f"{_sha256(archive_path.read_bytes())}  {archive_path.name}\n"
        f"{_sha256(manifest_bytes)}  {MANIFEST_NAME}\n"
    )
    checksums_path.write_text(checksums, encoding="utf-8")

    return {
        "pack_root": str(pack_root),
        "archive_path": str(archive_path),
        "manifest_path": str(external_manifest_path),
        "checksums_path": str(checksums_path),
        "version": version,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "packager_revision": packager_revision,
        "included_file_count": len(file_rows),
        "archive_size": archive_path.stat().st_size,
        "archive_sha256": _sha256(archive_path.read_bytes()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an independent EKRI release pack from an exact Git ref")
    parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-root", default="tmp/ekri-release-build")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = build_release_pack(
            repository_root=Path(args.repository_root),
            source_ref=args.source_ref,
            version=args.version,
            output_root=Path(args.output_root),
        )
    except EKRIReleasePackError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
