"""Small, explicit predicates for confirmed facts; never evaluate prose."""
from __future__ import annotations

import math
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from packages.contracts.workbench_contracts.protocol_v3 import (
    ApplicabilityEntry, ApplicabilitySnapshot, ApplicabilityStatus, CanonicalState, ChapterContractV2, ClaimRequirement,
    EvidenceSourceRequirement, FactRequirement, NonEmptyText, Sha256, StableId, StudyDefinitionV3,
    StructuralObjectKind,
)

if TYPE_CHECKING:
    from app.protocol_workflow.registries.chapters import ChapterContentPayload, FixtureCheckResult


class FactPredicate(BaseModel):
    """Compare an explicitly addressed scalar, without type coercion.

    Dotted canonical keys are literal. Members are an explicit path within a
    structured JSON value, not an inferred split of the canonical key.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)
    fact_path: NonEmptyText
    members: tuple[NonEmptyText, ...] = ()
    expected: bool | int | float | str
    accepted_values: tuple[bool | int | float | str, ...] | None = None

    @model_validator(mode="after")
    def _validate_value_domain(self):
        if self.accepted_values is not None:
            if (not self.accepted_values
                    or any(type(v) is not type(self.expected) for v in self.accepted_values)
                    or self.expected not in self.accepted_values
                    or len(set(self.accepted_values)) != len(self.accepted_values)):
                raise ValueError("predicate accepted values must uniquely cover the expected scalar type and value")
        return self


def evaluate_predicate(
    predicate: FactPredicate, facts: Mapping[str, JsonValue],
) -> ApplicabilityStatus:
    value = facts.get(predicate.fact_path)
    for member in predicate.members:
        if not isinstance(value, Mapping) or member not in value:
            return ApplicabilityStatus.CONDITIONAL
        value = value[member]
    # Missing, null and wrong-schema values are unresolved, not a negative
    # scientific decision. In particular False must never compare equal to 0.
    if (value is None or type(value) is not type(predicate.expected)
            or (isinstance(value, float) and not math.isfinite(value))):
        return ApplicabilityStatus.CONDITIONAL
    if predicate.accepted_values is not None and value not in predicate.accepted_values:
        return ApplicabilityStatus.CONDITIONAL
    return (ApplicabilityStatus.APPLICABLE if value == predicate.expected
            else ApplicabilityStatus.NOT_APPLICABLE)


def evaluate_predicates(
    predicates: Sequence[FactPredicate], facts: Mapping[str, JsonValue], *,
    mode: Literal["all", "any"],
) -> ApplicabilityStatus:
    if not predicates:
        raise ValueError("predicate set must be non-empty")
    if mode not in ("all", "any"):
        raise ValueError("predicate mode must be all or any")
    states = [evaluate_predicate(predicate, facts) for predicate in predicates]
    decisive = (ApplicabilityStatus.NOT_APPLICABLE if mode == "all"
                else ApplicabilityStatus.APPLICABLE)
    if decisive in states:
        return decisive
    if ApplicabilityStatus.CONDITIONAL in states:
        return ApplicabilityStatus.CONDITIONAL
    return (ApplicabilityStatus.APPLICABLE if mode == "all"
            else ApplicabilityStatus.NOT_APPLICABLE)


class ReferenceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_path: NonEmptyText
    semantic_node_ids: tuple[StableId, ...] = Field(min_length=1)


class RulePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_id: StableId
    source_rule_sha256: Sha256
    source_contract_sha256: Sha256 | None = None
    predicates: tuple[FactPredicate, ...] = Field(min_length=1)
    mode: Literal["all", "any"] = "all"
    affects_chapter_presence: bool = False
    conditional_fact_paths: tuple[NonEmptyText, ...] = ()
    conditional_claim_types: tuple[NonEmptyText, ...] = ()
    conditional_evidence_admission_types: tuple[NonEmptyText, ...] = ()
    conditional_object_kinds: tuple[StructuralObjectKind, ...] = ()
    conditional_object_cells: tuple[NonEmptyText, ...] = ()
    inactive_claim_requirements: tuple[ClaimRequirement, ...] = ()
    inactive_evidence_requirements: tuple[EvidenceSourceRequirement, ...] = ()
    active_evidence_requirements: tuple[EvidenceSourceRequirement, ...] = ()
    reference_targets: tuple[ReferenceTarget, ...] = ()

    @model_validator(mode="after")
    def _bind_projection_to_contract(self):
        if any((self.conditional_fact_paths, self.conditional_claim_types,
                self.conditional_evidence_admission_types, self.conditional_object_kinds, self.conditional_object_cells,
                self.inactive_claim_requirements, self.inactive_evidence_requirements, self.active_evidence_requirements,
                self.affects_chapter_presence, self.reference_targets)) and not self.source_contract_sha256:
            raise ValueError("obligation projection requires source contract hash")
        return self



class ApplicabilityRuleCatalog(BaseModel):
    """Versioned declarations with explicit incomplete coverage during migration."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["protocol-v3-applicability-rules.v1"] = "protocol-v3-applicability-rules.v1"
    template_id: StableId
    template_sha256: Sha256
    rules: tuple[RulePredicate, ...]
    pending_rule_ids: tuple[StableId, ...] = ()


