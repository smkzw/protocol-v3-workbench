from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Optional

from .monitoring_batch_rule_runner import MonitoringBatchRuleRunner
from .monitoring_batch_diff import MONITORING_BATCH_DIFF_ALGORITHM_VERSION
from .monitoring_batch_repository import MonitoringBatchRepository
from .monitoring_batch_service import MonitoringBatchService
from .monitoring_daily_run_repository import (
    DailyRunInput,
    MonitoringDailyRun,
    MonitoringDailyRunRepository,
    MonitoringDiffSnapshot,
    MonitoringRuleSnapshot,
)
from .monitoring_record_rule_resolver import (
    MonitoringRecordRuleResolver,
    RecordRuleAggregateIdentityError,
)


class MonitoringDailyRunServiceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code).strip() or "monitoring_daily_run_error"
        self.message = str(message).strip() or self.code
        super().__init__(self.message)


def _strict_analysis_complete(payload: Mapping[str, Any]) -> bool:
    value = payload.get("analysis_complete", True)
    if not isinstance(value, bool):
        raise MonitoringDailyRunServiceError(
            "monitoring_rule_snapshot_invalid",
            "规则快照 analysis_complete 必须是严格 Boolean 值。",
        )
    return value


@dataclass(frozen=True)
class MonitoringRuleRuntimeIdentity:
    rule_pack_revision: str
    engine_version: str
    resolution_mode: str = "project_effective"
    rule_mapping_revision: str = ""
    rule_mapping_content_sha256: str = ""
    rule_capability_manifest_sha256: str = ""
    rule_effective_capabilities_sha256: str = ""
    rule_identity_sha256: str = ""


