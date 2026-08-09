from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    content_sha256,
)
from .monitoring_ai_repository import MonitoringAiRepository
from .monitoring_ai_service import MonitoringAiService
from .monitoring_batch_repository import DiffReadyBatch, NormalizedRow
from .monitoring_daily_run_repository import (
    MonitoringDiffSnapshot,
    MonitoringRuleSnapshot,
)


MAX_EVIDENCE_PER_SUBJECT = 200
MAX_FIELDS_PER_ROW = 80
_SUBJECT_FIELDS = ("USUBJID", "SUBJID", "SUBJECT_ID", "SUBJECTID")
_STUDY_TREATMENT_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_TERMINAL_FAILURE_STATUSES = frozenset(
    {
        MonitoringAiJobStatus.FAILED,
        MonitoringAiJobStatus.BLOCKED,
        MonitoringAiJobStatus.STALE_INPUT,
        MonitoringAiJobStatus.CANCELLED,
    }
)
_SOURCE_CONTENT_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _optional_source_content_sha256(value: Any) -> str:
    """Preserve absent locator hashes but reject present noncanonical values."""

    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not _SOURCE_CONTENT_SHA256_RE.fullmatch(
        value
    ):
        raise ValueError("source content hash must be a lowercase SHA-256")
    return value


class MonitoringDailyRunAiServiceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code).strip() or "monitoring_daily_ai_error"
        self.message = str(message).strip() or self.code
        super().__init__(self.message)


@dataclass(frozen=True)
class MonitoringDailyAiSubmission:
    project_id: str
    run_id: str
    batch_id: str
    rule_snapshot_id: str
    selected_subject_ids: tuple[str, ...]
    jobs: tuple[MonitoringAiJob, ...]

    @property
    def job_ids(self) -> tuple[str, ...]:
        return tuple(job.job_id for job in self.jobs)


@dataclass(frozen=True)
class MonitoringDailyAiReviewCandidate:
    subject_id: str
    job_id: str
    candidate: MonitoringAiCandidate


@dataclass(frozen=True)
class MonitoringDailyAiProgress:
    project_id: str
    run_id: str
    status: str
    total: int
    queued: int
    running: int
    completed: int
    failed: int
    candidates: tuple[MonitoringDailyAiReviewCandidate, ...]
    failures: tuple[dict[str, str], ...]