def load_applicability_rules(path: Path, contracts: Sequence[ChapterContractV2]) -> ApplicabilityRuleCatalog:
    catalog = ApplicabilityRuleCatalog.model_validate_json(Path(path).read_text(encoding="utf-8"))
    current = {}
    for contract in contracts:
        if (contract.template_id, contract.template_sha256) != (catalog.template_id, catalog.template_sha256):
            raise ValueError("applicability template source changed")
        for rule in contract.conditional_applicability_rules:
            current[rule.conditional_applicability_rule_id] = (contract, rule)
    declared = [rule.rule_id for rule in catalog.rules]
    pending = catalog.pending_rule_ids
    if (len(set(declared)) != len(declared) or len(set(pending)) != len(pending)
            or set(declared) & set(pending) or set(declared) | set(pending) != set(current)):
        raise ValueError("applicability catalog coverage mismatch")
    for declaration in catalog.rules:
        contract, source = current[declaration.rule_id]
        if (declaration.source_rule_sha256 != source.material_sha256()
                or declaration.source_contract_sha256 != contract.material_sha256()):
            raise ValueError("applicability rule source changed")
        declared_cells = {
            cell
            for obligation in contract.substantive_content.structural_object_obligations
            for cell in obligation.required_object_cells
        }
        unknown_cells = set(declaration.conditional_object_cells) - declared_cells
        if unknown_cells:
            raise ValueError(
                f"applicability cell target missing: {declaration.rule_id}: "
                f"{sorted(unknown_cells)}"
            )
    return catalog


def _project_obligations(contract, content, declarations, states):
    """Apply only explicit, source-bound releases; shared active owners win."""
    from app.protocol_workflow.registries.chapters import _finding, _has_fact_value, _material_occurrences
    attributes = ("conditional_fact_paths", "conditional_claim_types",
                  "conditional_evidence_admission_types", "conditional_object_kinds", "conditional_object_cells")
    controlled = {attribute: {} for attribute in attributes}
    for rule_id, state in states.items():
        for attribute in attributes:
            for key in getattr(declarations[rule_id], attribute):
                controlled[attribute].setdefault(key, []).append(state)
    removed = {attribute: {key for key, owners in mapping.items() if ApplicabilityStatus.APPLICABLE not in owners}
               for attribute, mapping in controlled.items()}
    inactive = {attribute: {key for key, owners in mapping.items() if all(s is ApplicabilityStatus.NOT_APPLICABLE for s in owners)}
                for attribute, mapping in controlled.items()}
    substantive = contract.substantive_content
    facts = tuple(item for item in substantive.fact_requirements if item.fact_path not in removed["conditional_fact_paths"])
    claims = {item.claim_type: item for item in substantive.claim_requirements if item.claim_type not in removed["conditional_claim_types"]}
    evidence = []
    for group in substantive.evidence_source_requirements:
        admissions = tuple(key for key in group.admission_claim_types if key not in removed["conditional_evidence_admission_types"])
        if admissions:
            evidence.append(group.model_copy(update={"admission_claim_types": admissions}))
    objects = tuple(item.model_copy(update={
        "required_object_cells": tuple(cell for cell in item.required_object_cells
                                       if cell not in removed["conditional_object_cells"]),
    }) for item in substantive.structural_object_obligations
       if item.object_kind not in removed["conditional_object_kinds"])
    for rule_id, state in states.items():
        if state is ApplicabilityStatus.APPLICABLE:
            evidence.extend(declarations[rule_id].active_evidence_requirements)
        if state is ApplicabilityStatus.NOT_APPLICABLE:
            declaration = declarations[rule_id]
            for item in declaration.inactive_claim_requirements:
                claims[item.claim_type] = item
            evidence.extend(declaration.inactive_evidence_requirements)
    projected = substantive.model_copy(update={"fact_requirements": facts, "claim_requirements": tuple(claims.values()),
                                               "evidence_source_requirements": tuple(evidence), "structural_object_obligations": objects})
    findings = []
    disposition_owners = {}
    for rule_id, state in states.items():
        for requirement in declarations[rule_id].inactive_claim_requirements:
            disposition_owners.setdefault(requirement.claim_type, []).append(state)
    for item in content.claims:
        owners = disposition_owners.get(item.claim_type, ())
        if owners and all(state is ApplicabilityStatus.APPLICABLE for state in owners) and (item.statement or "").strip():
            findings.append(_finding("inactive_disposition_claim_present", item.claim_type,
                                     "Non-applicability disposition conflicts with confirmed applicability"))
    for item in content.facts:
        if item.fact_path in inactive["conditional_fact_paths"] and _has_fact_value(item.value):
            findings.append(_finding("inactive_conditional_fact_present", item.fact_path, "Fact conflicts with confirmed non-applicability"))
    for item in content.claims:
        if item.claim_type in inactive["conditional_claim_types"] and (item.statement or "").strip():
            findings.append(_finding("inactive_conditional_claim_present", item.claim_type, "Claim conflicts with confirmed non-applicability"))
    for kind in inactive["conditional_object_kinds"]:
        if _material_occurrences(content, kind.value):
            findings.append(_finding("inactive_conditional_object_present", kind.value, "Object conflicts with confirmed non-applicability"))
    for item in content.objects:
        for cell in item.cells:
            if cell.cell_id in inactive["conditional_object_cells"] and _has_fact_value(cell.value):
                findings.append(_finding("inactive_conditional_cell_present", cell.cell_id,
                                         "Table cell conflicts with confirmed non-applicability"))
    values = {item.fact_path: item.value for item in content.facts}
    for rule_id, state in states.items():
        if state is ApplicabilityStatus.APPLICABLE:
            for target in declarations[rule_id].reference_targets:
                value = values.get(target.fact_path)
                if _has_fact_value(value) and value not in target.semantic_node_ids:
                    findings.append(_finding("unresolved_reference_target", target.fact_path, "Reference must identify a declared current semantic target"))
    return contract.model_copy(update={"substantive_content": projected}), findings


