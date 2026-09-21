"""Auditable chapter translation pipeline for writing-reference documents.

Authoritative stages (per USER_REQUIREMENTS_CURRENT_20260718 §医学写作 OCR 与翻译覆盖规则):

    text extraction
    -> optional GLM-OCR-bf16 page recovery (>=200 DPI, <=8 concurrency)
    -> deepseek-v4-flash TOC/chapter planning
    -> dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX chapter/chunk translation
    -> deepseek-v4-flash integration QC
    -> pending medical approval

Hy-MT2 is the sole protocol-body translator. DeepSeek Flash, or Pro when an
upper-layer task is explicitly escalated, may only identify chapter structure,
integrate the existing Hy-MT2 output, perform continuity QC, or select corpus
material. Neither DeepSeek model may translate, retranslate, rewrite, or
replace protocol-body text. This module is self-contained and
deterministic-fake-friendly: every external call (OCR, DeepSeek planning,
Hy-MT2 translation, DeepSeek QC) goes through an injectable callable so tests
never touch the network.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable, List, Optional, Protocol, Sequence

# ---------------------------------------------------------------------------
# Model allowlists — exact identifiers required by the current contract.
# ---------------------------------------------------------------------------

WRITING_REFERENCE_OCR_MODEL = "GLM-OCR-bf16"
WRITING_REFERENCE_OCR_PROFILE = "ocr-glm-v1"
WRITING_REFERENCE_OCR_MIN_DPI = 200
WRITING_REFERENCE_OCR_MAX_CONCURRENCY = 8

HY_MT2_MODEL_ID = "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"

FLASH_PLANNING_MODEL = "deepseek-v4-flash"
FLASH_QC_MODEL = "deepseek-v4-flash"
PRO_UPPER_LAYER_MODEL = "deepseek-v4-pro"
FLASH_PLANNING_PREVIOUS_PROMPT_VERSION = (
    "flash_toc_planning_v0_2_segment_ranges"
)
FLASH_PLANNING_PROMPT_VERSION = "flash_toc_planning_v0_3_server_canonical_ids"
SERVER_CANONICAL_CHAPTER_ID_VERSION = "server_canonical_chapter_id_v1"
SERVER_CONTRACT_MIGRATION_NAMESPACE = "server_contract_migration_v1"
PLANNER_CONTRACT_TRANSITION_VERSION = (
    "planner_contract_v2_to_v3_supersession_v1"
)
FLASH_QC_PROMPT_VERSION = "flash_integration_qc_v0_6_traceable_advisory"
HY_MT2_PROMPT_VERSION = (
    "hy_mt2_chapter_translation_v0_30_protocol_heading_abbreviation_stopwords"
)
POST_HY_NORMALIZATION_VERSION = "post_hy_v0_6_inline_crf_restoration"

# V11 downstream translation-contract identity.  Any change to the alignment
# contract (marker format, unit bounds, prompt versions, chunk target) must
# invalidate previously persisted chunk/integration reuse without mutating
# the immutable old rows.
TRANSLATION_ALIGNMENT_CONTRACT = (
    "cms_seg_aligned_units_v36_protocol_heading_abbreviation_stopwords"
)
HY_MT2_MAX_UNITS_PER_CALL = 6
CHUNK_IDENTITY_VERSION = "translation_chunk_identity_v2_fingerprint_bound"


def translation_contract_fingerprint() -> str:
    """Deterministic fingerprint of the downstream translation contract.

    Persisted into chunk fingerprints and integration identity so that
    output produced under an older Hy/Flash/alignment contract can never be
    silently reused after a contract bump.
    """
    from .regulatory_translation_glossary import regulatory_translation_glossary_hash

    payload = {
        "alignment_contract": TRANSLATION_ALIGNMENT_CONTRACT,
        "hy_mt2_prompt_version": HY_MT2_PROMPT_VERSION,
        "post_hy_normalization_version": POST_HY_NORMALIZATION_VERSION,
        "flash_qc_prompt_version": FLASH_QC_PROMPT_VERSION,
        "glossary_hash": regulatory_translation_glossary_hash(),
        "chunk_target_chars": CHUNK_TARGET_CHARS,
        "unit_target_chars": UNIT_TARGET_CHARS,
        "hy_mt2_max_units_per_call": HY_MT2_MAX_UNITS_PER_CALL,
        "chunk_identity_version": CHUNK_IDENTITY_VERSION,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


PLANNER_SEGMENT_SAMPLE_CHARS = 80
PLANNER_MANIFEST_MAX_CHARS = 65_536

ALLOWED_OCR_MODELS = frozenset(
    {
        WRITING_REFERENCE_OCR_MODEL,
        "PaddleOCR",
        "models--PaddlePaddle--PaddleOCR-VL-1.6",
    }
)
ALLOWED_BODY_TRANSLATION_MODELS = frozenset({HY_MT2_MODEL_ID})
ALLOWED_FLASH_MODELS = frozenset({FLASH_PLANNING_MODEL, FLASH_QC_MODEL})
ALLOWED_UPPER_LAYER_MODELS = frozenset(
    {FLASH_PLANNING_MODEL, PRO_UPPER_LAYER_MODEL}
)

UPPER_LAYER_DOCUMENT_PLANNING = "document_planning"
UPPER_LAYER_POST_HY_INTEGRATION_QC = "post_hy_mt2_integration_qc"
ALLOWED_UPPER_LAYER_STAGES = frozenset(
    {
        UPPER_LAYER_DOCUMENT_PLANNING,
        UPPER_LAYER_POST_HY_INTEGRATION_QC,
    }
)


class TranslationPipelineStage(str, Enum):
    """Human-meaningful pipeline stage exposed via API progress."""

    EXTRACTING = "extracting"
    OCR_RUNNING = "ocr_running"
    TOC_PLANNING = "toc_planning"
    TRANSLATING_HY_MT2 = "translating_hy_mt2"
    INTEGRATION_QC = "integration_qc"
    CANDIDATE_READY = "candidate_ready"
    FIDELITY_BLOCKED = "fidelity_blocked"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


# Ordered stages for normal progression (excludes terminal/error states).
STAGE_ORDER: tuple[TranslationPipelineStage, ...] = (
    TranslationPipelineStage.EXTRACTING,
    TranslationPipelineStage.OCR_RUNNING,
    TranslationPipelineStage.TOC_PLANNING,
    TranslationPipelineStage.TRANSLATING_HY_MT2,
    TranslationPipelineStage.INTEGRATION_QC,
    TranslationPipelineStage.CANDIDATE_READY,
)


# ---------------------------------------------------------------------------
# Page triage — decide which pages need OCR recovery.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageTriageDecision:
    """Whether a PDF page should be sent to OCR or use extracted text only."""

    physical_page: int
    needs_ocr: bool
    channel: str  # "text" | "ocr"
    reason: str


def triage_page(
    physical_page: int,
    page_text: str,
    *,
    is_image_page: bool = False,
    is_spatial_page: bool = False,
) -> PageTriageDecision:
    """Return the OCR triage decision for a single page.

    A page with enough extractable text never calls OCR.  An empty, image-only,
    or spatial-layout page (figure/table/flowchart/scale) is routed to OCR.
    """
    if page_text.strip():
        return PageTriageDecision(
            physical_page=physical_page,
            needs_ocr=False,
            channel="text",
            reason="text_extracted",
        )
    if is_image_page or is_spatial_page or not page_text.strip():
        return PageTriageDecision(
            physical_page=physical_page,
            needs_ocr=True,
            channel="ocr",
            reason="zero_text_or_spatial_layout",
        )
    return PageTriageDecision(
        physical_page=physical_page,
        needs_ocr=True,
        channel="ocr",
        reason="empty_page",
    )


def triage_pages(
    page_texts: Sequence[tuple[int, str, bool, bool]],
) -> List[PageTriageDecision]:
    """Batch triage: (page_number, text, is_image, is_spatial) -> decisions."""
    return [
        triage_page(page, text, is_image_page=is_img, is_spatial_page=is_spatial)
        for page, text, is_img, is_spatial in page_texts
    ]


# ---------------------------------------------------------------------------
# OCR rendering — enforce DPI and concurrency bounds.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrRenderSpec:
    """Specification for a single OCR render request."""

    physical_page: int
    dpi: int
    model: str
    ocr_profile: str

    def __post_init__(self) -> None:
        if self.dpi < WRITING_REFERENCE_OCR_MIN_DPI:
            raise ValueError(
                f"OCR render DPI must be >= {WRITING_REFERENCE_OCR_MIN_DPI}, "
                f"got {self.dpi}"
            )
        if self.model not in ALLOWED_OCR_MODELS:
            raise ValueError(
                f"OCR model '{self.model}' is not in the writing-reference "
                f"allowlist {sorted(ALLOWED_OCR_MODELS)}"
            )


def build_ocr_render_spec(
    physical_page: int,
    *,
    dpi: int = WRITING_REFERENCE_OCR_MIN_DPI,
    model: str = WRITING_REFERENCE_OCR_MODEL,
    ocr_profile: str = WRITING_REFERENCE_OCR_PROFILE,
) -> OcrRenderSpec:
    """Construct an OCR render spec, enforcing minimum DPI and model allowlist."""
    return OcrRenderSpec(
        physical_page=physical_page,
        dpi=dpi,
        model=model,
        ocr_profile=ocr_profile,
    )


def enforce_ocr_concurrency(max_workers: int) -> int:
    """Clamp OCR concurrency to the 1..8 range."""
    if max_workers < 1:
        raise ValueError("OCR concurrency must be at least 1")
    return min(max_workers, WRITING_REFERENCE_OCR_MAX_CONCURRENCY)


# ---------------------------------------------------------------------------
# Pipeline lineage — persisted per chapter/chunk to prove provenance.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrPageLineage:
    """Provenance for a single OCR-recovered page."""

    physical_page: int
    dpi: int
    model: str
    ocr_profile_digest: str
    source_text_sha256: str
    channel: str  # "text" | "ocr"


@dataclass(frozen=True)
class ChapterTranslationLineage:
    """Full lineage for one chapter/chunk translation candidate.

    Every field is hashed into the idempotency key so that a change in any
    provenance dimension (glossary, model, prompt, OCR profile) forces a fresh
    candidate rather than silently reusing a stale one.
    """

    document_sha256: str
    extraction_revision: str
    chapter_id: str
    chunk_id: str
    glossary_version: str
    ocr_pages: tuple[OcrPageLineage, ...]
    hy_mt2_model: str
    flash_planning_prompt_version: str
    flash_qc_prompt_version: str
    hy_mt2_prompt_version: str
    source_text_sha256: str
    translated_text_sha256: str
    stage: TranslationPipelineStage

    def idempotency_fingerprint(self) -> str:
        """Deterministic hash of all lineage dimensions."""
        payload = {
            "document_sha256": self.document_sha256,
            "extraction_revision": self.extraction_revision,
            "chapter_id": self.chapter_id,
            "chunk_id": self.chunk_id,
            "glossary_version": self.glossary_version,
            "ocr_pages": [
                {
                    "page": p.physical_page,
                    "dpi": p.dpi,
                    "model": p.model,
                    "profile_digest": p.ocr_profile_digest,
                    "text_sha256": p.source_text_sha256,
                    "channel": p.channel,
                }
                for p in self.ocr_pages
            ],
            "hy_mt2_model": self.hy_mt2_model,
            "flash_planning_prompt_version": self.flash_planning_prompt_version,
            "flash_qc_prompt_version": self.flash_qc_prompt_version,
            "hy_mt2_prompt_version": self.hy_mt2_prompt_version,
            "source_text_sha256": self.source_text_sha256,
            "translated_text_sha256": self.translated_text_sha256,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stage outputs — lightweight dataclasses for each stage's result.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlashPlanResult:
    """Output of deepseek-v4-flash TOC/chapter planning."""

    chapters: tuple[dict[str, Any], ...]
    document_role: str
    plan_prompt_version: str
    plan_model: str
    plan_input_hash: str
    plan_output_hash: str


@dataclass(frozen=True)
class HyMt2TranslationResult:
    """Output of dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX chapter translation."""

    chapter_id: str
    chunk_id: str
    translated_text: str
    translated_text_sha256: str
    model: str
    prompt_version: str
    input_hash: str
    output_hash: str
    translation_strategy: str = "hy_mt2_aligned_units"


@dataclass(frozen=True)
class FlashQcResult:
    """Output of deepseek-v4-flash integration QC.

    Flash is a non-authoring upper-layer reviewer. ``integrated_text`` is an
    exact audit echo of the aligned Hy-MT2 draft, never an editable candidate.
    The admitted body always comes from the normalized Hy-MT2 ``target_map``.
    """

    passed: bool
    failure_codes: tuple[str, ...]
    qc_prompt_version: str
    qc_model: str
    qc_input_hash: str
    qc_output_hash: str
    integrated_text: str = ""
    integrated_text_sha256: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PipelineCandidate:
    """Final translation candidate produced by the pipeline."""

    lineage: ChapterTranslationLineage
    translated_text: str
    flash_plan: FlashPlanResult
    hy_mt2: HyMt2TranslationResult
    flash_qc: FlashQcResult
    fidelity_passed: bool
    needs_medical_approval: bool


# ---------------------------------------------------------------------------
# External-call type aliases (injectable for testing).
# ---------------------------------------------------------------------------

# OcrPageRunner: (page_number, dpi, model, image_bytes) -> ocr_text
# The image_bytes argument carries the rendered PNG of the page so the
# production runner can forward it to LocalOcrGateway without re-opening
# the PDF or sharing a PyMuPDF document across threads.
OcrPageRunner = Callable[[int, int, str, bytes], str]

# FlashPlanner: (source_text, document_context) -> FlashPlanResult
FlashPlanner = Callable[[str, dict[str, Any]], FlashPlanResult]

# HyMt2Translator: (chapter_text, glossary_version, chapter_id, chunk_id) -> HyMt2TranslationResult
HyMt2Translator = Callable[[str, str, str, str], HyMt2TranslationResult]

# FlashQcRunner: (translated_chunks, source_context) -> FlashQcResult
FlashQcRunner = Callable[[str, str], FlashQcResult]

# StageObserver: called before ("before") and after ("after") each external
# stage with the stage enum and optional partial lineage.  The observer is the
# hook through which the batch service persists progress so APIs can surface
# human-meaningful stage transitions without reading logs.
StageObserver = Callable[[str, TranslationPipelineStage, dict[str, Any]], None]


@dataclass(frozen=True)
class UpperLayerStageOwner:
    """Minimal owner identity passed to the shared upper-layer stage service."""

    project_id: str
    owner_type: str
    owner_id: str
    artifact_id: str
    extraction_revision: str
    batch_id: str = ""
    item_id: str = ""
    plan_id: str = ""
    chapter_id: str = ""
    retry_generation: int = 0
    retry_parent_stage_run_id: str = ""
    contract_supersession_generation: int = 0
    contract_supersession_transition_version: str = ""
    contract_supersession_source_stage_run_id: str = ""
    contract_supersession_source_execution_fingerprint: str = ""
    contract_supersession_source_prompt_version: str = ""
    contract_supersession_target_prompt_version: str = ""


@dataclass(frozen=True)
class UpperLayerStageExecutionResult:
    """One stage result plus the immutable lineage written by its owner service.

    The orchestration layer deliberately does not persist this record. The
    shared upper-layer execution service owns persistence and returns this
    compact projection after selecting Flash or, when deterministic rules
    allow, automatically rerunning the same stage with Pro.
    """

    output: Any
    stage: str
    requested_model: str
    response_model: str
    prompt_version: str
    input_hash: str
    output_hash: str
    expected_response_model: str = ""
    status: str = "succeeded"
    stage_run_id: str = ""
    latest_stage_run_id: str = ""
    latest_status: str = ""
    parent_stage_run_id: str = ""
    escalation_id: str = ""
    escalation_trigger_status: str = ""
    escalation_trigger_code: str = ""
    provider: str = "deepseek"
    transport: str = "openai_compatible"
    deployment_profile: str = ""
    provider_call_count: int = 1
    planner_attempt_count: int = 0
    provider_call_attempts: tuple[dict[str, Any], ...] = ()
    failure_code: str = ""
    retry_generation: int = 0
    retry_parent_stage_run_id: str = ""
    contract_supersession_generation: int = 0
    contract_supersession_transition_version: str = ""
    contract_supersession_source_stage_run_id: str = ""
    contract_supersession_source_execution_fingerprint: str = ""
    contract_supersession_source_prompt_version: str = ""
    contract_supersession_target_prompt_version: str = ""


class UpperLayerStageExecutor(Protocol):
    """Injection contract implemented by the shared durable stage service.

    ``invoke`` accepts only the server-selected model. A caller cannot supply
    provider, base URL, or model. The service may invoke Flash more than once
    for bounded same-model recovery and may invoke Pro only for an eligible
    semantic/degraded upper-layer result.
    """

    def execute(
        self,
        *,
        stage: str,
        owner: UpperLayerStageOwner,
        prompt_version: str,
        input_payload: Any,
        input_hash: str,
        invoke: Callable[[str], Any],
        output_hash: Callable[[Any], str],
        immutable_body_hash: str = "",
    ) -> UpperLayerStageExecutionResult: ...


class PersistedUpperLayerStageExecutorAdapter:
    """Bridge the pipeline protocol to the shared durable execution service.

    Runtime wiring supplies the exact prompt resolver and deployment profile.
    The shared service remains the only owner of route choice, bounded retry,
    automatic Pro escalation, and persistence.
    """

    def __init__(
        self,
        service: Any,
        *,
        deployment_profile: str,
        prompt_resolver: Callable[[str, str], str],
        output_decoder: Callable[[str, Any], Any] | None = None,
    ) -> None:
        if not deployment_profile.strip():
            raise ValueError("upper-layer deployment profile is required")
        self.service = service
        self.deployment_profile = deployment_profile
        self.prompt_resolver = prompt_resolver
        self.output_decoder = output_decoder or self._decode_output

    @staticmethod
    def _decode_output(stage: str, payload: Any) -> Any:
        if stage == UPPER_LAYER_DOCUMENT_PLANNING:
            if isinstance(payload, FlashPlanResult):
                return payload
            if not isinstance(payload, dict):
                raise ChapterTranslationPipelineError(
                    "persisted planner output is not structured"
                )
            return FlashPlanResult(
                chapters=tuple(payload.get("chapters") or ()),
                document_role=str(payload.get("document_role") or ""),
                plan_prompt_version=str(payload.get("plan_prompt_version") or ""),
                plan_model=str(payload.get("plan_model") or ""),
                plan_input_hash=str(payload.get("plan_input_hash") or ""),
                plan_output_hash=str(payload.get("plan_output_hash") or ""),
            )
        if stage == UPPER_LAYER_POST_HY_INTEGRATION_QC:
            if isinstance(payload, FlashIntegrationOutcome):
                return payload
            if not isinstance(payload, dict):
                raise ChapterTranslationPipelineError(
                    "persisted integration output is not structured"
                )
            qc_payload = payload.get("qc_result")
            qc_result = None
            if isinstance(qc_payload, dict):
                qc_result = FlashQcResult(
                    passed=bool(qc_payload.get("passed")),
                    failure_codes=tuple(qc_payload.get("failure_codes") or ()),
                    qc_prompt_version=str(
                        qc_payload.get("qc_prompt_version") or ""
                    ),
                    qc_model=str(qc_payload.get("qc_model") or ""),
                    qc_input_hash=str(qc_payload.get("qc_input_hash") or ""),
                    qc_output_hash=str(qc_payload.get("qc_output_hash") or ""),
                    integrated_text=str(qc_payload.get("integrated_text") or ""),
                    integrated_text_sha256=str(
                        qc_payload.get("integrated_text_sha256") or ""
                    ),
                    notes=str(qc_payload.get("notes") or ""),
                )
            return FlashIntegrationOutcome(
                passed=bool(payload.get("passed")),
                final_text=str(payload.get("final_text") or ""),
                failure_codes=tuple(payload.get("failure_codes") or ()),
                qc_result=qc_result,
                attempts=int(payload.get("attempts") or 0),
                fallback_used=bool(payload.get("fallback_used")),
                diagnostic_codes=tuple(payload.get("diagnostic_codes") or ()),
            )
        raise ValueError(f"unsupported upper-layer stage: {stage}")

    def execute(
        self,
        *,
        stage: str,
        owner: UpperLayerStageOwner,
        prompt_version: str,
        input_payload: Any,
        input_hash: str,
        invoke: Callable[[str], Any],
        output_hash: Callable[[Any], str],
        immutable_body_hash: str = "",
    ) -> UpperLayerStageExecutionResult:
        del invoke  # The shared service invokes its own server-owned adapters.
        from .writing_reference_upper_layer_execution import (
            UpperLayerExecutionRequest,
        )

        prompt = self.prompt_resolver(stage, prompt_version)
        if not prompt.strip():
            raise ValueError("upper-layer prompt resolver returned an empty prompt")
        idempotency_material = {
            "owner": _upper_layer_hash_payload(owner),
            "stage": stage,
            "prompt_version": prompt_version,
            "input_hash": input_hash,
            "provider": str(getattr(self.service, "provider", "") or ""),
            "transport": str(getattr(self.service, "transport", "") or ""),
            "default_model": str(
                getattr(self.service, "default_model", "") or ""
            ),
            "escalation_model": str(
                getattr(self.service, "escalation_model", "") or ""
            ),
            "expected_response_model": str(
                getattr(self.service, "expected_response_model", "") or ""
            ),
            "retry_generation": owner.retry_generation,
            "retry_parent_stage_run_id": owner.retry_parent_stage_run_id,
            "contract_supersession_generation": (
                owner.contract_supersession_generation
            ),
            "contract_supersession_transition_version": (
                owner.contract_supersession_transition_version
            ),
            "contract_supersession_source_stage_run_id": (
                owner.contract_supersession_source_stage_run_id
            ),
            "contract_supersession_source_execution_fingerprint": (
                owner.contract_supersession_source_execution_fingerprint
            ),
            "contract_supersession_source_prompt_version": (
                owner.contract_supersession_source_prompt_version
            ),
            "contract_supersession_target_prompt_version": (
                owner.contract_supersession_target_prompt_version
            ),
        }
        request = UpperLayerExecutionRequest(
            project_id=owner.project_id,
            owner_type=owner.owner_type,
            owner_id=owner.owner_id,
            artifact_id=owner.artifact_id,
            extraction_revision=owner.extraction_revision,
            stage=stage,
            prompt_version=prompt_version,
            prompt=prompt,
            deployment_profile=self.deployment_profile,
            input_payload=input_payload,
            idempotency_key=(
                "upper-stage-" + _upper_layer_payload_hash(idempotency_material)[:40]
            ),
            batch_id=owner.batch_id,
            item_id=owner.item_id,
            plan_id=owner.plan_id,
            chapter_id=owner.chapter_id,
            hy_mt2_target_map_sha256=immutable_body_hash,
            retry_generation=owner.retry_generation,
            retry_parent_stage_run_id=owner.retry_parent_stage_run_id,
            contract_supersession_generation=(
                owner.contract_supersession_generation
            ),
            contract_supersession_transition_version=(
                owner.contract_supersession_transition_version
            ),
            contract_supersession_source_stage_run_id=(
                owner.contract_supersession_source_stage_run_id
            ),
            contract_supersession_source_execution_fingerprint=(
                owner.contract_supersession_source_execution_fingerprint
            ),
            contract_supersession_source_prompt_version=(
                owner.contract_supersession_source_prompt_version
            ),
            contract_supersession_target_prompt_version=(
                owner.contract_supersession_target_prompt_version
            ),
        )
        outcome = self.service.execute(request)
        selected_run = outcome.selected_run
        latest_run = outcome.latest_run
        if outcome.selected_output is None:
            failure_code = (
                str(selected_run.failure_code or "").strip()
                or str(latest_run.failure_code or "").strip()
                or "upper_layer_stage_failed_without_output"
            )
            if stage == UPPER_LAYER_DOCUMENT_PLANNING:
                raise DocumentPlanValidationError(
                    (failure_code,),
                    source_stage_run_id=selected_run.stage_run_id,
                    latest_stage_run_id=latest_run.stage_run_id,
                )
            raise ChapterTranslationPipelineError(failure_code)
        output = self.output_decoder(stage, outcome.selected_output)
        calculated_hash = output_hash(output)
        if selected_run.output_hash != calculated_hash:
            raise ChapterTranslationPipelineError(
                "persisted upper-layer output hash does not match decoded output"
            )
        escalation = outcome.escalation
        selected_is_escalation = bool(
            selected_run.parent_stage_run_id and selected_run.escalation_id
        )
        return UpperLayerStageExecutionResult(
            output=output,
            stage=stage,
            requested_model=selected_run.requested_model,
            response_model=selected_run.response_model,
            expected_response_model=str(
                getattr(self.service, "expected_response_model", "")
                or selected_run.requested_model
            ),
            prompt_version=selected_run.prompt_version,
            input_hash=selected_run.input_hash,
            output_hash=selected_run.output_hash,
            status=selected_run.status,
            stage_run_id=selected_run.stage_run_id,
            latest_stage_run_id=latest_run.stage_run_id,
            latest_status=latest_run.status,
            parent_stage_run_id=selected_run.parent_stage_run_id,
            # The selected result may intentionally fall back to a usable
            # completed_degraded Flash run after the Pro child fails. In that
            # case the selected run is not itself an escalation child; keep
            # its lineage empty while latest_stage_run_id/latest_status retain
            # the attempted Pro execution for audit.
            escalation_id=selected_run.escalation_id,
            escalation_trigger_status=(
                escalation.trigger_status
                if escalation is not None and selected_is_escalation
                else ""
            ),
            escalation_trigger_code=(
                escalation.trigger_code
                if escalation is not None and selected_is_escalation
                else ""
            ),
            provider=selected_run.provider,
            transport=selected_run.transport,
            deployment_profile=selected_run.deployment_profile,
            provider_call_count=selected_run.provider_call_count,
            planner_attempt_count=int(
                getattr(selected_run, "planner_attempt_count", 0) or 0
            ),
            provider_call_attempts=tuple(
                (
                    attempt.model_dump(mode="json")
                    if hasattr(attempt, "model_dump")
                    else dict(attempt)
                )
                for attempt in (
                    getattr(selected_run, "provider_call_attempts", ()) or ()
                )
            ),
            failure_code=selected_run.failure_code,
            retry_generation=int(
                getattr(selected_run, "retry_generation", 0) or 0
            ),
            retry_parent_stage_run_id=str(
                getattr(selected_run, "retry_parent_stage_run_id", "") or ""
            ),
            contract_supersession_generation=int(
                getattr(
                    selected_run,
                    "contract_supersession_generation",
                    0,
                )
                or 0
            ),
            contract_supersession_transition_version=str(
                getattr(
                    selected_run,
                    "contract_supersession_transition_version",
                    "",
                )
                or ""
            ),
            contract_supersession_source_stage_run_id=str(
                getattr(
                    selected_run,
                    "contract_supersession_source_stage_run_id",
                    "",
                )
                or ""
            ),
            contract_supersession_source_execution_fingerprint=str(
                getattr(
                    selected_run,
                    "contract_supersession_source_execution_fingerprint",
                    "",
                )
                or ""
            ),
            contract_supersession_source_prompt_version=str(
                getattr(
                    selected_run,
                    "contract_supersession_source_prompt_version",
                    "",
                )
                or ""
            ),
            contract_supersession_target_prompt_version=str(
                getattr(
                    selected_run,
                    "contract_supersession_target_prompt_version",
                    "",
                )
                or ""
            ),
        )


class ChapterTranslationPipelineError(RuntimeError):
    """Base error for pipeline failures."""


class UpperLayerBodyMutationError(ChapterTranslationPipelineError):
    """Raised when an upper-layer model attempts to change Hy-MT2 body text."""


class FidelityBlockedError(ChapterTranslationPipelineError):
    """Raised when fidelity checks block candidate readiness."""

    def __init__(
        self,
        failure_codes: tuple[str, ...],
        *,
        last_output: str = "",
        raw_provider_output: str = "",
    ) -> None:
        self.failure_codes = failure_codes
        # ``last_output`` is the normalized aligned text that was actually
        # evaluated to produce ``failure_codes``.  The separate raw provider
        # output is retained for audit only and is never admitted.
        self.last_output = last_output
        self.raw_provider_output = raw_provider_output or last_output
        super().__init__(f"fidelity blocked: {failure_codes}")


class OcrConcurrencyExceededError(ChapterTranslationPipelineError):
    """Raised when OCR concurrency exceeds the configured maximum."""


class CompositePipelineUnavailableError(ChapterTranslationPipelineError):
    """Raised when a required composite-pipeline runtime dependency is missing.

    This is a retryable/terminal product state — never a silent fallback to
    the legacy Flash-only path.
    """


# ---------------------------------------------------------------------------
# The pipeline orchestrator.
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _upper_layer_hash_payload(value: Any) -> Any:
    if is_dataclass(value):
        return _upper_layer_hash_payload(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return _upper_layer_hash_payload(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(key): _upper_layer_hash_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_upper_layer_hash_payload(item) for item in value]
    return value


def _upper_layer_payload_hash(value: Any) -> str:
    canonical = json.dumps(
        _upper_layer_hash_payload(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(canonical)


@dataclass
class ChapterTranslationPipeline:
    """Orchestrates the auditable chapter translation pipeline.

    All external calls are injected via the constructor.  In production these
    are wired to the OCR gateway and OpenAI-compatible provider abstractions;
    in tests they are deterministic fakes.

    When ``stage_observer`` is provided, it is called with ``("before",
    stage, detail)`` immediately before each external call and ``("after",
    stage, detail)`` immediately after success, so the caller can persist
    each meaningful stage transition as it happens — not retroactively.
    """

    ocr_runner: OcrPageRunner
    flash_planner: FlashPlanner
    hy_mt2_translator: HyMt2Translator
    flash_qc_runner: FlashQcRunner
    ocr_max_concurrency: int = WRITING_REFERENCE_OCR_MAX_CONCURRENCY
    ocr_dpi: int = WRITING_REFERENCE_OCR_MIN_DPI
    ocr_model: str = WRITING_REFERENCE_OCR_MODEL
    ocr_profile: str = WRITING_REFERENCE_OCR_PROFILE
    ocr_model_resolver: Callable[[], str] | None = None
    stage_observer: StageObserver | None = None
    upper_layer_executor: UpperLayerStageExecutor | None = None
    upper_layer_planner_factory: Callable[[str], FlashPlanner] | None = None
    upper_layer_qc_factory: Callable[[str], FlashQcRunner] | None = None
    ocr_profile_digest_fn: Callable[[str], str] = lambda profile: hashlib.sha256(
        json.dumps(
            {"profile": profile, "model": WRITING_REFERENCE_OCR_MODEL},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    def __post_init__(self) -> None:
        self.ocr_max_concurrency = enforce_ocr_concurrency(self.ocr_max_concurrency)
        if self.ocr_dpi < WRITING_REFERENCE_OCR_MIN_DPI:
            raise ValueError(f"OCR DPI must be >= {WRITING_REFERENCE_OCR_MIN_DPI}")

    def _notify(
        self, phase: str, stage: TranslationPipelineStage, **detail: Any
    ) -> None:
        if self.stage_observer is not None:
            self.stage_observer(phase, stage, detail)

    def _planner_for_upper_layer_model(self, model: str) -> FlashPlanner:
        if not model.strip():
            raise ValueError("upper-layer model is required")
        if self.upper_layer_planner_factory is not None:
            return self.upper_layer_planner_factory(model)
        if model == FLASH_PLANNING_MODEL:
            return self.flash_planner
        raise CompositePipelineUnavailableError(
            "Pro document-planning adapter is not wired"
        )

    def _qc_for_upper_layer_model(self, model: str) -> FlashQcRunner:
        if not model.strip():
            raise ValueError("upper-layer model is required")
        if self.upper_layer_qc_factory is not None:
            return self.upper_layer_qc_factory(model)
        if model == FLASH_QC_MODEL:
            return self.flash_qc_runner
        raise CompositePipelineUnavailableError(
            "Pro integration-QC adapter is not wired"
        )

    @staticmethod
    def _legacy_upper_layer_result(
        *,
        output: Any,
        stage: str,
        prompt_version: str,
        input_hash: str,
        output_hash: str,
    ) -> UpperLayerStageExecutionResult:
        return UpperLayerStageExecutionResult(
            output=output,
            stage=stage,
            requested_model=FLASH_PLANNING_MODEL,
            response_model=FLASH_PLANNING_MODEL,
            prompt_version=prompt_version,
            input_hash=input_hash,
            output_hash=output_hash,
        )

    @staticmethod
    def _validate_upper_layer_execution(
        execution: UpperLayerStageExecutionResult,
        *,
        stage: str,
        prompt_version: str,
        input_hash: str,
        calculated_output_hash: str,
    ) -> None:
        if execution.stage != stage:
            raise ChapterTranslationPipelineError(
                "upper-layer stage result does not match the requested stage"
            )
        if not execution.requested_model.strip():
            raise ChapterTranslationPipelineError(
                "upper-layer stage returned an empty model identity"
            )
        if execution.status in {"succeeded", "completed_degraded"}:
            if execution.response_model != (
                execution.expected_response_model or execution.requested_model
            ):
                raise ChapterTranslationPipelineError(
                    "upper-layer response model does not match configured expectation"
                )
        if bool(execution.parent_stage_run_id) != bool(execution.escalation_id):
            raise ChapterTranslationPipelineError(
                "upper-layer escalation lineage is incomplete"
            )
        if bool(execution.retry_generation) != bool(
            execution.retry_parent_stage_run_id
        ):
            raise ChapterTranslationPipelineError(
                "upper-layer retry lineage is incomplete"
            )
        if (
            execution.retry_parent_stage_run_id
            and stage != UPPER_LAYER_DOCUMENT_PLANNING
        ):
            raise ChapterTranslationPipelineError(
                "upper-layer retry lineage is invalid for this stage"
            )
        supersession_values = (
            execution.contract_supersession_transition_version,
            execution.contract_supersession_source_stage_run_id,
            execution.contract_supersession_source_execution_fingerprint,
            execution.contract_supersession_source_prompt_version,
            execution.contract_supersession_target_prompt_version,
        )
        if bool(execution.contract_supersession_generation) != bool(
            any(supersession_values)
        ) or (
            execution.contract_supersession_generation
            and not all(value.strip() for value in supersession_values)
        ):
            raise ChapterTranslationPipelineError(
                "upper-layer contract supersession lineage is incomplete"
            )
        if execution.contract_supersession_generation:
            if (
                stage != UPPER_LAYER_DOCUMENT_PLANNING
                or execution.retry_generation
                or execution.retry_parent_stage_run_id
            ):
                raise ChapterTranslationPipelineError(
                    "upper-layer contract supersession lineage is invalid"
                )
            if (
                execution.contract_supersession_target_prompt_version
                != prompt_version
            ):
                raise ChapterTranslationPipelineError(
                    "upper-layer supersession target contract mismatch"
                )
        if execution.parent_stage_run_id:
            if execution.escalation_trigger_status not in {
                "failed_escalatable",
                "completed_degraded",
            }:
                raise ChapterTranslationPipelineError(
                    "upper-layer escalation has an ineligible trigger"
                )
        if execution.prompt_version != prompt_version:
            raise ChapterTranslationPipelineError(
                "upper-layer prompt lineage does not match the stage contract"
            )
        if execution.input_hash != input_hash:
            raise ChapterTranslationPipelineError(
                "upper-layer input hash does not match the frozen stage input"
            )
        if execution.output_hash != calculated_output_hash:
            raise ChapterTranslationPipelineError(
                "upper-layer output hash does not match the returned output"
            )

    def execute_document_planning_stage(
        self,
        source_text: str,
        document_context: dict[str, Any],
        *,
        owner: UpperLayerStageOwner,
        bounded_structural_retry: bool = False,
    ) -> tuple[FlashPlanResult, UpperLayerStageExecutionResult]:
        """Run server-routed document planning without exposing route controls."""

        input_payload = {
            "source_text": source_text,
            "document_context": document_context,
        }
        input_hash = _upper_layer_payload_hash(input_payload)

        def _invoke(model: str) -> FlashPlanResult:
            planner = self._planner_for_upper_layer_model(model)
            result = (
                call_flash_planner_with_single_retry(
                    planner, source_text, document_context
                )
                if bounded_structural_retry
                else planner(source_text, document_context)
            )
            if result.plan_model != model:
                raise ChapterTranslationPipelineError(
                    "document planner returned the wrong model identity"
                )
            return result

        if self.upper_layer_executor is None:
            output = _invoke(FLASH_PLANNING_MODEL)
            execution = self._legacy_upper_layer_result(
                output=output,
                stage=UPPER_LAYER_DOCUMENT_PLANNING,
                prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                input_hash=input_hash,
                output_hash=_upper_layer_payload_hash(output),
            )
        else:
            execution = self.upper_layer_executor.execute(
                stage=UPPER_LAYER_DOCUMENT_PLANNING,
                owner=owner,
                prompt_version=FLASH_PLANNING_PROMPT_VERSION,
                input_payload=input_payload,
                input_hash=input_hash,
                invoke=_invoke,
                output_hash=_upper_layer_payload_hash,
            )
            output = execution.output
        if not isinstance(output, FlashPlanResult):
            raise ChapterTranslationPipelineError(
                "upper-layer document planning returned an invalid result"
            )
        self._validate_upper_layer_execution(
            execution,
            stage=UPPER_LAYER_DOCUMENT_PLANNING,
            prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            input_hash=input_hash,
            calculated_output_hash=_upper_layer_payload_hash(output),
        )
        return output, execution

    def execute_integration_qc_stage(
        self,
        *,
        units: Sequence["TranslationUnit"],
        target_map: dict[int, str],
        owner: UpperLayerStageOwner,
    ) -> tuple["FlashIntegrationOutcome", UpperLayerStageExecutionResult]:
        """Run Flash/Pro upper-layer QC over one immutable Hy-MT2 target map."""

        frozen_target_map = dict(target_map)
        immutable_body_hash = _upper_layer_payload_hash(
            {
                "hy_mt2_target_map": {
                    str(key): value
                    for key, value in sorted(frozen_target_map.items())
                }
            }
        )
        input_payload = {
            "units": [
                {"ordinal": unit.ordinal, "source_text": unit.text}
                for unit in units
            ],
            "hy_mt2_target_map": {
                str(key): value for key, value in sorted(frozen_target_map.items())
            },
        }
        input_hash = _upper_layer_payload_hash(input_payload)

        def _invoke(model: str) -> FlashIntegrationOutcome:
            outcome = integrate_units_with_flash(
                self._qc_for_upper_layer_model(model),
                units=units,
                target_map=frozen_target_map,
            )
            qc_result = outcome.qc_result
            if qc_result is not None and qc_result.qc_model != model:
                raise ChapterTranslationPipelineError(
                    "integration QC returned the wrong model identity"
                )
            if model == PRO_UPPER_LAYER_MODEL and outcome.fallback_used:
                mutation_codes = {
                    code
                    for code in outcome.diagnostic_codes
                    if "mutation" in code or "drift" in code
                }
                if mutation_codes:
                    raise UpperLayerBodyMutationError(
                        "Pro integration attempted to modify Hy-MT2 body text"
                    )
            return outcome

        def _outcome_hash(outcome: FlashIntegrationOutcome) -> str:
            return _upper_layer_payload_hash(outcome)

        if self.upper_layer_executor is None:
            output = _invoke(FLASH_QC_MODEL)
            execution = self._legacy_upper_layer_result(
                output=output,
                stage=UPPER_LAYER_POST_HY_INTEGRATION_QC,
                prompt_version=FLASH_QC_PROMPT_VERSION,
                input_hash=input_hash,
                output_hash=_outcome_hash(output),
            )
        else:
            execution = self.upper_layer_executor.execute(
                stage=UPPER_LAYER_POST_HY_INTEGRATION_QC,
                owner=owner,
                prompt_version=FLASH_QC_PROMPT_VERSION,
                input_payload=input_payload,
                input_hash=input_hash,
                invoke=_invoke,
                output_hash=_outcome_hash,
                immutable_body_hash=immutable_body_hash,
            )
            output = execution.output
        if not isinstance(output, FlashIntegrationOutcome):
            raise ChapterTranslationPipelineError(
                "upper-layer integration QC returned an invalid result"
            )
        if target_map != frozen_target_map:
            raise UpperLayerBodyMutationError(
                "upper-layer integration mutated the Hy-MT2 target map"
            )
        expected_body = reassemble_aligned_translation(units, frozen_target_map)
        if output.passed and output.final_text != expected_body:
            raise UpperLayerBodyMutationError(
                "upper-layer integration changed the Hy-MT2 body"
            )
        self._validate_upper_layer_execution(
            execution,
            stage=UPPER_LAYER_POST_HY_INTEGRATION_QC,
            prompt_version=FLASH_QC_PROMPT_VERSION,
            input_hash=input_hash,
            calculated_output_hash=_outcome_hash(output),
        )
        return output, execution

    def run_ocr_for_pages(
        self,
        ocr_pages: Sequence[int],
        page_image_provider: Callable[[int], bytes],
    ) -> tuple[OcrPageLineage, ...]:
        """Run OCR for the given pages, enforcing DPI and concurrency bounds.

        ``page_image_provider`` renders a single page to PNG bytes at the
        configured DPI.  This avoids sharing a PyMuPDF document across worker
        threads.  Pages are processed in batches of at most
        ``ocr_max_concurrency`` concurrent OCR calls; every selected page is
        processed (there is no total-page cap).

        Returns lineage records ordered by physical page number.
        """
        if not ocr_pages:
            return ()
        self._notify(
            "before", TranslationPipelineStage.OCR_RUNNING, pages=list(ocr_pages)
        )

        ordered_pages = sorted(ocr_pages)
        max_workers = enforce_ocr_concurrency(self.ocr_max_concurrency)
        lineage_by_page: dict[int, OcrPageLineage] = {}

        def _process_page(page: int) -> OcrPageLineage:
            ocr_model = (
                self.ocr_model_resolver() if self.ocr_model_resolver else self.ocr_model
            )
            spec = build_ocr_render_spec(
                page,
                dpi=self.ocr_dpi,
                model=ocr_model,
                ocr_profile=self.ocr_profile,
            )
            image_bytes = page_image_provider(page)
            ocr_text = self.ocr_runner(
                spec.physical_page, spec.dpi, spec.model, image_bytes
            )
            return OcrPageLineage(
                physical_page=page,
                dpi=spec.dpi,
                model=spec.model,
                ocr_profile_digest=self.ocr_profile_digest_fn(spec.ocr_profile),
                source_text_sha256=_sha256(ocr_text),
                channel="ocr",
            )

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_page, page): page for page in ordered_pages
            }
            for future in concurrent.futures.as_completed(futures):
                page = futures[future]
                lineage_by_page[page] = future.result()

        lineage_records = [lineage_by_page[page] for page in ordered_pages]
        self._notify(
            "after", TranslationPipelineStage.OCR_RUNNING, pages=lineage_records
        )
        return tuple(lineage_records)

    def translate_chapter(
        self,
        *,
        source_text: str,
        document_sha256: str,
        extraction_revision: str,
        chapter_id: str,
        chunk_id: str,
        glossary_version: str,
        ocr_page_lineage: tuple[OcrPageLineage, ...] = (),
        document_context: Optional[dict[str, Any]] = None,
        call_observer: Optional[StageObserver] = None,
        user_instruction: str = "",
        glossary_contract: str = "",
        upper_layer_owner: UpperLayerStageOwner | None = None,
    ) -> PipelineCandidate:
        """Execute Flash plan -> Hy-MT2 translate -> Flash QC for one chapter.

        This is the authoritative body-translation path.  Flash is never the
        sole translator: it plans and then QCs, but the body text comes from
        the local Hy-MT2 model.

        ``user_instruction`` carries the user instruction and (for revisions)
        the medical-review comment.  ``glossary_contract`` carries the
        rendered, source-matched bilingual term contract.  Both are forwarded
        to every stage so the planner, body translator and QC operate under
        the same product, glossary and review constraints.

        Each external call is preceded and followed by a stage observer
        notification so the caller can persist progress in real time.

        ``call_observer`` allows a per-call observer that does not mutate the
        shared ``stage_observer`` attribute — safe for concurrent items.
        """
        document_context = dict(document_context or {})
        # Product instructions and the rendered glossary contract must reach
        # every stage.  Document context is the channel the Flash planner and
        # QC receive; Hy-MT2 receives the glossary contract via its glossary
        # argument.
        if user_instruction:
            document_context["user_instruction"] = user_instruction
        if glossary_contract:
            document_context["glossary_contract"] = glossary_contract
        effective_glossary = glossary_contract or glossary_version
        effective_owner = upper_layer_owner or UpperLayerStageOwner(
            project_id="",
            owner_type="direct_translation",
            owner_id=f"{chapter_id}:{chunk_id}",
            artifact_id=document_sha256,
            extraction_revision=extraction_revision,
            chapter_id=chapter_id,
        )

        def _emit(phase: str, stage: TranslationPipelineStage, **detail: Any) -> None:
            if call_observer is not None:
                call_observer(phase, stage, detail)
            self._notify(phase, stage, **detail)

        # Stage 1: Flash TOC/chapter planning — before/after notification.
        _emit(
            "before",
            TranslationPipelineStage.TOC_PLANNING,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
        )
        flash_plan, plan_execution = self.execute_document_planning_stage(
            source_text,
            document_context,
            owner=effective_owner,
        )
        _emit(
            "after",
            TranslationPipelineStage.TOC_PLANNING,
            plan_model=flash_plan.plan_model,
            plan_prompt_version=flash_plan.plan_prompt_version,
            upper_layer_stage=plan_execution.stage,
            upper_layer_stage_run_id=(
                plan_execution.latest_stage_run_id
                or plan_execution.stage_run_id
            ),
            upper_layer_parent_stage_run_id=plan_execution.parent_stage_run_id,
            upper_layer_escalation_id=plan_execution.escalation_id,
            upper_layer_status=(
                plan_execution.latest_status or plan_execution.status
            ),
            upper_layer_progress_label=(
                "增强分析未通过，已保留可用的章节结构"
                if plan_execution.latest_status
                in {"failed_retryable", "failed_terminal", "interrupted"}
                else "已使用增强分析完成章节结构识别"
                if plan_execution.requested_model == PRO_UPPER_LAYER_MODEL
                else "章节结构识别完成"
            ),
        )

        # Stage 2: Hy-MT2 chapter/chunk translation (body translator).
        # V11: source is split into ordered semantic translation units,
        # wrapped in stable ASCII markers so the output can be parsed
        # unit-by-unit and checked for alignment.  Failed unit
        # coverage/cardinality or unit-level deterministic fidelity triggers
        # at most one corrective retry naming the exact failing unit IDs;
        # a second failure blocks.
        _emit(
            "before",
            TranslationPipelineStage.TRANSLATING_HY_MT2,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
        )
        units = split_source_into_units(source_text)
        hy_mt2_result, parsed_map = translate_units_with_bounded_correction(
            self.hy_mt2_translator,
            units=units,
            glossary=effective_glossary,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
        )
        # Reassemble the aligned translation for diagnostics and lineage.
        aligned_translation = reassemble_aligned_translation(units, parsed_map)
        _emit(
            "after",
            TranslationPipelineStage.TRANSLATING_HY_MT2,
            hy_mt2_model=hy_mt2_result.model,
            hy_mt2_prompt_version=hy_mt2_result.prompt_version,
            translation_strategy=hy_mt2_result.translation_strategy,
            translated_text_sha256=_sha256(aligned_translation),
            unit_count=len(units),
        )

        # Stage 3: Flash integration QC over aligned marked source/target
        # envelopes.  Flash must preserve the unit markers exactly; they are
        # validated and removed only after validation, with at most one
        # corrective pass.  A second deterministic failure blocks.
        _emit(
            "before",
            TranslationPipelineStage.INTEGRATION_QC,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
        )
        integration_owner = UpperLayerStageOwner(
            project_id=effective_owner.project_id,
            owner_type=effective_owner.owner_type,
            owner_id=effective_owner.owner_id,
            artifact_id=effective_owner.artifact_id,
            extraction_revision=effective_owner.extraction_revision,
            batch_id=effective_owner.batch_id,
            item_id=effective_owner.item_id,
            plan_id=effective_owner.plan_id,
            chapter_id=chapter_id,
        )
        integration, qc_execution = self.execute_integration_qc_stage(
            units=units,
            target_map=parsed_map,
            owner=integration_owner,
        )
        flash_qc = integration.qc_result or FlashQcResult(
            passed=False,
            failure_codes=integration.failure_codes,
            qc_prompt_version=FLASH_QC_PROMPT_VERSION,
            qc_model=FLASH_QC_MODEL,
            qc_input_hash=_sha256(format_flash_integration_envelope(units, parsed_map)),
            qc_output_hash="",
            integrated_text="",
            integrated_text_sha256="",
            notes="flash integration unavailable",
        )
        _emit(
            "after",
            TranslationPipelineStage.INTEGRATION_QC,
            qc_model=flash_qc.qc_model,
            qc_prompt_version=flash_qc.qc_prompt_version,
            qc_passed=integration.passed,
            qc_failure_codes=list(integration.failure_codes),
            qc_diagnostic_codes=list(integration.diagnostic_codes),
            qc_attempts=integration.attempts,
            hy_fallback_used=integration.fallback_used,
            upper_layer_stage=qc_execution.stage,
            upper_layer_stage_run_id=(
                qc_execution.latest_stage_run_id
                or qc_execution.stage_run_id
            ),
            upper_layer_parent_stage_run_id=qc_execution.parent_stage_run_id,
            upper_layer_escalation_id=qc_execution.escalation_id,
            upper_layer_status=(
                qc_execution.latest_status or qc_execution.status
            ),
            upper_layer_progress_label=(
                "增强分析未通过，已保留原译文供核对"
                if qc_execution.latest_status
                in {"failed_retryable", "failed_terminal", "interrupted"}
                else "已使用增强分析完成译文核对"
                if qc_execution.requested_model == PRO_UPPER_LAYER_MODEL
                else "译文结构与章节衔接核对完成"
            ),
        )

        # Flash is non-authoring: it may pass or block the normalized Hy-MT2
        # body, but it cannot replace that body.
        if integration.passed:
            final_text = integration.final_text
            final_text_sha256 = _sha256(final_text)
        else:
            final_text = aligned_translation
            final_text_sha256 = _sha256(aligned_translation)
        # Marker transport must never leak into the candidate.
        if contains_unit_markers(final_text):
            raise ChapterTranslationPipelineError(
                "translation-unit markers leaked into the final candidate"
            )

        # Deterministic fidelity gate: the aligned Flash integration and the
        # per-unit deterministic checks together determine candidate
        # readiness.  A blocked integration is never silently admitted.
        final_stage = (
            TranslationPipelineStage.CANDIDATE_READY
            if integration.passed
            else TranslationPipelineStage.FIDELITY_BLOCKED
        )

        # Build lineage.
        lineage = ChapterTranslationLineage(
            document_sha256=document_sha256,
            extraction_revision=extraction_revision,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            glossary_version=glossary_version,
            ocr_pages=ocr_page_lineage,
            hy_mt2_model=hy_mt2_result.model,
            flash_planning_prompt_version=flash_plan.plan_prompt_version,
            flash_qc_prompt_version=flash_qc.qc_prompt_version,
            hy_mt2_prompt_version=hy_mt2_result.prompt_version,
            source_text_sha256=_sha256(source_text),
            translated_text_sha256=final_text_sha256,
            stage=final_stage,
        )

        return PipelineCandidate(
            lineage=lineage,
            translated_text=final_text,
            flash_plan=flash_plan,
            hy_mt2=hy_mt2_result,
            flash_qc=flash_qc,
            fidelity_passed=integration.passed,
            needs_medical_approval=True,
        )


# ---------------------------------------------------------------------------
# Document-level planning, chunking, and chapter integration (Round 7).
#
# The authoritative workflow is:
#
#   one document plan (Flash planner, once per artifact/extraction/contract)
#   -> deterministic chunking on current source spans
#   -> Hy-MT2 translation per chunk
#   -> Flash integration QC per chapter over ordered chunk outputs
#   -> deterministic fidelity gate on the integrated chapter candidate
#   -> medical review and corpus admission
#
# This replaces the legacy per-span ``translate_chapter`` loop which repeated
# Flash planning, Hy-MT2 and Flash QC for every source span — fragmenting
# the document and making integration QC impossible.
# ---------------------------------------------------------------------------

# Default chunk contract parameters.
# Reduced from 6000 to 3000 in V11: smaller chunks keep Hy-MT2 within its
# reliable context window, reduce unit-boundary drift, and make per-unit
# fidelity checks precise.
CHUNK_TARGET_CHARS = 3000
CHUNK_ADJACENT_CONTEXT_CHARS = 600
CHUNK_OVERSIZE_MARK = "OVERSIZE_INDIVISIBLE_UNIT"

# Bounded semantic translation-unit size (V11).  A production probe showed
# that one long unsegmented source line still lost a citation marker and a
# controlled term, so long lines are further split at safe sentence, bullet
# and numbered-criterion boundaries.  1200 characters keeps several dense
# eligibility clauses per unit while staying well inside the chunk target.
UNIT_TARGET_CHARS = 1200

# Fingerprint of the current downstream translation contract; persisted into
# chunk fingerprints and integration identity (see
# :func:`translation_contract_fingerprint`).
TRANSLATION_CONTRACT_FINGERPRINT = translation_contract_fingerprint()

# Flash integration provider input limit (characters of source + translated
# chapter envelope).  Ordinary multi-chunk chapters under this limit use a
# single integration call with integration_windowed=False.  Only chapters
# that exceed the limit use ordered windows + a final envelope check.
INTEGRATION_PROVIDER_INPUT_LIMIT = 50000


def format_hy_mt2_prompt_envelope(source_text: str, read_only_context: str = "") -> str:
    """Build an explicit prompt envelope separating read-only context from source.

    The translator must translate only the SOURCE_TEXT block.  Read-only
    continuity context is labelled and must not be copied into the output.
    """
    source_block = (
        "【待翻译原文 SOURCE_TEXT — translate only this block; "
        "output must correspond only to SOURCE_TEXT】\n"
        f"{source_text}"
    )
    if not (read_only_context or "").strip():
        return source_block
    return (
        "【只读上下文 READ_ONLY_CONTEXT — do not translate or copy this block "
        "into the output; continuity reference only】\n"
        f"{read_only_context}\n\n"
        f"{source_block}"
    )


# ---------------------------------------------------------------------------
# Translation-unit contract (V11 aligned units).
#
# Source text is split into ordered, nonempty semantic translation units.
# Paragraph/list/table-row boundaries are preserved; long lines are further
# split at safe sentence, bullet and numbered-criterion boundaries without
# breaking decimal numbers, abbreviations or comparator expressions.  Each
# unit receives a stable ASCII ID (``[[CMS_SEG_0001]]``) that is deterministic
# from the source order and re-derivable from the stored source text.  The
# Hy-MT2 envelope wraps each unit in markers so the output can be parsed back
# unit-by-unit and checked for alignment.  Misaligned output (missing,
# duplicate, reordered, unknown or empty units) is rejected deterministically
# — never silently admitted.  Markers are never exposed in the admitted
# Chinese corpus or writing candidate.
# ---------------------------------------------------------------------------

# Delimiter sentinels — plain ASCII, chosen to be extremely unlikely in
# clinical protocol text so parsing is robust without escaping.
_UNIT_SOURCE_OPEN = "[[CMS_SEG_{:04d}]]"
_UNIT_SOURCE_CLOSE = "[[/CMS_SEG_{:04d}]]"

_UNIT_TARGET_OPEN_RE = re.compile(r"\[\[CMS_SEG_(\d{1,4})\]\]")
_UNIT_TARGET_CLOSE_RE = re.compile(r"\[\[/CMS_SEG_\d{1,4}\]\]")
_UNIT_CURRENT_MARKER_RE = re.compile(
    r"\[\[(?P<close>/?)CMS_SEG_(?P<ordinal>\d{1,4})\]\]"
)
# Any unit marker (current ASCII format or the retired legacy ⟦UNIT_*⟧ form).
_UNIT_ANY_MARKER_RE = re.compile(
    r"\[\[/?CMS_SEG_\d{1,4}\]\]|⟦/?UNIT_(?:SRC|TGT)_\d{1,4}⟧"
)


def contains_unit_markers(text: str) -> bool:
    """Return True when text still carries translation-unit markers.

    Markers are a transport contract only; they must never reach the admitted
    Chinese corpus or writing candidate.
    """
    return bool(_UNIT_ANY_MARKER_RE.search(text or ""))


def strip_unit_markers(text: str) -> str:
    """Remove translation-unit markers from ``text``.

    Used for diagnostic retention of blocked model output; the admitted
    candidate path removes markers only through validated parsing.
    """
    cleaned = _UNIT_ANY_MARKER_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


@dataclass(frozen=True)
class TranslationUnit:
    """One atomic translation unit with a stable ordinal ID.

    Units are split on paragraph boundaries first; over-long paragraphs are
    then split on list/table-row boundaries, and over-long lines at safe
    sentence/bullet/numbered-criterion boundaries.  Within a chunk, units are
    numbered starting at ``ordinal_start``.
    """

    ordinal: int
    text: str


# Safe intra-line split boundaries.  Each pattern is guarded so decimal
# numbers (``2.0``), abbreviations (``e.g.``) and comparator/endpoint
# expressions (``>=``, ``EASI-50``) are never split.
_UNIT_BULLET_BOUNDARY_RE = re.compile(r"[•▪◦❑]\s+")
_UNIT_LETTERED_ITEM_BOUNDARY_RE = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Ma-m][.)]\s+(?:[A-Za-z]|\d+(?:\.\d+)?))"
)
_UNIT_NUMBERED_CRITERION_RE = re.compile(
    r"(?<![\d.A-Za-z\-])(?:\d{1,2}|[A-Z])[.)]\s+(?=[A-Za-z(（≥])"
)
_UNIT_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(•\-*≥])")
_UNIT_TRAILING_ABBREV_RE = re.compile(
    r"(?:e\.g|i\.e|etc|vs|cf|approx|No|Nos|Fig|Dr|Sec)\.$", re.IGNORECASE
)
_ABBREVIATION_DEFINITION_LINE_RE = re.compile(
    r"^\s*Abbreviations?\s*:\s*",
    re.IGNORECASE,
)
_ABBREVIATION_DEFINITION_BOUNDARY_RE = re.compile(
    r"(?<=[;,])\s+(?=[A-Za-z][A-Za-z0-9.-]{0,20}\s*=)"
)
_ABBREVIATION_DEFINITION_KEY_RE = re.compile(
    r"(?:^|[;；,，])\s*(?:(?:Abbreviations?|缩略语(?:说明)?)\s*[:：]\s*)?"
    r"([A-Za-z][A-Za-z0-9.-]{0,20})\s*=",
    re.IGNORECASE,
)
_PHYSICAL_FRAGMENT_CONTINUATION_START_RE = re.compile(
    r"^(?:[a-z]|[\(\[\{±]|(?:and|or|but|with|without|obtained|see|"
    r"inadequate|hospitalization|assessment|requiring|during|within)\b)"
)
_PHYSICAL_FRAGMENT_INCOMPLETE_END_RE = re.compile(
    r"(?:[,，/]|(?:has|have|had|is|are|was|were|be|been|being|with|without|"
    r"of|for|to|and|or|as|by|the|a|an|from|within|during|before|after))\s*$",
    re.IGNORECASE,
)


def _long_line_split_offsets(line: str) -> list[int]:
    """Return safe split offsets inside an over-long line.

    Candidate boundaries are: before inline bullets, before a new numbered
    criterion, and after sentence-ending punctuation followed by a new
    sentence/list item.  Offsets that would break decimals, abbreviations or
    comparator expressions are excluded by the pattern guards.
    """
    offsets: set[int] = set()
    for match in _UNIT_BULLET_BOUNDARY_RE.finditer(line):
        if match.start() > 0:
            offsets.add(match.start())
    for match in _UNIT_NUMBERED_CRITERION_RE.finditer(line):
        if match.start() > 0:
            offsets.add(match.start())
    for match in _UNIT_SENTENCE_BOUNDARY_RE.finditer(line):
        prefix = line[max(0, match.start() - 8) : match.start() + 1]
        if _UNIT_TRAILING_ABBREV_RE.search(prefix):
            continue
        offsets.add(match.end())
    return sorted(offsets)


def _split_long_line(line: str, target_chars: int = UNIT_TARGET_CHARS) -> list[str]:
    """Split an over-long line at safe semantic boundaries.

    Segments are packed greedily up to ``target_chars``.  If no safe boundary
    exists within the window, the next forward boundary is used; a line with
    no boundaries at all is kept intact (indivisible unit).
    """
    if len(line) <= target_chars:
        return [line]
    offsets = _long_line_split_offsets(line)
    if not offsets:
        return [line]
    segments: list[str] = []
    start = 0
    while len(line) - start > target_chars:
        limit = start + target_chars
        eligible = [o for o in offsets if start + 40 <= o <= limit]
        if eligible:
            cut = max(eligible)
        else:
            forward = [o for o in offsets if o > start]
            cut = min(forward) if forward else len(line)
        segment = line[start:cut].strip()
        if segment:
            segments.append(segment)
        start = cut
    tail = line[start:].strip()
    if tail:
        segments.append(tail)
    return segments or [line]


def _split_multiple_numbered_criteria(line: str) -> list[str]:
    """Split a paragraph that contains more than one numbered criterion.

    PDF extraction can merge adjacent eligibility criteria into one physical
    paragraph.  Keeping two criteria in one model unit makes an optional
    parenthetical clause in the later criterion easy to omit.  The first
    criterion stays with its category label; each later criterion starts a new
    auditable unit.
    """
    matches = list(_UNIT_NUMBERED_CRITERION_RE.finditer(line))
    if not matches:
        return [line]
    prefix = line[: matches[0].start()].strip()
    # A short category label such as "Medical conditions 1." belongs with
    # the first criterion.  A long preceding sentence/list item means the
    # first detected criterion is a new semantic item and must start its own
    # unit; otherwise Hy-MT2 can merge its threshold into the preceding rule.
    short_category_prefix = (
        bool(prefix)
        and len(prefix) <= 80
        and not re.search(
            r"[.!?]\s|^\s*[-–—*](?:\s+|(?=[A-Za-z\u3400-\u9fff]))",
            prefix,
        )
    )
    if len(matches) == 1 and short_category_prefix:
        return [line]
    first_split_index = 1 if short_category_prefix else 0
    offsets = [match.start() for match in matches[first_split_index:]]
    segments: list[str] = []
    start = 0
    for offset in offsets:
        segment = line[start:offset].strip()
        if segment:
            segments.append(segment)
        start = offset
    tail = line[start:].strip()
    if tail:
        segments.append(tail)
    return segments or [line]


def _split_inline_bullet_items(line: str) -> list[str]:
    """Split PDF-flattened adjacent list items while preserving markers."""
    bullet_parts = re.split(
        r"(?<=[.!?])\s+(?=[-*]\s*[A-Z])",
        line,
    )
    parts: list[str] = []
    for bullet_part in bullet_parts:
        matches = list(_UNIT_LETTERED_ITEM_BOUNDARY_RE.finditer(bullet_part))
        if len(matches) <= 1:
            parts.append(bullet_part)
            continue
        start = 0
        for match in matches:
            if match.start() <= start:
                continue
            prefix = bullet_part[start : match.start()].strip()
            if prefix:
                parts.append(prefix)
            start = match.start()
        tail = bullet_part[start:].strip()
        if tail:
            parts.append(tail)
    return [part.strip() for part in parts if part.strip()] or [line]


def _split_abbreviation_definition_line(line: str) -> list[str]:
    """Split a dense abbreviation glossary into bounded groups of definitions.

    Dense protocol footnotes such as ``Abbreviations: AE = ...; PK = ...``
    invite a translation model to expand definitions or move numbers between
    entries when treated as one long unit.  Conversely, one marker per
    definition can exceed the model's stable marker count.  Groups of at most
    five definitions preserve exact punctuation while keeping marker
    cardinality bounded.  Pairs are small enough that Hy-MT2 preserves the
    literal ``=`` contract, while a typical protocol footnote remains under
    the empirically stable marker count.
    """
    definition_count = len(_ABBREVIATION_DEFINITION_KEY_RE.findall(line))
    if (
        line.count(";") < 2
        or definition_count < 2
        or (
            not _ABBREVIATION_DEFINITION_LINE_RE.search(line)
            and not re.match(r"^\s*[A-Za-z][A-Za-z0-9.-]{0,20}\s*=", line)
        )
    ):
        return [line]
    parts = [
        part.strip()
        for part in _ABBREVIATION_DEFINITION_BOUNDARY_RE.split(line)
        if part.strip()
    ]
    if len(parts) <= 1:
        return [line]
    groups: list[str] = []
    pending: list[str] = []
    for part in parts:
        # EASI-100 is frequently paraphrased as "score reduced to zero",
        # which changes the literal 100% source token and weakens auditability.
        # Give this one high-risk definition an isolated model unit.
        isolate = bool(re.search(r"(?:\bEASI-100\b|\b100\s*%)", part, re.I))
        if isolate:
            if pending:
                groups.append(" ".join(pending))
                pending = []
            groups.append(part)
            continue
        pending.append(part)
        if len(pending) == 2:
            groups.append(" ".join(pending))
            pending = []
    if pending:
        groups.append(" ".join(pending))
    return groups


def _physical_fragments_form_semantic_continuation(previous: str, current: str) -> bool:
    """Return whether adjacent PDF blocks are one unfinished semantic unit.

    Protocol PDFs commonly break one eligibility criterion into separate text
    blocks at a page, column, or layout boundary.  Translating those blocks as
    independent units invites the model to move the missing clause across unit
    markers or copy it from read-only context.  Only strong continuation
    signals are merged; headings and complete sentences remain independent.
    """
    left = (previous or "").strip()
    right = (current or "").strip()
    if not left or not right:
        return False
    if _looks_like_table_row(left) or _looks_like_table_row(right):
        return False
    if re.match(r"^\d+(?:\.\d+)*\s+\S", right) and len(right) <= 160:
        return False
    if _PHYSICAL_FRAGMENT_CONTINUATION_START_RE.search(right):
        return True
    if _PHYSICAL_FRAGMENT_INCOMPLETE_END_RE.search(left):
        return True
    return False


def _merge_physical_paragraph_fragments(paragraphs: Sequence[str]) -> list[str]:
    """Merge only adjacent physical fragments that form one semantic unit."""
    merged: list[str] = []
    for paragraph in paragraphs:
        text = (paragraph or "").strip()
        if not text:
            continue
        if merged and _physical_fragments_form_semantic_continuation(merged[-1], text):
            merged[-1] = f"{merged[-1]} {text}".strip()
        else:
            merged.append(text)
    return merged


def _looks_like_table_row(line: str) -> bool:
    """A markdown-style table row is indivisible: never split it for size."""
    stripped = line.strip()
    return (
        stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
    )


def split_source_into_units(
    source_text: str,
    *,
    ordinal_start: int = 1,
    target_chars: int = UNIT_TARGET_CHARS,
) -> tuple[TranslationUnit, ...]:
    """Split source text into ordered, nonempty semantic translation units.

    Splitting hierarchy:
    1. paragraph boundaries (double newlines);
    2. for over-long paragraphs, list/table-row boundaries (single newlines),
       packed up to ``target_chars`` — an intact table row is never split;
    3. for a single over-long line, safe sentence, bullet and
       numbered-criterion boundaries (decimals, abbreviations and comparator
       expressions are never broken).

    A completely empty source produces a single empty unit so the round-trip
    is identity-preserving.
    """
    if not source_text:
        return (TranslationUnit(ordinal=ordinal_start, text=""),)
    raw_paragraphs = _merge_physical_paragraph_fragments(
        re.split(r"\n\s*\n", source_text)
    )
    unit_texts: list[str] = []
    for para in raw_paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        abbreviation_entries = _split_abbreviation_definition_line(stripped)
        if len(abbreviation_entries) > 1:
            unit_texts.extend(abbreviation_entries)
            continue
        if _looks_like_table_row(stripped):
            unit_texts.append(stripped)
            continue
        inline_items = _split_inline_bullet_items(stripped)
        semantic_segments: list[str] = []
        for inline_item in inline_items:
            semantic_segments.extend(_split_multiple_numbered_criteria(inline_item))
        if len(semantic_segments) > 1:
            for criterion_segment in semantic_segments:
                unit_texts.extend(
                    _split_long_line(criterion_segment, target_chars)
                    if len(criterion_segment) > target_chars
                    else [criterion_segment]
                )
            continue
        if len(stripped) <= target_chars:
            unit_texts.append(stripped)
            continue
        lines = [line for line in stripped.split("\n")]
        if len(lines) <= 1:
            unit_texts.extend(_split_long_line(stripped, target_chars))
            continue
        # Pack physical lines (list items / table rows) up to the bound.
        current: list[str] = []
        current_len = 0
        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > target_chars:
                unit_texts.append("\n".join(current).strip())
                current = []
                current_len = 0
            abbreviation_entries = _split_abbreviation_definition_line(line)
            if len(abbreviation_entries) > 1:
                if current:
                    unit_texts.append("\n".join(current).strip())
                    current = []
                    current_len = 0
                unit_texts.extend(abbreviation_entries)
                continue
            if len(line) > target_chars and not _looks_like_table_row(line):
                for segment in _split_long_line(line, target_chars):
                    unit_texts.append(segment)
                continue
            current.append(line)
            current_len += line_len
        if current:
            unit_texts.append("\n".join(current).strip())
    unit_texts = [text for text in unit_texts if text]
    if not unit_texts:
        return (TranslationUnit(ordinal=ordinal_start, text=""),)
    return tuple(
        TranslationUnit(ordinal=ordinal_start + index, text=text)
        for index, text in enumerate(unit_texts)
    )


def format_unit_delimited_source(units: Sequence[TranslationUnit]) -> str:
    """Format units into a delimited source envelope for Hy-MT2.

    Each unit is wrapped in ``[[CMS_SEG_NNNN]]`` ... ``[[/CMS_SEG_NNNN]]``
    markers.  The model is instructed to produce the same markers exactly
    once each, in order, around its Chinese output.
    """
    blocks: list[str] = []
    for unit in units:
        blocks.append(
            f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
            f"{unit.text}\n"
            f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
        )
    return "\n\n".join(blocks)


def parse_unit_delimited_output(
    output: str,
    *,
    expected_ordinals: Sequence[int],
) -> tuple[dict[int, str], list[str]]:
    """Parse unit-delimited translation output into an ordinal->text map.

    Returns ``(parsed_map, error_codes)``.  ``parsed_map`` is empty when
    ``error_codes`` is non-empty.  Error codes are deterministic:
    - ``missing_unit_output:{ordinal}`` — a unit present in source has no
      matching target block.
    - ``extra_unit_output:{ordinal}`` — a target block with no matching
      source (unknown unit).
    - ``duplicate_unit_output:{ordinal}`` — a unit emitted more than once.
    - ``unclosed_unit_output:{ordinal}`` — open marker without close marker.
    - ``reordered_unit_output`` — target ordinals are not in ascending order.
    - ``no_unit_markers_in_output`` — markerless output, including a
      single-unit source.
    - ``text_outside_unit_markers`` — non-whitespace prose exists outside
      the declared marker blocks.

    The current contract is strict for both single- and multi-unit sources.
    Markerless legacy output is never admitted under the current contract.
    """
    error_codes: list[str] = []
    expected_set = set(expected_ordinals)
    parsed: dict[int, str] = {}
    seen_ordinals: list[int] = []
    opened_ordinals: set[int] = set()
    marker_matches = list(_UNIT_CURRENT_MARKER_RE.finditer(output))
    if not marker_matches:
        return {}, ["no_unit_markers_in_output"]

    open_ordinal: int | None = None
    content_start = 0
    cursor = 0
    for marker in marker_matches:
        gap = output[cursor : marker.start()]
        if open_ordinal is None and gap.strip():
            error_codes.append("text_outside_unit_markers")

        raw_ordinal = marker.group("ordinal")
        ordinal = int(raw_ordinal)
        if raw_ordinal != f"{ordinal:04d}":
            error_codes.append(f"noncanonical_unit_marker:{ordinal}")

        is_close = marker.group("close") == "/"
        if not is_close:
            if open_ordinal is not None:
                error_codes.append(f"nested_unit_output:{ordinal}")
            else:
                if ordinal in opened_ordinals:
                    error_codes.append(f"duplicate_unit_output:{ordinal}")
                opened_ordinals.add(ordinal)
                open_ordinal = ordinal
                content_start = marker.end()
        elif open_ordinal is None:
            error_codes.append(f"unexpected_close_unit_output:{ordinal}")
        elif ordinal != open_ordinal:
            error_codes.append(f"mismatched_close_unit_output:{open_ordinal}:{ordinal}")
            error_codes.append(f"unclosed_unit_output:{open_ordinal}")
            open_ordinal = None
        else:
            text = output[content_start : marker.start()].strip()
            if ordinal in parsed:
                error_codes.append(f"duplicate_unit_output:{ordinal}")
            else:
                parsed[ordinal] = text
                seen_ordinals.append(ordinal)
            open_ordinal = None
        cursor = marker.end()

    if open_ordinal is not None:
        error_codes.append(f"unclosed_unit_output:{open_ordinal}")
    if output[cursor:].strip():
        error_codes.append("text_outside_unit_markers")

    # Check for missing, unknown (extra), and reordered units.
    parsed_set = set(parsed.keys())
    for ordinal in sorted(expected_set - parsed_set):
        error_codes.append(f"missing_unit_output:{ordinal}")
    for ordinal in sorted(parsed_set - expected_set):
        error_codes.append(f"extra_unit_output:{ordinal}")
    if (
        len(seen_ordinals) == len(expected_ordinals)
        and set(seen_ordinals) == expected_set
        and seen_ordinals != list(expected_ordinals)
    ):
        error_codes.append("reordered_unit_output")

    if error_codes:
        return {}, list(dict.fromkeys(error_codes))
    return parsed, []


def recover_single_unit_output(
    output: str,
    *,
    expected_ordinal: int,
) -> str:
    """Return body text for two bounded single-unit envelope failures.

    Hy-MT2 occasionally returns either plain translated prose or one correct
    opening marker followed by prose while omitting only the closing marker.
    Recovery is allowed only when there is exactly one expected unit, no
    prose precedes the marker, the marker ordinal is exact, and no other
    current or legacy marker occurs in the body.
    """
    candidate = (output or "").strip()
    if not candidate:
        return ""
    marker_matches = list(_UNIT_CURRENT_MARKER_RE.finditer(candidate))
    if not marker_matches:
        return candidate if not contains_unit_markers(candidate) else ""
    if len(marker_matches) != 1:
        return ""
    marker = marker_matches[0]
    if (
        marker.start() != 0
        or marker.group("close") == "/"
        or int(marker.group("ordinal")) != expected_ordinal
        or marker.group("ordinal") != f"{expected_ordinal:04d}"
    ):
        return ""
    body = candidate[marker.end() :].strip()
    if not body or contains_unit_markers(body):
        return ""
    return body


def reject_misaligned_output(
    units: Sequence[TranslationUnit],
    parsed_map: dict[int, str],
) -> tuple[str, ...]:
    """Return deterministic failure codes for misaligned unit output.

    This is a second-line check after :func:`parse_unit_delimited_output`:
    it inspects the parsed map for empty unit texts and ordinal coverage.
    """
    codes: list[str] = []
    for unit in units:
        text = parsed_map.get(unit.ordinal, "")
        if not text.strip():
            codes.append(f"empty_unit_output:{unit.ordinal}")
    return tuple(dict.fromkeys(codes))


def restore_abbreviation_definition_keys(source_text: str, target_text: str) -> str:
    """Restore source ASCII keys on the left side of abbreviation definitions.

    Hy-MT2 remains the body translator.  This deterministic post-Hy step only
    restores source tokens before ASCII ``=`` signs and leaves every translated
    right-hand side byte-for-byte unchanged.  Ambiguous counts fail closed and
    are handled by the existing fidelity gate.
    """
    source_keys = tuple(
        match.group(1)
        for match in _ABBREVIATION_DEFINITION_KEY_RE.finditer(source_text or "")
    )
    if not source_keys:
        return target_text
    delimiter_pattern = _abbreviation_definition_delimiter_pattern(source_text)
    target_parts = re.split(delimiter_pattern, target_text)
    clause_indexes = [
        index for index in range(0, len(target_parts), 2) if target_parts[index].strip()
    ]
    if len(clause_indexes) != len(source_keys):
        return target_text

    restored_parts = list(target_parts)
    for clause_index, source_key in zip(clause_indexes, source_keys):
        clause = restored_parts[clause_index]
        if clause.count("=") != 1:
            return target_text
        lhs, rhs = clause.split("=", 1)
        leading = lhs[: len(lhs) - len(lhs.lstrip())]
        label_match = re.match(
            r"(?P<label>(?:Abbreviations?|缩略语(?:说明)?)\s*[:：]\s*)",
            lhs.lstrip(),
            re.IGNORECASE,
        )
        label = label_match.group("label") if label_match else ""
        restored_parts[clause_index] = f"{leading}{label}{source_key} ={rhs}"
    return "".join(restored_parts)


def _abbreviation_definition_delimiter_pattern(source_text: str) -> str:
    """Return the separator that actually precedes the next definition key."""
    next_key = (
        r"\s*(?:(?:Abbreviations?|缩略语(?:说明)?)\s*[:：]\s*)?"
        r"[A-Za-z][A-Za-z0-9.-]{0,20}\s*="
    )
    if re.search(rf"[;；]{next_key}", source_text or "", re.IGNORECASE):
        return r"([;；])"
    if re.search(rf"[,，]{next_key}", source_text or "", re.IGNORECASE):
        return r"([,，])"
    return r"([;；])"


def normalize_post_hy_unit_output(source_text: str, target_text: str) -> str:
    """Apply bounded deterministic normalization without another translation model."""
    from .regulatory_translation_glossary import (
        PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS,
        normalize_subject_participant_terminology,
    )

    normalized = restore_abbreviation_definition_keys(source_text, target_text)
    source_keys = tuple(
        match.group(1)
        for match in _ABBREVIATION_DEFINITION_KEY_RE.finditer(source_text or "")
    )
    if source_keys:
        delimiter_pattern = _abbreviation_definition_delimiter_pattern(source_text)
        target_parts = re.split(delimiter_pattern, normalized)
        clause_indexes = [
            index
            for index in range(0, len(target_parts), 2)
            if target_parts[index].strip()
        ]
        if len(clause_indexes) == len(source_keys):
            controlled_parts = list(target_parts)
            for clause_index, source_key in zip(clause_indexes, source_keys):
                preferred = PREFERRED_CLINICAL_ABBREVIATION_TRANSLATIONS.get(source_key)
                clause = controlled_parts[clause_index]
                if not preferred or clause.count("=") != 1:
                    continue
                lhs, rhs = clause.split("=", 1)
                terminal_match = re.search(r"([。.!?；;])\s*$", rhs)
                terminal = terminal_match.group(1) if terminal_match else ""
                controlled_parts[clause_index] = (
                    f"{lhs.rstrip()} = {preferred}{terminal}"
                )
            normalized = "".join(controlled_parts)
    for endpoint_number in set(
        re.findall(r"\bEASI-(50|75|90|100)\b", source_text, re.IGNORECASE)
    ):
        normalized = re.sub(
            rf"湿疹面积(?:和|与)严重程度指数(?:评分)?\s*[-－]\s*"
            rf"{endpoint_number}\s*[（(]\s*EASI-{endpoint_number}\s*[）)]",
            f"EASI-{endpoint_number}",
            normalized,
            flags=re.IGNORECASE,
        )
    if re.search(r"\bCRF\b", source_text) and "CRF" not in normalized:
        normalized = re.sub(
            r"病例报告表(?![（(]\s*CRF)",
            "病例报告表（CRF）",
            normalized,
            count=1,
        )
    return normalize_subject_participant_terminology(source_text, normalized)


def reassemble_aligned_translation(
    units: Sequence[TranslationUnit],
    parsed_map: dict[int, str],
) -> str:
    """Reassemble unit outputs back into a single text, preserving order.

    Unit outputs are joined with a double newline separator so the
    paragraph structure of the source is mirrored in the target.  Markers
    are removed here — the output is plain Chinese.
    """
    parts: list[str] = []
    for unit in units:
        text = parsed_map.get(unit.ordinal, "")
        parts.append(text)
    return "\n\n".join(parts)


def reconstruct_unit_map(
    chunk_translated_text: str,
    stored_unit_targets: Any,
    units: Sequence[TranslationUnit],
) -> dict[int, str]:
    """Rebuild the ordinal -> target map for a reused translation chunk.

    Current-contract chunks must persist exact per-unit targets.  Reconstructing
    those targets heuristically from paragraphs could silently attach content
    to the wrong source unit, so a missing/incomplete map fails closed.
    """
    stored = stored_unit_targets or {}
    if stored:
        try:
            mapping = {int(key): str(value) for key, value in dict(stored).items()}
        except (TypeError, ValueError):
            mapping = {}
        expected = {unit.ordinal for unit in units}
        if (
            mapping
            and set(mapping) == expected
            and all(mapping[ordinal].strip() for ordinal in expected)
        ):
            return mapping
    raise ChapterTranslationPipelineError(
        "current-contract translation chunk has no complete unit_targets map; "
        "the chunk must be retranslated instead of heuristically reconstructed"
    )


# ---------------------------------------------------------------------------
# Structural cardinality checks (V11).
#
# Bullet, numbered-criterion and table row/cell counts are source features:
# a faithful translation preserves them one-to-one.  These checks run per
# aligned unit so one unit's surplus cannot mask another unit's loss.
# ---------------------------------------------------------------------------

_STRUCT_INLINE_BULLET_RE = re.compile(r"[•▪◦❑]")
_STRUCT_LINE_BULLET_RE = re.compile(
    r"^\s*[-–—*](?:\s+|(?=[\u3400-\u9fff]))",
    re.MULTILINE,
)
_STRUCT_NUMBERED_CANDIDATE_RE = re.compile(
    r"(?:"
    r"(?<![\d.A-Za-z\-])(?P<label>\d{1,3}|[A-Z])[.)]\s+"
    r"|"
    r"(?<![\u3400-\u9fff])(?P<zh_label>[一二三四五六七八九十]{1,3})[、.]\s*"
    r")"
    r"(?=[A-Za-z\u3400-\u9fff(（≥])"
)
_STRUCT_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_STRUCT_NON_CRITERION_PREFIX_RE = re.compile(
    r"(?:week|day|visit|section|appendix|panel|table|figure|part|chapter|"
    r"phase|dose|version)\s*$",
    re.IGNORECASE,
)


def _numbered_criterion_count(text: str) -> int:
    """Count numbered criteria without treating temporal references as items."""
    count = 0
    for match in _STRUCT_NUMBERED_CANDIDATE_RE.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 48) : match.start()]
        if _STRUCT_NON_CRITERION_PREFIX_RE.search(prefix):
            continue
        count += 1
    return count


def _structural_signature(text: str) -> dict[str, Any]:
    """Count structural features of a source or target unit text."""
    bullet_count = len(_STRUCT_INLINE_BULLET_RE.findall(text)) + len(
        _STRUCT_LINE_BULLET_RE.findall(text)
    )
    numbered_count = _numbered_criterion_count(text)
    table_rows = _STRUCT_TABLE_ROW_RE.findall(text)
    cell_count = sum(row.count("|") - 1 for row in table_rows)
    return {
        "bullets": bullet_count,
        "numbered": numbered_count,
        "table_rows": len(table_rows),
        "table_cells": cell_count,
    }


def structural_cardinality_failures(
    source_text: str, target_text: str
) -> tuple[str, ...]:
    """Fail when the target drops or adds bullets/numbered items/table parts.

    Only features actually present in the source are checked, so plain prose
    never triggers these codes.
    """
    source_sig = _structural_signature(source_text)
    target_sig = _structural_signature(target_text)
    codes: list[str] = []
    if source_sig["bullets"] and source_sig["bullets"] != target_sig["bullets"]:
        codes.append("bullet_cardinality_changed")
    if source_sig["numbered"] and source_sig["numbered"] != target_sig["numbered"]:
        codes.append("numbered_criterion_cardinality_changed")
    if source_sig["table_rows"]:
        if source_sig["table_rows"] != target_sig["table_rows"]:
            codes.append("table_row_cardinality_changed")
        elif source_sig["table_cells"] != target_sig["table_cells"]:
            codes.append("table_cell_cardinality_changed")
    source_abbreviation_keys = tuple(
        match.group(1)
        for match in _ABBREVIATION_DEFINITION_KEY_RE.finditer(source_text)
    )
    if source_abbreviation_keys:
        target_abbreviation_keys = tuple(
            match.group(1)
            for match in _ABBREVIATION_DEFINITION_KEY_RE.finditer(target_text)
        )
        if source_abbreviation_keys != target_abbreviation_keys:
            codes.append("abbreviation_definition_key_changed")
    return tuple(codes)


# ---------------------------------------------------------------------------
# Bounded corrective retry helpers (V11).
#
# Hy-MT2 gets at most one deterministic corrective retry when unit
# coverage/cardinality or a bounded set of unit-level deterministic fidelity
# findings fail; the retry names the exact failing unit IDs and observed
# codes.  A second failure stops and remains blocked — no unbounded loop.
# Flash integration/QC follows the same one-correction rule.
# ---------------------------------------------------------------------------


def build_correction_note(failure_codes: Sequence[str]) -> str:
    """Render a deterministic correction instruction for one bounded retry.

    The note names the exact failing unit IDs and observed codes so the
    corrective pass can repair precisely the flagged defects.
    """
    lines = [
        "【纠偏指令 CORRECTION】上一轮输出未通过确定性对齐/忠实度校验。"
        "本轮必须重新输出全部单元：每个 [[CMS_SEG_NNNN]] 标记恰好出现一次、"
        "顺序一致、每单元中文非空；仅修复下列缺陷，不得改动其他内容，"
        "不得摘要、合并、重排或将类别术语窄化为单一产品。",
        "失败单元与代码：",
    ]
    lines.extend(f"- {code}" for code in failure_codes)
    if any("range_inclusivity_changed" in code for code in failure_codes):
        lines.append(
            "范围边界专门要求：原文含“both included / inclusive / including”时，"
            "译文必须明确保留下限和上限均包含，例如“18至75周岁（含两端值）”；"
            "不得写成“75周岁以下”等排除上限的表达。"
        )
    if any("numeric_tokens_changed" in code for code in failure_codes):
        lines.append(
            "数字专门要求：逐单元逐一保留原文所有阿拉伯数字、百分号、比较符号和"
            "时间点，不得把“4”改写成“四”，不得新增相邻单元中的周数或阈值。"
            "EASI-50/75/90/100 等带数字终点名若保留原缩写，不得再用另一处"
            "相同数字重复展开，确保每个源数字在译文中只出现对应次数。"
            "同一量表在不同访视有不同阈值时必须逐时点明确保留，例如"
            "“EASI score ≥12 at screening and ≥16 at baseline”须译为"
            "“筛选时EASI评分≥12分且基线时≥16分”，不得把基线阈值省略成"
            "“也需满足该分值”或合并为一个阈值。"
        )
    if any("unit_sequence_changed" in code for code in failure_codes):
        lines.append(
            "单位/时间点专门要求：保持每个数字与其原单位、Week/Day/小时及起止"
            "范围的对应关系，不得跨条目移动、合并或补写时间点。"
            "“change from baseline to Week X”应译为“从基线至第X周的变化”"
            "或“第X周较基线的变化”，不得写成“第X周期间的变化”。"
        )
    if any("bullet_cardinality_changed" in code for code in failure_codes):
        lines.append(
            "项目符号专门要求：逐单元保留原文每一个“•”及其先后位置；表格内的"
            "项目符号必须留在对应单元格中，不得改成冒号、顿号或直接删除。"
        )
    if any(
        code_name in code
        for code in failure_codes
        for code_name in (
            "table_row_cardinality_changed",
            "table_cell_cardinality_changed",
        )
    ):
        lines.append(
            "表格结构专门要求：逐字保留原文全部竖线“|”及其先后顺序；每个"
            "表格行、单元格边界和单元格内项目符号“•”数量必须与原文一致。"
            "只能翻译单元格文字，不得把表格改写成普通段落或列表。"
        )
    if any("source_abbreviation_missing" in code for code in failure_codes):
        lines.append(
            "缩略语专门要求：原文出现的临床缩略语必须在同一单元保留；首次翻译"
            "全称时使用“规范中文（原缩略语）”，后续可直接保留缩略语。"
        )
    if any("controlled_term_missing:" in code for code in failure_codes):
        lines.append(
            "受控术语专门要求：逐项查阅本请求附带的术语表，缺失代码冒号后的"
            "术语必须在对应单元采用 preferred_zh 或 accepted_chinese 完整译出；"
            "不得仅保留英文、缩略语，或改成范围更宽的泛称。"
        )
    if any("controlled_term_missing:participant" in code for code in failure_codes):
        lines.append(
            "受试者主语专门要求：源文每个 Subjects/Subject 子句均须明确"
            "保留“受试者”主语，不得省略成只有“者、其、该类人群”的表达。"
        )
    if any("untranslated_source_connector" in code for code in failure_codes):
        lines.append(
            "未译英文专门要求：除源文临床缩略语、药物代码和专有名词外，"
            "等号右侧定义及正文中的 and/or/whether/whereas/unless/except、"
            "e.g./i.e. 等连接成分必须完整译为中文，不得原样残留。"
        )
    if any("abbreviation_definition_key_changed" in code for code in failure_codes):
        lines.append(
            "缩略语定义专门要求：每个等号左侧必须逐字保留原文ASCII缩写及顺序，"
            "每条定义必须直接保留ASCII等号字符“=”，不得改成“表示、即、为、是、"
            "则是”等连接词；只翻译等号右侧术语。不得把缩写左侧替换成中文。"
            "百分比降低定义必须"
            "保留原百分比，不得换算成推定的终点评分。"
        )
    if any("regulatory_chinese_term_calque" in code for code in failure_codes):
        lines.append(
            "监管术语专门要求：严格采用随请求提供的受控中英术语表，不得逐词"
            "直译或自行创造量表、终点、估计目标及药物类别名称。临床试验方案"
            "中的 subjects/participants 必须译为“受试者”；只有原文明确使用"
            " patient/patients 时才可译为“患者”。同一单元内不得混用。"
        )
    if any("important_side_effect_severity_upcoded" in code for code in failure_codes):
        lines.append(
            "安全性修饰语专门要求：原文 important 不能升级为 severe；"
            "“important side effects or safety risks”应保留为“重要的副作用"
            "或安全性风险”等值含义，不得改成“严重不良反应”。"
        )
    if any(
        "bilateral_tubal_occlusion_narrowed_to_ligation" in code
        for code in failure_codes
    ):
        lines.append(
            "避孕术语专门要求：bilateral tubal occlusion 是双侧输卵管"
            "阻塞/闭塞这一类别，不得缩窄为其中一种术式“输卵管结扎”。"
        )
    if any("ius_category_narrowed" in code for code in failure_codes):
        lines.append(
            "避孕器具专门要求：源文只写 IUS 时须译为通用类别“宫内节育"
            "系统（IUS）”，不得无依据添加“左炔诺孕酮”等特定成分。"
        )
    if any("same_sex_partner_omitted" in code for code in failure_codes):
        lines.append(
            "避孕条件专门要求：源文列出的 same-sex partner 必须在同一"
            "单元明确保留为“同性伴侣”，不得省略或并入其他避孕方式。"
        )
    if any("abstinence_partner_condition_inverted" in code for code in failure_codes):
        lines.append(
            "禁欲条件专门要求：not just being without a current partner "
            "必须译为“并非仅因当前无伴侣”；不得反向写成“且当前无伴侣”。"
        )
    if any("unsupported_medical_concept_added" in code for code in failure_codes):
        lines.append(
            "无来源医学概念专门要求：不得把 evaluation/assessment of the "
            "IMP 擅自缩窄成“疗效评估”；源文未写 efficacy 时应译为“对试验"
            "药物的评估”或同义中性表达，不得新增疗效、安全性或因果判断。"
        )
    if any("unsupported_scale_identity_added:" in code for code in failure_codes):
        lines.append(
            "量表身份专门要求：逐个失败单元核对冒号后的量表缩写。原文只出现"
            "IGA时只能保留IGA，不得新增或替换为EASI；原文只出现EASI时不得"
            "新增IGA；原文出现vIGA-AD时须保留vIGA-AD及其特应性皮炎限定。"
            "不得依据相邻单元、医学常识或量表定义补入另一量表，也不得建立"
            "EASI与IGA/vIGA-AD之间的等价、相当、换算或替代关系。"
        )
    return "\n".join(lines)


def format_flash_integration_envelope(
    units: Sequence[TranslationUnit],
    target_map: dict[int, str],
) -> str:
    """Build the aligned marked source/target envelope for Flash QC.

    Each unit carries its marked source text and the current marked Hy-MT2
    draft so Flash can integrate/QC one aligned pair at a time.  Flash must
    return the same markers exactly once each, in order, around the final
    Chinese for each unit.
    """
    blocks: list[str] = []
    for unit in units:
        blocks.append(
            f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
            f"SOURCE:\n{unit.text}\n"
            f"DRAFT_ZH:\n{target_map.get(unit.ordinal, '')}\n"
            f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
        )
    return "\n\n".join(blocks)


def extract_draft_map_from_envelope(envelope: str) -> dict[int, str]:
    """Extract ordinal -> DRAFT_ZH text from a Flash integration envelope.

    Used by deterministic fakes and tests to simulate a Flash integration
    that preserves markers; never used in the production acceptance path.
    """
    drafts: dict[int, str] = {}
    for match in _UNIT_TARGET_OPEN_RE.finditer(envelope):
        raw_ordinal = match.group(1)
        ordinal = int(raw_ordinal)
        close = re.search(
            rf"\[\[/CMS_SEG_{re.escape(raw_ordinal)}\]\]", envelope[match.end() :]
        )
        if close is None:
            continue
        block = envelope[match.end() : match.end() + close.start()]
        draft_split = block.split("DRAFT_ZH:", 1)
        drafts[ordinal] = draft_split[1].strip() if len(draft_split) == 2 else ""
    return drafts


def call_hy_mt2_translator(
    translator: Callable[..., HyMt2TranslationResult],
    *,
    source_text: str,
    glossary: str,
    chapter_id: str,
    chunk_id: str,
    read_only_context: str = "",
    correction_note: str = "",
) -> HyMt2TranslationResult:
    """Invoke a Hy-MT2 translator with structured source vs read-only context.

    Selects the newest compatible signature before invocation.  It does not
    catch a ``TypeError`` raised inside the provider callable, because doing
    so could duplicate a real provider request under a legacy arity.
    """
    argument_sets = (
        (
            source_text,
            glossary,
            chapter_id,
            chunk_id,
            read_only_context,
            correction_note,
        ),
        (source_text, glossary, chapter_id, chunk_id, read_only_context),
        (source_text, glossary, chapter_id, chunk_id),
    )
    try:
        signature = inspect.signature(translator)
    except (TypeError, ValueError):
        signature = None
    if signature is None:
        return translator(*argument_sets[0])
    for arguments in argument_sets:
        try:
            signature.bind(*arguments)
        except TypeError:
            continue
        return translator(*arguments)
    raise TypeError(
        "Hy-MT2 translator does not support the required callable signature"
    )


def call_flash_qc_with_note(
    flash_qc_runner: Callable[..., FlashQcResult],
    translated: str,
    source: str,
    *,
    correction_note: str = "",
) -> FlashQcResult:
    """Invoke Flash integration QC, optionally with a correction note.

    Selects the compatible signature before invocation.  A ``TypeError``
    raised inside the provider callable propagates and is never retried as a
    lower-arity call.
    """
    argument_sets = (
        (translated, source, correction_note),
        (translated, source),
    )
    if not correction_note:
        argument_sets = ((translated, source),)
    try:
        signature = inspect.signature(flash_qc_runner)
    except (TypeError, ValueError):
        signature = None
    if signature is None:
        return flash_qc_runner(*argument_sets[0])
    for arguments in argument_sets:
        try:
            signature.bind(*arguments)
        except TypeError:
            continue
        return flash_qc_runner(*arguments)
    raise TypeError("Flash QC runner does not support the required callable signature")


def _translate_complex_table_row_fragments(
    translator: Callable[..., HyMt2TranslationResult],
    *,
    unit: TranslationUnit,
    glossary: str,
    chapter_id: str,
    chunk_id: str,
    read_only_context: str,
) -> tuple[HyMt2TranslationResult, dict[int, str]] | None:
    """Translate a dense markdown table row as Hy-only semantic fragments.

    Long PDF-recovered table rows can contain dozens of inline bullets.  When
    two whole-row attempts fail structural fidelity, split only the cell
    prose and bullet bodies for Hy-MT2, then restore the source table
    delimiters and bullet markers deterministically.  Structural characters
    are not authored by another model.
    """
    source_row = unit.text.strip()
    if not _looks_like_table_row(source_row):
        return None
    raw_cells = source_row[1:-1].split("|")
    fragment_units: list[TranslationUnit] = []
    fragment_specs: list[tuple[int, str, int]] = []
    next_ordinal = 1
    for cell_index, raw_cell in enumerate(raw_cells):
        parts = re.split(r"([•▪◦])", raw_cell)
        leading_text = parts[0].strip()
        if leading_text:
            fragment_units.append(
                TranslationUnit(ordinal=next_ordinal, text=leading_text)
            )
            fragment_specs.append((cell_index, "", next_ordinal))
            next_ordinal += 1
        for offset in range(1, len(parts), 2):
            marker = parts[offset]
            content = parts[offset + 1].strip() if offset + 1 < len(parts) else ""
            if not content:
                continue
            fragment_units.append(TranslationUnit(ordinal=next_ordinal, text=content))
            fragment_specs.append((cell_index, marker, next_ordinal))
            next_ordinal += 1
    if len(fragment_units) <= 1:
        return None

    child_result, fragment_map = translate_units_with_bounded_correction(
        translator,
        units=tuple(fragment_units),
        glossary=glossary,
        chapter_id=chapter_id,
        chunk_id=f"{chunk_id}:table_fragments",
        read_only_context=read_only_context,
    )
    translated_cells: list[list[str]] = [[] for _ in raw_cells]
    for cell_index, marker, ordinal in fragment_specs:
        translated = fragment_map[ordinal].strip()
        translated_cells[cell_index].append(
            f"{marker} {translated}".strip() if marker else translated
        )
    rebuilt_row = (
        "| " + " | ".join(" ".join(parts).strip() for parts in translated_cells) + " |"
    )
    source_signature = _structural_signature(source_row)
    target_signature = _structural_signature(rebuilt_row)
    if source_signature != target_signature:
        raise FidelityBlockedError(
            ("deterministic_table_reassembly_mismatch",),
            last_output=rebuilt_row,
        )
    marked_output = (
        f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
        f"{rebuilt_row}\n"
        f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
    )
    output_hash = _sha256(marked_output)
    aggregate_input_hash = _sha256(
        json.dumps(
            {
                "source_row_sha256": _sha256(source_row),
                "fragment_input_hash": child_result.input_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return (
        HyMt2TranslationResult(
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            translated_text=marked_output,
            translated_text_sha256=output_hash,
            model=HY_MT2_MODEL_ID,
            prompt_version=HY_MT2_PROMPT_VERSION,
            input_hash=aggregate_input_hash,
            output_hash=output_hash,
            translation_strategy="hy_mt2_table_fragment_fallback",
        ),
        {unit.ordinal: rebuilt_row},
    )


def translate_units_with_bounded_correction(
    translator: Callable[..., HyMt2TranslationResult],
    *,
    units: Sequence[TranslationUnit],
    glossary: str,
    chapter_id: str,
    chunk_id: str,
    read_only_context: str = "",
) -> tuple[HyMt2TranslationResult, dict[int, str]]:
    """Translate marked units with bounded group and failed-unit correction.

    First pass: exact unit coverage/cardinality/order plus per-unit
    deterministic fidelity.  On failure, one corrective retry naming the
    exact failing unit IDs and observed codes.  If that retry still has only
    unit-scoped fidelity failures, each failed unit receives the same bounded
    Hy-MT2-only treatment in isolation before deterministic reassembly.  A
    failed isolated unit raises :class:`FidelityBlockedError`; DeepSeek never
    repairs or authors protocol-body text in this path.
    """
    if len(units) > HY_MT2_MAX_UNITS_PER_CALL:
        child_results: list[HyMt2TranslationResult] = []
        combined_map: dict[int, str] = {}
        for start in range(0, len(units), HY_MT2_MAX_UNITS_PER_CALL):
            batch = tuple(units[start : start + HY_MT2_MAX_UNITS_PER_CALL])
            child_result, child_map = translate_units_with_bounded_correction(
                translator,
                units=batch,
                glossary=glossary,
                chapter_id=chapter_id,
                chunk_id=(
                    f"{chunk_id}:unit_batch_{start // HY_MT2_MAX_UNITS_PER_CALL + 1}"
                ),
                read_only_context=read_only_context,
            )
            child_results.append(child_result)
            combined_map.update(child_map)
        combined_output = "\n\n".join(
            f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
            f"{combined_map[unit.ordinal]}\n"
            f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
            for unit in units
        )
        combined_hash = _sha256(combined_output)
        aggregate_input_hash = _sha256(
            json.dumps(
                [result.input_hash for result in child_results],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return (
            HyMt2TranslationResult(
                chapter_id=chapter_id,
                chunk_id=chunk_id,
                translated_text=combined_output,
                translated_text_sha256=combined_hash,
                model=HY_MT2_MODEL_ID,
                prompt_version=HY_MT2_PROMPT_VERSION,
                input_hash=aggregate_input_hash,
                output_hash=combined_hash,
                translation_strategy=(
                    "hy_mt2_bounded_unit_batches_with_table_fragment_fallback"
                    if any(
                        result.translation_strategy == "hy_mt2_table_fragment_fallback"
                        for result in child_results
                    )
                    else "hy_mt2_bounded_unit_batches"
                ),
            ),
            combined_map,
        )

    unit_ordinals = [u.ordinal for u in units]
    unit_delimited_source = format_unit_delimited_source(units)
    last_codes: list[str] = []
    last_aligned_map: dict[int, str] | None = None
    last_aligned_codes: tuple[str, ...] = ()
    result: HyMt2TranslationResult | None = None
    for attempt in (1, 2):
        note = build_correction_note(last_codes) if attempt == 2 else ""
        result = call_hy_mt2_translator(
            translator,
            source_text=unit_delimited_source,
            glossary=glossary,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            read_only_context=read_only_context,
            correction_note=note,
        )
        if result.model != HY_MT2_MODEL_ID:
            raise ChapterTranslationPipelineError(
                f"body translator model '{result.model}' does not match "
                f"required Hy-MT2 model '{HY_MT2_MODEL_ID}'"
            )
        parsed_map, unit_errors = parse_unit_delimited_output(
            result.translated_text,
            expected_ordinals=unit_ordinals,
        )
        codes: list[str] = list(unit_errors)
        if not codes:
            codes.extend(reject_misaligned_output(units, parsed_map))
        if not codes:
            parsed_map = {
                unit.ordinal: normalize_post_hy_unit_output(
                    unit.text,
                    parsed_map[unit.ordinal],
                )
                for unit in units
            }
            last_aligned_map = parsed_map
            last_aligned_codes = evaluate_translation_fidelity_aligned_units(
                units,
                parsed_map,
            )
            codes.extend(last_aligned_codes)
        if not codes:
            return result, parsed_map
        last_codes = codes
    recovered_single_text = (
        recover_single_unit_output(
            result.translated_text,
            expected_ordinal=units[0].ordinal,
        )
        if len(units) == 1 and result is not None
        else ""
    )
    if recovered_single_text:
        recovered_map = {
            units[0].ordinal: normalize_post_hy_unit_output(
                units[0].text,
                recovered_single_text,
            )
        }
        recovery_codes = list(reject_misaligned_output(units, recovered_map))
        if not recovery_codes:
            recovery_codes.extend(
                evaluate_translation_fidelity_aligned_units(units, recovered_map)
            )
        if not recovery_codes:
            return (
                HyMt2TranslationResult(
                    chapter_id=result.chapter_id,
                    chunk_id=result.chunk_id,
                    translated_text=result.translated_text,
                    translated_text_sha256=result.translated_text_sha256,
                    model=result.model,
                    prompt_version=HY_MT2_PROMPT_VERSION,
                    input_hash=result.input_hash,
                    output_hash=result.output_hash,
                    translation_strategy="hy_mt2_single_unit_envelope_recovery",
                ),
                recovered_map,
            )
        last_codes = recovery_codes
    if len(units) == 1 and any(
        code_name in code
        for code in last_codes
        for code_name in (
            "bullet_cardinality_changed",
            "table_row_cardinality_changed",
            "table_cell_cardinality_changed",
        )
    ):
        table_fallback = _translate_complex_table_row_fragments(
            translator,
            unit=units[0],
            glossary=glossary,
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            read_only_context=read_only_context,
        )
        if table_fallback is not None:
            return table_fallback
    failed_ordinals: list[int] = []
    isolation_codes = tuple(last_codes)
    if (
        len(units) > 1
        and last_aligned_map is not None
        and last_aligned_codes
        and not all(re.match(r"^unit_(\d+):", code) for code in isolation_codes)
    ):
        # The corrective group output may itself break the marker contract.
        # Discard it and retain the most recent structurally aligned Hy result
        # only long enough to isolate the unit-scoped fidelity defects already
        # proven there. Passing units are never copied from the malformed pass.
        isolation_codes = last_aligned_codes
    if len(units) > 1 and last_aligned_map is not None and isolation_codes:
        for code in isolation_codes:
            match = re.match(r"^unit_(\d+):", code)
            if match is None:
                failed_ordinals = []
                break
            ordinal = int(match.group(1))
            if ordinal not in failed_ordinals:
                failed_ordinals.append(ordinal)
    if failed_ordinals:
        unit_by_ordinal = {unit.ordinal: unit for unit in units}
        if all(ordinal in unit_by_ordinal for ordinal in failed_ordinals):
            isolated_map = dict(last_aligned_map)
            child_results: list[HyMt2TranslationResult] = []
            for ordinal in failed_ordinals:
                child_result, child_map = translate_units_with_bounded_correction(
                    translator,
                    units=(unit_by_ordinal[ordinal],),
                    glossary=glossary,
                    chapter_id=chapter_id,
                    chunk_id=f"{chunk_id}:failed_unit_{ordinal}",
                    read_only_context=read_only_context,
                )
                child_results.append(child_result)
                isolated_map[ordinal] = child_map[ordinal]
            reassembled_codes = list(reject_misaligned_output(units, isolated_map))
            if not reassembled_codes:
                reassembled_codes.extend(
                    evaluate_translation_fidelity_aligned_units(units, isolated_map)
                )
            if not reassembled_codes:
                reassembled_output = "\n\n".join(
                    f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
                    f"{isolated_map[unit.ordinal]}\n"
                    f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
                    for unit in units
                )
                reassembled_hash = _sha256(reassembled_output)
                aggregate_input_hash = _sha256(
                    json.dumps(
                        {
                            "group_input_hash": result.input_hash if result else "",
                            "isolated_input_hashes": [
                                child.input_hash for child in child_results
                            ],
                            "failed_ordinals": failed_ordinals,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                return (
                    HyMt2TranslationResult(
                        chapter_id=chapter_id,
                        chunk_id=chunk_id,
                        translated_text=reassembled_output,
                        translated_text_sha256=reassembled_hash,
                        model=HY_MT2_MODEL_ID,
                        prompt_version=HY_MT2_PROMPT_VERSION,
                        input_hash=aggregate_input_hash,
                        output_hash=reassembled_hash,
                        translation_strategy="hy_mt2_failed_unit_isolation_fallback",
                    ),
                    isolated_map,
                )
            last_codes = reassembled_codes
    raw_provider_output = result.translated_text if result is not None else ""
    normalized_diagnostic_output = raw_provider_output
    if result is not None:
        parsed_diagnostic, diagnostic_errors = parse_unit_delimited_output(
            raw_provider_output,
            expected_ordinals=unit_ordinals,
        )
        if not diagnostic_errors and set(parsed_diagnostic) == set(unit_ordinals):
            normalized_map = {
                unit.ordinal: normalize_post_hy_unit_output(
                    unit.text,
                    parsed_diagnostic[unit.ordinal],
                )
                for unit in units
            }
            normalized_diagnostic_output = "\n\n".join(
                f"{_UNIT_SOURCE_OPEN.format(unit.ordinal)}\n"
                f"{normalized_map[unit.ordinal]}\n"
                f"{_UNIT_SOURCE_CLOSE.format(unit.ordinal)}"
                for unit in units
            )
    raise FidelityBlockedError(
        tuple(dict.fromkeys(last_codes)),
        last_output=normalized_diagnostic_output,
        raw_provider_output=raw_provider_output,
    )


@dataclass(frozen=True)
class FlashIntegrationOutcome:
    """Result of the aligned Flash integration/QC stage."""

    passed: bool
    final_text: str
    failure_codes: tuple[str, ...]
    qc_result: FlashQcResult | None
    attempts: int
    fallback_used: bool = False
    diagnostic_codes: tuple[str, ...] = ()


def integrate_units_with_flash(
    flash_qc_runner: Callable[..., FlashQcResult],
    *,
    units: Sequence[TranslationUnit],
    target_map: dict[int, str],
) -> FlashIntegrationOutcome:
    """Run upper-layer Flash QC without allowing Flash to author body text.

    Flash receives aligned source/Hy-MT2 pairs and returns QC findings plus an
    exact marked echo. Any body mutation is rejected. The final text is always
    reconstructed from ``target_map``.
    """
    envelope = format_flash_integration_envelope(units, target_map)
    marked_source = format_unit_delimited_source(units)
    unit_ordinals = [u.ordinal for u in units]
    last_codes: list[str] = []
    qc: FlashQcResult | None = None
    first_output = ""
    for attempt in (1, 2):
        note = ""
        if attempt == 2:
            note = build_correction_note(last_codes) + (
                f"\n\n【上一轮输出 FIRST_OUTPUT】\n{first_output}"
            )
        qc = call_flash_qc_with_note(
            flash_qc_runner, envelope, marked_source, correction_note=note
        )
        if not qc.passed:
            hy_codes: list[str] = list(reject_misaligned_output(units, target_map))
            if not hy_codes:
                hy_codes.extend(
                    evaluate_translation_fidelity_aligned_units(
                        units,
                        target_map,
                    )
                )
            diagnostic_codes = tuple(
                dict.fromkeys(
                    [
                        "flash_qc_advisory_requires_medical_review",
                        *(
                            f"flash_qc_advisory:{code}"
                            for code in (
                                tuple(qc.failure_codes) or ("unspecified_qc_concern",)
                            )
                        ),
                    ]
                )
            )
            if not hy_codes:
                hy_text = reassemble_aligned_translation(units, target_map)
                if not contains_unit_markers(hy_text):
                    return FlashIntegrationOutcome(
                        passed=True,
                        final_text=hy_text,
                        failure_codes=(),
                        qc_result=qc,
                        attempts=attempt,
                        fallback_used=True,
                        diagnostic_codes=diagnostic_codes,
                    )
            return FlashIntegrationOutcome(
                passed=False,
                final_text="",
                failure_codes=tuple(dict.fromkeys(hy_codes)),
                qc_result=qc,
                attempts=attempt,
                diagnostic_codes=diagnostic_codes,
            )
        integrated = qc.integrated_text or ""
        if not integrated.strip():
            # A passed QC with an empty integrated candidate is malformed
            # output — fail closed, never silently substitute the draft.
            raise ChapterTranslationPipelineError(
                "Flash QC passed but returned empty integrated_text; "
                "the integration stage must produce a complete candidate"
            )
        first_output = integrated
        parsed_map, unit_errors = parse_unit_delimited_output(
            integrated, expected_ordinals=unit_ordinals
        )
        codes: list[str] = list(unit_errors)
        if not codes:
            codes.extend(reject_misaligned_output(units, parsed_map))
        if not codes:
            for unit in units:
                if parsed_map.get(unit.ordinal) != target_map.get(unit.ordinal):
                    codes.append(
                        f"unit_{unit.ordinal}:flash_qc_body_mutation_forbidden"
                    )
        if not codes:
            final_text = reassemble_aligned_translation(units, target_map)
            if contains_unit_markers(final_text):
                last_codes = ["unit_marker_leak_in_integrated_text"]
                continue
            return FlashIntegrationOutcome(
                passed=True,
                final_text=final_text,
                failure_codes=(),
                qc_result=qc,
                attempts=attempt,
            )
        last_codes = codes

    # A mutated Flash audit echo must never replace a faithful Hy-MT2 body.
    hy_codes: list[str] = list(reject_misaligned_output(units, target_map))
    if not hy_codes:
        hy_codes.extend(evaluate_translation_fidelity_aligned_units(units, target_map))
    if not hy_codes:
        hy_text = reassemble_aligned_translation(units, target_map)
        if not contains_unit_markers(hy_text):
            return FlashIntegrationOutcome(
                passed=True,
                final_text=hy_text,
                failure_codes=(),
                qc_result=qc,
                attempts=2,
                fallback_used=True,
                diagnostic_codes=tuple(
                    dict.fromkeys(
                        ["flash_integration_drift_fallback_to_hy", *last_codes]
                    )
                ),
            )
    return FlashIntegrationOutcome(
        passed=False,
        final_text="",
        failure_codes=tuple(dict.fromkeys([*last_codes, *hy_codes])),
        qc_result=qc,
        attempts=2,
    )


def validate_completion_payload(payload: Any, provider_label: str) -> str:
    """Validate an OpenAI-style chat completion payload; return its content.

    Fails closed unless the provider reports ``finish_reason == "stop"``, and
    also rejects empty/missing content or a malformed envelope.  A partial or
    interrupted translation can never be alignment-checked honestly.
    """
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices or not isinstance(choices, list):
        raise ChapterTranslationPipelineError(
            f"{provider_label} returned no choices; output is malformed"
        )
    first = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = first.get("finish_reason")
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if finish_reason != "stop":
        raise ChapterTranslationPipelineError(
            f"{provider_label} output did not complete normally "
            f"(finish_reason={finish_reason!r}); fails closed rather than "
            "admitting a partial translation"
        )
    if not isinstance(content, str) or not content.strip():
        raise ChapterTranslationPipelineError(
            f"{provider_label} returned empty content; output is malformed"
        )
    return content


def build_integration_windows(
    chunk_pairs: Sequence[tuple[Any, str]],
    *,
    input_limit: int = INTEGRATION_PROVIDER_INPUT_LIMIT,
) -> tuple[tuple[tuple[Any, str], ...], ...]:
    """Pack ordered (ChunkSpec, translated_text) pairs into integration windows.

    Returns a tuple of windows.  A single window means ordinary (non-windowed)
    integration.  Multiple windows are only produced when the cumulative
    source+translated character count exceeds ``input_limit``.
    """
    if not chunk_pairs:
        return ()
    total_chars = sum(
        len(getattr(cs, "source_text", "") or "") + len(translated or "")
        for cs, translated in chunk_pairs
    )
    if total_chars <= input_limit:
        return (tuple(chunk_pairs),)

    windows: list[list[tuple[Any, str]]] = []
    current: list[tuple[Any, str]] = []
    current_len = 0
    for pair in chunk_pairs:
        cs, translated = pair
        pair_len = len(getattr(cs, "source_text", "") or "") + len(translated or "")
        if current and current_len + pair_len > input_limit:
            windows.append(current)
            current = [pair]
            current_len = pair_len
        else:
            current.append(pair)
            current_len += pair_len
    if current:
        windows.append(current)
    return tuple(tuple(w) for w in windows)


@dataclass(frozen=True)
class ChunkSpec:
    """Specification for a single translation chunk within a chapter.

    Built deterministically from a :class:`DocumentStructurePlan` and the
    current ordered source spans.  Each chunk carries its source-span IDs,
    concatenated source text, optional adjacent read-only context (prompt
    context only — never duplicated in translated output), table-header
    prefix when a table spans chunks, and a deterministic fingerprint.
    """

    chunk_id: str
    chapter_id: str
    chunk_order: int
    source_span_ids: tuple[str, ...]
    source_text: str
    source_text_sha256: str
    adjacent_context: str
    adjacent_context_sha256: str
    table_header_prefix: str
    chunk_fingerprint: str


@dataclass(frozen=True)
class DocumentPlanRequest:
    """Input for a Flash document structure plan."""

    artifact_id: str
    extraction_revision: str
    document_sha256: str
    source_spans: tuple[Any, ...]  # WritingReferenceExtractedSpan


@dataclass(frozen=True)
class DocumentPlannerSegment:
    """A compact contiguous structural segment used by the Flash planner.

    ``source_span_ids`` remain process-local.  They are never sent to the
    model; deterministic code expands the model's segment ranges back to the
    immutable source-span membership after the model returns.
    """

    ordinal: int
    heading: str
    ich_m11_anchor: str
    page_start: int
    page_end: int
    span_count: int
    text_sample: str
    source_span_ids: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "heading": self.heading,
            "ich_m11_anchor": self.ich_m11_anchor,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "span_count": self.span_count,
            "text_sample": self.text_sample,
        }


def _compact_planner_text(
    value: Any, *, limit: int = PLANNER_SEGMENT_SAMPLE_CHARS
) -> str:
    compact = " ".join(str(value or "").split())
    return compact[:limit]


_PLANNER_NUMBERED_HEADING = re.compile(
    r"^(?:(?:section|chapter)\s+)?"
    r"(?:\d+(?:\.\d+){0,5}|[A-Z](?:\.\d+){0,3})[.)]?\s+[A-Za-z]",
    re.IGNORECASE,
)
_PLANNER_APPENDIX_HEADING = re.compile(
    r"^(?:appendix|annex|part)\s+[A-Z0-9]+(?:[.:\s-]|$)",
    re.IGNORECASE,
)
_PLANNER_TOP_LEVEL_NUMBERED_HEADING = re.compile(
    r"^(?P<number>[1-9]\d?)\s+(?P<title>[A-Z][^\n]{1,180})$"
)
_PLANNER_UNNUMBERED_HEADINGS = (
    "cover page",
    "title page",
    "protocol amendment summary",
    "document history",
    "table of contents",
    "list of panels",
    "list of tables",
    "list of figures",
    "list of abbreviations",
    "protocol summary",
    "protocol synopsis",
    "study design",
    "trial design",
    "objectives and endpoints",
    "endpoints",
    "trial objectives",
    "study objectives",
    "eligibility criteria",
    "inclusion criteria",
    "exclusion criteria",
    "schedule of activities",
    "schedule of assessments",
    "statistical methods",
    "statistical analysis plan",
    "references",
)


def _is_trusted_planner_heading(value: str) -> bool:
    heading = _compact_planner_text(value, limit=260)
    if not heading or len(heading) > 220:
        return False
    folded = heading.casefold()
    if any(
        folded == item or folded.startswith(f"{item}:")
        for item in _PLANNER_UNNUMBERED_HEADINGS
    ):
        return True
    return bool(
        _PLANNER_NUMBERED_HEADING.match(heading)
        or _PLANNER_APPENDIX_HEADING.match(heading)
    )


def required_top_level_segment_boundaries(
    segments: Sequence[DocumentPlannerSegment],
) -> tuple[int, ...]:
    """Return a high-confidence consecutive ``1..N`` chapter boundary set.

    Model planning may group front matter and unnumbered sections, but it must
    not merge across an obvious top-level protocol sequence.  TOC rows,
    numbered criteria and references can also look like headings, so the
    shortest clean title is selected for each number and a substantial
    consecutive run is required before this guard becomes active.
    """
    candidates: dict[int, list[tuple[int, str]]] = {}
    for segment in segments:
        heading = _compact_planner_text(segment.heading, limit=220)
        if "..." in heading:
            continue
        match = _PLANNER_TOP_LEVEL_NUMBERED_HEADING.match(heading)
        if not match:
            continue
        number = int(match.group("number"))
        title = match.group("title").strip()
        candidates.setdefault(number, []).append((segment.ordinal, title))

    if 1 not in candidates:
        return ()
    max_consecutive = 0
    while max_consecutive + 1 in candidates:
        max_consecutive += 1
    if max_consecutive < 4:
        return ()

    paths: list[tuple[tuple[int, str], ...]] = [()]
    for number in range(1, max_consecutive + 1):
        extended = [
            path + ((ordinal, title),)
            for path in paths
            for ordinal, title in candidates[number]
            if not path or ordinal > path[-1][0]
        ]
        if not extended:
            return ()
        paths = extended
    selected = min(
        paths,
        key=lambda path: (
            sum(len(title) for _, title in path),
            sum(title.count(".") for _, title in path),
            tuple(ordinal for ordinal, _ in path),
        ),
    )
    return tuple(ordinal for ordinal, _ in selected)


def build_document_planner_segments(
    source_spans: Sequence[Any],
) -> tuple[DocumentPlannerSegment, ...]:
    """Group ordered source spans into compact contiguous structural segments.

    A non-blank heading starts a new segment when the heading or mapped M11
    anchor changes.  Blank spans remain with the preceding heading; leading
    blank spans become an explicit front-matter segment.  An anchor change
    without a heading also starts a segment so synthetic/test extractions and
    OCR-recovered documents retain their known structure.
    """
    if not source_spans:
        raise DocumentPlanValidationError(("document_has_no_source_spans",))

    raw_headings = [
        _compact_planner_text(getattr(span, "section_heading", ""), limit=240)
        for span in source_spans
    ]
    has_trusted_headings = any(
        _is_trusted_planner_heading(heading) for heading in raw_headings
    )

    groups: list[dict[str, Any]] = []
    for span in source_spans:
        raw_heading = _compact_planner_text(
            getattr(span, "section_heading", ""), limit=240
        )
        heading = (
            raw_heading
            if has_trusted_headings and _is_trusted_planner_heading(raw_heading)
            else ""
        )
        anchor = (
            str(getattr(span, "ich_m11_anchor", "") or "unmapped").strip() or "unmapped"
        )
        page = int(getattr(span, "physical_page", 1))
        span_id = str(getattr(span, "span_id", "") or "").strip()
        if not span_id:
            raise DocumentPlanValidationError(("source_span_missing_id",))

        start_new = not groups
        if groups:
            current = groups[-1]
            current_heading = str(current["heading"])
            current_anchor = str(current["fallback_anchor"])
            if (
                has_trusted_headings
                and heading
                and (heading.casefold() != current_heading.casefold())
            ):
                start_new = True
            elif anchor != current_anchor and (
                anchor != "unmapped" or current_anchor != "unmapped"
            ):
                # Trusted headings can be repeated across a PDF extraction
                # block while the extractor has already recovered finer M11
                # anchors. Keep those spans separate so a deterministic
                # anchor-grouped plan cannot collapse eligibility, safety,
                # schedule, or endpoint content into one chapter. Splitting
                # mapped/unmapped transitions also prevents an unlabeled span
                # from silently inheriting the preceding mapped chapter.
                start_new = True

        if start_new:
            groups.append(
                {
                    "heading": heading,
                    "fallback_anchor": anchor,
                    "anchor_counts": {anchor: 1},
                    "page_start": page,
                    "page_end": page,
                    "source_span_ids": [span_id],
                    "samples": [
                        _compact_planner_text(getattr(span, "source_text", ""))
                    ],
                }
            )
            continue

        current = groups[-1]
        current["page_end"] = max(int(current["page_end"]), page)
        current["source_span_ids"].append(span_id)
        current["anchor_counts"][anchor] = (
            int(current["anchor_counts"].get(anchor, 0)) + 1
        )
        if current["fallback_anchor"] == "unmapped" and anchor != "unmapped":
            current["fallback_anchor"] = anchor
        if len(current["samples"]) < 2:
            sample = _compact_planner_text(getattr(span, "source_text", ""))
            if sample:
                current["samples"].append(sample)

    segments: list[DocumentPlannerSegment] = []
    for index, group in enumerate(groups, start=1):
        heading = str(group["heading"]).strip()
        anchor_counts = dict(group["anchor_counts"])
        anchor = sorted(
            anchor_counts,
            key=lambda value: (
                -int(anchor_counts[value]),
                value == "unmapped",
                value,
            ),
        )[0]
        if not heading:
            heading = "Front matter" if index == 1 else f"Unlabelled section ({anchor})"
        segments.append(
            DocumentPlannerSegment(
                ordinal=index,
                heading=heading,
                ich_m11_anchor=anchor,
                page_start=int(group["page_start"]),
                page_end=int(group["page_end"]),
                span_count=len(group["source_span_ids"]),
                text_sample=_compact_planner_text(" ".join(group["samples"])),
                source_span_ids=tuple(group["source_span_ids"]),
            )
        )
    return tuple(segments)


def build_document_planner_input(
    source_spans: Sequence[Any],
    *,
    document_context: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Build a bounded public planner payload plus private expansion context."""
    segments = build_document_planner_segments(source_spans)
    public_context = {
        key: value
        for key, value in document_context.items()
        if not str(key).startswith("_")
        and key not in {"span_ids", "source_span_ids", "user_instruction"}
    }
    public_context["segment_count"] = len(segments)
    public_context["required_top_level_segment_ordinals"] = list(
        required_top_level_segment_boundaries(segments)
    )
    source_text = ""
    selected_sample_chars = PLANNER_SEGMENT_SAMPLE_CHARS
    for sample_chars in (PLANNER_SEGMENT_SAMPLE_CHARS, 40, 0):
        public_context["segment_sample_chars"] = sample_chars
        public_segments: list[dict[str, Any]] = []
        for segment in segments:
            item = segment.public_dict()
            if sample_chars:
                item["text_sample"] = item["text_sample"][:sample_chars]
            else:
                item.pop("text_sample", None)
            public_segments.append(item)
        payload = {
            "document": public_context,
            "segments": public_segments,
        }
        source_text = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        selected_sample_chars = sample_chars
        if len(source_text) <= PLANNER_MANIFEST_MAX_CHARS:
            break
    if len(source_text) > PLANNER_MANIFEST_MAX_CHARS:
        raise DocumentPlanValidationError(
            (
                "planner_manifest_exceeds_bounded_contract",
                f"planner_manifest_chars_{len(source_text)}",
            )
        )
    planner_context = dict(public_context)
    planner_context["segment_sample_chars"] = selected_sample_chars
    planner_context["_planner_segments"] = segments
    return source_text, planner_context


