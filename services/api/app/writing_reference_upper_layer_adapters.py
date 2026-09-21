from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping

from .ai_gateway import (
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiProviderRuntimeError,
    AiTaskType,
    configured_ai_provider_from_env,
)
from .ai_runtime_settings import runtime_ai_env
from .chapter_translation_pipeline import (
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_PROMPT_VERSION,
    PRO_UPPER_LAYER_MODEL,
    UPPER_LAYER_DOCUMENT_PLANNING,
    UPPER_LAYER_POST_HY_INTEGRATION_QC,
    ChapterTranslationPipelineError,
    DocumentPlanValidationError,
    DocumentPlannerSegment,
    FlashPlanResult,
    FlashQcResult,
    PersistedUpperLayerStageExecutorAdapter,
    TranslationUnit,
    UpperLayerStageOwner,
    _upper_layer_hash_payload,
    _upper_layer_payload_hash,
    expand_document_plan_segment_ranges,
    extract_draft_map_from_envelope,
    integrate_units_with_flash,
    parse_unit_delimited_output,
)
from .writing_reference import WritingReferenceTranslationService
from .writing_reference_upper_layer_execution import (
    DEFAULT_UPPER_LAYER_MODEL,
    ESCALATED_UPPER_LAYER_MODEL,
    UpperLayerAdapterRequest,
    UpperLayerAdapterResult,
    UpperLayerExecutionRequest,
    WritingReferenceUpperLayerExecutionService,
    UpperLayerTransientError,
)


UPPER_LAYER_DEPLOYMENT_PROFILE_FALLBACK = "disabled"
ALLOWED_UPPER_LAYER_MODELS = frozenset(
    {DEFAULT_UPPER_LAYER_MODEL, ESCALATED_UPPER_LAYER_MODEL}
)
NON_ESCALATABLE_PLANNER_FAILURE_CODES = frozenset(
    {
        "planning_input_not_structured",
        "planning_segment_manifest_missing",
    }
)

DOCUMENT_PLANNING_SYSTEM_PROMPT = (
    "你是临床试验方案文档结构规划器，不是正文翻译器或撰写器。输入是按原文顺序"
    "排列的有界结构段清单。识别文档角色，并把全部结构段划分为连续、无重叠、"
    "无遗漏的章节区间。不得返回或猜测内部段落ID。仅返回JSON对象："
    '{"document_role":"protocol|protocol_with_sap|sap|csr",'
    '"chapters":[{"title":"原文章节标题",'
    '"ich_m11_anchor":"对应锚点或unmapped",'
    '"start_segment_ordinal":1,"end_segment_ordinal":3}]}。'
    "第一章必须从1开始；相邻章节必须首尾连续；最后一章必须覆盖最后一个结构段；"
    "required_top_level_segment_ordinals中的每个序号必须成为章节起点；章节title"
    "必须唯一，章节ID由服务端按顺序和区间生成，无需返回。同一原文章节的连续区间"
    "应合并，不得拆成同名章节。"
)

POST_HY_MT2_QC_SYSTEM_PROMPT = (
    "你是中国临床试验方案译后整合与忠实度QC审核器，不是翻译器、改写器或正文"
    "撰写器。translated_text含按[[CMS_SEG_NNNN]]标记对齐的SOURCE英文原文单元与"
    "DRAFT_ZH Hy-MT2中文草稿；source_text是同组英文原文。逐单元核对章节和分块"
    "衔接、标题层级、编号、项目符号、表格结构、引文、数字、单位、比较符、时间窗、"
    "否定关系、终点层级、动作主体、缩写及给药频次。不得翻译、润色、修订或替换"
    "DRAFT_ZH。integrated_text必须逐字回显全部Hy-MT2中文草稿及原标记，每个标记"
    "恰好一次且顺序不变；不得增加英文原文或说明。发现问题仍原样回显并返回"
    "passed=false和可定位failure_codes；无未解决问题才返回passed=true。仅返回"
    'JSON：{"passed":bool,"failure_codes":[str,...],"integrated_text":str}。'
)


class _DeterministicUpperLayerOutputError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ResponseModelIdentityError(RuntimeError):
    pass


