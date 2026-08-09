"""Read-only reconciliation contract for the Phase B authority migration.

The existing project has immutable risk snapshots and a separate disposition
log.  This module compares those inputs without opening a database or mutating
either side.  It is intentionally usable with both legacy ``RiskCase`` rows and
the B1 ``MedicalRiskAggregate`` contract.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RuxRiskDispositionRecord,
)

from .medical_risk_authority import MedicalRiskAggregate, MedicalRiskAuthorityError


class MedicalRiskReconciliationIssueCode(str, Enum):
    RISK_IDENTITY_GAP = "risk_identity_gap"
    DUPLICATE_RISK_INSTANCE = "duplicate_risk_instance"
    ORPHAN_DISPOSITION = "orphan_disposition"
    DISPOSITION_IDENTITY_MISMATCH = "disposition_identity_mismatch"
    SOURCE_VERSION_MAPPING_MISSING = "source_version_mapping_missing"
    DISPOSITION_SOURCE_VERSION_MISMATCH = "disposition_source_version_mismatch"
    DUPLICATE_DISPOSITION_EVENT = "duplicate_disposition_event"
    DISPOSITION_CHAIN_GAP = "disposition_chain_gap"
    AGGREGATE_STATE_DRIFT = "aggregate_state_drift"


@dataclass(frozen=True)
class MedicalRiskReconciliationIssue:
    code: MedicalRiskReconciliationIssueCode
    project_id: str
    risk_instance_id: str = ""
    risk_key: str = ""
    disposition_record_id: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("reconciliation issue project_id is required")
        if not self.detail.strip():
            raise ValueError("reconciliation issue detail is required")

    def public_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "project_id": self.project_id,
            "risk_instance_id": self.risk_instance_id,
            "risk_key": self.risk_key,
            "disposition_record_id": self.disposition_record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MedicalRiskReconciliationReport:
    risk_count: int
    disposition_count: int
    canonical_risk_count: int
    matched_disposition_count: int
    issues: tuple[MedicalRiskReconciliationIssue, ...]
    report_hash: str = ""

    def __post_init__(self) -> None:
        for name in (
            "risk_count",
            "disposition_count",
            "canonical_risk_count",
            "matched_disposition_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        ordered = tuple(
            sorted(
                self.issues,
                key=lambda issue: (
                    issue.code.value,
                    issue.project_id,
                    issue.risk_instance_id,
                    issue.risk_key,
                    issue.disposition_record_id,
                    issue.detail,
                ),
            )
        )
        object.__setattr__(self, "issues", ordered)
        calculated = _digest(self._hash_payload())
        if self.report_hash and self.report_hash != calculated:
            raise ValueError("report_hash does not match reconciliation contents")
        object.__setattr__(self, "report_hash", calculated)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def blocking_issue_count(self) -> int:
        return len(self.issues)

    @property
    def migration_ready(self) -> bool:
        return not self.issues

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "risk_count": self.risk_count,
            "disposition_count": self.disposition_count,
            "canonical_risk_count": self.canonical_risk_count,
            "matched_disposition_count": self.matched_disposition_count,
            "issues": [issue.public_dict() for issue in self.issues],
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            **self._hash_payload(),
            "issue_count": self.issue_count,
            "blocking_issue_count": self.blocking_issue_count,
            "migration_ready": self.migration_ready,
            "report_hash": self.report_hash,
        }


@dataclass(frozen=True)
class _RiskRef:
    project_id: str
    risk_id: str
    risk_key: str
    risk_instance_id: str
    source_revision: str
    subject_id: str | None
    site_id: str | None
    aggregate: MedicalRiskAggregate | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_version_set(
    mapping: Mapping[tuple[str, str], str | Sequence[str]] | None,
    key: tuple[str, str],
) -> tuple[str, ...] | None:
    if mapping is None or key not in mapping:
        return None
    value = mapping[key]
    values = (value,) if isinstance(value, str) else tuple(value)
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _risk_ref(
    value: RiskCase | MedicalRiskAggregate,
    *,
    trial_ids_by_project: Mapping[str, str],
) -> tuple[_RiskRef | None, MedicalRiskReconciliationIssue | None]:
    if isinstance(value, MedicalRiskAggregate):
        identity = value.identity
        return (
            _RiskRef(
                project_id=identity.project_id,
                risk_id="",
                risk_key=identity.risk_key,
                risk_instance_id=identity.risk_instance_id,
                source_revision=value.source_revision,
                subject_id=identity.subject_id,
                site_id=identity.site_id,
                aggregate=value,
            ),
            None,
        )

    trial_id = str(trial_ids_by_project.get(value.project_id, "")).strip()
    try:
        aggregate = MedicalRiskAggregate.from_risk_case(value, trial_id=trial_id)
    except (MedicalRiskAuthorityError, ValueError) as exc:
        risk_key = str(value.risk_key or value.risk_id).strip()
        instance_id = str(value.risk_instance_id or value.risk_id).strip()
        return (
            None,
            MedicalRiskReconciliationIssue(
                code=MedicalRiskReconciliationIssueCode.RISK_IDENTITY_GAP,
                project_id=value.project_id,
                risk_instance_id=instance_id,
                risk_key=risk_key,
                detail=str(exc),
            ),
        )
    identity = aggregate.identity
    return (
        _RiskRef(
            project_id=identity.project_id,
            risk_id=value.risk_id,
            risk_key=identity.risk_key,
            risk_instance_id=identity.risk_instance_id,
            source_revision=aggregate.source_revision,
            subject_id=identity.subject_id,
            site_id=identity.site_id,
            aggregate=aggregate,
        ),
        None,
    )


def _disposition_fingerprint(record: RuxRiskDispositionRecord) -> tuple[str, ...]:
    return (
        record.project_id,
        record.item_id,
        record.source_version,
        record.action.value,
        record.new_state,
        record.comment.strip(),
        record.query_draft_text.strip(),
        record.actor.strip(),
    )


def reconcile_medical_risk_records(
    risks: Iterable[RiskCase | MedicalRiskAggregate],
    dispositions: Iterable[RuxRiskDispositionRecord],
    *,
    trial_ids_by_project: Mapping[str, str] | None = None,
    expected_source_versions: Mapping[
        tuple[str, str], str | Sequence[str]
    ] | None = None,
) -> MedicalRiskReconciliationReport:
    """Compare legacy snapshot facts with disposition records without mutation.

    ``expected_source_versions`` is deliberately explicit.  A disposition's
    source token is produced by the current adapter and cannot safely be
    reconstructed from a stale ``RiskCase`` row during migration.
    """

    risk_values = tuple(risks)
    disposition_values = tuple(dispositions)
    trial_mapping = trial_ids_by_project or {}
    issues: list[MedicalRiskReconciliationIssue] = []
    refs: list[_RiskRef] = []
    for value in risk_values:
        ref, issue = _risk_ref(value, trial_ids_by_project=trial_mapping)
        if issue is not None:
            issues.append(issue)
        if ref is not None:
            refs.append(ref)

    by_instance: dict[tuple[str, str], _RiskRef] = {}
    by_key: dict[tuple[str, str], _RiskRef] = {}
    for ref in refs:
        instance_key = (ref.project_id, ref.risk_instance_id)
        key_key = (ref.project_id, ref.risk_key)
        if instance_key in by_instance:
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=MedicalRiskReconciliationIssueCode.DUPLICATE_RISK_INSTANCE,
                    project_id=ref.project_id,
                    risk_instance_id=ref.risk_instance_id,
                    risk_key=ref.risk_key,
                    detail="more than one source risk row maps to the same project/risk_instance_id",
                )
            )
        else:
            by_instance[instance_key] = ref
        by_key.setdefault(key_key, ref)

    grouped_dispositions: dict[tuple[str, str, str], list[RuxRiskDispositionRecord]] = defaultdict(list)
    matched_disposition_count = 0
    for record in disposition_values:
        requested_instance = str(record.risk_instance_id or record.risk_id).strip()
        instance_key = (record.project_id, requested_instance)
        ref = by_instance.get(instance_key)
        if ref is None:
            key_ref = by_key.get((record.project_id, record.risk_key.strip())) if record.risk_key else None
            legacy_ref = next(
                (
                    candidate
                    for candidate in refs
                    if candidate.project_id == record.project_id
                    and candidate.risk_id
                    and candidate.risk_id == record.risk_id
                ),
                None,
            )
            mapped_ref = key_ref or legacy_ref
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=(
                        MedicalRiskReconciliationIssueCode.DISPOSITION_IDENTITY_MISMATCH
                        if mapped_ref is not None
                        else MedicalRiskReconciliationIssueCode.ORPHAN_DISPOSITION
                    ),
                    project_id=record.project_id,
                    risk_instance_id=requested_instance,
                    risk_key=record.risk_key,
                    disposition_record_id=record.record_id,
                    detail=(
                        "disposition identity does not match the source risk instance; legacy risk_id/key provides a migration candidate"
                        if mapped_ref is not None
                        else "disposition has no matching source risk instance"
                    ),
                )
            )
            continue

        if record.risk_key and record.risk_key != ref.risk_key:
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=MedicalRiskReconciliationIssueCode.DISPOSITION_IDENTITY_MISMATCH,
                    project_id=record.project_id,
                    risk_instance_id=ref.risk_instance_id,
                    risk_key=record.risk_key,
                    disposition_record_id=record.record_id,
                    detail=(
                        f"disposition risk_key={record.risk_key!r} does not match "
                        f"source risk_key={ref.risk_key!r}"
                    ),
                )
            )
        if record.subject_id and record.subject_id != (ref.subject_id or ""):
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=MedicalRiskReconciliationIssueCode.DISPOSITION_IDENTITY_MISMATCH,
                    project_id=record.project_id,
                    risk_instance_id=ref.risk_instance_id,
                    risk_key=ref.risk_key,
                    disposition_record_id=record.record_id,
                    detail=(
                        f"disposition subject_id={record.subject_id!r} does not match "
                        f"source subject_id={ref.subject_id!r}"
                    ),
                )
            )

        expected_versions = _source_version_set(
            expected_source_versions,
            (ref.project_id, ref.risk_instance_id),
        )
        if expected_versions is None:
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=MedicalRiskReconciliationIssueCode.SOURCE_VERSION_MAPPING_MISSING,
                    project_id=ref.project_id,
                    risk_instance_id=ref.risk_instance_id,
                    risk_key=ref.risk_key,
                    disposition_record_id=record.record_id,
                    detail="migration requires an explicit adapter source-version mapping",
                )
            )
        elif record.source_version not in expected_versions:
            issues.append(
                MedicalRiskReconciliationIssue(
                    code=MedicalRiskReconciliationIssueCode.DISPOSITION_SOURCE_VERSION_MISMATCH,
                    project_id=ref.project_id,
                    risk_instance_id=ref.risk_instance_id,
                    risk_key=ref.risk_key,
                    disposition_record_id=record.record_id,
                    detail=(
                        f"disposition source_version={record.source_version!r} is not in "
                        f"expected mapping {expected_versions!r}"
                    ),
                )
            )
        else:
            matched_disposition_count += 1

        grouped_dispositions[(record.project_id, requested_instance, record.source_version)].append(record)

    for group_key, records in grouped_dispositions.items():
        ordered = sorted(records, key=lambda item: (_utc(item.created_at), item.record_id))
        fingerprints = Counter(_disposition_fingerprint(record) for record in ordered)
        ref = by_instance.get((group_key[0], group_key[1]))
        for fingerprint, count in fingerprints.items():
            if count > 1:
                duplicate = next(record for record in ordered if _disposition_fingerprint(record) == fingerprint)
                issues.append(
                    MedicalRiskReconciliationIssue(
                        code=MedicalRiskReconciliationIssueCode.DUPLICATE_DISPOSITION_EVENT,
                        project_id=group_key[0],
                        risk_instance_id=group_key[1],
                        risk_key=ref.risk_key if ref else "",
                        disposition_record_id=duplicate.record_id,
                        detail=f"identical disposition business event appears {count} times",
                    )
                )
        previous_state = "pending_review"
        for record in ordered:
            if record.previous_state != previous_state:
                issues.append(
                    MedicalRiskReconciliationIssue(
                        code=MedicalRiskReconciliationIssueCode.DISPOSITION_CHAIN_GAP,
                        project_id=group_key[0],
                        risk_instance_id=group_key[1],
                        risk_key=ref.risk_key if ref else "",
                        disposition_record_id=record.record_id,
                        detail=(
                            f"expected previous_state={previous_state!r}, "
                            f"found {record.previous_state!r}"
                        ),
                    )
                )
            previous_state = record.new_state

        if ref is not None and ref.aggregate is not None:
            latest = ordered[-1]
            expected_state = ref.aggregate.disposition_state.value
            if latest.new_state != expected_state:
                issues.append(
                    MedicalRiskReconciliationIssue(
                        code=MedicalRiskReconciliationIssueCode.AGGREGATE_STATE_DRIFT,
                        project_id=ref.project_id,
                        risk_instance_id=ref.risk_instance_id,
                        risk_key=ref.risk_key,
                        disposition_record_id=latest.record_id,
                        detail=(
                            f"aggregate disposition_state={expected_state!r} differs from "
                            f"latest disposition state={latest.new_state!r}"
                        ),
                    )
                )

    return MedicalRiskReconciliationReport(
        risk_count=len(risk_values),
        disposition_count=len(disposition_values),
        canonical_risk_count=len(by_instance),
        matched_disposition_count=matched_disposition_count,
        issues=tuple(issues),
    )


__all__ = [
    "MedicalRiskReconciliationIssue",
    "MedicalRiskReconciliationIssueCode",
    "MedicalRiskReconciliationReport",
    "reconcile_medical_risk_records",
]
