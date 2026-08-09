from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Callable, Literal, Protocol

from packages.contracts.workbench_contracts import (
    UpperLayerStage,
    WritingReferenceUpperLayerCapabilities,
    WritingReferenceUpperLayerEscalation,
    WritingReferenceUpperLayerProviderCallAttempt,
    WritingReferenceUpperLayerStageCapability,
    WritingReferenceUpperLayerStageRun,
)

from .chapter_translation_pipeline import (
    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
    FLASH_PLANNING_PROMPT_VERSION,
    PLANNER_CONTRACT_TRANSITION_VERSION,
)
from .writing_reference_repository import WritingReferenceRepository


DEFAULT_UPPER_LAYER_MODEL = "deepseek-v4-flash"
ESCALATED_UPPER_LAYER_MODEL = "deepseek-v4-pro"
UPPER_LAYER_PROVIDER = "deepseek"
UPPER_LAYER_TRANSPORT = "openai_compatible"
UPPER_LAYER_INVOCATION_CONTRACT_VERSION = (
    "product_ai_upper_layer_v5_contract_supersession"
)
IMPLEMENTED_UPPER_LAYER_STAGES = frozenset(
    {"document_planning", "post_hy_mt2_integration_qc"}
)
AUTOMATIC_ESCALATION_STATUSES = frozenset(
    {"failed_escalatable", "completed_degraded"}
)
_ADAPTER_RESULT_STATUSES = frozenset(
    {
        "succeeded",
        "completed_degraded",
        "failed_escalatable",
        "failed_terminal",
    }
)
PLANNER_STRUCTURAL_RETRY_FAILURE_CODES = frozenset(
    {
        "planning_chapters_missing",
        "planning_document_role_missing",
        "planner_range_gap",
        "planner_range_overlap",
        "planner_range_out_of_bounds",
        "planner_missing_required_boundary",
        "planner_duplicate_chapter_identity",
        "planner_output_not_structured",
        "planning_output_not_structured",
        "deterministic_upper_layer_output_invalid",
        "product_ai_deterministic_response_invalid",
    }
)
PLANNER_STRUCTURAL_RETRY_INSTRUCTION = (
    "上一轮输出未通过确定性结构校验。请仅按给定结构段顺序重新返回连续、无重叠、"
    "无遗漏的章节区间；第一章从1开始，最后一章覆盖最后一个结构段；"
    "required_top_level_segment_ordinals中的每个序号必须作为章节起点；"
    "章节title必须唯一，相邻同名章节必须合并；章节ID由服务端生成，无需返回；"
    "不得返回内部段落ID。"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_failure_code(value: str, fallback: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"_", "-", "."} else "_"
        for char in (value or "").strip().lower()
    )
    return normalized[:120] or fallback


@dataclass(frozen=True)
class UpperLayerExecutionRequest:
    """Server-internal stage request.

    Route identity is intentionally absent. The service owns provider and model
    selection; API request contracts must not expose this dataclass directly.
    """

    project_id: str
    owner_type: Literal[
        "translation_batch_item",
        "direct_translation",
        "corpus_selection",
    ]
    owner_id: str
    artifact_id: str
    extraction_revision: str
    stage: UpperLayerStage
    prompt_version: str
    prompt: str
    deployment_profile: str
    input_payload: Any
    idempotency_key: str
    batch_id: str = ""
    item_id: str = ""
    plan_id: str = ""
    chapter_id: str = ""
    hy_mt2_target_map_sha256: str = ""
    retry_generation: int = 0
    retry_parent_stage_run_id: str = ""
    contract_supersession_generation: int = 0
    contract_supersession_transition_version: str = ""
    contract_supersession_source_stage_run_id: str = ""
    contract_supersession_source_execution_fingerprint: str = ""
    contract_supersession_source_prompt_version: str = ""
    contract_supersession_target_prompt_version: str = ""

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "artifact_id": self.artifact_id,
            "extraction_revision": self.extraction_revision,
            "stage": self.stage,
            "prompt_version": self.prompt_version,
            "prompt_sha256": sha256(self.prompt.encode("utf-8")).hexdigest(),
            "deployment_profile": self.deployment_profile,
            "input_hash": _sha256_json(self.input_payload),
            "batch_id": self.batch_id,
            "item_id": self.item_id,
            "plan_id": self.plan_id,
            "chapter_id": self.chapter_id,
            "hy_mt2_target_map_sha256": self.hy_mt2_target_map_sha256,
            "retry_generation": self.retry_generation,
            "retry_parent_stage_run_id": self.retry_parent_stage_run_id,
            "contract_supersession_generation": (
                self.contract_supersession_generation
            ),
            "contract_supersession_transition_version": (
                self.contract_supersession_transition_version
            ),
            "contract_supersession_source_stage_run_id": (
                self.contract_supersession_source_stage_run_id
            ),
            "contract_supersession_source_execution_fingerprint": (
                self.contract_supersession_source_execution_fingerprint
            ),
            "contract_supersession_source_prompt_version": (
                self.contract_supersession_source_prompt_version
            ),
            "contract_supersession_target_prompt_version": (
                self.contract_supersession_target_prompt_version
            ),
        }


