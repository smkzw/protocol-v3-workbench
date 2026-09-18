"""Template-bound fact adoption (3R.4D): validate, plan and bind one adoption.

This module is the typed bridge between the current authored template (B
source-bound catalogs, C impact planning) and the existing application-layer
adoption transaction.  It owns no storage, opens no unit of work and holds no
clinical judgement:

* input validation reuses B's native-type, alias and three-state rule logic
  (``fact_bindings`` / ``applicability``); unknown stays 未决 and is never
  silently read as ``False``, and ``null`` is a value — never a delete;
* the applicability snapshot and the fact-labeled impact plan are B's and C's
  real outputs over the same facts transition, persisted verbatim inside the
  adoption event so any later reader can re-verify the bindings;
* the CAS material binds the template identity, the explicit retirement
  intent, the fact updates and the decision input refs — the plan hash is a
  projection and is never used as a work key.

Reconstruction and the read-only query reuse :func:`verify_template_adoption_payload`
so a rebuilt event stream must reproduce every recorded hash binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from packages.contracts.workbench_contracts.protocol_v3 import (
    ApplicabilityStatus,
    StudyDefinitionV3,
)

from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
from app.protocol_workflow.canonical.hashing import exact_payload_sha256
from app.protocol_workflow.canonical.study_definition import (
    TEMPLATE_FACT_ADOPTION_OPERATION,
    _fact_updates_sha256,
    study_revision_hash,
)
from app.protocol_workflow.registries.applicability import (
    build_applicability_snapshot,
    evaluate_predicates,
)
from app.protocol_workflow.registries.chapters import _has_fact_value
from app.protocol_workflow.registries.dependency_graph import (
    DependencyGraph,
    build_dependency_graph,
    build_fact_labeled_impact_plan,
)
from app.protocol_workflow.registries.fact_bindings import (
    FactBinding,
    FactBindingCatalog,
    FactBindingError,
    _typed_value,
)
from app.protocol_workflow.registries.template_runtime import (
    CurrentTemplate,
    template_identity,
)

__all__ = [
    "TEMPLATE_FACT_ADOPTION_SCHEMA",
    "GetTemplateAdoptionQuery",
    "TemplateAdoptionFlow",
    "TemplateAdoptionQueryResult",
    "TemplateAdoptionValidationError",
    "adoption_intent_material",
    "impact_plan_payload",
    "literal_fact_diff",
    "prepare_template_adoption",
    "recompute_adoption_intent_sha256",
    "validate_retirement_presence",
    "verify_template_adoption_payload",
]


TEMPLATE_FACT_ADOPTION_SCHEMA = "template-fact-adoption.v1"


# ---------------------------------------------------------------------------
# Typed validation failure
# ---------------------------------------------------------------------------


class TemplateAdoptionValidationError(ValueError):
    """A template-bound adoption contradicts the confirmed template state.

    ``kind`` is a stable machine label for the audit record; ``fact_paths``
    carries the exact offending paths.  The application service translates
    this into the finite error catalog — the raw message never reaches the UI.
    """

    def __init__(self, kind: str, fact_paths: Sequence[str], detail: str) -> None:
        self.kind = kind
        self.fact_paths = tuple(sorted(set(fact_paths)))
        self.detail = detail
        super().__init__(f"template adoption rejected ({kind}): {detail}")


# ---------------------------------------------------------------------------
# Pure helpers shared with reconstruction
# ---------------------------------------------------------------------------


def literal_fact_diff(
    facts_before: Mapping[str, Any], facts_after: Mapping[str, Any]
) -> tuple[str, ...]:
    """Literal-key diff preserving native JSON type differences.

    ``False`` and ``0`` never compare equal; a missing key is a change, not an
    implicit ``False``; dotted keys stay literal.
    """

    changed: list[str] = []
    for path in sorted(set(facts_before) | set(facts_after)):
        if path not in facts_before or path not in facts_after:
            changed.append(path)
            continue
        if exact_payload_sha256(facts_before[path]) != exact_payload_sha256(
            facts_after[path]
        ):
            changed.append(path)
    return tuple(changed)


def impact_plan_payload(plan) -> dict[str, Any]:
    """JSON-safe serialisation of C's :class:`FactLabeledImpactPlan`."""

    return {
        "plan_schema_version": plan.plan_schema_version,
        "graph_schema_version": plan.graph_schema_version,
        "template_id": plan.template_id,
        "registry_sha256": plan.registry_sha256,
        "changed_canonical_paths": list(plan.changed_canonical_paths),
        "changed_fact_paths": list(plan.changed_fact_paths),
        "unmapped_canonical_paths": list(plan.unmapped_canonical_paths),
        "unindexed_fact_paths": list(plan.unindexed_fact_paths),
        "projection_refreshes": [
            {
                "contract_id": item.contract_id,
                "fact_path": item.fact_path,
                "canonical_path": item.canonical_path,
            }
            for item in plan.projection_refreshes
        ],
        "entries": [
            {
                "contract_id": entry.contract_id,
                "reason": entry.reason.value,
                "confirmation": entry.confirmation,
                "via_fact_paths": list(entry.via_fact_paths),
                "via_contract_ids": list(entry.via_contract_ids),
                "rule_plans": [
                    {
                        "rule_id": item.rule_id,
                        "changed_triggering_fact_paths": list(
                            item.changed_triggering_fact_paths
                        ),
                        "state_before": item.state_before,
                        "state_after": item.state_after,
                        "disposition": item.disposition,
                    }
                    for item in entry.rule_plans
                ],
            }
            for entry in plan.entries
        ],
        "confirmed_reopen_contract_ids": list(plan.confirmed_reopen_contract_ids),
        "candidate_check_contract_ids": list(plan.candidate_check_contract_ids),
        "fact_bindings_sha256": plan.fact_bindings_sha256,
        "applicability_rules_sha256": plan.applicability_rules_sha256,
        "findings": [
            {
                "code": item.code,
                "severity": item.severity,
                "location": item.location,
                "message": item.message,
            }
            for item in plan.findings
        ],
        "plan_sha256": plan.plan_sha256,
    }


