"""Heterogeneous conformance and economy proof for EKRI v1.1 adaptive exploration.

The conformance harness intentionally uses small unrelated repository shapes.
It proves that one stable constitution, operator vocabulary, Mission Context,
Knowledge Sufficiency, Plan and bounded WAE loop can adapt without a maintained
technology-stack Profile matrix. Fixture file names are evidence shapes only;
they do not create framework/language semantics.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from .adaptive_exploration import (
    CONSTITUTION_ID,
    OPERATOR_REGISTRY,
    AdaptiveExplorationError,
    _digest,
    assess_knowledge_sufficiency,
    build_mission_context,
    build_mission_exploration_plan,
    collect_git_path_evidence,
    initialize_wae_trace,
    record_wae_iteration,
)


FIXTURE_SCHEMA_VERSION = "ekri.adaptive-exploration-conformance-fixture.v1"
REPORT_SCHEMA_VERSION = "ekri.adaptive-exploration-conformance-report.v1"
REPORT_STATUS = "adaptive-exploration-conformance-passed"


class AdaptiveExplorationConformanceError(RuntimeError):
    """Raised when the bounded v1.1 conformance corpus cannot prove its contract."""


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "specs" / "adaptive-exploration-conformance.json"


def _load_fixture(path: Path | None = None) -> dict[str, Any]:
    selected = path or _fixture_path()
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdaptiveExplorationConformanceError(f"adaptive conformance fixture cannot be read: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise AdaptiveExplorationConformanceError("unsupported adaptive conformance fixture schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise AdaptiveExplorationConformanceError("adaptive conformance requires at least three cases")
    return payload


def _run_git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **dict(env or {})},
    )
    if process.returncode != 0:
        raise AdaptiveExplorationConformanceError(
            f"git {' '.join(args)} failed: {(process.stderr or process.stdout).strip()}"
        )
    return process.stdout.strip()


def _materialize_case(root: Path, case: Mapping[str, Any]) -> tuple[str, str]:
    files = case.get("files")
    if not isinstance(files, Mapping) or not files:
        raise AdaptiveExplorationConformanceError("conformance case requires inline files")
    root.mkdir(parents=True, exist_ok=True)
    for raw_path, raw_content in sorted(files.items()):
        relative = Path(str(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            raise AdaptiveExplorationConformanceError(f"unsafe conformance fixture path: {raw_path}")
        output = root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(str(raw_content), encoding="utf-8")
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.name", "EKRI Conformance")
    _run_git(root, "config", "user.email", "ekri-conformance@example.invalid")
    _run_git(root, "add", ".")
    fixed_env = {
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    }
    _run_git(root, "commit", "-qm", "fixture", env=fixed_env)
    return _run_git(root, "rev-parse", "HEAD^{commit}"), _run_git(root, "rev-parse", "HEAD^{tree}")


def _questions(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = case.get("questions")
    if not isinstance(rows, list) or not rows:
        raise AdaptiveExplorationConformanceError("conformance case requires competency questions")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _build_case_plan(
    context: Mapping[str, Any],
    sufficiency: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    plan_spec = case.get("plan")
    if not isinstance(plan_spec, Mapping):
        raise AdaptiveExplorationConformanceError("conformance case requires plan specification")
    priority = [str(value) for value in plan_spec.get("priority_order", [])]
    operators = [str(value) for value in plan_spec.get("operators", [])]
    evidence_paths = [str(value) for value in plan_spec.get("evidence_paths", [])]
    if not priority or not (len(priority) == len(operators) == len(evidence_paths)):
        raise AdaptiveExplorationConformanceError(
            "conformance plan priority/operator/evidence lists must be aligned and non-empty"
        )
    slices: list[dict[str, Any]] = []
    rationale: dict[str, str] = {}
    for index, (question_id, operator_id, evidence_path) in enumerate(
        zip(priority, operators, evidence_paths, strict=True),
        start=1,
    ):
        rationale[question_id] = (
            "The mission marks this as a blocking knowledge gap and the selected generic operator "
            "targets the smallest evidence surface declared by the fixture."
        )
        slices.append(
            {
                "slice_id": f"slice-{index}",
                "question_ids": [question_id],
                "operator_id": operator_id,
                "scope_refs": [evidence_path],
                "expected_information_gain": (
                    "Acquire exact source evidence sufficient to resolve the mission question at the acquisition layer "
                    "or preserve it explicitly as unknown/conflicting."
                ),
                "required_evidence_kinds": ["git-blob"],
                "slice_budget": {
                    "max_tool_calls": 2,
                    "max_source_expansions": 2,
                    "max_source_bytes": 100_000,
                },
                "success_condition": (
                    "The WAE round has exact source evidence and can make an explicit acquisition-level reconciliation "
                    "without creating semantic authority."
                ),
                "failure_posture": "record-unknown",
            }
        )
    return build_mission_exploration_plan(
        context,
        sufficiency,
        plan_id=f"plan:{case['case_id']}",
        plan_revision=1,
        environment_interpretation=str(plan_spec.get("environment_interpretation") or ""),
        priority_order=priority,
        priority_rationale=rationale,
        slices=slices,
    )


def _execute_case(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    commit, tree = _materialize_case(root, case)
    mission = case.get("mission")
    if not isinstance(mission, Mapping):
        raise AdaptiveExplorationConformanceError("conformance case requires mission")
    context = build_mission_context(
        root,
        mission_id=f"mission:{case['case_id']}",
        mission_summary=str(mission.get("summary") or ""),
        decision_to_support=str(mission.get("decision_to_support") or ""),
        target_ref="HEAD",
        project_asset_id=None,
    )
    if context["target"]["commit"] != commit or context["target"]["tree"] != tree:
        raise AdaptiveExplorationConformanceError("conformance context target identity mismatch")
    sufficiency = assess_knowledge_sufficiency(context, _questions(case))
    if sufficiency["summary"]["reused_existing_question_count"] != 0:
        raise AdaptiveExplorationConformanceError("fixture without Project Knowledge unexpectedly reused knowledge")
    plan = _build_case_plan(context, sufficiency, case)
    trace = initialize_wae_trace(context, sufficiency, plan)
    receipts: list[dict[str, Any]] = []
    for index, slice_row in enumerate(plan["slices"]):
        evidence_path = slice_row["scope_refs"][0]
        receipt = collect_git_path_evidence(
            root,
            context,
            sufficiency,
            plan,
            slice_id=slice_row["slice_id"],
            operator_id=slice_row["operator_id"],
            paths=[evidence_path],
        )
        receipts.append(receipt)
        final = index == len(plan["slices"]) - 1
        trace = record_wae_iteration(
            trace,
            context,
            sufficiency,
            plan,
            slice_id=slice_row["slice_id"],
            evidence_receipts=[receipt],
            challenge_findings=[
                {
                    "finding_id": f"finding-{index + 1}",
                    "posture": "supports",
                    "detail": (
                        "The exact target blob materially answers the bounded acquisition question while remaining "
                        "non-authoritative engineering evidence."
                    ),
                    "evidence_receipt_fingerprints": [receipt["receipt_fingerprint"]],
                }
            ],
            reconciliation={
                "outcome": "inferred-candidate",
                "rationale": (
                    "The mission has enough exact evidence to resolve this acquisition question without asserting "
                    "that the evidence alone is semantic truth."
                ),
                "question_status_updates": {
                    question_id: "resolved" for question_id in slice_row["question_ids"]
                },
                "candidate_family_ids": [],
            },
            material_gain=(
                "One blocking question is resolved from a bounded exact source read rather than broad project exploration."
            ),
            next_action="converge" if final else "continue",
            stop_or_return_reason="mission-sufficient" if final else "",
            why_next_action=(
                "All blocking questions are resolved; broad re-exploration would add no mission value."
                if final
                else "Additional blocking questions remain, so the next planned bounded slice is justified."
            ),
        )
    if trace["status"] != "exploration-converged":
        raise AdaptiveExplorationConformanceError("conformance WAE trace did not converge")
    if any(state != "resolved" for state in trace["question_states"].values()):
        raise AdaptiveExplorationConformanceError("conformance WAE left unresolved question states")
    return {
        "case_id": str(case["case_id"]),
        "source": {"commit": commit, "tree": tree},
        "mission_context_fingerprint": context["context_fingerprint"],
        "repository_environment_fingerprint": context["repository_environment"][
            "visible_path_set_sha256"
        ],
        "constitution_id": context["constitution"]["constitution_id"],
        "operator_ids": [row["operator_id"] for row in plan["slices"]],
        "question_count": sufficiency["summary"]["question_count"],
        "planned_slice_count": len(plan["slices"]),
        "iteration_count": len(trace["iterations"]),
        "usage": deepcopy(trace["usage"]),
        "final_status": trace["status"],
        "trace_fingerprint": trace["trace_fingerprint"],
    }


def run_adaptive_exploration_conformance(
    *,
    fixture_path: Path | None = None,
) -> dict[str, Any]:
    fixture = _load_fixture(fixture_path)
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ekri-adaptive-conformance-") as temp_root:
        base = Path(temp_root)
        for raw_case in fixture["cases"]:
            if not isinstance(raw_case, Mapping):
                raise AdaptiveExplorationConformanceError("conformance case must be an object")
            cases.append(_execute_case(raw_case, base / str(raw_case.get("case_id") or "case")))
    constitution_ids = {row["constitution_id"] for row in cases}
    if constitution_ids != {CONSTITUTION_ID}:
        raise AdaptiveExplorationConformanceError("heterogeneous cases did not share one exploration constitution")
    operator_registry_fingerprint = _digest(list(OPERATOR_REGISTRY))
    distinct_operator_sets = {tuple(row["operator_ids"]) for row in cases}
    if len(distinct_operator_sets) < 3:
        raise AdaptiveExplorationConformanceError("heterogeneous cases did not adapt operator selection")
    profile_root = Path(__file__).resolve().parents[2] / "profiles"
    if profile_root.exists():
        raise AdaptiveExplorationConformanceError(
            "EKRI adaptive exploration must not require a technology-stack profiles directory"
        )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": REPORT_STATUS,
        "authority_mode": "conformance-evidence-only",
        "fixture_schema_version": fixture["schema_version"],
        "fixture_fingerprint": _digest(fixture),
        "constitution_id": CONSTITUTION_ID,
        "operator_registry_fingerprint": operator_registry_fingerprint,
        "case_count": len(cases),
        "cases": cases,
        "checks": [
            {"check": "single-constitution", "status": "passed"},
            {"check": "generic-operator-vocabulary", "status": "passed"},
            {"check": "heterogeneous-operator-selection", "status": "passed"},
            {"check": "no-technology-profile-directory", "status": "passed"},
            {"check": "bounded-source-evidence", "status": "passed"},
            {"check": "wae-convergence", "status": "passed"},
            {"check": "no-semantic-authority-from-conformance", "status": "passed"}
        ],
        "claim_ceiling": (
            "This conformance proves only that one EKRI adaptive-acquisition constitution, plan contract, generic operator vocabulary "
            "and bounded WAE loop can execute different mission/project shapes without a maintained technology-stack Profile matrix. "
            "It does not prove technology understanding, exhaustive project knowledge, semantic correctness of fixture interpretations, or production behavior."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_adaptive_exploration_conformance(report)


def validate_adaptive_exploration_conformance(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != REPORT_SCHEMA_VERSION or data.get("status") != REPORT_STATUS:
        raise AdaptiveExplorationConformanceError("adaptive exploration conformance report is not passed")
    if data.get("authority_mode") != "conformance-evidence-only":
        raise AdaptiveExplorationConformanceError("adaptive conformance attempted semantic authority")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise AdaptiveExplorationConformanceError("adaptive conformance report lost heterogeneous cases")
    if any(row.get("final_status") != "exploration-converged" for row in cases if isinstance(row, Mapping)):
        raise AdaptiveExplorationConformanceError("adaptive conformance contains a non-converged case")
    checks = data.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks
    ):
        raise AdaptiveExplorationConformanceError("adaptive conformance contains a failed check")
    fingerprint = str(data.get("report_fingerprint") or "")
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationConformanceError("adaptive conformance report fingerprint mismatch")
    return data