def _resolve_rule_states(contract, study, rules):
    from app.protocol_workflow.registries.chapters import _finding
    if study.canonical_state not in (CanonicalState.CONFIRMED, CanonicalState.FROZEN):
        raise ValueError("applicability requires confirmed study facts")
    index = {}
    for declaration in rules:
        if declaration.rule_id in index:
            raise ValueError("duplicate rule predicate")
        index[declaration.rule_id] = declaration
    findings = []
    states = {}
    for rule in contract.conditional_applicability_rules:
        rule_id = rule.conditional_applicability_rule_id
        declaration = index.get(rule_id)
        location = f"conditional_rule:{rule_id}"
        if declaration is None:
            findings.append(_finding("conditional_predicate_missing", location, "No executable predicate is declared"))
            continue
        if (declaration.source_rule_sha256 != rule.material_sha256()
            or (declaration.source_contract_sha256 is not None and declaration.source_contract_sha256 != contract.material_sha256())):
            findings.append(_finding("conditional_predicate_source_changed", location, "Predicate does not bind the current source rule"))
            continue
        if {p.fact_path for p in declaration.predicates} != set(rule.triggering_fact_paths):
            findings.append(_finding("conditional_predicate_trigger_mismatch", location, "Predicate references an undeclared trigger"))
            continue
        status = evaluate_predicates(declaration.predicates, study.facts, mode=declaration.mode)
        states[rule_id] = status
        if status is ApplicabilityStatus.CONDITIONAL:
            findings.append(_finding("conditional_applicability_unresolved", location, "Confirmed facts do not resolve this condition"))
    return index, states, findings


