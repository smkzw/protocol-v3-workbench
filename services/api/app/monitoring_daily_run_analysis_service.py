from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .medical_risk_repository import MedicalRiskRepository, MedicalRiskSnapshot
from .monitoring_ai_risk_bridge import (
    MonitoringAiRiskBridge,
    MonitoringAiRiskBridgeError,
)
from .monitoring_batch_repository import MonitoringBatchRepository
from .monitoring_batch_rule_runner import BatchRuleRunResult
from .monitoring_daily_run_ai_service import (
    MonitoringDailyAiProgress,
    MonitoringDailyAiSubmission,
    MonitoringDailyRunAiService,
)
from .monitoring_daily_run_repository import (
    MonitoringDailyRun,
    MonitoringDailyRunRepository,
)
from .monitoring_rule_risk_bridge import MonitoringRuleRiskBridge


class MonitoringDailyRunAnalysisServiceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code).strip() or "monitoring_daily_analysis_error"
        self.message = str(message).strip() or self.code
        super().__init__(self.message)


@dataclass(frozen=True)
class MonitoringDailyAiSubmissionResult:
    run: MonitoringDailyRun
    submission: MonitoringDailyAiSubmission
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "ai": {
                "status": "submitted",
                "selected_subject_count": len(
                    self.submission.selected_subject_ids
                ),
                "job_count": len(self.submission.jobs),
                "job_ids": list(self.submission.job_ids),
            },
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class MonitoringDailyRiskAssemblyResult:
    run: MonitoringDailyRun
    snapshot: MedicalRiskSnapshot
    resolution_complete: bool
    blockers: tuple[dict[str, str], ...]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "risk_snapshot": {
                **asdict(self.snapshot),
                "created_at": self.snapshot.created_at.isoformat(),
            },
            "resolution_complete": self.resolution_complete,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
        }


def _canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


