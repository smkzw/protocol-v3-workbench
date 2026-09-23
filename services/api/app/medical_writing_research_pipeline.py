"""Research pipeline orchestrator for medical-writing authoring.

Real-scenario order (user authority):

  indication + phase + drug type confirmed
    → CT.gov search (+ ChinaDrugTrials probe/intent, never invent rows)
    → competitor triage
    → download public Protocol → extract → translate critical anchors
    → round-1 deep analysis briefs bound to protocol modules
    → corpus / research ready
    → ONLY THEN design-guide recommendations

This module owns stage progression, progress projection, cancel/rerun hooks.
It reuses existing search / triage / prep / translation services; it does not
accept corpus-gate override as a happy-path unlock.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from packages.contracts.workbench_contracts import (
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    DurableJobRecord,
    MedicalWritingAuthoringJourney,
)

RESEARCH_PIPELINE_JOB_TYPE = "research_pipeline"
PIPELINE_SCHEMA = "medical_writing_research_pipeline_v1"

# Ordered stages with nominal progress anchors (monotonic).
STAGE_PROGRESS: dict[str, int] = {
    "queued": 0,
    "searching": 8,
    "triaging": 22,
    "awaiting_triage_confirm": 35,
    "preparing": 50,
    "awaiting_preparation_admission": 56,
    "awaiting_document_validation": 58,
    "awaiting_translation_scope": 64,
    "translating": 68,
    "analyzing_round1": 85,
    "awaiting_corpus_analysis": 86,
    "awaiting_corpus_admission": 90,
    "corpus_ready": 95,
    "analyzing_round2": 96,
    "round2_ready": 100,
    # Failure and cancellation preserve the last completed work percentage.
    # They are terminal outcomes, not successful work steps.
    "failed": 0,
    "cancelled": 0,
}

TERMINAL_STAGES = frozenset({"corpus_ready", "round2_ready", "failed", "cancelled"})
USER_ACTION_WAITING_STAGES = frozenset(
    {
        "awaiting_preparation_admission",
        "awaiting_document_validation",
        "awaiting_translation_scope",
        "awaiting_corpus_analysis",
    }
)

# Authoring-journal writes must not advance the journey revision while a
# search/triage/preparation/translation/analysis node owns a frozen input.
# The three document-processing waits and corpus admission are deliberate
# user-action pauses; they may legitimately require a journey/PICOS update.
AUTHORING_WRITE_ALLOWED_WAITING_STAGES = USER_ACTION_WAITING_STAGES | {
    "awaiting_corpus_admission",
}


def authoring_writes_blocked_by_pipeline(stage: str) -> bool:
    """Return whether a journey write would invalidate a frozen pipeline run.

    Empty stage means that no pipeline has been started. Successful terminal
    stages are safe because their frozen inputs are no longer being consumed.
    """

    normalized = str(stage or "").strip()
    if not normalized:
        return False
    # Cancelled/failed pipelines don't block authoring writes — they are
    # terminal states that no longer consume frozen inputs.
    if normalized in TERMINAL_STAGES:
        return False
    return normalized not in AUTHORING_WRITE_ALLOWED_WAITING_STAGES


def authoring_write_blocker_detail(stage: str) -> str:
    normalized = str(stage or "").strip() or "unknown"
    return (
        "研究流水线当前处于 "
        f"{normalized}；为保持检索/分诊快照与 AI 输入冻结，暂不能修改研究框架。"
        "请等待当前节点结束或先处理页面显示的用户等待项。"
    )

# ICH M11 anchors the corpus gate treats as "critical" for design-relevant
# corpus material (objectives/endpoints, eligibility, schedule, safety).
# Mirrors packages/api/app/medical_writing_corpus_readiness.py::_CRITICAL_ANCHORS
# so the pipeline's translation scope and its conservative round-1 unlock
# check use the same anchor universe as the real corpus gate.
CRITICAL_ANCHORS = frozenset({"objectives_endpoints", "eligibility", "schedule", "safety"})
ANCHOR_LABELS = {
    "objectives_endpoints": "研究目的与终点",
    "eligibility": "入选与排除标准",
    "schedule": "研究流程与访视",
    "safety": "安全性",
}

# Real terminal status values from WritingReferencePreparationBatch.status /
# WritingReferenceTranslationBatch.status (packages/contracts/workbench_contracts).
# "accepted"/"running" are the only non-terminal values for either model.
PREPARATION_BATCH_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "completed_with_review_required",
        "completed_with_manual_upload_required",
        "partial_failure",
        "failed",
    }
)
# A bounded preparation batch can also stop at a user-action boundary after
# the admitted stage has completed.  This is not a terminal batch outcome for
# the preparation worker (the batch is still resumable), but it is terminal
# for the parent ``preparing`` projection: status reads must be able to
# reconstruct the visible admission CTA after a worker restart or a late
# parent write.
PREPARATION_BATCH_RECONCILABLE_STATUSES = (
    PREPARATION_BATCH_TERMINAL_STATUSES | {"awaiting_stage_admission"}
)
TRANSLATION_BATCH_TERMINAL_STATUSES = frozenset(
    {"completed", "completed_with_blocked", "partial_failure", "failed"}
)

PROGRESS_SCHEMA_VERSION = "medical_writing_research_pipeline_progress_v1"
STAGE_PROGRESS_RANGES: dict[str, tuple[int, int]] = {
    "searching": (8, 22),
    "triaging": (22, 35),
    "preparing": (50, 58),
    "translating": (68, 85),
    "analyzing_round1": (85, 90),
    # Keep 100 exclusive to the successful round2_ready terminal stage.
    "analyzing_round2": (96, 99),
}
SEARCH_PROGRESS_STAGES = frozenset({"searching"})
TRIAGE_PROGRESS_STAGES = frozenset({"triaging", "awaiting_triage_confirm"})
PREPARATION_PROGRESS_STAGES = frozenset(
    {"preparing", "awaiting_preparation_admission", "awaiting_document_validation"}
)
TRANSLATION_PROGRESS_STAGES = frozenset(
    {"translating", "awaiting_translation_scope"}
)
ROUND1_PROGRESS_STAGES = frozenset(
    {"analyzing_round1", "awaiting_corpus_analysis", "awaiting_corpus_admission"}
)
ROUND2_PROGRESS_STAGES = frozenset({"analyzing_round2"})
TRANSLATION_TERMINAL_ITEM_STATUSES = frozenset(
    {"candidate_ready", "fidelity_blocked", "excluded", "failed_retryable", "failed_terminal"}
)
TRIAGE_CHILD_STALL_SECONDS = 1200.0
TRIAGE_CHILD_ABSOLUTE_CEILING_SECONDS = 7200.0

_PROGRESS_STAGE_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ("registry_search", SEARCH_PROGRESS_STAGES),
    ("competitor_triage", TRIAGE_PROGRESS_STAGES),
    ("document_preparation", PREPARATION_PROGRESS_STAGES),
    ("critical_anchor_translation", TRANSLATION_PROGRESS_STAGES),
    ("round1_corpus_analysis", ROUND1_PROGRESS_STAGES),
    ("round2_corpus_analysis", ROUND2_PROGRESS_STAGES),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).isoformat()


def _payload_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return vars(value)


def _percent(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round((completed / total) * 100)))


def _payload_text(payload: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty display value from a persisted payload."""
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _project_stage_percent(stage: str, child_percent: int, previous: int) -> int:
    start, end = STAGE_PROGRESS_RANGES.get(
        stage, (STAGE_PROGRESS.get(stage, previous), STAGE_PROGRESS.get(stage, previous))
    )
    projected = round(start + ((end - start) * max(0, min(100, child_percent)) / 100))
    return max(previous, projected, STAGE_PROGRESS.get(stage, previous))


def _progress_stage_group(stage: str) -> str:
    for group, stages in _PROGRESS_STAGE_GROUPS:
        if stage in stages:
            return group
    return ""


_STAGE_ORDER = list(STAGE_PROGRESS)


def _progress_payload(
    state: "ResearchPipelineState", detail: str
) -> DurableJobProgressPayload:
    """Build a real ``DurableJobProgressPayload`` from pipeline state.

    The contract requires ``percent`` as a 0.0-1.0 fraction (not 0-100) and
    ``step``/``step_total`` as integers (not the stage name) — using the
    pipeline's own percent/stage fields directly raises a pydantic
    ValidationError, which previously surfaced as a silent pipeline failure.
    """
    return DurableJobProgressPayload(
        phase=state.stage,
        percent=min(1.0, max(0.0, state.percent / 100.0)),
        step=_STAGE_ORDER.index(state.stage) if state.stage in _STAGE_ORDER else 0,
        step_total=len(_STAGE_ORDER),
        message=detail[:4000],
    )


@dataclass
class ResearchPipelineState:
    schema_version: str = PIPELINE_SCHEMA
    pipeline_id: str = ""
    project_id: str = ""
    job_id: str = ""
    stage: str = "queued"
    percent: int = 0
    progress_schema_version: str = PROGRESS_SCHEMA_VERSION
    child_phase: str = ""
    child_completed: int = 0
    child_total: int = 0
    child_percent: int = 0
    child_label: str = ""
    child_context: dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    eta_seconds: int | None = None
    cancel_requested: bool = False
    error_summary: str = ""
    snapshot_id: str = ""
    triage_run_id: str = ""
    prep_batch_id: str = ""
    document_admission_blockers: list[dict[str, Any]] = field(default_factory=list)
    document_admission_exclusions: list[dict[str, Any]] = field(default_factory=list)
    translation_batch_id: str = ""
    round1_brief_ids: list[str] = field(default_factory=list)
    round1_analysis_id: str = ""
    round1_analysis_output_hash: str = ""
    round1_ai_route: dict[str, Any] = field(default_factory=dict)
    round1_material_ready: bool = False
    round2_brief_ids: list[str] = field(default_factory=list)
    round2_material_ready: bool = False
    dual_registry: dict[str, Any] = field(default_factory=dict)
    last_resume_idempotency_key: str = ""
    last_resume_started_from_stage: str = ""
    last_resume_result_stage: str = ""
    last_resume_at: str = ""
    last_triage_retry_idempotency_key: str = ""
    last_triage_retry_job_id: str = ""
    last_triage_retry_at: str = ""
    # Monotonic write generation for the opaque journey projection.  The
    # authoring status endpoint and a durable worker can both hold a state
    # snapshot for a short time; this token lets the repository reject a late
    # stale snapshot instead of overwriting a newer continuation/job binding.
    write_generation: int = 0
    stage_started_at: str = ""
    updated_at: str = ""
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ResearchPipelineState":
        raw = dict(payload or {})
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in raw.items() if k in known}
        state = cls(**filtered)
        if not state.created_at:
            state.created_at = _iso()
        if not state.updated_at:
            state.updated_at = state.created_at
        state.percent = _normalize_terminal_percent(state)
        return state


def _normalize_terminal_percent(state: ResearchPipelineState) -> int:
    """Recover legacy failed/cancelled=100 from persisted work evidence."""
    percent = max(0, min(100, int(state.percent or 0)))
    if state.stage not in {"failed", "cancelled"} or percent < 100:
        return percent

    child_stage = {
        "registry_search": "searching",
        "competitor_triage": "triaging",
        "document_preparation": "preparing",
        "critical_anchor_translation": "translating",
        "round1_corpus_analysis": "analyzing_round1",
        "round2_corpus_analysis": "analyzing_round2",
    }.get(state.child_phase)
    if child_stage:
        return min(
            99,
            _project_stage_percent(
                child_stage,
                state.child_percent,
                STAGE_PROGRESS[child_stage],
            ),
        )
    if state.round1_analysis_id or state.round1_brief_ids:
        return STAGE_PROGRESS["awaiting_corpus_admission"]
    if state.translation_batch_id:
        return STAGE_PROGRESS["translating"]
    if state.prep_batch_id:
        return STAGE_PROGRESS["preparing"]
    if state.triage_run_id:
        return STAGE_PROGRESS["triaging"]
    if state.snapshot_id:
        return STAGE_PROGRESS["searching"]
    return 0


class ResearchPipelineConflictError(Exception):
    pass


class ResearchPipelineError(Exception):
    pass


class TriageWaitTimeoutError(ResearchPipelineError):
    """The child triage job stopped making business progress or hit its ceiling."""


@dataclass(frozen=True)
class PreparedDocumentAdmissionResult:
    admitted_count: int
    blocked_documents: tuple[dict[str, Any], ...] = ()
    excluded_documents: tuple[dict[str, Any], ...] = ()


def research_ready_for_design_recommendations(
    journey: MedicalWritingAuthoringJourney,
) -> tuple[bool, str]:
    """Hard gate: design packages must wait for real research corpus path.

    Override-only writing access does NOT unlock evidence-bound design
    packages. When the orchestrated research pipeline has produced a
    persisted, terminal-for-this-purpose stage, that stage is authoritative:

      - ``corpus_ready``: the full corpus gate is satisfied — unlocked.
      - ``awaiting_corpus_admission`` with ``round1_material_ready`` set: a
        conservative, round-1-only unlock. This requires triage to be
        finalized, at least one protocol extracted/validated, and at least
        one critical-anchor translation that passed fidelity — i.e. real
        round-1 research material exists — even though full medical
        admission / PICOS alignment may still be outstanding. This never
        activates from a corpus-gate override.
      - any other in-progress / failed / cancelled stage: locked.

    When no pipeline has run yet (or it left no stage), fall back to reading
    the corpus gate directly.
    """
    pipeline = None
    extras = getattr(journey, "research_pipeline", None)
    if isinstance(extras, dict):
        pipeline = extras
    elif extras is not None and hasattr(extras, "model_dump"):
        pipeline = extras.model_dump(mode="json")
    gate = journey.corpus_gate
    gate_ready = (
        gate is not None
        and str(getattr(gate, "readiness_status", "") or "") == "ready"
        and not bool(getattr(getattr(gate, "override", None), "active", False))
    )

    # Prefer explicit pipeline stage when present.
    if isinstance(pipeline, dict) and pipeline.get("stage"):
        # A project can retain an older orchestration projection while a
        # newer, independently audited corpus gate has already been bound to
        # a different locked snapshot.  The older projection must not keep
        # blocking current-snapshot design recommendations (and must never be
        # resumed implicitly).  Same-snapshot in-progress work remains
        # authoritative and continues to fail closed below.
        pipeline_snapshot_id = str(pipeline.get("snapshot_id") or "")
        gate_snapshot_id = str(getattr(gate, "bound_snapshot_id", "") or "")
        if (
            gate_ready
            and pipeline_snapshot_id
            and gate_snapshot_id
            and pipeline_snapshot_id != gate_snapshot_id
        ):
            return True, "research_pipeline_stale_scope_but_current_corpus_ready"
        stage = str(pipeline.get("stage") or "")
        if stage in {"corpus_ready", "analyzing_round2", "round2_ready"}:
            return True, (
                "research_pipeline_round2_ready"
                if stage == "round2_ready"
                else "research_pipeline_corpus_ready"
            )
        # Soft-terminal pause: if the corpus gate became ready after medical
        # admission / PICOS alignment, unlock as full corpus_ready even before
        # the persisted stage is rewritten by status()/promote.
        if stage == "awaiting_corpus_admission":
            if gate_ready:
                return True, "research_pipeline_corpus_ready"
            if bool(pipeline.get("round1_material_ready")):
                return True, "research_pipeline_round1_material_ready"
            return False, "research_pipeline_awaiting_corpus_admission"
        if stage in TERMINAL_STAGES and stage not in {
            "corpus_ready",
            "round2_ready",
        }:
            # Plan A (requirements-v2 R2): a zero-document project's public
            # search snapshot IS its structured evidence — the preserved
            # snapshot means the structured analysis completed, so
            # evidence-bound design recommendations bind to it instead of
            # staying permanently locked (modern ClinicalTrials.gov records
            # ship no Protocol documents).
            if str(pipeline.get("snapshot_id") or ""):
                return True, "research_pipeline_structured_evidence_only"
            return False, f"research_pipeline_{stage}"
        return False, f"research_pipeline_in_progress:{stage or 'queued'}"

    if gate is None:
        return False, "corpus_gate_missing"
    if bool(getattr(getattr(gate, "override", None), "active", False)):
        return False, "corpus_override_does_not_unlock_design_recommendations"
    if gate_ready:
        return True, "corpus_gate_ready"
    missing = list(getattr(gate, "missing_requirements", None) or [])
    return False, "corpus_not_ready:" + ",".join(missing[:5])