def evaluate_applicable_content(
    contract: ChapterContractV2, content: ChapterContentPayload, *,
    study: StudyDefinitionV3, rules: Sequence[RulePredicate], subject_id: str,
) -> FixtureCheckResult:
    """Execute source-bound conditional obligations alongside content checks."""
    from app.protocol_workflow.registries.chapters import (
        _finding, _has_fact_value, _material_occurrences, evaluate_chapter_content,
    )
    index, states, findings = _resolve_rule_states(contract, study, rules)
    facts = {item.fact_path: item.value for item in content.facts}
    claims = {item.claim_type: item.statement for item in content.claims}
    for rule in contract.conditional_applicability_rules:
        rule_id = rule.conditional_applicability_rule_id
        location = f"conditional_rule:{rule_id}"
        if states.get(rule_id) is not ApplicabilityStatus.APPLICABLE:
            continue
        for path in rule.required_when_active_fact_paths:
            if not _has_fact_value(facts.get(path)):
                findings.append(_finding("missing_conditional_fact", f"{location}:{path}", "Applicable condition requires this fact"))
        for claim in rule.required_when_active_claim_types:
            if not (claims.get(claim) or "").strip():
                findings.append(_finding("missing_conditional_claim", f"{location}:{claim}", "Applicable condition requires this claim"))
        if rule.required_when_active_source_roles and not any(
            item.source_role in rule.required_when_active_source_roles for item in content.evidence
        ):
            findings.append(_finding("missing_conditional_source", location, "Applicable condition requires an admitted source role"))
        for kind in rule.required_when_active_structural_objects:
            if _material_occurrences(content, kind.value) < 1:
                findings.append(_finding("missing_conditional_object", f"{location}:{kind.value}", "Applicable condition requires a material structural object"))
    effective_contract, projection_findings = _project_obligations(contract, content, index, states)
    result = evaluate_chapter_content(effective_contract, content, subject_id=subject_id)
    findings = list(result.findings) + findings + projection_findings
    return result.model_copy(update={
        "passed": not any(item.severity == "error" for item in findings),
        "findings": tuple(findings),
        "deferred_qc_obligations": tuple(
            item for item in result.deferred_qc_obligations
            if item not in {f"conditional_applicability_not_executed:{rule_id}" for rule_id in states}
        ),
    })


class ApplicabilityResolutionError(ValueError):
    def __init__(self, findings):
        self.findings = tuple(findings)
        super().__init__("; ".join(f"{item.code}:{item.location}" for item in findings))