# ---------------------------------------------------------------------------
# Pre-adoption validation (B logic; facts_after as adopted)
# ---------------------------------------------------------------------------


def _alias_bindings(catalog: FactBindingCatalog) -> dict[str, FactBinding]:
    return {
        binding.fact_path: binding
        for binding in catalog.bindings
        if binding.canonical_path is not None
        and binding.canonical_path != binding.fact_path
    }


def _controlled_fact_paths(rules_catalog) -> set[str]:
    """Fact paths whose obligations are condition-controlled by the rule set."""

    controlled: set[str] = set()
    for rule in rules_catalog.rules:
        controlled.update(rule.conditional_fact_paths)
    return controlled


def validate_retirement_intent(
    retired_fact_paths: Sequence[str],
    catalog: FactBindingCatalog,
    rules_catalog,
) -> None:
    """Only explicitly resolvable retirements may enter an adoption.

    Permitted: a confirmed alias mapping (display migration to its canonical
    owner) and a condition-controlled fact (its release is decided after the
    adoption by the resulting rule states).  A canonical owner that no rule
    controls and an unmapped path are canonical truths or unknown names — they
    are never retireable here.  Presence in the current facts is checked
    against the adopted state, not here, so an exact replay is always
    classified ledger-first.
    """

    aliases = _alias_bindings(catalog)
    controlled = _controlled_fact_paths(rules_catalog)
    for path in retired_fact_paths:
        if path in aliases or path in controlled:
            continue
        raise TemplateAdoptionValidationError(
            "retired_fact_not_resolvable",
            (path,),
            "only a confirmed alias mapping or a condition-controlled fact "
            "may be retired explicitly",
        )