class MonitoringDailyRunAiService:
    """Submit and observe subject-level product-AI review for one daily run.

    This layer only prepares source-bound CROSS_TABLE_CLUE_SYNTHESIS jobs and
    returns proposed AI candidates. It never promotes a candidate to a formal
    risk, protocol deviation, missing report, or Query.
    """

    def __init__(
        self,
        *,
        ai_service: MonitoringAiService,
        ai_repository: MonitoringAiRepository,
    ):
        if ai_service.repository is not ai_repository:
            raise ValueError(
                "monitoring daily AI service and repository must share state"
            )
        self.ai_service = ai_service
        self.ai_repository = ai_repository

    def submit(
        self,
        *,
        project_id: str,
        batch: DiffReadyBatch,
        rule_snapshot: MonitoringRuleSnapshot,
        diff_snapshot: MonitoringDiffSnapshot | None = None,
        max_attempts: int = 2,
    ) -> MonitoringDailyAiSubmission:
        self._validate_inputs(
            project_id=project_id,
            batch=batch,
            rule_snapshot=rule_snapshot,
            diff_snapshot=diff_snapshot,
        )
        rows_by_subject = self._rows_by_subject(batch.rows)
        candidate_subjects, candidate_row_keys = self._rule_candidate_scope(
            rule_snapshot
        )
        changed_row_keys = self._changed_row_keys(diff_snapshot)

        if diff_snapshot is None:
            selected = {
                subject_id
                for subject_id, rows in rows_by_subject.items()
                if len({row.domain.upper() for row in rows}) >= 2
            }
            selection_reason = {
                subject_id: ("initial_baseline_multi_domain",)
                for subject_id in selected
            }
        else:
            changed_subjects = {
                subject_id
                for subject_id, rows in rows_by_subject.items()
                if any(row.business_key in changed_row_keys for row in rows)
            }
            selected = candidate_subjects | changed_subjects
            selection_reason = {}
            for subject_id in selected:
                reasons = []
                if subject_id in changed_subjects:
                    reasons.append("incremental_diff")
                if subject_id in candidate_subjects:
                    reasons.append("deterministic_rule_candidate")
                selection_reason[subject_id] = tuple(reasons)

        eligible = tuple(
            subject_id
            for subject_id in sorted(selected, key=lambda value: (value.casefold(), value))
            if (
                subject_id in rows_by_subject
                and len(
                    {
                        row.domain.upper()
                        for row in rows_by_subject[subject_id]
                    }
                )
                >= 2
            )
        )
        jobs = []
        for subject_id in eligible:
            evidence = self._subject_evidence(
                batch=batch,
                subject_id=subject_id,
                rows=rows_by_subject[subject_id],
                priority_business_keys=(
                    changed_row_keys | candidate_row_keys.get(subject_id, set())
                ),
            )
            sources = self._source_bindings_from_evidence(evidence)
            input_revision = MonitoringAiInputRevision(
                project_id=project_id,
                batch_revision=f"{batch.batch_id}:v{batch.version}",
                mapping_revision=str(batch.mapping_revision or ""),
                rule_pack_revision=(
                    f"{rule_snapshot.rule_pack_id}:"
                    f"{rule_snapshot.output_sha256[:24]}"
                ),
                sources=sources,
            )
            domains = tuple(
                sorted(
                    {str(item["raw_fields"]["domain"]).upper() for item in evidence}
                )
            )
            payload = {
                "subject_context": {
                    "daily_run_id": rule_snapshot.run_id,
                    "subject_id": subject_id,
                    "batch_id": batch.batch_id,
                    "batch_version": batch.version,
                    "mapping_revision": batch.mapping_revision,
                    "rule_snapshot_id": rule_snapshot.snapshot_id,
                    "rule_pack_id": rule_snapshot.rule_pack_id,
                    "rule_output_sha256": rule_snapshot.output_sha256,
                    "selection_reasons": list(selection_reason[subject_id]),
                    "domains": list(domains),
                    "domain_semantics": {
                        "CM": "非试验用合并用药或治疗",
                        "EX_EC_DA_IP": (
                            "试验药物给药、剂量调整、停药、重启或依从性"
                        ),
                    },
                    "medical_boundary": (
                        "仅生成待当前医学用户复核的跨表线索；不得自动判定"
                        "AE/MH漏报、方案违背或生成Query。"
                    ),
                },
                "evidence_packet": evidence,
            }
            jobs.append(
                self.ai_service.submit_task(
                    project_id=project_id,
                    task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
                    input_revision=input_revision,
                    input_payload=payload,
                    business_key=self._business_key(
                        rule_snapshot.run_id,
                        subject_id,
                    ),
                    max_attempts=max_attempts,
                )
            )
        return MonitoringDailyAiSubmission(
            project_id=project_id,
            run_id=rule_snapshot.run_id,
            batch_id=batch.batch_id,
            rule_snapshot_id=rule_snapshot.snapshot_id,
            selected_subject_ids=eligible,
            jobs=tuple(jobs),
        )

    def progress(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> MonitoringDailyAiProgress:
        jobs = self.ai_repository.list_jobs(
            project_id,
            task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS.value,
            business_key_prefix=self._business_key_prefix(run_id),
        )
        queued = sum(job.status == MonitoringAiJobStatus.QUEUED for job in jobs)
        running = sum(job.status == MonitoringAiJobStatus.RUNNING for job in jobs)
        completed = sum(job.status == MonitoringAiJobStatus.COMPLETED for job in jobs)
        failed_jobs = tuple(
            job for job in jobs if job.status in _TERMINAL_FAILURE_STATUSES
        )
        failed = len(failed_jobs)
        if not jobs:
            status = "not_submitted"
        elif queued or running:
            status = "running"
        elif completed == len(jobs):
            status = "completed"
        elif failed == len(jobs):
            status = "failed"
        else:
            status = "partial_completed"

        candidates = []
        for job in jobs:
            if job.status != MonitoringAiJobStatus.COMPLETED:
                continue
            subject_id = str(
                self.ai_repository.input_payload(
                    project_id,
                    job.job_id,
                )["subject_context"]["subject_id"]
            )
            candidates.extend(
                MonitoringDailyAiReviewCandidate(
                    subject_id=subject_id,
                    job_id=job.job_id,
                    candidate=candidate,
                )
                for candidate in self.ai_repository.candidates(
                    project_id,
                    job.job_id,
                )
            )
        return MonitoringDailyAiProgress(
            project_id=project_id,
            run_id=run_id,
            status=status,
            total=len(jobs),
            queued=queued,
            running=running,
            completed=completed,
            failed=failed,
            candidates=tuple(candidates),
            failures=tuple(
                {
                    "job_id": job.job_id,
                    "subject_id": str(
                        self.ai_repository.input_payload(
                            project_id,
                            job.job_id,
                        )["subject_context"]["subject_id"]
                    ),
                    "status": job.status.value,
                    "failure_code": job.failure_code,
                    "failure_message": job.failure_message,
                }
                for job in failed_jobs
            ),
        )

    @classmethod
    def _validate_inputs(
        cls,
        *,
        project_id: str,
        batch: DiffReadyBatch,
        rule_snapshot: MonitoringRuleSnapshot,
        diff_snapshot: MonitoringDiffSnapshot | None,
    ) -> None:
        if batch.state != "frozen":
            raise MonitoringDailyRunAiServiceError(
                "monitoring_batch_not_frozen",
                "独立 AI 仅可读取已冻结的医学监查批次。",
            )
        if not batch.mapping_revision:
            raise MonitoringDailyRunAiServiceError(
                "monitoring_mapping_required",
                "冻结批次缺少字段映射修订。",
            )
        if (
            batch.project_id != project_id
            or rule_snapshot.project_id != project_id
            or rule_snapshot.batch_id != batch.batch_id
        ):
            raise MonitoringDailyRunAiServiceError(
                "monitoring_ai_lineage_mismatch",
                "批次、规则快照与项目来源链不一致。",
            )
        if not rule_snapshot.output_sha256 or not rule_snapshot.rule_pack_id:
            raise MonitoringDailyRunAiServiceError(
                "monitoring_rule_snapshot_incomplete",
                "规则快照缺少不可变输出或规则包身份。",
            )
        if diff_snapshot is not None and (
            diff_snapshot.project_id != project_id
            or diff_snapshot.run_id != rule_snapshot.run_id
            or diff_snapshot.current_batch_id != batch.batch_id
        ):
            raise MonitoringDailyRunAiServiceError(
                "monitoring_diff_lineage_mismatch",
                "增量差异快照与当前运行或批次不一致。",
            )

    @classmethod
    def _rows_by_subject(
        cls,
        rows: Iterable[NormalizedRow],
    ) -> dict[str, tuple[NormalizedRow, ...]]:
        grouped: dict[str, list[NormalizedRow]] = {}
        for row in rows:
            subject_id = cls._subject_id(row)
            if subject_id:
                grouped.setdefault(subject_id, []).append(row)
        return {
            subject_id: tuple(
                sorted(
                    subject_rows,
                    key=lambda row: (
                        row.domain.casefold(),
                        row.domain,
                        row.business_key,
                    ),
                )
            )
            for subject_id, subject_rows in grouped.items()
        }

    @staticmethod
    def _subject_id(row: NormalizedRow) -> str:
        values = {str(key).upper(): value for key, value in row.data.items()}
        for field in _SUBJECT_FIELDS:
            value = str(values.get(field) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _rule_candidate_scope(
        snapshot: MonitoringRuleSnapshot,
    ) -> tuple[set[str], dict[str, set[str]]]:
        subjects: set[str] = set()
        row_keys: dict[str, set[str]] = {}
        for candidate in snapshot.payload.get("candidates") or ():
            if not isinstance(candidate, Mapping):
                continue
            subject_id = str(candidate.get("subject_id") or "").strip()
            if not subject_id:
                continue
            subjects.add(subject_id)
            business_key = str(
                candidate.get("current_business_key") or ""
            ).strip()
            if business_key:
                row_keys.setdefault(subject_id, set()).add(business_key)
        return subjects, row_keys

    @staticmethod
    def _changed_row_keys(
        snapshot: MonitoringDiffSnapshot | None,
    ) -> set[str]:
        if snapshot is None:
            return set()
        row_diff = snapshot.payload.get("row_diff") or {}
        keys: set[str] = set()
        for name in (
            "new_keys",
            "changed_keys",
            "requires_rereview_keys",
        ):
            values = row_diff.get(name) or ()
            keys.update(str(value) for value in values if str(value).strip())
        for change in snapshot.payload.get("field_changes") or ():
            if isinstance(change, Mapping):
                key = str(change.get("business_key") or "").strip()
                if key:
                    keys.add(key)
        return keys

    @classmethod
    def _subject_evidence(
        cls,
        *,
        batch: DiffReadyBatch,
        subject_id: str,
        rows: Sequence[NormalizedRow],
        priority_business_keys: set[str],
    ) -> list[dict[str, Any]]:
        selected = cls._prioritized_rows(rows, priority_business_keys)
        evidence = [
            cls._row_evidence(
                batch=batch,
                subject_id=subject_id,
                row=row,
            )
            for row in selected[:MAX_EVIDENCE_PER_SUBJECT]
        ]
        if len({item["raw_fields"]["domain"] for item in evidence}) < 2:
            raise MonitoringDailyRunAiServiceError(
                "monitoring_ai_cross_table_evidence_insufficient",
                f"受试者 {subject_id} 缺少至少两个真实数据域的原始证据。",
            )
        return evidence

    @staticmethod
    def _prioritized_rows(
        rows: Sequence[NormalizedRow],
        priority_business_keys: set[str],
    ) -> tuple[NormalizedRow, ...]:
        by_domain: dict[str, list[NormalizedRow]] = {}
        for row in rows:
            by_domain.setdefault(row.domain.upper(), []).append(row)
        for domain_rows in by_domain.values():
            domain_rows.sort(
                key=lambda row: (
                    0 if row.business_key in priority_business_keys else 1,
                    row.business_key,
                )
            )

        selected: list[NormalizedRow] = []
        selected_keys: set[str] = set()
        for domain in sorted(by_domain):
            row = by_domain[domain][0]
            selected.append(row)
            selected_keys.add(row.business_key)
        remainder = sorted(
            (row for row in rows if row.business_key not in selected_keys),
            key=lambda row: (
                0 if row.business_key in priority_business_keys else 1,
                row.domain.casefold(),
                row.domain,
                row.business_key,
            ),
        )
        selected.extend(remainder)
        return tuple(selected)

    @classmethod
    def _row_evidence(
        cls,
        *,
        batch: DiffReadyBatch,
        subject_id: str,
        row: NormalizedRow,
    ) -> dict[str, Any]:
        source_entry_id, source_content_sha256 = cls._row_source_binding(
            batch,
            row,
        )
        fields, omitted_count = cls._compact_fields(row.data)
        locator = cls._locator_text(row.source_locator)
        quote_fields = "; ".join(
            f"{item['field']}={cls._display_value(item['value'])}"
            for item in fields[:20]
        )
        quote = f"{row.domain.upper()} | {quote_fields}"[:8_000]
        evidence_id = "mondaily_{}".format(
            content_sha256(
                {
                    "batch_id": batch.batch_id,
                    "subject_id": subject_id,
                    "business_key": row.business_key,
                    "row_fingerprint": row.row_fingerprint,
                    "source_entry_id": source_entry_id,
                    "source_content_sha256": source_content_sha256,
                }
            )[:28]
        )
        return {
            "evidence_id": evidence_id,
            "source_entry_id": source_entry_id,
            "source_content_sha256": source_content_sha256,
            "locator": locator,
            "quote": quote,
            "raw_fields": {
                "evidence_kind": "original_listing_row",
                "subject_id": subject_id,
                "domain": row.domain.upper(),
                "domain_role": cls._domain_role(row.domain),
                "business_key": row.business_key,
                "row_fingerprint": row.row_fingerprint,
                "fields": fields,
                "omitted_non_empty_field_count": omitted_count,
            },
        }

    @staticmethod
    def _row_source_binding(
        batch: DiffReadyBatch,
        row: NormalizedRow,
    ) -> tuple[str, str]:
        allowed = dict(batch.source_bindings)
        locator = row.source_locator
        source_entry_id = str(
            locator.get("source_entry_id")
            or locator.get("entry_id")
            or ""
        ).strip()
        raw_source_hash = (
            locator.get("source_content_sha256")
            or locator.get("content_sha256")
            or ""
        )
        try:
            source_hash = _optional_source_content_sha256(raw_source_hash)
        except ValueError as exc:
            raise MonitoringDailyRunAiServiceError(
                "monitoring_ai_source_binding_malformed",
                f"原始行 {row.business_key} 的来源内容哈希格式无效。",
            ) from exc
        if source_entry_id:
            expected_hash = allowed.get(source_entry_id)
            if expected_hash is None or (
                source_hash and source_hash != expected_hash
            ):
                raise MonitoringDailyRunAiServiceError(
                    "monitoring_ai_source_binding_mismatch",
                    f"原始行 {row.business_key} 的来源绑定不属于冻结批次。",
                )
            return source_entry_id, expected_hash
        if len(batch.source_bindings) == 1:
            return batch.source_bindings[0]
        raise MonitoringDailyRunAiServiceError(
            "monitoring_ai_source_binding_ambiguous",
            f"原始行 {row.business_key} 无法唯一定位到冻结来源文件。",
        )

    @staticmethod
    def _compact_fields(
        data: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        non_empty = [
            (str(field), _json_safe(value))
            for field, value in data.items()
            if value is not None and str(value).strip() != ""
        ]
        non_empty.sort(
            key=lambda item: (
                1 if item[0].startswith("__") else 0,
                item[0].casefold(),
                item[0],
            )
        )
        kept = non_empty[:MAX_FIELDS_PER_ROW]
        return (
            [{"field": field, "value": value} for field, value in kept],
            max(0, len(non_empty) - len(kept)),
        )

    @staticmethod
    def _source_bindings_from_evidence(
        evidence: Sequence[Mapping[str, Any]],
    ) -> tuple[MonitoringAiSourceBinding, ...]:
        pairs = sorted(
            {
                (
                    str(item["source_entry_id"]),
                    str(item["source_content_sha256"]),
                )
                for item in evidence
            }
        )
        return tuple(
            MonitoringAiSourceBinding(
                source_entry_id=source_entry_id,
                source_content_sha256=source_hash,
            )
            for source_entry_id, source_hash in pairs
        )

    @staticmethod
    def _locator_text(locator: Mapping[str, Any]) -> str:
        explicit = str(locator.get("locator") or "").strip()
        if explicit:
            return explicit[:1_000]
        return json.dumps(
            _json_safe(dict(locator)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )[:1_000]

    @staticmethod
    def _display_value(value: Any) -> str:
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(
                _json_safe(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return str(value)

    @staticmethod
    def _domain_role(domain: str) -> str:
        normalized = str(domain).strip().upper()
        if normalized == "CM":
            return "non_study_concomitant_medication_or_therapy"
        if normalized in _STUDY_TREATMENT_DOMAINS:
            return "study_treatment_exposure_or_adjustment"
        return "clinical_observation"

    @staticmethod
    def _business_key_prefix(run_id: str) -> str:
        return f"daily-run-ai:{run_id}:subject:"

    @classmethod
    def _business_key(cls, run_id: str, subject_id: str) -> str:
        return (
            cls._business_key_prefix(run_id)
            + content_sha256({"subject_id": subject_id})[:24]
        )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
