"""Offline inventory contract for fixed project-adapter mapping surfaces.

The inventory records what the current adapters visibly hard-code (sheet/metric
or method evidence).  It is intentionally review-only: observations are not
activated mappings and never invoke a project adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable

from .monitoring_mapping_contract import MonitoringFieldKind
from .monitoring_study_config import (
    CORE_CAPABILITY_IDS,
    StudyFieldMapping,
    StudyMonitoringConfigError,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
_PATH_SEGMENT_RE = re.compile(r"(?:^|[/\\])(?:\.|\.\.)(?:[/\\]|$)")
_INVENTORY_REVISION = "adapter-mapping-inventory-v1"
REVIEW_ONLY_STATUS = "observed_requires_medical_review"


class StudyAdapterMappingPlanError(StudyMonitoringConfigError):
    """Raised when an observed adapter mapping inventory is unsafe or ambiguous."""


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StudyAdapterMappingPlanError(f"{field} is required")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _required(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise StudyAdapterMappingPlanError(f"{field} contains unsupported characters")
    return text


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StudyAdapterMappingObservation:
    """One source-code-observed mapping surface, pending medical review."""

    mapping_id: str
    adapter_key: str
    project_id: str
    domain: str
    source_sheet: str
    source_field: str
    capability_id: str
    observation_kind: str
    evidence_locator: str
    recommended_role: str
    field_kind: MonitoringFieldKind = MonitoringFieldKind.SOURCE_COLLECTED
    notes: str = ""
    review_status: str = REVIEW_ONLY_STATUS

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_id", _identifier(self.mapping_id, "mapping_id"))
        object.__setattr__(self, "adapter_key", _identifier(self.adapter_key, "adapter_key"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "domain", _required(self.domain, "domain"))
        source_sheet = _required(self.source_sheet, "source_sheet")
        source_field = _required(self.source_field, "source_field")
        if _ABSOLUTE_PATH_RE.match(source_sheet) or _PATH_SEGMENT_RE.search(source_sheet):
            raise StudyAdapterMappingPlanError("source_sheet must not be a local path")
        if _ABSOLUTE_PATH_RE.match(source_field) or _PATH_SEGMENT_RE.search(source_field):
            raise StudyAdapterMappingPlanError("source_field must not be a local path")
        object.__setattr__(self, "source_sheet", source_sheet)
        object.__setattr__(self, "source_field", source_field)
        capability_id = _identifier(self.capability_id, "capability_id")
        if capability_id not in CORE_CAPABILITY_IDS:
            raise StudyAdapterMappingPlanError(f"unsupported capability_id: {capability_id}")
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "observation_kind", _identifier(self.observation_kind, "observation_kind"))
        evidence = _required(self.evidence_locator, "evidence_locator")
        if _ABSOLUTE_PATH_RE.match(evidence) or _PATH_SEGMENT_RE.search(evidence):
            raise StudyAdapterMappingPlanError("evidence_locator must not be a local path")
        object.__setattr__(self, "evidence_locator", evidence)
        object.__setattr__(self, "recommended_role", _required(self.recommended_role, "recommended_role"))
        if not isinstance(self.field_kind, MonitoringFieldKind):
            try:
                object.__setattr__(self, "field_kind", MonitoringFieldKind(self.field_kind))
            except ValueError as exc:
                raise StudyAdapterMappingPlanError("field_kind is invalid") from exc
        status = _required(self.review_status, "review_status")
        if status != REVIEW_ONLY_STATUS:
            raise StudyAdapterMappingPlanError(
                "adapter mapping observations must remain review-only"
            )
        object.__setattr__(self, "review_status", status)
        object.__setattr__(self, "notes", str(self.notes or "").strip())
        # Reuse the C1 semantic boundary. The source field is the current adapter
        # field identity; no observation becomes an active mapping here.
        StudyFieldMapping(
            mapping_id=self.mapping_id,
            domain=self.domain,
            target_field=self.source_field,
            source_fields=(self.source_field,),
            recommended_role=self.recommended_role,
            field_kind=self.field_kind,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "domain": self.domain,
            "source_sheet": self.source_sheet,
            "source_field": self.source_field,
            "capability_id": self.capability_id,
            "observation_kind": self.observation_kind,
            "evidence_locator": self.evidence_locator,
            "recommended_role": self.recommended_role,
            "field_kind": self.field_kind.value,
            "notes": self.notes,
            "review_status": self.review_status,
        }


@dataclass(frozen=True)
class StudyAdapterMappingPlan:
    """Deterministic review-only inventory for one adapter/study."""

    adapter_key: str
    project_id: str
    trial_id: str
    observations: tuple[StudyAdapterMappingObservation, ...]
    inventory_revision: str = _INVENTORY_REVISION
    plan_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_key", _identifier(self.adapter_key, "adapter_key"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "trial_id", _identifier(self.trial_id, "trial_id"))
        observations = tuple(self.observations)
        if not observations:
            raise StudyAdapterMappingPlanError("mapping plan must contain observations")
        if any(not isinstance(item, StudyAdapterMappingObservation) for item in observations):
            raise StudyAdapterMappingPlanError("observations must contain observation objects")
        if any(
            item.adapter_key != self.adapter_key or item.project_id != self.project_id
            for item in observations
        ):
            raise StudyAdapterMappingPlanError(
                "observation adapter/project identity does not match mapping plan"
            )
        mapping_ids = [item.mapping_id for item in observations]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise StudyAdapterMappingPlanError("mapping observation ids must be unique")
        surface_keys = [
            (item.domain, item.source_sheet, item.source_field)
            for item in observations
        ]
        if len(surface_keys) != len(set(surface_keys)):
            raise StudyAdapterMappingPlanError(
                "mapping observations must not duplicate a source surface"
            )
        revision = _identifier(self.inventory_revision, "inventory_revision")
        ordered = tuple(sorted(observations, key=lambda item: item.mapping_id))
        object.__setattr__(self, "observations", ordered)
        object.__setattr__(self, "inventory_revision", revision)
        object.__setattr__(self, "plan_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "inventory_revision": self.inventory_revision,
            "observations": [item.to_dict() for item in self.observations],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "plan_sha256": self.plan_sha256}


def build_review_only_mapping_plan(
    *,
    adapter_key: str,
    project_id: str,
    trial_id: str,
    observations: Iterable[StudyAdapterMappingObservation],
) -> StudyAdapterMappingPlan:
    """Build an inventory without activating or persisting any mapping."""
    return StudyAdapterMappingPlan(
        adapter_key=adapter_key,
        project_id=project_id,
        trial_id=trial_id,
        observations=tuple(observations),
    )


__all__ = [
    "REVIEW_ONLY_STATUS",
    "StudyAdapterMappingObservation",
    "StudyAdapterMappingPlan",
    "StudyAdapterMappingPlanError",
    "build_review_only_mapping_plan",
]
