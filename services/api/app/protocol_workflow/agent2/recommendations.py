"""Bind design interpretation to every seed candidate without adopting any facts.

Array position is only an address inside the pinned intake. Relations are supplied
by the design producer and remain proposals; coverage is not medical validation.
"""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from packages.contracts.workbench_contracts.protocol_v3 import NonEmptyText


class CandidateAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: NonEmptyText
    index: int = Field(ge=0)
    destination: NonEmptyText
    relation: Literal["component", "alternative", "refinement", "duplicate", "context", "unresolved"]
    reason: NonEmptyText


def bind_candidate_coverage(seed: dict, *, input_sha256: str, assignments: list[dict]) -> list[dict]:
    """Retain each original candidate once alongside its proposed interpretation.

    No text/number extraction, source upgrade, default selection or fact write is
    performed. Downstream typed design must still resolve conflicts and obtain
    the appropriate human decisions through the existing application/CAS path.
    """
    if not input_sha256 or seed.get("input_sha256") != input_sha256:
        raise ValueError("design_candidate_input_mismatch")
    candidates = {(field, index): candidate
                  for field, values in seed["fields"].items()
                  for index, candidate in enumerate(values)}
    bound = []
    seen = set()
    for raw in assignments:
        item = CandidateAssignment.model_validate(raw)
        key = (item.field, item.index)
        if key in seen:
            raise ValueError("design_candidate_assignment_duplicate")
        if key not in candidates:
            raise ValueError("design_candidate_assignment_unknown")
        seen.add(key)
        bound.append({**item.model_dump(), "candidate": deepcopy(candidates[key])})
    if seen != set(candidates):
        raise ValueError("design_candidate_coverage_incomplete")
    return bound