@dataclass(frozen=True)
class MonitoringDailyRunProcessResult:
    run: MonitoringDailyRun
    diff_snapshot: Optional[MonitoringDiffSnapshot]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "diff_snapshot": (
                asdict(self.diff_snapshot) if self.diff_snapshot is not None else None
            ),
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class MonitoringDailyRuleProcessResult:
    run: MonitoringDailyRun
    rule_snapshot: MonitoringRuleSnapshot
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.rule_snapshot.payload)
        return {
            "run": self.run.to_dict(),
            "rule_result": {
                "snapshot_id": self.rule_snapshot.snapshot_id,
                "output_sha256": self.rule_snapshot.output_sha256,
                "candidate_count": len(payload.get("candidates") or ()),
                "diagnostic_count": len(payload.get("diagnostics") or ()),
                "evaluated_record_count": int(
                    payload.get("evaluated_record_count") or 0
                ),
                "resolution_mode": str(
                    payload.get("resolution_mode") or "project_effective"
                ),
                "analysis_complete": _strict_analysis_complete(payload),
                "failed_resolution_count": int(
                    payload.get("failed_resolution_count") or 0
                ),
                "resolution_diagnostics": [
                    {
                        "code": str(item.get("code") or ""),
                        "message": str(item.get("message") or ""),
                        "current_business_key": str(
                            item.get("current_business_key") or ""
                        ),
                        "current_domain": str(
                            item.get("current_domain") or ""
                        ),
                    }
                    for item in (
                        payload.get("record_resolution_diagnostics") or ()
                    )
                    if isinstance(item, Mapping)
                ],
            },
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


_EXACT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_exact_sha256(value: Any) -> bool:
    """Return whether a supplied identity digest is already canonical.

    Runtime identity bytes are contract material, not user-facing text.  Do
    not coerce, trim or case-fold them here: a malformed persisted or
    resolver-supplied value must fail closed at the orchestration boundary.
    """

    return isinstance(value, str) and _EXACT_SHA256_RE.fullmatch(value) is not None


def _require_identity_sha256(
    value: Any,
    field: str,
    *,
    code: str,
) -> str:
    if not _is_exact_sha256(value):
        raise MonitoringDailyRunServiceError(
            code,
            f"{field} 必须是规范的小写 64 位 SHA-256 摘要。",
        )
    return value


def _require_optional_identity_sha256(
    value: Any,
    field: str,
    *,
    code: str,
) -> str:
    if value is None or value == "":
        return ""
    return _require_identity_sha256(value, field, code=code)


class MonitoringDailyRunService:
    """P7 orchestration boundary over immutable batches and the durable run ledger."""

    def __init__(
        self,
        *,
        run_repository: MonitoringDailyRunRepository,
        batch_repository: MonitoringBatchRepository,
        batch_service: MonitoringBatchService,
        rule_runtime_resolver: Callable[[str], MonitoringRuleRuntimeIdentity],
        active_mapping_resolver: Optional[Callable[[str], Any]] = None,
        ai_runtime_resolver: Optional[Callable[[], Any]] = None,
        rule_runner: Optional[MonitoringBatchRuleRunner] = None,
        record_rule_resolver: Optional[MonitoringRecordRuleResolver] = None,
    ) -> None:
        self.run_repository = run_repository
        self.batch_repository = batch_repository
        self.batch_service = batch_service
        self.rule_runtime_resolver = rule_runtime_resolver
        self.active_mapping_resolver = active_mapping_resolver
        self.ai_runtime_resolver = ai_runtime_resolver
        self.rule_runner = rule_runner
        self.record_rule_resolver = record_rule_resolver
        if self.record_rule_resolver is None and self.rule_runner is not None:
            repository = getattr(
                getattr(self.rule_runner, "rule_service", None),
                "repository",
                None,
            )
            if repository is not None:
                self.record_rule_resolver = MonitoringRecordRuleResolver(repository)

    def prepare(
        self,
        *,
        project_id: str,
        batch_id: str,
        idempotency_key: str,
        actor: str,
    ):
        batch = self._frozen_project_batch(project_id, batch_id)
        identity = self._validate_start_contract(project_id, batch)
        baseline = self.run_repository.current_baseline(project_id)
        baseline_batch_id = (
            baseline.current_baseline_batch_id if baseline is not None else None
        )
        if baseline_batch_id == batch.batch_id:
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_already_confirmed",
                "当前批次已经是项目医学确认基线，请导入新的全量 listing。",
            )
        if baseline_batch_id is not None:
            self._frozen_project_batch(project_id, baseline_batch_id)

        return self.run_repository.create_or_get(
            DailyRunInput(
                project_id=project_id,
                batch_id=batch.batch_id,
                baseline_batch_id=baseline_batch_id,
                batch_version=batch.version,
                mapping_revision=batch.active_mapping_revision,
                rule_pack_revision=(
                    identity.rule_pack_revision
                    if identity.resolution_mode == "project_effective"
                    else ""
                ),
                rule_resolution_mode=identity.resolution_mode,
                rule_identity_sha256=identity.rule_identity_sha256,
                engine_version=identity.engine_version,
                diff_algorithm_version=MONITORING_BATCH_DIFF_ALGORITHM_VERSION,
            ),
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def start_readiness(self, *, project_id: str, batch_id: str) -> dict[str, Any]:
        """Read-only projection of the formal daily-run start contract."""
        try:
            batch = self._frozen_project_batch(project_id, batch_id)
            identity = self._validate_start_contract(project_id, batch)
            baseline = self.run_repository.current_baseline(project_id)
            if (
                baseline is not None
                and baseline.current_baseline_batch_id == batch.batch_id
            ):
                raise MonitoringDailyRunServiceError(
                    "monitoring_batch_already_confirmed",
                    "当前批次已经是项目医学确认基线，请导入新的全量 listing。",
                )
            mapping_contract = (
                self.batch_repository.load_frozen_mapping_contract(batch.batch_id)
            )
            return {
                "project_id": project_id,
                "batch_id": batch.batch_id,
                "ready": True,
                "state_code": "ready",
                "message": "当前批次已具备正式日常医学监查启动条件。",
                "next_action": "start_daily_run",
                "mapping_revision": batch.active_mapping_revision,
                "capability_manifest_sha256": (
                    mapping_contract.capability_manifest_sha256
                ),
                "rule_pack_revision": identity.rule_pack_revision,
                "rule_resolution_mode": identity.resolution_mode,
            }
        except MonitoringDailyRunServiceError as exc:
            return {
                "project_id": project_id,
                "batch_id": batch_id,
                "ready": False,
                "state_code": exc.code,
                "message": exc.message,
                "next_action": self._readiness_next_action(exc.code),
            }

    def process_prepared(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_version: int,
        owner: str,
    ) -> MonitoringDailyRunProcessResult:
        claimed = self.run_repository.claim(
            project_id,
            run_id,
            owner=owner,
            expected_version=expected_version,
        )
        lease_epoch = claimed.lease_epoch
        current = claimed
        snapshot: Optional[MonitoringDiffSnapshot] = None
        try:
            self._validate_locked_input(current)
            if current.status == "rules_running":
                released = self.run_repository.release_lease(
                    project_id,
                    run_id,
                    owner=owner,
                    lease_epoch=lease_epoch,
                )
                return MonitoringDailyRunProcessResult(
                    run=released,
                    diff_snapshot=self.run_repository.get_diff_snapshot(
                        project_id,
                        run_id,
                    ),
                    next_action="run_rules",
                )
            if current.status not in {"prepared", "diffing"}:
                raise MonitoringDailyRunServiceError(
                    "monitoring_run_not_processable",
                    "当前运行不处于批次准备或差异分析阶段。",
                )
            if current.baseline_batch_id is None:
                if current.status != "prepared":
                    raise MonitoringDailyRunServiceError(
                        "monitoring_initial_baseline_state_invalid",
                        "首批基线不应进入差异分析状态。",
                    )
                step_input = _canonical_sha256(
                    {
                        "run_input_sha256": current.input_sha256,
                        "mode": "initial_baseline",
                    }
                )
                self.run_repository.start_step(
                    project_id,
                    run_id,
                    step_name="initial_baseline",
                    input_sha256=step_input,
                    expected_run_version=current.version,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    details={"batch_id": current.batch_id},
                )
                step_output = _canonical_sha256(
                    {
                        "batch_id": current.batch_id,
                        "status": "diff_not_applicable",
                    }
                )
                self.run_repository.finish_step(
                    project_id,
                    run_id,
                    step_name="initial_baseline",
                    status="completed",
                    input_sha256=step_input,
                    output_sha256=step_output,
                    expected_run_version=current.version,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    details={"reason": "项目尚无上一医学确认基线"},
                )
                current = self.run_repository.transition(
                    project_id,
                    run_id,
                    target_status="rules_running",
                    expected_version=current.version,
                    actor=owner,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    payload={"mode": "initial_baseline"},
                )
                next_action = "run_rules"
            else:
                if current.status == "prepared":
                    current = self.run_repository.transition(
                        project_id,
                        run_id,
                        target_status="diffing",
                        expected_version=current.version,
                        actor=owner,
                        lease_owner=owner,
                        lease_epoch=lease_epoch,
                    )
                previous = self.batch_repository.load_diff_ready_batch(
                    current.baseline_batch_id
                )
                latest = self.batch_repository.load_diff_ready_batch(
                    current.batch_id
                )
                diff_input_sha256 = _canonical_sha256(
                    {
                        "run_input_sha256": current.input_sha256,
                        "previous": self._diff_batch_identity(previous),
                        "current": self._diff_batch_identity(latest),
                    }
                )
                self.run_repository.start_step(
                    project_id,
                    run_id,
                    step_name="batch_diff",
                    input_sha256=diff_input_sha256,
                    expected_run_version=current.version,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    details={
                        "previous_batch_id": current.baseline_batch_id,
                        "current_batch_id": current.batch_id,
                    },
                )
                snapshot = self.run_repository.get_diff_snapshot(
                    project_id,
                    run_id,
                )
                if snapshot is None:
                    diff_payload = self.batch_service.detailed_diff(
                        current.baseline_batch_id,
                        current.batch_id,
                    )
                    saved = self.run_repository.save_diff_snapshot(
                        project_id,
                        run_id,
                        input_sha256=diff_input_sha256,
                        payload=diff_payload,
                        expected_version=current.version,
                        actor=owner,
                        lease_owner=owner,
                        lease_epoch=lease_epoch,
                    )
                    current = saved.run
                    snapshot = saved.snapshot
                else:
                    if snapshot.input_sha256 != diff_input_sha256:
                        raise MonitoringDailyRunServiceError(
                            "monitoring_diff_input_changed",
                            "已冻结差异结果与当前批次输入不一致，请新建运行。",
                        )
                    diff_payload = dict(snapshot.payload)
                self.run_repository.finish_step(
                    project_id,
                    run_id,
                    step_name="batch_diff",
                    status="completed",
                    input_sha256=diff_input_sha256,
                    output_sha256=snapshot.output_sha256,
                    expected_run_version=current.version,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    details={
                        "diff_snapshot_id": snapshot.snapshot_id,
                        "algorithm_output_sha256": diff_payload["output_sha256"],
                    },
                )
                drift_reasons: list[str] = []
                if diff_payload["schema_diffs"]:
                    drift_reasons.append("schema_drift")
                if diff_payload["row_diff"]["missing_current_domains"]:
                    drift_reasons.append("missing_expected_domain")
                # A full listing can only resolve a removed row when its
                # identity is unambiguous.  The diff engine deliberately
                # keeps ambiguous aliases and removals without snapshot proof
                # in removal_blocked_keys; never let those rows reach rules.
                if diff_payload["removal_blocked_keys"]:
                    drift_reasons.append("removal_resolution_blocked")
                if diff_payload["full_snapshot_proven"] is not True:
                    drift_reasons.append("full_snapshot_unproven")
                schema_drift = bool(
                    diff_payload["schema_diffs"]
                    or diff_payload["row_diff"]["missing_current_domains"]
                )
                requires_drift_review = bool(drift_reasons)
                target = (
                    "drift_review_required"
                    if requires_drift_review
                    else "rules_running"
                )
                current = self.run_repository.transition(
                    project_id,
                    run_id,
                    target_status=target,
                    expected_version=current.version,
                    actor=owner,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                    payload={
                        "diff_snapshot_id": snapshot.snapshot_id,
                        "schema_drift": schema_drift,
                        "drift_review_required": requires_drift_review,
                        "drift_reasons": drift_reasons,
                    },
                )
                next_action = (
                    "review_mapping_drift"
                    if requires_drift_review
                    else "run_rules"
                )
            released = self.run_repository.release_lease(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            return MonitoringDailyRunProcessResult(
                run=released,
                diff_snapshot=snapshot,
                next_action=next_action,
            )
        except Exception:
            try:
                self.run_repository.release_lease(
                    project_id,
                    run_id,
                    owner=owner,
                    lease_epoch=lease_epoch,
                )
            except Exception:
                pass
            raise

    def execute_rules(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_version: int,
        owner: str,
    ) -> MonitoringDailyRuleProcessResult:
        if self.rule_runner is None:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_runner_unavailable",
                "医学监查规则执行器当前不可用。",
            )
        claimed = self.run_repository.claim(
            project_id,
            run_id,
            owner=owner,
            expected_version=expected_version,
        )
        lease_epoch = claimed.lease_epoch
        current = claimed
        try:
            self._validate_locked_input(current)
            if current.status != "rules_running":
                raise MonitoringDailyRunServiceError(
                    "monitoring_rules_not_processable",
                    "当前运行不处于规则执行阶段。",
                )
            batch = self.batch_repository.load_diff_ready_batch(current.batch_id)
            mapping_contract = (
                self.batch_repository.load_frozen_mapping_contract(
                    current.batch_id
                )
            )
            capability_states = mapping_contract.capability_states
            if not capability_states:
                raise MonitoringDailyRunServiceError(
                    "monitoring_capability_contract_required",
                    "当前冻结批次缺少能力快照，不能运行医学监查规则；"
                    "请基于当前字段映射质量门重新冻结批次。",
                )
            existing = self.run_repository.get_rule_snapshot(project_id, run_id)
            resolution_plan = None
            if (
                current.rule_resolution_mode == "record_applicability"
                and existing is None
            ):
                if self.record_rule_resolver is None:
                    raise MonitoringDailyRunServiceError(
                        "monitoring_record_rule_resolver_unavailable",
                        "逐记录方案与规则包解析器当前不可用。",
                    )
                self._assert_record_rule_identity_frozen(current)
                resolution_plan = self.record_rule_resolver.resolve_batch(
                    batch,
                    mapping_contract,
                )
            if (
                current.rule_resolution_mode == "project_effective"
                and existing is None
            ):
                # Revalidate the project-effective frozen rule identity
                # immediately before first rule execution. Intentional
                # stored-snapshot replay (existing is not None) is not
                # invalidated by this check.
                self._assert_project_rule_identity_frozen(
                    current,
                    mapping_contract,
                )
            if (
                current.rule_resolution_mode == "record_applicability"
                and existing is not None
            ):
                rule_input_sha256 = existing.input_sha256
            else:
                rule_input_sha256 = _canonical_sha256(
                    {
                        "run_input_sha256": current.input_sha256,
                        "batch": self._diff_batch_identity(batch),
                        "rule_resolution_mode": current.rule_resolution_mode,
                        "rule_pack_id": current.rule_pack_revision,
                        "capability_manifest_sha256": (
                            mapping_contract.capability_manifest_sha256
                        ),
                        "effective_capabilities_sha256": (
                            mapping_contract.effective_capabilities_sha256
                        ),
                        "record_resolution_sha256": (
                            resolution_plan.resolution_sha256
                            if resolution_plan is not None
                            else ""
                        ),
                        "engine_version": current.engine_version,
                    }
                )
            self.run_repository.start_step(
                project_id,
                run_id,
                step_name="deterministic_rules",
                input_sha256=rule_input_sha256,
                expected_run_version=current.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details={
                    "batch_id": current.batch_id,
                    "rule_pack_id": current.rule_pack_revision,
                    "rule_resolution_mode": current.rule_resolution_mode,
                    "capability_manifest_sha256": (
                        mapping_contract.capability_manifest_sha256
                    ),
                    "effective_capabilities_sha256": (
                        mapping_contract.effective_capabilities_sha256
                    ),
                    "record_resolution_sha256": (
                        resolution_plan.resolution_sha256
                        if resolution_plan is not None
                        else ""
                    ),
                },
            )
            if existing is None:
                if resolution_plan is not None:
                    result_payload = self.record_rule_resolver.run_resolved(
                        batch,
                        resolution_plan,
                        self.rule_runner,
                        capability_states=capability_states,
                    )
                else:
                    result_payload = self.rule_runner.run(
                        batch,
                        rule_pack_id=current.rule_pack_revision,
                        capability_states=capability_states,
                    ).to_dict()
                    result_payload["resolution_mode"] = "project_effective"
                    capability_diagnostics = [
                        item
                        for item in result_payload.get("diagnostics") or ()
                        if str(item.get("code") or "").startswith(
                            "monitoring_capability_"
                        )
                    ]
                    result_payload["analysis_complete"] = not (
                        capability_diagnostics
                    )
                    result_payload["failed_resolution_count"] = len(
                        capability_diagnostics
                    )
                saved = self.run_repository.save_rule_snapshot(
                    project_id,
                    run_id,
                    input_sha256=rule_input_sha256,
                    payload=result_payload,
                    expected_version=current.version,
                    actor=owner,
                    lease_owner=owner,
                    lease_epoch=lease_epoch,
                )
                current = saved.run
                snapshot = saved.snapshot
            else:
                if existing.input_sha256 != rule_input_sha256:
                    raise MonitoringDailyRunServiceError(
                        "monitoring_rule_input_changed",
                        "已冻结规则结果与当前批次输入不一致，请新建运行。",
                    )
                snapshot = existing
            details = {
                "rule_snapshot_id": snapshot.snapshot_id,
                "candidate_count": len(snapshot.payload.get("candidates") or ()),
                "diagnostic_count": len(snapshot.payload.get("diagnostics") or ()),
                "evaluated_record_count": int(
                    snapshot.payload.get("evaluated_record_count") or 0
                ),
                "failed_resolution_count": int(
                    snapshot.payload.get("failed_resolution_count") or 0
                ),
            }
            self.run_repository.finish_step(
                project_id,
                run_id,
                step_name="deterministic_rules",
                status="completed",
                input_sha256=rule_input_sha256,
                output_sha256=snapshot.output_sha256,
                expected_run_version=current.version,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                details=details,
            )
            analysis_complete = _strict_analysis_complete(snapshot.payload)
            target_status = "ai_running" if analysis_complete else "analysis_partial"
            current = self.run_repository.transition(
                project_id,
                run_id,
                target_status=target_status,
                expected_version=current.version,
                actor=owner,
                lease_owner=owner,
                lease_epoch=lease_epoch,
                payload=details,
            )
            released = self.run_repository.release_lease(
                project_id,
                run_id,
                owner=owner,
                lease_epoch=lease_epoch,
            )
            return MonitoringDailyRuleProcessResult(
                run=released,
                rule_snapshot=snapshot,
                next_action=(
                    "run_independent_ai"
                    if analysis_complete
                    else "review_rule_resolution"
                ),
            )
        except Exception:
            try:
                self.run_repository.release_lease(
                    project_id,
                    run_id,
                    owner=owner,
                    lease_epoch=lease_epoch,
                )
            except Exception:
                pass
            raise

    def _assert_record_rule_identity_frozen(
        self,
        run: MonitoringDailyRun,
    ) -> None:
        frozen_identity = run.rule_identity_sha256
        if not isinstance(frozen_identity, str) or not frozen_identity:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_identity_unverifiable",
                "当前运行缺少已冻结的逐记录规则身份，请新建运行。",
            )
        _require_identity_sha256(
            frozen_identity,
            "run.rule_identity_sha256",
            code="monitoring_rule_identity_unverifiable",
        )
        try:
            aggregate = self.record_rule_resolver.aggregate_identity(
                run.project_id
            )
        except Exception as exc:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_identity_changed",
                "逐记录方案适用性或规则包身份在运行准备后失效，"
                "规则执行已关闭，请新建运行。",
            ) from exc
        for field in (
            "identity_sha256",
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            _require_identity_sha256(
                getattr(aggregate, field, None),
                f"record_rule_identity.{field}",
                code="monitoring_rule_identity_unverifiable",
            )
        if aggregate.identity_sha256 != frozen_identity:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_identity_changed",
                "方案适用性指派、规则包或其映射身份在运行准备后发生变化，"
                "规则执行已关闭，请新建运行。",
            )

    def _assert_project_rule_identity_frozen(
        self,
        run: MonitoringDailyRun,
        mapping_contract: Any,
    ) -> None:
        # Re-resolve the current published pack identity; any resolver
        # failure already fails closed inside _resolve_rule_identity.
        identity = self._resolve_rule_identity(run.project_id)
        for field in (
            "rule_mapping_content_sha256",
            "rule_capability_manifest_sha256",
            "rule_effective_capabilities_sha256",
        ):
            _require_identity_sha256(
                getattr(identity, field, None),
                f"rule_identity.{field}",
                code="monitoring_rule_identity_changed",
            )
        for field in (
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            _require_identity_sha256(
                getattr(mapping_contract, field, None),
                f"mapping_contract.{field}",
                code="monitoring_rule_identity_changed",
            )
        if (
            identity.resolution_mode != "project_effective"
            or identity.rule_pack_revision.strip()
            != str(run.rule_pack_revision or "").strip()
            or not identity.rule_mapping_revision.strip()
            or identity.rule_mapping_revision.strip()
            != str(mapping_contract.mapping_revision or "").strip()
            or not identity.rule_mapping_content_sha256
            or identity.rule_mapping_content_sha256
            != mapping_contract.mapping_content_sha256
            or not identity.rule_capability_manifest_sha256
            or identity.rule_capability_manifest_sha256
            != mapping_contract.capability_manifest_sha256
            or not identity.rule_effective_capabilities_sha256
            or identity.rule_effective_capabilities_sha256
            != mapping_contract.effective_capabilities_sha256
        ):
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_identity_changed",
                "已发布规则包或其映射身份在运行准备后发生变化，"
                "规则执行已关闭，请新建运行。",
            )

    def _validate_locked_input(self, run: MonitoringDailyRun) -> None:
        current = self._frozen_project_batch(run.project_id, run.batch_id)
        if current.version != run.batch_version:
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_changed",
                "批次版本在运行准备后发生变化。",
            )
        if current.active_mapping_revision != run.mapping_revision:
            raise MonitoringDailyRunServiceError(
                "monitoring_mapping_changed",
                "字段映射在运行准备后发生变化，请新建运行。",
            )
        if run.baseline_batch_id:
            self._frozen_project_batch(run.project_id, run.baseline_batch_id)

    def _validate_start_contract(
        self,
        project_id: str,
        batch: Any,
    ) -> MonitoringRuleRuntimeIdentity:
        if not batch.active_mapping_revision:
            raise MonitoringDailyRunServiceError(
                "monitoring_mapping_required",
                "当前批次尚未绑定已确认的字段映射。",
            )
        active_mapping = None
        if self.active_mapping_resolver is not None:
            try:
                active_mapping = self.active_mapping_resolver(project_id)
            except Exception as exc:
                raise MonitoringDailyRunServiceError(
                    "monitoring_mapping_required",
                    "当前项目尚无可用的已激活字段映射。",
                ) from exc
            if (
                str(getattr(active_mapping, "mapping_revision", "")).strip()
                != batch.active_mapping_revision
            ):
                raise MonitoringDailyRunServiceError(
                    "monitoring_mapping_changed",
                    "当前项目字段映射已变化，请按最新映射重新确认并冻结批次。",
                )
        try:
            mapping_contract = self.batch_repository.load_frozen_mapping_contract(
                batch.batch_id
            )
        except Exception as exc:
            raise MonitoringDailyRunServiceError(
                "monitoring_capability_contract_required",
                "当前冻结批次缺少字段能力快照，请重新校对字段映射。",
            ) from exc
        if (
            mapping_contract.mapping_revision != batch.active_mapping_revision
            or not mapping_contract.capability_manifest_sha256
            or not mapping_contract.capability_states
        ):
            raise MonitoringDailyRunServiceError(
                "monitoring_capability_contract_required",
                "当前冻结批次缺少与已激活映射一致的字段能力快照，请重新校对字段映射。",
            )
        for field in (
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            _require_identity_sha256(
                getattr(mapping_contract, field, None),
                f"mapping_contract.{field}",
                code="monitoring_capability_contract_required",
            )
        identity = self._resolve_rule_identity(project_id)
        if active_mapping is not None:
            rule_mapping_revision = identity.rule_mapping_revision.strip()
            rule_mapping_content_sha256 = identity.rule_mapping_content_sha256
            rule_capability_manifest_sha256 = (
                identity.rule_capability_manifest_sha256
            )
            rule_effective_capabilities_sha256 = (
                identity.rule_effective_capabilities_sha256
            )
            if (
                not rule_mapping_revision
                or not rule_mapping_content_sha256
                or not rule_capability_manifest_sha256
                or not rule_effective_capabilities_sha256
            ):
                raise MonitoringDailyRunServiceError(
                    "monitoring_rule_pack_identity_unverifiable",
                    "已发布规则包缺少可追溯的字段映射身份，请通过规则建议链重新确认并发布规则包。",
                )
            for field in (
                "mapping_content_sha256",
                "capability_manifest_sha256",
                "effective_capabilities_sha256",
            ):
                _require_identity_sha256(
                    getattr(active_mapping, field, None),
                    f"active_mapping.{field}",
                    code="monitoring_rule_pack_identity_unverifiable",
                )
            for field in (
                "rule_mapping_content_sha256",
                "rule_capability_manifest_sha256",
                "rule_effective_capabilities_sha256",
            ):
                _require_identity_sha256(
                    getattr(identity, field, None),
                    f"rule_identity.{field}",
                    code="monitoring_rule_pack_identity_unverifiable",
                )
            if (
                rule_mapping_revision
                != str(getattr(active_mapping, "mapping_revision", "")).strip()
                or rule_mapping_content_sha256
                != getattr(active_mapping, "mapping_content_sha256", "")
                or rule_capability_manifest_sha256
                != getattr(active_mapping, "capability_manifest_sha256", "")
                or rule_effective_capabilities_sha256
                != getattr(active_mapping, "effective_capabilities_sha256", "")
            ):
                raise MonitoringDailyRunServiceError(
                    "monitoring_rule_pack_identity_drift",
                    "已发布规则包的字段映射身份与当前已激活映射不一致，请按最新映射重新确认规则并发布规则包。",
                )
        self._require_ai_runtime()
        return identity

    def _resolve_rule_identity(
        self,
        project_id: str,
    ) -> MonitoringRuleRuntimeIdentity:
        try:
            record_resolution_available = (
                self.record_rule_resolver is not None
                and self.record_rule_resolver.project_supports_record_resolution(
                    project_id
                )
            )
            if record_resolution_available:
                aggregate = self.record_rule_resolver.aggregate_identity(
                    project_id
                )
                identity = MonitoringRuleRuntimeIdentity(
                    rule_pack_revision=aggregate.identity_sha256,
                    engine_version="monitoring_protocol_rule_engine.v1",
                    resolution_mode="record_applicability",
                    rule_mapping_revision=aggregate.mapping_revision,
                    rule_mapping_content_sha256=(
                        aggregate.mapping_content_sha256
                    ),
                    rule_capability_manifest_sha256=(
                        aggregate.capability_manifest_sha256
                    ),
                    rule_effective_capabilities_sha256=(
                        aggregate.effective_capabilities_sha256
                    ),
                    rule_identity_sha256=aggregate.identity_sha256,
                )
            else:
                identity = self.rule_runtime_resolver(project_id)
        except RecordRuleAggregateIdentityError as exc:
            raise MonitoringDailyRunServiceError(
                exc.code,
                exc.message,
            ) from exc
        except Exception as exc:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_pack_required",
                "当前项目尚无可用于日常医学监查的已发布规则包。",
            ) from exc
        if identity.resolution_mode == "project_effective" and (
            not identity.rule_pack_revision.strip()
        ):
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_pack_required",
                "当前项目尚无可用于日常医学监查的已发布规则包。",
            )
        if identity.resolution_mode == "record_applicability":
            for field in (
                "rule_mapping_content_sha256",
                "rule_capability_manifest_sha256",
                "rule_effective_capabilities_sha256",
                "rule_identity_sha256",
            ):
                _require_identity_sha256(
                    getattr(identity, field, None),
                    f"rule_identity.{field}",
                    code="monitoring_rule_pack_identity_unverifiable",
                )
        else:
            for field in (
                "rule_mapping_content_sha256",
                "rule_capability_manifest_sha256",
                "rule_effective_capabilities_sha256",
                "rule_identity_sha256",
            ):
                _require_optional_identity_sha256(
                    getattr(identity, field, None),
                    f"rule_identity.{field}",
                    code="monitoring_rule_pack_identity_unverifiable",
                )
        if identity.resolution_mode not in {
            "project_effective",
            "record_applicability",
        }:
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_resolution_mode_invalid",
                "医学监查规则解析模式无效。",
            )
        if (
            identity.resolution_mode == "record_applicability"
            and self.record_rule_resolver is None
        ):
            raise MonitoringDailyRunServiceError(
                "monitoring_record_rule_resolver_unavailable",
                "逐记录方案与规则包解析器当前不可用。",
            )
        if not identity.engine_version.strip():
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_engine_required",
                "当前项目尚无可审计的医学规则引擎版本。",
            )
        return identity

    def _require_ai_runtime(self) -> None:
        if self.ai_runtime_resolver is None:
            return
        try:
            ai_runtime = self.ai_runtime_resolver()
        except Exception as exc:
            raise MonitoringDailyRunServiceError(
                "monitoring_ai_not_ready",
                "独立 AI 运行配置当前不可用。",
            ) from exc
        if getattr(ai_runtime, "available", False) is not True:
            diagnostic = str(
                getattr(ai_runtime, "diagnostic", "")
                or "独立 AI 尚未配置为可运行状态。"
            )
            raise MonitoringDailyRunServiceError(
                "monitoring_ai_not_ready",
                diagnostic,
            )
        if str(getattr(ai_runtime, "transport", "")).strip() != (
            "openai_compatible"
        ):
            raise MonitoringDailyRunServiceError(
                "monitoring_ai_transport_rejected",
                "医学监查独立 AI 必须使用产品 API 运行通道。",
            )

    @staticmethod
    def _readiness_next_action(code: str) -> str:
        return {
            "monitoring_batch_not_found": "select_batch",
            "monitoring_batch_not_frozen": "complete_batch",
            "monitoring_batch_already_confirmed": "import_next_batch",
            "monitoring_mapping_required": "confirm_mapping",
            "monitoring_mapping_changed": "confirm_mapping",
            "monitoring_capability_contract_required": "confirm_mapping",
            "monitoring_rule_pack_required": "prepare_rule_pack",
            "monitoring_rule_pack_identity_unverifiable": "prepare_rule_pack",
            "monitoring_rule_pack_identity_drift": "prepare_rule_pack",
            "monitoring_rule_resolution_mode_invalid": "prepare_rule_pack",
            "monitoring_record_rule_resolver_unavailable": "prepare_rule_pack",
            "monitoring_rule_engine_required": "prepare_rule_pack",
            "monitoring_ai_not_ready": "configure_ai",
            "monitoring_ai_transport_rejected": "configure_ai",
        }.get(code, "review_configuration")

    def _frozen_project_batch(self, project_id: str, batch_id: str):
        try:
            batch = self.batch_repository.get_batch(batch_id)
        except Exception as exc:
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_not_found",
                "未找到医学监查批次。",
            ) from exc
        if batch.project_id != project_id:
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_not_found",
                "未找到当前项目的医学监查批次。",
            )
        if batch.state != "frozen":
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_not_frozen",
                "批次必须先完成内容、字段映射和完整性确认并冻结。",
            )
        return batch

    @staticmethod
    def _diff_batch_identity(batch: Any) -> Mapping[str, Any]:
        return {
            "batch_id": batch.batch_id,
            "version": batch.version,
            "mapping_revision": batch.mapping_revision,
            "source_bindings": list(batch.source_bindings),
            "source_hashes": list(batch.source_hashes),
            "schema_fields": list(batch.schema_fields),
            "full_snapshot_proven": bool(
                getattr(batch, "full_snapshot_proven", False)
            ),
            "row_fingerprints": [
                (row.business_key, row.row_fingerprint) for row in batch.rows
            ],
        }
