"""Non-writing legacy-to-current risk identity mapping candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from packages.contracts.workbench_contracts.models import RiskCase, RuxRiskDispositionRecord

from .medical_risk_authority import MedicalRiskAggregate


class MedicalRiskMappingBasis(str, Enum):
    EXACT_RISK_ID = "exact_risk_id"
    EXACT_RISK_KEY = "exact_risk_key"
    ITEM_ID_SUFFIX = "item_id_suffix"
    AMBIGUOUS = "ambiguous"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class MedicalRiskMappingCandidate:
    disposition_record_id: str
    project_id: str
    legacy_risk_id: str
    legacy_risk_key: str
    legacy_risk_instance_id: str
    current_risk_id: str = ""
    current_risk_key: str = ""
    current_risk_instance_id: str = ""
    current_subject_id: str = ""
    current_site_id: str = ""
    current_source_revision: str = ""
    basis: MedicalRiskMappingBasis = MedicalRiskMappingBasis.NO_CANDIDATE
    confidence: str = "none"
    approved: bool = False
    write_permitted: bool = False
    review_required: bool = True
    review_note: str = ""

    @property
    def has_candidate(self) -> bool:
        return bool(self.current_risk_instance_id)

    def public_dict(self) -> dict[str, object]:
        return {
            "disposition_record_id": self.disposition_record_id,
            "project_id": self.project_id,
            "legacy_risk_id": self.legacy_risk_id,
            "legacy_risk_key": self.legacy_risk_key,
            "legacy_risk_instance_id": self.legacy_risk_instance_id,
            "current_risk_id": self.current_risk_id,
            "current_risk_key": self.current_risk_key,
            "current_risk_instance_id": self.current_risk_instance_id,
            "current_subject_id": self.current_subject_id,
            "current_site_id": self.current_site_id,
            "current_source_revision": self.current_source_revision,
            "basis": self.basis.value,
            "confidence": self.confidence,
            "approved": self.approved,
            "write_permitted": self.write_permitted,
            "review_required": self.review_required,
            "review_note": self.review_note,
        }


def _risk_values(value: RiskCase | MedicalRiskAggregate) -> dict[str, str]:
    if isinstance(value, MedicalRiskAggregate):
        identity = value.identity
        return {
            "risk_id": "",
            "risk_key": identity.risk_key,
            "risk_instance_id": identity.risk_instance_id,
            "project_id": identity.project_id,
            "subject_id": identity.subject_id or "",
            "site_id": identity.site_id or "",
            "source_revision": value.source_revision,
        }
    return {
        "risk_id": value.risk_id,
        "risk_key": value.risk_key or value.risk_id,
        "risk_instance_id": value.risk_instance_id or value.risk_id,
        "project_id": value.project_id,
        "subject_id": value.subject_id or "",
        "site_id": value.site_id or "",
        "source_revision": value.source_revision,
    }


def propose_legacy_risk_mappings(
    dispositions: Iterable[RuxRiskDispositionRecord],
    risks: Iterable[RiskCase | MedicalRiskAggregate],
) -> tuple[MedicalRiskMappingCandidate, ...]:
    """Create review-only candidates using stable identity evidence only."""

    risk_rows = tuple(_risk_values(risk) for risk in risks)
    candidates: list[MedicalRiskMappingCandidate] = []
    for record in dispositions:
        legacy_risk_id = str(record.risk_id or "").strip()
        legacy_risk_key = str(record.risk_key or "").strip()
        legacy_instance = str(record.risk_instance_id or "").strip()
        project_rows = [row for row in risk_rows if row["project_id"] == record.project_id]
        exact_id = [row for row in project_rows if legacy_risk_id and row["risk_id"] == legacy_risk_id]
        exact_key = [row for row in project_rows if legacy_risk_key and row["risk_key"] == legacy_risk_key]
        suffix = str(record.item_id or "").rsplit(":", 1)[-1]
        suffix_matches = [
            row
            for row in project_rows
            if suffix and suffix in {row["risk_id"], row["risk_key"], row["risk_instance_id"]}
        ]

        selected: list[dict[str, str]]
        basis: MedicalRiskMappingBasis
        confidence: str
        note: str
        if len(exact_id) == 1:
            selected = exact_id
            basis = MedicalRiskMappingBasis.EXACT_RISK_ID
            confidence = "high"
            note = "legacy risk_id uniquely identifies one current risk row; medical review still required"
        elif len(exact_key) == 1:
            selected = exact_key
            basis = MedicalRiskMappingBasis.EXACT_RISK_KEY
            confidence = "high"
            note = "legacy risk_key uniquely identifies one current risk row; medical review still required"
        elif len(suffix_matches) == 1:
            selected = suffix_matches
            basis = MedicalRiskMappingBasis.ITEM_ID_SUFFIX
            confidence = "medium"
            note = "item_id suffix is only a fallback locator; medical review is mandatory"
        elif len({row["risk_instance_id"] for row in exact_id + exact_key + suffix_matches}) > 1:
            selected = []
            basis = MedicalRiskMappingBasis.AMBIGUOUS
            confidence = "none"
            note = "stable legacy locators point to multiple current rows; no mapping proposed"
        else:
            selected = []
            basis = MedicalRiskMappingBasis.NO_CANDIDATE
            confidence = "none"
            note = "no stable project-scoped legacy locator identifies a current risk row"

        current = selected[0] if len(selected) == 1 else None
        candidates.append(
            MedicalRiskMappingCandidate(
                disposition_record_id=record.record_id,
                project_id=record.project_id,
                legacy_risk_id=legacy_risk_id,
                legacy_risk_key=legacy_risk_key,
                legacy_risk_instance_id=legacy_instance,
                current_risk_id=current["risk_id"] if current else "",
                current_risk_key=current["risk_key"] if current else "",
                current_risk_instance_id=current["risk_instance_id"] if current else "",
                current_subject_id=current["subject_id"] if current else "",
                current_site_id=current["site_id"] if current else "",
                current_source_revision=current["source_revision"] if current else "",
                basis=basis,
                confidence=confidence,
                review_note=note,
            )
        )
    return tuple(sorted(candidates, key=lambda item: (item.project_id, item.disposition_record_id)))


def remap_disposition_for_dry_run(
    record: RuxRiskDispositionRecord,
    candidate: MedicalRiskMappingCandidate,
) -> RuxRiskDispositionRecord:
    """Return an in-memory copy; never mark the candidate approved or write it."""

    if not candidate.has_candidate:
        return record.model_copy(deep=True)
    return record.model_copy(
        deep=True,
        update={
            "risk_id": candidate.current_risk_id or record.risk_id,
            "risk_key": candidate.current_risk_key,
            "risk_instance_id": candidate.current_risk_instance_id,
            "item_id": f"monitoring-risk:{candidate.current_risk_instance_id}",
        },
    )


__all__ = [
    "MedicalRiskMappingBasis",
    "MedicalRiskMappingCandidate",
    "propose_legacy_risk_mappings",
    "remap_disposition_for_dry_run",
]
