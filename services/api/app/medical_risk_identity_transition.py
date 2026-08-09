"""Pure, read-only identity transition semantics for medical-risk history.

The persisted ``RiskCase`` contract intentionally keeps the current risk fact
and its batch delta. This module turns that low-level delta into an explicit
history relationship for projections. It never copies a disposition and it
never mutates a risk or a repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from packages.contracts.workbench_contracts.models import RiskCase


class MedicalRiskIdentityTransitionKind(str, Enum):
    NEW = "new"
    CONTINUATION = "continuation"
    REOPEN = "reopen"
    SUPERSEDE = "supersede"


class MedicalRiskDispositionLineage(str, Enum):
    NONE = "none"
    PRESERVE = "preserve"
    HISTORY_ONLY = "history_only"


@dataclass(frozen=True)
class MedicalRiskIdentityTransition:
    """One explicit relation between adjacent risk instances.

    ``HISTORY_ONLY`` is deliberately used for reopen/supersede. A prior
    disposition may be displayed as context, but it is not an instruction to
    apply that disposition to the current instance.
    """

    kind: MedicalRiskIdentityTransitionKind
    project_id: str
    risk_key: str
    current_risk_instance_id: str
    previous_risk_instance_id: str = ""
    disposition_lineage: MedicalRiskDispositionLineage = (
        MedicalRiskDispositionLineage.NONE
    )
    reason_code: str = ""

    @property
    def supersedes_risk_instance_id(self) -> str:
        if self.kind is MedicalRiskIdentityTransitionKind.SUPERSEDE:
            return self.previous_risk_instance_id
        return ""

    @property
    def label(self) -> str:
        return {
            MedicalRiskIdentityTransitionKind.NEW: "新增实例",
            MedicalRiskIdentityTransitionKind.CONTINUATION: "风险持续",
            MedicalRiskIdentityTransitionKind.REOPEN: "风险重开",
            MedicalRiskIdentityTransitionKind.SUPERSEDE: "新实例取代旧实例",
        }[self.kind]

    def public_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "project_id": self.project_id,
            "risk_key": self.risk_key,
            "current_risk_instance_id": self.current_risk_instance_id,
            "previous_risk_instance_id": self.previous_risk_instance_id,
            "supersedes_risk_instance_id": self.supersedes_risk_instance_id,
            "disposition_lineage": self.disposition_lineage.value,
            "reason_code": self.reason_code,
        }


def classify_risk_identity_transition(
    previous: RiskCase | None,
    current: RiskCase,
) -> MedicalRiskIdentityTransition:
    """Classify one current history row against its previous row.

    The function is intentionally strict about stable identity. A caller that
    compares different projects or different ``risk_key`` values has not
    supplied an adjacent history pair and must not receive an inferred
    continuation.
    """

    if not current.project_id.strip():
        raise ValueError("current risk project_id is required")
    if not current.risk_key.strip():
        raise ValueError("current risk_key is required")
    current_instance = current.risk_instance_id.strip() or current.risk_id.strip()
    if not current_instance:
        raise ValueError("current risk_instance_id is required")

    if previous is None:
        return MedicalRiskIdentityTransition(
            kind=MedicalRiskIdentityTransitionKind.NEW,
            project_id=current.project_id,
            risk_key=current.risk_key,
            current_risk_instance_id=current_instance,
            reason_code="first_observed_instance",
        )

    if previous.project_id != current.project_id:
        raise ValueError("risk transition project_id mismatch")
    if previous.risk_key != current.risk_key:
        raise ValueError("risk transition risk_key mismatch")
    previous_instance = previous.risk_instance_id.strip() or previous.risk_id.strip()
    if not previous_instance:
        raise ValueError("previous risk_instance_id is required")

    if current.batch_delta == "reopened":
        if current_instance == previous_instance:
            raise ValueError("reopened risk must use a new risk_instance_id")
        return MedicalRiskIdentityTransition(
            kind=MedicalRiskIdentityTransitionKind.REOPEN,
            project_id=current.project_id,
            risk_key=current.risk_key,
            current_risk_instance_id=current_instance,
            previous_risk_instance_id=previous_instance,
            disposition_lineage=MedicalRiskDispositionLineage.HISTORY_ONLY,
            reason_code="closed_or_resolved_risk_triggered_again",
        )

    if current.batch_delta in {
        "superseded_by_engine",
        "changed",
        "requires_rereview",
    }:
        if current_instance == previous_instance:
            raise ValueError(
                "changed or rereview risk must use a new risk_instance_id"
            )
        return MedicalRiskIdentityTransition(
            kind=MedicalRiskIdentityTransitionKind.SUPERSEDE,
            project_id=current.project_id,
            risk_key=current.risk_key,
            current_risk_instance_id=current_instance,
            previous_risk_instance_id=previous_instance,
            disposition_lineage=MedicalRiskDispositionLineage.HISTORY_ONLY,
            reason_code=(
                "engine_or_rule_identity_changed"
                if current.batch_delta == "superseded_by_engine"
                else "source_or_medical_meaning_changed"
            ),
        )

    return MedicalRiskIdentityTransition(
        kind=MedicalRiskIdentityTransitionKind.CONTINUATION,
        project_id=current.project_id,
        risk_key=current.risk_key,
        current_risk_instance_id=current_instance,
        previous_risk_instance_id=previous_instance,
        disposition_lineage=MedicalRiskDispositionLineage.PRESERVE,
        reason_code="same_risk_semantics_across_batches",
    )


__all__ = [
    "MedicalRiskDispositionLineage",
    "MedicalRiskIdentityTransition",
    "MedicalRiskIdentityTransitionKind",
    "classify_risk_identity_transition",
]
