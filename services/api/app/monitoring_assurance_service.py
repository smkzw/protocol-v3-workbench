from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .medical_monitoring_risk_taxonomy import project_risk_category
from .monitoring_assurance_repository import (
    AssuranceDriftError,
    AssuranceTask,
    AssuranceTaskMutationResult,
    AssuranceTaskStateConflictError,
    AssuranceVersionConflictError,
    FullRecomputeProof,
    MonitoringAssuranceError,
    MonitoringAssuranceAuditContext,
    MonitoringAssuranceRepository,
    RollupSummary,
)


_CONCOMITANT_MEDICATION_CATEGORY_CODES = frozenset(
    {
        "prohibited_concomitant_medication_pd",
        "restricted_concomitant_medication_pd",
    }
)
_STUDY_TREATMENT_CATEGORY_CODES = frozenset(
    {
        "study_treatment_dose_change",
        "study_treatment_interruption",
        "study_treatment_permanent_discontinuation",
        "study_treatment_restart",
        "study_treatment_adherence",
    }
)


# ---------------------------------------------------------------------------
# Risk reference interface
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskReference:
    """Lightweight reference to a persisted risk instance.

    The service never copies risk facts — it stores only IDs/references.
    """

    risk_instance_id: str
    risk_key: str
    project_id: str
    subject_id: str
    site_id: str
    primary_category: str
    severity: str
    status: str
    scope_type: str
    scope_id: str
    batch_delta: str
    is_safety_pv: bool
    is_concomitant_medication: bool
    is_study_treatment: bool
    closure_evidence_present: bool


def create_medical_risk_reference_reader(
    risk_repository: Any,
) -> Callable[[str, str], List[RiskReference]]:
    """Project the current pinned risk snapshot to minimal assurance references."""

    def read(project_id: str, snapshot_id: str) -> List[RiskReference]:
        try:
            current_snapshot = risk_repository.current_snapshot(project_id)
            pinned_snapshot = risk_repository.snapshot(project_id, snapshot_id)
        except KeyError as exc:
            raise AssuranceDriftError(
                "pinned risk snapshot is unavailable for the current project"
            ) from exc
        if (
            pinned_snapshot.project_id != project_id
            or current_snapshot.snapshot_id != pinned_snapshot.snapshot_id
        ):
            raise AssuranceDriftError(
                "current risk snapshot differs from the task's pinned snapshot"
            )

        references: List[RiskReference] = []
        seen_instance_ids: set[str] = set()
        for risk in risk_repository.list_risks(
            project_id,
            pinned_snapshot.snapshot_id,
        ):
            if risk.project_id != project_id:
                raise AssuranceDriftError(
                    "risk instance project differs from the pinned snapshot project"
                )
            if risk.risk_instance_id in seen_instance_ids:
                raise MonitoringAssuranceError(
                    "pinned risk snapshot contains duplicate risk instance identities"
                )
            seen_instance_ids.add(risk.risk_instance_id)
            category_code = str(
                project_risk_category(risk)["risk_category_code"]
            )
            tags = {str(tag).strip() for tag in (risk.tags or [])}
            references.append(
                RiskReference(
                    risk_instance_id=risk.risk_instance_id,
                    risk_key=risk.risk_key,
                    project_id=risk.project_id,
                    subject_id=risk.subject_id or "",
                    site_id=risk.site_id or "",
                    primary_category=category_code,
                    severity=risk.severity.value,
                    status=risk.status.value,
                    scope_type=risk.scope_type,
                    scope_id=risk.scope_id,
                    batch_delta=risk.batch_delta,
                    is_safety_pv="safety_pv" in tags,
                    is_concomitant_medication=(
                        category_code
                        in _CONCOMITANT_MEDICATION_CATEGORY_CODES
                    ),
                    is_study_treatment=(
                        category_code in _STUDY_TREATMENT_CATEGORY_CODES
                    ),
                    closure_evidence_present=bool(
                        str(risk.closure_evidence or "").strip()
                    ),
                )
            )
        return references

    return read


# ---------------------------------------------------------------------------
# Site clustering
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SiteClusterEntry:
    site_id: str
    numerator: int
    denominator: int
    missing_count: int
    missing_rate: float
    method_identity: str
    sample_adequate: bool
    signal_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "site_id": self.site_id,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "missing_count": self.missing_count,
            "missing_rate": round(self.missing_rate, 4),
            "method_identity": self.method_identity,
            "sample_adequate": self.sample_adequate,
            "signal_status": self.signal_status,
        }


