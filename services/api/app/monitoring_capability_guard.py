from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


READY_CAPABILITY_STATES = frozenset({"ready", "limited"})
UNAVAILABLE_CAPABILITY_STATES = frozenset(
    {"blocked_by_quality", "disabled_by_design"}
)


class MonitoringCapabilityContractError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        capability_id: str = "",
        state: str = "",
        limitation_codes: tuple[str, ...] = (),
    ) -> None:
        self.code = str(code).strip() or "monitoring_capability_contract_error"
        self.message = str(message).strip() or self.code
        self.capability_id = str(capability_id).strip()
        self.state = str(state).strip()
        self.limitation_codes = tuple(
            sorted({str(item).strip() for item in limitation_codes if str(item).strip()})
        )
        super().__init__(self.message)


@dataclass(frozen=True)
class MonitoringCapabilityDecision:
    capability_id: str
    state: str
    limitation_codes: tuple[str, ...]
    blocking_finding_group_ids: tuple[str, ...]

    @property
    def restricted(self) -> bool:
        return self.state == "limited"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "state": self.state,
            "limitation_codes": list(self.limitation_codes),
            "blocking_finding_group_ids": list(
                self.blocking_finding_group_ids
            ),
        }


_RULE_FAMILY_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "ae_mh_missing_review": ("ae_mh_reconciliation",),
    "cs_ncs_review": ("lab_ctcae_rules",),
    "study_treatment_change": ("protocol_medication_rules",),
    "study_treatment_adherence": (
        "protocol_medication_rules",
        "ip_exposure_adherence",
    ),
    "concomitant_medication_policy": ("protocol_medication_rules",),
    "visit_window_and_order": ("precise_temporal_rules",),
    "ae_sae_aesi_consistency": (
        "ae_mh_reconciliation",
        "standard_coding_rules",
    ),
    "laboratory_abnormality": ("lab_ctcae_rules",),
    "ctcae_longitudinal_worsening": (
        "lab_ctcae_rules",
        "precise_temporal_rules",
    ),
}

_STANDARD_CODING_MARKERS = re.compile(
    r"(?:meddra|whodrug|atc|snomed|coding|coded|standardized)",
    re.IGNORECASE,
)
_SCALE_RECALCULATION_MARKERS = re.compile(
    r"(?:scale|questionnaire|score|total_score|recalculat|derived_total)",
    re.IGNORECASE,
)


def capability_state_index(
    capability_states: Any,
) -> dict[str, Mapping[str, Any]]:
    if isinstance(capability_states, Mapping):
        items = []
        for capability_id, raw_state in capability_states.items():
            if isinstance(raw_state, Mapping):
                items.append(
                    {
                        "capability_id": capability_id,
                        **dict(raw_state),
                    }
                )
            else:
                items.append(
                    {
                        "capability_id": capability_id,
                        "state": raw_state,
                    }
                )
    elif isinstance(capability_states, (list, tuple)):
        items = list(capability_states)
    else:
        items = []

    index: dict[str, Mapping[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        capability_id = str(raw.get("capability_id") or "").strip()
        if not capability_id or capability_id in index:
            continue
        index[capability_id] = dict(raw)
    return index


def require_monitoring_capability_snapshot(
    capability_states: Any,
    capability_id: str,
) -> MonitoringCapabilityDecision:
    capability_id = str(capability_id).strip()
    if not capability_id:
        raise MonitoringCapabilityContractError(
            "monitoring_capability_id_required",
            "医学监查能力标识不能为空。",
        )
    raw = capability_state_index(capability_states).get(capability_id)
    if raw is None:
        raise MonitoringCapabilityContractError(
            "monitoring_capability_contract_missing",
            f"当前冻结映射未声明能力 {capability_id}，不能运行相关分析。",
            capability_id=capability_id,
        )
    state = str(raw.get("state") or "").strip()
    limitations = tuple(
        sorted(
            {
                str(item).strip()
                for item in raw.get("limitation_codes") or ()
                if str(item).strip()
            }
        )
    )
    finding_ids = tuple(
        sorted(
            {
                str(item).strip()
                for item in raw.get("blocking_finding_group_ids") or ()
                if str(item).strip()
            }
        )
    )
    if state in UNAVAILABLE_CAPABILITY_STATES:
        detail = "、".join(limitations) or state
        raise MonitoringCapabilityContractError(
            "monitoring_capability_unavailable",
            f"能力 {capability_id} 当前不可运行：{detail}。",
            capability_id=capability_id,
            state=state,
            limitation_codes=limitations,
        )
    if state not in READY_CAPABILITY_STATES:
        raise MonitoringCapabilityContractError(
            "monitoring_capability_state_invalid",
            f"能力 {capability_id} 的状态无效，不能运行相关分析。",
            capability_id=capability_id,
            state=state,
            limitation_codes=limitations,
        )
    return MonitoringCapabilityDecision(
        capability_id=capability_id,
        state=state,
        limitation_codes=limitations,
        blocking_finding_group_ids=finding_ids,
    )


def required_capabilities_for_rule(rule: Any) -> tuple[str, ...]:
    required = set(
        _RULE_FAMILY_CAPABILITIES.get(
            str(getattr(rule, "rule_family", "") or "").strip(),
            (),
        )
    )
    lineage = getattr(rule, "field_lineage", {}) or {}
    lineage_text = " ".join(
        [
            str(lineage),
            str(getattr(rule, "preconditions", {}) or {}),
            str(getattr(rule, "trigger_expression", {}) or {}),
            str(getattr(rule, "evidence_template", "") or ""),
        ]
    )
    if _STANDARD_CODING_MARKERS.search(lineage_text):
        required.add("standard_coding_rules")
    if _SCALE_RECALCULATION_MARKERS.search(lineage_text):
        required.add("scale_recalculation")
    if str(getattr(rule, "executor", "") or "").strip() == "temporal":
        required.add("precise_temporal_rules")
    return tuple(sorted(required))


def required_capabilities_for_rule_family(rule_family: str) -> tuple[str, ...]:
    """Return the frozen capability prerequisites for a rule family."""

    return tuple(
        _RULE_FAMILY_CAPABILITIES.get(
            str(rule_family or "").strip(),
            (),
        )
    )