@dataclass(frozen=True)
class UpperLayerAdapterRequest:
    stage_run_id: str
    stage: UpperLayerStage
    provider: str
    transport: str
    requested_model: str
    deployment_profile: str
    prompt_version: str
    prompt: str
    input_payload: Any
    input_hash: str
    hy_mt2_target_map_sha256: str = ""
    is_escalation: bool = False
    provider_call_index: int = 1
    planner_attempt: int = 0
    retry_instruction: str = ""


@dataclass(frozen=True)
class UpperLayerAdapterResult:
    response_model: str
    status: Literal[
        "succeeded",
        "completed_degraded",
        "failed_escalatable",
        "failed_terminal",
    ]
    output_payload: Any = None
    failure_code: str = ""
    preserved_hy_mt2_target_map_sha256: str = ""


class UpperLayerAdapter(Protocol):
    def invoke(self, request: UpperLayerAdapterRequest) -> UpperLayerAdapterResult:
        ...


class UpperLayerTransientError(RuntimeError):
    """Retryable provider failure.

    Only the stable code is persisted. Raw provider error text stays in the
    caller's operational logs.
    """

    def __init__(self, code: str = "provider_transient") -> None:
        super().__init__(code)
        self.code = _safe_failure_code(code, "provider_transient")


class UpperLayerInterruptedError(RuntimeError):
    def __init__(self, code: str = "execution_interrupted") -> None:
        super().__init__(code)
        self.code = _safe_failure_code(code, "execution_interrupted")


@dataclass(frozen=True)
class UpperLayerExecutionOutcome:
    flash_run: WritingReferenceUpperLayerStageRun
    latest_run: WritingReferenceUpperLayerStageRun
    selected_run: WritingReferenceUpperLayerStageRun
    selected_output: Any
    escalation: WritingReferenceUpperLayerEscalation | None = None


AdapterFactory = Callable[[str], UpperLayerAdapter]