class MonitoringDailyRunAnalysisService:
    """Join the durable daily-run ledger to product AI and the risk ledger."""

    def __init__(
        self,
        *,
        run_repository: MonitoringDailyRunRepository,
        batch_repository: MonitoringBatchRepository,
        ai_service: MonitoringDailyRunAiService,
        risk_repository: MedicalRiskRepository,
        worker_wake: Callable[[], None] | None = None,
    ) -> None:
        self.run_repository = run_repository
        self.batch_repository = batch_repository
        self.ai_service = ai_service
        self.risk_repository = risk_repository
        self.worker_wake = worker_wake

    def submit_ai(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_version: int,
        owner: str,
    ) -> MonitoringDailyAiSubmissionResult:
        claimed = self.run_repository.claim(
            project_id,
            run_id,
            owner=owner,
            expected_version=expected_version,
        )
        lease_epoch = claimed.lease_epoch
        try:
            if claimed.status != "ai_running":
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_ai_not_submittable",
                    "当前运行不处于独立 AI 分析阶段。",
                )
            batch = self._locked_batch(claimed)
            rule_snapshot = self.run_repository.get_rule_snapshot(
                project_id,
                run_id,
            )
            if rule_snapshot is None:
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_rule_snapshot_missing",
                    "独立 AI 分析前必须先冻结规则执行结果。",
                )
            diff_snapshot = self.run_repository.get_diff_snapshot(
                project_id,
                run_id,
            )
            if claimed.baseline_batch_id is None:
                if diff_snapshot is not None:
                    raise MonitoringDailyRunAnalysisServiceError(
                        "monitoring_diff_lineage_mismatch",
                        "首批基线运行不应绑定增量差异快照。",
                    )
            else:
                if diff_snapshot is None:
                    raise MonitoringDailyRunAnalysisServiceError(
                        "monitoring_diff_snapshot_missing",
                        "增量运行缺少已冻结的差异快照，不能提交独立 AI。",
                    )
                if (
                    diff_snapshot.previous_batch_id
                    != claimed.baseline_batch_id
                    or diff_snapshot.algorithm_version
                    != claimed.diff_algorithm_version
                ):
                    raise MonitoringDailyRunAnalysisServiceError(
                        "monitoring_diff_lineage_mismatch",
                        "增量差异快照未绑定当前运行的上一医学确认基线或算法版本。",
                    )
                diff_payload = diff_snapshot.payload
                row_diff = (
                    diff_payload.get("row_diff")
                    if isinstance(diff_payload, Mapping)
                    else None
                )
                if (
                    not isinstance(diff_payload, Mapping)
                    or not isinstance(row_diff, Mapping)
                    or diff_payload.get("full_snapshot_proven") is not True
                    or diff_payload.get("schema_diffs")
                    or diff_payload.get("removal_blocked_keys")
                    or row_diff.get("missing_current_domains")
                    or row_diff.get("removal_resolution_blocked_keys")
                ):
                    raise MonitoringDailyRunAnalysisServiceError(
                        "monitoring_diff_not_ready",
                        "增量差异快照仍含结构、域或删除解析阻断，不能提交独立 AI。",
                    )
            step_input = _canonical_sha256(
                {
                    "run_input_sha256": claimed.input_sha256,
                    "rule_snapshot_id": rule_snapshot.snapshot_id,
                    "rule_output_sha256": rule_snapshot.output_sha256,
                    "diff_snapshot_id": (
                        diff_snapshot.snapshot_id if diff_snapshot else None
                    ),
                    "diff_output_sha256": (
                        diff_snapshot.output_sha256 if diff_snapshot else None
                    ),
                }
            )
            self.run_repository.start_step(
                project_id,
                run_id,
                step_name="independent_ai_submission",
                input_sha256=step_input,
                expected_run_version=claimed.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details={"rule_snapshot_id": rule_snapshot.snapshot_id},
            )
            submission = self.ai_service.submit(
                project_id=project_id,
                batch=batch,
                rule_snapshot=rule_snapshot,
                diff_snapshot=diff_snapshot,
            )
            output_sha256 = _canonical_sha256(
                {
                    "selected_subject_ids": list(
                        submission.selected_subject_ids
                    ),
                    "jobs": [
                        {
                            "job_id": job.job_id,
                            "input_revision_sha256": job.input_revision_sha256,
                        }
                        for job in submission.jobs
                    ],
                }
            )
            self.run_repository.finish_step(
                project_id,
                run_id,
                step_name="independent_ai_submission",
                status="completed",
                input_sha256=step_input,
                output_sha256=output_sha256,
                expected_run_version=claimed.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details={
                    "selected_subject_count": len(
                        submission.selected_subject_ids
                    ),
                    "job_count": len(submission.jobs),
                },
            )
            if submission.jobs and self.worker_wake is not None:
                self.worker_wake()
            released = self.run_repository.release_lease(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            return MonitoringDailyAiSubmissionResult(
                run=released,
                submission=submission,
                next_action=(
                    "wait_for_independent_ai"
                    if submission.jobs
                    else "assemble_risk_snapshot"
                ),
            )
        except Exception:
            self._release_quietly(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            raise

    def ai_progress(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> MonitoringDailyAiProgress:
        run = self.run_repository.get(project_id, run_id)
        if run.status not in {
            "ai_running",
            "analysis_partial",
            "risk_review",
            "ready_to_confirm",
            "confirmed",
        }:
            raise MonitoringDailyRunAnalysisServiceError(
                "monitoring_ai_progress_unavailable",
                "当前运行尚未进入独立 AI 分析阶段。",
            )
        return self.ai_service.progress(
            project_id=project_id,
            run_id=run_id,
        )

    def assemble_risks(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_version: int,
        owner: str,
    ) -> MonitoringDailyRiskAssemblyResult:
        claimed = self.run_repository.claim(
            project_id,
            run_id,
            owner=owner,
            expected_version=expected_version,
        )
        lease_epoch = claimed.lease_epoch
        try:
            if claimed.status != "ai_running":
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_risk_assembly_not_ready",
                    "当前运行不处于风险汇总阶段。",
                )
            batch = self._locked_batch(claimed)
            rule_snapshot = self.run_repository.get_rule_snapshot(
                project_id,
                run_id,
            )
            if rule_snapshot is None:
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_rule_snapshot_missing",
                    "风险汇总前必须存在冻结的规则结果。",
                )
            submission_step = next(
                (
                    step
                    for step in self.run_repository.list_steps(run_id)
                    if step.step_name == "independent_ai_submission"
                    and step.status == "completed"
                ),
                None,
            )
            if submission_step is None:
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_ai_not_submitted",
                    "请先提交独立 AI 分析任务。",
                )
            progress = self.ai_service.progress(
                project_id=project_id,
                run_id=run_id,
            )
            if progress.status == "running":
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_ai_still_running",
                    "独立 AI 仍在分析，请稍后刷新。",
                )
            if progress.status == "not_submitted" and int(
                submission_step.details.get("job_count") or 0
            ):
                raise MonitoringDailyRunAnalysisServiceError(
                    "monitoring_ai_jobs_missing",
                    "独立 AI 提交记录与任务账本不一致。",
                )

            result = BatchRuleRunResult.from_dict(rule_snapshot.payload)
            blockers: list[dict[str, str]] = [
                {
                    "code": "deterministic_rule_diagnostic",
                    "message": diagnostic.message,
                }
                for diagnostic in result.diagnostics
            ]
            # A replay after a crash must regenerate byte-identical risk payloads.
            created_at = rule_snapshot.created_at
            terminal_payload = {
                "run_input_sha256": claimed.input_sha256,
                "rule_output_sha256": rule_snapshot.output_sha256,
                "ai_status": progress.status,
                "failures": list(progress.failures),
                "candidates": [
                    {
                        "job_id": item.job_id,
                        "candidate": item.candidate.model_dump(mode="json"),
                    }
                    for item in progress.candidates
                ],
            }
            source_revision = (
                f"monitoring-run:{_canonical_sha256(terminal_payload)}"
            )
            risks = list(
                MonitoringRuleRiskBridge.convert(
                    result,
                    engine_version=claimed.engine_version,
                    source_revision=source_revision,
                    created_at=created_at,
                )
            )
            for item in progress.candidates:
                try:
                    risks.extend(
                        MonitoringAiRiskBridge.convert(
                            item.candidate,
                            batch_id=claimed.batch_id,
                            source_revision=source_revision,
                            rule_pack_revision=claimed.rule_pack_revision,
                            engine_version=claimed.engine_version,
                            created_at=created_at,
                        )
                    )
                except MonitoringAiRiskBridgeError as exc:
                    blockers.append(
                        {
                            "code": "ai_candidate_rejected_by_boundary",
                            "message": (
                                f"{item.subject_id}: {str(exc)}"
                            ),
                        }
                    )
            risks = self._merge_same_risk_key(risks)
            blockers.extend(
                {
                    "code": str(item.get("failure_code") or "ai_job_failed"),
                    "message": (
                        f"{item.get('subject_id') or '受试者'}: "
                        f"{item.get('failure_message') or item.get('status')}"
                    ),
                }
                for item in progress.failures
            )
            resolution_complete = not blockers and progress.status in {
                "completed",
                "not_submitted",
            }
            prior_risk_keys: tuple[str, ...] = ()
            if resolution_complete:
                try:
                    previous = self.risk_repository.current_snapshot(project_id)
                    previous_snapshot_id = previous.snapshot_id
                    if (
                        previous.source_batch_id == claimed.batch_id
                        and previous.source_revision == source_revision
                    ):
                        previous_snapshot_id = previous.previous_snapshot_id
                    prior_risk_keys = tuple(
                        risk.risk_key
                        for risk in self.risk_repository.list_risks(
                            project_id,
                            previous_snapshot_id,
                        )
                    ) if previous_snapshot_id else ()
                except KeyError:
                    prior_risk_keys = ()
            assembly_input = _canonical_sha256(
                {
                    **terminal_payload,
                    "source_revision": source_revision,
                    "resolution_complete": resolution_complete,
                }
            )
            self.run_repository.start_step(
                project_id,
                run_id,
                step_name="risk_snapshot_assembly",
                input_sha256=assembly_input,
                expected_run_version=claimed.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details={
                    "rule_risk_count": len(result.candidates),
                    "ai_candidate_count": len(progress.candidates),
                    "blocker_count": len(blockers),
                },
            )
            snapshot = self.risk_repository.save_snapshot(
                project_id=project_id,
                source_batch_id=claimed.batch_id,
                source_revision=source_revision,
                rule_profile_revision=claimed.rule_pack_revision,
                engine_version=claimed.engine_version,
                evaluated_subject_count=len(
                    {
                        self._subject_id(self._row_data(row))
                        for row in batch.rows
                        if self._subject_id(self._row_data(row))
                    }
                ),
                risks=risks,
                resolution_complete=resolution_complete,
                resolution_eligible_risk_keys=prior_risk_keys,
            )
            bound = self.run_repository.bind_risk_snapshot(
                project_id,
                run_id,
                risk_snapshot_id=snapshot.snapshot_id,
                expected_version=claimed.version,
                actor=owner,
                lease_owner=owner,
                lease_epoch=lease_epoch,
            ).run
            assembly_output = _canonical_sha256(
                {
                    "risk_snapshot_id": snapshot.snapshot_id,
                    "risk_count": snapshot.risk_count,
                    "resolution_complete": resolution_complete,
                    "blockers": blockers,
                }
            )
            self.run_repository.finish_step(
                project_id,
                run_id,
                step_name="risk_snapshot_assembly",
                status="completed",
                input_sha256=assembly_input,
                output_sha256=assembly_output,
                expected_run_version=bound.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details={
                    "risk_snapshot_id": snapshot.snapshot_id,
                    "risk_count": snapshot.risk_count,
                    "resolution_complete": resolution_complete,
                    "blocker_count": len(blockers),
                },
            )
            target_status = (
                "risk_review" if resolution_complete else "analysis_partial"
            )
            transitioned = self.run_repository.transition(
                project_id,
                run_id,
                target_status=target_status,
                expected_version=bound.version,
                actor=owner,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                payload={
                    "risk_snapshot_id": snapshot.snapshot_id,
                    "resolution_complete": resolution_complete,
                    "blocker_count": len(blockers),
                },
            )
            released = self.run_repository.release_lease(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            return MonitoringDailyRiskAssemblyResult(
                run=released,
                snapshot=snapshot,
                resolution_complete=resolution_complete,
                blockers=tuple(blockers),
                next_action=(
                    "review_risks"
                    if resolution_complete
                    else "review_incomplete_analysis"
                ),
            )
        except Exception:
            self._release_quietly(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            raise

    def acknowledge_partial(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_version: int,
        actor: str,
    ) -> MonitoringDailyRun:
        run = self.run_repository.get(project_id, run_id)
        if run.status != "analysis_partial" or not run.risk_snapshot_id:
            raise MonitoringDailyRunAnalysisServiceError(
                "monitoring_partial_review_unavailable",
                "当前运行没有需要确认的不完整分析结果。",
            )
        return self.run_repository.transition(
            project_id,
            run_id,
            target_status="risk_review",
            expected_version=expected_version,
            actor=actor,
            payload={"partial_analysis_acknowledged": True},
        )

    def _locked_batch(self, run: MonitoringDailyRun):
        try:
            batch = self.batch_repository.load_diff_ready_batch(run.batch_id)
        except Exception as exc:
            raise MonitoringDailyRunAnalysisServiceError(
                "monitoring_batch_unavailable",
                "运行绑定的冻结批次当前不可用。",
            ) from exc
        if (
            batch.project_id != run.project_id
            or batch.version != run.batch_version
            or batch.mapping_revision != run.mapping_revision
        ):
            raise MonitoringDailyRunAnalysisServiceError(
                "monitoring_run_input_changed",
                "运行绑定的批次或字段映射已变化，请新建运行。",
            )
        return batch

    @staticmethod
    def _subject_id(raw_record: dict[str, Any]) -> str:
        for key in (
            "USUBJID",
            "SUBJID",
            "SUBJECT_ID",
            "SUBJECTID",
            "受试者编号",
        ):
            value = str(raw_record.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _row_data(row: Any) -> dict[str, Any]:
        value = getattr(row, "data", None)
        if isinstance(value, dict):
            return value
        value = getattr(row, "raw_record", None)
        if isinstance(value, dict):
            return value
        return {}

    @staticmethod
    def _merge_same_risk_key(risks: list[Any]) -> list[Any]:
        """Collapse repeated model candidates grounded in the same evidence."""
        merged: dict[str, Any] = {}
        for risk in risks:
            existing = merged.get(risk.risk_key)
            if existing is None:
                merged[risk.risk_key] = risk
                continue
            span_ids = list(
                dict.fromkeys(
                    [*existing.evidence_span_ids, *risk.evidence_span_ids]
                )
            )
            snapshots = [
                *existing.evidence_snapshots,
                *risk.evidence_snapshots,
            ]
            identity = _canonical_sha256(
                {
                    "risk_key": risk.risk_key,
                    "risk_instances": sorted(
                        {
                            existing.risk_instance_id,
                            risk.risk_instance_id,
                        }
                    ),
                }
            )
            merged[risk.risk_key] = existing.model_copy(
                update={
                    "risk_id": f"risk_{identity[:24]}",
                    "risk_instance_id": f"riskinst_{identity[:24]}",
                    "evidence_span_ids": span_ids,
                    "evidence_snapshots": snapshots,
                    "confidence": max(existing.confidence, risk.confidence),
                }
            )
        return list(merged.values())

    def _release_quietly(
        self,
        project_id: str,
        run_id: str,
        *,
        owner: str,
        lease_epoch: int,
    ) -> None:
        try:
            self.run_repository.release_lease(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
        except Exception:
            pass