def validate_retirement_presence(
    retired_fact_paths: Sequence[str], facts: Mapping[str, Any]
) -> None:
    """State-dependent half of the retirement intent: the path must exist.

    Runs only for a genuinely fresh apply (after the ledger proved no prior
    effect, before the reducer), so an exact replay is always classified
    ledger-first and never re-validated against a moved-forward state.
    """

    absent = tuple(path for path in retired_fact_paths if path not in facts)
    if absent:
        raise TemplateAdoptionValidationError(
            "retired_fact_absent",
            absent,
            "a retired fact path must be present in the current facts",
        )


def validate_adoption_facts(
    *,
    template: CurrentTemplate,
    facts_before: Mapping[str, Any],
    facts_after: Mapping[str, Any],
    retired_fact_paths: Sequence[str] = (),
) -> None:
    """Reject contradictions before the adoption transaction writes.

    Validation covers the *full resulting conditional fact state* plus every
    alias pair of the current catalog; unresolved conditions and absent facts
    stay undecided (未决) and never block a partial save.  Reuses B's native
    type and three-state logic directly so adoption and chapter binding cannot
    drift apart.
    """

    # 1. ``null`` is a written value, never a delete; removal is explicit
    #    retirement only.
    nulled = tuple(
        path
        for path in literal_fact_diff(facts_before, facts_after)
        if path in facts_after and facts_after[path] is None
    )
    if nulled:
        raise TemplateAdoptionValidationError(
            "null_is_not_a_delete",
            nulled,
            "adopting a null value is not a deletion; retire the fact path "
            "explicitly or supply a typed value",
        )

    bindings = {binding.fact_path: binding for binding in template.fact_catalog.bindings}

    # 2. Written values must match the declared native types (B logic; the
    #    native-JSON source format never parses strings into types).
    type_mismatches: list[str] = []
    for path in literal_fact_diff(facts_before, facts_after):
        if path not in facts_after:
            continue
        binding = bindings.get(path)
        if binding is None:
            continue
        try:
            _typed_value(binding, facts_after[path], "native_json")
        except FactBindingError as exc:
            type_mismatches.extend(exc.fact_paths or (path,))
    if type_mismatches:
        raise TemplateAdoptionValidationError(
            "fact_type_mismatch",
            type_mismatches,
            "written values do not match the template's declared native types",
        )

    # 3. An alias and its canonical owner must never hold different values.
    alias_conflicts: list[str] = []
    for path, binding in _alias_bindings(template.fact_catalog).items():
        canonical = binding.canonical_path
        if path in facts_after and canonical in facts_after:
            if exact_payload_sha256(facts_after[path]) != exact_payload_sha256(
                facts_after[canonical]
            ):
                alias_conflicts.append(path)
    if alias_conflicts:
        raise TemplateAdoptionValidationError(
            "fact_alias_conflict",
            alias_conflicts,
            "an alias and its canonical owner hold different values; retire "
            "the alias explicitly or align the values",
        )

    # 4. The FULL resulting conditional fact state must be consistent: a
    #    material value under a fully decided 不适用 condition contradicts the
    #    adoption even when the value's own path was not written this time.
    #    Any unresolved owner keeps the condition 未决 and the save proceeds.
    inactive_conflicts: list[str] = []
    controlled = _controlled_fact_paths(template.rules_catalog)
    for path in sorted(controlled):
        if path not in facts_after:
            continue
        controlling = [
            rule
            for rule in template.rules_catalog.rules
            if path in rule.conditional_fact_paths
        ]
        states = [
            evaluate_predicates(rule.predicates, facts_after, mode=rule.mode)
            for rule in controlling
        ]
        if all(state is ApplicabilityStatus.NOT_APPLICABLE for state in states):
            if _has_fact_value(facts_after[path]):
                inactive_conflicts.append(path)
    if inactive_conflicts:
        raise TemplateAdoptionValidationError(
            "inactive_conditional_conflict",
            inactive_conflicts,
            "confirmed non-applicable conditions conflict with supplied "
            "values; retire the values explicitly in the same adoption or "
            "resolve the conditions first",
        )

    # 5. Explicit retirement must match reality: every retired path existed in
    #    the adopted-from facts, is gone after adoption, and a condition-
    #    controlled retirement is only resolved when the condition is genuinely
    #    不适用 on the resulting facts (unknown is not inactive; any applicable
    #    shared owner keeps the fact alive).
    absent_retirements = tuple(
        path for path in retired_fact_paths if path not in facts_before
    )
    if absent_retirements:
        raise TemplateAdoptionValidationError(
            "retired_fact_absent",
            absent_retirements,
            "a retired fact path must be present in the current facts",
        )
    surviving_retirements = tuple(
        path for path in retired_fact_paths if path in facts_after
    )
    if surviving_retirements:
        raise TemplateAdoptionValidationError(
            "retired_fact_not_removed",
            surviving_retirements,
            "a retired fact path must be removed from the adopted facts",
        )
    aliases = _alias_bindings(template.fact_catalog)
    unresolved_retirements: list[str] = []
    active_retirements: list[str] = []
    for path in retired_fact_paths:
        if path in aliases or path not in controlled:
            continue
        controlling = [
            rule
            for rule in template.rules_catalog.rules
            if path in rule.conditional_fact_paths
        ]
        states = [
            evaluate_predicates(rule.predicates, facts_after, mode=rule.mode)
            for rule in controlling
        ]
        if any(state is ApplicabilityStatus.APPLICABLE for state in states):
            active_retirements.append(path)
        elif any(state is ApplicabilityStatus.CONDITIONAL for state in states):
            unresolved_retirements.append(path)
    if active_retirements:
        raise TemplateAdoptionValidationError(
            "retired_fact_still_active",
            active_retirements,
            "an applicable condition keeps this fact alive; it cannot be "
            "retired",
        )
    if unresolved_retirements:
        raise TemplateAdoptionValidationError(
            "retired_fact_unresolved",
            unresolved_retirements,
            "unknown is not inactive; resolve the condition before retiring "
            "this fact",
        )


