"""EKRI v1.0 P5 bounded Flow/Handoff reconstruction and named query.

Flow is not a peer semantic authority or a Flow truth store. A FlowDefinition is
an engineering Object, one bounded handoff is an Occurrence, and routing /
carriage / reliance / continuation semantics are qualified Assertions. The
normal consumer uses ``trace_flow`` and never traverses raw Assertions.

P5 consumes bounded conformance fixtures plus already accepted source
identities. WFF fixture participants are revalidated against independently
verified portable Architecture Memory identities. Non-WFF fixtures use the same
model/query contract without WFF-specific meta-kernel vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .project_assets import ProjectAssetError, verify_project_asset
from .shadow_semantic_substrate import MODEL_VERSION


FIXTURE_SCHEMA_VERSION = "ekri.flow-conformance-fixture.v1"
MODEL_SCHEMA_VERSION = "ekri.flow-semantic-model.v1"
ANSWER_SCHEMA_VERSION = "ekri.flow-query-answer.v1"
MODEL_STATUS = "flow-semantic-model-derived"
ANSWER_STATUS = "flow-query-answered"
AUTHORITY_MODE = "derived-non-authoritative"
MATERIALIZATION_CLASS = "ephemeral-rebuildable-query-model"
QUERY_KIND = "trace-flow"
QUERY_LEVELS = frozenset({"L0", "L1", "L2", "L3"})
BINDING_MODES = frozenset({"architecture-semantic-ids", "self-contained-fixture"})
ROUTE_KINDS = frozenset({"forward", "branch", "stop", "return", "reentry"})
OBJECT_TYPES = frozenset({"Context", "FlowDefinition", "EngineeringStep", "Artifact", "AuthorityReference"})
OCCURRENCE_TYPES = frozenset({"HandoffOccurrence"})
PREDICATES = frozenset(
    {
        "partOfFlow",
        "routesFrom",
        "routesTo",
        "carries",
        "reliesOnAuthority",
        "allowsReliance",
        "hasUnresolvedItem",
        "forbidsAssumption",
        "hasConsumerScope",
        "supportedByEvidence",
        "precedes",
    }
)
COMPILER_VERSION = "ekri.flow-query-compiler.v0.1"
WFF_ARCHITECTURE_PROJECT_ASSET_ID = "wff-v1.6.2-baseline"


class FlowQueryError(RuntimeError):
    """Raised when a Flow/Handoff source, model, or query breaks the P5 contract."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FlowQueryError(f"{label} must be an object")
    return dict(value)


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FlowQueryError(f"{label} must be a list")
    return value


