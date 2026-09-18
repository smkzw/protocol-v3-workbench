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
    return [ref.model_dump(mode="json") for ref in refs]


def _read(ref: DecisionInputRef, facts: Mapping[str, Any]):
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