class MedicalWritingResearchPipelineService:
    """Persists pipeline projection on the authoring journey and drives stages."""

    def __init__(
        self,
        *,
        journey_service: Any,
        discovery_service: Any,
        triage_service: Any,
        preparation_batch_service: Any,
        translation_batch_service: Any,
        corpus_readiness_service: Any,
        china_client_factory: Callable[[], Any],
        durable_store: Any | None = None,
        durable_worker: Any | None = None,
        triage_provider_factory: Callable[[], Any] | None = None,
        corpus_analysis_ai_service: Any | None = None,
    ) -> None:
        self.journey_service = journey_service
        self.discovery_service = discovery_service
        self.triage_service = triage_service
        self.preparation_batch_service = preparation_batch_service
        self.translation_batch_service = translation_batch_service
        self.corpus_readiness_service = corpus_readiness_service
        self.china_client_factory = china_client_factory
        self.durable_store = durable_store
        self.durable_worker = durable_worker
        self.triage_provider_factory = triage_provider_factory
        if corpus_analysis_ai_service is None:
            from .medical_writing_corpus_analysis_ai import (
                MedicalWritingCorpusAnalysisAiService,
            )

            corpus_analysis_ai_service = MedicalWritingCorpusAnalysisAiService(
                self.triage_service.repository
            )
        self.corpus_analysis_ai_service = corpus_analysis_ai_service
        self._lock = threading.RLock()
        # ``resume_waiting`` deliberately releases ``_lock`` while it runs
        # download/OCR/translation work.  Keep a small in-process lease so a
        # concurrent status request cannot mistake that legitimate
        # ``preparing`` window for a crashed/stale pipeline and overwrite its
        # state.  The lease is process-local on purpose: after a process
        # restart it is absent and the persisted batch evidence below is used
        # for deterministic reconciliation instead of trusting an old marker.
        self._active_resume_projects: set[str] = set()
        if durable_worker is not None:
            durable_worker.register_executor(ResearchPipelineDurableExecutor(self))

    def get_state(self, project_id: str) -> ResearchPipelineState:
        journey = self.journey_service.get(project_id)
        raw = getattr(journey, "research_pipeline", None)
        if raw is None or (isinstance(raw, dict) and not raw):
            # No pipeline has been started — return an empty-stage state so
            # the frontend banner stays hidden instead of showing a
            # perpetual "queued 0%" spinner for a pipeline that was never
            # created.
            return ResearchPipelineState(project_id=project_id, stage="")
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        state = ResearchPipelineState.from_dict(dict(raw or {}))
        state.project_id = project_id
        return state

    def _persist(self, project_id: str, state: ResearchPipelineState) -> ResearchPipelineState:
        # Every persistence attempt advances a local generation.  The journey
        # repository performs the authoritative compare-and-preserve check;
        # equal/older generations are treated as late stale writes and return
        # the current projection unchanged.
        state.write_generation = max(0, int(state.write_generation or 0)) + 1
        state.updated_at = _iso()
        state.percent = _normalize_terminal_percent(state)
        state.percent = max(state.percent, STAGE_PROGRESS.get(state.stage, state.percent))
        # Journey service extension point — store as opaque dict on journey row.
        saver = getattr(self.journey_service, "save_research_pipeline", None)
        if callable(saver):
            saver(project_id, state.as_dict())
            return self.get_state(project_id)
        # Fallback: attach on in-memory journey object when saver not yet wired.
        journey = self.journey_service.get(project_id)
        try:
            object.__setattr__(journey, "research_pipeline", state.as_dict())
        except Exception:
            journey.__dict__["research_pipeline"] = state.as_dict()
        return state

    def _set_stage(
        self,
        state: ResearchPipelineState,
        stage: str,
        *,
        detail: str = "",
        eta_seconds: int | None = None,
        error: str = "",
    ) -> ResearchPipelineState:
        previous_stage = state.stage
        previous_group = _progress_stage_group(previous_stage)
        next_group = _progress_stage_group(stage)
        stage_changed = stage != previous_stage

        state.stage = stage
        state.detail = detail
        state.eta_seconds = eta_seconds
        state.stage_started_at = _iso()
        if stage_changed:
            # A pipeline_id is one progress attempt. Stage transitions,
            # including failure/cancellation and same-attempt retries, may
            # never move its total percentage backwards. A new start creates
            # a new state/pipeline_id at zero.
            state.percent = max(
                state.percent, STAGE_PROGRESS.get(stage, state.percent)
            )
            # Preserve the last real child evidence on failure/cancellation,
            # but never project a prior phase's label/counts into a new phase.
            if (
                stage not in {"failed", "cancelled"}
                and previous_group != next_group
            ):
                state.progress_schema_version = PROGRESS_SCHEMA_VERSION
                state.child_phase = ""
                state.child_completed = 0
                state.child_total = 0
                state.child_percent = 0
                state.child_label = ""
                state.child_context = {}
        else:
            state.percent = max(
                state.percent, STAGE_PROGRESS.get(stage, state.percent)
            )
        # Always assign so promoting out of a failed/soft-terminal stage
        # can clear a stale error_summary (e.g. corpus_not_ready:…).
        state.error_summary = error
        if error:
            # A waiting/failed projection must not keep presenting the last
            # child checkpoint as if work were still running. Durable jobs and
            # audit rows retain the history; the user-facing banner shows the
            # actionable terminal/waiting message.
            state.child_phase = ""
            state.child_completed = 0
            state.child_total = 0
            state.child_percent = 0
            state.child_label = ""
            state.child_context = {}
        return state

    def start(
        self,
        project_id: str,
        *,
        actor: str,
        idempotency_key: str,
        auto_confirm_triage: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Enqueue or resume a research pipeline for the project."""
        with self._lock:
            journey = self.journey_service.get(project_id)
            framing = journey.framing
            if framing is None or not framing.creation_minimum_complete():
                raise ResearchPipelineError(
                    "须先确认试验药物、适应症、研究分期后再启动研究流水线"
                )
            profile = getattr(framing, "product_profile", None)
            tech_raw = getattr(profile, "technology_type", None) if profile is not None else None
            tech = str(tech_raw or "").strip()
            routes = list(getattr(profile, "administration_routes", None) or [])
            routes = [str(r).strip() for r in routes if str(r).strip()]
            tech_known = bool(tech) and tech.lower() not in {"unknown", "none", "null"}
            profile_notes = []
            if tech_known:
                profile_notes.append(f"药品种类={tech}")
            if routes:
                profile_notes.append(f"给药途径={'/'.join(routes[:4])}")
            tech_note = (
                "；".join(profile_notes)
                if profile_notes
                else "产品画像待公开证据、IB或用户补充；先按最小项目信息检索"
            )

            existing = self.get_state(project_id)
            # Human-action waiting stages are soft-terminal for the durable
            # job. They resume through the existing continuation endpoint
            # after the user resolves the blocker.
            soft_terminal = existing.stage in {
                "awaiting_document_validation",
                "awaiting_translation_scope",
                "awaiting_corpus_analysis",
                "awaiting_corpus_admission",
            }
            if (
                existing.stage
                and existing.stage not in TERMINAL_STAGES
                and not soft_terminal
                and existing.pipeline_id
                and not force
            ):
                return {
                    "pipeline": existing.as_dict(),
                    "started": False,
                    "reason": "already_running",
                }
            if soft_terminal and not force:
                return {
                    "pipeline": existing.as_dict(),
                    "started": False,
                    "reason": existing.stage,
                }

            try:
                round1_ai_route = (
                    self.corpus_analysis_ai_service.freeze_active_route()
                )
            except Exception as exc:  # noqa: BLE001
                raise ResearchPipelineError(
                    "产品独立AI未达到可用状态，无法启动研究流水线："
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            # Force/re-run must not leave prior research_pipeline jobs racing
            # on the same journey.research_pipeline row (lease-lost chaos).
            if force and self.durable_store is not None:
                try:
                    for job in self.durable_store.list_by_project(project_id):
                        if (
                            getattr(job, "job_type", "") == RESEARCH_PIPELINE_JOB_TYPE
                            and getattr(job, "status", "")
                            in {"queued", "running", "retry_wait"}
                        ):
                            try:
                                self.durable_store.cancel(project_id, job.job_id)
                            except Exception:
                                pass
                except Exception:
                    pass

            pipeline_id = "mwpipe_" + hashlib.sha256(
                f"{project_id}|{idempotency_key}".encode()
            ).hexdigest()[:20]
            state = ResearchPipelineState(
                pipeline_id=pipeline_id,
                project_id=project_id,
                stage="queued",
                percent=0,
                detail=f"研究流水线已排队。{tech_note}",
                round1_ai_route=dict(round1_ai_route),
                created_at=_iso(),
                updated_at=_iso(),
            )
            state = self._persist(project_id, state)

            if self.durable_store is None:
                # Synchronous fallback for tests / early wiring — still real stages.
                return self._run_inline(
                    project_id,
                    state,
                    actor=actor,
                    auto_confirm_triage=auto_confirm_triage,
                )

            payload = {
                "pipeline_id": pipeline_id,
                "actor": actor,
                "auto_confirm_triage": bool(auto_confirm_triage),
                "corpus_analysis_ai_route": dict(round1_ai_route),
            }
            request_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            create_req = DurableJobCreateRequest(
                project_id=project_id,
                job_type=RESEARCH_PIPELINE_JOB_TYPE,
                # Include pipeline_id so force/re-runs are not blocked by the
                # first completed job's business_key (create_or_reuse conflicts
                # when the same key is reused with a different request_hash).
                business_key=f"research-pipeline:{project_id}:{pipeline_id}",
                request_hash=request_hash,
                input_hash=request_hash[:64],
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_by=actor or "research_pipeline",
                max_attempts=3,
                provider="workbench",
                model="research_pipeline_orchestrator",
            )
            start_resp = self.durable_store.create_or_reuse(create_req)
            state.job_id = start_resp.job_id
            state = self._persist(project_id, state)
            if self.durable_worker is not None:
                self.durable_worker.wake(project_id, start_resp.job_id)
            return {
                "pipeline": state.as_dict(),
                "job_id": start_resp.job_id,
                "started": True,
            }

    def cancel(self, project_id: str, *, actor: str) -> ResearchPipelineState:
        state = self.get_state(project_id)
        if state.stage in TERMINAL_STAGES:
            return state
        state.cancel_requested = True
        state = self._set_stage(
            state, "cancelled", detail=f"已由 {actor} 取消研究流水线"
        )
        return self._persist(project_id, state)

    def _reconcile_stale_preparation_state(
        self, project_id: str, state: ResearchPipelineState
    ) -> ResearchPipelineState:
        """Reconcile a synchronous downstream resume without clobbering it.

        A user ``resume`` call owns the same immutable preparation batch as the
        durable pipeline.  If an unexpected exception escapes that call, the
        old implementation could leave the persisted parent at ``preparing``
        even though the batch and its durable job were already terminal.  A
        read of the status endpoint is an appropriate reconciliation boundary:
        it never retries OCR/download/translation.  While the in-process
        resume lease is held, status must not write at all: the request is
        still legitimately processing the already-admitted batch.  After a
        restart, a partial-success batch is converted to an explicit waiting
        state from its durable counts; only a batch with no reusable evidence
        remains terminally failed.
        """
        if (
            state.stage != "preparing"
            or not state.prep_batch_id
            or state.translation_batch_id
        ):
            return state
        if project_id in getattr(self, "_active_resume_projects", set()):
            return state
        getter = getattr(self.preparation_batch_service, "get", None)
        if not callable(getter):
            return state
        try:
            batch = getter(project_id, state.prep_batch_id)
        except Exception:
            return state
        batch_payload = _payload_dict(batch)
        batch_status = str(batch_payload.get("status") or "")
        if batch_status not in PREPARATION_BATCH_RECONCILABLE_STATUSES:
            return state
        durable_store = getattr(self, "durable_store", None)
        if durable_store is not None and state.job_id:
            try:
                job = durable_store.get(project_id, state.job_id)
            except Exception:
                job = None
            if job is not None and str(getattr(job, "status", "")) in {
                "queued",
                "running",
                "retry_wait",
            }:
                return state
        failed_count = int(batch_payload.get("failed_count") or 0)
        deferred_count = int(batch_payload.get("deferred_item_count") or 0)
        prepared_count = int(batch_payload.get("prepared_count") or 0)
        completed_count = int(batch_payload.get("completed_document_count") or 0)
        if batch_status == "awaiting_stage_admission" and deferred_count > 0:
            return self._persist(
                project_id,
                self._set_stage(
                    state,
                    "awaiting_preparation_admission",
                    detail=(
                        "原文准备批次已完成当前阶段；"
                        f"已保留 {prepared_count} 份可用原文，仍有 "
                        f"{deferred_count} 份公开Protocol待下一阶段准入。"
                        "已完成项不会重复下载或OCR。"
                    ),
                    error="preparation_stage_admission_required",
                ),
            )
        if batch_status == "partial_failure" and (
            deferred_count > 0 or prepared_count > 0 or completed_count > failed_count
        ):
            if deferred_count > 0:
                stage = "awaiting_preparation_admission"
                detail = (
                    "原文准备批次已完成当前阶段，但包含可复用资料和失败文件；"
                    f"已保留 {prepared_count} 份可用原文，失败 {failed_count} 份，"
                    f"仍有 {deferred_count} 份公开Protocol待下一阶段准入。"
                    "失败文件不会被静默纳入，已完成项不会重复下载或OCR。"
                )
                error = "preparation_partial_failure_stage_admission_required"
            else:
                stage = "awaiting_translation_scope"
                detail = (
                    "原文准备批次已完成，但包含失败文件；"
                    f"已保留 {prepared_count} 份可用原文，失败 {failed_count} 份。"
                    "请从已完成原文继续并复核失败文件，系统不会重复下载或OCR。"
                )
                error = "preparation_partial_failure_review_required"
            return self._persist(
                project_id,
                self._set_stage(
                    state,
                    stage,
                    detail=detail,
                    error=error,
                ),
            )
        detail = (
            "原文准备批次已结束，但研究流水线未能进入下一节点；"
            f"已保留已完成资料（批次状态：{batch_status}，失败 {failed_count} 份）。"
            "请从已完成原文继续，系统不会重复下载或OCR。"
        )
        return self._persist(
            project_id,
            self._set_stage(
                state,
                "failed",
                detail=detail,
                error=f"stale_preparation_state:{batch_status}",
            ),
        )

    def _reconcile_completed_round1_analysis(
        self, project_id: str, state: ResearchPipelineState
    ) -> ResearchPipelineState:
        """Bind an orphaned immutable round-1 artifact after a parent race.

        The parent pipeline projection and the corpus-analysis artifact live
        in separate stores.  A status refresh can win a generation race while
        the analysis provider is returning, leaving the immutable ``mwca_*``
        row completed but the parent still showing ``translating`` with no
        analysis identity.  Recovery is deliberately read-only with respect
        to the corpus store: it matches the exact pipeline, snapshot, and
        frozen route, then persists only the missing parent projection.  No
        provider, translation batch, OCR, or preparation work is retried.
        """
        if state.stage not in {
            "translating",
            "analyzing_round1",
            "awaiting_corpus_analysis",
            "awaiting_corpus_admission",
            "failed",
        }:
            return state
        if not state.pipeline_id or not state.snapshot_id or not state.round1_ai_route:
            return state
        if (
            state.round1_analysis_id
            and state.round1_analysis_output_hash
            and state.round1_brief_ids
        ):
            return state

        finder = getattr(self.corpus_analysis_ai_service, "find_completed_analysis", None)
        if not callable(finder):
            return state
        route_identity_hash = str(
            (state.round1_ai_route or {}).get("identity_hash") or ""
        ).strip()
        try:
            result = finder(
                project_id,
                pipeline_id=state.pipeline_id,
                snapshot_id=state.snapshot_id,
                route_identity_hash=route_identity_hash,
            )
        except Exception:
            # Evidence-store outages stay fail-closed; the normal status path
            # will retry the read on a later request without changing state.
            return state
        if not isinstance(result, dict):
            return state

        analysis_id = str(result.get("analysis_id") or "").strip()
        output_hash = str(result.get("output_hash") or "").strip().lower()
        brief_ids = [
            str(item).strip()
            for item in (result.get("evidence_summary_ids") or [])
            if str(item).strip()
        ][:50]
        if (
            result.get("status") != "completed"
            or not analysis_id
            or not output_hash
            or not brief_ids
            or str(result.get("pipeline_id") or "") != state.pipeline_id
            or str(result.get("snapshot_id") or "") != state.snapshot_id
        ):
            return state

        with self._lock:
            current = self.get_state(project_id)
            if current.pipeline_id != state.pipeline_id or current.snapshot_id != state.snapshot_id:
                return current
            if (
                current.round1_analysis_id
                and current.round1_analysis_output_hash
                and current.round1_brief_ids
            ):
                return current
            current.round1_analysis_id = analysis_id
            current.round1_analysis_output_hash = output_hash
            current.round1_brief_ids = brief_ids
            current.round1_material_ready = False
            if current.stage in {
                "translating",
                "analyzing_round1",
                "awaiting_corpus_analysis",
                "failed",
            }:
                current = self._set_stage(
                    current,
                    "awaiting_corpus_admission",
                    detail=(
                        "第一轮语料分析产物已从不可变证据库恢复绑定（"
                        f"{analysis_id}）；未重新调用独立AI。"
                        "正在重新核验语料门与设计推荐条件。"
                    ),
                    eta_seconds=None,
                    error="corpus_not_ready:round1_analysis_recovered",
                )
            return self._persist(project_id, current)

    def _recalculate_gate_after_round1_recovery(
        self, project_id: str, state: ResearchPipelineState
    ) -> None:
        """Materialize the full corpus-gate projection after a recovery bind.

        ``round1_material_ready`` is a deliberately conservative early design
        unlock; it is not the full corpus gate.  When a parent projection was
        lost after analysis completed, the gate can still be the initial
        stale/empty object, which hides the real medical-admission and PICOS
        gaps from the user.  Recalculate once the exact round-1 identity is
        bound.  The readiness service is deterministic and idempotent; it
        never invokes OCR, translation, or an LLM.  A transient conflict or
        unavailable evidence store remains fail-closed and is retried by the
        next status read.
        """
        if not (
            state.round1_analysis_id
            and state.round1_analysis_output_hash
            and state.round1_brief_ids
        ):
            return
        try:
            journey = self.journey_service.get(project_id)
            gate = getattr(journey, "corpus_gate", None)
            if gate is None or not bool(getattr(gate, "stale", False)):
                return
        except Exception:
            return
        recalculate = getattr(
            getattr(self, "corpus_readiness_service", None), "recalculate", None
        )
        if not callable(recalculate):
            return
        try:
            recalculate(project_id, actor="research_pipeline_reconciliation")
        except Exception:
            # Do not turn a read/status request into a false success or a
            # second downstream run.  The next status read can retry this
            # deterministic projection after the conflict/evidence store is
            # available again.
            return

    def status(self, project_id: str) -> dict[str, Any]:
        state = self.reconcile_review_ready_triage(project_id)
        state = self._reconcile_stale_preparation_state(project_id, state)
        state = self._reconcile_completed_round1_analysis(project_id, state)
        self._recalculate_gate_after_round1_recovery(project_id, state)
        journey = self.journey_service.get(project_id)
        read_only_degraded = False
        readiness_detail = ""
        # Promote soft-terminal pause → corpus_ready once the gate is truly ready
        # (admission + PICOS completed after the pipeline paused).
        if state.stage == "awaiting_corpus_admission":
            gate = journey.corpus_gate
            gate_ready = (
                gate is not None
                and str(getattr(gate, "readiness_status", "") or "") == "ready"
                and not bool(getattr(getattr(gate, "override", None), "active", False))
            )
            if gate_ready:
                state = self._set_stage(
                    state,
                    "corpus_ready",
                    detail="语料已就绪（医学准入与PICOS对齐完成后晋升），可生成证据化研究设计推荐。",
                    error="",
                )
                state = self._persist(project_id, state)
                self._notify_corpus_ready(project_id)
                journey = self.journey_service.get(project_id)
            else:
                material_ready, _material_detail = self._round1_material_ready(
                    project_id, journey, state
                )
                readiness_detail = _material_detail
                evidence_unavailable = _material_detail.startswith(
                    "evidence_unavailable:"
                )
                if evidence_unavailable:
                    # A status read must never turn missing/incomplete fixture
                    # dependencies into a durable business downgrade.  Return
                    # a transient fail-closed projection instead; the persisted
                    # readiness flag remains untouched until its evidence can
                    # be read authoritatively.
                    read_only_degraded = True
                    state = copy.deepcopy(state)
                    state.round1_material_ready = False
                    state.detail = (
                        "研究材料依赖证据当前不可读取，设计推荐已暂时锁定；"
                        "恢复依赖证据后将重新核验。"
                    )
                else:
                    detail_changed = False
                    if material_ready and (
                        "设计推荐仍锁定" in str(state.detail or "")
                        or "第一轮研究材料尚未齐备" in str(state.detail or "")
                    ):
                        state.detail = (
                            "第一轮竞品语料分析已完成，证据化研究设计推荐已开放。"
                            "完整医学准入与PICOS对齐仍将在后续语料门中完成。"
                        )
                        detail_changed = True
                    if material_ready != state.round1_material_ready or detail_changed:
                        state.round1_material_ready = material_ready
                        state = self._persist(project_id, state)
                        journey = self.journey_service.get(project_id)
        elif state.stage == "corpus_ready" and str(
            getattr(state, "error_summary", "") or ""
        ).startswith("corpus_not_ready"):
            # Clear stale blocker left from the pre-admission pause.
            state = self._set_stage(
                state,
                "corpus_ready",
                detail=state.detail
                or "语料已就绪，可生成证据化研究设计推荐。",
                error="",
            )
            state = self._persist(project_id, state)
            journey = self.journey_service.get(project_id)
        state = self._refresh_progress_projection(
            project_id, state, persist=not read_only_degraded
        )
        readiness_journey = journey
        if read_only_degraded:
            # Use the transient fail-closed state for the unlock decision while
            # keeping the persisted journey and its immutable event history
            # unchanged.
            readiness_journey = copy.deepcopy(journey)
            try:
                setattr(readiness_journey, "research_pipeline", state.as_dict())
            except Exception:
                readiness_journey = journey
        ready, reason = research_ready_for_design_recommendations(
            readiness_journey
        )
        if read_only_degraded:
            reason = "research_pipeline_evidence_unavailable"
        triage_progress = self._triage_progress(project_id, state)
        triage_retryable = (
            state.stage == "failed"
            and bool(state.triage_run_id)
            and not bool(state.prep_batch_id)
            and (
                "分诊" in str(state.error_summary or "")
                or str(state.error_summary or "").startswith(
                    "competitor_triage_"
                )
            )
            # A stale run is the explicit fail-closed representation of a
            # partially completed child whose remaining chunks may be resumed.
            # Keep the visible retry action available for that state; hiding
            # it would leave the user with an error that says "可重试" but no
            # bounded, idempotent recovery path.
            and triage_progress.get("status") not in {"review_ready", "confirmed"}
        )
        pipeline_retryable = (
            state.stage == "failed"
            and bool(state.prep_batch_id)
            and not triage_retryable
        )
        return {
            "pipeline": state.as_dict(),
            "design_recommendations_unlocked": ready,
            "unlock_reason": reason,
            "triage_progress": triage_progress,
            "triage_retryable": triage_retryable,
            "pipeline_retryable": pipeline_retryable,
            "read_only_degraded": read_only_degraded,
            "readiness_detail": readiness_detail,
        }

    def _triage_progress(
        self, project_id: str, state: ResearchPipelineState
    ) -> dict[str, Any]:
        """Return a compact user-facing projection for the bound triage run."""
        if not state.triage_run_id:
            return {}
        repository = getattr(self.triage_service, "repository", None)
        get_run = getattr(repository, "triage_run", None)
        if not callable(get_run):
            return {}
        run = get_run(project_id, state.triage_run_id)
        if run is None:
            return {}
        chunks = list(getattr(run, "chunks", None) or [])
        status_counts: dict[str, int] = {}
        for chunk in chunks:
            chunk_status = str(
                getattr(getattr(chunk, "status", ""), "value", None)
                or getattr(chunk, "status", "")
            )
            status_counts[chunk_status] = status_counts.get(chunk_status, 0) + 1
        completed = status_counts.get("succeeded", 0)
        total = len(chunks)
        status = str(
            getattr(getattr(run, "status", ""), "value", None)
            or getattr(run, "status", "")
        )
        active_chunk = next(
            (
                chunk
                for chunk in chunks
                if str(
                    getattr(getattr(chunk, "status", ""), "value", None)
                    or getattr(chunk, "status", "")
                )
                == "running"
            ),
            None,
        ) or next(
            (
                chunk
                for chunk in chunks
                if str(
                    getattr(getattr(chunk, "status", ""), "value", None)
                    or getattr(chunk, "status", "")
                )
                == "pending"
            ),
            None,
        )
        active_results = list(getattr(active_chunk, "results", None) or [])
        current_study = _payload_text(
            _payload_dict(active_results[0]) if active_results else {},
            "nct_id",
            "study_id",
        )
        current_chunk_id = str(getattr(active_chunk, "chunk_id", "") or "")
        active_index = next(
            (index for index, chunk in enumerate(chunks, start=1) if chunk is active_chunk),
            0,
        )
        if status in {"review_ready", "confirmed"}:
            label = "竞品分诊已完成"
        elif active_chunk is not None:
            # 消息卫生（T17 P1）：内部分块ID（ct_chunk_*）不进入用户界面；
            # 仅展示人类可读的研究名称，缺失时用批次序号。
            object_label = f" · {current_study or f'第 {active_index} 批'}"
            label = f"正在处理竞品文献 {active_index}/{total}{object_label}"
        else:
            label = "正在等待竞品分诊结果"
        return {
            "run_id": str(getattr(run, "run_id", "") or ""),
            "snapshot_id": str(getattr(run, "snapshot_id", "") or ""),
            "status": status,
            "completed_chunks": completed,
            "total_chunks": total,
            "pending_chunks": status_counts.get("pending", 0),
            "running_chunks": status_counts.get("running", 0),
            "failed_chunks": status_counts.get("failed", 0),
            "percent": _percent(completed, total),
            "label": label,
            "context": {
                "unit_type": "chunk",
                "current_chunk_id": current_chunk_id,
                "current_study_id": current_study,
                "current_chunk_index": active_index,
                "chunk_total": total,
                "substep_percent": 0 if active_chunk is not None else _percent(completed, total),
            },
        }

    @staticmethod
    def _apply_child_progress(
        state: ResearchPipelineState,
        *,
        phase: str,
        completed: int,
        total: int,
        label: str,
        child_percent: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> ResearchPipelineState:
        completed = max(0, int(completed or 0))
        total = max(0, int(total or 0))
        if total:
            completed = min(completed, total)
        child_percent = (
            _percent(completed, total)
            if child_percent is None
            else max(0, min(100, int(child_percent)))
        )
        if state.child_phase == phase:
            completed = max(state.child_completed, completed)
            child_percent = max(state.child_percent, child_percent)
        state.progress_schema_version = PROGRESS_SCHEMA_VERSION
        state.child_phase = phase
        state.child_completed = completed
        state.child_total = total
        state.child_percent = child_percent
        state.child_label = str(label or "")[:4000]
        state.child_context = dict(context or {})
        state.percent = _project_stage_percent(
            state.stage, child_percent, state.percent
        )
        return state

    def _refresh_progress_projection(
        self,
        project_id: str,
        state: ResearchPipelineState,
        *,
        persist: bool = True,
    ) -> ResearchPipelineState:
        """Refresh the child projection from durable child records.

        ``persist=False`` is used by a read-only degraded status response when
        a required evidence store cannot be read.  It prevents a transient
        fixture/runtime outage from becoming a durable pipeline event.
        """
        before = (
            state.percent,
            state.progress_schema_version,
            state.child_phase,
            state.child_completed,
            state.child_total,
            state.child_percent,
            state.child_label,
            json.dumps(state.child_context, sort_keys=True, ensure_ascii=False),
        )

        if (
            state.stage in TRIAGE_PROGRESS_STAGES
            or (
                state.stage == "failed"
                and state.triage_run_id
                and not state.prep_batch_id
                and not state.translation_batch_id
            )
        ) and state.triage_run_id:
            progress = self._triage_progress(project_id, state)
            if progress:
                self._apply_child_progress(
                    state,
                    phase="competitor_triage",
                    completed=progress["completed_chunks"],
                    total=progress["total_chunks"],
                    child_percent=progress["percent"],
                    label=progress["label"],
                    context=progress.get("context"),
                )
        elif (
            state.stage in PREPARATION_PROGRESS_STAGES
            or (state.stage == "failed" and state.prep_batch_id and not state.translation_batch_id)
        ) and state.prep_batch_id:
            getter = getattr(self.preparation_batch_service, "get", None)
            if callable(getter):
                try:
                    batch = getter(project_id, state.prep_batch_id)
                    projection = self._preparation_progress_projection(batch)
                    self._apply_child_progress(state, **projection)
                except Exception:
                    pass
        elif (
            state.stage in TRANSLATION_PROGRESS_STAGES
            or (state.stage == "failed" and state.translation_batch_id)
        ) and state.translation_batch_id:
            translation_service = getattr(self, "translation_batch_service", None)
            getter = getattr(translation_service, "get", None)
            if callable(getter):
                try:
                    batch = getter(project_id, state.translation_batch_id)
                    projection = self._translation_progress_projection(batch)
                    self._apply_child_progress(state, **projection)
                except Exception:
                    pass
        elif state.stage in ROUND1_PROGRESS_STAGES:
            completed = 4 if state.round1_analysis_id and state.round1_brief_ids else 0
            label = (
                "第一轮语料分析已完成"
                if completed
                else "正在收集第一轮语料分析的准入来源"
            )
            # Do not overwrite a live 4-step analysis checkpoint during a
            # status refresh. Legacy 0/1 projections are upgraded in place.
            if not (
                state.child_phase == "round1_corpus_analysis"
                and state.child_total == 4
                and not completed
            ):
                self._apply_child_progress(
                    state,
                    phase="round1_corpus_analysis",
                    completed=completed,
                    total=4,
                    label=label,
                    context={"analysis_artifact_ready": bool(completed)},
                )

        after = (
            state.percent,
            state.progress_schema_version,
            state.child_phase,
            state.child_completed,
            state.child_total,
            state.child_percent,
            state.child_label,
            json.dumps(state.child_context, sort_keys=True, ensure_ascii=False),
        )
        if after != before and persist:
            return self._persist(project_id, state)
        return state

    def error_summary_indicates_triage_failure(self, error_summary: str) -> bool:
        """Whether a failed pipeline state is recoverable from the triage node.

        Kept inclusive on purpose: every shape below was once a real 409
        deadlock reported from a test round. R12 added "竞品分诊仅部分完成" —
        honest partial_failed runs (terminal status now persisted) must stay
        recoverable instead of being rejected as a non-triage failure.
        """
        summary = str(error_summary or "")
        return (
            "分诊超时" in summary
            or "分诊任务结束为 failed" in summary
            or "分诊任务结束为 cancelled" in summary
            or "竞品分诊仅部分完成" in summary
            or summary.startswith("competitor_triage_")
            or "CompetitorTriageError" in summary
            or "frozen durable route" in summary
            or "provider identity" in summary
        )

    def retry_triage(
        self,
        project_id: str,
        *,
        actor: str,
        idempotency_key: str,
        expected_pipeline_id: str = "",
        expected_triage_run_id: str = "",
    ) -> dict[str, Any]:
        """Resume only the frozen competitor-triage child of a failed parent.

        Search, snapshot binding, successful chunk results, and downstream
        preparation are intentionally untouched. Repeated calls with the same
        idempotency key return the persisted transition.
        """
        from packages.contracts.workbench_contracts import (
            CompetitorTriageChunkStatus,
            CompetitorTriageRetryRequest,
            CompetitorTriageRunStatus,
        )

        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("重试竞品分诊必须提供 idempotency_key")
        with self._lock:
            state = self.get_state(project_id)
            if expected_pipeline_id and state.pipeline_id != expected_pipeline_id:
                raise ResearchPipelineConflictError(
                    "研究流水线已更新，请刷新当前状态后重试"
                )
            if (
                expected_triage_run_id
                and state.triage_run_id != expected_triage_run_id
            ):
                raise ResearchPipelineConflictError(
                    "竞品分诊批次已更新，请刷新当前状态后重试"
                )
            if state.last_triage_retry_idempotency_key == key:
                return {
                    "pipeline": state.as_dict(),
                    "triage_job_id": state.last_triage_retry_job_id,
                    "reused": True,
                }
            if state.stage not in {"failed", "triaging"}:
                raise ResearchPipelineConflictError(
                    f"当前阶段 {state.stage or '未启动'} 不允许从分诊节点恢复"
                )
            if state.stage == "failed":
                error_summary = str(state.error_summary or "")
                if not self.error_summary_indicates_triage_failure(error_summary):
                    raise ResearchPipelineConflictError(
                        "当前失败不属于竞品分诊节点，不能从分诊入口恢复"
                    )
            if not state.pipeline_id or not state.snapshot_id or not state.triage_run_id:
                raise ResearchPipelineError(
                    "当前流水线缺少原检索快照或分诊批次，不能无损恢复"
                )
            if state.prep_batch_id:
                raise ResearchPipelineConflictError(
                    "原文准备已经开始，不能回退到竞品分诊节点"
                )

            repository = getattr(self.triage_service, "repository", None)
            get_run = getattr(repository, "triage_run", None)
            run = get_run(project_id, state.triage_run_id) if callable(get_run) else None
            if run is None:
                raise ResearchPipelineError("原竞品分诊批次不存在，不能无损恢复")
            if (
                str(getattr(run, "snapshot_id", "") or "") != state.snapshot_id
                or str(getattr(run, "run_id", "") or "") != state.triage_run_id
            ):
                raise ResearchPipelineConflictError(
                    "竞品分诊批次与原检索快照不一致，已停止恢复"
                )

            run_status = getattr(run, "status", None)
            if run_status in {
                CompetitorTriageRunStatus.REVIEW_READY,
                CompetitorTriageRunStatus.CONFIRMED,
            }:
                state = self._set_stage(
                    state,
                    "awaiting_triage_confirm",
                    detail="竞品分诊已完成，请确认保留的竞品篮子后继续。",
                    eta_seconds=None,
                    error="",
                )
                state.last_triage_retry_idempotency_key = key
                state.last_triage_retry_at = _iso()
                state = self._persist(project_id, state)
                return {"pipeline": state.as_dict(), "triage_job_id": "", "reused": True}

            incomplete_chunk_ids = [
                chunk.chunk_id
                for chunk in list(getattr(run, "chunks", None) or [])
                if chunk.status != CompetitorTriageChunkStatus.SUCCEEDED
            ]
            if not incomplete_chunk_ids:
                raise ResearchPipelineError(
                    "分诊批次没有未完成分块，但尚未达到可审核状态，请刷新后重试"
                )
            provider = (
                self.triage_provider_factory()
                if self.triage_provider_factory
                else None
            )
            if provider is None:
                raise ResearchPipelineError("未配置竞品分诊模型，无法恢复分诊")
            result = self.triage_service.retry_run(
                project_id,
                state.triage_run_id,
                CompetitorTriageRetryRequest(
                    actor=actor or "medical_manager",
                    idempotency_key=key,
                    chunk_ids=incomplete_chunk_ids,
                ),
                provider,
            )
            job_id = str(getattr(result, "job_id", "") or "")
            if not job_id:
                raise ResearchPipelineError("竞品分诊恢复未获得持久化任务标识")
            completed = len(list(getattr(run, "chunks", None) or [])) - len(
                incomplete_chunk_ids
            )
            total = len(list(getattr(run, "chunks", None) or []))
            state = self._set_stage(
                state,
                "triaging",
                detail=f"继续竞品分诊：已完成 {completed}/{total} 个分块，仅处理未完成部分。",
                eta_seconds=None,
                error="",
            )
            state.last_triage_retry_idempotency_key = key
            state.last_triage_retry_job_id = job_id
            state.last_triage_retry_at = _iso()
            state = self._persist(project_id, state)
            return {
                "pipeline": state.as_dict(),
                "triage_job_id": job_id,
                "reused": bool(getattr(result, "reused", False)),
            }

    def reconcile_review_ready_triage(
        self, project_id: str
    ) -> ResearchPipelineState:
        """Restore a parent that stopped while its durable triage was pending.

        This is deliberately narrower than a general failed-pipeline retry. It
        only promotes the same persisted triage run and snapshot after that run
        has reached ``review_ready``. Repeated status polls are idempotent, and
        no preparation work is started by reconciliation.
        """
        with self._lock:
            state = self.get_state(project_id)
            if state.stage not in {"failed", "triaging"}:
                return state
            if (
                not state.pipeline_id
                or not state.snapshot_id
                or not state.triage_run_id
                or state.prep_batch_id
            ):
                return state
            if state.stage == "failed":
                error_summary = str(state.error_summary or "")
                stopped_in_triage_wait = (
                    self.error_summary_indicates_triage_failure(error_summary)
                )
                if not stopped_in_triage_wait:
                    return state

            repository = getattr(self.triage_service, "repository", None)
            get_run = getattr(repository, "triage_run", None)
            if not callable(get_run):
                return state
            run = get_run(project_id, state.triage_run_id)
            if run is None:
                return state
            run_status = str(
                getattr(getattr(run, "status", ""), "value", None)
                or getattr(run, "status", "")
            )
            if (
                str(getattr(run, "run_id", "") or "") != state.triage_run_id
                or str(getattr(run, "snapshot_id", "") or "")
                != state.snapshot_id
            ):
                return state
            if run_status in {"failed", "partial_failed", "stale"}:
                if state.stage != "failed":
                    state = self._set_stage(
                        state,
                        "failed",
                        detail="竞品分诊未全部完成，可保留已成功分块并重试其余部分。",
                        eta_seconds=None,
                        error=f"competitor_triage_{run_status}",
                    )
                    return self._persist(project_id, state)
                return state
            if run_status != "review_ready":
                return state

            state = self._set_stage(
                state,
                "awaiting_triage_confirm",
                detail=(
                    "分诊重试已完成，已恢复到人工确认暂停态；"
                    "请确认保留的竞品篮子后继续下载方案原文。"
                ),
                eta_seconds=None,
                error="",
            )
            progress = self._triage_progress(project_id, state)
            if progress:
                self._apply_child_progress(
                    state,
                    phase="competitor_triage",
                    completed=progress["completed_chunks"],
                    total=progress["total_chunks"],
                    child_percent=progress["percent"],
                    label=progress["label"],
                    context=progress.get("context"),
                )
            return self._persist(project_id, state)

    def _triage_review_ready_at_deadline(
        self,
        project_id: str,
        state: ResearchPipelineState,
        triage_job_id: str,
        *,
        record: DurableJobRecord | None = None,
    ) -> bool:
        """One final authoritative reconciliation before a parent timeout.

        The polling loop can reach a stall or absolute ceiling while the durable
        child finishes inside the last sleep window. Before the parent declares
        a timeout, re-read the durable child and the bound triage run:

        - child ``failed``/``cancelled`` -> raise the truthful child error;
        - child ``completed`` AND the same run/snapshot is ``review_ready``
          (or already ``confirmed``) -> return True so the caller promotes
          the parent to ``awaiting_triage_confirm`` with live progress;
        - anything else (still queued/running, or completed but the run is
          not review-ready) -> return False so the caller preserves the
          truthful ``分诊超时`` failure.

        Never creates a triage run, repeats AI work, or weakens the basket
        confirmation gate.
        """
        record = record or self.durable_store.get(project_id, triage_job_id)
        if record.status in {"failed", "cancelled"}:
            raise ResearchPipelineError(
                f"分诊任务结束为 {record.status}: {record.error_summary}"
            )
        if record.status != "completed":
            return False
        repository = getattr(self.triage_service, "repository", None)
        get_run = getattr(repository, "triage_run", None)
        run = (
            get_run(project_id, state.triage_run_id) if callable(get_run) else None
        )
        if run is None:
            return False
        if (
            str(getattr(run, "run_id", "") or "") != state.triage_run_id
            or str(getattr(run, "snapshot_id", "") or "") != state.snapshot_id
        ):
            return False
        run_status = str(
            getattr(getattr(run, "status", ""), "value", None)
            or getattr(run, "status", "")
        )
        if run_status == "partial_failed":
            messages = [
                str(getattr(chunk, "error_message", "") or "").strip()
                for chunk in (getattr(run, "chunks", None) or [])
                if str(getattr(chunk, "error_message", "") or "").strip()
            ]
            if any("HTTP 401" in message for message in messages):
                raise ResearchPipelineError(
                    "竞品分诊模型鉴权失败（HTTP 401）；公开检索结果已保留，请检查产品模型连接后重试分诊"
                )
            detail = next(iter(dict.fromkeys(messages)), "部分分诊批次失败")
            raise ResearchPipelineError(f"竞品分诊仅部分完成：{detail}")
        return run_status in {"review_ready", "confirmed"}

    def _await_triage_child(
        self,
        project_id: str,
        state: ResearchPipelineState,
        triage_job_id: str,
        *,
        actor: str,
        pulse: Callable[[str], None],
    ) -> bool:
        """Poll the durable triage child until terminal, stalled, or hard-capped.

        Returns ``True`` only when cancellation means the caller must stop
        driving stages. Returns ``False`` when the child completed either
        inside the normal polling window or at a timeout edge, so both
        cases enter the same standard confirm/auto-confirm continuation.
        Lease heartbeat proves worker liveness only. It never resets the
        monotonic business-progress stall clock.
        """
        started_at = time.monotonic()
        last_progress_at = started_at
        best_completed = -1
        while True:
            if state.cancel_requested:
                self.cancel(project_id, actor=actor)
                return True
            record = self.durable_store.get(project_id, triage_job_id)
            if record.status in {"failed", "cancelled"}:
                raise ResearchPipelineError(
                    f"分诊任务结束为 {record.status}: {record.error_summary}"
                )
            progress = self._triage_progress(project_id, state)
            if progress:
                completed = int(progress["completed_chunks"])
                if completed > best_completed:
                    best_completed = completed
                    last_progress_at = time.monotonic()
                self._apply_child_progress(
                    state,
                    phase="competitor_triage",
                    completed=completed,
                    total=progress["total_chunks"],
                    child_percent=progress["percent"],
                    label=progress["label"],
                    context=progress.get("context"),
                )
                pulse(progress["label"])
            else:
                completed = int(record.progress.step or 0)
                if completed > best_completed:
                    best_completed = completed
                    last_progress_at = time.monotonic()
                pulse(f"分诊进行中… ({record.progress.percent}%)")

            if record.status == "completed":
                if self._triage_review_ready_at_deadline(
                    project_id,
                    state,
                    triage_job_id,
                    record=record,
                ):
                    return False
                raise TriageWaitTimeoutError(
                    "分诊超时：子任务已完成但分诊结果未达到可审核状态"
                )

            now = time.monotonic()
            elapsed = now - started_at
            stalled_for = now - last_progress_at
            if elapsed >= TRIAGE_CHILD_ABSOLUTE_CEILING_SECONDS:
                if self._triage_review_ready_at_deadline(
                    project_id, state, triage_job_id
                ):
                    return False
                raise TriageWaitTimeoutError(
                    "分诊超时：已达到父任务绝对等待上限"
                )
            if stalled_for >= TRIAGE_CHILD_STALL_SECONDS:
                if self._triage_review_ready_at_deadline(
                    project_id, state, triage_job_id
                ):
                    return False
                raise TriageWaitTimeoutError(
                    "分诊超时：子任务长时间未产生新的业务进度"
                )

            time.sleep(2.5)

    def _notify_corpus_ready(self, project_id: str) -> None:
        """Best-effort in-app notice when corpus becomes ready."""
        try:
            from services.api.app.workbench_notifications import (
                notify_corpus_ready,
                notifications_path,
            )
            import os
            from pathlib import Path

            runtime_dir = os.environ.get("WORKBENCH_RUNTIME_DIR")
            path = (
                notifications_path(runtime_dir)
                if runtime_dir
                else notifications_path(
                    Path(__file__).resolve().parents[5] / "runtime"
                )
            )
            notify_corpus_ready(project_id, path=path)
        except Exception:
            pass

    def start_round2_after_design(
        self,
        project_id: str,
        *,
        actor: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """After design confirmation, run a lightweight round-2 competitor re-analysis.

        Requires design recommendations unlocked (corpus_ready / round1 material /
        corpus gate ready). Completes to ``round2_ready`` and stamps
        ``round2_material_ready=True``.
        """
        with self._lock:
            journey = self.journey_service.get(project_id)
            ready, reason = research_ready_for_design_recommendations(journey)
            framing = journey.framing
            picos = journey.picos if hasattr(journey, "picos") else getattr(
                getattr(journey, "study_definition", None), "picos", None
            )
            framing_ok = framing is not None and framing.creation_minimum_complete()
            picos_ok = False
            if picos is not None:
                checker = getattr(picos, "completion_status", None) or getattr(
                    picos, "is_complete", None
                )
                if callable(checker):
                    try:
                        picos_ok = bool(checker())
                    except TypeError:
                        picos_ok = bool(checker)
                elif checker is not None:
                    picos_ok = bool(checker)
                else:
                    # Soft presence check — PICOS object exists after framing.
                    picos_ok = True
            gate = journey.corpus_gate
            gate_ready = (
                gate is not None
                and str(getattr(gate, "readiness_status", "") or "") == "ready"
                and not bool(getattr(getattr(gate, "override", None), "active", False))
            )
            state = self.get_state(project_id)
            stage_ok = state.stage in {
                "corpus_ready",
                "analyzing_round2",
                "round2_ready",
                "awaiting_corpus_admission",
            }
            if not (
                ready
                or (framing_ok and picos_ok and gate_ready)
                or (stage_ok and (ready or gate_ready or state.round1_material_ready))
            ):
                raise ValueError(
                    "须先完成研究语料准备并解锁研究设计推荐后，才能启动第2轮精细化竞品再分析"
                    f"（当前：{reason or state.stage or '未就绪'}）。"
                )

            if state.stage == "round2_ready" and state.round2_material_ready:
                return {
                    "pipeline": state.as_dict(),
                    "started": False,
                    "reason": "already_round2_ready",
                }

            pipeline_id = state.pipeline_id or (
                "mwpipe_r2_"
                + hashlib.sha256(
                    f"{project_id}|{idempotency_key}|round2".encode()
                ).hexdigest()[:16]
            )
            if not state.pipeline_id:
                state.pipeline_id = pipeline_id
            # Persist analyzing stage first so UI can show progress, then complete.
            state = self._set_stage(
                state,
                "analyzing_round2",
                detail="基于已确认研究设计做精细化竞品再分析",
                eta_seconds=None,
                error="",
            )
            state = self._persist(project_id, state)

            brief_ids = self._run_corpus_analysis(
                project_id,
                actor,
                state,
                round_number=2,
            )
            state.round2_brief_ids = brief_ids[:50]
            state.round2_material_ready = True
            state = self._set_stage(
                state,
                "round2_ready",
                detail=(
                    f"第2轮精细化竞品再分析已就绪（绑定 {len(state.round2_brief_ids)} 条"
                    "证据摘要），可对照已确认设计复核竞品差异。"
                ),
                error="",
            )
            state = self._persist(project_id, state)
            return {
                "pipeline": state.as_dict(),
                "started": True,
                "round2_material_ready": True,
            }

    def _run_inline(
        self,
        project_id: str,
        state: ResearchPipelineState,
        *,
        actor: str,
        auto_confirm_triage: bool,
    ) -> dict[str, Any]:
        try:
            state = self.execute_stages(
                project_id,
                state,
                actor=actor,
                auto_confirm_triage=auto_confirm_triage,
                heartbeat=lambda _p: not state.cancel_requested,
            )
        except TriageWaitTimeoutError as exc:
            state = self.get_state(project_id)
            progress = self._triage_progress(project_id, state)
            if progress:
                self._apply_child_progress(
                    state,
                    phase="competitor_triage",
                    completed=progress["completed_chunks"],
                    total=progress["total_chunks"],
                    child_percent=progress["percent"],
                    label=progress["label"],
                    context=progress.get("context"),
                )
            state = self._set_stage(
                state,
                "triaging",
                detail=(
                    "竞品分诊长时间未产生新批次结果；"
                    "后台子任务状态已保留，完成后可继续。"
                ),
                error=f"{type(exc).__name__}: {exc}",
            )
            state = self._persist(project_id, state)
        except Exception as exc:  # noqa: BLE001
            state = self._set_stage(
                state,
                "failed",
                detail="研究流水线失败",
                error=f"{type(exc).__name__}: {exc}",
            )
            state = self._persist(project_id, state)
        return {"pipeline": state.as_dict(), "started": True, "mode": "inline"}

    def execute_stages(
        self,
        project_id: str,
        state: ResearchPipelineState,
        *,
        actor: str,
        auto_confirm_triage: bool,
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> ResearchPipelineState:
        """Drive stages. Designed for durable executor or inline use."""

        def pulse(detail: str) -> None:
            if not heartbeat(_progress_payload(state, detail)):
                raise ResearchPipelineError("pipeline cancelled or lease lost")

        # --- search ---
        state = self._set_stage(
            state, "searching", detail="正在检索 ClinicalTrials.gov", eta_seconds=None
        )
        self._apply_child_progress(
            state,
            phase="registry_search",
            completed=0,
            total=2,
            label="正在检索 ClinicalTrials.gov",
            context={
                "current_registry": "clinicaltrials.gov",
                "registry_step": 1,
                "registry_total": 2,
            },
        )
        state = self._persist(project_id, state)
        pulse(state.detail)
        if state.cancel_requested:
            return self.cancel(project_id, actor=actor)

        from packages.contracts.workbench_contracts import (
            MedicalWritingCompetitorSearchExecuteRequest,
        )

        journey = self.journey_service.get(project_id)
        if journey.search_plan is None:
            raise ResearchPipelineError("缺少竞品检索计划，请先确认最小项目事实")
        existing_snapshot_id = str(
            getattr(journey.search_plan, "latest_snapshot_id", "") or ""
        ).strip()
        existing_returned = int(
            getattr(journey.search_plan, "returned_count", 0) or 0
        )
        if existing_snapshot_id and existing_returned > 0:
            # Force/re-run on an already-bound journey must reuse the immutable
            # search snapshot — create_search_snapshot + attach would conflict.
            class _ReuseSnapshot:
                snapshot_id = existing_snapshot_id
                returned_count = existing_returned

            snapshot = _ReuseSnapshot()
            state.snapshot_id = existing_snapshot_id
            state.detail = (
                f"复用已绑定检索快照 {existing_snapshot_id}（{existing_returned} 项）"
            )
            state = self._persist(project_id, state)
            pulse(state.detail)
        else:
            search_req = MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=journey.search_plan.plan_id,
                actor=actor,
                idempotency_key=f"pipe-search-{state.pipeline_id}",
            )
            search_request = self.journey_service.build_competitor_search_request(
                project_id, search_req
            )
            snapshot = self.discovery_service.create_search_snapshot(
                project_id, search_request
            )
            journey = self.journey_service.attach_search_snapshot(
                project_id, snapshot, search_req
            )
            state.snapshot_id = snapshot.snapshot_id

        self._apply_child_progress(
            state,
            phase="registry_search",
            completed=1,
            total=2,
            label="ClinicalTrials.gov 检索完成，正在探针中国注册平台",
            context={
                "current_registry": "chinadrugtrials.org.cn",
                "registry_step": 2,
                "registry_total": 2,
                "clinicaltrials_snapshot_id": state.snapshot_id,
                "clinicaltrials_returned_count": int(snapshot.returned_count),
            },
        )
        state.detail = state.child_label
        state = self._persist(project_id, state)
        pulse(state.detail)

        # China probe (never invent rows)
        try:
            china = self.china_client_factory().probe_and_search(
                indication_zh=journey.framing.indication or "",
                study_phase=journey.framing.study_phase or "",
                product_name=journey.framing.investigational_product or "",
            )
            state.dual_registry = {
                "primary": "clinicaltrials.gov",
                "secondary": "chinadrugtrials.org.cn",
                "chinadrugtrials": china.as_dict(),
            }
        except Exception as exc:  # noqa: BLE001
            state.dual_registry = {
                "primary": "clinicaltrials.gov",
                "secondary": "chinadrugtrials.org.cn",
                "chinadrugtrials": {
                    "status": "probe_exception",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            }

        china_status = str(
            state.dual_registry.get("chinadrugtrials", {}).get("status") or "completed"
        )
        self._apply_child_progress(
            state,
            phase="registry_search",
            completed=2,
            total=2,
            label="中国注册平台探针完成",
            context={
                "current_registry": "chinadrugtrials.org.cn",
                "registry_step": 2,
                "registry_total": 2,
                "clinicaltrials_snapshot_id": state.snapshot_id,
                "clinicaltrials_returned_count": int(snapshot.returned_count),
                "chinadrugtrials_status": china_status,
            },
        )
        state.detail = state.child_label
        state = self._persist(project_id, state)
        pulse(state.detail)

        if snapshot.returned_count <= 0:
            # A valid zero-result public search is an actionable evidence
            # boundary, not an infrastructure failure. Keep the exact
            # search snapshot and registry probe audit while routing the user
            # to the shared-corpus/manual-upload gate. No heavy downstream
            # stage may start when there is no public Protocol to retain.
            return self._persist_no_retainable_candidate_fallback(
                project_id,
                state,
                error="no_public_protocol_results",
            )

        # --- triage ---
        journey = self.journey_service.get(project_id)
        corpus_triage = getattr(journey, "corpus_triage", None)
        corpus_status = str(getattr(corpus_triage, "status", "") or "")
        corpus_snapshot = str(getattr(corpus_triage, "snapshot_id", "") or "")
        retained_ids = list(getattr(corpus_triage, "retained_candidate_ids", None) or [])
        if (
            corpus_status == "finalized"
            and corpus_snapshot == state.snapshot_id
            and retained_ids
        ):
            state.triage_run_id = state.triage_run_id or str(
                getattr(journey, "latest_competitor_triage_run_id", "") or ""
            )
            state = self._set_stage(
                state,
                "awaiting_triage_confirm",
                detail=(
                    f"复用已定稿语料分诊篮子（{len(retained_ids)} 项），跳过重复 AI 分诊。"
                ),
                eta_seconds=None,
            )
            state = self._persist(project_id, state)
            pulse(state.detail)
            if not auto_confirm_triage:
                return state
            return self.continue_after_triage(
                project_id,
                actor=actor,
                retained_candidate_ids=retained_ids,
                heartbeat=heartbeat,
                state=state,
            )

        state = self._set_stage(
            state,
            "triaging",
            detail=f"已检索到 {snapshot.returned_count} 项研究，正在 AI 分诊…",
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)

        from packages.contracts.workbench_contracts import CompetitorTriageCreateRequest

        provider = (
            self.triage_provider_factory()
            if self.triage_provider_factory
            else None
        )
        if provider is None:
            raise ResearchPipelineError("未配置竞品分诊模型，无法执行真实分诊")
        journey = self.journey_service.get(project_id)
        triage_req = CompetitorTriageCreateRequest(
            snapshot_id=state.snapshot_id,
            expected_journey_revision=journey.revision,
            actor=actor,
            idempotency_key=f"pipe-triage-{state.pipeline_id}",
        )
        triage_start = self.triage_service.create_run(
            project_id, triage_req, provider
        )
        triage_run_id = getattr(triage_start, "run_id", None) or (
            triage_start.get("run_id") if isinstance(triage_start, dict) else ""
        )
        triage_job_id = getattr(triage_start, "job_id", None) or (
            triage_start.get("job_id") if isinstance(triage_start, dict) else ""
        )
        state.triage_run_id = str(triage_run_id or "")
        state = self._persist(project_id, state)

        # Wait for triage durable job if present
        if triage_job_id and self.durable_store is not None:
            if self._await_triage_child(
                project_id, state, triage_job_id, actor=actor, pulse=pulse
            ):
                return self.get_state(project_id)
        final_triage_progress = self._triage_progress(project_id, state)
        if final_triage_progress:
            self._apply_child_progress(
                state,
                phase="competitor_triage",
                completed=final_triage_progress["completed_chunks"],
                total=final_triage_progress["total_chunks"],
                child_percent=final_triage_progress["percent"],
                label=final_triage_progress["label"],
                context=final_triage_progress.get("context"),
            )

        # Pause for human confirm unless auto_confirm_triage
        state = self._set_stage(
            state,
            "awaiting_triage_confirm",
            detail=(
                "分诊已完成，请确认保留的竞品篮子后继续下载方案原文。"
                if not auto_confirm_triage
                else "分诊完成，流水线将自动保留含公开Protocol的相关候选并继续。"
            ),
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)

        if not auto_confirm_triage:
            # Durable job completes at this pause; UI confirm resumes via continue_after_triage.
            return state

        return self.continue_after_triage(
            project_id,
            actor=actor,
            heartbeat=heartbeat,
            state=state,
        )

    def advance_after_basket_confirm(
        self,
        project_id: str,
        *,
        actor: str,
        idempotency_key: str,
        expected_pipeline_id: str = "",
        retained_candidate_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Advance the parent pipeline after the user's one-click basket confirm.

        This is the single action that replaces the old two-click flow
        (confirm basket → then click "continue after triage"). It is
        idempotent: repeated calls or page reloads do not duplicate
        download/extraction/translation work.

        ``retained_candidate_ids`` carries the exact authoritative retained
        scope from the successful ``confirm_basket`` call (or from the
        current locked-snapshot confirmed projection when not supplied).
        The resume path consumes these frozen IDs and NEVER calls
        ``confirm_basket``, ``_confirm_triage_basket``, or legacy
        ``finalize_triage`` again — the medical manager's one-click
        decision is final.

        Returns the pipeline state dict. If no pipeline exists or the
        pipeline is not at ``awaiting_triage_confirm``, returns the current
        state without raising — the confirm call itself is always valid
        independent of pipeline state.
        """
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("advance_after_basket_confirm requires idempotency_key")
        with self._lock:
            state = self.get_state(project_id)
            if not state.pipeline_id:
                return {"pipeline": state.as_dict(), "advanced": False}
            if expected_pipeline_id and state.pipeline_id != expected_pipeline_id:
                raise ResearchPipelineConflictError(
                    "研究流水线已更新，请刷新当前状态后重试"
                )
            if state.stage != "awaiting_triage_confirm":
                # Already advanced (or not yet at the confirm gate).
                # Return current state without error — idempotent.
                return {"pipeline": state.as_dict(), "advanced": False}

            # Resolve the frozen retained IDs from the explicit argument
            # or from the current locked-snapshot confirmed projection.
            # This is the ONLY authority for the downstream preparation
            # scope; the resume path must never recompute from AI
            # classifications or public-document preference.
            frozen_retained = self._resolve_confirmed_retained_ids(
                project_id, state, retained_candidate_ids
            )
            if not frozen_retained:
                state = self._persist_no_retainable_candidate_fallback(
                    project_id,
                    state,
                    error="no_retainable_candidates_after_confirm",
                )
                return {"pipeline": state.as_dict(), "advanced": False}

            # Resume through the durable worker if available, so heavy
            # download/extract/translate work does not block the API
            # response thread.
            if self.durable_store is not None:
                from packages.contracts.workbench_contracts import (
                    DurableJobCreateRequest,
                )
                payload = {
                    "pipeline_id": state.pipeline_id,
                    "actor": actor or "medical_manager",
                    "resume_from": "awaiting_triage_confirm",
                    "idempotency_key": key,
                    "retained_candidate_ids": frozen_retained,
                }
                request_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                create_req = DurableJobCreateRequest(
                    project_id=project_id,
                    job_type=RESEARCH_PIPELINE_JOB_TYPE,
                    business_key=(
                        f"research-pipeline:{project_id}:{state.pipeline_id}"
                        f":after-triage-confirm:{key}"
                    ),
                    request_hash=request_hash,
                    input_hash=request_hash[:64],
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    created_by=actor or "research_pipeline",
                    max_attempts=3,
                    provider="workbench",
                    model="research_pipeline_orchestrator",
                )
                start_resp = self.durable_store.create_or_reuse(create_req)
                state.job_id = start_resp.job_id
                state.last_resume_idempotency_key = key
                state.last_resume_at = _iso()
                # Only transition to "preparing" if the durable worker can
                # actually be woken. If wake fails, keep the truthful
                # awaiting_triage_confirm stage so the UI does not show
                # false progress.
                woken = False
                if self.durable_worker is not None:
                    try:
                        self.durable_worker.wake(project_id, start_resp.job_id)
                        woken = True
                    except Exception:  # noqa: BLE001
                        pass
                if woken:
                    state = self._set_stage(
                        state,
                        "preparing",
                        detail="竞品篮子已确认，正在继续下载方案原文…",
                        eta_seconds=None,
                        error="",
                    )
                else:
                    # Durable store accepted the job but worker could not be
                    # woken. Keep the truthful paused state; the worker's
                    # own poll loop will eventually pick up the queued job.
                    state = self._set_stage(
                        state,
                        "awaiting_triage_confirm",
                        detail="竞品篮子已确认，研究流水线已排队等待后台继续。",
                        eta_seconds=None,
                        error="",
                    )
                state = self._persist(project_id, state)
                return {
                    "pipeline": state.as_dict(),
                    "advanced": True,
                    "job_id": start_resp.job_id,
                }

            # Synchronous fallback (tests / no durable worker).
            try:
                resumed = self._continue_after_confirmed_triage(
                    project_id,
                    actor=actor,
                    frozen_retained_ids=frozen_retained,
                    heartbeat=lambda _p: not state.cancel_requested,
                    state=state,
                )
                resumed.last_resume_idempotency_key = key
                resumed.last_resume_at = _iso()
                resumed = self._persist(project_id, resumed)
                return {"pipeline": resumed.as_dict(), "advanced": True}
            except (ResearchPipelineError, ValueError) as exc:
                current = self.get_state(project_id)
                if current.stage == "translating":
                    failure_stage = "awaiting_translation_scope"
                else:
                    failure_stage = "awaiting_triage_confirm"
                current = self._set_stage(
                    current,
                    failure_stage,
                    detail=f"确认后继续未完成：{exc}",
                    eta_seconds=None,
                    error=f"advance_failed:{type(exc).__name__}:{exc}",
                )
                current.last_resume_idempotency_key = key
                current.last_resume_at = _iso()
                self._persist(project_id, current)
                raise

    def _resolve_confirmed_retained_ids(
        self,
        project_id: str,
        state: ResearchPipelineState,
        explicit_retained: list[str] | None,
    ) -> list[str]:
        """Resolve the authoritative retained candidate IDs from the current
        confirmed basket projection.

        When ``explicit_retained`` is provided (from the API's confirmation
        response), it is preferred — it is the exact set the medical manager
        confirmed. When not provided, the method reads the current locked-
        snapshot confirmed projection (discovery basket or finalized corpus
        triage), validates the snapshot matches the pipeline's snapshot, and
        returns those IDs.

        This method MUST NOT recompute from AI classifications or public-
        document preference.
        """
        if explicit_retained is not None:
            return sorted(dict.fromkeys(explicit_retained))

        journey = self.journey_service.get(project_id)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id
            if journey.search_plan
            else ""
        )
        if not snapshot_id:
            return []

        # Prefer finalized corpus triage (post-PICOS).
        triage = getattr(journey, "corpus_triage", None)
        if (
            triage is not None
            and str(getattr(triage, "status", "")) == "finalized"
            and str(getattr(triage, "snapshot_id", "")) == snapshot_id
        ):
            ids = list(getattr(triage, "retained_candidate_ids", None) or [])
            if ids:
                return sorted(dict.fromkeys(ids))

        # Fall back to confirmed discovery basket projection (pre-PICOS).
        discovery = getattr(journey, "discovery_basket_projection", None)
        if (
            discovery is not None
            and getattr(discovery, "confirmation_id", "")
            and str(getattr(discovery, "snapshot_id", "")) == snapshot_id
        ):
            ids = list(getattr(discovery, "retained_nct_ids", None) or [])
            if ids:
                return sorted(dict.fromkeys(ids))

        return []

    def _persist_no_retainable_candidate_fallback(
        self,
        project_id: str,
        state: ResearchPipelineState,
        *,
        error: str,
    ) -> ResearchPipelineState:
        """Keep an empty confirmed basket actionable instead of terminal-failing.

        A confirmed empty basket is a valid medical decision when public
        Protocol/SAP documents are unavailable or unsuitable. It must not
        start download/OCR/translation work, but it also must not strand the
        greenfield journey in a terminal failure: the user still needs a
        visible path to the shared-corpus/manual-upload review and the
        explicit corpus-gate exception. Preserve the exact error code and
        triage lineage for audit while leaving all downstream heavy stages
        untouched.
        """
        state.round1_material_ready = False
        state = self._set_stage(
            state,
            "awaiting_corpus_admission",
            detail=(
                "已确认当前公开检索没有可保留Protocol；未启动下载、OCR或翻译。"
                "可在语料准入处使用已审核共享语料或手动上传方案，并由医学经理"
                "明确记录项目特异理由后继续；系统不会伪造公开来源。"
            ),
            error=error,
        )
        # The previous registry-search/triage projection is no longer an
        # active child job.  Clear it explicitly even when the stage remains
        # in the same round-1 progress group (for example, a zero-result
        # retry from ``awaiting_corpus_analysis``); otherwise the UI can show
        # a stale "collecting 0/4" spinner beside a truthful waiting state.
        self._apply_child_progress(
            state,
            phase="corpus_admission",
            completed=0,
            total=0,
            child_percent=0,
            label="等待医学经理选择语料来源",
            context={
                "fallback_mode": "shared_corpus_or_manual_upload",
                "confirmed_empty_basket": True,
                "downstream_heavy_stages_started": False,
            },
        )
        state.child_context = {
            "fallback_mode": "shared_corpus_or_manual_upload",
            "confirmed_empty_basket": True,
            "downstream_heavy_stages_started": False,
        }
        return self._persist(project_id, state)

    def _continue_after_confirmed_triage(
        self,
        project_id: str,
        *,
        actor: str,
        frozen_retained_ids: list[str],
        heartbeat: Callable[[DurableJobProgressPayload], bool] | None = None,
        state: ResearchPipelineState | None = None,
    ) -> ResearchPipelineState:
        """Resume from an already-confirmed basket → prep → translate → round1.

        This method NEVER calls ``confirm_basket``, ``_confirm_triage_basket``,
        or legacy ``finalize_triage``. The ``frozen_retained_ids`` are the
        authoritative scope from the medical manager's one-click decision.
        Before beginning preparation, it validates that these IDs still match
        the current locked-snapshot confirmed projection.
        """
        state = state or self.get_state(project_id)
        if state.stage in {"corpus_ready", "cancelled"}:
            return state

        def pulse(detail: str) -> None:
            if heartbeat is None:
                return
            if not heartbeat(_progress_payload(state, detail)):
                raise ResearchPipelineError("pipeline cancelled or lease lost")

        journey = self.journey_service.get(project_id)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id if journey.search_plan else ""
        )
        if not snapshot_id:
            raise ResearchPipelineError("缺少检索快照，无法继续语料准备")

        # Validate frozen IDs still match the current confirmed projection.
        current_retained = self._resolve_confirmed_retained_ids(
            project_id, state, None
        )
        if sorted(frozen_retained_ids) != sorted(current_retained):
            raise ResearchPipelineError(
                "确认的竞品篮子范围与当前锁定快照的投影不一致，请刷新后重试"
            )

        retained_ids = sorted(dict.fromkeys(frozen_retained_ids))
        if not retained_ids:
            return self._persist_no_retainable_candidate_fallback(
                project_id,
                state,
                error="no_retainable_candidates",
            )

        # --- preparing (download + extract) ---
        state = self._set_stage(
            state,
            "preparing",
            detail=f"已锁定候选 {len(retained_ids)} 项，正在核对公开Protocol范围…",
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)

        from packages.contracts.workbench_contracts.models import (
            WritingReferencePreparationBatchCreateRequest,
        )

        # Reuse a successful prep for this snapshot when force/re-run would
        # otherwise re-extract immutable artifacts.
        reused_prep = self._find_reusable_preparation_batch(
            project_id, snapshot_id=snapshot_id, retained_ids=retained_ids
        )
        if reused_prep is not None:
            prep_batch = reused_prep
            state.prep_batch_id = prep_batch.batch_id
            state.detail = (
                f"{self._preparation_progress_detail(prep_batch)}；"
                f"复用已成功的原文准备批次 {prep_batch.batch_id}（跳过重复提取）"
            )
            state = self._persist(project_id, state)
            pulse(state.detail)
        else:
            prep_batch = self.preparation_batch_service.create(
                project_id,
                WritingReferencePreparationBatchCreateRequest(
                    snapshot_id=snapshot_id,
                    actor=actor,
                    idempotency_key=f"pipe-prep-snap-{snapshot_id}",
                ),
            )
            state.prep_batch_id = prep_batch.batch_id
            state = self._persist(project_id, state)

            def report_preparation_progress(batch: Any) -> None:
                nonlocal state
                detail = self._preparation_progress_detail(batch)
                self._apply_child_progress(
                    state, **self._preparation_progress_projection(batch)
                )
                state.detail = detail
                state.eta_seconds = None
                state = self._persist(project_id, state)
                pulse(detail)

            self.preparation_batch_service.run_pending(
                project_id,
                prep_batch.batch_id,
                actor,
                progress_callback=report_preparation_progress,
            )
            self._wait_preparation(project_id, state, pulse)
            prep_batch = self._drain_deferred_preparation_stages(
                project_id,
                prep_batch.batch_id,
                actor=actor,
                progress_callback=report_preparation_progress,
            )

        # Document-content validation is a user-authority boundary.
        admission = self._admit_prepared_public_documents(
            project_id,
            actor=actor,
            pipeline_id=state.pipeline_id,
            prep_batch_id=prep_batch.batch_id,
        )
        state.document_admission_blockers = [
            dict(item) for item in admission.blocked_documents
        ]
        state.document_admission_exclusions = [
            dict(item) for item in admission.excluded_documents
        ]
        if admission.blocked_documents:
            blocked_labels = [
                str(item.get("filename") or item.get("artifact_id") or "未命名文件")
                for item in admission.blocked_documents[:5]
            ]
            state = self._set_stage(
                state,
                "awaiting_document_validation",
                detail=(
                    f"{len(admission.blocked_documents)} 份Protocol尚未通过内容或结构准入："
                    f"{'、'.join(blocked_labels)}。请查看适应症、文档类型、研究标识、"
                    "版本/来源校验结果；如确认文件无误，可由用户明确覆盖后重试。"
                ),
                eta_seconds=None,
                error="document_admission_review_required",
            )
            return self._persist(project_id, state)
        if admission.admitted_count <= 0:
            state = self._set_stage(
                state,
                "awaiting_translation_scope",
                detail="本轮公开Protocol均未形成可用章节语料，请处理例外文件后重试。",
                eta_seconds=None,
                error="translation_scope_not_ready:no_admitted_documents",
            )
            return self._persist(project_id, state)
        exclusion_note = (
            f"；另有 {len(admission.excluded_documents)} 份例外文件已从本轮语料范围排除"
            if admission.excluded_documents
            else ""
        )
        state.detail = (
            f"已准入 {admission.admitted_count} 份内容校验通过的Protocol"
            f"{exclusion_note}，进入翻译。"
        )
        state = self._persist(project_id, state)

        return self._translate_analyze_and_finalize(
            project_id,
            actor=actor,
            state=state,
            snapshot_id=snapshot_id,
            heartbeat=heartbeat,
        )

    def resume_waiting(
        self,
        project_id: str,
        *,
        actor: str,
        idempotency_key: str,
        expected_pipeline_id: str = "",
        expected_stage: str = "",
    ) -> ResearchPipelineState:
        """Retry a user-resolved document gate without replaying earlier work.

        This route is intentionally narrower than ``continue_after_triage``:
        it only accepts document-processing/analysis retry stages and starts from
        the already persisted preparation batch. Search, triage, download, and
        extraction are never rerun here.
        """
        if not str(idempotency_key or "").strip():
            raise ValueError("恢复研究流水线必须提供 idempotency_key")

        with self._lock:
            state = self.get_state(project_id)
            if expected_pipeline_id and state.pipeline_id != expected_pipeline_id:
                raise ResearchPipelineConflictError(
                    "研究流水线已更新，请刷新当前状态后再继续"
                )
            if state.last_resume_idempotency_key == idempotency_key:
                return state
            retrying_failed_downstream = (
                state.stage == "failed" and bool(state.prep_batch_id)
            )
            if (
                state.stage not in USER_ACTION_WAITING_STAGES
                and not retrying_failed_downstream
            ):
                raise ResearchPipelineConflictError(
                    f"当前阶段 {state.stage or '未启动'} 不允许从文档处理入口恢复"
                )
            if expected_stage and state.stage != expected_stage:
                raise ResearchPipelineConflictError(
                    f"等待阶段已从 {expected_stage} 变为 {state.stage}，请刷新后重试"
                )
            if not state.prep_batch_id:
                raise ResearchPipelineError(
                    "等待状态缺少既有原文准备批次，无法在不重复下载/提取的前提下恢复"
                )

            started_from_stage = state.stage
            prep_batch_id = state.prep_batch_id
            state = self._set_stage(
                state,
                "preparing",
                detail="正在复核既有原文、解析、OCR与准入状态后继续翻译。",
                eta_seconds=None,
                error="",
            )
            # Mark the in-flight idempotency key before releasing the lock.
            # A duplicate click returns this current state instead of starting
            # a second translation run. Failure clears the key for a later
            # deliberate retry.
            state.last_resume_idempotency_key = idempotency_key
            state.last_resume_started_from_stage = started_from_stage
            state.last_resume_result_stage = "preparing"
            state.last_resume_at = _iso()

            # A user-resolved preparation/document gate can own the same
            # immutable batch for a long time (download/OCR and later
            # translation).  Running that work inline in the HTTP request
            # leaves a persisted ``preparing`` projection with only the old
            # completed parent job if the browser, worker thread, or process
            # disappears at a stage boundary.  In the production composition
            # root, hand the continuation to the durable research-pipeline
            # worker instead.  The business key is bound to this explicit
            # user idempotency key, so a duplicate click/restart reuses the
            # same job and cannot replay completed preparation items.
            if (
                getattr(self, "durable_store", None) is not None
                and getattr(self, "durable_worker", None) is not None
            ):
                from packages.contracts.workbench_contracts import (
                    DurableJobCreateRequest,
                )

                payload = {
                    "pipeline_id": state.pipeline_id,
                    "actor": actor or "medical_manager",
                    "resume_from": started_from_stage,
                    "prep_batch_id": prep_batch_id,
                    "idempotency_key": idempotency_key,
                    "corpus_analysis_ai_route": dict(state.round1_ai_route),
                }
                request_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False).encode(
                        "utf-8"
                    )
                ).hexdigest()
                create_req = DurableJobCreateRequest(
                    project_id=project_id,
                    job_type=RESEARCH_PIPELINE_JOB_TYPE,
                    business_key=(
                        f"research-pipeline:{project_id}:{state.pipeline_id}"
                        f":resume-waiting:{idempotency_key}"
                    ),
                    request_hash=request_hash,
                    input_hash=request_hash[:64],
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    created_by=actor or "research_pipeline",
                    max_attempts=3,
                    provider="workbench",
                    model="research_pipeline_orchestrator",
                )
                start_resp = self.durable_store.create_or_reuse(create_req)
                state.job_id = start_resp.job_id
                state = self._persist(project_id, state)
                try:
                    self.durable_worker.wake(project_id, start_resp.job_id)
                except Exception:
                    # The durable store remains authoritative; its poll loop
                    # can claim the queued job.  Keep the preparing projection
                    # rather than exposing a false waiting/finished state.
                    pass
                return state

            active_resumes = getattr(self, "_active_resume_projects", None)
            if active_resumes is None:
                active_resumes = set()
                self._active_resume_projects = active_resumes
            active_resumes.add(project_id)
            state = self._persist(project_id, state)

        try:
            continuation = self._continue_from_prepared_batch
            continuation_kwargs = {
                "actor": actor,
                "state": state,
                "prep_batch_id": prep_batch_id,
            }
            # Keep narrow test doubles and older in-process adapters
            # compatible while the production method gains stage idempotency.
            if "resume_idempotency_key" in inspect.signature(continuation).parameters:
                continuation_kwargs["resume_idempotency_key"] = idempotency_key
            resumed = continuation(project_id, **continuation_kwargs)
            # If a concurrent status refresh won a parent-generation race,
            # the immutable round-1 artifact may already exist while the
            # continuation returned an older parent projection.  Rebind that
            # artifact before returning so the same request exposes a truthful
            # resumable state and never needs another model call.
            resumed = self._reconcile_completed_round1_analysis(project_id, resumed)
        except Exception as exc:  # noqa: BLE001 — leave no stale in-flight stage
            with self._lock:
                # Preserve a truthful, retryable waiting state. The exception
                # still reaches the API caller; it is never converted into a
                # successful corpus-ready response.
                current = self.get_state(project_id)
                if current.stage == "translating":
                    failure_stage = "awaiting_translation_scope"
                elif current.stage == "analyzing_round1":
                    failure_stage = "awaiting_corpus_analysis"
                else:
                    failure_stage = started_from_stage
                current = self._set_stage(
                    current,
                    failure_stage,
                    detail=(
                        f"恢复未完成：{exc}。已完成的下载与结构提取仍保留，"
                        "请处理提示后再次继续。"
                    ),
                    eta_seconds=None,
                    error=f"resume_failed:{type(exc).__name__}:{exc}",
                )
                # Record the failed attempt without consuming the idempotency
                # key. The same user action can be retried after the translation
                # issue is resolved, while the UI still shows where this attempt
                # started and actually stopped.
                current.last_resume_idempotency_key = ""
                current.last_resume_started_from_stage = started_from_stage
                current.last_resume_result_stage = failure_stage
                current.last_resume_at = _iso()
                self._persist(project_id, current)
                getattr(self, "_active_resume_projects", set()).discard(project_id)
            raise

        with self._lock:
            resumed.last_resume_idempotency_key = idempotency_key
            resumed.last_resume_started_from_stage = started_from_stage
            resumed.last_resume_result_stage = resumed.stage
            resumed.last_resume_at = _iso()
            result = self._persist(project_id, resumed)
        # Clear only after the terminal/waiting projection has been persisted;
        # otherwise a status request could still observe ``preparing`` and
        # race the final write.
        getattr(self, "_active_resume_projects", set()).discard(project_id)
        return result

    def continue_after_triage(
        self,
        project_id: str,
        *,
        actor: str,
        retained_candidate_ids: list[str] | None = None,
        heartbeat: Callable[[DurableJobProgressPayload], bool] | None = None,
        state: ResearchPipelineState | None = None,
    ) -> ResearchPipelineState:
        """Resume from triage confirm → prep → translate → round1 → corpus_ready."""
        state = state or self.get_state(project_id)
        if state.stage in {"corpus_ready", "cancelled"}:
            return state

        def pulse(detail: str) -> None:
            if heartbeat is None:
                return
            if not heartbeat(_progress_payload(state, detail)):
                raise ResearchPipelineError("pipeline cancelled or lease lost")

        journey = self.journey_service.get(project_id)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id if journey.search_plan else ""
        )
        if not snapshot_id:
            raise ResearchPipelineError("缺少检索快照，无法继续语料准备")

        # Confirm the competitor basket. Prefer the real single user-decision
        # action (CompetitorTriageService.confirm_basket): it writes relevance
        # decisions AND projects discovery-basket (pre-PICOS) / finalized
        # corpus triage (post-PICOS) from the AI run's own classifications in
        # one authoritative step. Fall back to the legacy finalize_triage path
        # (existing relevance decisions only) when confirm_basket cannot be
        # used (e.g. no triage run bound to this pipeline state).
        retained_ids = self._confirm_triage_basket(
            project_id, actor, state, retained_candidate_ids
        )
        if not retained_ids:
            return self._persist_no_retainable_candidate_fallback(
                project_id,
                state,
                error="no_retainable_candidates",
            )

        # --- preparing (download + extract) ---
        state = self._set_stage(
            state,
            "preparing",
            detail=f"已锁定候选 {len(retained_ids)} 项，正在核对公开Protocol范围…",
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)

        from packages.contracts.workbench_contracts.models import (
            WritingReferencePreparationBatchCreateRequest,
        )

        # Reuse a successful prep for this snapshot when force/re-run would
        # otherwise re-extract immutable artifacts ("immutable document
        # extraction changed") and fail the whole pipeline.
        reused_prep = self._find_reusable_preparation_batch(
            project_id, snapshot_id=snapshot_id, retained_ids=retained_ids
        )
        if reused_prep is not None:
            prep_batch = reused_prep
            state.prep_batch_id = prep_batch.batch_id
            state.detail = (
                f"{self._preparation_progress_detail(prep_batch)}；"
                f"复用已成功的原文准备批次 {prep_batch.batch_id}（跳过重复提取）"
            )
            state = self._persist(project_id, state)
            pulse(state.detail)
        else:
            prep_batch = self.preparation_batch_service.create(
                project_id,
                WritingReferencePreparationBatchCreateRequest(
                    snapshot_id=snapshot_id,
                    actor=actor,
                    # Stable across force re-runs of the same snapshot so
                    # create() can idempotently return the prior batch.
                    idempotency_key=f"pipe-prep-snap-{snapshot_id}",
                ),
            )
            state.prep_batch_id = prep_batch.batch_id
            state = self._persist(project_id, state)

            def report_preparation_progress(batch: Any) -> None:
                nonlocal state
                detail = self._preparation_progress_detail(batch)
                self._apply_child_progress(
                    state, **self._preparation_progress_projection(batch)
                )
                state.detail = detail
                state.eta_seconds = None
                state = self._persist(project_id, state)
                pulse(detail)

            self.preparation_batch_service.run_pending(
                project_id,
                prep_batch.batch_id,
                actor,
                progress_callback=report_preparation_progress,
            )
            self._wait_preparation(project_id, state, pulse)
            prep_batch = self._drain_deferred_preparation_stages(
                project_id,
                prep_batch.batch_id,
                actor=actor,
                progress_callback=report_preparation_progress,
            )

        # Document-content validation is a user-authority boundary. The
        # pipeline may batch-approve clean structure extraction, but it must
        # never turn a needs_review/mismatch content result into an override.
        admission = self._admit_prepared_public_documents(
            project_id,
            actor=actor,
            pipeline_id=state.pipeline_id,
            prep_batch_id=prep_batch.batch_id,
        )
        state.document_admission_blockers = [
            dict(item) for item in admission.blocked_documents
        ]
        state.document_admission_exclusions = [
            dict(item) for item in admission.excluded_documents
        ]
        if admission.blocked_documents:
            blocked_labels = [
                str(item.get("filename") or item.get("artifact_id") or "未命名文件")
                for item in admission.blocked_documents[:5]
            ]
            state = self._set_stage(
                state,
                "awaiting_document_validation",
                detail=(
                    f"{len(admission.blocked_documents)} 份Protocol尚未通过内容或结构准入："
                    f"{'、'.join(blocked_labels)}。请查看适应症、文档类型、研究标识、"
                    "版本/来源校验结果；如确认文件无误，可由用户明确覆盖后重试。"
                ),
                eta_seconds=None,
                error="document_admission_review_required",
            )
            return self._persist(project_id, state)
        if admission.admitted_count <= 0:
            state = self._set_stage(
                state,
                "awaiting_translation_scope",
                detail="本轮公开Protocol均未形成可用章节语料，请处理例外文件后重试。",
                eta_seconds=None,
                error="translation_scope_not_ready:no_admitted_documents",
            )
            return self._persist(project_id, state)
        exclusion_note = (
            f"；另有 {len(admission.excluded_documents)} 份例外文件已从本轮语料范围排除"
            if admission.excluded_documents
            else ""
        )
        state.detail = (
            f"已准入 {admission.admitted_count} 份内容校验通过的Protocol"
            f"{exclusion_note}，进入翻译。"
        )
        state = self._persist(project_id, state)

        return self._translate_analyze_and_finalize(
            project_id,
            actor=actor,
            state=state,
            snapshot_id=snapshot_id,
            heartbeat=heartbeat,
        )

    def _continue_from_prepared_batch(
        self,
        project_id: str,
        *,
        actor: str,
        state: ResearchPipelineState,
        prep_batch_id: str,
        resume_idempotency_key: str = "",
    ) -> ResearchPipelineState:
        """Recheck admission on an existing preparation batch, then continue."""
        journey = self.journey_service.get(project_id)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id if journey.search_plan else ""
        )
        if not snapshot_id:
            raise ResearchPipelineError("缺少检索快照，无法恢复翻译范围检查")

        # Verifies the persisted batch still exists.  Internal resource stages
        # are implementation batches, not user decisions: drain every pending
        # stage in the same immutable batch without replaying completed work.
        batch = self.preparation_batch_service.get(project_id, prep_batch_id)
        if int(getattr(batch, "deferred_item_count", 0) or 0) > 0:
            batch = self._drain_deferred_preparation_stages(
                project_id,
                prep_batch_id,
                actor=actor,
            )
        admission = self._admit_prepared_public_documents(
            project_id,
            actor=actor,
            pipeline_id=state.pipeline_id,
            prep_batch_id=prep_batch_id,
        )
        state.document_admission_blockers = [
            dict(item) for item in admission.blocked_documents
        ]
        state.document_admission_exclusions = [
            dict(item) for item in admission.excluded_documents
        ]
        if admission.blocked_documents:
            blocked_labels = [
                str(item.get("filename") or item.get("artifact_id") or "未命名文件")
                for item in admission.blocked_documents[:5]
            ]
            state = self._set_stage(
                state,
                "awaiting_document_validation",
                detail=(
                    f"{len(admission.blocked_documents)} 份Protocol尚未通过内容或结构准入："
                    f"{'、'.join(blocked_labels)}。请查看适应症、文档类型、研究标识、"
                    "版本/来源校验结果；如确认文件无误，可由用户明确覆盖后重试。"
                ),
                eta_seconds=None,
                error="document_admission_review_required",
            )
            return self._persist(project_id, state)
        if admission.admitted_count <= 0:
            state = self._set_stage(
                state,
                "awaiting_translation_scope",
                detail="本轮公开Protocol均未形成可用章节语料，请处理例外文件后重试。",
                eta_seconds=None,
                error="translation_scope_not_ready:no_admitted_documents",
            )
            return self._persist(project_id, state)

        exclusion_note = (
            f"；另有 {len(admission.excluded_documents)} 份例外文件已从本轮语料范围排除"
            if admission.excluded_documents
            else ""
        )
        state.detail = (
            f"已复核既有原文准备批次 {prep_batch_id}；"
            f"{admission.admitted_count} 份Protocol可进入翻译"
            f"{exclusion_note}。"
        )
        state = self._persist(project_id, state)
        return self._translate_analyze_and_finalize(
            project_id,
            actor=actor,
            state=state,
            snapshot_id=snapshot_id,
            # A user-resolved waiting-stage retry is an explicit new attempt;
            # it may create a new immutable translation batch lineage.  The
            # durable parent retry path does not come through this method.
            allow_new_translation_batch=bool(resume_idempotency_key),
            translation_retry_key=resume_idempotency_key,
        )

    def _drain_deferred_preparation_stages(
        self,
        project_id: str,
        prep_batch_id: str,
        *,
        actor: str,
        progress_callback: Callable[[Any], None] | None = None,
    ) -> Any:
        """Run bounded preparation stages continuously after basket approval.

        Stage size remains the worker's resource-control mechanism.  It no
        longer creates a repeated user gate because no scientific choice is
        made between stages.  The stable stage idempotency key and the existing
        batch preserve completed download/OCR work across retries and restarts.
        """

        stage_advancer = getattr(
            self.preparation_batch_service, "admit_next_stage", None
        )
        if not callable(stage_advancer):
            raise ResearchPipelineError(
                "既有原文准备批次仍有延后项，但当前服务不支持阶段准入"
            )
        from packages.contracts.workbench_contracts.models import (
            WritingReferencePreparationBatchStageAdvanceRequest,
        )

        batch = self.preparation_batch_service.get(project_id, prep_batch_id)
        while int(getattr(batch, "deferred_item_count", 0) or 0) > 0:
            previous_deferred = int(
                getattr(batch, "deferred_item_count", 0) or 0
            )
            stage_index = int(
                getattr(batch, "admission_stage_index", 1) or 1
            )
            batch = stage_advancer(
                project_id,
                prep_batch_id,
                WritingReferencePreparationBatchStageAdvanceRequest(
                    actor=actor,
                    idempotency_key=(
                        f"pipeline-preparation-stage:{prep_batch_id}:"
                        f"{stage_index}:automatic"
                    ),
                ),
            )
            self.preparation_batch_service.run_pending(
                project_id,
                prep_batch_id,
                actor,
                progress_callback=progress_callback,
            )
            batch = self.preparation_batch_service.get(project_id, prep_batch_id)
            remaining = int(getattr(batch, "deferred_item_count", 0) or 0)
            if remaining >= previous_deferred:
                raise ResearchPipelineError(
                    "原文准备下一批未产生进展；已保留完成项，请从当前批次恢复"
                )
        return batch

    def _pause_for_deferred_preparation_stage(
        self,
        project_id: str,
        state: ResearchPipelineState,
        prep_batch_id: str,
    ) -> ResearchPipelineState | None:
        """Persist a truthful user wait when more bounded prep remains."""

        batch = self.preparation_batch_service.get(project_id, prep_batch_id)
        deferred_count = int(getattr(batch, "deferred_item_count", 0) or 0)
        if deferred_count <= 0:
            return None
        stage_index = int(getattr(batch, "admission_stage_index", 1) or 1)
        stage_size = int(getattr(batch, "admission_stage_size", 8) or 8)
        completed_count = int(getattr(batch, "completed_document_count", 0) or 0)
        state = self._set_stage(
            state,
            "awaiting_preparation_admission",
            detail=(
                f"原文准备第 {stage_index} 阶段已完成 {completed_count} 份；"
                f"仍有 {deferred_count} 份公开Protocol待下一阶段准入。"
                f"每次最多准入 {stage_size} 份，已完成项不会重复下载或OCR。"
            ),
            eta_seconds=None,
            error="preparation_stage_admission_required",
        )
        return self._persist(project_id, state)

    def _translate_analyze_and_finalize(
        self,
        project_id: str,
        *,
        actor: str,
        state: ResearchPipelineState,
        snapshot_id: str,
        heartbeat: Callable[[DurableJobProgressPayload], bool] | None = None,
        allow_new_translation_batch: bool = False,
        translation_retry_key: str = "",
    ) -> ResearchPipelineState:
        """Continue from admitted source documents through round-1 analysis."""

        def pulse(detail: str) -> None:
            if heartbeat is None:
                return
            if not heartbeat(_progress_payload(state, detail)):
                raise ResearchPipelineError("pipeline cancelled or lease lost")

        state = self._set_stage(
            state,
            "translating",
            detail="正在翻译关键章节（目的终点/入排/流程/安全性）…",
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)
        try:
            start_translation = self._start_translation_batch
            start_args = (
                project_id,
                actor,
                state.pipeline_id,
                snapshot_id,
                state.translation_batch_id,
            )
            if "allow_new_batch" in inspect.signature(start_translation).parameters:
                start_kwargs = {
                    "allow_new_batch": allow_new_translation_batch,
                }
                if "retry_idempotency_key" in inspect.signature(
                    start_translation
                ).parameters:
                    start_kwargs["retry_idempotency_key"] = translation_retry_key
                translation = start_translation(*start_args, **start_kwargs)
            else:
                # Keep narrow test doubles and older adapters source-compatible
                # while the production method gains automatic-retry lineage
                # protection.
                translation = start_translation(*start_args)
            state.translation_batch_id = str(translation.get("batch_id") or "")
            state = self._persist(project_id, state)
            state = self._refresh_progress_projection(project_id, state)
            self._wait_translation(project_id, state, pulse)
        except ValueError as exc:
            state = self._set_stage(
                state,
                "awaiting_translation_scope",
                detail=f"翻译范围尚未就绪：{exc}。请处理提示后重试研究流水线。",
                eta_seconds=None,
                error=f"translation_scope_not_ready:{exc}",
            )
            return self._persist(project_id, state)

        state = self._set_stage(
            state,
            "analyzing_round1",
            detail="正在基于已提取/翻译的方案正文生成第一轮竞品设计深析…",
            eta_seconds=None,
        )
        state = self._persist(project_id, state)
        pulse(state.detail)
        brief_ids = self._run_round1_analysis(project_id, actor, state)
        state.round1_brief_ids = brief_ids
        if not brief_ids or not state.round1_analysis_id:
            raise ResearchPipelineError(
                "产品独立AI未形成可持久审计的证据化竞品Protocol语料分析"
            )

        try:
            self.corpus_readiness_service.recalculate(project_id, actor=actor)
        except Exception as exc:  # noqa: BLE001
            state.detail = f"语料就绪重算提示：{exc}"

        journey = self.journey_service.get(project_id)
        gate = journey.corpus_gate
        gate_ready = (
            gate is not None
            and str(getattr(gate, "readiness_status", "") or "") == "ready"
            and not bool(getattr(getattr(gate, "override", None), "active", False))
        )
        if gate_ready:
            state = self._set_stage(
                state,
                "corpus_ready",
                detail="语料已就绪，可生成证据化研究设计推荐。",
            )
            state = self._persist(project_id, state)
            self._notify_corpus_ready(project_id)
            return state

        missing = (
            ",".join(list(getattr(gate, "missing_requirements", None) or [])[:5])
            if gate
            else "corpus_gate_missing"
        )
        material_ready, material_detail = self._round1_material_ready(
            project_id, journey, state
        )
        state.round1_material_ready = material_ready
        detail = (
            "原文下载/提取/翻译/一轮分析已跑完，但完整语料门尚未满足："
            f"{missing}。请完成医学准入与PICOS对齐后重算。"
        )
        if material_ready:
            if material_detail == "material_ready_source_only":
                detail += (
                    "已满足第一轮研究材料最低条件（分诊固化+至少一份Protocol结构化+"
                    "关键锚点英文原文可追溯），已开放证据化设计推荐；专用翻译服务"
                    "恢复后可补充受控中文译文，完整医学准入与PICOS对齐仍需补齐。"
                )
            else:
                detail += (
                    "已满足第一轮研究材料最低条件（分诊固化+至少一份Protocol结构化+"
                    "关键锚点翻译通过），已开放证据化设计推荐；完整医学准入与"
                    "PICOS对齐仍需补齐。"
                )
        else:
            detail += f"第一轮研究材料尚未齐备（{material_detail}），设计推荐仍锁定。"
        state = self._set_stage(
            state,
            "awaiting_corpus_admission",
            detail=detail,
            error=f"corpus_not_ready:{missing}",
        )
        return self._persist(project_id, state)

    def _confirm_triage_basket(
        self,
        project_id: str,
        actor: str,
        state: ResearchPipelineState,
        retained_override: list[str] | None,
    ) -> list[str]:
        """Confirm the AI-recommended (or medical-manager-adjusted) basket.

        Prefers ``CompetitorTriageService.confirm_basket`` — the real single
        user-decision action that writes relevance decisions AND projects
        discovery-basket (pre-PICOS) or finalized corpus triage (post-PICOS)
        from the run's own classifications, in one authoritative step. Falls
        back to the legacy ``corpus_readiness_service.finalize_triage`` path
        (which requires relevance decisions to already exist) when
        confirm_basket cannot be used — e.g. no triage run is bound to this
        pipeline state, or the run cannot be confirmed for some other reason.

        Returns the retained candidate NCT ids (empty when nothing could be
        retained/confirmed by either path).
        """
        from packages.contracts.workbench_contracts import (
            CompetitorTriageBasketConfirmationRequest,
            CompetitorTriageChunkStatus,
            CompetitorTriageClassification,
        )

        journey = self.journey_service.get(project_id)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id if journey.search_plan else ""
        )
        repo = self.triage_service.repository
        confirm_basket = getattr(self.triage_service, "confirm_basket", None)
        run = None
        if state.triage_run_id:
            try:
                run = repo.triage_run(project_id, state.triage_run_id)
            except Exception:  # noqa: BLE001
                run = None

        if run is not None and callable(confirm_basket):
            try:
                snapshot = repo.search_snapshot(project_id, run.snapshot_id)
                candidate_ids = {c.nct_id for c in snapshot.candidates}
                with_public_docs = {
                    c.nct_id
                    for c in snapshot.candidates
                    if self._candidate_has_public_protocol(c)
                }
                classification_map: dict[str, CompetitorTriageClassification] = {}
                for chunk in run.chunks:
                    if chunk.status != CompetitorTriageChunkStatus.SUCCEEDED:
                        continue
                    for result in chunk.results:
                        classification_map[result.nct_id] = result.classification
                if retained_override is not None:
                    # Explicit medical-manager override may include manual-upload
                    # studies; still prefer public-doc NCTs when the override is
                    # empty so the download→extract path can run.
                    retained_set = {
                        nct_id for nct_id in retained_override if nct_id in candidate_ids
                    }
                    if not retained_set:
                        retained_set = self._select_retain_with_public_docs(
                            recommended=set(run.recommended_retain),
                            with_public_docs=with_public_docs,
                            classification_map=classification_map,
                        )
                else:
                    # Research pipeline auto-confirm: NEVER retain NCT without a
                    # public Protocol — otherwise prep only emits
                    # study_manual_upload_required and design stays locked forever.
                    retained_set = self._select_retain_with_public_docs(
                        recommended=set(run.recommended_retain),
                        with_public_docs=with_public_docs,
                        classification_map=classification_map,
                    )
                excluded_set = candidate_ids - retained_set
                final_classifications: dict[str, CompetitorTriageClassification] = {}
                for nct_id in candidate_ids:
                    if nct_id in retained_set:
                        known = classification_map.get(nct_id)
                        final_classifications[nct_id] = (
                            known
                            if known
                            in (
                                CompetitorTriageClassification.DIRECT_COMPETITOR,
                                CompetitorTriageClassification.INDIRECT_REFERENCE,
                            )
                            else CompetitorTriageClassification.DIRECT_COMPETITOR
                        )
                    else:
                        final_classifications[nct_id] = (
                            CompetitorTriageClassification.EXCLUDED
                        )
                no_suitable_reason = (
                    "检索结果中无可下载公开 Protocol 的竞品，研究流水线无法自动"
                    "下载原文；请上传纸质/内部方案或调整检索后重跑。"
                    if not retained_set
                    else ""
                )
                confirm_basket(
                    project_id,
                    run.run_id,
                    CompetitorTriageBasketConfirmationRequest(
                        expected_run_revision=run.canonical_input_hash,
                        retained_nct_ids=sorted(retained_set),
                        excluded_nct_ids=sorted(excluded_set),
                        final_classifications=final_classifications,
                        no_suitable_competitor_reason=no_suitable_reason,
                        actor=actor,
                        reason="研究流水线确认AI分诊建议的竞品篮子，以便下载原文并进入提取与翻译。",
                        idempotency_key=f"pipe-confirm-{state.pipeline_id}",
                        expected_journey_revision=self.journey_service.get(
                            project_id
                        ).revision,
                    ),
                )
                return sorted(retained_set)
            except Exception as exc:  # noqa: BLE001 — fall back to legacy finalize path
                state.detail = (
                    f"竞品篮子确认提示（回退固化路径）：{type(exc).__name__}: {exc}"
                )

        retained_ids = (
            list(retained_override)
            if retained_override
            else self._auto_retain_public_protocol_candidates(project_id, snapshot_id)
        )
        if not retained_ids:
            return []
        try:
            from packages.contracts.workbench_contracts import (
                MedicalWritingCorpusTriageFinalizeRequest,
            )

            self.corpus_readiness_service.finalize_triage(
                project_id,
                MedicalWritingCorpusTriageFinalizeRequest(
                    snapshot_id=snapshot_id,
                    retained_candidate_ids=list(retained_ids),
                    actor=actor,
                    reason=(
                        "研究流水线回退路径：基于既有相关性决策固化竞品分诊，"
                        "以便下载原文并进入提取与翻译。"
                    ),
                    idempotency_key=f"pipe-finalize-{state.pipeline_id}",
                    expected_revision=self.journey_service.get(project_id).revision,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — continue to prep; readiness recalculates later
            state.detail = f"分诊固化提示：{type(exc).__name__}: {exc}"
        return retained_ids

    def _round1_material_ready(
        self,
        project_id: str,
        journey: MedicalWritingAuthoringJourney,
        state: ResearchPipelineState,
    ) -> tuple[bool, str]:
        """Conservative round-1-only unlock check (never an override).

        True only when ALL of:
          - competitor scope is confirmed for the current snapshot, through
            either the pre-PICOS discovery basket or post-PICOS finalized
            corpus triage, with at least one retained candidate;
          - at least one protocol has been extracted/validated — read from
            the corpus gate's own ``protocol_structure`` requirement status
            when available (identical semantics to the corpus gate itself);
          - critical-anchor evidence is available from a fidelity-passed
            translation, or from at least two validated original-language
            anchors when the dedicated body translator is unavailable. The
            corpus analysis always quotes the original source text; translation
            remains an aid rather than a prerequisite for scientific review.
          - the frozen product independent-AI route produced an immutable,
            evidence-bound round-1 analysis artifact with at least one
            validated evidence summary. A marker, skeleton, override, or
            status-only stamp never satisfies this condition.
        """
        reasons: list[str] = []
        unavailable_reasons: list[str] = []
        persisted_ready = bool(state.round1_material_ready)
        triage = getattr(journey, "corpus_triage", None)
        discovery = getattr(journey, "discovery_basket_projection", None)
        snapshot_id = state.snapshot_id or (
            journey.search_plan.latest_snapshot_id if journey.search_plan else ""
        )
        triage_finalized = bool(
            triage is not None
            and str(getattr(triage, "status", "")) == "finalized"
            and (not snapshot_id or getattr(triage, "snapshot_id", "") == snapshot_id)
            and list(getattr(triage, "retained_candidate_ids", None) or [])
        )
        discovery_confirmed = bool(
            discovery is not None
            and str(getattr(discovery, "confirmation_id", "") or "")
            and (not snapshot_id or getattr(discovery, "snapshot_id", "") == snapshot_id)
            and list(getattr(discovery, "retained_nct_ids", None) or [])
        )
        triage_authority_ready = triage_finalized or discovery_confirmed
        if not triage_authority_ready:
            reasons.append("competitor_scope_not_confirmed")
            if persisted_ready and triage is None and discovery is None:
                unavailable_reasons.append("competitor_scope_evidence_missing")

        gate = getattr(journey, "corpus_gate", None)
        if gate is None and persisted_ready:
            unavailable_reasons.append("corpus_gate_missing")
        elif (
            persisted_ready
            and gate is not None
            and not list(getattr(gate, "requirements", None) or [])
        ):
            unavailable_reasons.append("corpus_gate_requirements_missing")
        requirement_by_code = (
            {item.code: item for item in (getattr(gate, "requirements", None) or [])}
            if gate is not None
            else {}
        )
        protocol_requirement = requirement_by_code.get("protocol_structure")
        protocol_ready = bool(protocol_requirement and protocol_requirement.satisfied)
        batch_items: list[Any] = []
        translation_ready = False
        source_only_anchors: set[str] = set()
        if state.translation_batch_id:
            try:
                batch = self.translation_batch_service.get(
                    project_id, state.translation_batch_id
                )
            except Exception:  # noqa: BLE001
                batch = None
                if persisted_ready:
                    unavailable_reasons.append("translation_batch_unavailable")
            if batch is not None:
                batch_items = list(getattr(batch, "items", None) or [])
                translation_ready = any(
                    str(getattr(item, "ich_m11_anchor", "")) in CRITICAL_ANCHORS
                    and (
                        str(getattr(item, "generation_status", "")) == "candidate_ready"
                        or str(getattr(item, "fidelity_status", "")) == "passed"
                    )
                    for item in batch_items
                )
                source_only_anchors = self._source_only_critical_anchors(batch)
            elif persisted_ready and "translation_batch_unavailable" not in unavailable_reasons:
                unavailable_reasons.append("translation_batch_missing")
        elif persisted_ready:
            unavailable_reasons.append("translation_batch_id_missing")
        if not protocol_ready:
            # Translation scope is created only after the document gate freezes
            # content validation and structure-review lineage. This is a
            # stronger pre-PICOS proof than a stale corpus-gate projection and
            # does not admit an unvalidated or unstructured document.
            protocol_ready = any(
                str(getattr(item, "document_type", "") or "").casefold()
                == "protocol"
                and str(getattr(item, "validation_status", "") or "")
                in {"confirmed", "user_overridden"}
                and bool(str(getattr(item, "structure_review_id", "") or ""))
                and int(getattr(item, "structure_review_revision", 0) or 0) >= 1
                for item in batch_items
            )
        if not protocol_ready:
            reasons.append("protocol_structure_not_satisfied")
        source_only_ready = len(source_only_anchors) >= 2
        if not translation_ready and not source_only_ready:
            reasons.append("critical_anchor_evidence_not_ready")

        analysis_ready = bool(
            state.round1_analysis_id
            and state.round1_analysis_output_hash
            and state.round1_brief_ids
            and state.round1_ai_route
        )
        if not analysis_ready:
            reasons.append("evidence_bound_round1_analysis_missing")
            if persisted_ready:
                unavailable_reasons.append("round1_analysis_evidence_missing")

        ready = (
            triage_authority_ready
            and protocol_ready
            and (translation_ready or source_only_ready)
            and analysis_ready
        )
        if ready:
            return (
                True,
                "material_ready"
                if translation_ready
                else "material_ready_source_only",
            )
        detail = ",".join(reasons) if reasons else "material_not_ready"
        if unavailable_reasons:
            return (
                False,
                "evidence_unavailable:"
                + ",".join(sorted(set(unavailable_reasons)))
                + "|"
                + detail,
            )
        return False, detail

    @staticmethod
    def _candidate_has_public_protocol(candidate: Any) -> bool:
        docs = getattr(candidate, "public_documents", None) or []
        return any(
            str(getattr(doc, "document_type", "") or "").strip().casefold()
            in {"protocol", "sap", "protocol_sap"}
            for doc in docs
        )

    @staticmethod
    def _select_retain_with_public_docs(
        *,
        recommended: set[str],
        with_public_docs: set[str],
        classification_map: dict[str, Any],
        limit: int = 12,
    ) -> set[str]:
        """Pick retain set that can actually download Protocol PDFs.

        Priority:
        1) AI recommended ∩ public docs
        2) AI direct/indirect ∩ public docs
        3) any public-doc candidate (research cannot proceed without material)
        """
        from packages.contracts.workbench_contracts import CompetitorTriageClassification

        preferred = recommended & with_public_docs
        if preferred:
            return set(sorted(preferred)[:limit])
        classified_ok = {
            nct_id
            for nct_id, classification in classification_map.items()
            if nct_id in with_public_docs
            and classification
            in (
                CompetitorTriageClassification.DIRECT_COMPETITOR,
                CompetitorTriageClassification.INDIRECT_REFERENCE,
            )
        }
        if classified_ok:
            return set(sorted(classified_ok)[:limit])
        return set(sorted(with_public_docs)[:limit])

    def _auto_retain_public_protocol_candidates(
        self, project_id: str, snapshot_id: str
    ) -> list[str]:
        repo = self.triage_service.repository
        snapshot = repo.search_snapshot(project_id, snapshot_id)
        decisions = {
            item.nct_id: item
            for item in repo.relevance_decisions_for_snapshot(project_id, snapshot_id)
        }
        retained: list[str] = []
        for candidate in snapshot.candidates:
            decision = decisions.get(candidate.nct_id)
            if decision is None:
                continue
            if decision.relevance_status not in {
                "direct_competitor",
                "indirect_reference",
            }:
                continue
            if self._candidate_has_public_protocol(candidate):
                retained.append(candidate.nct_id)
        if retained:
            return retained[:20]
        # Fallback: any snapshot candidate with public Protocol.
        return [
            c.nct_id
            for c in snapshot.candidates
            if self._candidate_has_public_protocol(c)
        ][:12]

    def _admit_prepared_public_documents(
        self,
        project_id: str,
        *,
        actor: str,
        pipeline_id: str,
        prep_batch_id: str,
    ) -> PreparedDocumentAdmissionResult:
        """Admit validated public docs and batch-approve clean extraction structure.

        Content validation is never changed here. Only documents already in
        ``confirmed`` or ``user_overridden`` state may receive an automatic
        clean-structure approval and proceed to translation.
        """
        repo = getattr(self.preparation_batch_service, "repository", None)
        if repo is None:
            raise ResearchPipelineError(
                "原文准备服务未提供文档准入仓储，无法确认翻译输入"
            )
        batch = self.preparation_batch_service.get(project_id, prep_batch_id)
        items = getattr(batch, "items", None) or []
        admitted = 0
        blocked: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []

        def issue_payload(
            item: Any,
            *,
            artifact_id: str,
            status: str,
            reason_code: str,
            detail: str,
            validation: Any | None = None,
            required_action: str = "",
        ) -> dict[str, Any]:
            checks = []
            if validation is not None:
                checks = [
                    {
                        "check_code": str(getattr(check, "check_code", "") or ""),
                        "label": str(getattr(check, "label", "") or ""),
                        "expected_value": str(
                            getattr(check, "expected_value", "") or ""
                        ),
                        "observed_value": str(
                            getattr(check, "observed_value", "") or ""
                        ),
                        "outcome": str(getattr(check, "outcome", "") or ""),
                    }
                    for check in (getattr(validation, "checks", None) or [])
                    if getattr(check, "outcome", "") in {"warning", "mismatch"}
                ]
            return {
                "artifact_id": artifact_id,
                "nct_id": str(getattr(item, "nct_id", "") or ""),
                "filename": str(getattr(item, "filename", "") or ""),
                "document_type": str(getattr(item, "document_type", "") or ""),
                "validation_status": status,
                "reason_code": reason_code,
                "detail": detail,
                "checks": checks,
                "required_action": required_action,
            }

        def add_blocker(item: Any, **kwargs: Any) -> None:
            blocked.append(
                issue_payload(
                    item,
                    **kwargs,
                    required_action=(
                        "请用户核对基本内容校验；确认文件适用于当前研究时，"
                        "可明确覆盖后重试。"
                    ),
                )
            )

        def add_exclusion(item: Any, **kwargs: Any) -> None:
            excluded.append(
                issue_payload(
                    item,
                    **kwargs,
                    required_action=(
                        "系统已从本轮章节语料范围排除；如需纳入，请先修复结构提取后重试。"
                    ),
                )
            )

        for index, item in enumerate(items):
            if str(getattr(item, "item_kind", "") or "") != "public_document":
                continue
            artifact_id = str(getattr(item, "artifact_id", "") or "")
            extraction_revision = str(getattr(item, "extraction_revision", "") or "")
            if not artifact_id or not extraction_revision:
                add_blocker(
                    item,
                    artifact_id=artifact_id,
                    status="missing",
                    reason_code="prepared_document_incomplete",
                    detail="原文准备项缺少当前文档或结构提取版本，不能进入翻译。",
                )
                continue
            try:
                validation = repo.document_validation(project_id, artifact_id)
            except KeyError:
                add_blocker(
                    item,
                    artifact_id=artifact_id,
                    status="missing",
                    reason_code="document_validation_missing",
                    detail="尚无当前文档的基本内容校验结果。",
                )
                continue
            status = str(getattr(validation, "status", "") or "")
            if status not in {"confirmed", "user_overridden"}:
                add_blocker(
                    item,
                    artifact_id=artifact_id,
                    status=status or "unknown",
                    reason_code="document_validation_not_confirmed",
                    detail=(
                        "基本内容校验尚未确认，系统不会自动覆盖适应症、文档类型、"
                        "研究标识或版本/来源不一致提示。"
                    ),
                    validation=validation,
                )
                continue

            artifact = repo.document_artifact(project_id, artifact_id)
            if (
                not bool(getattr(artifact, "source_current", False))
                or str(getattr(validation, "document_sha256", "") or "")
                != str(getattr(artifact, "content_sha256", "") or "")
                or int(getattr(validation, "source_state_revision", 0) or 0)
                != int(getattr(artifact, "state_revision", 0) or 0)
                or str(getattr(validation, "extraction_revision", "") or "")
                != extraction_revision
            ):
                add_blocker(
                    item,
                    artifact_id=artifact_id,
                    status=status,
                    reason_code="document_validation_stale",
                    detail="文档内容、来源版本或结构提取版本已变化，需要重新校验。",
                    validation=validation,
                )
                continue

            # Approve structure review for all mapped M11 anchors present in extraction.
            spans = repo.source_spans(
                project_id,
                artifact_id,
                extraction_revision=extraction_revision,
            )
            anchors = sorted(
                {
                    span.ich_m11_anchor
                    for span in spans
                    if span.ich_m11_anchor and span.ich_m11_anchor != "unmapped"
                }
            )
            if not anchors:
                add_exclusion(
                    item,
                    artifact_id=artifact_id,
                    status=status,
                    reason_code="structure_anchor_missing",
                    detail="结构提取未形成可确认的 ICH M11 章节锚点。",
                    validation=validation,
                )
                continue

            reviews = [
                review
                for review in repo.extraction_reviews(
                    project_id, artifact_id=artifact_id
                )
                if getattr(review, "extraction_revision", "") == extraction_revision
            ]
            if reviews:
                current_review = max(
                    reviews, key=lambda review: int(getattr(review, "revision", 0) or 0)
                )
                if (
                    getattr(current_review, "decision", "") == "approved"
                    and not (
                        getattr(current_review, "unresolved_structure_issues", None)
                        or []
                    )
                ):
                    admitted += 1
                    continue
                add_exclusion(
                    item,
                    artifact_id=artifact_id,
                    status=status,
                    reason_code="structure_review_required",
                    detail=(
                        "结构提取仍有未解决问题，必须先完成结构修订/复核；"
                        "文档内容覆盖不能解决结构问题。"
                    ),
                    validation=validation,
                )
                continue

            # No prior structure review and no unresolved issue: batch approval
            # is allowed because all mapped anchors are confirmed together.
            try:
                repo.record_extraction_review(
                    project_id=project_id,
                    artifact_id=artifact_id,
                    extraction_revision=extraction_revision,
                    decision="approved",
                    confirmed_anchor_coverage=anchors,
                    unresolved_structure_issues=[],
                    comment=(
                        "研究流水线自动确认结构化提取：公开Protocol已映射至ICH M11"
                        f"锚点（{', '.join(anchors)}），可进入关键章节翻译。"
                    ),
                    actor=actor,
                    expected_revision=0,
                    idempotency_key=f"pipe-admit-struct-{pipeline_id}-{artifact_id}-{index}",
                )
                admitted += 1
            except Exception as exc:  # noqa: BLE001
                # A concurrent clean approval is safe to reuse. Any other
                # failure is explicit and retryable; do not continue as if the
                # document were admitted.
                reviews = repo.extraction_reviews(
                    project_id, artifact_id=artifact_id
                )
                if any(
                    getattr(review, "extraction_revision", "") == extraction_revision
                    and getattr(review, "decision", "") == "approved"
                    and not (
                        getattr(review, "unresolved_structure_issues", None) or []
                    )
                    for review in reviews
                ):
                    admitted += 1
                else:
                    raise ResearchPipelineError(
                        f"公开原文结构确认失败 {artifact_id}: {exc}"
                    ) from exc
        if admitted > 0 and blocked:
            excluded.extend(blocked)
            blocked = []
        return PreparedDocumentAdmissionResult(
            admitted_count=admitted,
            # A single unusable public document must not hold the entire corpus
            # hostage when other evidence is admissible. Structure failures are
            # always corpus exclusions; content conflicts require user action
            # only when no clean public source remains.
            blocked_documents=tuple(blocked),
            excluded_documents=tuple(excluded),
        )

    def _find_reusable_preparation_batch(
        self,
        project_id: str,
        *,
        snapshot_id: str,
        retained_ids: list[str],
    ):
        """Return a prior successful prep batch for the same snapshot/retain set.

        Force/re-run otherwise re-extracts immutable artifacts and fails with
        ``immutable document extraction changed``.
        """
        getter = getattr(self.preparation_batch_service, "get", None)
        if not callable(getter):
            return None
        wanted = sorted(str(x) for x in retained_ids)
        repo = getattr(self.preparation_batch_service, "repository", None)
        if repo is None or not hasattr(repo, "_connect"):
            return None
        try:
            with repo._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT batch_id, status, retained_candidate_ids_json
                    FROM writing_reference_preparation_batches
                    WHERE project_id=? AND snapshot_id=?
                    ORDER BY updated_at DESC
                    """,
                    (project_id, snapshot_id),
                ).fetchall()
        except Exception:
            return None
        for row in rows:
            batch_id = row["batch_id"] if hasattr(row, "keys") else row[0]
            status = str(row["status"] if hasattr(row, "keys") else row[1] or "")
            retained_json = (
                row["retained_candidate_ids_json"]
                if hasattr(row, "keys")
                else row[2]
            )
            if status == "failed" or status not in PREPARATION_BATCH_TERMINAL_STATUSES:
                continue
            try:
                retained = json.loads(retained_json or "[]")
            except Exception:
                retained = []
            if sorted(str(x) for x in retained) != wanted:
                continue
            try:
                return getter(project_id, batch_id)
            except Exception:
                continue
        return None

    def _wait_preparation(
        self,
        project_id: str,
        state: ResearchPipelineState,
        pulse: Callable[[str], None],
    ) -> None:
        """Poll the real preparation-batch status until terminal.

        ``run_pending`` (called by the caller before this) is synchronous —
        it performs the downloads/extraction inline — so by the time this is
        reached the batch should already be terminal. The poll loop is kept
        as the real source of truth (and a safety net if that ever changes)
        rather than assuming completion.
        """
        if not state.prep_batch_id:
            return
        getter = getattr(self.preparation_batch_service, "get", None)
        if not callable(getter):
            return
        deadline = time.time() + 600
        while time.time() < deadline:
            batch = getter(project_id, state.prep_batch_id)
            payload = (
                batch.model_dump(mode="json") if hasattr(batch, "model_dump") else dict(batch or {})
            )
            status = str(payload.get("status") or "")
            detail = self._preparation_progress_detail(batch)
            self._apply_child_progress(
                state, **self._preparation_progress_projection(batch)
            )
            if detail != state.detail:
                pulse(detail)
            if status == "awaiting_stage_admission":
                return
            if status in PREPARATION_BATCH_TERMINAL_STATUSES:
                if status == "failed":
                    # Structured-evidence branch (plan A): the preparation
                    # batch failed (e.g. scanned PDF needing OCR without a
                    # key).  Instead of hard-failing the pipeline, advance
                    # to awaiting_corpus_analysis so the AI can work with
                    # the search snapshot's structured data directly.
                    state.stage = "awaiting_corpus_analysis"
                    state.detail = "原文准备失败（结构化证据模式）：跳过文档深度处理，以检索快照结构化数据进入corpus analysis"
                    self._persist(project_id, state)
                    return
                return
            time.sleep(2.0)
        raise ResearchPipelineError("原文准备超时")

    @staticmethod
    def _preparation_progress_detail(batch: Any) -> str:
        payload = _payload_dict(batch)

        retained_ids = list(payload.get("retained_candidate_ids") or [])
        retained_count = payload.get("retained_candidate_count")
        if retained_count is None:
            retained_count = len(retained_ids)

        items = list(payload.get("items") or [])
        item_payloads = [
            (
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else dict(item)
                if isinstance(item, dict)
                else vars(item)
            )
            for item in items
        ]
        public_documents = [
            item
            for item in item_payloads
            if str(item.get("item_kind") or "") == "public_document"
        ]
        document_count = payload.get("document_item_count")
        if document_count is None:
            document_count = len(public_documents)
        completed_count = payload.get("completed_document_count")
        if completed_count is None:
            completed_count = sum(
                str(item.get("status") or "")
                in {"prepared", "review_required", "failed"}
                for item in public_documents
            )

        detail = (
            f"锁定候选 {int(retained_count)} 项、"
            f"公开文档 {int(document_count)} 份、"
            f"已完成 {int(completed_count)} 份"
        )
        deferred_count = int(payload.get("deferred_item_count") or 0)
        if deferred_count:
            stage_index = int(payload.get("admission_stage_index") or 1)
            detail += f"；第 {stage_index} 阶段后延后 {deferred_count} 份"
        progress = _payload_dict(payload.get("progress") or {})
        progress_context = _payload_dict(progress.get("context") or {})
        current_item_id = str(
            progress_context.get("item_id")
            or payload.get("current_item_id")
            or ""
        )
        running = next(
            (
                item
                for item in public_documents
                if str(item.get("item_id") or "") == current_item_id
                and str(item.get("status") or "") == "running"
            ),
            None,
        ) or next(
            (
                item
                for item in public_documents
                if str(item.get("status") or "") == "running"
            ),
            None,
        )
        if running is not None:
            nct_id = str(running.get("nct_id") or "未知研究")
            document_label = str(
                running.get("filename")
                or running.get("document_id")
                or running.get("document_type")
                or "未命名文档"
            )
            detail += f"；正在处理 {nct_id} / {document_label}"
            substep = str(progress.get("current_substep") or "")
            completed = int(progress.get("completed") or 0)
            total = int(progress.get("total") or 0)
            if substep:
                detail += f"；{substep}"
            if total:
                unit = str(progress.get("unit") or "")
                detail += (
                    f"；已完成 {completed}/{total} 个需识别页面"
                    if unit == "page"
                    and str(progress.get("phase") or "").startswith("ocr_")
                    else f"（{completed}/{total}）"
                )
        failed_count = int(payload.get("failed_count") or 0)
        if running is None and failed_count:
            detail += f"；失败 {failed_count} 份"
        return detail

    @staticmethod
    def _preparation_progress_projection(batch: Any) -> dict[str, Any]:
        payload = _payload_dict(batch)
        items = [_payload_dict(item) for item in list(payload.get("items") or [])]
        public_documents = [
            item for item in items if str(item.get("item_kind") or "") == "public_document"
        ]
        total = int(payload.get("document_item_count") or len(public_documents))
        completed_value = payload.get("completed_document_count")
        completed = int(
            completed_value
            if completed_value is not None
            else sum(
                str(item.get("status") or "")
                in {"prepared", "review_required", "failed"}
                for item in public_documents
            )
        )
        raw_batch_progress = payload.get("progress")
        batch_progress = _payload_dict(raw_batch_progress or {})
        progress_context = _payload_dict(batch_progress.get("context") or {})
        current_item_id = str(
            progress_context.get("item_id")
            or payload.get("current_item_id")
            or ""
        )
        running = next(
            (
                item
                for item in public_documents
                if str(item.get("item_id") or "") == current_item_id
                and str(item.get("status") or "") == "running"
            ),
            None,
        ) or next(
            (
                item
                for item in public_documents
                if str(item.get("status") or "") == "running"
            ),
            None,
        )
        current = running or next(
            (
                item
                for item in public_documents
                if str(item.get("status") or "") == "pending"
            ),
            None,
        ) or next(
            (
                item
                for item in public_documents
                if str(item.get("status") or "") == "failed"
            ),
            None,
        )
        item_progress: dict[str, Any] = {}
        substep = str(batch_progress.get("current_substep") or "")
        if current:
            nct_id = str(current.get("nct_id") or "未知研究")
            document_label = str(
                current.get("filename")
                or current.get("document_id")
                or current.get("document_type")
                or "未命名文档"
            )
            progress = batch_progress
            item_progress = _payload_dict(current.get("progress") or {})
            substep = str(
                item_progress.get("current_substep")
                or progress.get("current_substep")
                or ""
            )
            completed_value = progress.get("completed")
            total_value = progress.get("total")
            item_percent = item_progress.get("percent")
            item_unit = str(
                item_progress.get("unit") or progress.get("unit") or ""
            )
            progress_suffix = ""
            if substep:
                progress_suffix += f"；{substep}"
            if total_value:
                progress_suffix += (
                    f"；已完成 {int(completed_value or 0)}/{int(total_value)} 个需识别页面"
                    if item_unit == "page"
                    and str(progress.get("phase") or "").startswith("ocr_")
                    else f"（{int(completed_value or 0)}/{int(total_value)}）"
                )
            if item_percent is not None and substep:
                progress_suffix += f" · 子步骤 {max(0, min(100, int(item_percent)))}%"
            action = "处理失败" if str(current.get("status") or "") == "failed" else "正在处理"
            label = f"{action} {nct_id} / {document_label}{progress_suffix}"
        elif (
            (total > 0 and completed >= total)
            or str(payload.get("status") or "") in PREPARATION_BATCH_TERMINAL_STATUSES
        ):
            label = "原文准备已完成"
        elif int(payload.get("deferred_item_count") or 0) > 0:
            label = (
                "本阶段原文准备完成，等待下一批准入（"
                f"剩余 {int(payload.get('deferred_item_count') or 0)} 份）"
            )
        else:
            label = "正在准备公开Protocol"
        projected_percent = batch_progress.get("percent")
        context = {
            "current_nct_id": str(
                payload.get("current_nct_id")
                or (current.get("nct_id") if current else "")
                or ""
            ),
            "current_document_label": str(
                payload.get("current_document_label")
                or (
                    current.get("filename")
                    or current.get("document_id")
                    if current
                    else ""
                )
                or ""
            ),
        }
        if current and (item_progress or raw_batch_progress is not None):
            context.update(
                {
                    "unit_type": (
                        "page" if item_unit == "page" else "document"
                    ),
                    "current_object_label": (
                        f"{current.get('nct_id') or '未知研究'} / "
                        f"{current.get('filename') or current.get('document_id') or '未命名文档'}"
                    ),
                }
            )
        if raw_batch_progress is not None:
            context.update(
                {
                    "current_item_id": str(payload.get("current_item_id") or ""),
                    "current_substep": str(
                        item_progress.get("current_substep")
                        or batch_progress.get("current_substep")
                        or ""
                    ),
                    "current_substep_percent": (
                        max(
                            0,
                            min(
                                100,
                                int(
                                    item_progress.get("percent")
                                    if item_progress.get("percent") is not None
                                    else batch_progress.get("percent")
                                ),
                            ),
                        )
                        if (
                            item_progress.get("percent") is not None
                            or (
                                batch_progress.get("percent") is not None
                                and bool(substep)
                            )
                        )
                        else None
                    ),
                    "current_unit": str(
                        item_progress.get("unit") or batch_progress.get("unit") or ""
                    ),
                    "item_completed": int(batch_progress.get("completed") or 0),
                    "item_total": int(batch_progress.get("total") or 0),
                    **progress_context,
                }
            )
        return {
            "phase": "document_preparation",
            "completed": completed,
            "total": total,
            "label": label,
            "child_percent": (
                int(projected_percent)
                if projected_percent is not None
                else None
            ),
            "context": context,
        }

    def _start_translation_batch(
        self,
        project_id: str,
        actor: str,
        pipeline_id: str,
        snapshot_id: str,
        prior_batch_id: str = "",
        allow_new_batch: bool = False,
        retry_idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Create a translation batch scoped to the critical ICH M11 anchors.

        Mirrors ``main.py``'s ``create_writing_reference_translation_batch``:
        build the real ``WritingReferenceTranslationBatchCreateRequest``,
        create the batch, then ensure a durable ``reference_translation`` job
        exists and wake the shared worker so it actually runs (translation is
        AI work and must not block the caller's thread).
        """
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceTranslationBatchCreateRequest,
            WritingReferenceTranslationBatchPreviewRequest,
        )

        # An automatic durable-worker retry/restart must resume the immutable
        # child batch already bound to the parent.  Creating a new batch here
        # would repeat model calls merely because the parent lease was lost.
        # A deliberate user ``resume_waiting`` action passes
        # ``allow_new_batch=True`` and is the only path allowed to create a
        # new immutable retry lineage.
        if allow_new_batch:
            latest = getattr(self.translation_batch_service, "latest", None)
            try:
                previous = latest(project_id, snapshot_id) if callable(latest) else None
            except Exception:
                previous = None
            if previous is not None and len(
                self._source_only_critical_anchors(previous)
            ) >= 2:
                result = (
                    previous.model_dump(mode="json")
                    if hasattr(previous, "model_dump")
                    else dict(previous)
                )
                result["batch_id"] = str(result.get("batch_id") or "")
                result["durable_job_id"] = ""
                result["reused_source_only_batch"] = True
                return result
        if prior_batch_id and not allow_new_batch:
            getter = getattr(self.translation_batch_service, "get", None)
            if callable(getter):
                try:
                    existing = getter(project_id, prior_batch_id)
                except Exception:
                    existing = None
                if existing is not None:
                    result = (
                        existing.model_dump(mode="json")
                        if hasattr(existing, "model_dump")
                        else dict(existing)
                    )
                    job_id = ""
                    status = str(result.get("status") or "")
                    # Pending/running/failed-retryable items still need their
                    # existing durable worker claim woken; terminal batches
                    # are read-only and must not create a new job.
                    if status in {"pending", "running", "failed_retryable"}:
                        ensure_job = getattr(
                            self.translation_batch_service,
                            "ensure_reference_translation_job",
                            None,
                        )
                        if callable(ensure_job):
                            job_id = ensure_job(
                                project_id, prior_batch_id, actor=actor
                            ) or ""
                            if job_id and self.durable_worker is not None:
                                try:
                                    self.durable_worker.wake(project_id, job_id)
                                except Exception:  # noqa: BLE001 — sweeper recovers
                                    pass
                    result["batch_id"] = str(
                        result.get("batch_id") or prior_batch_id
                    )
                    result["durable_job_id"] = job_id
                    result["reused_existing_batch"] = True
                    return result

        anchors = sorted(CRITICAL_ANCHORS)
        scope_preview = self.translation_batch_service.preview(
            project_id,
            WritingReferenceTranslationBatchPreviewRequest(
                snapshot_id=snapshot_id,
                glossary_version="cms_regulatory_zh_v1",
                anchor_filter=anchors,
                max_spans_per_anchor=5,
            ),
        )
        retry_identity = str(
            retry_idempotency_key
            if allow_new_batch and retry_idempotency_key
            else prior_batch_id or "initial"
        )
        retry_identity_hash = hashlib.sha256(
            retry_identity.encode("utf-8")
        ).hexdigest()[:10]
        request = WritingReferenceTranslationBatchCreateRequest(
            snapshot_id=snapshot_id,
            glossary_version="cms_regulatory_zh_v1",
            anchor_filter=anchors,
            # Research unlock only needs a few high-signal spans per critical
            # anchor — full-protocol span floods (hundreds) never finish in time.
            max_spans_per_anchor=5,
            actor=actor,
            # Scope lineage changes and each failed predecessor receive a new
            # immutable batch. Repeated submission from the same predecessor
            # still replays the same idempotent result.
            idempotency_key=(
                f"pipe-tr-v23-{pipeline_id}-"
                f"{scope_preview.scope_sha256[:16]}-{retry_identity_hash}"
            ),
        )
        batch = self.translation_batch_service.create(project_id, request)
        job_id = ""
        ensure_job = getattr(
            self.translation_batch_service, "ensure_reference_translation_job", None
        )
        if callable(ensure_job):
            job_id = ensure_job(project_id, batch.batch_id, actor=actor) or ""
            if job_id and self.durable_worker is not None:
                try:
                    self.durable_worker.wake(project_id, job_id)
                except Exception:  # noqa: BLE001 — sweeper recovers
                    pass
        result = (
            batch.model_dump(mode="json") if hasattr(batch, "model_dump") else dict(batch)
        )
        result["durable_job_id"] = job_id
        return result

    def _wait_translation(
        self,
        project_id: str,
        state: ResearchPipelineState,
        pulse: Callable[[str], None],
    ) -> None:
        """Poll the real translation-batch status until terminal.

        Translation runs via the shared durable worker (background thread),
        so this loop is the actual wait — not a formality.
        """
        if not state.translation_batch_id:
            return
        getter = getattr(self.translation_batch_service, "get", None)
        if not callable(getter):
            return
        deadline = time.time() + 1800
        while time.time() < deadline:
            if state.cancel_requested:
                raise ResearchPipelineError("pipeline cancelled or lease lost")
            batch = getter(project_id, state.translation_batch_id)
            payload = _payload_dict(batch)
            status = str(payload.get("status") or "")
            projection = self._translation_progress_projection(payload)
            self._apply_child_progress(state, **projection)
            critical_ready = int(projection["context"]["critical_anchors_ready"])
            pulse(projection["label"])
            if status in TRANSLATION_BATCH_TERMINAL_STATUSES:
                # partial_failure / completed_with_blocked without any
                # candidate_ready critical anchors must NOT unlock the
                # downstream round-1 path — that previously left design
                # locked forever after a fidelity wipeout.
                if not critical_ready and len(
                    self._source_only_critical_anchors(batch)
                ) < 2:
                    raise ResearchPipelineError(
                        f"翻译未形成可用关键锚点译文（status={status}，"
                        f"critical_ready=0/{len(CRITICAL_ANCHORS)}）"
                    )
                return
            # Research pipeline may unlock round-1 once any critical anchors
            # have real translations, without waiting for every pending span.
            if critical_ready >= 2:
                return
            time.sleep(2.5)
        # Soft timeout: proceed if at least one critical anchor exists.
        batch = getter(project_id, state.translation_batch_id)
        projection = self._translation_progress_projection(batch)
        if int(projection["context"]["critical_anchors_ready"]) or len(
            self._source_only_critical_anchors(batch)
        ) >= 2:
            return
        raise ResearchPipelineError("翻译超时")

    @staticmethod
    def _source_only_critical_anchors(batch: Any) -> set[str]:
        """Return validated source anchors usable when body translation is down."""
        payload = _payload_dict(batch)
        items = [_payload_dict(item) for item in list(payload.get("items") or [])]
        return {
            str(item.get("ich_m11_anchor") or "")
            for item in items
            if str(item.get("ich_m11_anchor") or "") in CRITICAL_ANCHORS
            and str(item.get("document_type") or "").casefold() == "protocol"
            and str(item.get("validation_status") or "")
            in {"confirmed", "user_overridden"}
            and str(item.get("structure_review_id") or "")
            and int(item.get("structure_review_revision") or 0) >= 1
            and str(item.get("source_text_sha256") or "")
            and str(item.get("generation_status") or "") == "failed_retryable"
            and str(item.get("error_code") or "")
            == "translation_generation_failed"
        }

    @staticmethod
    def _translation_progress_projection(batch: Any) -> dict[str, Any]:
        payload = _payload_dict(batch)
        items = [_payload_dict(item) for item in list(payload.get("items") or [])]
        counts = _payload_dict(payload.get("counts") or {})
        total = int(counts.get("item_count") or len(items))
        completed = sum(
            str(item.get("generation_status") or "")
            in TRANSLATION_TERMINAL_ITEM_STATUSES
            for item in items
        )
        if counts and not items:
            completed = int(
                counts.get("candidate_ready_count", 0)
                + counts.get("fidelity_blocked_count", 0)
                + counts.get("failed_count", 0)
                + counts.get("excluded_count", 0)
            )
        critical_ready = {
            str(item.get("ich_m11_anchor") or "")
            for item in items
            if str(item.get("ich_m11_anchor") or "") in CRITICAL_ANCHORS
            and (
                str(item.get("generation_status") or "") == "candidate_ready"
                or str(item.get("fidelity_status") or "") == "passed"
            )
        }
        def item_fraction(item: dict[str, Any]) -> float:
            status = str(item.get("generation_status") or "")
            if status in TRANSLATION_TERMINAL_ITEM_STATUSES:
                return 1.0
            stage = str(item.get("pipeline_stage") or "")
            if stage == "toc_planning":
                return 0.08
            if stage == "translating_hy_mt2":
                chunk_total = max(0, int(item.get("chunk_count") or 0))
                chunk_completed = min(
                    chunk_total,
                    max(0, int(item.get("chunk_completed") or 0)),
                )
                chunk_fraction = (
                    chunk_completed / chunk_total if chunk_total else 0.0
                )
                return 0.10 + (0.70 * chunk_fraction)
            if stage == "integration_qc":
                return 0.88
            if stage == "candidate_ready":
                return 1.0
            if stage == "ocr_running":
                return 0.05
            if stage == "extracting":
                return 0.03
            return 0.0

        item_percent = (
            round(
                (
                    sum(item_fraction(item) for item in items)
                    / max(total, len(items), 1)
                )
                * 100
            )
            if items
            else _percent(completed, total)
        )
        anchor_percent = _percent(len(critical_ready), len(CRITICAL_ANCHORS))
        child_percent = round((item_percent * 0.7) + (anchor_percent * 0.3))
        current = next(
            (
                item
                for item in items
                if str(item.get("generation_status") or "")
                not in TRANSLATION_TERMINAL_ITEM_STATUSES
            ),
            None,
        )
        current_anchor = str(current.get("ich_m11_anchor") or "") if current else ""
        current_study = str(current.get("nct_id") or "") if current else ""
        current_document = str(
            (current.get("filename") or current.get("artifact_id") or "")
            if current
            else ""
        )
        if current:
            object_parts = [
                value
                for value in (
                    current_study,
                    current_document,
                    ANCHOR_LABELS.get(current_anchor, current_anchor),
                )
                if value
            ]
            label = "正在翻译 " + " / ".join(object_parts)
        elif total:
            label = "关键章节翻译已完成"
        else:
            label = "正在准备翻译项"
        current_percent = round(item_fraction(current) * 100) if current else 100
        return {
            "phase": "critical_anchor_translation",
            "completed": completed,
            "total": total,
            "child_percent": child_percent,
            "label": label,
            "context": {
                "unit_type": "chapter",
                "current_study_id": current_study,
                "current_document_label": current_document,
                "current_chapter_label": ANCHOR_LABELS.get(current_anchor, current_anchor),
                "current_substep_percent": current_percent,
                "critical_anchors_ready": len(critical_ready),
                "critical_anchors_total": len(CRITICAL_ANCHORS),
                "item_percent": item_percent,
                "anchor_percent": anchor_percent,
            },
        }

    def _run_round1_analysis(
        self, project_id: str, actor: str, state: ResearchPipelineState
    ) -> list[str]:
        return self._run_corpus_analysis(
            project_id,
            actor,
            state,
            round_number=1,
        )

    def _run_corpus_analysis(
        self,
        project_id: str,
        actor: str,
        state: ResearchPipelineState,
        *,
        round_number: int,
    ) -> list[str]:
        """Run evidence-bound analysis with four observable real boundaries.

        The analysis service reads current Protocol source spans and
        fidelity-passed translations, validates every source quote and numeric
        claim, derives source/sponsor support through the corpus policy, and
        persists an immutable analysis artifact. There is deliberately no
        continuous model-call percentage: progress stays on the AI step until
        the provider returns.
        """
        if round_number not in {1, 2}:
            raise ValueError("round_number must be 1 or 2")
        if not state.round1_ai_route:
            raise ResearchPipelineError(
                "研究流水线缺少冻结的产品独立AI路由，请重新启动流水线"
            )
        if not state.snapshot_id:
            raise ResearchPipelineError(f"第{round_number}轮语料分析缺少检索快照")

        round_label = "第一轮" if round_number == 1 else "第二轮"
        phase = f"round{round_number}_corpus_analysis"
        analysis_context: dict[str, Any] = {
            "analysis_round": round_number,
            "analysis_artifact_ready": False,
            "analysis_step": "collect_admitted_sources",
        }
        persist = getattr(self, "_persist", None)

        def checkpoint(completed: int, label: str, step: str) -> None:
            analysis_context["analysis_step"] = step
            analysis_context["unit_type"] = (
                "corpus" if step in {"collect_admitted_sources", "validate_evidence"} else "writing"
            )
            analysis_context["current_object_label"] = (
                "当前研究语料库"
                if analysis_context["unit_type"] == "corpus"
                else "医学写作研究稿"
            )
            self._apply_child_progress(
                state,
                phase=phase,
                completed=completed,
                total=4,
                label=label,
                context=analysis_context,
            )
            state.detail = label
            if callable(persist):
                persist(project_id, state)

        checkpoint(
            0,
            f"正在收集{round_label}语料分析的准入来源（研究语料库）",
            "collect_admitted_sources",
        )
        journey = self.journey_service.get(project_id)

        # The concrete production analysis service exposes the same bounded
        # source-collection helpers used by analyze(). Running the preflight
        # here makes source collection and evidence admission independently
        # observable without pretending to know model-internal progress.
        evidence_catalog: list[dict[str, Any]] | None = None
        project_context_builder = getattr(
            self.corpus_analysis_ai_service, "_project_context", None
        )
        evidence_catalog_builder = getattr(
            self.corpus_analysis_ai_service, "_evidence_catalog", None
        )
        if callable(project_context_builder) and callable(evidence_catalog_builder):
            project_context = project_context_builder(journey)
            evidence_catalog = list(
                evidence_catalog_builder(
                    project_id=project_id,
                    snapshot_id=state.snapshot_id,
                    project_context=project_context,
                )
                or []
            )
            analysis_context["source_count"] = len(
                {
                    str(item.get("source_id") or "")
                    for item in evidence_catalog
                    if str(item.get("source_id") or "")
                }
            )
            analysis_context["evidence_count"] = len(evidence_catalog)

        checkpoint(
            1,
            f"正在验证{round_label}语料分析证据（语料库校验）",
            "validate_evidence",
        )
        if evidence_catalog is not None:
            if not evidence_catalog:
                raise ResearchPipelineError(
                    f"{round_label}语料分析没有可准入的Protocol证据"
                )
            required_evidence_fields = {"evidence_id", "source_id", "evidence_text"}
            if any(
                not required_evidence_fields.issubset(item)
                or any(not str(item.get(key) or "").strip() for key in required_evidence_fields)
                for item in evidence_catalog
            ):
                raise ResearchPipelineError(
                    f"{round_label}语料分析存在缺少来源绑定的证据"
                )

        checkpoint(
            2,
            f"正在调用综合AI生成{round_label}语料分析（写作研究稿）",
            "invoke_synthesis_ai",
        )
        analysis_pipeline_id = (
            state.pipeline_id
            if round_number == 1
            else f"{state.pipeline_id}:round2"
        )
        try:
            result = self.corpus_analysis_ai_service.analyze(
                project_id=project_id,
                pipeline_id=analysis_pipeline_id,
                snapshot_id=state.snapshot_id,
                journey=journey,
                actor=actor,
                frozen_route=state.round1_ai_route,
            )
        except Exception as exc:  # noqa: BLE001 — persist safe provider diagnostics
            diagnostics = getattr(exc, "diagnostics", {}) or {}
            if diagnostics:
                analysis_context["provider_diagnostics"] = {
                    str(key): value
                    for key, value in diagnostics.items()
                    if isinstance(value, (str, int, float, bool))
                    or value is None
                    or (
                        isinstance(value, list)
                        and all(
                            isinstance(item, (str, int, float, bool))
                            or item is None
                            for item in value
                        )
                    )
                }
                analysis_context["provider_failure_code"] = str(
                    diagnostics.get("failure_code") or "provider_response_invalid"
                )
                analysis_context["analysis_step"] = "provider_response"
                state.detail = (
                    f"{round_label}语料分析的独立AI响应未形成可解析的最终JSON；"
                    "已保留安全响应诊断，未写入分析产物。"
                )
                if callable(persist):
                    persist(project_id, state)
            raise
        checkpoint(
            3,
            f"正在校验并持久化{round_label}语料分析产物（写作研究稿）",
            "validate_and_persist",
        )
        analysis_id = str(result.get("analysis_id") or "")
        output_hash = str(result.get("output_hash") or "")
        brief_ids = [
            str(item)
            for item in (result.get("evidence_summary_ids") or [])
            if str(item)
        ][:50]
        if (
            result.get("status") != "completed"
            or not analysis_id
            or not output_hash
            or not brief_ids
        ):
            raise ResearchPipelineError(
                f"产品独立AI未形成完整的{round_label}证据摘要产物"
            )

        get_analysis = getattr(self.corpus_analysis_ai_service, "get_analysis", None)
        if callable(get_analysis) and get_analysis(project_id, analysis_id) is None:
            raise ResearchPipelineError(
                f"{round_label}语料分析产物未完成持久化"
            )

        if round_number == 1:
            state.round1_analysis_id = analysis_id
            state.round1_analysis_output_hash = output_hash
        completion_detail = (
            f"{round_label}竞品Protocol语料深析已持久化 {len(brief_ids)} 条证据摘要"
            f"（分析产物 {analysis_id}）；设计推荐只能引用这些经来源绑定的正文模块。"
        )
        analysis_context.update(
            {
                "analysis_artifact_ready": True,
                "analysis_id": analysis_id,
                "evidence_summary_count": len(brief_ids),
            }
        )
        checkpoint(
            4,
            f"{round_label}语料分析已完成（研究语料库与写作研究稿）",
            "completed",
        )
        state.detail = completion_detail
        if callable(persist):
            persist(project_id, state)
        return brief_ids


class ResearchPipelineDurableExecutor:
    job_type = RESEARCH_PIPELINE_JOB_TYPE

    def __init__(self, service: MedicalWritingResearchPipelineService) -> None:
        self.service = service

    def execute(
        self,
        job: DurableJobRecord,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> Any:
        """Matches the ``DurableJobExecutor`` protocol (see
        ``medical_writing_durable_jobs.DurableJobExecutor.execute``):
        ``(job, claim_token, cancel_check, heartbeat)`` are all positional.
        ``execute_stages`` only takes a single combined heartbeat callable —
        fold ``cancel_check`` into it so a lost lease or explicit shutdown
        both surface as "pulse failed" inside the pipeline's own pulse()/
        cancel_requested handling.
        """
        from services.api.app.medical_writing_durable_jobs import DurableJobResult

        def combined_heartbeat(progress: DurableJobProgressPayload) -> bool:
            if cancel_check():
                return False
            return heartbeat(progress)

        try:
            payload = json.loads(job.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        project_id = job.project_id
        actor = str(payload.get("actor") or "system")
        auto_confirm = bool(payload.get("auto_confirm_triage"))
        resume_from = str(payload.get("resume_from") or "")
        resume_idempotency_key = str(payload.get("idempotency_key") or "")
        state = self.service.get_state(project_id)
        try:
            payload_route = payload.get("corpus_analysis_ai_route")
            if resume_from == "awaiting_triage_confirm":
                # Resume path from advance_after_basket_confirm — the
                # basket is already confirmed by the medical manager's
                # one-click action. Use the frozen retained IDs from the
                # durable payload; NEVER re-confirm or recompute the
                # basket from AI classifications.
                if not state.pipeline_id:
                    raise ResearchPipelineError(
                        "durable resume job has no persisted pipeline"
                    )
                frozen_retained = list(
                    payload.get("retained_candidate_ids") or []
                )
                if not frozen_retained:
                    raise ResearchPipelineError(
                        "durable resume job has no frozen retained candidate IDs"
                    )
                state = self.service._continue_after_confirmed_triage(
                    project_id,
                    actor=actor,
                    frozen_retained_ids=frozen_retained,
                    heartbeat=combined_heartbeat,
                    state=state,
                )
            elif resume_from in (USER_ACTION_WAITING_STAGES | {"failed"}):
                # User-resolved preparation/document gates are durable
                # continuations of an existing immutable batch.  They must not
                # fall through to execute_stages (which would recreate search
                # or triage work).  The resume key is passed through so an
                # explicit retry may create only the next translation lineage
                # when the prior one is terminal.
                prep_batch_id = str(
                    payload.get("prep_batch_id") or state.prep_batch_id or ""
                )
                if not prep_batch_id:
                    raise ResearchPipelineError(
                        "durable waiting-stage resume has no preparation batch"
                    )
                state = self.service._continue_from_prepared_batch(
                    project_id,
                    actor=actor,
                    state=state,
                    prep_batch_id=prep_batch_id,
                    resume_idempotency_key=resume_idempotency_key,
                )
                state.last_resume_idempotency_key = resume_idempotency_key
                state.last_resume_started_from_stage = resume_from
                state.last_resume_result_stage = state.stage
                state.last_resume_at = _iso()
                state = self.service._persist(project_id, state)
            else:
                if not isinstance(payload_route, dict) or not payload_route:
                    raise ResearchPipelineError(
                        "durable research-pipeline job has no frozen corpus-analysis AI route"
                    )
                if payload_route != state.round1_ai_route:
                    raise ResearchPipelineError(
                        "durable research-pipeline AI route does not match persisted pipeline state"
                    )
                state = self.service.execute_stages(
                    project_id,
                    state,
                    actor=actor,
                    auto_confirm_triage=auto_confirm,
                    heartbeat=combined_heartbeat,
                )
            # If paused awaiting triage confirm, job completes successfully at pause.
            # (DurableJobResult has no "status" field — success/failure is
            # signaled purely by whether "error" is set.)
            output = {"pipeline": state.as_dict()}
            return DurableJobResult(
                output_hash=hashlib.sha256(
                    json.dumps(output, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
                artifact_locator=f"research_pipeline:{state.pipeline_id}",
                progress=_progress_payload(state, state.detail),
            )
        except TriageWaitTimeoutError as exc:
            state = self.service.get_state(project_id)
            progress = self.service._triage_progress(project_id, state)
            if progress:
                self.service._apply_child_progress(
                    state,
                    phase="competitor_triage",
                    completed=progress["completed_chunks"],
                    total=progress["total_chunks"],
                    child_percent=progress["percent"],
                    label=progress["label"],
                    context=progress.get("context"),
                )
            state = self.service._set_stage(
                state,
                "triaging",
                detail=(
                    "竞品分诊长时间未产生新批次结果；"
                    "后台子任务状态已保留，完成后可继续。"
                ),
                error=f"{type(exc).__name__}: {exc}",
            )
            self.service._persist(project_id, state)
            return DurableJobResult(
                error=str(exc)[:800],
                retryable=False,
                progress=_progress_payload(state, str(exc)[:300]),
            )
        except Exception as exc:  # noqa: BLE001
            state = self.service.get_state(project_id)
            if resume_from in (USER_ACTION_WAITING_STAGES | {"failed"}):
                # A durable user continuation must fail closed at a truthful
                # retryable gate, not leave the parent at ``preparing`` or
                # silently turn a document-stage error into a fresh search/
                # triage attempt.  Explicit user retry is required; the
                # worker must not replay a completed OCR/download stage.
                if state.stage == "translating":
                    failure_stage = "awaiting_translation_scope"
                elif state.stage == "analyzing_round1":
                    failure_stage = "awaiting_corpus_analysis"
                elif state.stage == "preparing":
                    reconciled = self.service._reconcile_stale_preparation_state(
                        project_id, state
                    )
                    state = reconciled
                    failure_stage = (
                        reconciled.stage
                        if reconciled.stage != "preparing"
                        else resume_from
                    )
                else:
                    failure_stage = resume_from
                state = self.service._set_stage(
                    state,
                    failure_stage,
                    detail=(
                        f"恢复未完成：{exc}。已完成的下载与结构提取仍保留，"
                        "请处理提示后再次继续。"
                    ),
                    error=f"resume_failed:{type(exc).__name__}:{exc}",
                )
                state.last_resume_idempotency_key = ""
                state.last_resume_started_from_stage = resume_from
                state.last_resume_result_stage = failure_stage
                state.last_resume_at = _iso()
                state = self.service._persist(project_id, state)
                return DurableJobResult(
                    error=str(exc)[:800],
                    retryable=False,
                    progress=_progress_payload(state, str(exc)[:300]),
                )
            state = self.service._set_stage(
                state,
                "failed",
                detail="研究流水线失败",
                error=f"{type(exc).__name__}: {exc}",
            )
            self.service._persist(project_id, state)
            return DurableJobResult(
                error=str(exc)[:800],
                retryable=True,
                progress=_progress_payload(state, str(exc)[:300]),
            )