def _text(value: object, label: str, *, minimum: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise FlowQueryError(f"{label} must not be empty")
    return text


def _strings(value: object, label: str, *, minimum: int = 0) -> list[str]:
    rows = [_text(item, f"{label} item") for item in _array(value, label)]
    if len(rows) < minimum:
        raise FlowQueryError(f"{label} requires at least {minimum} item(s)")
    if len(rows) != len(set(rows)):
        raise FlowQueryError(f"{label} contains duplicates")
    return rows


def _record_id(prefix: str, value: object) -> str:
    return f"{prefix}:{_digest(value)[:32]}"


def load_flow_fixture(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve(strict=False)
    if source.is_symlink() or not source.is_file():
        raise FlowQueryError(f"flow fixture must be a safe regular file: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlowQueryError(f"flow fixture cannot be read: {exc}") from exc
    return validate_flow_fixture(payload)


def _validate_external_sources(
    repository_root: Path,
    source_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    root = repository_root.resolve(strict=False)
    for raw in _array(source_context.get("external_sources"), "source_context.external_sources"):
        row = _mapping(raw, "external source")
        relative = _text(row.get("path"), "external source path")
        candidate = (root / relative).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FlowQueryError(f"external source escapes repository root: {relative}") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise FlowQueryError(f"external source must be a safe regular file: {relative}")
        raw_bytes = candidate.read_bytes()
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        expected_sha = _text(row.get("sha256"), f"external source {relative} sha256")
        if actual_sha != expected_sha:
            raise FlowQueryError(f"external source digest mismatch: {relative}")
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FlowQueryError(f"external source must be UTF-8 text: {relative}") from exc
        tokens = _strings(row.get("required_tokens"), f"external source {relative} required_tokens", minimum=1)
        missing = [token for token in tokens if token not in text]
        if missing:
            raise FlowQueryError(
                f"external source lost required semantic token(s): {relative}: {', '.join(missing)}"
            )
        receipts.append(
            {
                "semantic_identity": _text(
                    row.get("semantic_identity"),
                    f"external source {relative} semantic_identity",
                ),
                "path": relative,
                "sha256": actual_sha,
                "required_tokens": tokens,
            }
        )
    return receipts


def _known_architecture_ids(
    repository_root: Path,
    *,
    asset_id: str = WFF_ARCHITECTURE_PROJECT_ASSET_ID,
) -> set[str]:
    try:
        asset = verify_project_asset(repository_root, asset_id=asset_id)
    except ProjectAssetError as exc:
        raise FlowQueryError(
            f"WFF flow fixture requires verified portable Architecture knowledge: {exc}"
        ) from exc
    rows = _array(
        asset.architecture_memory.get("system_architecture_tree"),
        "verified project Architecture nodes",
    )
    result = {
        _text(_mapping(row, "Architecture node").get("id"), "Architecture node id")
        for row in rows
    }
    if not result:
        raise FlowQueryError("verified portable Architecture knowledge contains no semantic IDs")
    return result


def validate_flow_fixture(payload: Mapping[str, Any]) -> dict[str, Any]:
    fixture = _copy(_mapping(payload, "flow fixture"))
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise FlowQueryError("unsupported flow fixture schema")
    if fixture.get("status") != "bounded-conformance-fixture":
        raise FlowQueryError("flow fixture status must remain bounded-conformance-fixture")
    fixture_id = _text(fixture.get("fixture_id"), "fixture_id")
    _text(fixture.get("profile_id"), "profile_id")
    binding_mode = _text(fixture.get("binding_mode"), "binding_mode")
    if binding_mode not in BINDING_MODES:
        raise FlowQueryError(f"unsupported flow binding_mode: {binding_mode}")
    source_context = _mapping(fixture.get("source_context"), "source_context")
    _text(source_context.get("context_id"), "source_context.context_id")
    _text(source_context.get("kind"), "source_context.kind")
    _text(source_context.get("semantic_identity"), "source_context.semantic_identity")
    _array(source_context.get("external_sources"), "source_context.external_sources")

    definition = _mapping(fixture.get("flow_definition"), "flow_definition")
    flow_id = _text(definition.get("id"), "flow_definition.id")
    _text(definition.get("name"), "flow_definition.name")

    object_rows: list[tuple[str, str]] = []
    for key, expected_type in (
        ("participants", "EngineeringStep"),
        ("artifacts", "Artifact"),
        ("authority_refs", "AuthorityReference"),
    ):
        rows = _array(fixture.get(key), key)
        if not rows:
            raise FlowQueryError(f"{key} must not be empty")
        for raw in rows:
            row = _mapping(raw, f"{key} row")
            semantic_id = _text(row.get("id"), f"{key} id")
            _text(row.get("name"), f"{key} name")
            concept_type = _text(row.get("concept_type"), f"{key} concept_type")
            if concept_type != expected_type or concept_type not in OBJECT_TYPES:
                raise FlowQueryError(f"{key} uses unsupported general concept_type: {concept_type}")
            object_rows.append((semantic_id, key))
    object_ids = [item[0] for item in object_rows]
    reserved_ids = {
        _text(source_context.get("context_id"), "context_id"),
        flow_id,
    }
    duplicates = sorted({item for item in object_ids if object_ids.count(item) > 1})
    if duplicates or reserved_ids.intersection(object_ids):
        raise FlowQueryError(
            "flow fixture object identities collide: "
            + ", ".join(duplicates or sorted(reserved_ids.intersection(object_ids)))
        )
    known_object_ids = set(object_ids) | reserved_ids

    handoffs = _array(fixture.get("handoffs"), "handoffs")
    if not handoffs:
        raise FlowQueryError("flow fixture requires at least one handoff")
    occurrence_ids: list[str] = []
    normalized_handoffs: list[dict[str, Any]] = []
    participant_ids = {item[0] for item in object_rows if item[1] == "participants"}
    artifact_ids = {item[0] for item in object_rows if item[1] == "artifacts"}
    authority_ids = {item[0] for item in object_rows if item[1] == "authority_refs"}
    for raw in handoffs:
        row = _mapping(raw, "handoff")
        occurrence_id = _text(row.get("id"), "handoff id")
        if occurrence_id in occurrence_ids or occurrence_id in known_object_ids:
            raise FlowQueryError(f"duplicate/colliding handoff id: {occurrence_id}")
        occurrence_ids.append(occurrence_id)
        route_kind = _text(row.get("route_kind"), f"handoff {occurrence_id} route_kind")
        if route_kind not in ROUTE_KINDS:
            raise FlowQueryError(f"unsupported route_kind for {occurrence_id}: {route_kind}")
        from_ref = _text(row.get("from_ref"), f"handoff {occurrence_id} from_ref")
        to_ref = _text(row.get("to_ref"), f"handoff {occurrence_id} to_ref")
        if from_ref not in participant_ids or to_ref not in participant_ids:
            raise FlowQueryError(f"handoff {occurrence_id} routes outside declared participants")
        carried_refs = _strings(row.get("carried_refs"), f"handoff {occurrence_id} carried_refs", minimum=1)
        if not set(carried_refs) <= artifact_ids:
            raise FlowQueryError(f"handoff {occurrence_id} carries unknown artifact")
        authority_refs = _strings(row.get("authority_refs"), f"handoff {occurrence_id} authority_refs", minimum=1)
        if not set(authority_refs) <= authority_ids:
            raise FlowQueryError(f"handoff {occurrence_id} references unknown authority")
        allowed_reliance = _strings(row.get("allowed_reliance"), f"handoff {occurrence_id} allowed_reliance", minimum=1)
        unresolved_items = _strings(row.get("unresolved_items"), f"handoff {occurrence_id} unresolved_items")
        forbidden_assumptions = _strings(
            row.get("forbidden_assumptions"),
            f"handoff {occurrence_id} forbidden_assumptions",
            minimum=1,
        )
        consumer_scope = _strings(row.get("consumer_scope"), f"handoff {occurrence_id} consumer_scope", minimum=1)
        evidence_refs = _strings(row.get("evidence_refs"), f"handoff {occurrence_id} evidence_refs", minimum=1)
        next_ids = _strings(row.get("next_occurrence_ids"), f"handoff {occurrence_id} next_occurrence_ids")
        if route_kind == "stop" and next_ids:
            raise FlowQueryError(f"stop handoff {occurrence_id} cannot have successors")
        if route_kind == "branch" and len(next_ids) < 2:
            raise FlowQueryError(f"branch handoff {occurrence_id} requires at least two successors")
        if route_kind in {"forward", "return", "reentry"} and len(next_ids) > 1:
            raise FlowQueryError(f"{route_kind} handoff {occurrence_id} has too many successors")
        normalized_handoffs.append(
            {
                "id": occurrence_id,
                "route_kind": route_kind,
                "from_ref": from_ref,
                "to_ref": to_ref,
                "carried_refs": carried_refs,
                "authority_refs": authority_refs,
                "allowed_reliance": allowed_reliance,
                "unresolved_items": unresolved_items,
                "forbidden_assumptions": forbidden_assumptions,
                "consumer_scope": consumer_scope,
                "evidence_refs": evidence_refs,
                "next_occurrence_ids": next_ids,
            }
        )
    occurrence_set = set(occurrence_ids)
    for row in normalized_handoffs:
        unknown_next = sorted(set(row["next_occurrence_ids"]) - occurrence_set)
        if unknown_next:
            raise FlowQueryError(
                f"handoff {row['id']} references unknown successor(s): {', '.join(unknown_next)}"
            )
    entries = _strings(fixture.get("entry_occurrence_ids"), "entry_occurrence_ids", minimum=1)
    if not set(entries) <= occurrence_set:
        raise FlowQueryError("entry_occurrence_ids reference unknown handoff occurrences")
    _text(fixture.get("claim_ceiling"), "claim_ceiling", minimum=80)
    fixture["handoffs"] = normalized_handoffs
    fixture["entry_occurrence_ids"] = entries
    return fixture


def _qualifications(context_ref: str, *, source_family: str) -> dict[str, Any]:
    return {
        "semantic_modality": "descriptive",
        "epistemic_posture": "observed",
        "normative_posture": "not-specified",
        "validity": "fixture-context-bound",
        "scope": "bounded-flow-handoff-conformance",
        "completeness": "fixture-bounded",
        "reliance": "conformance-only",
        "authority_mode": AUTHORITY_MODE,
        "semantic_authority": False,
        "context_ref": context_ref,
        "source_family": source_family,
    }


def _assertion(
    subject_ref: str,
    predicate: str,
    *,
    context_ref: str,
    source_family: str,
    object_ref: str = "",
    value: str = "",
) -> dict[str, Any]:
    if predicate not in PREDICATES:
        raise FlowQueryError(f"unsupported Flow predicate: {predicate}")
    if bool(object_ref) == bool(value):
        raise FlowQueryError("Flow assertion requires exactly one object_ref or value")
    proposition = {
        "subject_ref": subject_ref,
        "predicate": predicate,
        "object_ref": object_ref,
        "value": value,
        "context_ref": context_ref,
        "source_family": source_family,
    }
    return {
        "record_id": _record_id("flow-assertion", proposition),
        "statement_key": _digest(
            {
                "subject_ref": subject_ref,
                "predicate": predicate,
                "object_ref": object_ref,
                "value": value,
            }
        ),
        "subject_ref": subject_ref,
        "predicate": predicate,
        "object_ref": object_ref,
        "value": value,
        "qualifications": _qualifications(context_ref, source_family=source_family),
    }


def _model_semantic_basis(model: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(model.get("source"), "model.source")
    return {
        "model_version": model.get("model_version"),
        "source": {
            "fixture_id": source.get("fixture_id"),
            "profile_id": source.get("profile_id"),
            "binding_mode": source.get("binding_mode"),
            "context_id": source.get("context_id"),
            "context_semantic_identity": source.get("context_semantic_identity"),
            "external_semantic_identities": list(source.get("external_semantic_identities", [])),
            "architecture_binding_verified": source.get("architecture_binding_verified"),
        },
        "flow_definition_ref": model.get("flow_definition_ref"),
        "entry_occurrence_ids": list(model.get("entry_occurrence_ids", [])),
        "objects": _copy(model.get("objects", [])),
        "occurrences": _copy(model.get("occurrences", [])),
        "assertions": _copy(model.get("assertions", [])),
        "claim_ceiling": model.get("claim_ceiling"),
    }


def _projection_basis(model: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(model.get("source"), "model.source")
    return {
        "semantic_fingerprint": model.get("semantic_fingerprint"),
        "compiler_version": model.get("compiler_version"),
        "external_source_receipts": _copy(source.get("external_source_receipts", [])),
    }


def compile_flow_fixture(
    fixture_payload: Mapping[str, Any],
    *,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    fixture = validate_flow_fixture(fixture_payload)
    root = Path(repository_root).expanduser().resolve(strict=False) if repository_root is not None else None
    source_context = _mapping(fixture["source_context"], "source_context")
    external_semantic_ids = sorted(
        _text(_mapping(row, "external source").get("semantic_identity"), "external semantic identity")
        for row in _array(source_context.get("external_sources"), "external_sources")
    )
    external_receipts: list[dict[str, Any]] = []
    known_architecture_ids: set[str] | None = None
    if root is not None:
        external_receipts = _validate_external_sources(root, source_context)
        if fixture["binding_mode"] == "architecture-semantic-ids":
            known_architecture_ids = _known_architecture_ids(root)
    elif fixture["binding_mode"] == "architecture-semantic-ids":
        raise FlowQueryError(
            "architecture-semantic-ids fixture requires repository_root for independent identity verification"
        )
    if known_architecture_ids is not None:
        participant_ids = {str(row["id"]) for row in fixture["participants"]}
        unknown = sorted(participant_ids - known_architecture_ids)
        if unknown:
            raise FlowQueryError(
                "WFF Flow fixture references unknown Architecture semantic IDs: " + ", ".join(unknown)
            )

    context_id = _text(source_context.get("context_id"), "context_id")
    objects: list[dict[str, Any]] = [
        {
            "semantic_id": context_id,
            "types": ["Context"],
            "roles": ["SourceContext"],
            "identity": {
                "kind": source_context["kind"],
                "semantic_identity": source_context["semantic_identity"],
            },
            "contexts": [context_id],
        },
        {
            "semantic_id": fixture["flow_definition"]["id"],
            "types": ["FlowDefinition"],
            "roles": ["FlowDefinition"],
            "identity": {"name": fixture["flow_definition"]["name"]},
            "contexts": [context_id],
        },
    ]
    for key in ("participants", "artifacts", "authority_refs"):
        for row in fixture[key]:
            objects.append(
                {
                    "semantic_id": row["id"],
                    "types": [row["concept_type"]],
                    "roles": [row["concept_type"]],
                    "identity": {"name": row["name"]},
                    "contexts": [context_id],
                }
            )

    occurrences = [
        {
            "semantic_id": row["id"],
            "occurrence_type": "HandoffOccurrence",
            "occurrence_posture": "fixture-conformance",
            "route_kind": row["route_kind"],
            "contexts": [context_id],
        }
        for row in fixture["handoffs"]
    ]
    assertions: list[dict[str, Any]] = []
    flow_id = fixture["flow_definition"]["id"]
    for row in fixture["handoffs"]:
        occurrence_id = row["id"]
        assertions.extend(
            [
                _assertion(
                    occurrence_id,
                    "partOfFlow",
                    context_ref=context_id,
                    source_family="handoff-definition",
                    object_ref=flow_id,
                ),
                _assertion(
                    occurrence_id,
                    "routesFrom",
                    context_ref=context_id,
                    source_family="handoff-routing",
                    object_ref=row["from_ref"],
                ),
                _assertion(
                    occurrence_id,
                    "routesTo",
                    context_ref=context_id,
                    source_family="handoff-routing",
                    object_ref=row["to_ref"],
                ),
            ]
        )
        for ref in row["carried_refs"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "carries",
                    context_ref=context_id,
                    source_family="handoff-carriage",
                    object_ref=ref,
                )
            )
        for ref in row["authority_refs"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "reliesOnAuthority",
                    context_ref=context_id,
                    source_family="handoff-authority",
                    object_ref=ref,
                )
            )
        for value in row["allowed_reliance"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "allowsReliance",
                    context_ref=context_id,
                    source_family="handoff-reliance",
                    value=value,
                )
            )
        for value in row["unresolved_items"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "hasUnresolvedItem",
                    context_ref=context_id,
                    source_family="handoff-uncertainty",
                    value=value,
                )
            )
        for value in row["forbidden_assumptions"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "forbidsAssumption",
                    context_ref=context_id,
                    source_family="handoff-reliance",
                    value=value,
                )
            )
        for value in row["consumer_scope"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "hasConsumerScope",
                    context_ref=context_id,
                    source_family="handoff-reliance",
                    value=value,
                )
            )
        for value in row["evidence_refs"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "supportedByEvidence",
                    context_ref=context_id,
                    source_family="handoff-evidence",
                    value=value,
                )
            )
        for ref in row["next_occurrence_ids"]:
            assertions.append(
                _assertion(
                    occurrence_id,
                    "precedes",
                    context_ref=context_id,
                    source_family="flow-order",
                    object_ref=ref,
                )
            )

    model = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "status": MODEL_STATUS,
        "authority_mode": AUTHORITY_MODE,
        "materialization_class": MATERIALIZATION_CLASS,
        "compiler_version": COMPILER_VERSION,
        "source": {
            "fixture_id": fixture["fixture_id"],
            "profile_id": fixture["profile_id"],
            "binding_mode": fixture["binding_mode"],
            "context_id": context_id,
            "context_semantic_identity": source_context["semantic_identity"],
            "external_semantic_identities": external_semantic_ids,
            "external_source_receipts": external_receipts,
            "architecture_binding_verified": known_architecture_ids is not None,
        },
        "flow_definition_ref": flow_id,
        "entry_occurrence_ids": list(fixture["entry_occurrence_ids"]),
        "objects": sorted(objects, key=lambda row: row["semantic_id"]),
        "occurrences": sorted(occurrences, key=lambda row: row["semantic_id"]),
        "assertions": sorted(assertions, key=lambda row: row["record_id"]),
        "summary": {
            "object_count": len(objects),
            "occurrence_count": len(occurrences),
            "assertion_count": len(assertions),
            "route_kind_counts": {
                kind: sum(1 for row in occurrences if row["route_kind"] == kind)
                for kind in sorted(ROUTE_KINDS)
            },
            "unresolved_item_count": sum(len(row["unresolved_items"]) for row in fixture["handoffs"]),
        },
        "semantic_fingerprint": "",
        "projection_fingerprint": "",
        "claim_ceiling": fixture["claim_ceiling"],
    }
    model["semantic_fingerprint"] = _digest(_model_semantic_basis(model))
    model["projection_fingerprint"] = _digest(_projection_basis(model))
    return validate_flow_model(model)