# ---------------------------------------------------------------------------
# Adoption flow (pure; the application service drives it inside its UoW)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateAdoptionFlow:
    """One prepared template-bound adoption for one command.

    ``material`` is the CAS adoption intent material — the request-level
    fields (template echo + explicit retirement) that an exact replay can
    reproduce WITHOUT loading the current template; the loaded template
    identity is enforced at adoption time and persisted in the payload, never
    reloaded for replay classification.  ``validate_and_build_payload`` runs
    after the reducer produced the adopted definition, so validation observes
    the *adopted* state and the payload binds the exact base/result revisions.
    """

    template: CurrentTemplate
    identity: Mapping[str, Any]
    graph: DependencyGraph
    retired_fact_paths: tuple[str, ...]
    material: Mapping[str, Any]

    def validate_and_build_payload(
        self,
        *,
        facts_before: Mapping[str, Any],
        adopted: StudyDefinitionV3,
        facts_before_revision: int,
        facts_before_revision_sha256: str,
        request_template_id: Optional[str],
        now,
    ) -> dict[str, Any]:
        result_revision_sha256 = study_revision_hash(adopted)
        validate_adoption_facts(
            template=self.template,
            facts_before=facts_before,
            facts_after=adopted.facts,
            retired_fact_paths=self.retired_fact_paths,
        )
        snapshot = build_applicability_snapshot(
            (entry.contract for entry in self.template.registry.chapters),
            adopted,
            self.template.rules_catalog.rules,
            created_at=now,
        )
        plan = build_fact_labeled_impact_plan(
            self.graph,
            facts_before=facts_before,
            facts_after=adopted.facts,
            bindings=self.template.fact_catalog.bindings,
            rules=self.template.rules_catalog.rules,
        )
        snapshot_payload = snapshot.model_dump(mode="json")
        plan_payload = impact_plan_payload(plan)
        return {
            "schema_version": TEMPLATE_FACT_ADOPTION_SCHEMA,
            "operation": TEMPLATE_FACT_ADOPTION_OPERATION,
            "template": dict(self.identity),
            "request_template_id": request_template_id,
            "base_revision": facts_before_revision,
            "base_revision_sha256": facts_before_revision_sha256,
            "result_revision": adopted.revision,
            "result_revision_sha256": result_revision_sha256,
            "facts_before_sha256": exact_payload_sha256(dict(facts_before)),
            "facts_after_sha256": exact_payload_sha256(dict(adopted.facts)),
            "changed_fact_paths": list(literal_fact_diff(facts_before, adopted.facts)),
            "retired_fact_paths": list(self.retired_fact_paths),
            "applicability_snapshot": snapshot_payload,
            "impact_plan": plan_payload,
        }