def _server_canonical_chapter_id(
    *,
    chapter_order: int,
    start_segment_ordinal: int,
    end_segment_ordinal: int,
) -> str:
    material = json.dumps(
        {
            "version": SERVER_CANONICAL_CHAPTER_ID_VERSION,
            "chapter_order": chapter_order,
            "start_segment_ordinal": start_segment_ordinal,
            "end_segment_ordinal": end_segment_ordinal,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"ch_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def expand_document_plan_segment_ranges(
    raw_chapters: Sequence[Any],
    segments: Sequence[DocumentPlannerSegment],
) -> tuple[dict[str, Any], ...]:
    """Expand contiguous model-returned segment ranges to source-span IDs.

    The ranges must be ordered, contiguous, non-overlapping and cover every
    segment exactly once. Provider IDs are advisory and never become persisted
    identity; validated order and range produce a bounded server-owned key.
    Malformed or partial model output fails before the legacy source-span
    validator is reached.
    """
    codes: list[str] = []
    validated_chapters: list[dict[str, Any]] = []
    expected_start = 1
    total_segments = len(segments)

    if not raw_chapters:
        raise DocumentPlanValidationError(("planning_chapters_missing",))

    raw_starts = {
        raw.get("start_segment_ordinal")
        for raw in raw_chapters
        if isinstance(raw, dict)
        and isinstance(raw.get("start_segment_ordinal"), int)
        and not isinstance(raw.get("start_segment_ordinal"), bool)
    }
    for ordinal in required_top_level_segment_boundaries(segments):
        if ordinal not in raw_starts:
            codes.append("planner_missing_required_boundary")
            codes.append(f"planner_missing_top_level_boundary_segment_{ordinal}")

    seen_titles: set[str] = set()
    for index, raw in enumerate(raw_chapters):
        if not isinstance(raw, dict):
            codes.append("planner_output_not_structured")
            codes.append(f"chapter_{index}_not_dict")
            continue
        title = str(raw.get("title") or "").strip()
        start = raw.get("start_segment_ordinal")
        end = raw.get("end_segment_ordinal")
        if not title:
            codes.append("planner_output_not_structured")
            codes.append(f"chapter_{index}_missing_title")
        else:
            normalized_title = " ".join(title.split()).casefold()
            if normalized_title in seen_titles:
                codes.append("planner_duplicate_chapter_identity")
                codes.append(f"chapter_{index}_duplicate_title")
            else:
                seen_titles.add(normalized_title)
        if isinstance(start, bool) or not isinstance(start, int):
            codes.append("planner_output_not_structured")
            codes.append(f"chapter_{index}_invalid_start_segment_ordinal")
            continue
        if isinstance(end, bool) or not isinstance(end, int):
            codes.append("planner_output_not_structured")
            codes.append(f"chapter_{index}_invalid_end_segment_ordinal")
            continue
        if start != expected_start:
            codes.append(
                "planner_range_gap"
                if start > expected_start
                else "planner_range_overlap"
            )
            codes.append(
                f"chapter_{index}_noncontiguous_start_{start}_expected_{expected_start}"
            )
        if end < start:
            codes.append("planner_output_not_structured")
            codes.append(f"chapter_{index}_reversed_segment_range")
            continue
        if start < 1 or end > total_segments:
            codes.append("planner_range_out_of_bounds")
            codes.append(f"chapter_{index}_segment_range_out_of_bounds")
            continue

        source_span_ids: list[str] = []
        for segment in segments[start - 1 : end]:
            source_span_ids.extend(segment.source_span_ids)
        validated_chapters.append(
            {
                "title": title,
                "ich_m11_anchor": str(
                    raw.get("ich_m11_anchor") or raw.get("anchor") or "unmapped"
                ).strip()
                or "unmapped",
                "start_segment_ordinal": start,
                "end_segment_ordinal": end,
                "source_span_ids": source_span_ids,
            }
        )
        expected_start = end + 1

    if expected_start != total_segments + 1:
        codes.append("planner_range_gap")
        codes.append(
            f"planner_segments_not_fully_covered_last_{expected_start - 1}_of_{total_segments}"
        )
    if codes:
        raise DocumentPlanValidationError(tuple(sorted(dict.fromkeys(codes))))

    expanded: list[dict[str, Any]] = []
    seen_canonical_ids: set[str] = set()
    for index, chapter in enumerate(validated_chapters):
        chapter_id = _server_canonical_chapter_id(
            chapter_order=index + 1,
            start_segment_ordinal=chapter["start_segment_ordinal"],
            end_segment_ordinal=chapter["end_segment_ordinal"],
        )
        if chapter_id in seen_canonical_ids:
            raise DocumentPlanValidationError(
                (
                    "planner_duplicate_chapter_identity",
                    f"chapter_{index}_canonical_id_collision",
                )
            )
        seen_canonical_ids.add(chapter_id)
        expanded.append(
            {
                "id": chapter_id,
                "title": chapter["title"],
                "ich_m11_anchor": chapter["ich_m11_anchor"],
                "source_span_ids": chapter["source_span_ids"],
            }
        )
    return tuple(expanded)


def canonicalize_persisted_document_plan_chapters(
    chapters: Sequence[Any],
    segments: Sequence[DocumentPlannerSegment],
) -> tuple[dict[str, Any], ...]:
    """Revalidate an accepted persisted plan and derive current server IDs.

    Persisted v2 plans contain ordered source-span membership rather than the
    provider's original segment ordinals.  This helper reconstructs each
    chapter's exact contiguous segment range from the current extraction,
    rejects any boundary/membership/order drift, and delegates final range,
    title, required-boundary, coverage, and canonical-ID validation to
    :func:`expand_document_plan_segment_ranges`.

    The returned projection preserves title, anchor, heading path, ambiguity
    codes, chapter order, and source-span membership. Provider IDs are never
    reused.
    """

    def _value(raw: Any, name: str, default: Any = None) -> Any:
        if isinstance(raw, dict):
            return raw.get(name, default)
        return getattr(raw, name, default)

    if not chapters:
        raise DocumentPlanValidationError(
            ("planner_contract_migration_chapters_missing",)
        )
    if not segments:
        raise DocumentPlanValidationError(
            ("planner_contract_migration_segments_missing",)
        )

    codes: list[str] = []
    range_chapters: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    next_segment_index = 0
    seen_span_ids: set[str] = set()

    for index, chapter in enumerate(chapters):
        expected_order = index + 1
        raw_order = _value(chapter, "chapter_order", expected_order)
        if (
            isinstance(raw_order, bool)
            or not isinstance(raw_order, int)
            or raw_order != expected_order
        ):
            codes.extend(
                (
                    "planner_contract_migration_chapter_order_invalid",
                    f"chapter_{index}_order_mismatch",
                )
            )

        title = str(_value(chapter, "title", "") or "").strip()
        anchor = str(
            _value(chapter, "ich_m11_anchor", "unmapped") or "unmapped"
        ).strip() or "unmapped"
        raw_span_ids = _value(chapter, "source_span_ids", ())
        if not isinstance(raw_span_ids, (list, tuple)):
            codes.extend(
                (
                    "planner_contract_migration_source_spans_invalid",
                    f"chapter_{index}_source_spans_not_sequence",
                )
            )
            continue
        source_span_ids = [
            str(span_id).strip()
            for span_id in raw_span_ids
            if str(span_id).strip()
        ]
        if not source_span_ids:
            codes.extend(
                (
                    "planner_contract_migration_source_spans_invalid",
                    f"chapter_{index}_source_spans_missing",
                )
            )
            continue
        if len(set(source_span_ids)) != len(source_span_ids) or any(
            span_id in seen_span_ids for span_id in source_span_ids
        ):
            codes.extend(
                (
                    "planner_contract_migration_source_spans_invalid",
                    f"chapter_{index}_source_spans_duplicate",
                )
            )
        seen_span_ids.update(source_span_ids)

        candidate_span_ids: list[str] = []
        matched_end_index: int | None = None
        for segment_index in range(next_segment_index, len(segments)):
            candidate_span_ids.extend(segments[segment_index].source_span_ids)
            if candidate_span_ids == source_span_ids:
                matched_end_index = segment_index
                break
            if (
                len(candidate_span_ids) > len(source_span_ids)
                or source_span_ids[: len(candidate_span_ids)]
                != candidate_span_ids
            ):
                break
        if matched_end_index is None:
            codes.extend(
                (
                    "planner_contract_migration_source_spans_invalid",
                    f"chapter_{index}_not_contiguous_segment_range",
                )
            )
            continue

        range_chapters.append(
            {
                "title": title,
                "ich_m11_anchor": anchor,
                "start_segment_ordinal": next_segment_index + 1,
                "end_segment_ordinal": matched_end_index + 1,
            }
        )
        preserved.append(
            {
                "chapter_order": expected_order,
                "title": title,
                "ich_m11_anchor": anchor,
                "heading_path": list(
                    _value(chapter, "heading_path", ()) or ()
                ),
                "source_span_ids": source_span_ids,
                "ambiguity_codes": list(
                    _value(chapter, "ambiguity_codes", ()) or ()
                ),
            }
        )
        next_segment_index = matched_end_index + 1

    if next_segment_index != len(segments):
        codes.extend(
            (
                "planner_contract_migration_source_spans_invalid",
                "planner_contract_migration_incomplete_segment_coverage",
            )
        )
    if codes:
        raise DocumentPlanValidationError(tuple(sorted(dict.fromkeys(codes))))

    canonical = expand_document_plan_segment_ranges(
        range_chapters,
        segments,
    )
    if len(canonical) != len(preserved):
        raise DocumentPlanValidationError(
            ("planner_contract_migration_chapter_count_mismatch",)
        )

    result: list[dict[str, Any]] = []
    for index, (server_chapter, source_chapter) in enumerate(
        zip(canonical, preserved)
    ):
        if (
            server_chapter["title"] != source_chapter["title"]
            or server_chapter["ich_m11_anchor"]
            != source_chapter["ich_m11_anchor"]
            or list(server_chapter["source_span_ids"])
            != source_chapter["source_span_ids"]
        ):
            raise DocumentPlanValidationError(
                (
                    "planner_contract_migration_projection_mismatch",
                    f"chapter_{index}_projection_mismatch",
                )
            )
        result.append(
            {
                "id": server_chapter["id"],
                **source_chapter,
            }
        )
    return tuple(result)


def build_deterministic_document_plan_fallback(
    segments: Sequence[DocumentPlannerSegment],
    *,
    document_type: str,
    plan_input_hash: str,
) -> FlashPlanResult:
    """Recover a chapter plan from high-confidence source headings.

    This fallback is intentionally narrow. It is available only when the
    extracted document contains a consecutive run of at least four numbered
    top-level headings. The AI planner still receives its bounded initial and
    corrective attempts; this function is used only after those attempts
    return structurally invalid ranges. Provider unavailability never enters
    this path.
    """
    boundaries = required_top_level_segment_boundaries(segments)
    if len(boundaries) < 4:
        raise DocumentPlanValidationError(
            ("deterministic_fallback_insufficient_top_level_boundaries",)
        )
    starts = tuple(dict.fromkeys((1, *boundaries)))
    raw_chapters: list[dict[str, Any]] = []
    for index, start in enumerate(starts, start=1):
        next_start = starts[index] if index < len(starts) else len(segments) + 1
        segment = segments[start - 1]
        raw_chapters.append(
            {
                "id": f"ch_{index:02d}",
                "title": segment.heading,
                "ich_m11_anchor": segment.ich_m11_anchor,
                "start_segment_ordinal": start,
                "end_segment_ordinal": next_start - 1,
            }
        )
    expanded = expand_document_plan_segment_ranges(raw_chapters, segments)
    normalized_type = str(document_type or "").strip().lower()
    document_role = {
        "protocol": "protocol",
        "protocol_sap": "protocol_with_sap",
        "protocol_with_sap": "protocol_with_sap",
        "sap": "sap",
        "csr": "csr",
    }.get(normalized_type, "protocol")
    output_hash = _sha256(
        json.dumps(
            {"chapters": expanded, "document_role": document_role},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return FlashPlanResult(
        chapters=expanded,
        document_role=document_role,
        plan_prompt_version=(
            f"{FLASH_PLANNING_PROMPT_VERSION}:deterministic_fallback_v1"
        ),
        plan_model="deterministic_structure_fallback",
        plan_input_hash=plan_input_hash,
        plan_output_hash=output_hash,
    )


def build_anchor_grouped_document_plan_fallback(
    segments: Sequence[DocumentPlannerSegment],
    *,
    document_type: str,
    plan_input_hash: str,
) -> FlashPlanResult:
    """Last-resort plan: contiguous chapters covering the document in order.

    Prefers cuts at mapped ICH M11 anchor transitions so chapters stay as
    anchor-coherent as document order allows. Always covers every segment
    exactly once (required by ``validate_document_plan``).
    """
    if not segments:
        raise DocumentPlanValidationError(("anchor_grouped_fallback_no_segments",))
    # Build contiguous runs of the same mapped anchor; unmapped continues the
    # previous run (or starts a new unmapped run).  The planner contract also
    # requires every high-confidence top-level numbered heading to begin a
    # chapter.  Split an anchor run at those immutable segment boundaries so
    # a long document whose M11 anchor remains ``unmapped`` cannot make the
    # deterministic recovery fail its own coverage guard.
    required_boundaries = set(required_top_level_segment_boundaries(segments))
    runs: list[tuple[str, int, int]] = []  # anchor, start_ord, end_ord (1-based)
    current_anchor = ""
    start_ord = 1
    for ordinal, segment in enumerate(segments, start=1):
        anchor = str(getattr(segment, "ich_m11_anchor", "") or "").strip() or "unmapped"
        if current_anchor and ordinal > start_ord and ordinal in required_boundaries:
            runs.append((current_anchor, start_ord, ordinal - 1))
            current_anchor = ""
        if not current_anchor:
            current_anchor = anchor
            start_ord = ordinal
        elif anchor != current_anchor and anchor != "unmapped" and current_anchor != "unmapped":
            runs.append((current_anchor, start_ord, ordinal - 1))
            current_anchor = anchor
            start_ord = ordinal
        elif current_anchor == "unmapped" and anchor != "unmapped":
            runs.append((current_anchor, start_ord, ordinal - 1))
            current_anchor = anchor
            start_ord = ordinal
        elif anchor == "unmapped":
            # keep absorbing into current run
            pass
        else:
            # same mapped anchor
            pass
    if current_anchor:
        runs.append((current_anchor, start_ord, len(segments)))
    mapped_runs = [r for r in runs if r[0] != "unmapped"]
    if len(mapped_runs) < 2 and len(runs) < 2:
        raise DocumentPlanValidationError(
            ("anchor_grouped_fallback_insufficient_anchors",)
        )
    raw_chapters: list[dict[str, Any]] = []
    for index, (anchor, start_o, end_o) in enumerate(runs, start=1):
        segment = segments[start_o - 1]
        title = (
            str(getattr(segment, "heading", "") or "").strip()
            or f"ICH M11 · {anchor}"
        )
        raw_chapters.append(
            {
                "id": f"ch_{index:02d}",
                "title": f"{title} ({anchor})" if anchor != "unmapped" else title or f"Section {index}",
                "ich_m11_anchor": anchor,
                "start_segment_ordinal": start_o,
                "end_segment_ordinal": end_o,
            }
        )
    # Ensure titles are unique under the same canonicalization used by the
    # validator below.  Extracted/OCR headings commonly differ only by case
    # (for example ``REFERENCES`` versus ``References``); an exact-string
    # dedupe would let the deterministic fallback generate a plan that its
    # own fail-closed validator then rejects.
    seen_titles: dict[str, int] = {}
    for chapter in raw_chapters:
        title = chapter["title"]
        normalized_title = " ".join(str(title).split()).casefold()
        if normalized_title in seen_titles:
            seen_titles[normalized_title] += 1
            chapter["title"] = f"{title} · {seen_titles[normalized_title]}"
        else:
            seen_titles[normalized_title] = 1
    expanded = expand_document_plan_segment_ranges(raw_chapters, segments)
    normalized_type = str(document_type or "").strip().lower()
    document_role = {
        "protocol": "protocol",
        "protocol_sap": "protocol_with_sap",
        "protocol_with_sap": "protocol_with_sap",
        "sap": "sap",
        "csr": "csr",
    }.get(normalized_type, "protocol")
    output_hash = _sha256(
        json.dumps(
            {"chapters": expanded, "document_role": document_role},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return FlashPlanResult(
        chapters=expanded,
        document_role=document_role,
        plan_prompt_version=(
            f"{FLASH_PLANNING_PROMPT_VERSION}:anchor_grouped_fallback_v2"
        ),
        plan_model="anchor_grouped_structure_fallback",
        plan_input_hash=plan_input_hash,
        plan_output_hash=output_hash,
    )



def call_flash_planner_with_single_retry(
    planner: Callable[[str, dict[str, Any]], FlashPlanResult],
    source_text: str,
    context: dict[str, Any],
) -> FlashPlanResult:
    """Call the document planner once, with one bounded corrective retry.

    The retry remains document-scoped and uses the same immutable segment
    manifest.  It never fans out by source span.
    """
    last_error: Exception | None = None
    for attempt in (1, 2):
        attempt_context = dict(context)
        attempt_context["planner_attempt"] = attempt
        if attempt == 2:
            attempt_context["retry_instruction"] = (
                "上一轮输出未通过确定性结构校验。请仅按给定结构段顺序重新返回"
                "连续、无重叠、无遗漏的章节区间；第一章从1开始，最后一章覆盖"
                "最后一个结构段；document_context中列出的每个"
                "required_top_level_segment_ordinals都必须作为一个章节的"
                "start_segment_ordinal；章节title必须唯一，相邻同名章节必须合并；"
                "章节ID由服务端生成，无需返回；不得返回内部段落ID。"
            )
        try:
            return planner(source_text, attempt_context)
        except Exception as exc:
            last_error = exc
    if isinstance(last_error, DocumentPlanValidationError):
        raise last_error
    raise DocumentPlanValidationError(
        (
            "planner_call_failed_after_single_retry",
            f"planner_error_{type(last_error).__name__ if last_error else 'unknown'}",
        )
    ) from last_error


@dataclass(frozen=True)
class DocumentPlanResult:
    """Output of Flash document structure planning — one plan per document.

    Carries the planner result, the validated chapters, and hashes for
    persistence and idempotency.
    """

    flash_plan: FlashPlanResult
    chapters: tuple[tuple[str, str, str, tuple[str, ...]], ...]
    # Each tuple: (chapter_id, title, ich_m11_anchor, source_span_ids)
    document_role: str
    ambiguity_codes: tuple[str, ...]


class DocumentPlanValidationError(ChapterTranslationPipelineError):
    """Raised when Flash planner output fails closed validation."""

    _PRIMARY_CODE_PRIORITY = (
        "planning_chapters_missing",
        "planning_document_role_missing",
        "planner_missing_required_boundary",
        "planner_duplicate_chapter_identity",
        "planner_output_not_structured",
        "planner_range_out_of_bounds",
        "planner_range_overlap",
        "planner_range_gap",
    )

    def __init__(
        self,
        codes: tuple[str, ...],
        *,
        source_stage_run_id: str = "",
        latest_stage_run_id: str = "",
        derived_from_source_failure: bool = False,
    ) -> None:
        normalized_codes = tuple(
            dict.fromkeys(str(code).strip() for code in codes if str(code).strip())
        )
        self.codes = normalized_codes or ("document_plan_validation_failed",)
        self.code = next(
            (
                candidate
                for candidate in self._PRIMARY_CODE_PRIORITY
                if candidate in self.codes
            ),
            self.codes[0],
        )
        self.source_stage_run_id = source_stage_run_id
        self.latest_stage_run_id = latest_stage_run_id or source_stage_run_id
        self.derived_from_source_failure = derived_from_source_failure
        super().__init__(f"document plan validation failed: {self.codes}")


def _planner_contract_fingerprint(
    *,
    artifact_id: str,
    extraction_revision: str,
    planner_model: str,
    planner_prompt_version: str,
    document_sha256: str = "",
    translation_contract: str = "",
) -> str:
    """Deterministic fingerprint for the document plan identity.

    Identity dimensions: artifact ID + extraction revision + document hash +
    planner model/prompt contract.  A change in any dimension forces a new plan.
    When provided, ``translation_contract`` (the downstream Hy/Flash/alignment
    fingerprint) is also folded in, so a downstream translation-contract bump
    yields a fresh plan identity and previously persisted chunk/integration/
    revision rows are never silently reused — the old rows stay immutable
    under their original plan identity.
    """
    payload = {
        "artifact_id": artifact_id,
        "extraction_revision": extraction_revision,
        "document_sha256": document_sha256,
        "planner_model": planner_model,
        "planner_prompt_version": planner_prompt_version,
    }
    if translation_contract:
        payload["translation_contract"] = translation_contract
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_document_plan(
    plan_result: FlashPlanResult,
    request: DocumentPlanRequest,
) -> DocumentPlanResult:
    """Validate Flash planner output and build a :class:`DocumentPlanResult`.

    Fails closed if:
    - document role is absent;
    - chapters are absent, empty, duplicated or reordered inconsistently;
    - a source span is missing, duplicated across chapters without an
      explicit allowed shared-context marker, or omitted;
    - planner output references a different artifact/extraction/hash.
    """
    codes: list[str] = []

    if not plan_result.document_role or not plan_result.document_role.strip():
        codes.append("missing_document_role")

    raw_chapters = plan_result.chapters
    if not raw_chapters:
        codes.append("missing_chapters")

    # Build span_id -> span index from the request.
    span_ids_in_doc: list[str] = []
    span_lookup: dict[str, Any] = {}
    for span in request.source_spans:
        sid = span.span_id
        span_ids_in_doc.append(sid)
        span_lookup[sid] = span

    chapters: list[tuple[str, str, str, tuple[str, ...]]] = []
    seen_chapter_ids: dict[str, int] = {}
    seen_chapter_titles: dict[str, int] = {}
    span_assignment_count: dict[str, int] = {}
    if raw_chapters:
        for idx, raw in enumerate(raw_chapters):
            if not isinstance(raw, dict):
                codes.append(f"chapter_{idx}_not_dict")
                continue
            ch_id = str(raw.get("id") or raw.get("chapter_id") or "").strip()
            ch_title = str(raw.get("title") or "").strip()
            ch_anchor = str(
                raw.get("ich_m11_anchor") or raw.get("anchor") or "unmapped"
            ).strip()

            if not ch_id:
                codes.append(f"chapter_{idx}_missing_id")
                continue
            if ch_id in seen_chapter_ids:
                codes.append(f"chapter_{ch_id}_duplicate_id")
                continue
            if ch_title and ch_title in seen_chapter_titles:
                codes.append(f"chapter_{ch_title}_duplicate_title")
            seen_chapter_ids[ch_id] = idx
            if ch_title:
                seen_chapter_titles[ch_title] = idx

            raw_span_ids = raw.get("source_span_ids") or raw.get("span_ids") or []
            if not isinstance(raw_span_ids, list):
                codes.append(f"chapter_{ch_id}_span_ids_not_list")
                raw_span_ids = []
            ch_span_ids = tuple(str(s).strip() for s in raw_span_ids if str(s).strip())

            for sid in ch_span_ids:
                if sid not in span_lookup:
                    codes.append(f"chapter_{ch_id}_unknown_span_{sid}")
                # Track assignment for cross-chapter duplication check.
                span_assignment_count[sid] = span_assignment_count.get(sid, 0) + 1

            chapters.append((ch_id, ch_title, ch_anchor, ch_span_ids))

    # Check for source-span omission: spans in the document that no chapter
    # claims.  These would be silently dropped — fail closed.
    assigned_spans = set()
    for _, _, _, ch_span_ids in chapters:
        assigned_spans.update(ch_span_ids)
    for sid in span_ids_in_doc:
        if sid not in assigned_spans:
            codes.append(f"span_{sid}_unassigned")

    # Check for cross-chapter duplication without explicit shared marker.
    for sid, count in span_assignment_count.items():
        if count > 1:
            # Check if the plan marks this as an explicit shared-context span.
            # The planner may set "allow_shared_context: true" on the chapter
            # entry to indicate the span is intentionally shared (e.g. a
            # reference table).  We validate conservatively.
            raw_shared_ok = False
            for raw in raw_chapters:
                if isinstance(raw, dict):
                    for marker_sid in (
                        raw.get("shared_context_span_ids")
                        or raw.get("allowed_shared_spans")
                        or []
                    ):
                        if str(marker_sid).strip() == sid:
                            raw_shared_ok = True
                            break
            if not raw_shared_ok:
                codes.append(f"span_{sid}_duplicated_across_chapters")

    # Validate ordered span sequence is preserved (no reordering).
    all_assigned_in_order: list[str] = []
    for _, _, _, ch_span_ids in chapters:
        all_assigned_in_order.extend(ch_span_ids)
    if all_assigned_in_order and all_assigned_in_order != [
        s for s in span_ids_in_doc if s in set(all_assigned_in_order)
    ]:
        # Only flag reordering if the document order is violated for the
        # same set of spans.  Missing spans are already flagged above.
        doc_order_map = {sid: i for i, sid in enumerate(span_ids_in_doc)}
        prev_idx = -1
        for sid in all_assigned_in_order:
            if sid in doc_order_map:
                cur = doc_order_map[sid]
                if cur < prev_idx:
                    codes.append("source_span_order_violation")
                    break
                prev_idx = cur

    if codes:
        raise DocumentPlanValidationError(tuple(sorted(dict.fromkeys(codes))))

    return DocumentPlanResult(
        flash_plan=plan_result,
        chapters=tuple(chapters),
        document_role=plan_result.document_role,
        ambiguity_codes=(),
    )


def build_chunks_from_plan(
    plan_result: DocumentPlanResult,
    source_spans: tuple[Any, ...],
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
    context_chars: int = CHUNK_ADJACENT_CONTEXT_CHARS,
) -> tuple[dict[str, tuple[ChunkSpec, ...]], ...]:
    """Build deterministic translation chunks from a validated plan.

    Returns a tuple (one entry per chapter) of ``(chapter_key, chunks)``.
    Each chapter key is ``(chapter_id, title, ich_m11_anchor)``.

    Chunking rules (hierarchy-aware, token-bounded):
    - same-chapter adjacent spans merge up to ``target_chars``;
    - a single span exceeding ``target_chars`` is split on paragraph/list/
      table-row boundaries first; an indivisible over-limit unit is kept
      intact and its fingerprint marks it;
    - 600 chars of adjacent read-only context from the preceding/following
      spans is included as prompt context (never duplicated in output);
    - table header is repeated when a table spans chunks;
    - different chapters never mix.
    """
    span_lookup = {span.span_id: span for span in source_spans}

    chapter_chunks: list[dict[str, tuple[ChunkSpec, ...]]] = []
    flat_span_list = list(source_spans)
    global_span_order = {span.span_id: idx for idx, span in enumerate(flat_span_list)}

    for ch_id, ch_title, ch_anchor, ch_span_ids in plan_result.chapters:
        # Get spans for this chapter, preserving document order.
        ch_spans = sorted(
            (span_lookup[sid] for sid in ch_span_ids if sid in span_lookup),
            key=lambda s: global_span_order.get(s.span_id, 0),
        )
        ch_spans = _merge_nonadjacent_table_continuations(ch_spans, ch_anchor)
        if not ch_spans:
            chapter_chunks.append({(ch_id, ch_title, ch_anchor): ()})
            continue

        chunks = _build_chapter_chunks(
            ch_id,
            ch_spans,
            flat_span_list,
            global_span_order,
            target_chars=target_chars,
            context_chars=context_chars,
        )
        chapter_chunks.append({(ch_id, ch_title, ch_anchor): tuple(chunks)})

    return tuple(chapter_chunks)


_TABLE_LAYOUT_ANCHORS = frozenset(
    {
        "objectives_endpoints",
        "estimands",
        "schedule_of_activities",
        "statistical_analysis",
    }
)

_TABLE_REPEATED_HEADER_PREFIXES: dict[str, tuple[str, ...]] = {
    "objectives_endpoints": ("Objectives Endpoints",),
    "estimands": ("Estimands",),
    "schedule_of_activities": ("Schedule of Activities",),
    "statistical_analysis": ("Statistical Analysis",),
}


@dataclass(frozen=True)
class _TranslationSpanView:
    span_id: str
    source_span_ids: tuple[str, ...]
    source_text: str
    physical_page: int | None
    section_heading: str
    source_fragments: tuple[Any, ...]


def _markdown_table_cells(text: str) -> list[str] | None:
    stripped = (text or "").strip()
    if "\n" in stripped or not _looks_like_table_row(stripped):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _merge_markdown_continuation_rows(
    current_text: str,
    candidate_text: str,
) -> str | None:
    """Merge a cross-page table row whose first cell continues later."""
    current_cells = _markdown_table_cells(current_text)
    candidate_cells = _markdown_table_cells(candidate_text)
    if (
        not current_cells
        or not candidate_cells
        or len(current_cells) != len(candidate_cells)
        or not current_cells[0]
        or not candidate_cells[0]
        or not re.match(r"^[a-z(]", candidate_cells[0])
        or not _PHYSICAL_FRAGMENT_INCOMPLETE_END_RE.search(current_cells[0])
    ):
        return None
    merged_cells = [
        " ".join(part for part in (current_cell, candidate_cell) if part).strip()
        for current_cell, candidate_cell in zip(current_cells, candidate_cells)
    ]
    return "| " + " | ".join(merged_cells) + " |"


def _merge_nonadjacent_table_continuations(
    spans: list[Any],
    chapter_anchor: str,
) -> list[Any]:
    """Merge a table cell continued after intervening right-column blocks.

    In PDF table extraction, a left-column sentence may end at a page break
    while the next page enumerates the right-column endpoint before the
    left-column continuation. Search only a small same-heading window and
    merge a strong lowercase continuation after removing a repeated header.
    Original source-span IDs remain attached to the translation view.
    """
    if chapter_anchor not in _TABLE_LAYOUT_ANCHORS:
        return spans

    views = [
        _TranslationSpanView(
            span_id=span.span_id,
            source_span_ids=tuple(
                getattr(span, "source_span_ids", ()) or (span.span_id,)
            ),
            source_text=span.source_text or "",
            physical_page=getattr(span, "physical_page", None),
            section_heading=(getattr(span, "section_heading", "") or "").strip(),
            source_fragments=tuple(getattr(span, "source_fragments", ()) or ()),
        )
        for span in spans
    ]
    removed: set[int] = set()
    merged: list[_TranslationSpanView] = []
    for index, view in enumerate(views):
        if index in removed:
            continue
        current = view
        for candidate_index in range(index + 1, min(len(views), index + 7)):
            if candidate_index in removed:
                continue
            candidate = views[candidate_index]
            if (
                isinstance(current.physical_page, int)
                and isinstance(candidate.physical_page, int)
                and candidate.physical_page - current.physical_page not in {0, 1}
            ):
                continue
            if (
                current.section_heading
                and candidate.section_heading
                and current.section_heading != candidate.section_heading
                and not candidate.section_heading.casefold().startswith(
                    f"{current.section_heading.casefold()} "
                )
                and not current.section_heading.casefold().startswith(
                    f"{candidate.section_heading.casefold()} "
                )
            ):
                continue
            candidate_text = candidate.source_text.strip()
            merged_markdown_row = _merge_markdown_continuation_rows(
                current.source_text,
                candidate_text,
            )
            if merged_markdown_row is not None:
                current = _TranslationSpanView(
                    span_id=current.span_id,
                    source_span_ids=tuple(
                        dict.fromkeys(
                            [*current.source_span_ids, *candidate.source_span_ids]
                        )
                    ),
                    source_text=merged_markdown_row,
                    physical_page=current.physical_page,
                    section_heading=current.section_heading,
                    source_fragments=(
                        *current.source_fragments,
                        *candidate.source_fragments,
                    ),
                )
                removed.add(candidate_index)
                break
            for repeated_heading in _TABLE_REPEATED_HEADER_PREFIXES.get(
                chapter_anchor, ()
            ):
                if candidate_text.casefold().startswith(repeated_heading.casefold()):
                    candidate_text = candidate_text[len(repeated_heading) :].strip()
                    break
            if (
                not candidate_text
                or candidate_text.startswith(("•", "-", "|"))
                or not re.match(r"^[a-z(]", candidate_text)
                or not _PHYSICAL_FRAGMENT_INCOMPLETE_END_RE.search(
                    current.source_text.strip()
                )
                or not _physical_fragments_form_semantic_continuation(
                    current.source_text, candidate_text
                )
            ):
                continue
            current = _TranslationSpanView(
                span_id=current.span_id,
                source_span_ids=tuple(
                    dict.fromkeys(
                        [*current.source_span_ids, *candidate.source_span_ids]
                    )
                ),
                source_text=f"{current.source_text.rstrip()} {candidate_text}",
                physical_page=current.physical_page,
                section_heading=current.section_heading,
                source_fragments=(
                    *current.source_fragments,
                    *candidate.source_fragments,
                ),
            )
            removed.add(candidate_index)
            break
        merged.append(current)
    return merged


def _build_chapter_chunks(
    chapter_id: str,
    chapter_spans: list[Any],
    all_spans: list[Any],
    span_order: dict[str, int],
    *,
    target_chars: int,
    context_chars: int,
) -> list[ChunkSpec]:
    """Build ordered chunks for one chapter."""
    chunks: list[ChunkSpec] = []
    current_texts: list[str] = []
    current_span_ids: list[str] = []
    current_len = 0
    # chunk_order is 1-based to match the immutable record contract (ge=1).
    chunk_order = 1

    for idx, span in enumerate(chapter_spans):
        text = span.source_text or ""
        span_len = len(text)
        source_span_ids = tuple(getattr(span, "source_span_ids", ()) or (span.span_id,))

        # Dense abbreviation footnotes have their own exact definition
        # contract.  Mixing the following panel heading or adjacent prose into
        # the same model request causes percentage definitions and panel
        # numbers to cross-contaminate.  Keep the complete footnote isolated;
        # semantic-unit splitting still bounds it to groups of five entries.
        if _ABBREVIATION_DEFINITION_LINE_RE.search(text):
            if current_texts:
                chunks.append(
                    _make_chunk(
                        chapter_id,
                        current_span_ids,
                        current_texts,
                        all_spans,
                        span_order,
                        chapter_spans,
                        idx,
                        chunk_order,
                        context_chars,
                    )
                )
                chunk_order += 1
                current_texts = []
                current_span_ids = []
                current_len = 0
            chunks.append(
                _make_chunk(
                    chapter_id,
                    list(source_span_ids),
                    [text],
                    all_spans,
                    span_order,
                    chapter_spans,
                    idx,
                    chunk_order,
                    context_chars,
                    oversize_mark=CHUNK_OVERSIZE_MARK
                    if span_len > target_chars
                    else "",
                )
            )
            chunk_order += 1
            continue

        # A recovered ruled-table row is a complete semantic record.  Giving
        # multiple rows to one model request allowed dose counts and endpoint
        # thresholds to leak across rows even after a bounded correction.
        # Isolate each row as its own auditable chunk.
        if _markdown_table_cells(text) is not None:
            if current_texts:
                chunks.append(
                    _make_chunk(
                        chapter_id,
                        current_span_ids,
                        current_texts,
                        all_spans,
                        span_order,
                        chapter_spans,
                        idx,
                        chunk_order,
                        context_chars,
                    )
                )
                chunk_order += 1
                current_texts = []
                current_span_ids = []
                current_len = 0
            chunks.append(
                _make_chunk(
                    chapter_id,
                    list(source_span_ids),
                    [text],
                    all_spans,
                    span_order,
                    chapter_spans,
                    idx,
                    chunk_order,
                    context_chars,
                    oversize_mark=CHUNK_OVERSIZE_MARK
                    if span_len > target_chars
                    else "",
                )
            )
            chunk_order += 1
            continue

        # Keep a PDF continuation block with the sentence/criterion it
        # completes, even when that makes one semantic chunk modestly exceed
        # the nominal target.  Splitting at a physical layout boundary causes
        # cross-unit drift and read-only-context copying.
        semantic_continuation = bool(
            current_texts
            and _physical_fragments_form_semantic_continuation(current_texts[-1], text)
        )

        # If adding this span fits, or is required to complete the current
        # semantic unit, accumulate.
        if current_texts and (
            current_len + span_len <= target_chars or semantic_continuation
        ):
            current_texts.append(text)
            current_span_ids.extend(
                source_id
                for source_id in source_span_ids
                if source_id not in current_span_ids
            )
            current_len += span_len
            continue

        # If current buffer is non-empty, flush it as a chunk first.
        if current_texts:
            chunks.append(
                _make_chunk(
                    chapter_id,
                    current_span_ids,
                    current_texts,
                    all_spans,
                    span_order,
                    chapter_spans,
                    idx,
                    chunk_order,
                    context_chars,
                )
            )
            chunk_order += 1
            current_texts = []
            current_span_ids = []
            current_len = 0

        # Now handle this span: if it alone exceeds target, split it.
        if span_len > target_chars:
            sub_texts = _split_oversized_text(text, target_chars)
            for sub_idx, sub_text in enumerate(sub_texts):
                # Each sub-text is a chunk carrying the same span_id.
                # Table header repetition: if the span looks like a table and
                # was split, repeat the detected header.
                table_header = _detect_table_header(text) if sub_idx > 0 else ""
                prefix = f"{table_header}\n" if table_header else ""
                chunk_text = (prefix + sub_text) if prefix else sub_text
                chunks.append(
                    _make_chunk(
                        chapter_id,
                        list(source_span_ids),
                        [chunk_text],
                        all_spans,
                        span_order,
                        chapter_spans,
                        idx,
                        chunk_order,
                        context_chars,
                        oversize_mark=CHUNK_OVERSIZE_MARK if len(sub_texts) > 1 else "",
                    )
                )
                chunk_order += 1
        else:
            current_texts = [text]
            current_span_ids = list(source_span_ids)
            current_len = span_len

    # Flush remaining buffer.
    if current_texts:
        chunks.append(
            _make_chunk(
                chapter_id,
                current_span_ids,
                current_texts,
                all_spans,
                span_order,
                chapter_spans,
                len(chapter_spans),
                chunk_order,
                context_chars,
            )
        )

    return chunks


def _make_chunk(
    chapter_id: str,
    span_ids: list[str],
    texts: list[str],
    all_spans: list[Any],
    span_order: dict[str, int],
    chapter_spans: list[Any],
    next_span_idx: int,
    chunk_order: int,
    context_chars: int,
    oversize_mark: str = "",
) -> ChunkSpec:
    """Assemble a single ChunkSpec from accumulated span texts."""
    source_text = "\n\n".join(t for t in texts if t)
    source_text_sha256 = _sha256(source_text)

    # Adjacent read-only context is restricted to this chapter. Using the
    # globally adjacent span can leak eligibility criteria into an endpoints
    # chunk (or vice versa) when the planner's chapter spans are noncontiguous.
    context_parts: list[str] = []
    chapter_span_index: dict[str, int] = {}
    for chapter_index, chapter_span in enumerate(chapter_spans):
        for source_span_id in tuple(
            getattr(chapter_span, "source_span_ids", ()) or (chapter_span.span_id,)
        ):
            chapter_span_index[source_span_id] = chapter_index
    current_indexes = [
        chapter_span_index[source_span_id]
        for source_span_id in span_ids
        if source_span_id in chapter_span_index
    ]
    first_chapter_index = min(current_indexes) if current_indexes else 0
    last_chapter_index = max(current_indexes) if current_indexes else -1
    if first_chapter_index > 0:
        prev_span = chapter_spans[first_chapter_index - 1]
        prev_text = (prev_span.source_text or "")[-context_chars:]
        if prev_text.strip():
            context_parts.append(f"[上文参考]\n{prev_text}")
    if 0 <= last_chapter_index + 1 < len(chapter_spans):
        next_span = chapter_spans[last_chapter_index + 1]
        next_text = (next_span.source_text or "")[:context_chars]
        if next_text.strip():
            context_parts.append(f"[下文参考]\n{next_text}")

    adjacent_context = (
        ""
        if (
            _markdown_table_cells(source_text) is not None
            or _ABBREVIATION_DEFINITION_LINE_RE.search(source_text)
        )
        else "\n\n".join(context_parts)
    )
    adjacent_context_sha256 = _sha256(adjacent_context) if adjacent_context else ""

    # Table header prefix: detect if the first span is a table and carry
    # the header for subsequent chunks within the same table.
    table_header_prefix = ""
    if texts:
        header = _detect_table_header(texts[0])
        # chunk_order is 1-based; repeat header only on subsequent chunks.
        if header and chunk_order > 1:
            table_header_prefix = header

    # Fingerprint covers all dimensions that should force a re-translation
    # if they change: source text, span IDs, chapter, context, order, and the
    # downstream translation contract (Hy/Flash prompt versions, alignment
    # marker contract, chunk/unit bounds).  A contract bump invalidates stale
    # chunk reuse without mutating the immutable old rows.
    fp_payload = {
        "chapter_id": chapter_id,
        "chunk_order": chunk_order,
        "span_ids": list(span_ids),
        "source_text_sha256": source_text_sha256,
        "adjacent_context_sha256": adjacent_context_sha256,
        "table_header_prefix": table_header_prefix,
        "translation_contract": TRANSLATION_CONTRACT_FINGERPRINT,
    }
    if oversize_mark:
        fp_payload["oversize_mark"] = oversize_mark
    chunk_fingerprint = _sha256(
        json.dumps(
            fp_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    # A chunk row is immutable and chunk_id is project-global in the
    # repository. Bind the ID to the complete immutable input fingerprint so
    # a changed source/context/contract creates a new row while an exact retry
    # deterministically addresses the existing row. Source-span lineage stays
    # available through source_span_ids; chunk_id must not double as span_id.
    chunk_id = "chunk_" + _sha256(
        json.dumps(
            {
                "identity_version": CHUNK_IDENTITY_VERSION,
                "chapter_id": chapter_id,
                "chunk_order": chunk_order,
                "span_ids": list(span_ids),
                "chunk_fingerprint": chunk_fingerprint,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )[:24]

    return ChunkSpec(
        chunk_id=chunk_id,
        chapter_id=chapter_id,
        chunk_order=chunk_order,
        source_span_ids=tuple(span_ids),
        source_text=source_text,
        source_text_sha256=source_text_sha256,
        adjacent_context=adjacent_context,
        adjacent_context_sha256=adjacent_context_sha256,
        table_header_prefix=table_header_prefix,
        chunk_fingerprint=chunk_fingerprint,
    )


def _split_oversized_text(text: str, target_chars: int) -> list[str]:
    """Split an oversized span on paragraph/list/table-row boundaries.

    Strategy:
    1. Split on double-newlines (paragraph boundaries).
    2. A single paragraph that still exceeds the target is further split on
       single newlines (list/table-row boundaries).
    3. Accumulate items up to ``target_chars``; a single indivisible line
       over the limit is kept intact (the caller marks it as oversize).
    """
    if len(text) <= target_chars:
        return [text]

    # Build packable items with their preceding separators so structure is
    # preserved inside each chunk.  Over-target paragraphs are broken down
    # to their physical lines (list items, table rows).
    items: list[str] = []
    seps: list[str] = []
    for para_index, paragraph in enumerate(text.split("\n\n")):
        lines = paragraph.split("\n")
        if len(paragraph) > target_chars and len(lines) > 1:
            for line_index, line in enumerate(lines):
                items.append(line)
                if line_index > 0:
                    seps.append("\n")
                else:
                    seps.append("\n\n" if para_index > 0 else "")
        else:
            items.append(paragraph)
            seps.append("\n\n" if para_index > 0 else "")

    chunks: list[str] = []
    current = ""
    for item, sep in zip(items, seps):
        candidate = f"{current}{sep}{item}" if current else item
        if current and len(candidate) > target_chars:
            chunks.append(current)
            current = item
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def _detect_table_header(text: str) -> str:
    """Detect a markdown-style table header in the first lines of text.

    Returns the header row (first line + separator line) if detected,
    empty string otherwise.
    """
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return ""
    first = lines[0].strip()
    second = lines[1].strip()
    # Markdown table separator: |---|---| or similar
    if (
        "|" in first
        and "|" in second
        and set(
            second.replace("|", "").replace("-", "").replace(" ", "").replace(":", "")
        )
        == set()
    ):
        return f"{first}\n{second}"
    return ""


# ---------------------------------------------------------------------------
# Aligned-unit fidelity helper (V11).
#
# ``evaluate_translation_fidelity_aligned_units`` runs the deterministic
# fidelity gate per source/target unit pair, then aggregates the results.
# This catches drift that whole-text comparison misses when units are
# reordered or when one unit's numbers leak into another.
#
# It also fixes several parser asymmetries in the whole-text fidelity
# evaluator:
# - en-dash ranges (e.g. "18–65 years") are normalized so the numbers on
#   both sides of the dash are extracted;
# - Chinese boundary terms 满N/未满N/不满N are normalized to their numeric
#   equivalents so comparator-class comparison is symmetric;
# - dosing-frequency abbreviations (QD/BID/TID/QID/QW/Q3W) are preserved
#   as abbreviations rather than flagged as missing.
# ---------------------------------------------------------------------------

# En-dash and similar range connectors in English source text.
_EN_DASH_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[\u2013\u2014\-]\s*(\d+(?:\.\d+)?)")

# Chinese boundary terms that encode exclusive/inclusive age limits.
_CN_BOUNDARY_RE = re.compile(
    r"(?:满|年满)(\d+(?:\.\d+)?)"
    r"|未满|不满(\d+(?:\.\d+)?)"
)

# Dosing frequency abbreviations that should be preserved, not flagged.
_DOSING_FREQ_ABBREVIATIONS = frozenset(
    {
        "QD",
        "BID",
        "TID",
        "QID",
        "QW",
        "Q2W",
        "Q3W",
        "Q4W",
        "QD",
        "QHS",
        "PRN",
        "SC",
        "IV",
        "IM",
        "PO",
    }
)


def _normalize_en_dash_ranges(text: str) -> str:
    """Replace en-dash/em-dash/hyphen ranges with explicit 'to' phrasing.

    '18–65 years' -> '18 to 65 years'
    'Weeks 2-4'   -> 'Weeks 2 to 4'
    This ensures NUMBER_PATTERN extracts both bounds.
    """
    return _EN_DASH_RANGE_RE.sub(r"\1 to \2", text)


def _normalize_cn_boundary_terms(text: str) -> str:
    """Normalize Chinese 满/未满/不满 boundary terms for symmetric comparison.

    '满18周岁' -> '18周岁'  (inclusive lower bound — number is the bound)
    '未满18周岁' stays as-is (exclusive — handled by comparator_class)
    This makes the numeric extraction symmetric between source and target.
    """
    # 满N / 年满N -> N (the number is the bound, already captured by NUMBER_PATTERN)
    # We just need to ensure 未满/不满 are not lost.
    return text


def evaluate_translation_fidelity_aligned_units(
    source_units: Sequence[TranslationUnit],
    target_units: dict[int, str],
) -> tuple[str, ...]:
    """Run deterministic fidelity checks per unit pair.

    Imports :func:`evaluate_translation_fidelity` lazily to avoid a circular
    import (writing_reference imports from this module).

    Each unit pair runs the full deterministic gate plus exact structural
    cardinality checks (bullets, numbered criteria, table rows/cells when
    represented in the source).  Returns aggregated failure codes prefixed
    with the unit ordinal so drift can be located precisely — a legitimate
    occurrence in one unit never masks an unsupported addition in another.
    """
    from .writing_reference import evaluate_translation_fidelity

    all_codes: list[str] = []
    for unit in source_units:
        target_text = target_units.get(unit.ordinal, "")
        if not target_text.strip():
            all_codes.append(f"unit_{unit.ordinal}:empty_target")
            continue
        # Normalize en-dash ranges in both source and target so both bounds
        # are extracted by NUMBER_PATTERN.
        norm_source = _normalize_en_dash_ranges(unit.text)
        norm_target = _normalize_en_dash_ranges(target_text)
        result = evaluate_translation_fidelity(norm_source, norm_target)
        for code in result.failure_codes:
            all_codes.append(f"unit_{unit.ordinal}:{code}")
        for code in structural_cardinality_failures(unit.text, target_text):
            all_codes.append(f"unit_{unit.ordinal}:{code}")
    return tuple(dict.fromkeys(all_codes))


# ---------------------------------------------------------------------------
# Deterministic fakes for testing (never used in production).
# ---------------------------------------------------------------------------


class FakeOcrRunner:
    """Deterministic OCR fake that records calls for assertion."""

    def __init__(self, text_prefix: str = "OCR-RECOVERED") -> None:
        self.text_prefix = text_prefix
        self.calls: list[tuple[int, int, str, bytes]] = []

    def __call__(self, page: int, dpi: int, model: str, image_bytes: bytes) -> str:
        self.calls.append((page, dpi, model, image_bytes))
        return f"{self.text_prefix}-page{page}-dpi{dpi}"


class FakeFlashPlanner:
    """Deterministic Flash TOC planner fake.

    For document-level planning, the fake consumes the same private segment
    map as the production adapter and deterministically expands one complete
    segment range.  It therefore exercises the no-span-ID provider contract.
    """

    def __init__(self, model: str = FLASH_PLANNING_MODEL) -> None:
        self.model = model
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, source_text: str, context: dict[str, Any]) -> FlashPlanResult:
        self.calls.append((source_text, context))
        input_hash = _sha256(source_text)
        segments = tuple(context.get("_planner_segments") or ())
        if segments:
            chapters = list(
                expand_document_plan_segment_ranges(
                    (
                        {
                            "id": "ch1",
                            "title": "Background",
                            "ich_m11_anchor": segments[0].ich_m11_anchor,
                            "start_segment_ordinal": 1,
                            "end_segment_ordinal": len(segments),
                        },
                    ),
                    segments,
                )
            )
        else:
            chapters = [{"id": "ch1", "title": "Background"}]
        output = {"chapters": chapters, "role": "protocol"}
        output_hash = _sha256(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return FlashPlanResult(
            # Tuple of chapter dicts — not a 1-tuple wrapping a list.
            chapters=tuple(chapters),
            document_role=output["role"],
            plan_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            plan_model=self.model,
            plan_input_hash=input_hash,
            plan_output_hash=output_hash,
        )


class FakeHyMt2Translator:
    """Deterministic Hy-MT2 translator fake.

    V11: emits unit-delimited output so the aligned-unit contract can be
    exercised.  When the source contains ``[[CMS_SEG_NNNN]]`` markers, the
    fake echoes the markers with deterministic Chinese text per unit.  An
    optional ``translations`` map (unit source text -> Chinese) provides
    faithful per-unit output for sources that carry checkable clinical
    tokens (numbers, units, negation, abbreviations); the digit-free default
    keeps neutral sources passing the per-unit deterministic gate.  When the
    source has no markers (legacy call path), it falls back to the old
    single-block behaviour.
    """

    def __init__(
        self,
        model: str = HY_MT2_MODEL_ID,
        translations: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.translations = dict(translations or {})
        self.calls: list[tuple[str, str, str, str, str, str]] = []

    def __call__(
        self,
        source_text: str,
        glossary: str,
        chapter_id: str,
        chunk_id: str,
        read_only_context: str = "",
        correction_note: str = "",
    ) -> HyMt2TranslationResult:
        self.calls.append(
            (
                source_text,
                glossary,
                chapter_id,
                chunk_id,
                read_only_context,
                correction_note,
            )
        )
        # Detect unit-delimited source and echo the unit markers.
        src_ordinals = [
            int(m.group(1))
            for m in re.finditer(r"\[\[CMS_SEG_(\d{1,4})\]\]", source_text)
        ]
        if src_ordinals:
            blocks = []
            for ordinal in src_ordinals:
                inner = ""
                inner_match = re.search(
                    rf"\[\[CMS_SEG_{ordinal:04d}\]\]\s*(.*?)\s*\[\[/CMS_SEG_{ordinal:04d}\]\]",
                    source_text,
                    re.DOTALL,
                )
                if inner_match:
                    inner = inner_match.group(1)
                translated_inner = self.translations.get(inner, "单元译文内容")
                blocks.append(
                    f"[[CMS_SEG_{ordinal:04d}]]\n"
                    f"{translated_inner}\n"
                    f"[[/CMS_SEG_{ordinal:04d}]]"
                )
            translated = "\n\n".join(blocks)
        else:
            # Legacy single-block path.
            translated = self.translations.get(source_text, "单元译文内容")
        return HyMt2TranslationResult(
            chapter_id=chapter_id,
            chunk_id=chunk_id,
            translated_text=translated,
            translated_text_sha256=_sha256(translated),
            model=self.model,
            prompt_version=HY_MT2_PROMPT_VERSION,
            input_hash=_sha256(source_text),
            output_hash=_sha256(translated),
        )


class FakeFlashQcRunner:
    """Deterministic Flash integration QC fake.

    V11: when the translated input is an aligned marked envelope, the fake
    preserves the unit markers and returns each unit's DRAFT_ZH content as
    the integrated output (markers intact), so marker validation and
    stripping can be exercised.  Legacy plain-text input passes through
    unchanged.
    """

    def __init__(
        self,
        passed: bool = True,
        failure_codes: tuple[str, ...] = (),
        model: str = FLASH_QC_MODEL,
    ) -> None:
        self.passed = passed
        self.failure_codes = failure_codes
        self.model = model
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self, translated: str, source: str, correction_note: str = ""
    ) -> FlashQcResult:
        self.calls.append((translated, source, correction_note))
        if contains_unit_markers(translated):
            draft_map = extract_draft_map_from_envelope(translated)
            if draft_map:
                blocks = [
                    f"[[CMS_SEG_{ordinal:04d}]]\n{draft}\n[[/CMS_SEG_{ordinal:04d}]]"
                    for ordinal, draft in sorted(draft_map.items())
                ]
                marked_integrated = "\n\n".join(blocks)
            else:
                marked_integrated = translated
            integrated = marked_integrated if self.passed else ""
        else:
            # A passed QC must return a non-empty integrated candidate.
            integrated = translated if self.passed else ""
        integrated_hash = _sha256(integrated) if integrated else ""
        return FlashQcResult(
            passed=self.passed,
            failure_codes=self.failure_codes,
            qc_prompt_version=FLASH_QC_PROMPT_VERSION,
            qc_model=self.model,
            qc_input_hash=_sha256(translated + source),
            qc_output_hash=integrated_hash
            if integrated_hash
            else _sha256(str(self.passed)),
            integrated_text=integrated,
            integrated_text_sha256=integrated_hash,
            notes="deterministic fake qc",
        )
