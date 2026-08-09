from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Sequence, Tuple

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
)

from .ai_task_runner import AiTaskRunner
from .eligibility_protocol_rules import eligibility_criterion_text_hash
from .eligibility_review_workflow import CriterionKind, EligibilityReviewWorkflow
from .sqlite_runtime_store import RuntimeStoreError

if TYPE_CHECKING:
    from .eligibility_ai_packet import EligibilityAiPacket


@dataclass(frozen=True)
class EligibilityAiCriterion:
    criterion_uid: str
    criterion_kind: CriterionKind
    text: str
    source_locator: str
    display_order: int


@dataclass(frozen=True)
class EligibilityAiBatchOutcome:
    batch_id: str
    criterion_kind: str
    criterion_uids: Tuple[str, ...]
    run_id: str
    status: str
    drafts_persisted: bool
    validation_errors: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EligibilityAiSubjectResult:
    project_id: str
    subject_id: str
    rule_revision: str
    subject_source_revision: str
    batches: Tuple[EligibilityAiBatchOutcome, ...]


def _canonical_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def plan_criterion_batches(
    criteria: Iterable[EligibilityAiCriterion],
) -> List[Tuple[EligibilityAiCriterion, ...]]:
    ordered = sorted(criteria, key=lambda item: (item.display_order, item.criterion_uid))
    if not ordered:
        return []
    kinds = {item.criterion_kind for item in ordered}
    if len(kinds) != 1:
        raise ValueError("eligibility AI batch planner accepts one criterion kind")
    count = len(ordered)
    if count < 5:
        return [(item,) for item in ordered]
    group_count = next(
        (
            groups
            for groups in range((count + 7) // 8, count // 5 + 1)
            if groups * 5 <= count <= groups * 8
        ),
        None,
    )
    if group_count is None:
        full, tail = divmod(count, 8)
        batches = [tuple(ordered[index * 8 : (index + 1) * 8]) for index in range(full)]
        batches.extend((item,) for item in ordered[full * 8 :] if tail)
        return batches
    base, remainder = divmod(count, group_count)
    sizes = [base + (1 if index < remainder else 0) for index in range(group_count)]
    batches = []
    offset = 0
    for size in sizes:
        batches.append(tuple(ordered[offset : offset + size]))
        offset += size
    return batches


class EligibilityAiBatchService:
    def __init__(
        self,
        runner: AiTaskRunner,
        review_workflow: EligibilityReviewWorkflow,
    ) -> None:
        self.runner = runner
        self.review_workflow = review_workflow

    def run_packet(self, packet: "EligibilityAiPacket") -> EligibilityAiSubjectResult:
        return self._run_verified_subject(
            project_id=packet.project_id,
            subject_id=packet.subject_id,
            subject_token=packet.subject_token,
            rule_revision=packet.rule_revision,
            subject_source_revision=packet.subject_source_revision,
            packet_digest=packet.packet_digest,
            criteria=packet.criteria,
            evidence_sources=packet.evidence_sources,
        )

    def _run_verified_subject(
        self,
        *,
        project_id: str,
        subject_id: str,
        subject_token: str,
        rule_revision: str,
        subject_source_revision: str,
        packet_digest: str,
        criteria: Sequence[EligibilityAiCriterion],
        evidence_sources: Sequence[AiTaskSourceRef],
    ) -> EligibilityAiSubjectResult:
        if not all(
            (
                project_id,
                subject_id,
                subject_token,
                rule_revision,
                subject_source_revision,
                packet_digest,
            )
        ):
            raise ValueError("eligibility AI subject identity is required")
        if any(
            source.project_id != project_id or source.module != "eligibility_review"
            for source in evidence_sources
        ):
            raise ValueError(
                "eligibility AI evidence sources must belong to the canonical project"
            )
        evidence_ids = [source.source_id for source in evidence_sources]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("eligibility AI evidence source IDs must be unique")

        derived_processing_state = (
            self.review_workflow.store.validate_eligibility_ai_inputs(
                project_id=project_id,
                subject_id=subject_id,
                rule_revision=rule_revision,
                subject_source_revision=subject_source_revision,
                criteria=[
                    {
                        "criterion_uid": criterion.criterion_uid,
                        "criterion_kind": criterion.criterion_kind.value,
                        "source_locator": criterion.source_locator,
                        "normalized_text_hash": eligibility_criterion_text_hash(
                            criterion.text
                        ),
                        "display_order": criterion.display_order,
                    }
                    for criterion in criteria
                ],
                evidence_ids=evidence_ids,
            )
        )
        if derived_processing_state != "completed":
            raise ValueError(
                "eligibility AI review requires server-verified completed evidence processing"
            )

        outcomes: List[EligibilityAiBatchOutcome] = []
        for kind in (CriterionKind.INCLUSION, CriterionKind.EXCLUSION):
            kind_criteria = [item for item in criteria if item.criterion_kind == kind]
            for criterion_batch in plan_criterion_batches(kind_criteria):
                outcome = self._run_batch(
                    project_id=project_id,
                    subject_id=subject_id,
                    subject_token=subject_token,
                    rule_revision=rule_revision,
                    subject_source_revision=subject_source_revision,
                    packet_digest=packet_digest,
                    criteria=criterion_batch,
                    evidence_sources=evidence_sources,
                    evidence_processing_state=derived_processing_state,
                )
                outcomes.append(outcome)
        return EligibilityAiSubjectResult(
            project_id=project_id,
            subject_id=subject_id,
            rule_revision=rule_revision,
            subject_source_revision=subject_source_revision,
            batches=tuple(outcomes),
        )

    def _run_batch(
        self,
        *,
        project_id: str,
        subject_id: str,
        subject_token: str,
        rule_revision: str,
        subject_source_revision: str,
        packet_digest: str,
        criteria: Tuple[EligibilityAiCriterion, ...],
        evidence_sources: Sequence[AiTaskSourceRef],
        evidence_processing_state: str,
    ) -> EligibilityAiBatchOutcome:
        criterion_uids = [criterion.criterion_uid for criterion in criteria]
        criterion_kind = criteria[0].criterion_kind.value
        batch_id = "eligbatch_" + _canonical_hash(
            {
                "project_id": project_id,
                "subject_id": subject_id,
                "rule_revision": rule_revision,
                "subject_source_revision": subject_source_revision,
                "packet_digest": packet_digest,
                "criterion_kind": criterion_kind,
                "criterion_uids": criterion_uids,
            }
        )[:24]
        idempotency_key = f"{batch_id}:{packet_digest}"
        request_fingerprint = _canonical_hash(
            {
                "batch_id": batch_id,
                "packet_digest": packet_digest,
                "criterion_uids": criterion_uids,
            }
        )
        replay = self.review_workflow.store.eligibility_ai_batch_replay(
            project_id=project_id,
            subject_id=subject_id,
            batch_id=batch_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return EligibilityAiBatchOutcome(
                batch_id=batch_id,
                criterion_kind=criterion_kind,
                criterion_uids=tuple(criterion_uids),
                run_id=replay.request_id,
                status="replayed",
                drafts_persisted=True,
            )
        rule_sources = [
            AiTaskSourceRef(
                source_id=f"rule:{criterion.criterion_uid}",
                source_type="eligibility_protocol_rule",
                title=criterion.criterion_uid,
                locator=criterion.source_locator,
                text_preview=criterion.text,
                project_id=project_id,
                module="eligibility_review",
            )
            for criterion in criteria
        ]
        context = {
            "batch_id": batch_id,
            "subject_token": subject_token,
            "criterion_kind": criterion_kind,
            "criterion_uids": criterion_uids,
            "rule_revision": rule_revision,
            "subject_source_revision": subject_source_revision,
            "packet_digest": packet_digest,
            "allowed_evidence_ids": [source.source_id for source in evidence_sources],
        }
        expected_state_revisions = {
            criterion.criterion_uid: int(
                (
                    self.review_workflow.store.eligibility_review_state(
                        project_id, subject_id, criterion.criterion_uid
                    )
                    or {"state_revision": 0}
                )["state_revision"]
            )
            for criterion in criteria
        }
        run = self.runner.submit_internal(
            project_id,
            AiTaskRequest(
                module="eligibility_review",
                task_type="eligibility_rule_review",
                prompt_version="eligibility_rule_review_v0_1",
                allowed_sources=[*rule_sources, *evidence_sources],
                forbidden_source_ids=[
                    "legacy_evidence_bundle",
                    "legacy_review_report",
                    "previous_ai_summary",
                ],
                user_instruction=(
                    "仅处理本批次同一类型标准。不得引用另一类型标准的AI结论；"
                    "逐条输出待医学确认的审核草稿。"
                ),
                task_context=context,
            ),
        )
        if run.status != AiTaskRunStatus.COMPLETED:
            return EligibilityAiBatchOutcome(
                batch_id=batch_id,
                criterion_kind=criterion_kind,
                criterion_uids=tuple(criterion_uids),
                run_id=run.run_id,
                status=str(getattr(run.status, "value", run.status)),
                drafts_persisted=False,
                validation_errors=tuple(run.validation_errors),
            )
        output = self._provider_output(run)
        result_by_uid = {
            result["criterion_uid"]: result
            for result in output["criterion_results"]
        }
        records = []
        for criterion in criteria:
            result = result_by_uid[criterion.criterion_uid]
            previous_revision = expected_state_revisions[criterion.criterion_uid]
            records.append(
                {
                    "record_id": (
                        f"eligreview_{_canonical_hash([run.run_id, criterion.criterion_uid])[:24]}"
                    ),
                    "project_id": project_id,
                    "subject_id": subject_id,
                    "criterion_uid": criterion.criterion_uid,
                    "criterion_kind": criterion_kind,
                    "record_type": "ai_draft",
                    "action": "save_ai_draft",
                    "action_decision": result["decision"],
                    "evidence_processing_state": evidence_processing_state,
                    "rule_revision": rule_revision,
                    "subject_source_revision": subject_source_revision,
                    "previous_state_revision": previous_revision,
                    "new_state_revision": previous_revision + 1,
                    "evidence_ids": list(result["evidence_ids"]),
                    "reason": result["rationale"],
                    "actor": "workbench_ai_gateway",
                }
            )
        try:
            self.review_workflow.store.commit_eligibility_ai_draft_batch(
                records,
                batch_id=batch_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        except RuntimeStoreError as exc:
            return EligibilityAiBatchOutcome(
                batch_id=batch_id,
                criterion_kind=criterion_kind,
                criterion_uids=tuple(criterion_uids),
                run_id=run.run_id,
                status="persistence_failed",
                drafts_persisted=False,
                validation_errors=(str(exc),),
            )
        return EligibilityAiBatchOutcome(
            batch_id=batch_id,
            criterion_kind=criterion_kind,
            criterion_uids=tuple(criterion_uids),
            run_id=run.run_id,
            status="completed",
            drafts_persisted=True,
        )

    @staticmethod
    def _provider_output(run: Any) -> Dict[str, Any]:
        for artifact in run.artifacts:
            if artifact.artifact_type == "provider_output" and isinstance(
                artifact.payload, dict
            ):
                return artifact.payload
        raise ValueError("eligibility AI run has no validated provider output")