def _assertion_groups(model: Mapping[str, Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for raw in _array(model.get("assertions"), "model.assertions"):
        row = _mapping(raw, "Flow assertion")
        result.setdefault(str(row["subject_ref"]), {}).setdefault(str(row["predicate"]), []).append(row)
    return result


def _object_targets(groups: Mapping[str, list[dict[str, Any]]], predicate: str) -> list[str]:
    return sorted(_text(row.get("object_ref"), f"{predicate} object_ref") for row in groups.get(predicate, []))


def _values(groups: Mapping[str, list[dict[str, Any]]], predicate: str) -> list[str]:
    return sorted(_text(row.get("value"), f"{predicate} value") for row in groups.get(predicate, []))


def _single_target(groups: Mapping[str, list[dict[str, Any]]], predicate: str, label: str) -> str:
    values = _object_targets(groups, predicate)
    if len(values) != 1:
        raise FlowQueryError(f"{label} requires exactly one {predicate} assertion")
    return values[0]


def _validate_graph(
    occurrences: Mapping[str, Mapping[str, Any]],
    adjacency: Mapping[str, list[str]],
    entries: Sequence[str],
) -> None:
    reachable: set[str] = set()
    queue = list(entries)
    while queue:
        current = queue.pop(0)
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(adjacency.get(current, []))
    missing = sorted(set(occurrences) - reachable)
    if missing:
        raise FlowQueryError("Flow contains unreachable handoff occurrence(s): " + ", ".join(missing))

    def visit(node: str, stack: list[str], visited_edges: set[tuple[str, str]]) -> None:
        for target in adjacency.get(node, []):
            edge = (node, target)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
            if target in stack:
                route_kind = str(occurrences[node].get("route_kind") or "")
                if route_kind not in {"return", "reentry"}:
                    raise FlowQueryError(
                        f"Flow cycle is allowed only through return/reentry occurrence: {node} -> {target}"
                    )
                continue
            visit(target, [*stack, target], visited_edges)

    visited_edges: set[tuple[str, str]] = set()
    for entry in entries:
        visit(entry, [entry], visited_edges)


def validate_flow_model(payload: Mapping[str, Any]) -> dict[str, Any]:
    model = _copy(_mapping(payload, "Flow semantic model"))
    if model.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise FlowQueryError("unsupported Flow semantic model schema")
    if model.get("model_version") != MODEL_VERSION:
        raise FlowQueryError("Flow semantic model uses unsupported shared model_version")
    if model.get("status") != MODEL_STATUS:
        raise FlowQueryError("Flow semantic model status mismatch")
    if model.get("authority_mode") != AUTHORITY_MODE:
        raise FlowQueryError("Flow semantic model cannot become semantic authority in P5")
    if model.get("materialization_class") != MATERIALIZATION_CLASS:
        raise FlowQueryError("Flow semantic model must remain ephemeral/rebuildable")
    if model.get("compiler_version") != COMPILER_VERSION:
        raise FlowQueryError("Flow semantic model compiler identity mismatch")
    source = _mapping(model.get("source"), "model.source")
    _text(source.get("fixture_id"), "model.source.fixture_id")
    _text(source.get("profile_id"), "model.source.profile_id")
    if _text(source.get("binding_mode"), "model.source.binding_mode") not in BINDING_MODES:
        raise FlowQueryError("Flow model binding_mode is unsupported")
    context_id = _text(source.get("context_id"), "model.source.context_id")
    _text(source.get("context_semantic_identity"), "model.source.context_semantic_identity")
    external_semantic_ids = _strings(
        source.get("external_semantic_identities"),
        "model.source.external_semantic_identities",
    )
    if external_semantic_ids != sorted(external_semantic_ids):
        raise FlowQueryError("Flow external semantic identities must use canonical sorted order")
    if not isinstance(source.get("architecture_binding_verified"), bool):
        raise FlowQueryError("Flow model architecture binding verification flag must be boolean")

    objects = [_mapping(row, "Flow Object") for row in _array(model.get("objects"), "objects")]
    object_ids: set[str] = set()
    for row in objects:
        semantic_id = _text(row.get("semantic_id"), "Flow Object semantic_id")
        if semantic_id in object_ids:
            raise FlowQueryError(f"duplicate Flow Object semantic_id: {semantic_id}")
        object_ids.add(semantic_id)
        types = _strings(row.get("types"), f"Flow Object {semantic_id} types", minimum=1)
        if len(types) != 1 or types[0] not in OBJECT_TYPES:
            raise FlowQueryError(f"Flow Object {semantic_id} uses unsupported type")
        if _strings(row.get("contexts"), f"Flow Object {semantic_id} contexts", minimum=1) != [context_id]:
            raise FlowQueryError(f"Flow Object {semantic_id} context binding mismatch")
    flow_ref = _text(model.get("flow_definition_ref"), "flow_definition_ref")
    flow_objects = [row for row in objects if row["semantic_id"] == flow_ref and row["types"] == ["FlowDefinition"]]
    if len(flow_objects) != 1:
        raise FlowQueryError("Flow model must contain exactly one referenced FlowDefinition Object")
    context_objects = [row for row in objects if row["semantic_id"] == context_id and row["types"] == ["Context"]]
    if len(context_objects) != 1:
        raise FlowQueryError("Flow model must contain its source Context Object")

    occurrences_list = [_mapping(row, "Flow Occurrence") for row in _array(model.get("occurrences"), "occurrences")]
    occurrences: dict[str, dict[str, Any]] = {}
    for row in occurrences_list:
        semantic_id = _text(row.get("semantic_id"), "Flow Occurrence semantic_id")
        if semantic_id in occurrences or semantic_id in object_ids:
            raise FlowQueryError(f"duplicate/colliding Flow Occurrence semantic_id: {semantic_id}")
        if row.get("occurrence_type") not in OCCURRENCE_TYPES:
            raise FlowQueryError(f"unsupported Flow Occurrence type: {semantic_id}")
        if row.get("occurrence_posture") != "fixture-conformance":
            raise FlowQueryError(f"Flow Occurrence {semantic_id} must remain fixture-conformance")
        route_kind = _text(row.get("route_kind"), f"Flow Occurrence {semantic_id} route_kind")
        if route_kind not in ROUTE_KINDS:
            raise FlowQueryError(f"unsupported route_kind: {semantic_id}")
        if _strings(row.get("contexts"), f"Flow Occurrence {semantic_id} contexts", minimum=1) != [context_id]:
            raise FlowQueryError(f"Flow Occurrence {semantic_id} context binding mismatch")
        occurrences[semantic_id] = row
    if not occurrences:
        raise FlowQueryError("Flow model requires at least one HandoffOccurrence")

    assertion_rows = [_mapping(row, "Flow Assertion") for row in _array(model.get("assertions"), "assertions")]
    seen_records: set[str] = set()
    for row in assertion_rows:
        record_id = _text(row.get("record_id"), "Flow Assertion record_id")
        if record_id in seen_records:
            raise FlowQueryError(f"duplicate Flow Assertion record_id: {record_id}")
        seen_records.add(record_id)
        subject_ref = _text(row.get("subject_ref"), "Flow Assertion subject_ref")
        if subject_ref not in occurrences:
            raise FlowQueryError("P5 Flow Assertions must be scoped to HandoffOccurrences")
        predicate = _text(row.get("predicate"), "Flow Assertion predicate")
        if predicate not in PREDICATES:
            raise FlowQueryError(f"Flow Assertion uses unsupported predicate: {predicate}")
        object_ref = str(row.get("object_ref") or "")
        value = str(row.get("value") or "")
        if bool(object_ref) == bool(value):
            raise FlowQueryError("Flow Assertion must contain exactly one object_ref or value")
        if object_ref and object_ref not in object_ids and object_ref not in occurrences:
            raise FlowQueryError(f"Flow Assertion references unknown object/occurrence: {object_ref}")
        q = _mapping(row.get("qualifications"), "Flow Assertion qualifications")
        if q.get("authority_mode") != AUTHORITY_MODE or q.get("semantic_authority") is not False:
            raise FlowQueryError("P5 Flow Assertion cannot carry semantic authority")
        if q.get("context_ref") != context_id:
            raise FlowQueryError("Flow Assertion context binding mismatch")

    groups = _assertion_groups(model)
    adjacency: dict[str, list[str]] = {}
    for occurrence_id, occurrence in occurrences.items():
        predicates = groups.get(occurrence_id, {})
        if _single_target(predicates, "partOfFlow", occurrence_id) != flow_ref:
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} is not bound to the declared FlowDefinition")
        _single_target(predicates, "routesFrom", occurrence_id)
        _single_target(predicates, "routesTo", occurrence_id)
        if not _object_targets(predicates, "carries"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} carries no artifact")
        if not _object_targets(predicates, "reliesOnAuthority"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} has no authority reference")
        if not _values(predicates, "allowsReliance"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} has no allowed reliance")
        if not _values(predicates, "forbidsAssumption"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} has no forbidden assumption")
        if not _values(predicates, "hasConsumerScope"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} has no consumer scope")
        if not _values(predicates, "supportedByEvidence"):
            raise FlowQueryError(f"Flow Occurrence {occurrence_id} has no evidence reference")
        adjacency[occurrence_id] = _object_targets(predicates, "precedes")
        route_kind = str(occurrence["route_kind"])
        if route_kind == "stop" and adjacency[occurrence_id]:
            raise FlowQueryError(f"stop occurrence {occurrence_id} has successors")
        if route_kind == "branch" and len(adjacency[occurrence_id]) < 2:
            raise FlowQueryError(f"branch occurrence {occurrence_id} lacks two successors")
        if route_kind in {"forward", "return", "reentry"} and len(adjacency[occurrence_id]) > 1:
            raise FlowQueryError(f"{route_kind} occurrence {occurrence_id} has too many successors")
    entries = _strings(model.get("entry_occurrence_ids"), "entry_occurrence_ids", minimum=1)
    if not set(entries) <= set(occurrences):
        raise FlowQueryError("Flow model entry occurrence is missing")
    _validate_graph(occurrences, adjacency, entries)

    summary = _mapping(model.get("summary"), "model.summary")
    if int(summary.get("object_count", -1)) != len(objects):
        raise FlowQueryError("Flow model object_count mismatch")
    if int(summary.get("occurrence_count", -1)) != len(occurrences):
        raise FlowQueryError("Flow model occurrence_count mismatch")
    if int(summary.get("assertion_count", -1)) != len(assertion_rows):
        raise FlowQueryError("Flow model assertion_count mismatch")
    expected_route_counts = {
        kind: sum(1 for row in occurrences.values() if row["route_kind"] == kind)
        for kind in sorted(ROUTE_KINDS)
    }
    if summary.get("route_kind_counts") != expected_route_counts:
        raise FlowQueryError("Flow model route_kind_counts mismatch")
    expected_unresolved = sum(len(_values(groups.get(item, {}), "hasUnresolvedItem")) for item in occurrences)
    if int(summary.get("unresolved_item_count", -1)) != expected_unresolved:
        raise FlowQueryError("Flow model unresolved_item_count mismatch")
    semantic_fingerprint = _text(model.get("semantic_fingerprint"), "semantic_fingerprint")
    projection_fingerprint = _text(model.get("projection_fingerprint"), "projection_fingerprint")
    if len(semantic_fingerprint) != 64 or len(projection_fingerprint) != 64:
        raise FlowQueryError("Flow fingerprints must be SHA-256 hex strings")
    _text(model.get("claim_ceiling"), "claim_ceiling", minimum=80)
    if semantic_fingerprint != _digest(_model_semantic_basis(model)):
        raise FlowQueryError("Flow semantic fingerprint does not match canonical model semantics")
    if projection_fingerprint != _digest(_projection_basis(model)):
        raise FlowQueryError("Flow projection fingerprint does not match exact projection provenance")
    return model


@dataclass(frozen=True)
class FlowQueryService:
    """Verified named-query facade over one bounded non-authoritative Flow model."""

    model: dict[str, Any]

    @classmethod
    def from_fixture(
        cls,
        fixture_payload: Mapping[str, Any],
        *,
        repository_root: str | Path | None = None,
    ) -> "FlowQueryService":
        return cls(compile_flow_fixture(fixture_payload, repository_root=repository_root))

    @classmethod
    def from_fixture_path(
        cls,
        path: str | Path,
        *,
        repository_root: str | Path | None = None,
    ) -> "FlowQueryService":
        return cls.from_fixture(load_flow_fixture(path), repository_root=repository_root)

    def trace_flow(self, *, disclosure_level: str = "L1", max_depth: int = 64) -> dict[str, Any]:
        return trace_flow(self, disclosure_level=disclosure_level, max_depth=max_depth)


def _verify_service(service: FlowQueryService) -> dict[str, Any]:
    if not isinstance(service, FlowQueryService):
        raise FlowQueryError("trace_flow requires a verified FlowQueryService")
    return validate_flow_model(service.model)


def _occurrence_detail(
    occurrence_id: str,
    occurrence: Mapping[str, Any],
    groups: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    *,
    disclosure_level: str,
) -> dict[str, Any]:
    predicates = groups[occurrence_id]
    row: dict[str, Any] = {
        "occurrence_id": occurrence_id,
        "route_kind": occurrence["route_kind"],
        "from_ref": _single_target(predicates, "routesFrom", occurrence_id),
        "to_ref": _single_target(predicates, "routesTo", occurrence_id),
        "next_occurrence_ids": _object_targets(predicates, "precedes"),
    }
    if disclosure_level in {"L2", "L3"}:
        row.update(
            {
                "carried_refs": _object_targets(predicates, "carries"),
                "authority_refs": _object_targets(predicates, "reliesOnAuthority"),
                "allowed_reliance": _values(predicates, "allowsReliance"),
                "unresolved_items": _values(predicates, "hasUnresolvedItem"),
                "forbidden_assumptions": _values(predicates, "forbidsAssumption"),
                "consumer_scope": _values(predicates, "hasConsumerScope"),
            }
        )
    if disclosure_level == "L3":
        row["evidence_refs"] = _values(predicates, "supportedByEvidence")
    return row


def trace_flow(
    service: FlowQueryService,
    *,
    disclosure_level: str = "L1",
    max_depth: int = 64,
) -> dict[str, Any]:
    model = _verify_service(service)
    if disclosure_level not in QUERY_LEVELS:
        raise FlowQueryError(f"unsupported Flow disclosure level: {disclosure_level}")
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 256:
        raise FlowQueryError("max_depth must be an integer between 1 and 256")
    occurrences = {
        str(row["semantic_id"]): row
        for row in [_mapping(raw, "Flow Occurrence") for raw in model["occurrences"]]
    }
    groups = _assertion_groups(model)
    entries = list(model["entry_occurrence_ids"])
    queue: list[tuple[str, int]] = [(item, 0) for item in entries]
    visited: set[str] = set()
    ordered: list[str] = []
    truncated = False
    while queue:
        current, depth = queue.pop(0)
        if current in visited:
            continue
        if depth >= max_depth:
            truncated = True
            continue
        visited.add(current)
        ordered.append(current)
        for target in _object_targets(groups[current], "precedes"):
            queue.append((target, depth + 1))
    if len(visited) != len(occurrences) and not truncated:
        raise FlowQueryError("trace_flow did not reach every validated Flow occurrence")

    summary = _copy(model["summary"])
    summary.update(
        {
            "visited_occurrence_count": len(visited),
            "truncated": truncated,
            "branch_occurrence_ids": sorted(
                item for item in visited if occurrences[item]["route_kind"] == "branch"
            ),
            "return_occurrence_ids": sorted(
                item for item in visited if occurrences[item]["route_kind"] == "return"
            ),
            "reentry_occurrence_ids": sorted(
                item for item in visited if occurrences[item]["route_kind"] == "reentry"
            ),
            "stop_occurrence_ids": sorted(
                item for item in visited if occurrences[item]["route_kind"] == "stop"
            ),
        }
    )
    answer: dict[str, Any] = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": ANSWER_STATUS,
        "query_kind": QUERY_KIND,
        "disclosure_level": disclosure_level,
        "authority_mode": AUTHORITY_MODE,
        "source": {
            "fixture_id": model["source"]["fixture_id"],
            "profile_id": model["source"]["profile_id"],
            "context_id": model["source"]["context_id"],
            "context_semantic_identity": model["source"]["context_semantic_identity"],
            "semantic_fingerprint": model["semantic_fingerprint"],
            "projection_fingerprint": model["projection_fingerprint"],
        },
        "resolution": {
            "status": "matched",
            "flow_definition_ref": model["flow_definition_ref"],
            "entry_occurrence_ids": entries,
        },
        "answer": {
            "summary": summary,
        },
        "claim_ceiling": model["claim_ceiling"],
    }
    if disclosure_level in {"L1", "L2", "L3"}:
        answer["answer"]["route"] = [
            _occurrence_detail(item, occurrences[item], groups, disclosure_level=disclosure_level)
            for item in ordered
        ]
    if disclosure_level == "L3":
        answer["answer"]["source_provenance"] = {
            "binding_mode": model["source"]["binding_mode"],
            "architecture_binding_verified": model["source"]["architecture_binding_verified"],
            "external_source_receipts": _copy(model["source"]["external_source_receipts"]),
        }
    return validate_flow_query_answer(answer)