def prepare_template_adoption(
    *,
    template: CurrentTemplate,
    retired_fact_paths: Sequence[str],
    template_id: Optional[str],
) -> TemplateAdoptionFlow:
    """Validate intent against the loaded current template and build the CAS
    adoption intent material.

    Runs only for a genuinely fresh apply (the ledger proved no recorded
    effect), so an exact replay never loads the current template; everything
    that depends on the adopted state happens in
    :meth:`TemplateAdoptionFlow.validate_and_build_payload`.
    """

    identity = template_identity(template)
    if template_id is not None and template_id != identity["template_id"]:
        raise TemplateAdoptionValidationError(
            "template_identity_mismatch",
            (),
            f"the request names template {template_id!r} while the current "
            f"authored template is {identity['template_id']!r}",
        )
    validate_retirement_intent(retired_fact_paths, template.fact_catalog, template.rules_catalog)
    graph = build_dependency_graph(template.registry)
    retired = tuple(retired_fact_paths)
    material = adoption_intent_material(
        retired_fact_paths=retired, request_template_id=template_id
    )
    return TemplateAdoptionFlow(
        template=template,
        identity=identity,
        graph=graph,
        retired_fact_paths=retired,
        material=material,
    )


def adoption_intent_material(
    *, retired_fact_paths: Sequence[str], request_template_id: Optional[str]
) -> dict[str, Any]:
    """Request-level adoption intent — the exact-replay fingerprint input.

    Deliberately excludes the loaded template identity: replay classification
    must be reproducible from the caller's request and the recorded event
    alone, so template drift never invalidates an identical caller request
    while a changed request still conflicts.
    """

    return {
        "request_template_id": request_template_id,
        "retired_fact_paths": sorted(retired_fact_paths),
    }


def recompute_adoption_intent_sha256(payload: Mapping[str, Any]) -> str:
    """Recompute the recorded CAS intent hash from a committed event payload.

    Every input is materialised in the payload itself (fact updates, decision
    input binding refs, request template echo, retired paths), so the ledger
    rebuild can prove the stored ``fact_updates_sha256`` binds the recorded
    contents instead of accepting the field's existence.
    """

    adoption = payload.get("template_adoption")
    if not isinstance(adoption, Mapping):
        raise ValueError("template adoption event without its adoption payload")
    binding = payload.get("decision_input_binding")
    refs = None
    if binding is not None:
        refs = tuple(
            DecisionInputRef.model_validate(item) for item in binding["refs"]
        )
    return _fact_updates_sha256(
        payload.get("fact_updates"),
        revise_confirmed_facts=True,
        decision_input_refs=refs,
        adoption_material={
            "request_template_id": adoption.get("request_template_id"),
            "retired_fact_paths": list(adoption["retired_fact_paths"]),
        },
    )


# ---------------------------------------------------------------------------
# Post-hoc verification (reconstruction + read-only query)
# ---------------------------------------------------------------------------


