"""Mission-oriented adaptive knowledge acquisition for EKRI v1.1.

The v1.1 acquisition layer is deliberately non-authoritative. It helps a host
Agent reuse existing Project Knowledge, identify mission-scoped gaps, author a
bounded exploration plan and record WAE-style acquisition iterations. It never
creates semantic truth merely because a plan, collector or structural tool
reported something.

Durable EKRI knowledge semantics remain owned by the existing family authority
paths. This module owns only source-bound acquisition control records.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .observation_boundary import (
    PROTECTED_PATH_PREFIXES,
    ObservationBoundaryError,
    _run_git,
    _tree_entries,
    resolve_git_target,
)
from .project_assets import ProjectAssetError, VerifiedProjectAsset
from .project_assets_v2 import VerifiedProjectAssetV2, verify_project_asset_any


CONSTITUTION_ID = "ekri.adaptive-exploration-constitution.v1"
MISSION_CONTEXT_SCHEMA_VERSION = "ekri.mission-context.v1"
SUFFICIENCY_SCHEMA_VERSION = "ekri.knowledge-sufficiency-report.v1"
PLAN_SCHEMA_VERSION = "ekri.mission-exploration-plan.v1"
EVIDENCE_RECEIPT_SCHEMA_VERSION = "ekri.acquisition-evidence-receipt.v1"
WAE_TRACE_SCHEMA_VERSION = "ekri.adaptive-exploration-wae-trace.v1"
CANDIDATE_DELTA_SCHEMA_VERSION = "ekri.candidate-knowledge-delta.v1"
ROUTING_DECISION_SCHEMA_VERSION = "ekri.candidate-authority-routing-decision.v1"
ACQUISITION_AUTHORITY_MODE = "acquisition-non-authoritative"
MATERIALIZATION_CLASS = "ephemeral-rebuildable-control-record"

DEFAULT_BUDGET = {
    "max_iterations": 6,
    "max_slices": 8,
    "max_tool_calls": 32,
    "max_source_expansions": 64,
    "max_source_bytes": 2_000_000,
}

BUDGET_KEYS = tuple(DEFAULT_BUDGET)
SLICE_BUDGET_KEYS = ("max_tool_calls", "max_source_expansions", "max_source_bytes")
FRESHNESS_REQUIREMENTS = frozenset({"exact-target", "allow-source-bound-stale"})
UNCERTAINTY_POLICIES = frozenset({"explore", "carry-review-bound", "block"})
PLAN_FAILURE_POSTURES = frozenset(
    {"record-unknown", "record-conflicting", "return-remediate", "block"}
)
PLAN_STOP_CONDITIONS = frozenset(
    {
        "mission-sufficient",
        "budget-exhausted",
        "blocked-by-authority",
        "blocked-by-missing-evidence",
        "conflict-requires-owner",
        "source-context-changed",
    }
)
MANDATORY_STOP_CONDITIONS = frozenset(
    {"mission-sufficient", "budget-exhausted", "source-context-changed"}
)
WAE_CHALLENGE_POSTURES = frozenset(
    {"supports", "contradicts", "uncertain", "authority-risk", "scope-risk"}
)
WAE_RECONCILIATION_OUTCOMES = frozenset(
    {"accept-candidate", "inferred-candidate", "preserve-unknown", "preserve-conflicting", "reject", "defer"}
)
WAE_NEXT_ACTIONS = frozenset(
    {"continue", "replan", "converge", "return-remediate", "blocked"}
)
QUESTION_RUNTIME_STATES = frozenset(
    {"satisfied-existing", "unresolved", "resolved", "review-bound", "unknown", "conflicting", "blocked", "deferred"}
)
CANDIDATE_KNOWLEDGE_STATES = frozenset(
    {"observed-fact", "inferred-knowledge", "unknown", "conflicting"}
)
CANDIDATE_ACTIONS = frozenset(
    {"refresh-existing-family", "extend-existing-family", "reconcile-conflict", "record-unknown", "no-change"}
)
FAMILY_AUTHORITY_ROUTES = {
    "architecture": "architecture-reconstruction-authority-path",
    "capability": "capability-semantic-authority",
    "repository-asset-identity": "repository-asset-identity-authority",
    "repository-ownership-boundary": "repository-ownership-boundary-authority",
    "repository-lifecycle-observation": "repository-lifecycle-observation-authority",
    "evolution-impact": "evolution-impact-authority",
    "flow-handoff": "derived-only-no-truth-store",
}
V1_LEGACY_AVAILABILITY = "legacy-v1-verified"

EXPLORATION_CONSTITUTION = (
    {
        "rule_id": "reuse-existing-knowledge-first",
        "rule": "Existing verified Project Knowledge must be assessed before source expansion is planned.",
    },
    {
        "rule_id": "exact-source-context",
        "rule": "Every mission and evidence receipt must bind an exact immutable Git commit/tree context.",
    },
    {
        "rule_id": "miss-is-not-absence",
        "rule": "Search, graph or collector misses cannot establish semantic absence or safe deletion.",
    },
    {
        "rule_id": "structure-is-not-authority",
        "rule": "Imports, calls, references and other structural observations cannot create semantic ownership or architecture authority.",
    },
    {
        "rule_id": "preserve-uncertainty",
        "rule": "Unknown and conflicting knowledge must remain explicit rather than being silently collapsed into certainty.",
    },
    {
        "rule_id": "plan-is-non-authoritative",
        "rule": "Mission plans, operators, collectors and WAE traces are acquisition controls only and cannot write semantic truth directly.",
    },
    {
        "rule_id": "bounded-deepening",
        "rule": "Exploration must be budget-bounded with explicit continue, return and stop conditions; later iterations should integrate rather than reopen broad scope.",
    },
    {
        "rule_id": "family-authority-promotion",
        "rule": "Candidate knowledge may enter durable EKRI truth only through an existing or explicitly versioned family authority path with evidence/claim validation.",
    },
)

OPERATOR_REGISTRY = (
    {
        "operator_id": "query-existing-knowledge",
        "purpose": "Resolve mission questions through existing named EKRI Project Knowledge queries before source expansion.",
        "output_posture": "derived-query-answer",
        "forbidden_claims": ["absence-proof", "new-semantic-authority"],
    },
    {
        "operator_id": "identify-boundary",
        "purpose": "Acquire evidence about system, repository, execution or deployment boundaries relevant to the mission.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["complete-system-boundary", "architecture-authority"],
    },
    {
        "operator_id": "discover-entrypoints",
        "purpose": "Find candidate request, event, CLI, job or other execution entrypoints without assuming technology-specific semantics.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["complete-entrypoint-inventory", "capability-authority"],
    },
    {
        "operator_id": "discover-capability-candidates",
        "purpose": "Locate evidence that may realize or constrain a requested engineering capability.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["capability-existence-authority", "absence-proof"],
    },
    {
        "operator_id": "inspect-contracts",
        "purpose": "Inspect explicit interfaces, schemas, events and cross-boundary contracts relevant to a mission question.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["runtime-success", "consumer-completeness"],
    },
    {
        "operator_id": "inspect-state-and-data",
        "purpose": "Inspect state, persistence, schema, resource or data-flow evidence relevant to the mission.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["domain-authority", "complete-data-lineage"],
    },
    {
        "operator_id": "trace-flow",
        "purpose": "Trace bounded execution or handoff evidence using existing Flow semantics and source observations.",
        "output_posture": "derived-flow-candidate",
        "forbidden_claims": ["historical-occurrence-truth", "complete-runtime-trace"],
    },
    {
        "operator_id": "map-ownership",
        "purpose": "Acquire bounded owner evidence and structural neighborhoods while preserving unresolved and multi-owner posture.",
        "output_posture": "candidate-evidence",
        "forbidden_claims": ["owner-from-topology", "safe-move-authority"],
    },
    {
        "operator_id": "expand-structural-neighborhood",
        "purpose": "Collect bounded import, call, reference, test or resource candidates around a named mission frontier.",
        "output_posture": "structural-candidate-only",
        "forbidden_claims": ["dependency-completeness", "absence-proof", "safe-deletion"],
    },
    {
        "operator_id": "assess-freshness",
        "purpose": "Compare knowledge source identity with the mission target and identify stale or changed knowledge surfaces.",
        "output_posture": "source-context-assessment",
        "forbidden_claims": ["semantic-change-proof"],
    },
    {
        "operator_id": "locate-unknowns-and-conflicts",
        "purpose": "Surface explicit unknown, conflicting, blocked or review-bound knowledge that may affect the mission.",
        "output_posture": "derived-gap-assessment",
        "forbidden_claims": ["automatic-conflict-resolution"],
    },
)


class AdaptiveExplorationError(RuntimeError):
    """Raised when an adaptive acquisition control record violates v1.1 rules."""


@dataclass(frozen=True)
class MissionBudget:
    max_iterations: int = DEFAULT_BUDGET["max_iterations"]
    max_slices: int = DEFAULT_BUDGET["max_slices"]
    max_tool_calls: int = DEFAULT_BUDGET["max_tool_calls"]
    max_source_expansions: int = DEFAULT_BUDGET["max_source_expansions"]
    max_source_bytes: int = DEFAULT_BUDGET["max_source_bytes"]


@dataclass(frozen=True)
class CompetencyQuestion:
    question_id: str
    question: str
    decision_relevance: str
    blocking: bool
    family_requirements: tuple[dict[str, Any], ...]
    uncertainty_policy: str = "explore"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: object, label: str, *, minimum: int = 1, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > maximum:
        raise AdaptiveExplorationError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _identifier(value: object, label: str) -> str:
    text = _text(value, label, maximum=160)
    if not all(char.isalnum() or char in {"-", "_", ".", ":"} for char in text):
        raise AdaptiveExplorationError(f"{label} contains unsupported characters")
    return text


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptiveExplorationError(f"{label} must be an object")
    return dict(value)


def _array(value: object, label: str, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise AdaptiveExplorationError(f"{label} must be a list with at least {minimum} item(s)")
    return value


def _validate_budget(value: Mapping[str, Any] | MissionBudget | None) -> dict[str, int]:
    if value is None:
        raw = dict(DEFAULT_BUDGET)
    elif isinstance(value, MissionBudget):
        raw = asdict(value)
    else:
        raw = dict(value)
    if set(raw) != set(BUDGET_KEYS):
        raise AdaptiveExplorationError(
            "mission budget must declare exactly: " + ", ".join(BUDGET_KEYS)
        )
    result: dict[str, int] = {}
    for key in BUDGET_KEYS:
        number = raw.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise AdaptiveExplorationError(f"mission budget {key} must be a positive integer")
        result[key] = number
    if result["max_slices"] < result["max_iterations"]:
        raise AdaptiveExplorationError("mission budget max_slices must be >= max_iterations")
    return result


def _family_inventory(asset: VerifiedProjectAsset | VerifiedProjectAssetV2) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if isinstance(asset, VerifiedProjectAssetV2):
        manifest = asset.manifest
        families = [
            {
                "family_id": str(row.get("family_id") or ""),
                "availability": str(row.get("availability") or ""),
                "artifact_role": str(row.get("artifact", {}).get("role") or "")
                if isinstance(row.get("artifact"), Mapping)
                else "",
            }
            for row in manifest.get("families", [])
            if isinstance(row, Mapping)
        ]
        return "project-knowledge-asset-v2", families, dict(manifest.get("target", {}))

    manifest = asset.manifest
    return (
        "project-knowledge-asset-v1",
        [
            {
                "family_id": "architecture",
                "availability": V1_LEGACY_AVAILABILITY,
                "artifact_role": "legacy-portable-authority-projection",
            },
            {
                "family_id": "capability",
                "availability": V1_LEGACY_AVAILABILITY,
                "artifact_role": "legacy-portable-authority-projection",
            },
        ],
        dict(manifest.get("target", {})),
    )


def _repository_surface_hint(repository_root: Path, tree: str) -> dict[str, Any]:
    entries = _tree_entries(repository_root, tree)
    visible_paths: list[str] = []
    protected_count = 0
    for _, object_type, _, path in entries:
        if object_type != "blob":
            continue
        normalized = str(path).replace("\\", "/")
        if any(
            normalized == prefix.rstrip("/") or normalized.startswith(prefix)
            for prefix in PROTECTED_PATH_PREFIXES
        ):
            protected_count += 1
            continue
        visible_paths.append(normalized)
    visible_paths.sort()
    root_files = [path for path in visible_paths if "/" not in path]
    top_level_roots = sorted(
        {
            PurePosixPath(path).parts[0]
            for path in visible_paths
            if len(PurePosixPath(path).parts) > 1
        }
    )
    suffix_counts: Counter[str] = Counter()
    for path in visible_paths:
        suffix = PurePosixPath(path).suffix.casefold() or "<none>"
        suffix_counts[suffix] += 1
    return {
        "posture": "path-metadata-only-non-authoritative",
        "visible_blob_path_count": len(visible_paths),
        "protected_blob_path_count": protected_count,
        "root_files": root_files,
        "top_level_roots": top_level_roots,
        "suffix_counts": [
            {"suffix": suffix, "count": count}
            for suffix, count in sorted(
                suffix_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "visible_path_set_sha256": _digest(visible_paths),
        "claim_ceiling": (
            "This environment hint contains Git tree path metadata only. It does not classify technology, "
            "architecture, capability, ownership, runtime behavior, dependency completeness or absence."
        ),
    }


def build_mission_context(
    repository_root: str | Path,
    *,
    mission_id: str,
    mission_summary: str,
    decision_to_support: str,
    target_ref: str = "HEAD",
    project_asset_id: str | None = None,
    budget: Mapping[str, Any] | MissionBudget | None = None,
) -> dict[str, Any]:
    """Build the exact, non-authoritative context packet a host Agent plans from."""
    root = Path(repository_root).expanduser().resolve(strict=False)
    try:
        target = resolve_git_target(root, target_ref=target_ref)
    except ObservationBoundaryError as exc:
        raise AdaptiveExplorationError(f"mission target cannot be resolved: {exc}") from exc

    family_rows: list[dict[str, Any]] = []
    knowledge_target: dict[str, Any] = {}
    knowledge_source = "none"
    asset_schema = ""
    freshness = "no-project-knowledge"
    selected_asset_id = ""
    if project_asset_id is not None:
        try:
            asset = verify_project_asset_any(root, asset_id=project_asset_id)
        except ProjectAssetError as exc:
            raise AdaptiveExplorationError(f"project knowledge verification failed: {exc}") from exc
        knowledge_source, family_rows, knowledge_target = _family_inventory(asset)
        selected_asset_id = str(asset.manifest.get("asset_id") or project_asset_id)
        asset_schema = str(asset.manifest.get("schema_version") or "")
        if (
            str(knowledge_target.get("commit") or "") == target.commit
            and str(knowledge_target.get("tree") or "") == target.tree
        ):
            freshness = "exact-target"
        else:
            freshness = "stale-target"

    packet: dict[str, Any] = {
        "schema_version": MISSION_CONTEXT_SCHEMA_VERSION,
        "status": "mission-context-ready",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "mission": {
            "mission_id": _identifier(mission_id, "mission id"),
            "summary": _text(mission_summary, "mission summary", maximum=1200),
            "decision_to_support": _text(
                decision_to_support,
                "mission decision_to_support",
                maximum=1200,
            ),
        },
        "target": {
            "requested_ref": target.requested_ref,
            "commit": target.commit,
            "tree": target.tree,
            "object_format": target.object_format,
        },
        "repository_environment": _repository_surface_hint(root, target.tree),
        "project_knowledge": {
            "source": knowledge_source,
            "asset_id": selected_asset_id,
            "schema_version": asset_schema,
            "freshness": freshness,
            "target": knowledge_target,
            "families": sorted(family_rows, key=lambda row: str(row.get("family_id") or "")),
        },
        "constitution": {
            "constitution_id": CONSTITUTION_ID,
            "rules": deepcopy(list(EXPLORATION_CONSTITUTION)),
        },
        "operator_registry": deepcopy(list(OPERATOR_REGISTRY)),
        "budget": _validate_budget(budget),
        "claim_ceiling": (
            "This packet establishes the exact mission source context, available verified Project Knowledge, "
            "non-authoritative exploration rules and caller budget. It does not decide the exploration plan, "
            "create semantic truth, prove project completeness, or authorize WFF lifecycle decisions."
        ),
    }
    packet["context_fingerprint"] = _digest(packet)
    return validate_mission_context(packet)


def validate_mission_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != MISSION_CONTEXT_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported mission-context schema")
    if data.get("status") != "mission-context-ready":
        raise AdaptiveExplorationError("mission context is not ready")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE:
        raise AdaptiveExplorationError("mission context attempted semantic authority")
    if data.get("materialization_class") != MATERIALIZATION_CLASS:
        raise AdaptiveExplorationError("mission context materialization posture changed")
    mission = _mapping(data.get("mission"), "mission")
    _identifier(mission.get("mission_id"), "mission id")
    _text(mission.get("summary"), "mission summary", maximum=1200)
    _text(mission.get("decision_to_support"), "mission decision_to_support", maximum=1200)
    target = _mapping(data.get("target"), "mission target")
    _text(target.get("commit"), "mission target commit", minimum=40, maximum=64)
    _text(target.get("tree"), "mission target tree", minimum=40, maximum=64)
    environment = _mapping(data.get("repository_environment"), "repository environment")
    if environment.get("posture") != "path-metadata-only-non-authoritative":
        raise AdaptiveExplorationError("repository environment posture changed")
    if not isinstance(environment.get("visible_blob_path_count"), int) or environment["visible_blob_path_count"] < 0:
        raise AdaptiveExplorationError("repository environment visible path count is invalid")
    _text(
        environment.get("visible_path_set_sha256"),
        "repository environment path-set digest",
        minimum=64,
        maximum=64,
    )
    _text(environment.get("claim_ceiling"), "repository environment claim ceiling", minimum=80)
    knowledge = _mapping(data.get("project_knowledge"), "project knowledge")
    if knowledge.get("freshness") not in {"no-project-knowledge", "exact-target", "stale-target"}:
        raise AdaptiveExplorationError("unsupported project-knowledge freshness posture")
    families = _array(knowledge.get("families"), "project knowledge families")
    ids: list[str] = []
    for raw in families:
        row = _mapping(raw, "project knowledge family")
        family_id = _identifier(row.get("family_id"), "project knowledge family id")
        if family_id in ids:
            raise AdaptiveExplorationError(f"duplicate project knowledge family: {family_id}")
        ids.append(family_id)
        _text(row.get("availability"), f"{family_id} availability", maximum=100)
    if ids != sorted(ids):
        raise AdaptiveExplorationError("project knowledge families must be sorted by id")
    constitution = _mapping(data.get("constitution"), "exploration constitution")
    if constitution.get("constitution_id") != CONSTITUTION_ID:
        raise AdaptiveExplorationError("exploration constitution id changed")
    rules = _array(constitution.get("rules"), "exploration constitution rules", minimum=len(EXPLORATION_CONSTITUTION))
    if [row.get("rule_id") for row in rules if isinstance(row, Mapping)] != [
        row["rule_id"] for row in EXPLORATION_CONSTITUTION
    ]:
        raise AdaptiveExplorationError("exploration constitution rules changed")
    registry = _array(data.get("operator_registry"), "operator registry", minimum=len(OPERATOR_REGISTRY))
    if [row.get("operator_id") for row in registry if isinstance(row, Mapping)] != [
        row["operator_id"] for row in OPERATOR_REGISTRY
    ]:
        raise AdaptiveExplorationError("operator registry changed")
    _validate_budget(_mapping(data.get("budget"), "mission budget"))
    _text(data.get("claim_ceiling"), "mission context claim ceiling", minimum=80)
    fingerprint = _text(data.get("context_fingerprint"), "mission context fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "context_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("mission context fingerprint mismatch")
    return data


def _normalize_question(raw: Mapping[str, Any] | CompetencyQuestion) -> dict[str, Any]:
    value = asdict(raw) if isinstance(raw, CompetencyQuestion) else dict(raw)
    question_id = _identifier(value.get("question_id"), "competency question id")
    question = _text(value.get("question"), f"{question_id} question", maximum=1200)
    relevance = _text(value.get("decision_relevance"), f"{question_id} decision relevance", maximum=1200)
    blocking = value.get("blocking")
    if not isinstance(blocking, bool):
        raise AdaptiveExplorationError(f"{question_id} blocking must be boolean")
    uncertainty_policy = str(value.get("uncertainty_policy") or "explore")
    if uncertainty_policy not in UNCERTAINTY_POLICIES:
        raise AdaptiveExplorationError(f"{question_id} uncertainty policy is unsupported")
    raw_requirements = value.get("family_requirements")
    requirements = list(raw_requirements) if isinstance(raw_requirements, (list, tuple)) else []
    if not requirements:
        raise AdaptiveExplorationError(f"{question_id} requires at least one knowledge-family requirement")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_requirement in enumerate(requirements, start=1):
        requirement = _mapping(raw_requirement, f"{question_id} family requirement {index}")
        family_id = _identifier(requirement.get("family_id"), f"{question_id} family id")
        if family_id in seen:
            raise AdaptiveExplorationError(f"{question_id} duplicates family requirement: {family_id}")
        seen.add(family_id)
        acceptable = requirement.get("acceptable_availability")
        if not isinstance(acceptable, (list, tuple)) or not acceptable:
            raise AdaptiveExplorationError(f"{question_id} {family_id} acceptable_availability must be non-empty")
        acceptable_values = sorted({_text(item, f"{question_id} acceptable availability", maximum=100) for item in acceptable})
        freshness = str(requirement.get("freshness_requirement") or "exact-target")
        if freshness not in FRESHNESS_REQUIREMENTS:
            raise AdaptiveExplorationError(f"{question_id} {family_id} freshness requirement is unsupported")
        normalized.append(
            {
                "family_id": family_id,
                "acceptable_availability": acceptable_values,
                "freshness_requirement": freshness,
            }
        )
    return {
        "question_id": question_id,
        "question": question,
        "decision_relevance": relevance,
        "blocking": blocking,
        "family_requirements": sorted(normalized, key=lambda row: row["family_id"]),
        "uncertainty_policy": uncertainty_policy,
    }


def assess_knowledge_sufficiency(
    mission_context: Mapping[str, Any],
    competency_questions: Sequence[Mapping[str, Any] | CompetencyQuestion],
) -> dict[str, Any]:
    """Mechanically compare Agent-authored competency questions with verified knowledge posture."""
    context = validate_mission_context(mission_context)
    questions = [_normalize_question(raw) for raw in competency_questions]
    if not questions:
        raise AdaptiveExplorationError("knowledge sufficiency requires at least one competency question")
    ids = [row["question_id"] for row in questions]
    if len(ids) != len(set(ids)):
        raise AdaptiveExplorationError("competency question ids must be unique")

    knowledge = _mapping(context["project_knowledge"], "project knowledge")
    family_index = {
        str(row.get("family_id") or ""): row
        for row in knowledge.get("families", [])
        if isinstance(row, Mapping)
    }
    freshness = str(knowledge.get("freshness") or "")
    results: list[dict[str, Any]] = []
    reused_questions = 0
    gap_questions = 0
    blocking_gap_ids: list[str] = []
    for question in questions:
        requirement_results: list[dict[str, Any]] = []
        for requirement in question["family_requirements"]:
            family_id = requirement["family_id"]
            observed = family_index.get(family_id)
            reasons: list[str] = []
            if observed is None:
                status = "missing-family"
                observed_availability = ""
                reasons.append("required family is absent from selected Project Knowledge")
            else:
                observed_availability = str(observed.get("availability") or "")
                if (
                    requirement["freshness_requirement"] == "exact-target"
                    and freshness != "exact-target"
                ):
                    status = "stale-target"
                    reasons.append(
                        "selected Project Knowledge is not bound to the exact mission target"
                    )
                elif observed_availability not in requirement["acceptable_availability"]:
                    status = "posture-not-accepted"
                    reasons.append(
                        "family availability does not satisfy this mission question's accepted posture"
                    )
                else:
                    status = "satisfied-existing"
            requirement_results.append(
                {
                    **requirement,
                    "observed_availability": observed_availability,
                    "status": status,
                    "reasons": reasons,
                }
            )
        satisfied = all(row["status"] == "satisfied-existing" for row in requirement_results)
        if satisfied:
            question_status = "sufficient-existing"
            reused_questions += 1
        else:
            question_status = "requires-exploration"
            gap_questions += 1
            if question["blocking"]:
                blocking_gap_ids.append(question["question_id"])
        results.append(
            {
                **question,
                "status": question_status,
                "requirement_results": requirement_results,
            }
        )

    report: dict[str, Any] = {
        "schema_version": SUFFICIENCY_SCHEMA_VERSION,
        "status": "knowledge-sufficiency-assessed",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "mission_context_fingerprint": context["context_fingerprint"],
        "mission": deepcopy(context["mission"]),
        "target": deepcopy(context["target"]),
        "project_knowledge": {
            "asset_id": knowledge.get("asset_id", ""),
            "schema_version": knowledge.get("schema_version", ""),
            "freshness": freshness,
        },
        "questions": results,
        "summary": {
            "question_count": len(results),
            "reused_existing_question_count": reused_questions,
            "exploration_gap_question_count": gap_questions,
            "blocking_gap_question_ids": sorted(blocking_gap_ids),
            "existing_knowledge_reuse_ratio": reused_questions / len(results),
        },
        "claim_ceiling": (
            "This report compares Agent-authored mission questions with verified Project Knowledge availability and source freshness. "
            "It does not decide what questions should exist, prove that an accepted family completely answers a question, "
            "resolve semantic conflicts, or authorize semantic knowledge writes."
        ),
    }
    report["report_fingerprint"] = _digest(report)
    return validate_knowledge_sufficiency(report, mission_context=context)


def validate_knowledge_sufficiency(
    payload: Mapping[str, Any],
    *,
    mission_context: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    if data.get("schema_version") != SUFFICIENCY_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported knowledge-sufficiency schema")
    if data.get("status") != "knowledge-sufficiency-assessed":
        raise AdaptiveExplorationError("knowledge sufficiency report is not assessed")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE:
        raise AdaptiveExplorationError("knowledge sufficiency attempted semantic authority")
    if data.get("mission_context_fingerprint") != context["context_fingerprint"]:
        raise AdaptiveExplorationError("knowledge sufficiency does not bind the mission context")
    questions = _array(data.get("questions"), "sufficiency questions", minimum=1)
    seen: set[str] = set()
    reused = 0
    gaps = 0
    blocking: list[str] = []
    for raw in questions:
        row = _mapping(raw, "sufficiency question")
        question_id = _identifier(row.get("question_id"), "sufficiency question id")
        if question_id in seen:
            raise AdaptiveExplorationError(f"duplicate sufficiency question: {question_id}")
        seen.add(question_id)
        if row.get("status") == "sufficient-existing":
            reused += 1
        elif row.get("status") == "requires-exploration":
            gaps += 1
            if row.get("blocking") is True:
                blocking.append(question_id)
        else:
            raise AdaptiveExplorationError(f"unsupported sufficiency question status: {question_id}")
        requirement_results = _array(
            row.get("requirement_results"),
            f"{question_id} requirement results",
            minimum=1,
        )
        if row.get("status") == "sufficient-existing" and any(
            not isinstance(result, Mapping) or result.get("status") != "satisfied-existing"
            for result in requirement_results
        ):
            raise AdaptiveExplorationError(
                f"sufficient question contains an unsatisfied requirement: {question_id}"
            )
    summary = _mapping(data.get("summary"), "sufficiency summary")
    expected_summary = {
        "question_count": len(questions),
        "reused_existing_question_count": reused,
        "exploration_gap_question_count": gaps,
        "blocking_gap_question_ids": sorted(blocking),
        "existing_knowledge_reuse_ratio": reused / len(questions),
    }
    if summary != expected_summary:
        raise AdaptiveExplorationError("knowledge sufficiency summary mismatch")
    _text(data.get("claim_ceiling"), "sufficiency claim ceiling", minimum=80)
    fingerprint = _text(data.get("report_fingerprint"), "sufficiency fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "report_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("knowledge sufficiency fingerprint mismatch")
    return data


def _normalize_slice_budget(value: object, *, label: str) -> dict[str, int]:
    raw = _mapping(value, label)
    if set(raw) != set(SLICE_BUDGET_KEYS):
        raise AdaptiveExplorationError(
            f"{label} must declare exactly: " + ", ".join(SLICE_BUDGET_KEYS)
        )
    result: dict[str, int] = {}
    for key in SLICE_BUDGET_KEYS:
        number = raw.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise AdaptiveExplorationError(f"{label} {key} must be a non-negative integer")
        result[key] = number
    if result["max_tool_calls"] < 1:
        raise AdaptiveExplorationError(f"{label} max_tool_calls must be at least 1")
    return result


def _normalize_plan_slice(
    raw: Mapping[str, Any],
    *,
    known_question_ids: set[str],
    gap_question_ids: set[str],
    operator_ids: set[str],
) -> dict[str, Any]:
    row = dict(raw)
    slice_id = _identifier(row.get("slice_id"), "exploration slice id")
    question_ids = [
        _identifier(value, f"{slice_id} question id")
        for value in _array(row.get("question_ids"), f"{slice_id} question ids", minimum=1)
    ]
    if len(question_ids) != len(set(question_ids)):
        raise AdaptiveExplorationError(f"{slice_id} question ids must be unique")
    unknown = sorted(set(question_ids) - known_question_ids)
    if unknown:
        raise AdaptiveExplorationError(
            f"{slice_id} references unknown competency questions: {', '.join(unknown)}"
        )
    non_gap = sorted(set(question_ids) - gap_question_ids)
    if non_gap:
        raise AdaptiveExplorationError(
            f"{slice_id} attempts to rescan already-sufficient questions: {', '.join(non_gap)}"
        )
    operator_id = _identifier(row.get("operator_id"), f"{slice_id} operator id")
    if operator_id not in operator_ids:
        raise AdaptiveExplorationError(f"{slice_id} uses unknown exploration operator: {operator_id}")
    scope_refs = [
        _text(value, f"{slice_id} scope ref", maximum=500)
        for value in _array(row.get("scope_refs"), f"{slice_id} scope refs", minimum=1)
    ]
    if len(scope_refs) != len(set(scope_refs)):
        raise AdaptiveExplorationError(f"{slice_id} scope refs must be unique")
    evidence_kinds = [
        _identifier(value, f"{slice_id} evidence kind")
        for value in _array(
            row.get("required_evidence_kinds"),
            f"{slice_id} required evidence kinds",
            minimum=1,
        )
    ]
    if len(evidence_kinds) != len(set(evidence_kinds)):
        raise AdaptiveExplorationError(f"{slice_id} evidence kinds must be unique")
    failure_posture = str(row.get("failure_posture") or "")
    if failure_posture not in PLAN_FAILURE_POSTURES:
        raise AdaptiveExplorationError(f"{slice_id} failure posture is unsupported")
    return {
        "slice_id": slice_id,
        "question_ids": question_ids,
        "operator_id": operator_id,
        "scope_refs": scope_refs,
        "expected_information_gain": _text(
            row.get("expected_information_gain"),
            f"{slice_id} expected information gain",
            maximum=1200,
        ),
        "required_evidence_kinds": evidence_kinds,
        "slice_budget": _normalize_slice_budget(
            row.get("slice_budget"),
            label=f"{slice_id} slice budget",
        ),
        "success_condition": _text(
            row.get("success_condition"),
            f"{slice_id} success condition",
            maximum=1200,
        ),
        "failure_posture": failure_posture,
    }


def build_mission_exploration_plan(
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    *,
    plan_id: str,
    plan_revision: int,
    environment_interpretation: str,
    priority_order: Sequence[str],
    priority_rationale: Mapping[str, str],
    slices: Sequence[Mapping[str, Any]],
    deferred_nonblocking_question_ids: Sequence[str] = (),
    stop_conditions: Sequence[str] = tuple(sorted(MANDATORY_STOP_CONDITIONS)),
    return_conditions: Sequence[str] = (
        "new-higher-priority-gap",
        "source-context-changed",
        "unresolved-blocking-conflict",
    ),
) -> dict[str, Any]:
    """Normalize and validate one Agent-authored, disposable exploration plan."""
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    if not isinstance(plan_revision, int) or isinstance(plan_revision, bool) or plan_revision < 1:
        raise AdaptiveExplorationError("plan revision must be a positive integer")
    question_rows = {
        str(row["question_id"]): row
        for row in sufficiency["questions"]
        if isinstance(row, Mapping)
    }
    known_question_ids = set(question_rows)
    gap_question_ids = {
        question_id
        for question_id, row in question_rows.items()
        if row.get("status") == "requires-exploration"
    }
    blocking_gap_ids = {
        question_id
        for question_id in gap_question_ids
        if question_rows[question_id].get("blocking") is True
    }
    nonblocking_gap_ids = gap_question_ids - blocking_gap_ids
    normalized_priority = [
        _identifier(value, "priority question id") for value in priority_order
    ]
    if set(normalized_priority) != gap_question_ids or len(normalized_priority) != len(
        gap_question_ids
    ):
        raise AdaptiveExplorationError(
            "priority_order must contain every exploration-gap question exactly once"
        )
    rationale_map = {
        _identifier(key, "priority rationale question id"): _text(
            value,
            "priority rationale",
            maximum=1200,
        )
        for key, value in priority_rationale.items()
    }
    if set(rationale_map) != gap_question_ids:
        raise AdaptiveExplorationError(
            "priority_rationale must explain every exploration-gap question"
        )
    operator_ids = {
        str(row.get("operator_id") or "")
        for row in context["operator_registry"]
        if isinstance(row, Mapping)
    }
    normalized_slices = [
        _normalize_plan_slice(
            raw,
            known_question_ids=known_question_ids,
            gap_question_ids=gap_question_ids,
            operator_ids=operator_ids,
        )
        for raw in slices
    ]
    slice_ids = [row["slice_id"] for row in normalized_slices]
    if len(slice_ids) != len(set(slice_ids)):
        raise AdaptiveExplorationError("exploration slice ids must be unique")
    budget = context["budget"]
    if len(normalized_slices) > budget["max_slices"]:
        raise AdaptiveExplorationError("exploration plan exceeds mission max_slices budget")
    totals = {
        key: sum(row["slice_budget"][key] for row in normalized_slices)
        for key in SLICE_BUDGET_KEYS
    }
    for key in SLICE_BUDGET_KEYS:
        if totals[key] > budget[key]:
            raise AdaptiveExplorationError(f"exploration plan exceeds mission budget: {key}")
    covered_question_ids = {
        question_id
        for row in normalized_slices
        for question_id in row["question_ids"]
    }
    missing_blocking = sorted(blocking_gap_ids - covered_question_ids)
    if missing_blocking:
        raise AdaptiveExplorationError(
            "blocking exploration gaps are not covered by a slice: "
            + ", ".join(missing_blocking)
        )
    deferred = [
        _identifier(value, "deferred question id")
        for value in deferred_nonblocking_question_ids
    ]
    if len(deferred) != len(set(deferred)):
        raise AdaptiveExplorationError("deferred question ids must be unique")
    invalid_deferred = sorted(set(deferred) - nonblocking_gap_ids)
    if invalid_deferred:
        raise AdaptiveExplorationError(
            "only non-blocking exploration gaps may be deferred: "
            + ", ".join(invalid_deferred)
        )
    unresolved_nonblocking = sorted(
        nonblocking_gap_ids - covered_question_ids - set(deferred)
    )
    if unresolved_nonblocking:
        raise AdaptiveExplorationError(
            "non-blocking gaps must be covered or explicitly deferred: "
            + ", ".join(unresolved_nonblocking)
        )
    normalized_stops = sorted(
        {
            _identifier(value, "plan stop condition")
            for value in stop_conditions
        }
    )
    unsupported_stops = sorted(set(normalized_stops) - PLAN_STOP_CONDITIONS)
    if unsupported_stops:
        raise AdaptiveExplorationError(
            "unsupported plan stop conditions: " + ", ".join(unsupported_stops)
        )
    if not MANDATORY_STOP_CONDITIONS.issubset(normalized_stops):
        raise AdaptiveExplorationError(
            "plan must preserve mandatory mission-sufficient, budget-exhausted and source-context-changed stops"
        )
    normalized_returns = sorted(
        {
            _identifier(value, "plan return condition")
            for value in return_conditions
        }
    )
    if not normalized_returns:
        raise AdaptiveExplorationError("plan requires at least one explicit return condition")

    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "mission-exploration-plan-ready",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "plan_id": _identifier(plan_id, "plan id"),
        "plan_revision": plan_revision,
        "mission_context_fingerprint": context["context_fingerprint"],
        "sufficiency_report_fingerprint": sufficiency["report_fingerprint"],
        "target": deepcopy(context["target"]),
        "repository_environment_fingerprint": context["repository_environment"][
            "visible_path_set_sha256"
        ],
        "environment_interpretation": _text(
            environment_interpretation,
            "environment interpretation",
            maximum=1600,
        ),
        "priority_order": normalized_priority,
        "priority_rationale": rationale_map,
        "slices": normalized_slices,
        "deferred_nonblocking_question_ids": sorted(deferred),
        "budget": {
            "mission_ceiling": deepcopy(budget),
            "planned_totals": totals,
        },
        "stop_conditions": normalized_stops,
        "return_conditions": normalized_returns,
        "forbidden_claims": sorted(
            {
                forbidden
                for row in context["operator_registry"]
                if isinstance(row, Mapping)
                for forbidden in row.get("forbidden_claims", [])
            }
        ),
        "claim_ceiling": (
            "This plan records a host-Agent exploration decision over explicit EKRI knowledge gaps, generic operators and caller budgets. "
            "It is disposable acquisition control, not workflow/semantic authority, and it cannot prove absence, ownership, project completeness or safe change."
        ),
    }
    plan["plan_fingerprint"] = _digest(plan)
    return validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )


def validate_mission_exploration_plan(
    payload: Mapping[str, Any],
    *,
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    if data.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported mission-exploration-plan schema")
    if data.get("status") != "mission-exploration-plan-ready":
        raise AdaptiveExplorationError("mission exploration plan is not ready")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE:
        raise AdaptiveExplorationError("mission plan attempted semantic authority")
    if data.get("mission_context_fingerprint") != context["context_fingerprint"]:
        raise AdaptiveExplorationError("mission plan does not bind the mission context")
    if data.get("sufficiency_report_fingerprint") != sufficiency["report_fingerprint"]:
        raise AdaptiveExplorationError("mission plan does not bind the sufficiency report")
    if data.get("repository_environment_fingerprint") != context["repository_environment"][
        "visible_path_set_sha256"
    ]:
        raise AdaptiveExplorationError("mission plan environment binding mismatch")
    _identifier(data.get("plan_id"), "plan id")
    revision = data.get("plan_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise AdaptiveExplorationError("plan revision must be a positive integer")
    _text(data.get("environment_interpretation"), "environment interpretation", maximum=1600)
    question_rows = {
        str(row["question_id"]): row
        for row in sufficiency["questions"]
        if isinstance(row, Mapping)
    }
    known_question_ids = set(question_rows)
    gap_question_ids = {
        question_id
        for question_id, row in question_rows.items()
        if row.get("status") == "requires-exploration"
    }
    blocking_gap_ids = {
        question_id
        for question_id in gap_question_ids
        if question_rows[question_id].get("blocking") is True
    }
    nonblocking_gap_ids = gap_question_ids - blocking_gap_ids
    priority_order = [
        _identifier(value, "priority question id")
        for value in _array(data.get("priority_order"), "priority order")
    ]
    if set(priority_order) != gap_question_ids or len(priority_order) != len(gap_question_ids):
        raise AdaptiveExplorationError(
            "mission plan priority order does not exactly cover exploration gaps"
        )
    rationale = _mapping(data.get("priority_rationale"), "priority rationale")
    if set(rationale) != gap_question_ids:
        raise AdaptiveExplorationError(
            "mission plan priority rationale does not exactly cover exploration gaps"
        )
    operator_ids = {
        str(row.get("operator_id") or "")
        for row in context["operator_registry"]
        if isinstance(row, Mapping)
    }
    slices = _array(data.get("slices"), "exploration plan slices")
    normalized_slices = [
        _normalize_plan_slice(
            _mapping(row, "exploration plan slice"),
            known_question_ids=known_question_ids,
            gap_question_ids=gap_question_ids,
            operator_ids=operator_ids,
        )
        for row in slices
    ]
    if normalized_slices != slices:
        raise AdaptiveExplorationError("exploration plan slices are not canonical")
    slice_ids = [row["slice_id"] for row in normalized_slices]
    if len(slice_ids) != len(set(slice_ids)):
        raise AdaptiveExplorationError("exploration plan slice ids must be unique")
    if len(normalized_slices) > context["budget"]["max_slices"]:
        raise AdaptiveExplorationError("exploration plan exceeds mission max_slices budget")
    covered_question_ids = {
        question_id
        for row in normalized_slices
        for question_id in row["question_ids"]
    }
    missing_blocking = sorted(blocking_gap_ids - covered_question_ids)
    if missing_blocking:
        raise AdaptiveExplorationError(
            "blocking exploration gaps are not covered by a slice: "
            + ", ".join(missing_blocking)
        )
    deferred = [
        _identifier(value, "deferred question id")
        for value in _array(
            data.get("deferred_nonblocking_question_ids"),
            "deferred nonblocking question ids",
        )
    ]
    if len(deferred) != len(set(deferred)):
        raise AdaptiveExplorationError("deferred question ids must be unique")
    invalid_deferred = sorted(set(deferred) - nonblocking_gap_ids)
    if invalid_deferred:
        raise AdaptiveExplorationError(
            "only non-blocking exploration gaps may be deferred: "
            + ", ".join(invalid_deferred)
        )
    unresolved_nonblocking = sorted(
        nonblocking_gap_ids - covered_question_ids - set(deferred)
    )
    if unresolved_nonblocking:
        raise AdaptiveExplorationError(
            "non-blocking gaps must be covered or explicitly deferred: "
            + ", ".join(unresolved_nonblocking)
        )
    budget = _mapping(data.get("budget"), "exploration plan budget")
    if budget.get("mission_ceiling") != context["budget"]:
        raise AdaptiveExplorationError("exploration plan mission budget ceiling changed")
    totals = _mapping(budget.get("planned_totals"), "exploration plan totals")
    expected_totals = {
        key: sum(
            int(row.get("slice_budget", {}).get(key, 0))
            for row in slices
            if isinstance(row, Mapping)
        )
        for key in SLICE_BUDGET_KEYS
    }
    if totals != expected_totals:
        raise AdaptiveExplorationError("exploration plan budget totals mismatch")
    for key in SLICE_BUDGET_KEYS:
        if int(totals.get(key, 0)) > int(context["budget"][key]):
            raise AdaptiveExplorationError(f"exploration plan exceeds mission budget: {key}")
    stops = set(_array(data.get("stop_conditions"), "plan stop conditions", minimum=1))
    if not MANDATORY_STOP_CONDITIONS.issubset(stops):
        raise AdaptiveExplorationError("mission plan lost a mandatory stop condition")
    if stops - PLAN_STOP_CONDITIONS:
        raise AdaptiveExplorationError("mission plan contains an unsupported stop condition")
    _array(data.get("return_conditions"), "plan return conditions", minimum=1)
    _text(data.get("claim_ceiling"), "plan claim ceiling", minimum=80)
    fingerprint = _text(data.get("plan_fingerprint"), "plan fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "plan_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("mission plan fingerprint mismatch")
    return data


def _safe_target_path(value: object, label: str) -> str:
    text = _text(value, label, maximum=800).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise AdaptiveExplorationError(f"{label} must be a canonical repository-relative path")
    normalized = path.as_posix()
    if normalized != text:
        raise AdaptiveExplorationError(f"{label} is not canonical")
    if any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in PROTECTED_PATH_PREFIXES
    ):
        raise AdaptiveExplorationError(f"{label} enters protected EKRI/runtime state")
    return normalized


def _plan_slice_index(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("slice_id") or ""): dict(row)
        for row in plan.get("slices", [])
        if isinstance(row, Mapping)
    }


def collect_git_path_evidence(
    repository_root: str | Path,
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    slice_id: str,
    operator_id: str,
    paths: Sequence[str],
) -> dict[str, Any]:
    """Collect exact target-tree Git blob receipts for one bounded plan slice."""
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    selected_slice_id = _identifier(slice_id, "evidence slice id")
    selected_operator = _identifier(operator_id, "evidence operator id")
    slice_row = _plan_slice_index(validated_plan).get(selected_slice_id)
    if slice_row is None:
        raise AdaptiveExplorationError(f"evidence receipt references unknown plan slice: {selected_slice_id}")
    if slice_row.get("operator_id") != selected_operator:
        raise AdaptiveExplorationError("evidence receipt operator does not match plan slice")
    normalized_paths = [_safe_target_path(path, "evidence target path") for path in paths]
    if not normalized_paths:
        raise AdaptiveExplorationError("Git path evidence requires at least one source path")
    if len(normalized_paths) != len(set(normalized_paths)):
        raise AdaptiveExplorationError("Git path evidence paths must be unique")
    root = Path(repository_root).expanduser().resolve(strict=False)
    target = context["target"]
    tree = str(target["tree"])
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(normalized_paths):
        entries = [
            entry
            for entry in _tree_entries(root, tree, pathspec=path)
            if entry[3] == path
        ]
        if len(entries) != 1:
            raise AdaptiveExplorationError(f"evidence target path is missing or ambiguous: {path}")
        mode, object_type, oid, _ = entries[0]
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise AdaptiveExplorationError(f"evidence target path is not a regular Git blob: {path}")
        try:
            raw = _run_git(root, "cat-file", "blob", oid, binary=True)
        except ObservationBoundaryError as exc:
            raise AdaptiveExplorationError(f"evidence blob cannot be read: {path}: {exc}") from exc
        assert isinstance(raw, bytes)
        total_bytes += len(raw)
        rows.append(
            {
                "path": path,
                "mode": mode,
                "blob_oid": oid,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    usage = {
        "tool_calls": 1,
        "source_expansions": len(rows),
        "source_bytes": total_bytes,
    }
    slice_budget = slice_row["slice_budget"]
    if usage["tool_calls"] > slice_budget["max_tool_calls"]:
        raise AdaptiveExplorationError("evidence collection exceeds slice tool-call budget")
    if usage["source_expansions"] > slice_budget["max_source_expansions"]:
        raise AdaptiveExplorationError("evidence collection exceeds slice source-expansion budget")
    if usage["source_bytes"] > slice_budget["max_source_bytes"]:
        raise AdaptiveExplorationError("evidence collection exceeds slice source-byte budget")
    receipt: dict[str, Any] = {
        "schema_version": EVIDENCE_RECEIPT_SCHEMA_VERSION,
        "status": "acquisition-evidence-recorded",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "semantic_authority": False,
        "mission_context_fingerprint": context["context_fingerprint"],
        "plan_fingerprint": validated_plan["plan_fingerprint"],
        "slice_id": selected_slice_id,
        "operator_id": selected_operator,
        "collector_id": "git-target-blob-reader",
        "target": deepcopy(target),
        "evidence": rows,
        "usage": usage,
        "claim_ceiling": (
            "This receipt proves only the exact Git blob identities read for one bounded acquisition slice. "
            "Blob presence, text or structural content does not by itself create architecture, capability, ownership, absence or safe-change authority."
        ),
    }
    receipt["receipt_fingerprint"] = _digest(receipt)
    return validate_evidence_receipt(
        receipt,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )


def validate_evidence_receipt(
    payload: Mapping[str, Any],
    *,
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    if data.get("schema_version") != EVIDENCE_RECEIPT_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported acquisition-evidence schema")
    if data.get("status") != "acquisition-evidence-recorded":
        raise AdaptiveExplorationError("acquisition evidence is not recorded")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE or data.get("semantic_authority") is not False:
        raise AdaptiveExplorationError("acquisition evidence attempted semantic authority")
    if data.get("mission_context_fingerprint") != context["context_fingerprint"]:
        raise AdaptiveExplorationError("acquisition evidence does not bind mission context")
    if data.get("plan_fingerprint") != validated_plan["plan_fingerprint"]:
        raise AdaptiveExplorationError("acquisition evidence does not bind plan")
    slice_id = _identifier(data.get("slice_id"), "evidence slice id")
    operator_id = _identifier(data.get("operator_id"), "evidence operator id")
    slice_row = _plan_slice_index(validated_plan).get(slice_id)
    if slice_row is None or slice_row.get("operator_id") != operator_id:
        raise AdaptiveExplorationError("acquisition evidence slice/operator binding mismatch")
    if data.get("target") != context["target"]:
        raise AdaptiveExplorationError("acquisition evidence target identity mismatch")
    evidence = _array(data.get("evidence"), "acquisition evidence rows", minimum=1)
    paths: list[str] = []
    computed_bytes = 0
    for raw in evidence:
        row = _mapping(raw, "acquisition evidence row")
        path = _safe_target_path(row.get("path"), "acquisition evidence path")
        if path in paths:
            raise AdaptiveExplorationError("acquisition evidence paths must be unique")
        paths.append(path)
        sha = _text(row.get("sha256"), "acquisition evidence sha256", minimum=64, maximum=64)
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise AdaptiveExplorationError("acquisition evidence sha256 is invalid")
        size = row.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise AdaptiveExplorationError("acquisition evidence size is invalid")
        computed_bytes += size
    usage = _mapping(data.get("usage"), "acquisition evidence usage")
    expected_usage = {
        "tool_calls": 1,
        "source_expansions": len(evidence),
        "source_bytes": computed_bytes,
    }
    if usage != expected_usage:
        raise AdaptiveExplorationError("acquisition evidence usage mismatch")
    slice_budget = slice_row["slice_budget"]
    if usage["source_expansions"] > slice_budget["max_source_expansions"] or usage["source_bytes"] > slice_budget["max_source_bytes"]:
        raise AdaptiveExplorationError("acquisition evidence exceeds plan slice budget")
    _text(data.get("claim_ceiling"), "acquisition evidence claim ceiling", minimum=80)
    fingerprint = _text(data.get("receipt_fingerprint"), "acquisition evidence fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "receipt_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("acquisition evidence fingerprint mismatch")
    return data


def _initial_question_states(
    sufficiency: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, str]:
    deferred = set(plan.get("deferred_nonblocking_question_ids", []))
    result: dict[str, str] = {}
    for raw in sufficiency.get("questions", []):
        if not isinstance(raw, Mapping):
            continue
        question_id = str(raw.get("question_id") or "")
        if raw.get("status") == "sufficient-existing":
            result[question_id] = "satisfied-existing"
        elif question_id in deferred:
            result[question_id] = "deferred"
        else:
            result[question_id] = "unresolved"
    return result


def initialize_wae_trace(
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    trace: dict[str, Any] = {
        "schema_version": WAE_TRACE_SCHEMA_VERSION,
        "status": "exploration-ready",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "mission_context_fingerprint": context["context_fingerprint"],
        "sufficiency_report_fingerprint": sufficiency["report_fingerprint"],
        "plan_fingerprint": validated_plan["plan_fingerprint"],
        "plan_id": validated_plan["plan_id"],
        "plan_revision": validated_plan["plan_revision"],
        "target": deepcopy(context["target"]),
        "question_states": _initial_question_states(sufficiency, validated_plan),
        "iterations": [],
        "usage": {"tool_calls": 0, "source_expansions": 0, "source_bytes": 0},
        "stop_or_return_reason": "",
        "claim_ceiling": (
            "This WAE trace records bounded acquisition iterations, challenge evidence and Agent reconciliation over one mission plan. "
            "It does not create semantic truth, decide WFF workflow routes or allow exploration findings to bypass family authority."
        ),
    }
    trace["trace_fingerprint"] = _digest(trace)
    return validate_wae_trace(
        trace,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )


def _normalize_challenge_findings(
    values: object,
    *,
    allowed_receipt_fingerprints: set[str],
    label: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in _array(values, label):
        row = _mapping(raw, "WAE challenge finding")
        finding_id = _identifier(row.get("finding_id"), "WAE challenge finding id")
        if finding_id in ids:
            raise AdaptiveExplorationError(f"duplicate WAE challenge finding: {finding_id}")
        ids.add(finding_id)
        posture = str(row.get("posture") or "")
        if posture not in WAE_CHALLENGE_POSTURES:
            raise AdaptiveExplorationError(f"unsupported WAE challenge posture: {posture}")
        evidence_refs = [
            _text(value, "WAE challenge evidence receipt fingerprint", minimum=64, maximum=64)
            for value in _array(
                row.get("evidence_receipt_fingerprints"),
                "WAE challenge evidence refs",
            )
        ]
        unknown = sorted(set(evidence_refs) - allowed_receipt_fingerprints)
        if unknown:
            raise AdaptiveExplorationError(
                "WAE challenge references evidence outside the trace: " + ", ".join(unknown)
            )
        findings.append(
            {
                "finding_id": finding_id,
                "posture": posture,
                "detail": _text(row.get("detail"), "WAE challenge detail", maximum=1600),
                "evidence_receipt_fingerprints": evidence_refs,
            }
        )
    return findings


def _normalize_reconciliation(
    value: object,
    *,
    slice_question_ids: set[str],
) -> dict[str, Any]:
    row = _mapping(value, "WAE reconciliation")
    outcome = str(row.get("outcome") or "")
    if outcome not in WAE_RECONCILIATION_OUTCOMES:
        raise AdaptiveExplorationError(f"unsupported WAE reconciliation outcome: {outcome}")
    updates = _mapping(row.get("question_status_updates"), "WAE question status updates")
    unknown_questions = sorted(set(updates) - slice_question_ids)
    if unknown_questions:
        raise AdaptiveExplorationError(
            "WAE reconciliation updates questions outside selected slice: "
            + ", ".join(unknown_questions)
        )
    normalized_updates: dict[str, str] = {}
    for question_id, state in updates.items():
        normalized_id = _identifier(question_id, "WAE reconciliation question id")
        normalized_state = str(state or "")
        if normalized_state not in QUESTION_RUNTIME_STATES:
            raise AdaptiveExplorationError(
                f"unsupported WAE question runtime state: {normalized_state}"
            )
        normalized_updates[normalized_id] = normalized_state
    family_ids = [
        _identifier(value, "WAE candidate family id")
        for value in _array(row.get("candidate_family_ids"), "WAE candidate family ids")
    ]
    if len(family_ids) != len(set(family_ids)):
        raise AdaptiveExplorationError("WAE candidate family ids must be unique")
    return {
        "outcome": outcome,
        "rationale": _text(row.get("rationale"), "WAE reconciliation rationale", maximum=1800),
        "question_status_updates": normalized_updates,
        "candidate_family_ids": family_ids,
    }


def _blocking_questions_satisfied(
    sufficiency: Mapping[str, Any],
    question_states: Mapping[str, str],
) -> bool:
    for raw in sufficiency.get("questions", []):
        if not isinstance(raw, Mapping) or raw.get("blocking") is not True:
            continue
        question_id = str(raw.get("question_id") or "")
        state = str(question_states.get(question_id) or "")
        if state in {"satisfied-existing", "resolved"}:
            continue
        if state == "review-bound" and raw.get("uncertainty_policy") == "carry-review-bound":
            continue
        return False
    return True


def record_wae_iteration(
    trace: Mapping[str, Any],
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    slice_id: str,
    evidence_receipts: Sequence[Mapping[str, Any]],
    challenge_findings: Sequence[Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
    material_gain: str,
    next_action: str,
    stop_or_return_reason: str = "",
    why_next_action: str,
) -> dict[str, Any]:
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    current = validate_wae_trace(
        trace,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )
    if current["status"] not in {"exploration-ready", "exploration-in-progress"}:
        raise AdaptiveExplorationError("WAE trace is already in a terminal state")
    iteration_number = len(current["iterations"]) + 1
    if iteration_number > context["budget"]["max_iterations"]:
        raise AdaptiveExplorationError("WAE iteration exceeds mission iteration budget")
    selected_slice_id = _identifier(slice_id, "WAE slice id")
    slice_row = _plan_slice_index(validated_plan).get(selected_slice_id)
    if slice_row is None:
        raise AdaptiveExplorationError(f"WAE iteration references unknown plan slice: {selected_slice_id}")
    receipts = [
        validate_evidence_receipt(
            raw,
            mission_context=context,
            sufficiency_report=sufficiency,
            plan=validated_plan,
        )
        for raw in evidence_receipts
    ]
    for receipt in receipts:
        if receipt["slice_id"] != selected_slice_id:
            raise AdaptiveExplorationError("WAE iteration evidence belongs to a different plan slice")
    current_receipt_fps = [receipt["receipt_fingerprint"] for receipt in receipts]
    if len(current_receipt_fps) != len(set(current_receipt_fps)):
        raise AdaptiveExplorationError("WAE iteration evidence receipts must be unique")
    previous_receipt_fps = {
        receipt["receipt_fingerprint"]
        for iteration in current["iterations"]
        for receipt in iteration.get("evidence_receipts", [])
        if isinstance(receipt, Mapping)
    }
    if previous_receipt_fps.intersection(current_receipt_fps):
        raise AdaptiveExplorationError("WAE iteration cannot reuse the same evidence receipt as a new acquisition round")
    all_receipt_fps = previous_receipt_fps | set(current_receipt_fps)
    findings = _normalize_challenge_findings(
        list(challenge_findings),
        allowed_receipt_fingerprints=all_receipt_fps,
        label="WAE challenge findings",
    )
    normalized_reconciliation = _normalize_reconciliation(
        reconciliation,
        slice_question_ids=set(slice_row["question_ids"]),
    )
    if normalized_reconciliation["outcome"] in {"accept-candidate", "inferred-candidate"} and not receipts:
        raise AdaptiveExplorationError("accepted/inferred WAE candidate requires acquired evidence")
    action = str(next_action or "")
    if action not in WAE_NEXT_ACTIONS:
        raise AdaptiveExplorationError(f"unsupported WAE next action: {action}")
    reason = str(stop_or_return_reason or "").strip()
    if action == "continue" and reason:
        raise AdaptiveExplorationError("continuing WAE iteration cannot declare a stop/return reason")
    if action != "continue":
        allowed_reasons = set(validated_plan["stop_conditions"]) | set(
            validated_plan["return_conditions"]
        )
        if reason not in allowed_reasons:
            raise AdaptiveExplorationError(
                "terminal/replan WAE action must use a declared plan stop or return reason"
            )
    updated_states = dict(current["question_states"])
    updated_states.update(normalized_reconciliation["question_status_updates"])
    if action == "converge":
        if reason != "mission-sufficient":
            raise AdaptiveExplorationError("converged WAE trace must stop for mission-sufficient")
        if not _blocking_questions_satisfied(sufficiency, updated_states):
            raise AdaptiveExplorationError(
                "WAE cannot converge while blocking competency questions remain unresolved"
            )
    added_usage = {
        key: sum(int(receipt["usage"][key.replace("max_", "")]) for receipt in receipts)
        for key in SLICE_BUDGET_KEYS
    }
    new_usage = {
        "tool_calls": current["usage"]["tool_calls"] + added_usage["max_tool_calls"],
        "source_expansions": current["usage"]["source_expansions"] + added_usage["max_source_expansions"],
        "source_bytes": current["usage"]["source_bytes"] + added_usage["max_source_bytes"],
    }
    if new_usage["tool_calls"] > context["budget"]["max_tool_calls"]:
        raise AdaptiveExplorationError("WAE trace exceeds mission tool-call budget")
    if new_usage["source_expansions"] > context["budget"]["max_source_expansions"]:
        raise AdaptiveExplorationError("WAE trace exceeds mission source-expansion budget")
    if new_usage["source_bytes"] > context["budget"]["max_source_bytes"]:
        raise AdaptiveExplorationError("WAE trace exceeds mission source-byte budget")
    budget_exhausted = (
        new_usage["tool_calls"] >= context["budget"]["max_tool_calls"]
        or new_usage["source_expansions"] >= context["budget"]["max_source_expansions"]
        or new_usage["source_bytes"] >= context["budget"]["max_source_bytes"]
    )
    if action == "continue" and budget_exhausted:
        raise AdaptiveExplorationError("WAE cannot continue after mission exploration budget is exhausted")
    status_by_action = {
        "continue": "exploration-in-progress",
        "replan": "exploration-returned-for-replan",
        "converge": "exploration-converged",
        "return-remediate": "exploration-returned",
        "blocked": "exploration-blocked",
    }
    iteration = {
        "iteration_number": iteration_number,
        "iteration_id": f"{validated_plan['plan_id']}:iteration-{iteration_number}",
        "slice_id": selected_slice_id,
        "question_ids": list(slice_row["question_ids"]),
        "operator_id": slice_row["operator_id"],
        "evidence_receipts": receipts,
        "challenge_findings": findings,
        "reconciliation": normalized_reconciliation,
        "material_gain": _text(material_gain, "WAE iteration material gain", maximum=1800),
        "question_states_after": updated_states,
        "usage_after": new_usage,
        "next_action": action,
        "stop_or_return_reason": reason,
        "why_next_action": _text(why_next_action, "WAE next-action rationale", maximum=1800),
    }
    result = deepcopy(current)
    result["iterations"].append(iteration)
    result["question_states"] = updated_states
    result["usage"] = new_usage
    result["status"] = status_by_action[action]
    result["stop_or_return_reason"] = reason
    result["trace_fingerprint"] = _digest(
        {key: value for key, value in result.items() if key != "trace_fingerprint"}
    )
    return validate_wae_trace(
        result,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )


def validate_wae_trace(
    payload: Mapping[str, Any],
    *,
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    if data.get("schema_version") != WAE_TRACE_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported adaptive WAE trace schema")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE:
        raise AdaptiveExplorationError("adaptive WAE trace attempted semantic authority")
    if data.get("mission_context_fingerprint") != context["context_fingerprint"]:
        raise AdaptiveExplorationError("adaptive WAE trace mission binding mismatch")
    if data.get("sufficiency_report_fingerprint") != sufficiency["report_fingerprint"]:
        raise AdaptiveExplorationError("adaptive WAE trace sufficiency binding mismatch")
    if data.get("plan_fingerprint") != validated_plan["plan_fingerprint"]:
        raise AdaptiveExplorationError("adaptive WAE trace plan binding mismatch")
    if data.get("target") != context["target"]:
        raise AdaptiveExplorationError("adaptive WAE trace target binding mismatch")
    iterations = _array(data.get("iterations"), "adaptive WAE iterations")
    if len(iterations) > context["budget"]["max_iterations"]:
        raise AdaptiveExplorationError("adaptive WAE trace exceeds iteration budget")
    states = _initial_question_states(sufficiency, validated_plan)
    usage = {"tool_calls": 0, "source_expansions": 0, "source_bytes": 0}
    seen_receipts: set[str] = set()
    terminal_seen = False
    for index, raw in enumerate(iterations, start=1):
        if terminal_seen:
            raise AdaptiveExplorationError("adaptive WAE trace contains iterations after terminal action")
        row = _mapping(raw, "adaptive WAE iteration")
        if row.get("iteration_number") != index:
            raise AdaptiveExplorationError("adaptive WAE iteration numbers are not sequential")
        slice_id = _identifier(row.get("slice_id"), "adaptive WAE slice id")
        slice_row = _plan_slice_index(validated_plan).get(slice_id)
        if slice_row is None or row.get("operator_id") != slice_row.get("operator_id"):
            raise AdaptiveExplorationError("adaptive WAE iteration slice/operator mismatch")
        receipts = [
            validate_evidence_receipt(
                receipt,
                mission_context=context,
                sufficiency_report=sufficiency,
                plan=validated_plan,
            )
            for receipt in _array(row.get("evidence_receipts"), "adaptive WAE evidence receipts")
        ]
        current_fps = {receipt["receipt_fingerprint"] for receipt in receipts}
        if len(current_fps) != len(receipts) or seen_receipts.intersection(current_fps):
            raise AdaptiveExplorationError("adaptive WAE evidence receipt reuse/duplication detected")
        seen_receipts.update(current_fps)
        normalized_findings = _normalize_challenge_findings(
            row.get("challenge_findings"),
            allowed_receipt_fingerprints=set(seen_receipts),
            label="adaptive WAE challenge findings",
        )
        if normalized_findings != row.get("challenge_findings"):
            raise AdaptiveExplorationError("adaptive WAE challenge findings are not canonical")
        reconciliation = _normalize_reconciliation(
            row.get("reconciliation"),
            slice_question_ids=set(slice_row["question_ids"]),
        )
        if reconciliation != row.get("reconciliation"):
            raise AdaptiveExplorationError("adaptive WAE reconciliation is not canonical")
        if reconciliation["outcome"] in {"accept-candidate", "inferred-candidate"} and not receipts:
            raise AdaptiveExplorationError("adaptive WAE accepted/inferred candidate lacks acquired evidence")
        states.update(reconciliation["question_status_updates"])
        if row.get("question_states_after") != states:
            raise AdaptiveExplorationError("adaptive WAE question-state trace mismatch")
        for receipt in receipts:
            usage["tool_calls"] += int(receipt["usage"]["tool_calls"])
            usage["source_expansions"] += int(receipt["usage"]["source_expansions"])
            usage["source_bytes"] += int(receipt["usage"]["source_bytes"])
        if row.get("usage_after") != usage:
            raise AdaptiveExplorationError("adaptive WAE usage trace mismatch")
        _text(row.get("material_gain"), "adaptive WAE material gain", maximum=1800)
        _text(row.get("why_next_action"), "adaptive WAE next-action rationale", maximum=1800)
        action = str(row.get("next_action") or "")
        if action not in WAE_NEXT_ACTIONS:
            raise AdaptiveExplorationError("adaptive WAE iteration has unsupported next action")
        reason = str(row.get("stop_or_return_reason") or "")
        if action == "continue":
            if reason:
                raise AdaptiveExplorationError("adaptive WAE continuing iteration contains terminal reason")
        else:
            allowed_reasons = set(validated_plan["stop_conditions"]) | set(
                validated_plan["return_conditions"]
            )
            if reason not in allowed_reasons:
                raise AdaptiveExplorationError("adaptive WAE terminal reason is outside plan contract")
            terminal_seen = True
        if action == "converge":
            if reason != "mission-sufficient" or not _blocking_questions_satisfied(sufficiency, states):
                raise AdaptiveExplorationError("adaptive WAE convergence is not mission-sufficient")
    if data.get("question_states") != states:
        raise AdaptiveExplorationError("adaptive WAE final question-state mismatch")
    if data.get("usage") != usage:
        raise AdaptiveExplorationError("adaptive WAE final usage mismatch")
    expected_status = "exploration-ready" if not iterations else (
        "exploration-in-progress"
        if iterations[-1].get("next_action") == "continue"
        else {
            "replan": "exploration-returned-for-replan",
            "converge": "exploration-converged",
            "return-remediate": "exploration-returned",
            "blocked": "exploration-blocked",
        }[str(iterations[-1].get("next_action"))]
    )
    if data.get("status") != expected_status:
        raise AdaptiveExplorationError("adaptive WAE trace status mismatch")
    expected_reason = "" if not iterations else str(iterations[-1].get("stop_or_return_reason") or "")
    if data.get("stop_or_return_reason") != expected_reason:
        raise AdaptiveExplorationError("adaptive WAE final stop/return reason mismatch")
    if usage["tool_calls"] > context["budget"]["max_tool_calls"]:
        raise AdaptiveExplorationError("adaptive WAE usage exceeds mission tool-call budget")
    if usage["source_expansions"] > context["budget"]["max_source_expansions"]:
        raise AdaptiveExplorationError("adaptive WAE usage exceeds mission source-expansion budget")
    if usage["source_bytes"] > context["budget"]["max_source_bytes"]:
        raise AdaptiveExplorationError("adaptive WAE usage exceeds mission source-byte budget")
    _text(data.get("claim_ceiling"), "adaptive WAE trace claim ceiling", minimum=80)
    fingerprint = _text(data.get("trace_fingerprint"), "adaptive WAE trace fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "trace_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("adaptive WAE trace fingerprint mismatch")
    return data


def _trace_receipt_fingerprints(trace: Mapping[str, Any]) -> set[str]:
    return {
        str(receipt.get("receipt_fingerprint") or "")
        for iteration in trace.get("iterations", [])
        if isinstance(iteration, Mapping)
        for receipt in iteration.get("evidence_receipts", [])
        if isinstance(receipt, Mapping)
        and str(receipt.get("receipt_fingerprint") or "")
    }


def build_candidate_knowledge_delta(
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
    trace: Mapping[str, Any],
    *,
    delta_id: str,
    family_id: str,
    question_ids: Sequence[str],
    knowledge_state: str,
    proposed_action: str,
    candidate_summary: str,
    family_contract_ref: str,
    evidence_receipt_fingerprints: Sequence[str],
) -> dict[str, Any]:
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    validated_trace = validate_wae_trace(
        trace,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )
    if validated_trace["status"] != "exploration-converged":
        raise AdaptiveExplorationError("candidate knowledge delta requires a converged WAE trace")
    normalized_state = str(knowledge_state or "")
    if normalized_state not in CANDIDATE_KNOWLEDGE_STATES:
        raise AdaptiveExplorationError("candidate knowledge state is unsupported")
    normalized_action = str(proposed_action or "")
    if normalized_action not in CANDIDATE_ACTIONS:
        raise AdaptiveExplorationError("candidate knowledge action is unsupported")
    normalized_questions = [
        _identifier(value, "candidate delta question id") for value in question_ids
    ]
    if not normalized_questions or len(normalized_questions) != len(set(normalized_questions)):
        raise AdaptiveExplorationError("candidate knowledge delta requires unique competency question ids")
    known_question_ids = {
        str(row.get("question_id") or "")
        for row in sufficiency["questions"]
        if isinstance(row, Mapping)
    }
    unknown_questions = sorted(set(normalized_questions) - known_question_ids)
    if unknown_questions:
        raise AdaptiveExplorationError(
            "candidate delta references unknown competency questions: "
            + ", ".join(unknown_questions)
        )
    evidence_fps = [
        _text(value, "candidate delta evidence fingerprint", minimum=64, maximum=64)
        for value in evidence_receipt_fingerprints
    ]
    if len(evidence_fps) != len(set(evidence_fps)):
        raise AdaptiveExplorationError("candidate delta evidence fingerprints must be unique")
    trace_fps = _trace_receipt_fingerprints(validated_trace)
    unknown_evidence = sorted(set(evidence_fps) - trace_fps)
    if unknown_evidence:
        raise AdaptiveExplorationError(
            "candidate delta references evidence outside the WAE trace: "
            + ", ".join(unknown_evidence)
        )
    if normalized_state in {"observed-fact", "inferred-knowledge", "conflicting"} and not evidence_fps:
        raise AdaptiveExplorationError(
            "observed/inferred/conflicting candidate knowledge requires acquisition evidence"
        )
    if normalized_action == "record-unknown" and normalized_state != "unknown":
        raise AdaptiveExplorationError("record-unknown action requires unknown knowledge state")
    delta: dict[str, Any] = {
        "schema_version": CANDIDATE_DELTA_SCHEMA_VERSION,
        "status": "candidate-knowledge-delta-ready",
        "authority_mode": ACQUISITION_AUTHORITY_MODE,
        "semantic_authority": False,
        "delta_id": _identifier(delta_id, "candidate delta id"),
        "mission_context_fingerprint": context["context_fingerprint"],
        "plan_fingerprint": validated_plan["plan_fingerprint"],
        "wae_trace_fingerprint": validated_trace["trace_fingerprint"],
        "target": deepcopy(context["target"]),
        "family_id": _identifier(family_id, "candidate delta family id"),
        "family_contract_ref": _text(
            family_contract_ref,
            "candidate delta family contract ref",
            maximum=500,
        ),
        "question_ids": normalized_questions,
        "knowledge_state": normalized_state,
        "proposed_action": normalized_action,
        "candidate_summary": _text(
            candidate_summary,
            "candidate delta summary",
            maximum=2400,
        ),
        "evidence_receipt_fingerprints": sorted(evidence_fps),
        "claim_ceiling": (
            "This delta is a non-authoritative acquisition candidate produced after a converged WAE mission. "
            "It cannot modify durable Project Knowledge or semantic authority until a family-specific authority path revalidates its evidence and semantics."
        ),
    }
    delta["delta_fingerprint"] = _digest(delta)
    return validate_candidate_knowledge_delta(
        delta,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
        trace=validated_trace,
    )


def validate_candidate_knowledge_delta(
    payload: Mapping[str, Any],
    *,
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    validated_trace = validate_wae_trace(
        trace,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )
    if data.get("schema_version") != CANDIDATE_DELTA_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported candidate-knowledge-delta schema")
    if data.get("status") != "candidate-knowledge-delta-ready":
        raise AdaptiveExplorationError("candidate knowledge delta is not ready")
    if data.get("authority_mode") != ACQUISITION_AUTHORITY_MODE or data.get("semantic_authority") is not False:
        raise AdaptiveExplorationError("candidate knowledge delta attempted semantic authority")
    if data.get("mission_context_fingerprint") != context["context_fingerprint"]:
        raise AdaptiveExplorationError("candidate delta mission binding mismatch")
    if data.get("plan_fingerprint") != validated_plan["plan_fingerprint"]:
        raise AdaptiveExplorationError("candidate delta plan binding mismatch")
    if data.get("wae_trace_fingerprint") != validated_trace["trace_fingerprint"]:
        raise AdaptiveExplorationError("candidate delta WAE binding mismatch")
    if data.get("target") != context["target"]:
        raise AdaptiveExplorationError("candidate delta target mismatch")
    if validated_trace["status"] != "exploration-converged":
        raise AdaptiveExplorationError("candidate delta requires converged WAE trace")
    _identifier(data.get("delta_id"), "candidate delta id")
    _identifier(data.get("family_id"), "candidate delta family id")
    question_ids = [
        _identifier(value, "candidate delta question id")
        for value in _array(data.get("question_ids"), "candidate delta question ids", minimum=1)
    ]
    if len(question_ids) != len(set(question_ids)):
        raise AdaptiveExplorationError("candidate delta question ids must be unique")
    known_question_ids = {
        str(row.get("question_id") or "")
        for row in sufficiency["questions"]
        if isinstance(row, Mapping)
    }
    unknown_questions = sorted(set(question_ids) - known_question_ids)
    if unknown_questions:
        raise AdaptiveExplorationError(
            "candidate delta references unknown competency questions: "
            + ", ".join(unknown_questions)
        )
    state = str(data.get("knowledge_state") or "")
    action = str(data.get("proposed_action") or "")
    if state not in CANDIDATE_KNOWLEDGE_STATES or action not in CANDIDATE_ACTIONS:
        raise AdaptiveExplorationError("candidate delta posture is unsupported")
    evidence_fps = [
        _text(value, "candidate delta evidence fingerprint", minimum=64, maximum=64)
        for value in _array(
            data.get("evidence_receipt_fingerprints"),
            "candidate delta evidence fingerprints",
        )
    ]
    if len(evidence_fps) != len(set(evidence_fps)):
        raise AdaptiveExplorationError("candidate delta evidence fingerprints must be unique")
    if set(evidence_fps) - _trace_receipt_fingerprints(validated_trace):
        raise AdaptiveExplorationError("candidate delta evidence is outside WAE trace")
    if state in {"observed-fact", "inferred-knowledge", "conflicting"} and not evidence_fps:
        raise AdaptiveExplorationError("candidate delta evidence is required for this knowledge state")
    if action == "record-unknown" and state != "unknown":
        raise AdaptiveExplorationError("candidate delta record-unknown posture mismatch")
    _text(data.get("family_contract_ref"), "candidate delta family contract ref", maximum=500)
    _text(data.get("candidate_summary"), "candidate delta summary", maximum=2400)
    _text(data.get("claim_ceiling"), "candidate delta claim ceiling", minimum=80)
    fingerprint = _text(data.get("delta_fingerprint"), "candidate delta fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "delta_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("candidate delta fingerprint mismatch")
    return data


def evaluate_candidate_authority_route(
    mission_context: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
    plan: Mapping[str, Any],
    trace: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed at the acquisition/family-authority boundary; never write semantic truth."""
    context = validate_mission_context(mission_context)
    sufficiency = validate_knowledge_sufficiency(
        sufficiency_report,
        mission_context=context,
    )
    validated_plan = validate_mission_exploration_plan(
        plan,
        mission_context=context,
        sufficiency_report=sufficiency,
    )
    validated_trace = validate_wae_trace(
        trace,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
    )
    validated_delta = validate_candidate_knowledge_delta(
        delta,
        mission_context=context,
        sufficiency_report=sufficiency,
        plan=validated_plan,
        trace=validated_trace,
    )
    family_id = str(validated_delta["family_id"])
    route = FAMILY_AUTHORITY_ROUTES.get(family_id, "new-family-contract-required")
    if validated_delta["proposed_action"] == "no-change":
        status = "no-family-update-required"
        review_required = False
    elif route == "derived-only-no-truth-store":
        status = "not-promotable-derived-family"
        review_required = False
    elif route == "new-family-contract-required":
        status = "blocked-no-family-authority-route"
        review_required = True
    else:
        status = "family-authority-review-required"
        review_required = True
    decision: dict[str, Any] = {
        "schema_version": ROUTING_DECISION_SCHEMA_VERSION,
        "status": status,
        "authority_mode": "routing-gate-non-authoritative",
        "semantic_write_performed": False,
        "direct_promotion_allowed": False,
        "family_authority_review_required": review_required,
        "delta_fingerprint": validated_delta["delta_fingerprint"],
        "family_id": family_id,
        "family_authority_route": route,
        "target": deepcopy(context["target"]),
        "claim_ceiling": (
            "This routing gate can only determine whether an acquisition candidate must be handed to an existing family authority, "
            "requires a new explicit family contract, needs no update, or is non-promotable by design. It never writes semantic truth itself."
        ),
    }
    decision["decision_fingerprint"] = _digest(decision)
    return validate_candidate_authority_route(
        decision,
        delta=validated_delta,
        mission_context=context,
    )