def _resolved_input_contract(study, contract, bindings, rules, *, collect_findings=False):
    from app.protocol_workflow.registries.chapters import ChapterContentPayload, ContentFact
    index, states, findings = _resolve_rule_states(contract, study, rules)
    if findings and not collect_findings:
        raise ApplicabilityResolutionError(findings)
    # Check actual canonical values for stale inactive parameters before writing.
    controlled_paths = {path for rule_id in states for path in index[rule_id].conditional_fact_paths}
    controlled_paths.update(target.fact_path for rule_id in states for target in index[rule_id].reference_targets)
    canonical_facts = tuple(
        ContentFact(fact_path=b.fact_path, value=study.facts[b.canonical_path])
        for b in bindings if b.fact_path in controlled_paths and b.canonical_path in study.facts
    )
    effective, conflicts = _project_obligations(contract, ChapterContentPayload(facts=canonical_facts), index, states)
    if conflicts and not collect_findings:
        raise ApplicabilityResolutionError(conflicts)
    active_ids = tuple(sorted(rule_id for rule_id, state in states.items() if state is ApplicabilityStatus.APPLICABLE))
    active_rules = tuple(rule for rule in contract.conditional_applicability_rules
                         if rule.conditional_applicability_rule_id in active_ids)
    requirements = {item.fact_path: item for item in effective.substantive_content.fact_requirements}
    for rule in active_rules:
        for path in rule.required_when_active_fact_paths:
            previous = requirements.get(path)
            if previous is not None and previous.obligation.value == "forbidden":
                raise ValueError(f"active conditional fact is forbidden: {path}")
            requirements[path] = FactRequirement(
                fact_path=path, obligation="required",
                rationale=f"Active condition {rule.conditional_applicability_rule_id}: {rule.rationale}",
            )
    effective = effective.model_copy(update={
        "conditional_applicability_rules": active_rules,
        "substantive_content": effective.substantive_content.model_copy(update={
            "fact_requirements": tuple(requirements.values()),
        }),
    })
    digest = hashlib.sha256(json.dumps({
        "source_contract_sha256": contract.material_sha256(),
        "rules": [index[rule_id].model_dump(mode="json") for rule_id in sorted(states)],
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if collect_findings:
        return effective, active_ids, digest, tuple(findings)+tuple(conflicts)
    return effective, active_ids, digest


def diagnose_applicable_input(study, contract, bindings, *, rules):
    """Use the same obligation projection to collect all currently knowable gaps.

    Unresolved conditions remain findings. Their obligations are not activated;
    already applicable siblings retain their required facts and shared owners.
    This diagnostic result is never an executable bound input.
    """
    from app.protocol_workflow.registries.fact_bindings import diagnose_chapter_facts
    bindings=tuple(bindings)
    effective,_,_,findings=_resolved_input_contract(study,contract,bindings,rules,collect_findings=True)
    return findings,diagnose_chapter_facts(study,effective,bindings)


def bind_applicable_chapter(study, contract, bindings, *, rules, source_format="native_json",
                            deferred_required_paths=()):
    """Return the effective contract and its input from one applicability resolution.

    ``deferred_required_paths`` names required facts the caller turns into
    explicit draft gap objects (R2); they are never silently dropped.
    """
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    bindings = tuple(bindings)
    effective, active_ids, digest = _resolved_input_contract(study, contract, bindings, rules)
    bound = bind_chapter_input(study, effective, bindings, source_format=source_format,
                               active_conditional_rule_ids=active_ids, applicability_rules_sha256=digest,
                               deferred_required_paths=deferred_required_paths)
    return effective, bound


def bind_applicable_input(study, contract, bindings, *, rules, source_format="native_json"):
    """Keep the existing input-only interface for current callers."""
    return bind_applicable_chapter(study, contract, bindings, rules=rules,
                                   source_format=source_format)[1]


def check_applicable_output(bound, output, study, contract, bindings, *, rules):
    """Fresh canonical equality and executable content checks; medical QC remains separate."""
    from app.protocol_workflow.registries.fact_bindings import validate_output_facts
    bindings = tuple(bindings)
    effective, active_ids, digest = _resolved_input_contract(study, contract, bindings, rules)
    validate_output_facts(bound, output, study, contract=effective, bindings=bindings,
                          active_conditional_rule_ids=active_ids, applicability_rules_sha256=digest)
    return evaluate_applicable_content(contract, output.content_payload(), study=study, rules=rules,
                                        subject_id=f"skill_output:{output.node_id}")


def build_applicability_snapshot(contracts, study, rules, *, created_at):
    """Use the existing node snapshot; inner-rule false does not hide a chapter.

    Rule decisions are deterministically reproducible from the bound study and
    ruleset. Only an explicit whole-chapter rule can exclude a semantic node.
    """
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    contracts, rules = tuple(contracts), tuple(rules)
    entries = []
    used_rule_ids = set()
    labels = {ApplicabilityStatus.APPLICABLE: "适用", ApplicabilityStatus.NOT_APPLICABLE: "不适用", ApplicabilityStatus.CONDITIONAL: "未决"}
    for contract in contracts:
        index, states, findings = _resolve_rule_states(contract, study, rules)
        errors = [item for item in findings if item.code != "conditional_applicability_unresolved"]
        if errors:
            raise ApplicabilityResolutionError(errors)
        used_rule_ids.update(states)
        presence_rules = [rule_id for rule_id in states if index[rule_id].affects_chapter_presence]
        if len(presence_rules) > 1:
            raise ValueError("chapter presence requires one explicit combined rule")
        status = (states[presence_rules[0]] if presence_rules else
                  ApplicabilityStatus.CONDITIONAL if ApplicabilityStatus.CONDITIONAL in states.values() else
                  ApplicabilityStatus.APPLICABLE)
        if status is ApplicabilityStatus.APPLICABLE and ApplicabilityStatus.CONDITIONAL in states.values():
            status = ApplicabilityStatus.CONDITIONAL
        paths = tuple(sorted({path for rule in contract.conditional_applicability_rules for path in rule.triggering_fact_paths}))
        if not paths:
            paths = tuple(item.fact_path for item in contract.substantive_content.fact_requirements if item.obligation.value != "forbidden")
        reason = "；".join(f"{rule.condition}：{labels[states[rule.conditional_applicability_rule_id]]}"
                           for rule in contract.conditional_applicability_rules) or "基础章节适用；内容充分性另行检查。"
        entries.append(ApplicabilityEntry(
            applicability_entry_id=f"applicability:{contract.semantic_node_id}",
            semantic_node_id=contract.semantic_node_id, status=status, reason=reason,
            triggering_fact_paths=paths, rule_id="ruleset:chapter-conditions",
        ))
    digest = hashlib.sha256(json.dumps({
        "contracts": sorted((c.chapter_contract_id, c.material_sha256()) for c in contracts),
        "rules": [rule.model_dump(mode="json") for rule in sorted(rules, key=lambda r: r.rule_id) if rule.rule_id in used_rule_ids],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    study_sha = study_revision_hash(study)
    snapshot_key = hashlib.sha256(f"{study_sha}:{digest}".encode()).hexdigest()[:24]
    return ApplicabilitySnapshot(
        applicability_snapshot_id=f"applicability:{snapshot_key}",
        study_definition_id=study.study_definition_id, study_definition_sha256=study_sha,
        ruleset_id="ruleset:chapter-conditions", ruleset_version="3r4b.1",
        ruleset_sha256=digest, entries=tuple(entries), created_at=created_at,
    )