def verify_template_adoption_payload(
    adoption: Mapping[str, Any],
    *,
    facts_before: StudyDefinitionV3,
    facts_after: StudyDefinitionV3,
) -> None:
    """Re-verify every recorded hash binding from the event alone.

    ``facts_before`` / ``facts_after`` are the rebuilt aggregates around the
    adoption event.  This never re-runs B or C and never touches the
    filesystem: it proves the payload binds the adopted revision, the exact
    fact transition, the explicit retirement and the snapshot/plan identity.
    """

    if not isinstance(adoption, Mapping):
        raise ValueError("template adoption payload must be a mapping")
    if adoption.get("schema_version") != TEMPLATE_FACT_ADOPTION_SCHEMA:
        raise ValueError("unsupported template adoption schema version")
    if adoption.get("operation") != TEMPLATE_FACT_ADOPTION_OPERATION:
        raise ValueError("unsupported template adoption operation")
    before_hash = study_revision_hash(facts_before)
    after_hash = study_revision_hash(facts_after)
    if adoption["base_revision"] != facts_before.revision:
        raise ValueError("adoption base revision does not bind the rebuilt stream")
    if adoption["base_revision_sha256"] != before_hash:
        raise ValueError("adoption base revision hash does not bind the rebuilt stream")
    if adoption["result_revision"] != facts_after.revision:
        raise ValueError("adoption result revision does not bind the rebuilt stream")
    if adoption["result_revision_sha256"] != after_hash:
        raise ValueError("adoption result revision hash does not bind the rebuilt stream")
    if adoption["facts_before_sha256"] != exact_payload_sha256(dict(facts_before.facts)):
        raise ValueError("adoption facts-before hash does not match the rebuilt facts")
    if adoption["facts_after_sha256"] != exact_payload_sha256(dict(facts_after.facts)):
        raise ValueError("adoption facts-after hash does not match the rebuilt facts")
    changed = list(literal_fact_diff(facts_before.facts, facts_after.facts))
    if list(adoption["changed_fact_paths"]) != changed:
        raise ValueError("adoption changed paths do not match the rebuilt fact diff")
    retired = list(adoption["retired_fact_paths"])
    for path in retired:
        if path not in facts_before.facts:
            raise ValueError("a retired fact path was absent from the adopted-from facts")
        if path in facts_after.facts:
            raise ValueError("a retired fact path survived the adopted revision")
    template = adoption["template"]
    request_template_id = adoption.get("request_template_id")
    if request_template_id is not None and request_template_id != template["template_id"]:
        raise ValueError("request template echo does not bind the adopted template identity")
    snapshot = adoption["applicability_snapshot"]
    if snapshot["study_definition_sha256"] != after_hash:
        raise ValueError("applicability snapshot does not bind the adopted revision")
    if snapshot["study_definition_id"] != facts_after.study_definition_id:
        raise ValueError("applicability snapshot does not bind the adopted study")
    plan = adoption["impact_plan"]
    if plan["registry_sha256"] != template["registry_sha256"]:
        raise ValueError("impact plan does not bind the adopted template identity")
    if (
        plan["applicability_rules_sha256"]
        != template["applicability_rules_sha256"]
    ):
        raise ValueError("impact plan does not bind the adopted rule set")
    if list(plan["changed_canonical_paths"]) != changed:
        raise ValueError("impact plan does not bind the rebuilt fact diff")


# ---------------------------------------------------------------------------
# Read-only query types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GetTemplateAdoptionQuery:
    project_id: str
    study_definition_id: str


@dataclass(frozen=True)
class TemplateAdoptionQueryResult:
    """The latest template-bound adoption record rebuilt from events."""

    project_id: str
    study_definition_id: str
    cas_identity: str
    decision_record_id: str
    decision_key: str
    base_revision: int
    base_revision_sha256: str
    applied_revision: int
    applied_revision_sha256: str
    facts_before_sha256: str
    facts_after_sha256: str
    changed_fact_paths: tuple[str, ...]
    retired_fact_paths: tuple[str, ...]
    template: Mapping[str, Any]
    applicability_snapshot: Mapping[str, Any]
    impact_plan: Mapping[str, Any]