def upper_layer_prompt_resolver(stage: str, prompt_version: str) -> str:
    expected = {
        UPPER_LAYER_DOCUMENT_PLANNING: (
            FLASH_PLANNING_PROMPT_VERSION,
            DOCUMENT_PLANNING_SYSTEM_PROMPT,
        ),
        UPPER_LAYER_POST_HY_INTEGRATION_QC: (
            FLASH_QC_PROMPT_VERSION,
            POST_HY_MT2_QC_SYSTEM_PROMPT,
        ),
    }
    if stage not in expected:
        raise ValueError(f"unsupported upper-layer stage: {stage}")
    expected_version, prompt = expected[stage]
    if prompt_version != expected_version:
        raise ValueError(
            f"upper-layer prompt version mismatch for {stage}: {prompt_version}"
        )
    return prompt


def upper_layer_deployment_profile_from_env(
    env: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if env is None else env
    return (
        str(values.get("WORKBENCH_AI_DEPLOYMENT_PROFILE") or "").strip()
        or UPPER_LAYER_DEPLOYMENT_PROFILE_FALLBACK
    )


def build_production_deepseek_provider_factory(
    *,
    env: Mapping[str, str] | None = None,
    provider_builder: Callable[[dict[str, str]], Any] = configured_ai_provider_from_env,
) -> Callable[[str], Any]:
    """Compatibility factory for historical DeepSeek-specific routes."""
    frozen_env = dict(os.environ if env is None else env)

    def _factory(model: str) -> Any:
        if model not in ALLOWED_UPPER_LAYER_MODELS:
            raise ValueError(f"unsupported upper-layer model: {model}")
        values = dict(frozen_env)
        values["WORKBENCH_AI_PROVIDER"] = "deepseek"
        values["WORKBENCH_AI_TRANSPORT"] = "openai_compatible"
        values["WORKBENCH_AI_MODEL"] = model
        values["WORKBENCH_AI_BASE_URL"] = "https://api.deepseek.com/v1"
        profile = upper_layer_deployment_profile_from_env(values)
        api_key = (
            str(values.get("DEEPSEEK_API_KEY") or "").strip()
            or str(values.get("WORKBENCH_AI_API_KEY") or "").strip()
        )
        if profile not in {
            "local_private_clinical",
            "approved_private_clinical",
            "approved_private_documents",
        }:
            raise UpperLayerTransientError("deepseek_deployment_profile_not_configured")
        if not api_key:
            raise UpperLayerTransientError("deepseek_provider_not_configured")
        provider = provider_builder(values)
        return provider

    return _factory


@dataclass(frozen=True)
class UpperLayerRuntimeRoute:
    provider: str
    transport: str
    model: str
    expected_response_model: str
    deployment_profile: str


def upper_layer_runtime_route_from_env(
    env: Mapping[str, str] | None = None,
) -> UpperLayerRuntimeRoute:
    values = dict(runtime_ai_env() if env is None else env)
    route = UpperLayerRuntimeRoute(
        provider=str(values.get("WORKBENCH_AI_PROVIDER") or "").strip(),
        transport=str(
            values.get("WORKBENCH_AI_TRANSPORT") or "openai_compatible"
        ).strip(),
        model=str(values.get("WORKBENCH_AI_MODEL") or "").strip(),
        expected_response_model=str(
            values.get("WORKBENCH_AI_EXPECTED_RESPONSE_MODEL")
            or values.get("WORKBENCH_AI_MODEL")
            or ""
        ).strip(),
        deployment_profile=upper_layer_deployment_profile_from_env(values),
    )
    if not route.provider or not route.transport or not route.model:
        raise UpperLayerTransientError("product_ai_route_not_configured")
    return route


def build_production_product_ai_provider_factory(
    *,
    env: Mapping[str, str] | None = None,
    provider_builder: Callable[[dict[str, str]], Any] = configured_ai_provider_from_env,
) -> Callable[[str], Any]:
    frozen_env = dict(runtime_ai_env() if env is None else env)
    route = upper_layer_runtime_route_from_env(frozen_env)

    def _factory(model: str) -> Any:
        if model != route.model:
            raise ValueError("upper-layer model differs from active product AI route")
        if route.deployment_profile not in {
            "local_private_clinical",
            "approved_private_clinical",
            "approved_private_documents",
        }:
            raise UpperLayerTransientError(
                "product_ai_deployment_profile_not_configured"
            )
        provider = provider_builder(dict(frozen_env))
        if str(getattr(provider, "provider_name", "") or "") == "disabled":
            raise UpperLayerTransientError("product_ai_provider_not_configured")
        return provider

    return _factory


class RuntimeRoutedWritingReferenceUpperLayerExecutionService:
    """Resolve the selected translation-support route once per stage call."""

    def __init__(
        self,
        repository: Any,
        env_resolver: Callable[[], Mapping[str, str]],
    ) -> None:
        self.repository = repository
        self.env_resolver = env_resolver

    def _snapshot(self) -> tuple[dict[str, str], UpperLayerRuntimeRoute]:
        values = dict(self.env_resolver())
        return values, upper_layer_runtime_route_from_env(values)

    def _service(
        self,
        values: Mapping[str, str],
        route: UpperLayerRuntimeRoute,
    ) -> WritingReferenceUpperLayerExecutionService:
        return WritingReferenceUpperLayerExecutionService(
            self.repository,
            build_production_upper_layer_adapter_factory(
                env=values,
                provider=route.provider,
                transport=route.transport,
            ),
            provider=route.provider,
            transport=route.transport,
            expected_response_model=route.expected_response_model,
            default_model=route.model,
            escalation_model=self._escalation_model(route),
        )

    @staticmethod
    def _escalation_model(route: UpperLayerRuntimeRoute) -> str:
        # The normal translation-support route is deliberately Flash. A failed
        # deterministic integration/QC response must be upgraded to Pro rather
        # than replayed against the same Flash model under an "escalation"
        # label. Non-DeepSeek routes retain their selected model because their
        # provider credentials cannot authorize an implicit cross-provider call.
        if (
            route.provider == "deepseek"
            and route.model == DEFAULT_UPPER_LAYER_MODEL
        ):
            return ESCALATED_UPPER_LAYER_MODEL
        return route.model

    @property
    def provider(self) -> str:
        return self._snapshot()[1].provider

    @property
    def transport(self) -> str:
        return self._snapshot()[1].transport

    @property
    def default_model(self) -> str:
        return self._snapshot()[1].model

    @property
    def expected_response_model(self) -> str:
        return self._snapshot()[1].expected_response_model

    @property
    def escalation_model(self) -> str:
        return self._escalation_model(self._snapshot()[1])

    def configured_capabilities(self):
        values, route = self._snapshot()
        return self._service(values, route).configured_capabilities()

    def execute(self, request: UpperLayerExecutionRequest):
        values, route = self._snapshot()
        return self._service(values, route).execute(request)

    def resume_pending_escalations(self, *, project_id: str | None = None):
        values, route = self._snapshot()
        return self._service(values, route).resume_pending_escalations(
            project_id=project_id
        )


class ProductionPersistedUpperLayerStageExecutorAdapter(
    PersistedUpperLayerStageExecutorAdapter
):
    """Persist through the shared bridge after making private dataclasses JSON-safe."""

    def execute(self, **kwargs: Any):
        normalized = dict(kwargs)
        normalized["input_payload"] = _upper_layer_hash_payload(
            normalized["input_payload"]
        )
        return super().execute(**normalized)


@dataclass(frozen=True)
class _DirectUpperLayerScope:
    owner: UpperLayerStageOwner


_DIRECT_UPPER_LAYER_SCOPE: ContextVar[_DirectUpperLayerScope | None] = ContextVar(
    "writing_reference_direct_upper_layer_scope",
    default=None,
)


class PersistentUpperLayerWritingReferenceTranslationService(
    WritingReferenceTranslationService
):
    """Give the existing direct path a concurrency-safe persisted owner scope."""

    def _generate_with_composite_pipeline(self, **kwargs: Any):
        artifact = kwargs["artifact"]
        span = kwargs["span"]
        scope = _DirectUpperLayerScope(
            owner=UpperLayerStageOwner(
                project_id=str(kwargs["project_id"]),
                owner_type="direct_translation",
                owner_id=str(kwargs["translation_id"]),
                artifact_id=str(artifact.artifact_id),
                extraction_revision=str(span.extraction_revision),
            )
        )
        token = _DIRECT_UPPER_LAYER_SCOPE.set(scope)
        try:
            return super()._generate_with_composite_pipeline(**kwargs)
        finally:
            _DIRECT_UPPER_LAYER_SCOPE.reset(token)


class DirectPersistentUpperLayerCallableBridge:
    """Route the legacy direct callable surface into the persisted stage API.

    ``WritingReferenceTranslationService`` still calls the pipeline's planner
    and QC callable attributes directly. This bridge prevents that historical
    surface from bypassing persistence while batch continues to call the same
    pipeline's explicit stage methods.
    """

    def __init__(self) -> None:
        self.pipeline: Any = None

    def bind(self, pipeline: Any) -> None:
        if self.pipeline is not None and self.pipeline is not pipeline:
            raise RuntimeError("direct upper-layer bridge is already bound")
        self.pipeline = pipeline

    def plan(self, source_text: str, context: dict[str, Any]) -> FlashPlanResult:
        scope = self._scope()
        normalized_context = dict(context)
        # The historical direct caller adds these fields for its own retry.
        # The durable upper-layer service already owns bounded retry/escalation;
        # removing them keeps a replay on the same immutable stage identity.
        normalized_context.pop("planner_attempt", None)
        normalized_context.pop("retry_instruction", None)
        result, _execution = self.pipeline.execute_document_planning_stage(
            source_text,
            normalized_context,
            owner=scope.owner,
            bounded_structural_retry=False,
        )
        return result

    def qc(
        self,
        translated: str,
        source: str,
        correction_note: str = "",
    ) -> FlashQcResult:
        del correction_note
        scope = self._scope()
        target_map = extract_draft_map_from_envelope(translated)
        if not target_map:
            raise ChapterTranslationPipelineError(
                "direct persisted QC received no Hy-MT2 target map"
            )
        expected_ordinals = sorted(target_map)
        source_map, source_errors = parse_unit_delimited_output(
            source,
            expected_ordinals=expected_ordinals,
        )
        if source_errors:
            raise ChapterTranslationPipelineError(
                "direct persisted QC received an invalid source unit map"
            )
        units = tuple(
            TranslationUnit(ordinal=ordinal, text=source_map[ordinal])
            for ordinal in expected_ordinals
        )
        outcome, _execution = self.pipeline.execute_integration_qc_stage(
            units=units,
            target_map=dict(target_map),
            owner=scope.owner,
        )
        if outcome.qc_result is None:
            raise ChapterTranslationPipelineError(
                "direct persisted QC returned no model result"
            )
        return outcome.qc_result

    def _scope(self) -> _DirectUpperLayerScope:
        if self.pipeline is None:
            raise ChapterTranslationPipelineError(
                "direct persisted upper-layer bridge is not bound"
            )
        scope = _DIRECT_UPPER_LAYER_SCOPE.get()
        if scope is None:
            raise ChapterTranslationPipelineError(
                "direct persisted upper-layer owner scope is unavailable"
            )
        return scope


class DeepSeekUpperLayerAdapter:
    """Server-owned product-AI adapter for planning and post-Hy-MT2 QC."""

    def __init__(
        self,
        requested_model: str,
        provider_factory: Callable[[str], Any],
        *,
        expected_provider: str = "deepseek",
        expected_transport: str = "openai_compatible",
        expected_response_model: str = "",
    ) -> None:
        if not requested_model.strip():
            raise ValueError("upper-layer requested model is required")
        self.requested_model = requested_model
        self.provider_factory = provider_factory
        self.expected_provider = expected_provider
        self.expected_transport = expected_transport
        self.expected_response_model = (
            expected_response_model.strip() or requested_model.strip()
        )

    def _thinking_mode(self) -> str:
        return (
            "enabled"
            if self.expected_provider == "alibaba_token_plan"
            else "disabled"
        )

    def invoke(self, request: UpperLayerAdapterRequest) -> UpperLayerAdapterResult:
        if (
            request.provider != self.expected_provider
            or request.transport != self.expected_transport
            or request.requested_model != self.requested_model
        ):
            return self._terminal("server_route_identity_mismatch")
        if request.stage not in {
            UPPER_LAYER_DOCUMENT_PLANNING,
            UPPER_LAYER_POST_HY_INTEGRATION_QC,
        }:
            return self._terminal("unsupported_upper_layer_stage")
        try:
            provider = self.provider_factory(self.requested_model)
            route_error = self._provider_route_error(provider)
            if route_error:
                if route_error == "provider_not_configured":
                    raise UpperLayerTransientError(route_error)
                return self._terminal(route_error)
            if request.stage == UPPER_LAYER_DOCUMENT_PLANNING:
                result = self._invoke_planning(provider, request)
            else:
                result = self._invoke_qc(provider, request)
            return result
        except UpperLayerTransientError:
            raise
        except AiGatewayConfigurationError as exc:
            raise UpperLayerTransientError("product_ai_provider_not_configured") from exc
        except AiProviderRuntimeError as exc:
            return self._classify_provider_runtime_error(
                exc,
                is_escalation=request.is_escalation,
            )
        except _ResponseModelIdentityError:
            # Preserve the provider's observed identity even when the
            # adapter, rather than the generic gateway, detects the mismatch.
            # The call remains terminal/fail-closed; only the audit detail is
            # improved for diagnosis and recovery planning.
            return self._terminal(
                "response_model_mismatch",
                response_model=str(getattr(provider, "response_model", "") or ""),
            )
        except (
            DocumentPlanValidationError,
            _DeterministicUpperLayerOutputError,
        ) as exc:
            code = (
                getattr(exc, "code", "") or "deterministic_upper_layer_output_invalid"
            )
            return self._deterministic_failure(
                code,
                is_escalation=request.is_escalation,
                stage=request.stage,
            )
        except ChapterTranslationPipelineError as exc:
            return self._deterministic_failure(
                self._safe_code(str(exc), "deterministic_upper_layer_output_invalid"),
                is_escalation=request.is_escalation,
                stage=request.stage,
            )
        except (ConnectionError, TimeoutError) as exc:
            raise UpperLayerTransientError("product_ai_provider_transient") from exc
        except Exception:
            return self._terminal("upper_layer_adapter_terminal_error")

    def _provider_route_error(self, provider: Any) -> str:
        provider_name = str(getattr(provider, "provider_name", "") or "")
        model_name = str(getattr(provider, "model_name", "") or "")
        transport = str(getattr(provider, "transport_name", "") or "")
        if provider_name == "disabled" or model_name == "not_configured":
            return "provider_not_configured"
        if provider_name != self.expected_provider:
            return "provider_identity_mismatch"
        if model_name != self.requested_model:
            return "requested_model_identity_mismatch"
        if (
            str(
                getattr(provider, "expected_response_model", "")
                or model_name
            ).strip()
            != self.expected_response_model
        ):
            return "expected_response_model_identity_mismatch"
        if transport != self.expected_transport:
            return "transport_identity_mismatch"
        return ""

    def _invoke_planning(
        self,
        provider: Any,
        request: UpperLayerAdapterRequest,
    ) -> UpperLayerAdapterResult:
        payload = request.input_payload
        if not isinstance(payload, dict):
            raise _DeterministicUpperLayerOutputError("planning_input_not_structured")
        source_text = payload.get("source_text")
        context = payload.get("document_context")
        if not isinstance(source_text, str) or not isinstance(context, dict):
            raise _DeterministicUpperLayerOutputError("planning_input_not_structured")
        segments = self._planner_segments(context.get("_planner_segments"))
        if not segments:
            raise _DeterministicUpperLayerOutputError(
                "planning_segment_manifest_missing"
            )
        public_context = {
            key: value
            for key, value in context.items()
            if not str(key).startswith("_")
            and key not in {"span_ids", "source_span_ids"}
        }
        task_id = (
            f"upper_plan_{request.stage_run_id}_"
            f"a{request.planner_attempt or 1}_c{request.provider_call_index}"
        )
        system_prompt = request.prompt
        if request.retry_instruction:
            system_prompt = (
                f"{system_prompt}\n\n同模型结构纠错重试："
                f"{request.retry_instruction}"
            )
        provider_payload = {
            "task_id": task_id,
            "task_type": AiTaskType.REGULATORY_TRANSLATION_ZH.value,
            "source_text": source_text,
            "document_context": public_context,
            "planner_attempt": request.planner_attempt or 1,
        }
        if request.retry_instruction:
            provider_payload["retry_instruction"] = request.retry_instruction
        output = self._run_provider(
            provider,
            AiPromptEnvelope(
                task_id=task_id,
                task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
                prompt_version=request.prompt_version,
                thinking=self._thinking_mode(),
                system_prompt=system_prompt,
                payload=provider_payload,
            ),
        )
        if not isinstance(output, dict):
            raise _DeterministicUpperLayerOutputError(
                "planner_output_not_structured"
            )
        raw_chapters = output.get("chapters")
        document_role = output.get("document_role")
        if not isinstance(raw_chapters, list) or not raw_chapters:
            raise _DeterministicUpperLayerOutputError("planning_chapters_missing")
        if not isinstance(document_role, str) or document_role.strip() not in {
            "protocol",
            "protocol_with_sap",
            "sap",
            "csr",
        }:
            raise _DeterministicUpperLayerOutputError("planning_document_role_missing")
        chapters = expand_document_plan_segment_ranges(raw_chapters, segments)
        plan = FlashPlanResult(
            chapters=chapters,
            document_role=document_role.strip(),
            plan_prompt_version=request.prompt_version,
            plan_model=request.requested_model,
            plan_input_hash=request.input_hash,
            plan_output_hash=self._hash(
                {"chapters": list(chapters), "document_role": document_role.strip()}
            ),
        )
        return UpperLayerAdapterResult(
            response_model=str(
                getattr(provider, "response_model", "") or request.requested_model
            ),
            status="succeeded",
            output_payload=_upper_layer_hash_payload(plan),
        )

    def _invoke_qc(
        self,
        provider: Any,
        request: UpperLayerAdapterRequest,
    ) -> UpperLayerAdapterResult:
        payload = request.input_payload
        if not isinstance(payload, dict):
            raise _DeterministicUpperLayerOutputError("qc_input_not_structured")
        raw_units = payload.get("units")
        raw_target_map = payload.get("hy_mt2_target_map")
        if not isinstance(raw_units, list) or not isinstance(raw_target_map, dict):
            raise _DeterministicUpperLayerOutputError("qc_input_not_structured")
        units = tuple(
            TranslationUnit(
                ordinal=int(item["ordinal"]),
                text=str(item["source_text"]),
            )
            for item in raw_units
            if isinstance(item, dict) and "ordinal" in item and "source_text" in item
        )
        if any(
            not isinstance(key, str) or not key.isdigit() or not isinstance(value, str)
            for key, value in raw_target_map.items()
        ):
            raise _DeterministicUpperLayerOutputError("qc_target_map_not_canonical")
        target_map = {int(key): value for key, value in raw_target_map.items()}
        unit_ordinals = [unit.ordinal for unit in units]
        if (
            len(units) != len(raw_units)
            or len(set(unit_ordinals)) != len(unit_ordinals)
            or len(target_map) != len(raw_target_map)
            or set(target_map) != set(unit_ordinals)
        ):
            raise _DeterministicUpperLayerOutputError("qc_unit_map_mismatch")
        initial_target_map = dict(target_map)
        actual_target_hash = _upper_layer_payload_hash(
            {
                "hy_mt2_target_map": {
                    str(key): value for key, value in sorted(target_map.items())
                }
            }
        )
        if actual_target_hash != request.hy_mt2_target_map_sha256:
            return self._terminal("hy_mt2_target_map_hash_mismatch")

        def _runner(
            translated: str,
            source: str,
            correction_note: str = "",
        ) -> FlashQcResult:
            semantic_payload = {
                "task_type": AiTaskType.REGULATORY_TRANSLATION_ZH.value,
                "translated_text": translated,
                "source_text": source,
                **({"correction_note": correction_note} if correction_note else {}),
            }
            task_id = (
                f"upper_qc_{request.stage_run_id}_{self._hash(semantic_payload)[:10]}"
            )
            output = self._run_provider(
                provider,
                AiPromptEnvelope(
                    task_id=task_id,
                    task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
                    prompt_version=request.prompt_version,
                    thinking=self._thinking_mode(),
                    system_prompt=request.prompt,
                    payload={"task_id": task_id, **semantic_payload},
                ),
            )
            if not isinstance(output, dict):
                raise _DeterministicUpperLayerOutputError("qc_output_not_structured")
            passed = output.get("passed")
            failure_codes = output.get("failure_codes", [])
            integrated_text = output.get("integrated_text")
            if not isinstance(passed, bool):
                raise _DeterministicUpperLayerOutputError("qc_passed_not_boolean")
            if not isinstance(failure_codes, list):
                raise _DeterministicUpperLayerOutputError("qc_failure_codes_not_list")
            if not isinstance(integrated_text, str):
                raise _DeterministicUpperLayerOutputError(
                    "qc_integrated_text_not_string"
                )
            if passed and not integrated_text.strip():
                raise _DeterministicUpperLayerOutputError(
                    "qc_passed_without_integrated_text"
                )
            output_hash = self._hash(output)
            return FlashQcResult(
                passed=passed,
                failure_codes=tuple(str(code) for code in failure_codes),
                qc_prompt_version=request.prompt_version,
                qc_model=request.requested_model,
                qc_input_hash=self._hash(semantic_payload),
                qc_output_hash=output_hash,
                integrated_text=integrated_text,
                integrated_text_sha256=self._hash(integrated_text),
                notes="persisted upper-layer QC",
            )

        outcome = integrate_units_with_flash(
            _runner,
            units=units,
            target_map=target_map,
        )
        if target_map != initial_target_map:
            return self._terminal("hy_mt2_target_map_changed")
        serialized_outcome = _upper_layer_hash_payload(outcome)
        if outcome.passed and not outcome.fallback_used:
            return UpperLayerAdapterResult(
                response_model=str(
                    getattr(provider, "response_model", "") or request.requested_model
                ),
                status="succeeded",
                output_payload=serialized_outcome,
                preserved_hy_mt2_target_map_sha256=actual_target_hash,
            )
        if request.is_escalation:
            return self._terminal("pro_upper_layer_qc_not_accepted")
        if outcome.passed:
            return UpperLayerAdapterResult(
                response_model=str(
                    getattr(provider, "response_model", "") or request.requested_model
                ),
                status="completed_degraded",
                output_payload=serialized_outcome,
                failure_code="flash_qc_degraded_hy_mt2_preserved",
                preserved_hy_mt2_target_map_sha256=actual_target_hash,
            )
        return UpperLayerAdapterResult(
            response_model=str(
                getattr(provider, "response_model", "") or request.requested_model
            ),
            status="failed_escalatable",
            failure_code="flash_qc_deterministic_failure",
        )

    def _classify_provider_runtime_error(
        self,
        exc: AiProviderRuntimeError,
        *,
        is_escalation: bool,
    ) -> UpperLayerAdapterResult:
        message = str(exc).lower()
        if "model identity" in message:
            # Preserve the observed endpoint identity in the immutable stage
            # record.  The gateway already fail-closes the call; collapsing
            # the detail here made a real mismatch indistinguishable from a
            # missing response model during runtime diagnosis.
            actual_match = re.search(r"actual=([^,\\s)]+)", message)
            observed = actual_match.group(1).strip() if actual_match else ""
            return self._terminal(
                "response_model_mismatch",
                response_model=observed,
            )
        if any(
            marker in message
            for marker in (
                "http 400",
                "http 401",
                "http 403",
                "http 404",
            )
        ):
            diagnostics = dict(getattr(exc, "diagnostics", {}) or {})
            status = int(diagnostics.get("http_status") or 0)
            return self._terminal(
                {
                    400: "product_ai_http_400_invalid_request",
                    401: "product_ai_http_401_authentication_failed",
                    403: "product_ai_http_403_forbidden",
                    404: "product_ai_http_404_route_or_model_not_found",
                }.get(status, "product_ai_request_rejected")
            )
        if any(
            marker in message
            for marker in (
                "not valid json",
                "malformed",
                "empty content",
            )
        ):
            return self._deterministic_failure(
                "product_ai_deterministic_response_invalid",
                is_escalation=is_escalation,
            )
        raise UpperLayerTransientError("product_ai_provider_transient") from exc

    def _run_provider(self, provider: Any, envelope: AiPromptEnvelope) -> Any:
        output = provider.run(envelope)
        if (
            str(getattr(provider, "response_model", "") or "")
            != self.expected_response_model
        ):
            raise _ResponseModelIdentityError
        return output

    def _deterministic_failure(
        self,
        code: str,
        *,
        is_escalation: bool,
        stage: str = "",
    ) -> UpperLayerAdapterResult:
        safe_code = self._safe_code(
            code,
            "deterministic_upper_layer_failure",
        )
        if (
            not is_escalation
            and stage == UPPER_LAYER_DOCUMENT_PLANNING
            and safe_code in NON_ESCALATABLE_PLANNER_FAILURE_CODES
        ):
            return self._terminal(safe_code)
        if not is_escalation:
            return UpperLayerAdapterResult(
                response_model=self.requested_model,
                status="failed_escalatable",
                failure_code=safe_code,
            )
        return self._terminal(safe_code)

    def _terminal(
        self,
        code: str,
        *,
        response_model: str | None = None,
    ) -> UpperLayerAdapterResult:
        return UpperLayerAdapterResult(
            response_model=(
                self.requested_model if response_model is None else response_model
            ),
            status="failed_terminal",
            failure_code=self._safe_code(code, "upper_layer_terminal_failure"),
        )

    @staticmethod
    def _planner_segments(value: Any) -> tuple[DocumentPlannerSegment, ...]:
        if not isinstance(value, list):
            return ()
        segments: list[DocumentPlannerSegment] = []
        for item in value:
            if not isinstance(item, dict):
                return ()
            try:
                segments.append(
                    DocumentPlannerSegment(
                        ordinal=int(item["ordinal"]),
                        heading=str(item.get("heading") or ""),
                        ich_m11_anchor=str(item.get("ich_m11_anchor") or "unmapped"),
                        page_start=int(item.get("page_start") or 0),
                        page_end=int(item.get("page_end") or 0),
                        span_count=int(item.get("span_count") or 0),
                        text_sample=str(item.get("text_sample") or ""),
                        source_span_ids=tuple(
                            str(span_id)
                            for span_id in item.get("source_span_ids") or ()
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                return ()
        return tuple(segments)

    @staticmethod
    def _hash(value: Any) -> str:
        if isinstance(value, str):
            encoded = value
        else:
            encoded = json.dumps(
                _upper_layer_hash_payload(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_code(value: str, fallback: str) -> str:
        normalized = "".join(
            char if char.isalnum() or char in {"_", "-", "."} else "_"
            for char in (value or "").strip().lower()
        )
        return normalized[:120] or fallback


def build_production_upper_layer_adapter_factory(
    *,
    env: Mapping[str, str] | None = None,
    provider_factory: Callable[[str], Any] | None = None,
    provider: str = "deepseek",
    transport: str = "openai_compatible",
) -> Callable[[str], DeepSeekUpperLayerAdapter]:
    effective_provider_factory = provider_factory or (
        build_production_product_ai_provider_factory(env=env)
        if env is not None or provider != "deepseek"
        else build_production_deepseek_provider_factory()
    )
    expected_response_model = str(
        (env or {}).get("WORKBENCH_AI_EXPECTED_RESPONSE_MODEL")
        or (env or {}).get("WORKBENCH_AI_MODEL")
        or ""
    ).strip()

    def _factory(model: str) -> DeepSeekUpperLayerAdapter:
        return DeepSeekUpperLayerAdapter(
            model,
            effective_provider_factory,
            expected_provider=provider,
            expected_transport=transport,
            expected_response_model=expected_response_model,
        )

    return _factory