def validate_candidate_authority_route(
    payload: Mapping[str, Any],
    *,
    delta: Mapping[str, Any],
    mission_context: Mapping[str, Any],
) -> dict[str, Any]:
    data = dict(payload)
    context = validate_mission_context(mission_context)
    if data.get("schema_version") != ROUTING_DECISION_SCHEMA_VERSION:
        raise AdaptiveExplorationError("unsupported candidate authority-routing schema")
    if data.get("authority_mode") != "routing-gate-non-authoritative":
        raise AdaptiveExplorationError("candidate routing gate attempted semantic authority")
    if data.get("semantic_write_performed") is not False or data.get("direct_promotion_allowed") is not False:
        raise AdaptiveExplorationError("candidate routing gate cannot directly promote semantic truth")
    if data.get("delta_fingerprint") != delta.get("delta_fingerprint"):
        raise AdaptiveExplorationError("candidate routing decision does not bind delta")
    if data.get("target") != context["target"]:
        raise AdaptiveExplorationError("candidate routing decision target mismatch")
    family_id = _identifier(data.get("family_id"), "candidate routing family id")
    route = str(data.get("family_authority_route") or "")
    if route != FAMILY_AUTHORITY_ROUTES.get(family_id, "new-family-contract-required"):
        raise AdaptiveExplorationError("candidate routing family-authority path mismatch")
    action = str(delta.get("proposed_action") or "")
    if action == "no-change":
        expected_status = "no-family-update-required"
        expected_review = False
    elif route == "derived-only-no-truth-store":
        expected_status = "not-promotable-derived-family"
        expected_review = False
    elif route == "new-family-contract-required":
        expected_status = "blocked-no-family-authority-route"
        expected_review = True
    else:
        expected_status = "family-authority-review-required"
        expected_review = True
    if data.get("status") != expected_status:
        raise AdaptiveExplorationError("candidate routing status does not match family/action posture")
    if data.get("family_authority_review_required") is not expected_review:
        raise AdaptiveExplorationError("candidate routing review requirement mismatch")
    _text(data.get("claim_ceiling"), "candidate routing claim ceiling", minimum=80)
    fingerprint = _text(data.get("decision_fingerprint"), "candidate routing fingerprint", minimum=64, maximum=64)
    expected = _digest({key: value for key, value in data.items() if key != "decision_fingerprint"})
    if fingerprint != expected:
        raise AdaptiveExplorationError("candidate routing fingerprint mismatch")
    return data