def compute_site_clusters(
    risks: Sequence[RiskReference],
    *,
    site_method_approved: bool,
    min_sample_size: int = 30,
) -> List[SiteClusterEntry]:
    """Compute descriptive site clusters.

    Without a project-approved method or with inadequate sample,
    signal_status must be ``descriptive_only``.
    Never label a site abnormal or noncompliant.
    """
    site_groups: Dict[str, List[RiskReference]] = {}
    for risk in risks:
        site_groups.setdefault(risk.site_id, []).append(risk)

    results: List[SiteClusterEntry] = []
    for site_id in sorted(site_groups):
        group = site_groups[site_id]
        denominator = len({r.subject_id for r in group if r.subject_id})
        if denominator == 0:
            denominator = len(group)
        numerator = len(group)
        missing_subjects = {
            r.subject_id for r in group if not r.closure_evidence_present
        }
        missing_count = len(missing_subjects)
        missing_rate = (missing_count / denominator) if denominator else 0.0
        sample_adequate = denominator >= min_sample_size and numerator > 0
        if not site_method_approved or not sample_adequate:
            signal_status = "descriptive_only"
        else:
            signal_status = "evaluated"
        results.append(
            SiteClusterEntry(
                site_id=site_id,
                numerator=numerator,
                denominator=denominator,
                missing_count=missing_count,
                missing_rate=missing_rate,
                method_identity=(
                    "project_approved"
                    if site_method_approved
                    else "no_project_method"
                ),
                sample_adequate=sample_adequate,
                signal_status=signal_status,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    gaps: Tuple[str, ...]
    frozen_identity_ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "gaps": list(self.gaps),
            "frozen_identity_ok": self.frozen_identity_ok,
        }


def evaluate_readiness(
    task: AssuranceTask,
    *,
    current_identity: Optional[Mapping[str, Any]] = None,
    planned_subjects: int = 0,
    actual_subjects: int = 0,
    planned_sites: int = 0,
    actual_sites: int = 0,
    critical_domains_covered: int = 0,
    critical_domains_expected: int = 0,
) -> ReadinessResult:
    gaps: List[str] = []
    frozen_ok = True
    if current_identity is not None:
        if not task.frozen_identity.matches(current_identity):
            frozen_ok = False
            gaps.append("frozen_identity_drift")
    if planned_subjects > 0 and actual_subjects < planned_subjects:
        gaps.append("subject_coverage_incomplete")
    if planned_sites > 0 and actual_sites < planned_sites:
        gaps.append("site_coverage_incomplete")
    if critical_domains_expected > 0 and critical_domains_covered < critical_domains_expected:
        gaps.append("critical_domain_coverage_incomplete")
    return ReadinessResult(
        ready=frozen_ok and len(gaps) == 0,
        gaps=tuple(gaps),
        frozen_identity_ok=frozen_ok,
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _instance_set(risks: Sequence[RiskReference]) -> set:
    return {r.risk_instance_id for r in risks}


def reconcile_three_levels(
    risks: Sequence[RiskReference],
) -> Dict[str, Any]:
    """Exact three-level instance reconciliation (subject → site → trial).

    Instance set equality is stronger than count equality.
    """
    risk_instances = _instance_set(risks)

    subject_map: Dict[str, set] = {}
    site_map: Dict[str, set] = {}
    for risk in risks:
        sid = risk.subject_id or "(none)"
        site = risk.site_id or "(none)"
        subject_map.setdefault(sid, set()).add(risk.risk_instance_id)
        site_map.setdefault(site, set()).add(risk.risk_instance_id)

    subject_union: set = set()
    for instances in subject_map.values():
        subject_union |= instances
    site_union: set = set()
    for instances in site_map.values():
        site_union |= instances

    subject_ok = subject_union == risk_instances
    site_ok = site_union == risk_instances
    trial_ok = len(risk_instances) == len(risks)

    return {
        "total_risk_count": len(risks),
        "unique_risk_instance_count": len(risk_instances),
        "subject_level_instance_count": len(subject_union),
        "site_level_instance_count": len(site_union),
        "subject_reconciliation_ok": subject_ok,
        "site_reconciliation_ok": site_ok,
        "trial_reconciliation_ok": trial_ok,
        "all_levels_consistent": subject_ok and site_ok and trial_ok,
    }


# ---------------------------------------------------------------------------
# Rollup building (pre_inspection)
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {"resolved", "closed", "superseded"}
_HIGH_SEVERITIES = {"high", "critical"}


def _is_closed(risk: RiskReference) -> bool:
    return risk.status.lower() in _TERMINAL_STATUSES


def _is_open(risk: RiskReference) -> bool:
    return not _is_closed(risk)


def _is_high(risk: RiskReference) -> bool:
    return risk.severity.lower() in _HIGH_SEVERITIES


def build_rollup_payload(
    *,
    task: AssuranceTask,
    risks: Sequence[RiskReference],
    site_clusters: Sequence[SiteClusterEntry],
) -> Dict[str, Any]:
    """Build the three-level rollup from the pinned risk snapshot.

    Stores risk instance IDs/references only — never copies risk facts or evidence blobs.
    """
    by_subject: Dict[str, List[RiskReference]] = {}
    by_site: Dict[str, List[RiskReference]] = {}
    for risk in risks:
        sid = risk.subject_id or "(none)"
        site = risk.site_id or "(none)"
        by_subject.setdefault(sid, []).append(risk)
        by_site.setdefault(site, []).append(risk)

    subject_rollup: List[Dict[str, Any]] = []
    for sid in sorted(by_subject):
        group = by_subject[sid]
        open_risks = [r for r in group if _is_open(r)]
        subject_rollup.append(
            {
                "subject_id": sid,
                "total_risk_count": len(group),
                "open_risk_count": len(open_risks),
                "risk_instance_ids": sorted(r.risk_instance_id for r in group),
                "site_id": group[0].site_id,
            }
        )

    site_rollup: List[Dict[str, Any]] = []
    for site_id in sorted(by_site):
        group = by_site[site_id]
        open_risks = [r for r in group if _is_open(r)]
        high_open = [r for r in open_risks if _is_high(r)]
        cluster = next(
            (c for c in site_clusters if c.site_id == site_id), None
        )
        entry: Dict[str, Any] = {
            "site_id": site_id,
            "total_risk_count": len(group),
            "open_risk_count": len(open_risks),
            "open_high_risk_count": len(high_open),
            "risk_instance_ids": sorted(r.risk_instance_id for r in group),
        }
        if cluster:
            entry["cluster"] = cluster.to_dict()
        site_rollup.append(entry)

    open_risks = [r for r in risks if _is_open(r)]
    open_high = [r for r in open_risks if _is_high(r)]
    closed = [r for r in risks if _is_closed(r)]
    closed_no_evidence = [r for r in closed if not r.closure_evidence_present]

    # Safety/PV and CM vs study-treatment distinct counts
    safety_pv = [r for r in risks if r.is_safety_pv]
    cm_only = [r for r in risks if r.is_concomitant_medication and not r.is_study_treatment]
    study_tx = [r for r in risks if r.is_study_treatment]

    # Distributions
    category_dist: Dict[str, int] = {}
    for risk in risks:
        cat = risk.primary_category or "(uncategorized)"
        category_dist[cat] = category_dist.get(cat, 0) + 1
    severity_dist: Dict[str, int] = {}
    for risk in risks:
        sev = risk.severity.lower()
        severity_dist[sev] = severity_dist.get(sev, 0) + 1
    status_dist: Dict[str, int] = {}
    for risk in risks:
        st = risk.status.lower()
        status_dist[st] = status_dist.get(st, 0) + 1
    disposition_dist: Dict[str, int] = {
        "open": len(open_risks),
        "closed": len(closed),
    }

    remediation_matrix = [
        {
            "risk_instance_id": r.risk_instance_id,
            "risk_key": r.risk_key,
            "subject_id": r.subject_id,
            "site_id": r.site_id,
            "severity": r.severity,
            "status": r.status,
            "closure_evidence_present": r.closure_evidence_present,
        }
        for r in sorted(risks, key=lambda x: x.risk_instance_id)
    ]

    evidence_manifest = [
        {
            "risk_instance_id": r.risk_instance_id,
            "risk_key": r.risk_key,
            "has_closure_evidence": r.closure_evidence_present,
        }
        for r in sorted(risks, key=lambda x: x.risk_instance_id)
    ]

    return {
        "risk_snapshot_id": task.frozen_identity.risk_snapshot_id,
        "subject_rollup": subject_rollup,
        "site_rollup": site_rollup,
        "trial_rollup": {
            "total_risk_count": len(risks),
            "open_risk_count": len(open_risks),
            "open_high_risk_count": len(open_high),
            "closed_risk_count": len(closed),
            "closed_risks_lacking_evidence_count": len(closed_no_evidence),
            "safety_pv_risk_count": len(safety_pv),
            "concomitant_medication_risk_count": len(cm_only),
            "study_treatment_risk_count": len(study_tx),
            "risk_instance_ids": sorted(r.risk_instance_id for r in risks),
        },
        "distributions": {
            "by_category": category_dist,
            "by_severity": severity_dist,
            "by_status": status_dist,
            "by_disposition": disposition_dist,
            "safety_pv": {"count": len(safety_pv), "is_additional_dimension": True},
            "concomitant_medication_vs_study_treatment": {
                "cm_risk_count": len(cm_only),
                "study_treatment_risk_count": len(study_tx),
                "distinct": True,
            },
        },
        "remediation_matrix": remediation_matrix,
        "evidence_manifest": evidence_manifest,
    }


def _strict_rollup_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _rollup_reference_ids(
    value: Any,
    *,
    path: str,
    blockers: List[str],
) -> List[str]:
    if not isinstance(value, (list, tuple)):
        blockers.append(f"{path}_invalid")
        return []
    ids: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            blockers.append(f"{path}_invalid_id")
            continue
        ids.append(item.strip())
    if len(ids) != len(set(ids)):
        blockers.append(f"{path}_duplicate_id")
    return ids


def validate_pre_inspection_rollup(
    task: AssuranceTask,
    rollup: Mapping[str, Any],
) -> Tuple[str, ...]:
    """Validate persisted pre-inspection references before completion.

    The validator checks only persisted IDs, explicit counts and evidence metadata; it
    never reconstructs or copies clinical risk facts. Completion must remain fail-closed
    if a rollup is missing, drifted, malformed or tampered after generation.
    """
    blockers: List[str] = []
    if not isinstance(rollup, Mapping):
        return ("rollup_invalid",)
    if rollup.get("task_id") != task.task_id:
        blockers.append("rollup_task_identity_mismatch")
    if rollup.get("project_id") != task.project_id:
        blockers.append("rollup_project_identity_mismatch")
    if rollup.get("risk_snapshot_id") != task.frozen_identity.risk_snapshot_id:
        blockers.append("rollup_snapshot_identity_mismatch")

    trial = rollup.get("trial_rollup")
    if not isinstance(trial, Mapping):
        blockers.append("trial_rollup_invalid")
        trial = {}
    trial_ids = _rollup_reference_ids(
        trial.get("risk_instance_ids"),
        path="trial_risk_instance_ids",
        blockers=blockers,
    )
    trial_count = _strict_rollup_count(trial.get("total_risk_count"))
    if trial_count is None:
        blockers.append("trial_total_risk_count_invalid")
    elif trial_count != len(trial_ids):
        blockers.append("trial_total_risk_count_mismatch")
    closed_without_evidence = _strict_rollup_count(
        trial.get("closed_risks_lacking_evidence_count")
    )
    if closed_without_evidence is None:
        blockers.append("closed_risk_evidence_count_invalid")
    elif closed_without_evidence != 0:
        blockers.append("closed_risks_lacking_evidence")

    level_ids: Dict[str, List[str]] = {}
    for level in ("subject", "site"):
        rows = rollup.get(f"{level}_rollup")
        if not isinstance(rows, (list, tuple)):
            blockers.append(f"{level}_rollup_invalid")
            level_ids[level] = []
            continue
        flattened: List[str] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                blockers.append(f"{level}_rollup_row_invalid")
                continue
            row_path = f"{level}_rollup[{index}]"
            row_ids = _rollup_reference_ids(
                row.get("risk_instance_ids"),
                path=f"{row_path}_risk_instance_ids",
                blockers=blockers,
            )
            row_count = _strict_rollup_count(row.get("total_risk_count"))
            if row_count is None:
                blockers.append(f"{row_path}_total_risk_count_invalid")
            elif row_count != len(row_ids):
                blockers.append(f"{row_path}_total_risk_count_mismatch")
            flattened.extend(row_ids)
        if len(flattened) != len(set(flattened)):
            blockers.append(f"{level}_rollup_duplicate_id")
        level_ids[level] = flattened

    trial_id_set = set(trial_ids)
    for level, ids in level_ids.items():
        if set(ids) != trial_id_set:
            blockers.append(f"{level}_trial_identity_mismatch")

    for manifest_name in ("evidence_manifest", "remediation_matrix"):
        rows = rollup.get(manifest_name)
        if not isinstance(rows, (list, tuple)):
            blockers.append(f"{manifest_name}_invalid")
            continue
        manifest_ids: List[str] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                blockers.append(f"{manifest_name}_row_invalid")
                continue
            risk_id = row.get("risk_instance_id")
            if not isinstance(risk_id, str) or not risk_id.strip():
                blockers.append(f"{manifest_name}[{index}]_risk_instance_id_invalid")
            else:
                manifest_ids.append(risk_id.strip())
            if manifest_name == "evidence_manifest" and not isinstance(
                row.get("has_closure_evidence"), bool
            ):
                blockers.append(f"{manifest_name}[{index}]_closure_evidence_invalid")
        if len(manifest_ids) != len(set(manifest_ids)):
            blockers.append(f"{manifest_name}_duplicate_id")
        if set(manifest_ids) != trial_id_set:
            blockers.append(f"{manifest_name}_identity_mismatch")

    return tuple(dict.fromkeys(blockers))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MonitoringAssuranceService:
    """Service layer for P8 pre-lock / pre-inspection assurance tasks.

    Dependencies are injectable so tests never need ``main.py`` or runtime DB.
    The service receives risk references (not risk facts) via a callable.
    """

    def __init__(
        self,
        repository: MonitoringAssuranceRepository,
        *,
        risk_reader: Optional[Callable[[str, str], List[RiskReference]]] = None,
    ) -> None:
        self.repository = repository
        self._risk_reader = risk_reader

    def set_risk_reader(self, reader: Callable[[str, str], List[RiskReference]]) -> None:
        self._risk_reader = reader

    def create_task(
        self,
        *,
        project_id: str,
        mode: str,
        frozen_identity: Mapping[str, Any],
        idempotency_key: str,
        actor: str,
        owner: str = "",
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTaskMutationResult:
        return self.repository.create_task(
            project_id=project_id,
            mode=mode,
            frozen_identity=frozen_identity,
            idempotency_key=idempotency_key,
            actor=actor,
            owner=owner,
            audit_context=audit_context,
        )

    def get_task(self, project_id: str, task_id: str) -> AssuranceTask:
        return self.repository.get(project_id, task_id)

    def list_tasks(
        self,
        project_id: str,
        *,
        mode: Optional[str] = None,
    ) -> List[AssuranceTask]:
        return self.repository.list_tasks(project_id, mode=mode)

    def evaluate_readiness(
        self,
        project_id: str,
        task_id: str,
        *,
        expected_version: int,
        current_identity: Optional[Mapping[str, Any]] = None,
        planned_subjects: int = 0,
        actual_subjects: int = 0,
        planned_sites: int = 0,
        actual_sites: int = 0,
        critical_domains_covered: int = 0,
        critical_domains_expected: int = 0,
    ) -> ReadinessResult:
        task = self.repository.get(project_id, task_id)
        if task.version != expected_version:
            raise AssuranceVersionConflictError(
                f"readiness version CAS conflict: expected {expected_version}, "
                f"current {task.version}"
            )
        return evaluate_readiness(
            task,
            current_identity=current_identity,
            planned_subjects=planned_subjects,
            actual_subjects=actual_subjects,
            planned_sites=planned_sites,
            actual_sites=actual_sites,
            critical_domains_covered=critical_domains_covered,
            critical_domains_expected=critical_domains_expected,
        )

    def record_full_recompute_proof(
        self,
        *,
        project_id: str,
        task_id: str,
        proof_payload: Mapping[str, Any],
        expected_version: int,
        actor: str,
        idempotency_key: str,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> Tuple[AssuranceTask, FullRecomputeProof, bool]:
        task = self.repository.get(project_id, task_id)

        # If risk reader is available, compute reconciliation and counts from
        # actual risk references. Otherwise, trust the caller's payload.
        if self._risk_reader is not None:
            risks = self._risk_reader(project_id, task.frozen_identity.risk_snapshot_id)
            reconciliation = reconcile_three_levels(risks)
            open_risks = [r for r in risks if _is_open(r)]
            open_high = [r for r in open_risks if _is_high(r)]
            closed = [r for r in risks if _is_closed(r)]
            closed_no_evidence = [r for r in closed if not r.closure_evidence_present]
            proof_payload = {
                **proof_payload,
                "subject_reconciliation_ok": reconciliation["subject_reconciliation_ok"],
                "site_reconciliation_ok": reconciliation["site_reconciliation_ok"],
                "trial_reconciliation_ok": reconciliation["trial_reconciliation_ok"],
                "open_high_risk_count": len(open_high),
                "open_risk_count": len(open_risks),
                "closed_risks_lacking_evidence_count": len(closed_no_evidence),
            }

        return self.repository.save_full_recompute_proof(
            project_id=project_id,
            task_id=task_id,
            proof_payload=proof_payload,
            expected_version=expected_version,
            actor=actor,
            idempotency_key=idempotency_key,
            audit_context=audit_context,
        )

    def generate_rollups(
        self,
        *,
        project_id: str,
        task_id: str,
        expected_version: int,
        actor: str,
        idempotency_key: str,
        site_method_approved: bool = False,
        min_sample_size: int = 30,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> Tuple[AssuranceTask, RollupSummary, bool]:
        task = self.repository.get(project_id, task_id)
        if self._risk_reader is None:
            raise MonitoringAssuranceError(
                "risk_reader is required to generate rollups"
            )
        risks = self._risk_reader(project_id, task.frozen_identity.risk_snapshot_id)
        clusters = compute_site_clusters(
            risks,
            site_method_approved=site_method_approved,
            min_sample_size=min_sample_size,
        )
        rollup_payload = build_rollup_payload(
            task=task,
            risks=risks,
            site_clusters=clusters,
        )
        return self.repository.save_rollup(
            project_id=project_id,
            task_id=task_id,
            rollup_payload=rollup_payload,
            expected_version=expected_version,
            actor=actor,
            idempotency_key=idempotency_key,
            audit_context=audit_context,
        )

    def get_rollup(
        self,
        project_id: str,
        task_id: str,
    ) -> Optional[RollupSummary]:
        return self.repository.get_rollup(project_id, task_id)

    def record_medical_review(
        self,
        *,
        project_id: str,
        task_id: str,
        expected_version: int,
        actor: str,
        idempotency_key: str,
        review_payload: Mapping[str, Any],
        owner: Optional[str] = None,
        lock_impact: Optional[str] = None,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTask:
        return self.repository.record_medical_review(
            project_id=project_id,
            task_id=task_id,
            expected_version=expected_version,
            actor=actor,
            idempotency_key=idempotency_key,
            review_payload=review_payload,
            owner=owner,
            lock_impact=lock_impact,
            audit_context=audit_context,
        )

    def complete_task(
        self,
        *,
        project_id: str,
        task_id: str,
        expected_version: int,
        confirmed_by: str,
        idempotency_key: str,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTask:
        task = self.repository.get(project_id, task_id)
        if task.mode == "pre_lock":
            proof = self.repository.get_full_recompute_proof(project_id, task_id)
            if proof is None:
                raise AssuranceTaskStateConflictError(
                    "pre_lock task requires a full recompute proof before completion"
                )
            if proof.failures > 0 or proof.skips > 0:
                raise AssuranceTaskStateConflictError(
                    "pre_lock task cannot complete with failures or skips in proof"
                )
            if not (
                proof.subject_reconciliation_ok
                and proof.site_reconciliation_ok
                and proof.trial_reconciliation_ok
            ):
                raise AssuranceTaskStateConflictError(
                    "pre_lock task cannot complete with failed reconciliation"
                )
            if proof.closed_risks_lacking_evidence_count > 0:
                raise AssuranceTaskStateConflictError(
                    "pre_lock task cannot complete: closed risks lacking evidence"
                )
        elif task.mode == "pre_inspection":
            rollup = self.repository.get_rollup(project_id, task_id)
            if rollup is None:
                raise AssuranceTaskStateConflictError(
                    "pre_inspection task requires generated rollups before completion"
                )
            blockers = validate_pre_inspection_rollup(task, rollup.to_dict())
            if blockers:
                raise AssuranceTaskStateConflictError(
                    "pre_inspection task cannot complete: " + ", ".join(blockers)
                )
        return self.repository.complete_task(
            project_id=project_id,
            task_id=task_id,
            expected_version=expected_version,
            confirmed_by=confirmed_by,
            idempotency_key=idempotency_key,
            audit_context=audit_context,
        )
