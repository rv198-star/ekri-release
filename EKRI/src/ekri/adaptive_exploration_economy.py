"""Planned exploration-economy audit for EKRI v1.1.

This audit compares two plans over the exact same WFF v1.9.2 target:

- from-zero: no Project Knowledge is selected;
- reuse-aware: the verified WFF v1.9.2 Project Knowledge Asset v2 is selected.

The report measures reusable question coverage and *planned* source-expansion
ceilings only. It does not claim actual token, time or model-cost savings.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adaptive_exploration import (
    AdaptiveExplorationError,
    CompetencyQuestion,
    _digest,
    assess_knowledge_sufficiency,
    build_mission_context,
    build_mission_exploration_plan,
)


REPORT_SCHEMA_VERSION = "ekri.adaptive-exploration-economy-report.v1"
REPORT_STATUS = "adaptive-exploration-economy-passed"
WFF_V192_ASSET_ID = "wff-v1.9.2-ekri-v1.0"
WFF_V192_COMMIT = "b4f4c383a76fc21df36ef25515325c4b089dcc86"

FAMILY_QUESTIONS = (
    ("architecture", ("native-bounded",), "identify-boundary"),
    ("capability", ("migration-supported-legacy",), "discover-capability-candidates"),
    ("repository-asset-identity", ("native-bounded",), "inspect-state-and-data"),
    ("repository-ownership-boundary", ("native-bounded",), "map-ownership"),
    ("repository-lifecycle-observation", ("native-bounded",), "assess-freshness"),
    ("evolution-impact", ("bounded-overlay",), "assess-freshness"),
    ("flow-handoff", ("derived-conformance",), "trace-flow"),
)


class AdaptiveExplorationEconomyError(RuntimeError):
    """Raised when the v1.1 economy comparison cannot be proven."""


def _questions() -> list[CompetencyQuestion]:
    return [
        CompetencyQuestion(
            question_id=f"CQ-{family_id.upper().replace('-', '_')}",
            question=f"What verified {family_id} knowledge can be reused for this bounded project-takeover mission?",
            decision_relevance=(
                "Reuse exact source-bound Project Knowledge when acceptable; otherwise keep the question as an explicit exploration gap."
            ),
            blocking=True,
            family_requirements=(
                {
                    "family_id": family_id,
                    "acceptable_availability": list(accepted),
                    "freshness_requirement": "exact-target",
                },
            ),
            uncertainty_policy="explore",
        )
        for family_id, accepted, _ in FAMILY_QUESTIONS
    ]


def _operator_by_question() -> dict[str, str]:
    return {
        f"CQ-{family_id.upper().replace('-', '_')}": operator_id
        for family_id, _, operator_id in FAMILY_QUESTIONS
    }


def _build_gap_plan(
    context: Mapping[str, Any],
    sufficiency: Mapping[str, Any],
    *,
    plan_id: str,
) -> dict[str, Any]:
    gap_rows = [
        row
        for row in sufficiency.get("questions", [])
        if isinstance(row, Mapping) and row.get("status") == "requires-exploration"
    ]
    priority_order = [str(row["question_id"]) for row in gap_rows]
    operator_by_question = _operator_by_question()
    rationale = {
        question_id: (
            "This question remains an exact-target gap after mechanically assessing verified Project Knowledge, so one bounded source-expansion slice is planned."
        )
        for question_id in priority_order
    }
    slices: list[dict[str, Any]] = []
    for index, question_id in enumerate(priority_order, start=1):
        slices.append(
            {
                "slice_id": f"slice-{index}",
                "question_ids": [question_id],
                "operator_id": operator_by_question[question_id],
                "scope_refs": ["mission-target"],
                "expected_information_gain": (
                    "Obtain enough exact target evidence to resolve this mission question or preserve an explicit bounded gap."
                ),
                "required_evidence_kinds": ["source-bound-evidence"],
                "slice_budget": {
                    "max_tool_calls": 1,
                    "max_source_expansions": 4,
                    "max_source_bytes": 100_000,
                },
                "success_condition": (
                    "The acquisition loop can route a bounded candidate or explicit uncertainty without broad repository rescanning."
                ),
                "failure_posture": "record-unknown",
            }
        )
    return build_mission_exploration_plan(
        context,
        sufficiency,
        plan_id=plan_id,
        plan_revision=1,
        environment_interpretation=(
            "This economy audit compares only knowledge reuse and planned exploration ceilings; repository path metadata is not interpreted as technology authority."
        ),
        priority_order=priority_order,
        priority_rationale=rationale,
        slices=slices,
    )


def _scenario(
    repository_root: Path,
    *,
    scenario_id: str,
    project_asset_id: str | None,
) -> dict[str, Any]:
    context = build_mission_context(
        repository_root,
        mission_id=f"mission:economy:{scenario_id}",
        mission_summary=(
            "Assess a bounded project-takeover knowledge set while measuring how much existing exact Project Knowledge can avoid planned source expansion."
        ),
        decision_to_support=(
            "Decide which engineering-knowledge questions require new source acquisition before a host Agent continues project work."
        ),
        target_ref=WFF_V192_COMMIT,
        project_asset_id=project_asset_id,
    )
    sufficiency = assess_knowledge_sufficiency(context, _questions())
    plan = _build_gap_plan(
        context,
        sufficiency,
        plan_id=f"plan:economy:{scenario_id}",
    )
    return {
        "scenario_id": scenario_id,
        "project_asset_id": str(project_asset_id or ""),
        "context_fingerprint": context["context_fingerprint"],
        "sufficiency_fingerprint": sufficiency["report_fingerprint"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "reuse": deepcopy(sufficiency["summary"]),
        "planned_slice_count": len(plan["slices"]),
        "planned_budget": deepcopy(plan["budget"]["planned_totals"]),
        "gap_question_ids": [
            str(row["question_id"])
            for row in sufficiency["questions"]
            if row["status"] == "requires-exploration"
        ],
        "reused_question_ids": [
            str(row["question_id"])
            for row in sufficiency["questions"]
            if row["status"] == "sufficient-existing"
        ],
    }


def run_adaptive_exploration_economy_audit(
    repository_root: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve(strict=False)
    baseline = _scenario(root, scenario_id="from-zero", project_asset_id=None)
    adaptive = _scenario(
        root,
        scenario_id="reuse-aware",
        project_asset_id=WFF_V192_ASSET_ID,
    )
    if baseline["reuse"]["reused_existing_question_count"] != 0:
        raise AdaptiveExplorationEconomyError("from-zero baseline unexpectedly reused Project Knowledge")
    if baseline["planned_slice_count"] != len(FAMILY_QUESTIONS):
        raise AdaptiveExplorationEconomyError("from-zero baseline did not plan all knowledge gaps")
    if adaptive["reuse"]["reused_existing_question_count"] < 1:
        raise AdaptiveExplorationEconomyError("reuse-aware scenario did not reuse any Project Knowledge")
    architecture_question = "CQ-ARCHITECTURE"
    if architecture_question not in adaptive["gap_question_ids"]:
        raise AdaptiveExplorationEconomyError(
            "reuse-aware scenario falsely treated blocked Architecture knowledge as sufficient"
        )
    if adaptive["planned_slice_count"] >= baseline["planned_slice_count"]:
        raise AdaptiveExplorationEconomyError("reuse-aware plan did not reduce planned source expansion")

    reduction = {
        "reused_question_delta": (
            adaptive["reuse"]["reused_existing_question_count"]
            - baseline["reuse"]["reused_existing_question_count"]
        ),
        "exploration_gap_reduction": (
            baseline["reuse"]["exploration_gap_question_count"]
            - adaptive["reuse"]["exploration_gap_question_count"]
        ),
        "planned_slice_reduction": baseline["planned_slice_count"] - adaptive["planned_slice_count"],
        "planned_tool_call_ceiling_reduction": (
            baseline["planned_budget"]["max_tool_calls"]
            - adaptive["planned_budget"]["max_tool_calls"]
        ),
        "planned_source_expansion_ceiling_reduction": (
            baseline["planned_budget"]["max_source_expansions"]
            - adaptive["planned_budget"]["max_source_expansions"]
        ),
        "planned_source_byte_ceiling_reduction": (
            baseline["planned_budget"]["max_source_bytes"]
            - adaptive["planned_budget"]["max_source_bytes"]
        ),
    }
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": REPORT_STATUS,
        "authority_mode": "economy-evidence-only",
        "target": {
            "product": "WFF",
            "version": "1.9.2",
            "commit": WFF_V192_COMMIT,
        },
        "question_count": len(FAMILY_QUESTIONS),
        "baseline": baseline,
        "adaptive": adaptive,
        "reduction": reduction,
        "checks": [
            {"check": "same-target-question-set", "status": "passed"},
            {"check": "from-zero-no-reuse", "status": "passed"},
            {"check": "existing-knowledge-reused", "status": "passed"},
            {"check": "blocked-architecture-not-overclaimed", "status": "passed"},
            {"check": "planned-source-expansion-reduced", "status": "passed"},
            {"check": "no-semantic-authority-from-economy-audit", "status": "passed"}
        ],
        "claim_ceiling": (
            "This audit proves only a reduction in planned exploration gaps, slices and caller-declared source/tool ceilings when exact verified Project Knowledge is reused. "
            "It does not measure or claim actual model tokens, wall-clock speed, money saved, project completeness, or semantic correctness beyond the existing EKRI family postures."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_adaptive_exploration_economy_report(report)


def validate_adaptive_exploration_economy_report(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != REPORT_SCHEMA_VERSION or data.get("status") != REPORT_STATUS:
        raise AdaptiveExplorationEconomyError("adaptive exploration economy report is not passed")
    if data.get("authority_mode") != "economy-evidence-only":
        raise AdaptiveExplorationEconomyError("adaptive exploration economy audit attempted authority")
    baseline = data.get("baseline")
    adaptive = data.get("adaptive")
    reduction = data.get("reduction")
    if not isinstance(baseline, Mapping) or not isinstance(adaptive, Mapping) or not isinstance(reduction, Mapping):
        raise AdaptiveExplorationEconomyError("adaptive economy report sections are malformed")
    if int(adaptive.get("planned_slice_count", 0)) >= int(baseline.get("planned_slice_count", 0)):
        raise AdaptiveExplorationEconomyError("adaptive economy report does not prove fewer planned slices")
    if "CQ-ARCHITECTURE" not in adaptive.get("gap_question_ids", []):
        raise AdaptiveExplorationEconomyError("adaptive economy report hides the blocked Architecture gap")
    if any(int(reduction.get(key, 0)) <= 0 for key in (
        "reused_question_delta",
        "exploration_gap_reduction",
        "planned_slice_reduction",
        "planned_tool_call_ceiling_reduction",
        "planned_source_expansion_ceiling_reduction",
        "planned_source_byte_ceiling_reduction",
    )):
        raise AdaptiveExplorationEconomyError("adaptive economy reduction metrics are not all positive")
    checks = data.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks
    ):
        raise AdaptiveExplorationEconomyError("adaptive economy report contains a failed check")
    fingerprint = str(data.get("report_fingerprint") or "")
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationEconomyError("adaptive economy report fingerprint mismatch")
    return data
