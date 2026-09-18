"""Recorded recommendation inputs, separate from historical decision status.

The producer supplies its actual read-set. This module proves whether those
recorded inputs remain unchanged; it does not prove medical approval or that
the producer disclosed every input. Recommendation assembly must verify that
coverage against its source context.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText, Sha256
from .hashing import exact_payload_sha256


class DecisionInputRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_path: NonEmptyText
    members: tuple[NonEmptyText, ...] = ()
    scope: Literal["fact", "all_facts"] = "fact"
    excluded_fact_paths: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "fact" and self.excluded_fact_paths:
            raise ValueError("exclusions require all_facts scope")
        if self.scope == "all_facts" and self.members:
            raise ValueError("all_facts scope cannot select nested members")
        return self


class DecisionInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["decision-input-binding.v1"] = "decision-input-binding.v1"
    adopted_revision_sha256: Sha256
    refs: tuple[DecisionInputRef, ...] = Field(min_length=1)
    value_sha256: tuple[Sha256, ...] = Field(min_length=1)
    fully_known: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_refs(self):
        if len(self.refs) != len(self.value_sha256) or len(set(self.refs)) != len(self.refs):
            raise ValueError("input bindings must have unique refs and matching values")
        return self


def input_refs_payload(refs):
    if refs is None:
        return None
    if not refs or any(not isinstance(ref, DecisionInputRef) for ref in refs):
        raise ValueError("decision input refs must be non-empty typed references")
    if len(set(refs)) != len(refs):
        raise ValueError("decision input refs must be unique")
    payloads = []
    for ref in refs:
        payload = ref.model_dump(mode="json")
        if ref.scope == "fact":
            payload.pop("scope")
            payload.pop("excluded_fact_paths")
        payloads.append(payload)
    return payloads


def _read(ref: DecisionInputRef, facts: Mapping[str, Any]):
    if ref.scope == "all_facts":
        return True, {key: value for key, value in facts.items() if key not in ref.excluded_fact_paths}
    # Dotted keys remain literal; nested members are explicit and independent.
    present = ref.fact_path in facts
    value = facts.get(ref.fact_path)
    for member in ref.members:
        if not isinstance(value, Mapping) or member not in value:
            present, value = False, None
            break
        value = value[member]
    return present, value


def bind_decision_inputs(refs, facts, adopted_revision_sha256):
    input_refs_payload(refs)
    values = [_read(ref, facts) for ref in refs]
    return DecisionInputBinding(
        adopted_revision_sha256=adopted_revision_sha256,
        refs=tuple(refs),
        value_sha256=tuple(exact_payload_sha256({"present": present, "value": value})
                           for present, value in values),
        fully_known=all(present and value is not None and value != ""
                        for present, value in values),
    )


def current_input_validity(binding: DecisionInputBinding, facts):
    current = bind_decision_inputs(binding.refs, facts, binding.adopted_revision_sha256)
    if current.value_sha256 != binding.value_sha256:
        return "stale"
    return "current" if binding.fully_known and current.fully_known else "unverified"


class ConfirmationDependency(BaseModel):
    """One medically-explained validity prerequisite of a human confirmation.

    The server declares which confirmed facts a decision card medically
    depends on, each with an explicit rationale. This is deliberately narrower
    than the producer read-set: a model reading every fact does not make every
    fact a medical precondition of the user's decision, and treating it so
    would reopen every card whenever any other card is confirmed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_path: NonEmptyText
    rationale: NonEmptyText


class ConfirmationBinding(BaseModel):
    """Server-side medical validity scope, frozen into the adoption event.

    Stored alongside (never instead of) the producer's
    ``decision_input_binding``: the producer binding remains the production
    reconciliation record, while this binding drives the user-facing
    current/stale validity of the confirmation. Unknown new fact keys are not
    silently irrelevant — their impact is computed through the typed
    dependency graph, not through this explicit list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["confirmation-binding.v1"] = "confirmation-binding.v1"
    decision_key: NonEmptyText
    adopted_revision_sha256: Sha256
    dependencies: tuple[ConfirmationDependency, ...] = ()
    value_sha256: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def validate_dependencies(self):
        if len(self.value_sha256) != len(self.dependencies):
            raise ValueError("confirmation binding must hash every dependency value")
        paths = [item.fact_path for item in self.dependencies]
        if len(set(paths)) != len(paths):
            raise ValueError("confirmation dependencies must have unique fact paths")
        return self


def bind_confirmation_dependencies(decision_key, dependencies, facts, adopted_revision_sha256):
    """Freeze the medical dependency values at confirmation time."""
    deps = tuple(
        item if isinstance(item, ConfirmationDependency) else ConfirmationDependency.model_validate(item)
        for item in (dependencies or ())
    )
    if len({item.fact_path for item in deps}) != len(deps):
        raise ValueError("confirmation dependencies must have unique fact paths")
    values = []
    for item in deps:
        parts = item.fact_path.split(".")
        present = item.fact_path in facts
        value = facts.get(item.fact_path)
        # Dotted paths are literal keys in the fact dictionary; no implicit
        # traversal beyond what the confirmed facts actually contain.
        if not present and len(parts) > 1:
            probe = facts
            for part in parts:
                if not isinstance(probe, Mapping) or part not in probe:
                    present, value = False, None
                    break
                probe = probe[part]
            else:
                present, value = True, probe
        values.append(exact_payload_sha256({"present": present, "value": value}))
    return ConfirmationBinding(
        decision_key=decision_key,
        adopted_revision_sha256=adopted_revision_sha256,
        dependencies=deps,
        value_sha256=tuple(values),
    )


def confirmation_validity(binding: ConfirmationBinding, facts):
    """Medical-dependency validity: stale only when a declared prerequisite changed."""
    current = bind_confirmation_dependencies(
        binding.decision_key, binding.dependencies, facts, binding.adopted_revision_sha256
    )
    if current.value_sha256 != binding.value_sha256:
        return "stale"
    return "current"
