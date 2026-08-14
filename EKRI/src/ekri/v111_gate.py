"""EKRI v1.1.1 hotfix release gate for the official Skill surface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Any, Mapping

from .observation_boundary import ObservationBoundaryError, resolve_scanner_identity
from .skill_surface import EKRISkillSurfaceError, SKILL_NAMES, validate_skill_surface
from .version_compatibility import (
    VersionCompatibilityError,
    check_version_compatibility,
    load_version_compatibility,
)
from .v100_release_gate import (
    M0_METRICS,
    _current_metrics,
    _verify_peer_authority,
    _verify_retirement,
    _verify_writer_inventory,
)
from .v110_gate import _acquisition_boundary


GATE_SCHEMA_VERSION = "ekri.v111-release-gate.v1"
GATE_STATUS = "v111-release-candidate-ready"
PRODUCT_VERSION = "1.1.1"
V100_TAG = "ekri/v1.0.0"
V100_SOURCE = "026f2ffa5c3c8685418adc4bf281911b4ff2d578"
V110_TAG = "ekri/v1.1.0"
V110_SOURCE = "d45dc12d0777d5c7f6651f3564dea63b1dded8a6"
V111_BASE_SOURCE = "5592672c0e126dd343b615f1430c2c75cd59d8e8"
V111_TAG = "ekri/v1.1.1"
ALLOWED_SRC_CHANGES = frozenset(
    {
        "EKRI/src/ekri/skill_surface.py",
        "EKRI/src/ekri/v110_gate.py",
        "EKRI/src/ekri/v111_gate.py",
        "EKRI/src/ekri/version_compatibility.py",
    }
)


class V111GateError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise V111GateError(f"git {' '.join(args)} failed: {(process.stderr or process.stdout).strip()}")
    return process.stdout.strip()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V111GateError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise V111GateError(f"{label} must be an object")
    return value


def _product_metadata(ekri_root: Path) -> dict[str, Any]:
    try:
        pyproject = tomllib.loads((ekri_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise V111GateError(f"pyproject cannot be read: {exc}") from exc
    version = str(pyproject.get("project", {}).get("version") or "")
    if version != PRODUCT_VERSION:
        raise V111GateError(f"EKRI product version is not {PRODUCT_VERSION}: {version}")
    required = [
        ekri_root / "CHANGELOG.md",
        ekri_root / "docs" / "releases" / "v1.1.1.md",
        ekri_root / "specs" / "v111-skill-surface-classification.json",
        ekri_root / "scripts" / "install_ekri_skills.py",
        ekri_root / "scripts" / "check_version_compatibility.py",
        ekri_root / "specs" / "version-compatibility.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise V111GateError("required v1.1.1 product records missing: " + ", ".join(missing))
    if "## [1.1.1] - 2026-08-14" not in (ekri_root / "CHANGELOG.md").read_text(encoding="utf-8"):
        raise V111GateError("CHANGELOG lacks the v1.1.1 release entry")
    classification = _read_json(
        ekri_root / "specs" / "v111-skill-surface-classification.json",
        "v1.1.1 Skill classification",
    )
    if classification.get("schema_version") != "ekri.v111-skill-surface-classification.v1":
        raise V111GateError("unsupported v1.1.1 Skill classification schema")
    if classification.get("product_version") != PRODUCT_VERSION:
        raise V111GateError("v1.1.1 Skill classification product version mismatch")
    if classification.get("semantic_change") is not False:
        raise V111GateError("v1.1.1 Skill hotfix attempted a semantic product change")
    if classification.get("consumer") != "ai-agent":
        raise V111GateError("v1.1.1 Skills must be classified as AI-Agent-facing")
    access = classification.get("target_project_access")
    if not isinstance(access, Mapping) or access.get("default") != "read-only":
        raise V111GateError("v1.1.1 Skills must default to read-only target-project access")
    persistence = access.get("authorized_knowledge_persistence")
    if not isinstance(persistence, Mapping):
        raise V111GateError("v1.1.1 authorized knowledge-persistence contract is missing")
    if persistence.get("requires_explicit_user_authorization") is not True:
        raise V111GateError("v1.1.1 knowledge persistence must require explicit user authorization")
    if persistence.get("allowed_path") != ".EKRI/project/**":
        raise V111GateError("v1.1.1 knowledge persistence path must remain .EKRI/project/**")
    if persistence.get("recommend_git_tracking") is not True:
        raise V111GateError("v1.1.1 persisted project knowledge must recommend Git tracking")
    classified = [
        str(row.get("name") or "")
        for row in classification.get("skills", [])
        if isinstance(row, Mapping)
    ]
    if classified != list(SKILL_NAMES):
        raise V111GateError("v1.1.1 Skill classification does not match the official Skill set")
    return {
        "version": version,
        "release_notes": "EKRI/docs/releases/v1.1.1.md",
        "skill_classification": "EKRI/specs/v111-skill-surface-classification.json",
    }


def _skill_surface(ekri_root: Path) -> dict[str, Any]:
    try:
        rows = validate_skill_surface(ekri_root)
    except EKRISkillSurfaceError as exc:
        raise V111GateError(str(exc)) from exc
    installer = ekri_root / "scripts" / "install_ekri_skills.py"
    if not installer.is_file():
        raise V111GateError("EKRI Skill installer is missing")
    text = installer.read_text(encoding="utf-8")
    for required in ("--list", "--check", "--target-dir", "--force"):
        if required not in text:
            raise V111GateError(f"EKRI Skill installer lacks required option: {required}")
    texts = {
        row["name"]: (ekri_root / "skills" / row["name"] / "SKILL.md").read_text(encoding="utf-8")
        for row in rows
    }
    forbidden_write_commands = (
        "manage_project_assets.py promote",
        "manage_project_assets.py hydrate",
        "git commit",
        "git add",
    )
    for name, skill_text in texts.items():
        if "AI Agent" not in skill_text and "AI Agent" not in skill_text.replace("AI-Agent", "AI Agent"):
            raise V111GateError(f"EKRI Skill does not declare AI Agent audience: {name}")
        if "修改目标项目源码" not in skill_text:
            raise V111GateError(f"EKRI Skill lacks target-project write boundary: {name}")
        hits = [token for token in forbidden_write_commands if token in skill_text]
        if hits:
            raise V111GateError(f"EKRI Skill contains forbidden target-project write command ({name}): {', '.join(hits)}")
    for name in ("using-ekri", "ekri-init", "ekri-refresh"):
        if ".EKRI/project/**" not in texts[name] or "明确授权" not in texts[name]:
            raise V111GateError(f"EKRI Skill lacks authorized knowledge-persistence boundary: {name}")
    if ".EKRI/project/**" not in texts["ekri-query"] or "严格只读" not in texts["ekri-query"]:
        raise V111GateError("ekri-query must remain strictly read-only")
    return {
        "skill_count": len(rows),
        "skill_names": [row["name"] for row in rows],
        "installer": "EKRI/scripts/install_ekri_skills.py",
        "installation_unit": "complete-skill-directory",
        "consumer": "ai-agent",
        "target_project_default_access": "read-only",
        "authorized_knowledge_persistence_path": ".EKRI/project/**",
        "semantic_authority": False,
    }


def _compatibility_surface() -> dict[str, Any]:
    try:
        spec = load_version_compatibility()
        same_line = check_version_compatibility("1.1.0", "1.1.1")
        prior_line = check_version_compatibility("1.0.0", "1.1.1")
    except VersionCompatibilityError as exc:
        raise V111GateError(str(exc)) from exc
    if same_line.get("status") != "fully-compatible" or same_line.get("fully_compatible") is not True:
        raise V111GateError("v1.1.0 and v1.1.1 must remain in the same Project Knowledge layout generation")
    if prior_line.get("status") != "not-fully-compatible" or prior_line.get("fully_compatible") is not False:
        raise V111GateError("v1.0.0 and v1.1.1 must remain separated by the Project Knowledge layout change")
    current = [
        row
        for row in spec.get("generations", [])
        if isinstance(row, Mapping) and row.get("status") == "current-compatible-line"
    ]
    if len(current) != 1:
        raise V111GateError("version compatibility list must declare exactly one current generation")
    row = current[0]
    if row.get("generation_id") != "project-knowledge-layout-g2":
        raise V111GateError("current Project Knowledge compatibility generation drifted")
    if row.get("current_asset_schema") != "ekri.project-knowledge-asset.v2":
        raise V111GateError("v1.1.1 current Project Knowledge asset schema drifted")
    if list(row.get("versions", [])) != ["1.1.0", "1.1.1"]:
        raise V111GateError("v1.1.x compatibility version list drifted")
    return {
        "generation_id": row["generation_id"],
        "current_asset_schema": row["current_asset_schema"],
        "supported_asset_schemas": list(row.get("supported_asset_schemas", [])),
        "compatible_versions": list(row.get("versions", [])),
        "v110_v111": same_line["status"],
        "v100_v111": prior_line["status"],
        "compatibility_spec": "EKRI/specs/version-compatibility.json",
    }


def _semantic_baseline(ekri_root: Path) -> dict[str, Any]:
    try:
        writers = _verify_writer_inventory(ekri_root)
        retirement = _verify_retirement(ekri_root)
        peer_authority = _verify_peer_authority()
        metrics = _current_metrics(ekri_root)
    except Exception as exc:
        raise V111GateError(f"v1.1 semantic baseline invariant failed: {exc}") from exc
    if len(writers) != M0_METRICS["major_semantic_writer_paths"]:
        raise V111GateError("v1.1.1 changed the major semantic writer denominator")
    if metrics["primary_semantic_output_families"] != M0_METRICS["primary_semantic_output_families"]:
        raise V111GateError("v1.1.1 changed the semantic output-family denominator")
    acquisition = _acquisition_boundary(ekri_root)
    return {
        "major_writer_path_count": len(writers),
        "primary_family_count": metrics["primary_semantic_output_families"],
        "peer_authority": peer_authority,
        "retirement": retirement,
        "adaptive_acquisition": acquisition,
    }


def _distribution_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "EKRI_RELEASE_PACK_MANIFEST.json"
    if not path.is_file():
        return None
    manifest = _read_json(path, "release-pack manifest")
    if manifest.get("product") != "EKRI" or manifest.get("version") != PRODUCT_VERSION:
        raise V111GateError("release-pack manifest does not identify EKRI v1.1.1")
    source_ref = str(manifest.get("source_ref") or "")
    if source_ref != V111_TAG and source_ref != "HEAD":
        raise V111GateError(
            "v1.1.1 release-pack manifest source_ref must be HEAD for a candidate or ekri/v1.1.1 for the formal release"
        )
    return manifest


def _version_invariants(root: Path, *, distribution: bool) -> dict[str, Any]:
    if distribution:
        manifest = _distribution_manifest(root)
        assert manifest is not None
        return {
            "mode": "distribution-manifest",
            "v100_source": "not-locally-resolvable",
            "v110_source": "not-locally-resolvable",
            "v111_release_tag": V111_TAG,
            "v111_release_tag_exists": False,
            "source_revision": str(manifest.get("source_revision") or ""),
        }

    resolved_v100 = _git(root, "rev-parse", f"{V100_TAG}^{{commit}}")
    resolved_v110 = _git(root, "rev-parse", f"{V110_TAG}^{{commit}}")
    if resolved_v100 != V100_SOURCE:
        raise V111GateError("published EKRI v1.0.0 tag/source identity changed")
    if resolved_v110 != V110_SOURCE:
        raise V111GateError("published EKRI v1.1.0 tag/source identity changed")
    if _git(root, "tag", "--list", V111_TAG):
        raise V111GateError("v1.1.1 source Gate must run before publication")
    return {
        "mode": "source-repository",
        "v100_source": resolved_v100,
        "v110_source": resolved_v110,
        "v111_release_tag": V111_TAG,
        "v111_release_tag_exists": False,
    }


def _scope_audit(root: Path, *, distribution: bool) -> dict[str, Any]:
    if distribution:
        files = [
            line
            for line in _git(root, "ls-files").splitlines()
            if line
        ]
        allowed_root = {".gitignore", "README.md", "EKRI_RELEASE_PACK_MANIFEST.json"}
        forbidden = sorted(
            path
            for path in files
            if not path.startswith("EKRI/") and path not in allowed_root
        )
        if forbidden:
            raise V111GateError(
                "v1.1.1 distribution contains unexpected non-EKRI payload: " + ", ".join(forbidden[:20])
            )
        return {
            "mode": "distribution-boundary",
            "tracked_path_count": len(files),
            "unexpected_paths": forbidden,
        }

    parents = _git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parents) == 3:
        candidate_paths = [
            line
            for line in _git(root, "diff", "--name-only", f"{parents[1]}..HEAD").splitlines()
            if line
        ]
        if "EKRI/docs/releases/v1.1.1.md" in candidate_paths:
            base = parents[1]
            mode = "merge-commit-pr-delta"
            changed = candidate_paths
        else:
            base = V111_BASE_SOURCE
            mode = "candidate-branch-delta"
            changed = [
                line
                for line in _git(root, "diff", "--name-only", f"{base}..HEAD").splitlines()
                if line
            ]
    else:
        base = V111_BASE_SOURCE
        mode = "candidate-branch-delta"
        changed = [
            line
            for line in _git(root, "diff", "--name-only", f"{base}..HEAD").splitlines()
            if line
        ]
    non_ekri = sorted(path for path in changed if not path.startswith("EKRI/"))
    if non_ekri:
        raise V111GateError("v1.1.1 scope changed non-EKRI paths: " + ", ".join(non_ekri[:20]))
    changed_src = sorted(path for path in changed if path.startswith("EKRI/src/ekri/"))
    forbidden_src = sorted(set(changed_src) - ALLOWED_SRC_CHANGES)
    if forbidden_src:
        raise V111GateError(
            "v1.1.1 hotfix changed semantic/runtime source outside the Skill/Gate surface: "
            + ", ".join(forbidden_src[:20])
        )
    return {
        "mode": mode,
        "base_source": base,
        "changed_path_count": len(changed),
        "non_ekri_changed_paths": non_ekri,
        "changed_src_paths": changed_src,
        "forbidden_src_paths": forbidden_src,
    }


def run_v111_release_gate(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    ekri_root = root / "EKRI"
    if not ekri_root.is_dir():
        raise V111GateError("repository root does not contain top-level EKRI")
    try:
        scanner = resolve_scanner_identity()
    except ObservationBoundaryError as exc:
        raise V111GateError(f"v1.1.1 Gate requires exact clean scanner identity: {exc}") from exc
    source_commit = _git(root, "rev-parse", "HEAD^{commit}")
    source_tree = _git(root, "rev-parse", "HEAD^{tree}")
    if scanner.commit != source_commit or scanner.tree != source_tree or not scanner.runtime_matches_commit:
        raise V111GateError("v1.1.1 scanner/runtime/source identities diverge")

    distribution = _distribution_manifest(root) is not None
    product = _product_metadata(ekri_root)
    skills = _skill_surface(ekri_root)
    semantic = _semantic_baseline(ekri_root)
    compatibility = _compatibility_surface()
    versions = _version_invariants(root, distribution=distribution)
    scope = _scope_audit(root, distribution=distribution)

    checks = [
        {"check": "exact-scanner-source-identity", "status": "passed"},
        {"check": "official-four-skill-surface", "status": "passed"},
        {"check": "skill-installer-contract", "status": "passed"},
        {"check": "skill-target-project-read-only-boundary", "status": "passed"},
        {"check": "project-knowledge-version-compatibility-list", "status": "passed"},
        {"check": "semantic-writer-denominator-unchanged", "status": "passed"},
        {"check": "semantic-family-denominator-unchanged", "status": "passed"},
        {"check": "adaptive-acquisition-authority-preserved", "status": "passed"},
        {"check": "v100-v110-release-identities-preserved", "status": "passed"},
        {"check": "hotfix-scope-ekri-only", "status": "passed"},
    ]
    report: dict[str, Any] = {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": GATE_STATUS,
        "authority_mode": "release-evidence-only",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "scanner_commit": scanner.commit,
            "scanner_tree": scanner.tree,
            "runtime_matches_commit": scanner.runtime_matches_commit,
        },
        "product": product,
        "skills": skills,
        "semantic_baseline": semantic,
        "compatibility": compatibility,
        "versions": versions,
        "scope": scope,
        "checks": checks,
        "claim_ceiling": (
            "This Gate proves a bounded EKRI v1.1.1 hotfix that restores the official packaged four-Skill AI-Agent entry surface and installer, enforces read-only target-project behavior except explicitly authorized .EKRI/project knowledge persistence, and records Project Knowledge layout compatibility while preserving the v1.1 semantic writer/family and Adaptive Knowledge Acquisition authority boundaries. It does not prove universal Agent-platform compatibility, exhaustive project knowledge, autonomous semantic acceptance, refactoring correctness, UAT or production readiness."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_v111_release_gate_report(report)


def validate_v111_release_gate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    if report.get("schema_version") != GATE_SCHEMA_VERSION or report.get("status") != GATE_STATUS:
        raise V111GateError("v1.1.1 Gate report identity is invalid")
    if report.get("authority_mode") != "release-evidence-only":
        raise V111GateError("v1.1.1 Gate attempted semantic authority")
    skills = report.get("skills")
    if not isinstance(skills, Mapping) or list(skills.get("skill_names", [])) != list(SKILL_NAMES):
        raise V111GateError("v1.1.1 Gate Skill surface drifted")
    if skills.get("semantic_authority") is not False:
        raise V111GateError("v1.1.1 Skills attempted semantic authority")
    if skills.get("consumer") != "ai-agent" or skills.get("target_project_default_access") != "read-only":
        raise V111GateError("v1.1.1 Skill consumer/read-only boundary drifted")
    if skills.get("authorized_knowledge_persistence_path") != ".EKRI/project/**":
        raise V111GateError("v1.1.1 authorized knowledge-persistence path drifted")
    compatibility = report.get("compatibility")
    if not isinstance(compatibility, Mapping):
        raise V111GateError("v1.1.1 compatibility evidence is missing")
    if compatibility.get("generation_id") != "project-knowledge-layout-g2":
        raise V111GateError("v1.1.1 compatibility generation drifted")
    if compatibility.get("compatible_versions") != ["1.1.0", "1.1.1"]:
        raise V111GateError("v1.1.1 compatibility version list drifted")
    if compatibility.get("v110_v111") != "fully-compatible" or compatibility.get("v100_v111") != "not-fully-compatible":
        raise V111GateError("v1.1.1 compatibility judgment drifted")
    semantic = report.get("semantic_baseline")
    if not isinstance(semantic, Mapping):
        raise V111GateError("v1.1.1 semantic baseline is missing")
    if semantic.get("major_writer_path_count") != 6 or semantic.get("primary_family_count") != 7:
        raise V111GateError("v1.1.1 semantic writer/family denominator drifted")
    acquisition = semantic.get("adaptive_acquisition")
    if not isinstance(acquisition, Mapping) or acquisition.get("persistent_truth_store") is not False:
        raise V111GateError("v1.1.1 Adaptive Knowledge Acquisition boundary drifted")
    checks = report.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks
    ):
        raise V111GateError("v1.1.1 Gate contains a failed check")
    fingerprint = str(report.get("report_fingerprint") or "")
    expected = _digest({key: value for key, value in report.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise V111GateError("v1.1.1 Gate fingerprint mismatch")
    return report