def validate_flow_query_answer(payload: Mapping[str, Any]) -> dict[str, Any]:
    answer = _copy(_mapping(payload, "Flow query answer"))
    if answer.get("schema_version") != ANSWER_SCHEMA_VERSION:
        raise FlowQueryError("unsupported Flow query answer schema")
    if answer.get("status") != ANSWER_STATUS or answer.get("query_kind") != QUERY_KIND:
        raise FlowQueryError("Flow query answer status/kind mismatch")
    level = _text(answer.get("disclosure_level"), "disclosure_level")
    if level not in QUERY_LEVELS:
        raise FlowQueryError("Flow query answer disclosure level is invalid")
    if answer.get("authority_mode") != AUTHORITY_MODE:
        raise FlowQueryError("Flow query answer cannot become semantic authority")
    source = _mapping(answer.get("source"), "answer.source")
    _text(source.get("fixture_id"), "answer.source.fixture_id")
    _text(source.get("profile_id"), "answer.source.profile_id")
    _text(source.get("context_id"), "answer.source.context_id")
    for key in ("semantic_fingerprint", "projection_fingerprint"):
        if len(_text(source.get(key), f"answer.source.{key}")) != 64:
            raise FlowQueryError(f"answer.source.{key} must be a SHA-256 fingerprint")
    resolution = _mapping(answer.get("resolution"), "answer.resolution")
    if resolution.get("status") != "matched":
        raise FlowQueryError("P5 trace_flow only returns a matched bounded Flow")
    _text(resolution.get("flow_definition_ref"), "flow_definition_ref")
    _strings(resolution.get("entry_occurrence_ids"), "entry_occurrence_ids", minimum=1)
    body = _mapping(answer.get("answer"), "answer.answer")
    summary = _mapping(body.get("summary"), "answer.summary")
    if not isinstance(summary.get("truncated"), bool):
        raise FlowQueryError("Flow query summary truncated must be boolean")
    if level == "L0" and "route" in body:
        raise FlowQueryError("L0 Flow answer must not disclose route details")
    if level in {"L1", "L2", "L3"}:
        route = [_mapping(row, "Flow route row") for row in _array(body.get("route"), "answer.route")]
        if not route:
            raise FlowQueryError("Flow route must not be empty above L0")
        for row in route:
            _text(row.get("occurrence_id"), "route occurrence_id")
            if _text(row.get("route_kind"), "route route_kind") not in ROUTE_KINDS:
                raise FlowQueryError("Flow route contains invalid route_kind")
            _text(row.get("from_ref"), "route from_ref")
            _text(row.get("to_ref"), "route to_ref")
            _strings(row.get("next_occurrence_ids"), "route next_occurrence_ids")
            if level in {"L2", "L3"}:
                _strings(row.get("carried_refs"), "route carried_refs", minimum=1)
                _strings(row.get("authority_refs"), "route authority_refs", minimum=1)
                _strings(row.get("allowed_reliance"), "route allowed_reliance", minimum=1)
                _strings(row.get("unresolved_items"), "route unresolved_items")
                _strings(row.get("forbidden_assumptions"), "route forbidden_assumptions", minimum=1)
                _strings(row.get("consumer_scope"), "route consumer_scope", minimum=1)
            if level == "L3":
                _strings(row.get("evidence_refs"), "route evidence_refs", minimum=1)
    if level != "L3" and "source_provenance" in body:
        raise FlowQueryError("source provenance is L3-only")
    if level == "L3":
        provenance = _mapping(body.get("source_provenance"), "source_provenance")
        if _text(provenance.get("binding_mode"), "source_provenance.binding_mode") not in BINDING_MODES:
            raise FlowQueryError("source provenance binding_mode invalid")
        if not isinstance(provenance.get("architecture_binding_verified"), bool):
            raise FlowQueryError("source provenance architecture_binding_verified must be boolean")
        _array(provenance.get("external_source_receipts"), "source_provenance.external_source_receipts")
    _text(answer.get("claim_ceiling"), "claim_ceiling", minimum=80)
    if "assertions" in answer or "objects" in answer or "occurrences" in answer:
        raise FlowQueryError("normal Flow query answers must not expose raw meta-kernel records")
    return answer