class WritingReferenceUpperLayerExecutionService:
    """Durable, server-routed Flash-to-Pro upper-layer execution."""

    def __init__(
        self,
        repository: WritingReferenceRepository,
        adapter_factory: AdapterFactory,
        *,
        provider: str = UPPER_LAYER_PROVIDER,
        transport: str = UPPER_LAYER_TRANSPORT,
        default_model: str = DEFAULT_UPPER_LAYER_MODEL,
        escalation_model: str = ESCALATED_UPPER_LAYER_MODEL,
        clock: Callable[[], datetime] = _utc_now,
        flash_max_attempts: int = 3,
        escalation_lease_seconds: int = 300,
    ) -> None:
        if flash_max_attempts < 1:
            raise ValueError("flash_max_attempts must be at least 1")
        if escalation_lease_seconds < 30:
            raise ValueError("escalation_lease_seconds must be at least 30")
        self.repository = repository
        self.adapter_factory = adapter_factory
        self.provider = provider.strip()
        self.transport = transport.strip()
        self.default_model = default_model.strip()
        self.escalation_model = escalation_model.strip()
        if not all(
            (
                self.provider,
                self.transport,
                self.default_model,
                self.escalation_model,
            )
        ):
            raise ValueError("upper-layer route identity is required")
        self.clock = clock
        self.flash_max_attempts = flash_max_attempts
        self.escalation_lease_seconds = escalation_lease_seconds

    @staticmethod
    def capabilities() -> WritingReferenceUpperLayerCapabilities:
        return WritingReferenceUpperLayerExecutionService._capabilities_for_models(
            DEFAULT_UPPER_LAYER_MODEL,
            ESCALATED_UPPER_LAYER_MODEL,
        )

    def configured_capabilities(self) -> WritingReferenceUpperLayerCapabilities:
        return self._capabilities_for_models(
            self.default_model,
            self.escalation_model,
        )

    @staticmethod
    def _capabilities_for_models(
        default_model: str,
        escalation_model: str,
    ) -> WritingReferenceUpperLayerCapabilities:
        return WritingReferenceUpperLayerCapabilities(
            upper_layer_stages={
                "document_planning": WritingReferenceUpperLayerStageCapability(
                    stage="document_planning",
                    status="implemented",
                    default_model=default_model,
                    escalation_model=escalation_model,
                    automatic_escalation_supported=True,
                ),
                "post_hy_mt2_integration_qc": WritingReferenceUpperLayerStageCapability(
                    stage="post_hy_mt2_integration_qc",
                    status="implemented",
                    default_model=default_model,
                    escalation_model=escalation_model,
                    automatic_escalation_supported=True,
                ),
                "corpus_selection_support": WritingReferenceUpperLayerStageCapability(
                    stage="corpus_selection_support",
                    status="not_implemented",
                    reason="no_product_stage_owner",
                ),
            }
        )

    def execute(self, request: UpperLayerExecutionRequest) -> UpperLayerExecutionOutcome:
        self._validate_request(request)
        self._validate_retry_parent(request)
        self._validate_contract_supersession(request)
        semantic = {
            **request.semantic_payload(),
            "provider": self.provider,
            "transport": self.transport,
            "default_model": self.default_model,
            "escalation_model": self.escalation_model,
            "invocation_contract_version": UPPER_LAYER_INVOCATION_CONTRACT_VERSION,
        }
        request_hash = _sha256_json(semantic)
        scoped_idempotency_key = self._route_scoped_idempotency_key(
            request.idempotency_key
        )
        replay_run_id = self.repository.upper_layer_execution_replay(
            request.project_id,
            idempotency_key=scoped_idempotency_key,
            request_hash=request_hash,
        )
        if replay_run_id:
            return self._outcome_from_persisted_run(
                request.project_id,
                replay_run_id,
            )

        flash_fingerprint = self._execution_fingerprint(
            request,
            model=self.default_model,
        )
        flash_run_id = self._stage_run_id(flash_fingerprint)
        flash_run = self.repository.optional_upper_layer_stage_run(
            request.project_id,
            flash_run_id,
        )
        if flash_run is None:
            flash_run, flash_output = self._invoke_and_persist(
                request,
                requested_model=self.default_model,
                stage_run_id=flash_run_id,
                execution_fingerprint=flash_fingerprint,
                max_attempts=self.flash_max_attempts,
            )
        else:
            self._verify_persisted_run_matches_request(
                flash_run,
                request,
                self.default_model,
            )
            persisted_execution = self.repository.upper_layer_stage_run_execution(
                request.project_id,
                flash_run.stage_run_id,
            )
            if (
                persisted_execution["execution_fingerprint"]
                != flash_fingerprint
            ):
                raise ValueError(
                    "persisted upper-layer execution fingerprint mismatch"
                )
            flash_output = persisted_execution["output_payload"]

        escalation: WritingReferenceUpperLayerEscalation | None = None
        latest_run = flash_run
        latest_output = flash_output
        if self._automatic_escalation_eligible(flash_run):
            escalation = self._get_or_create_escalation(request, flash_run)
            latest_run, latest_output, escalation = self._run_or_resume_escalation(
                request,
                flash_run,
                escalation,
            )

        selected_run, selected_output = self._select_effective_result(
            flash_run=flash_run,
            flash_output=flash_output,
            latest_run=latest_run,
            latest_output=latest_output,
        )
        if escalation is None or escalation.status not in {"queued", "running"}:
            self.repository.record_upper_layer_execution_idempotency(
                request.project_id,
                idempotency_key=scoped_idempotency_key,
                request_hash=request_hash,
                result_id=latest_run.stage_run_id,
            )
        return UpperLayerExecutionOutcome(
            flash_run=flash_run,
            latest_run=latest_run,
            selected_run=selected_run,
            selected_output=selected_output,
            escalation=escalation,
        )

    def resume_pending_escalations(
        self,
        *,
        project_id: str | None = None,
    ) -> list[UpperLayerExecutionOutcome]:
        outcomes: list[UpperLayerExecutionOutcome] = []
        for escalation in self.repository.recoverable_upper_layer_escalations(
            project_id=project_id,
            now=self.clock(),
        ):
            flash_run = self.repository.upper_layer_stage_run(
                escalation.project_id,
                escalation.source_stage_run_id,
            )
            request = self._request_from_persisted_run(flash_run)
            latest_run, latest_output, current = self._run_or_resume_escalation(
                request,
                flash_run,
                escalation,
            )
            flash_output = self.repository.upper_layer_stage_run_output(
                flash_run.project_id,
                flash_run.stage_run_id,
            )
            selected_run, selected_output = self._select_effective_result(
                flash_run=flash_run,
                flash_output=flash_output,
                latest_run=latest_run,
                latest_output=latest_output,
            )
            outcomes.append(
                UpperLayerExecutionOutcome(
                    flash_run=flash_run,
                    latest_run=latest_run,
                    selected_run=selected_run,
                    selected_output=selected_output,
                    escalation=current,
                )
            )
        return outcomes

    def _validate_request(self, request: UpperLayerExecutionRequest) -> None:
        if request.stage == "corpus_selection_support":
            raise NotImplementedError(
                "corpus_selection_support has no product model invocation"
            )
        if request.stage not in IMPLEMENTED_UPPER_LAYER_STAGES:
            raise ValueError("unsupported upper-layer stage")
        required = {
            "project_id": request.project_id,
            "owner_id": request.owner_id,
            "artifact_id": request.artifact_id,
            "extraction_revision": request.extraction_revision,
            "prompt_version": request.prompt_version,
            "prompt": request.prompt,
            "deployment_profile": request.deployment_profile,
            "idempotency_key": request.idempotency_key,
        }
        missing = sorted(name for name, value in required.items() if not value.strip())
        if missing:
            raise ValueError(f"upper-layer request fields are required: {', '.join(missing)}")
        if len(request.idempotency_key) < 8:
            raise ValueError("idempotency_key must contain at least 8 characters")
        _canonical_json(request.input_payload)
        if request.stage == "post_hy_mt2_integration_qc":
            value = request.hy_mt2_target_map_sha256
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(
                    "post-Hy-MT2 integration/QC requires a lowercase target-map SHA-256"
                )
        if request.retry_generation < 0:
            raise ValueError("upper-layer retry generation cannot be negative")
        if bool(request.retry_generation) != bool(
            request.retry_parent_stage_run_id
        ):
            raise ValueError(
                "upper-layer retry generation and retry parent must coexist"
            )
        if (
            request.retry_parent_stage_run_id
            and request.stage != "document_planning"
        ):
            raise ValueError(
                "upper-layer retry lineage is document-planning only"
            )
        supersession_values = (
            request.contract_supersession_transition_version,
            request.contract_supersession_source_stage_run_id,
            request.contract_supersession_source_execution_fingerprint,
            request.contract_supersession_source_prompt_version,
            request.contract_supersession_target_prompt_version,
        )
        if bool(request.contract_supersession_generation) != bool(
            any(supersession_values)
        ) or (
            request.contract_supersession_generation
            and not all(value.strip() for value in supersession_values)
        ):
            raise ValueError(
                "upper-layer contract supersession fields must coexist"
            )
        if request.contract_supersession_generation:
            if request.stage != "document_planning":
                raise ValueError(
                    "upper-layer contract supersession is document-planning only"
                )
            if request.retry_generation or request.retry_parent_stage_run_id:
                raise ValueError(
                    "ordinary retry and contract supersession are mutually exclusive"
                )

    def _validate_retry_parent(
        self,
        request: UpperLayerExecutionRequest,
    ) -> None:
        if request.retry_generation == 0:
            return
        try:
            parent = self.repository.upper_layer_stage_run(
                request.project_id,
                request.retry_parent_stage_run_id,
            )
        except KeyError as exc:
            raise ValueError("upper-layer retry parent was not found") from exc
        parent_execution = self.repository.upper_layer_stage_run_execution(
            request.project_id,
            parent.stage_run_id,
        )
        expected = {
            "owner_type": request.owner_type,
            "owner_id": request.owner_id,
            "batch_id": request.batch_id,
            "item_id": request.item_id,
            "artifact_id": request.artifact_id,
            "extraction_revision": request.extraction_revision,
            "stage": request.stage,
            "prompt_version": request.prompt_version,
            "deployment_profile": request.deployment_profile,
            "input_hash": _sha256_json(request.input_payload),
            "requested_model": self.default_model,
        }
        actual = {key: getattr(parent, key) for key in expected}
        if actual != expected:
            raise ValueError(
                "upper-layer retry parent does not match frozen stage lineage"
            )
        if parent_execution["prompt_text"] != request.prompt:
            raise ValueError(
                "upper-layer retry parent does not match frozen prompt contract"
            )
        if parent.parent_stage_run_id or parent.escalation_id:
            raise ValueError(
                "upper-layer retry parent must be a Flash source stage run"
            )
        if parent.status in {"succeeded", "completed_degraded"}:
            raise ValueError(
                "upper-layer retry parent must be a failed stage run"
            )
        if parent.retry_generation >= request.retry_generation:
            raise ValueError(
                "upper-layer retry generation must advance its parent"
            )

    def _validate_contract_supersession(
        self,
        request: UpperLayerExecutionRequest,
    ) -> None:
        if request.contract_supersession_generation == 0:
            return
        expected_transition = (
            FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            FLASH_PLANNING_PROMPT_VERSION,
            PLANNER_CONTRACT_TRANSITION_VERSION,
        )
        actual_transition = (
            request.contract_supersession_source_prompt_version,
            request.contract_supersession_target_prompt_version,
            request.contract_supersession_transition_version,
        )
        if actual_transition != expected_transition:
            raise ValueError(
                "upper-layer contract supersession transition is not allowlisted"
            )
        if request.prompt_version != FLASH_PLANNING_PROMPT_VERSION:
            raise ValueError(
                "upper-layer contract supersession target prompt is invalid"
            )
        try:
            source = self.repository.upper_layer_stage_run(
                request.project_id,
                request.contract_supersession_source_stage_run_id,
            )
        except KeyError as exc:
            raise ValueError(
                "upper-layer contract supersession source was not found"
            ) from exc
        source_execution = self.repository.upper_layer_stage_run_execution(
            request.project_id,
            source.stage_run_id,
        )
        expected = {
            "owner_type": request.owner_type,
            "owner_id": request.owner_id,
            "batch_id": request.batch_id,
            "item_id": request.item_id,
            "artifact_id": request.artifact_id,
            "extraction_revision": request.extraction_revision,
            "stage": request.stage,
            "prompt_version": (
                request.contract_supersession_source_prompt_version
            ),
            "deployment_profile": request.deployment_profile,
            "input_hash": _sha256_json(request.input_payload),
            "requested_model": self.default_model,
        }
        actual = {key: getattr(source, key) for key in expected}
        if actual != expected:
            raise ValueError(
                "upper-layer contract supersession source lineage mismatch"
            )
        if (
            source.parent_stage_run_id
            or source.escalation_id
            or source.status in {"succeeded", "completed_degraded"}
            or source.contract_supersession_generation
            or source.retry_generation
            >= request.contract_supersession_generation
        ):
            raise ValueError(
                "upper-layer contract supersession source is ineligible"
            )
        source_fingerprint = str(
            source_execution["execution_fingerprint"]
        )
        if (
            source_fingerprint
            != request.contract_supersession_source_execution_fingerprint
        ):
            raise ValueError(
                "upper-layer contract supersession source fingerprint mismatch"
            )

    def _invoke_and_persist(
        self,
        request: UpperLayerExecutionRequest,
        *,
        requested_model: str,
        stage_run_id: str,
        execution_fingerprint: str,
        parent_stage_run_id: str = "",
        escalation_id: str = "",
        max_attempts: int,
    ) -> tuple[WritingReferenceUpperLayerStageRun, Any]:
        started_at = self.clock()
        input_hash = _sha256_json(request.input_payload)
        is_escalation = bool(parent_stage_run_id and escalation_id)
        call_count = 0
        transport_failure_count = 0
        planner_attempt = 1 if request.stage == "document_planning" else 0
        planner_attempt_call_count = 0
        retry_instruction = ""
        provider_call_attempts: list[
            WritingReferenceUpperLayerProviderCallAttempt
        ] = []
        terminal_status: str = ""
        failure_code = ""
        response_model = ""
        output_payload: Any = None

        while True:
            call_count += 1
            planner_attempt_call_count += 1
            if is_escalation and call_count == 1:
                retry_kind = "escalation_initial"
            elif planner_attempt == 2 and planner_attempt_call_count == 1:
                retry_kind = "structural_correction"
            elif call_count == 1:
                retry_kind = "initial"
            else:
                retry_kind = "transport_retry"
            adapter_request = UpperLayerAdapterRequest(
                stage_run_id=stage_run_id,
                stage=request.stage,
                provider=self.provider,
                transport=self.transport,
                requested_model=requested_model,
                deployment_profile=request.deployment_profile,
                prompt_version=request.prompt_version,
                prompt=request.prompt,
                input_payload=request.input_payload,
                input_hash=input_hash,
                hy_mt2_target_map_sha256=request.hy_mt2_target_map_sha256,
                is_escalation=is_escalation,
                provider_call_index=call_count,
                planner_attempt=planner_attempt,
                retry_instruction=retry_instruction,
            )
            try:
                result = self.adapter_factory(requested_model).invoke(adapter_request)
            except UpperLayerTransientError as exc:
                transport_failure_count += 1
                failure_code = exc.code
                terminal_status = "failed_retryable"
                provider_call_attempts.append(
                    self._provider_call_attempt(
                        adapter_request,
                        retry_kind=retry_kind,
                        status=terminal_status,
                        failure_code=failure_code,
                    )
                )
                if transport_failure_count >= max_attempts:
                    break
                continue
            except UpperLayerInterruptedError as exc:
                failure_code = exc.code
                terminal_status = "interrupted"
                provider_call_attempts.append(
                    self._provider_call_attempt(
                        adapter_request,
                        retry_kind=retry_kind,
                        status=terminal_status,
                        failure_code=failure_code,
                    )
                )
                break
            except Exception:
                failure_code = "upper_layer_adapter_terminal_error"
                terminal_status = "failed_terminal"
                provider_call_attempts.append(
                    self._provider_call_attempt(
                        adapter_request,
                        retry_kind=retry_kind,
                        status=terminal_status,
                        failure_code=failure_code,
                    )
                )
                break

            response_model = result.response_model.strip()
            terminal_status = result.status
            failure_code = _safe_failure_code(
                result.failure_code,
                "upper_layer_stage_degraded"
                if terminal_status == "completed_degraded"
                else "",
            )
            output_payload = result.output_payload
            terminal_status, failure_code, output_payload = self._validate_adapter_result(
                request=request,
                requested_model=requested_model,
                result=result,
                status=terminal_status,
                failure_code=failure_code,
                is_escalation=is_escalation,
            )
            provider_call_attempts.append(
                self._provider_call_attempt(
                    adapter_request,
                    retry_kind=retry_kind,
                    status=terminal_status,
                    failure_code=failure_code,
                    response_model=response_model,
                )
            )
            if self._should_retry_planner_structure(
                request=request,
                requested_model=requested_model,
                is_escalation=is_escalation,
                planner_attempt=planner_attempt,
                status=terminal_status,
                failure_code=failure_code,
            ):
                planner_attempt = 2
                planner_attempt_call_count = 0
                retry_instruction = PLANNER_STRUCTURAL_RETRY_INSTRUCTION
                terminal_status = ""
                failure_code = ""
                response_model = ""
                output_payload = None
                continue
            break

        completed_at = self.clock()
        output_hash = (
            _sha256_json(output_payload)
            if output_payload is not None and terminal_status in {"succeeded", "completed_degraded"}
            else ""
        )
        run = WritingReferenceUpperLayerStageRun(
            stage_run_id=stage_run_id,
            project_id=request.project_id,
            owner_type=request.owner_type,
            owner_id=request.owner_id,
            batch_id=request.batch_id,
            item_id=request.item_id,
            artifact_id=request.artifact_id,
            extraction_revision=request.extraction_revision,
            plan_id=request.plan_id,
            chapter_id=request.chapter_id,
            stage=request.stage,
            provider=self.provider,
            transport=self.transport,
            requested_model=requested_model,
            response_model=response_model,
            deployment_profile=request.deployment_profile,
            prompt_version=request.prompt_version,
            input_hash=input_hash,
            output_hash=output_hash,
            status=terminal_status,
            failure_code=failure_code,
            provider_call_count=call_count,
            planner_attempt_count=planner_attempt,
            provider_call_attempts=provider_call_attempts,
            retry_generation=request.retry_generation,
            retry_parent_stage_run_id=request.retry_parent_stage_run_id,
            parent_stage_run_id=parent_stage_run_id,
            escalation_id=escalation_id,
            contract_supersession_generation=(
                request.contract_supersession_generation
                if not is_escalation
                else 0
            ),
            contract_supersession_transition_version=(
                request.contract_supersession_transition_version
                if not is_escalation
                else ""
            ),
            contract_supersession_source_stage_run_id=(
                request.contract_supersession_source_stage_run_id
                if not is_escalation
                else ""
            ),
            contract_supersession_source_execution_fingerprint=(
                request.contract_supersession_source_execution_fingerprint
                if not is_escalation
                else ""
            ),
            contract_supersession_source_prompt_version=(
                request.contract_supersession_source_prompt_version
                if not is_escalation
                else ""
            ),
            contract_supersession_target_prompt_version=(
                request.contract_supersession_target_prompt_version
                if not is_escalation
                else ""
            ),
            created_at=started_at,
            completed_at=completed_at,
        )
        stored = self.repository.save_upper_layer_stage_run(
            run,
            execution_fingerprint=execution_fingerprint,
            prompt_text=request.prompt,
            input_payload=request.input_payload,
            output_payload=output_payload,
            hy_mt2_target_map_sha256=request.hy_mt2_target_map_sha256,
        )
        return stored, output_payload

    @staticmethod
    def _provider_call_attempt(
        request: UpperLayerAdapterRequest,
        *,
        retry_kind: str,
        status: str,
        failure_code: str,
        response_model: str = "",
    ) -> WritingReferenceUpperLayerProviderCallAttempt:
        instruction_hash = (
            sha256(request.retry_instruction.encode("utf-8")).hexdigest()
            if request.retry_instruction
            else ""
        )
        return WritingReferenceUpperLayerProviderCallAttempt(
            call_index=request.provider_call_index,
            requested_model=request.requested_model,
            response_model=response_model,
            planner_attempt=request.planner_attempt,
            retry_kind=retry_kind,
            status=status,
            failure_code=failure_code,
            input_hash=request.input_hash,
            prompt_version=request.prompt_version,
            correction_instruction_sha256=instruction_hash,
        )

    def _should_retry_planner_structure(
        self,
        *,
        request: UpperLayerExecutionRequest,
        requested_model: str,
        is_escalation: bool,
        planner_attempt: int,
        status: str,
        failure_code: str,
    ) -> bool:
        return (
            request.stage == "document_planning"
            and requested_model == self.default_model
            and not is_escalation
            and planner_attempt == 1
            and status == "failed_escalatable"
            and failure_code in PLANNER_STRUCTURAL_RETRY_FAILURE_CODES
        )

    def _automatic_escalation_eligible(
        self,
        run: WritingReferenceUpperLayerStageRun,
    ) -> bool:
        if run.stage != "document_planning":
            return run.status in AUTOMATIC_ESCALATION_STATUSES
        if (
            run.requested_model != self.default_model
            or run.status != "failed_escalatable"
            or run.planner_attempt_count != 2
            or run.failure_code not in PLANNER_STRUCTURAL_RETRY_FAILURE_CODES
        ):
            return False
        attempts = tuple(run.provider_call_attempts)
        if not attempts:
            return False
        final_attempt = attempts[-1]
        return bool(
            final_attempt.planner_attempt == 2
            and final_attempt.failure_code == run.failure_code
            and any(
                attempt.planner_attempt == 2
                and attempt.correction_instruction_sha256
                for attempt in attempts
            )
        )

    def _validate_adapter_result(
        self,
        *,
        request: UpperLayerExecutionRequest,
        requested_model: str,
        result: UpperLayerAdapterResult,
        status: str,
        failure_code: str,
        is_escalation: bool,
    ) -> tuple[str, str, Any]:
        if status not in _ADAPTER_RESULT_STATUSES:
            return "failed_terminal", "invalid_upper_layer_result_status", None
        if status in {"succeeded", "completed_degraded"}:
            if result.response_model != requested_model:
                return "failed_terminal", "response_model_mismatch", None
            if result.output_payload is None:
                return "failed_terminal", "upper_layer_output_missing", None
        if is_escalation and status in {
            "completed_degraded",
            "failed_escalatable",
        }:
            return "failed_terminal", "pro_upper_layer_output_invalid", None
        if request.stage == "post_hy_mt2_integration_qc" and status in {
            "succeeded",
            "completed_degraded",
        }:
            if (
                result.preserved_hy_mt2_target_map_sha256
                != request.hy_mt2_target_map_sha256
            ):
                return "failed_terminal", "hy_mt2_target_map_changed", None
        if status not in {"succeeded", "completed_degraded"}:
            return status, failure_code, None
        return status, failure_code, result.output_payload

    def _get_or_create_escalation(
        self,
        request: UpperLayerExecutionRequest,
        flash_run: WritingReferenceUpperLayerStageRun,
    ) -> WritingReferenceUpperLayerEscalation:
        existing = self.repository.upper_layer_escalation_for_source(
            request.project_id,
            flash_run.stage_run_id,
        )
        if existing is not None:
            return existing
        escalation_id = "wref_ulesc_" + sha256(
            f"{flash_run.stage_run_id}|{flash_run.status}|{flash_run.failure_code}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        pro_fingerprint = self._execution_fingerprint(
            request,
            model=self.escalation_model,
            parent_stage_run_id=flash_run.stage_run_id,
            escalation_id=escalation_id,
        )
        target_run_id = self._stage_run_id(pro_fingerprint)
        now = self.clock()
        lineage_material = {
            "project_id": request.project_id,
            "stage": request.stage,
            "source_stage_run_id": flash_run.stage_run_id,
            "target_stage_run_id": target_run_id,
            "source_model": self.default_model,
            "target_model": self.escalation_model,
            "trigger_status": flash_run.status,
            "trigger_code": flash_run.failure_code,
            "request_fingerprint": pro_fingerprint,
        }
        escalation = WritingReferenceUpperLayerEscalation(
            escalation_id=escalation_id,
            project_id=request.project_id,
            stage=request.stage,
            source_stage_run_id=flash_run.stage_run_id,
            target_stage_run_id=target_run_id,
            trigger_status=flash_run.status,
            trigger_code=flash_run.failure_code
            or (
                "flash_completed_degraded"
                if flash_run.status == "completed_degraded"
                else "flash_failed_escalatable"
            ),
            lineage_hash=_sha256_json(lineage_material),
            source_model=self.default_model,
            target_model=self.escalation_model,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        return self.repository.save_upper_layer_escalation(
            escalation,
            request_fingerprint=pro_fingerprint,
        )

    def _run_or_resume_escalation(
        self,
        request: UpperLayerExecutionRequest,
        flash_run: WritingReferenceUpperLayerStageRun,
        escalation: WritingReferenceUpperLayerEscalation,
    ) -> tuple[
        WritingReferenceUpperLayerStageRun,
        Any,
        WritingReferenceUpperLayerEscalation,
    ]:
        persisted_target = self.repository.optional_upper_layer_stage_run(
            request.project_id,
            escalation.target_stage_run_id,
        )
        if persisted_target is not None:
            persisted_execution = self.repository.upper_layer_stage_run_execution(
                request.project_id,
                persisted_target.stage_run_id,
            )
            expected_fingerprint = (
                self.repository.upper_layer_escalation_request_fingerprint(
                    request.project_id,
                    escalation.escalation_id,
                )
            )
            if (
                persisted_execution["execution_fingerprint"]
                != expected_fingerprint
            ):
                raise ValueError(
                    "persisted Pro upper-layer execution fingerprint mismatch"
                )
            finalized = self.repository.finalize_upper_layer_escalation_from_existing_run(
                request.project_id,
                escalation.escalation_id,
                persisted_target,
                now=self.clock(),
            )
            return (
                persisted_target,
                self.repository.upper_layer_stage_run_output(
                    request.project_id,
                    persisted_target.stage_run_id,
                ),
                finalized,
            )
        if escalation.status in {"completed", "failed_terminal"}:
            return flash_run, self.repository.upper_layer_stage_run_output(
                request.project_id,
                flash_run.stage_run_id,
            ), escalation

        claim_started_at = self.clock()
        claim = self.repository.claim_upper_layer_escalation(
            request.project_id,
            escalation.escalation_id,
            now=claim_started_at,
            lease_expires_at=claim_started_at
            + timedelta(seconds=self.escalation_lease_seconds),
        )
        if claim is None:
            current = self.repository.upper_layer_escalation(
                request.project_id,
                escalation.escalation_id,
            )
            target = self.repository.optional_upper_layer_stage_run(
                request.project_id,
                current.target_stage_run_id,
            )
            if target is not None:
                return (
                    target,
                    self.repository.upper_layer_stage_run_output(
                        request.project_id,
                        target.stage_run_id,
                    ),
                    current,
                )
            return flash_run, self.repository.upper_layer_stage_run_output(
                request.project_id,
                flash_run.stage_run_id,
            ), current

        claimed_escalation, claim_token = claim
        pro_fingerprint = self.repository.upper_layer_escalation_request_fingerprint(
            request.project_id,
            claimed_escalation.escalation_id,
        )
        pro_run, pro_output = self._invoke_and_persist(
            request,
            requested_model=self.escalation_model,
            stage_run_id=claimed_escalation.target_stage_run_id,
            execution_fingerprint=pro_fingerprint,
            parent_stage_run_id=flash_run.stage_run_id,
            escalation_id=claimed_escalation.escalation_id,
            max_attempts=1,
        )
        escalation_status = (
            "completed"
            if pro_run.status == "succeeded"
            else "failed_retryable"
            if pro_run.status in {"failed_retryable", "interrupted"}
            else "failed_terminal"
        )
        finalized = self.repository.finish_upper_layer_escalation(
            request.project_id,
            claimed_escalation.escalation_id,
            claim_token=claim_token,
            target_run=pro_run,
            status=escalation_status,
            now=self.clock(),
        )
        return pro_run, pro_output, finalized

    def _outcome_from_persisted_run(
        self,
        project_id: str,
        run_id: str,
    ) -> UpperLayerExecutionOutcome:
        latest = self.repository.upper_layer_stage_run(project_id, run_id)
        if latest.parent_stage_run_id and latest.escalation_id:
            flash = self.repository.upper_layer_stage_run(
                project_id,
                latest.parent_stage_run_id,
            )
            escalation = self.repository.upper_layer_escalation(
                project_id,
                latest.escalation_id,
            )
        else:
            flash = latest
            escalation = self.repository.upper_layer_escalation_for_source(
                project_id,
                flash.stage_run_id,
            )
        flash_output = self.repository.upper_layer_stage_run_output(
            project_id,
            flash.stage_run_id,
        )
        latest_output = self.repository.upper_layer_stage_run_output(
            project_id,
            latest.stage_run_id,
        )
        selected_run, selected_output = self._select_effective_result(
            flash_run=flash,
            flash_output=flash_output,
            latest_run=latest,
            latest_output=latest_output,
        )
        return UpperLayerExecutionOutcome(
            flash_run=flash,
            latest_run=latest,
            selected_run=selected_run,
            selected_output=selected_output,
            escalation=escalation,
        )

    def _request_from_persisted_run(
        self,
        flash_run: WritingReferenceUpperLayerStageRun,
    ) -> UpperLayerExecutionRequest:
        persisted = self.repository.upper_layer_stage_run_execution(
            flash_run.project_id,
            flash_run.stage_run_id,
        )
        request = UpperLayerExecutionRequest(
            project_id=flash_run.project_id,
            owner_type=flash_run.owner_type,
            owner_id=flash_run.owner_id,
            artifact_id=flash_run.artifact_id,
            extraction_revision=flash_run.extraction_revision,
            stage=flash_run.stage,
            prompt_version=flash_run.prompt_version,
            prompt=persisted["prompt_text"],
            deployment_profile=flash_run.deployment_profile,
            input_payload=persisted["input_payload"],
            idempotency_key="recovery-" + flash_run.stage_run_id,
            batch_id=flash_run.batch_id,
            item_id=flash_run.item_id,
            plan_id=flash_run.plan_id,
            chapter_id=flash_run.chapter_id,
            hy_mt2_target_map_sha256=persisted["hy_mt2_target_map_sha256"],
            retry_generation=flash_run.retry_generation,
            retry_parent_stage_run_id=flash_run.retry_parent_stage_run_id,
            contract_supersession_generation=(
                flash_run.contract_supersession_generation
            ),
            contract_supersession_transition_version=(
                flash_run.contract_supersession_transition_version
            ),
            contract_supersession_source_stage_run_id=(
                flash_run.contract_supersession_source_stage_run_id
            ),
            contract_supersession_source_execution_fingerprint=(
                flash_run.contract_supersession_source_execution_fingerprint
            ),
            contract_supersession_source_prompt_version=(
                flash_run.contract_supersession_source_prompt_version
            ),
            contract_supersession_target_prompt_version=(
                flash_run.contract_supersession_target_prompt_version
            ),
        )
        expected_fingerprint = self._execution_fingerprint(
            request,
            model=flash_run.requested_model,
        )
        if persisted["execution_fingerprint"] != expected_fingerprint:
            raise ValueError(
                "persisted upper-layer execution fingerprint mismatch"
            )
        return request

    @staticmethod
    def _select_effective_result(
        *,
        flash_run: WritingReferenceUpperLayerStageRun,
        flash_output: Any,
        latest_run: WritingReferenceUpperLayerStageRun,
        latest_output: Any,
    ) -> tuple[WritingReferenceUpperLayerStageRun, Any]:
        if latest_run.parent_stage_run_id and latest_run.escalation_id:
            if latest_run.status == "succeeded":
                return latest_run, latest_output
            if flash_run.status == "completed_degraded":
                return flash_run, flash_output
        return flash_run, flash_output

    def _execution_fingerprint(
        self,
        request: UpperLayerExecutionRequest,
        *,
        model: str,
        parent_stage_run_id: str = "",
        escalation_id: str = "",
    ) -> str:
        return _sha256_json(
            {
                **request.semantic_payload(),
                "provider": self.provider,
                "transport": self.transport,
                "requested_model": model,
                "invocation_contract_version": UPPER_LAYER_INVOCATION_CONTRACT_VERSION,
                "parent_stage_run_id": parent_stage_run_id,
                "escalation_id": escalation_id,
            }
        )

    @staticmethod
    def _stage_run_id(execution_fingerprint: str) -> str:
        return "wref_ulrun_" + execution_fingerprint[:24]

    def _route_scoped_idempotency_key(self, key: str) -> str:
        route_hash = _sha256_json(
            {
                "provider": self.provider,
                "transport": self.transport,
                "default_model": self.default_model,
                "escalation_model": self.escalation_model,
                "invocation_contract_version": UPPER_LAYER_INVOCATION_CONTRACT_VERSION,
            }
        )[:16]
        return f"{key}:route:{route_hash}"

    def _verify_persisted_run_matches_request(
        self,
        run: WritingReferenceUpperLayerStageRun,
        request: UpperLayerExecutionRequest,
        expected_model: str,
    ) -> None:
        expected = {
            "project_id": request.project_id,
            "owner_type": request.owner_type,
            "owner_id": request.owner_id,
            "artifact_id": request.artifact_id,
            "extraction_revision": request.extraction_revision,
            "stage": request.stage,
            "prompt_version": request.prompt_version,
            "deployment_profile": request.deployment_profile,
            "input_hash": _sha256_json(request.input_payload),
            "requested_model": expected_model,
            "provider": self.provider,
            "transport": self.transport,
            "retry_generation": request.retry_generation,
            "retry_parent_stage_run_id": request.retry_parent_stage_run_id,
            "contract_supersession_generation": (
                request.contract_supersession_generation
            ),
            "contract_supersession_transition_version": (
                request.contract_supersession_transition_version
            ),
            "contract_supersession_source_stage_run_id": (
                request.contract_supersession_source_stage_run_id
            ),
            "contract_supersession_source_execution_fingerprint": (
                request.contract_supersession_source_execution_fingerprint
            ),
            "contract_supersession_source_prompt_version": (
                request.contract_supersession_source_prompt_version
            ),
            "contract_supersession_target_prompt_version": (
                request.contract_supersession_target_prompt_version
            ),
        }
        actual = {key: getattr(run, key) for key in expected}
        if actual != expected:
            raise ValueError("persisted upper-layer run does not match request lineage")
