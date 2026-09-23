from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Dict, List, Sequence

from packages.contracts.workbench_contracts import (
    AiTaskFromRegistryRequest,
    AiTaskRequest,
    AiTaskSourceRef,
)

from .ai_gateway import (
    ALIBABA_TOKEN_PLAN_BASE_URL,
    ALIBABA_TOKEN_PLAN_MODEL,
    ALIBABA_TOKEN_PLAN_PROVIDER,
    DIRECT_DEEPSEEK_BASE_URL,
    DIRECT_DEEPSEEK_MODEL,
    DIRECT_DEEPSEEK_TRANSLATION_SUPPORT_MODEL,
    DEEPSEEK_COMPATIBLE_GATEWAY_BASE_URLS,
    DEEPSEEK_COMPATIBLE_GATEWAY_MODELS,
    OPENCODE_GO_BASE_URL,
    OPENCODE_GO_MODEL,
    OPENCODE_GO_PROVIDER,
    AiTaskType,
    PROTOCOL_FULL_DRAFT_CONTEXT_REQUIRED_KEYS,
)
from .medical_writing_revision_prompts import MEDICAL_WRITING_REVISION_PROMPT_VERSION
from .ai_runtime_settings import AiRuntimeSettingsStore, runtime_ai_settings_store
from .ai_runtime_settings import AiProviderProfile


class AiExecutionPolicyDenied(ValueError):
    pass


TASK_DEFAULT_MODULE = {
    AiTaskType.DISEASE_BACKGROUND_RESEARCH: "evidence_design",
    AiTaskType.COMPETITIVE_INTELLIGENCE: "evidence_design",
    AiTaskType.PROTOCOL_DESIGN_SYNTHESIS: "evidence_design",
    AiTaskType.PICOS_DESIGN_COACH: "evidence_design",
    AiTaskType.PROTOCOL_RULE_EXTRACTION: "eligibility_review",
    AiTaskType.LISTING_SEMANTIC_MAPPING: "medical_monitoring",
    AiTaskType.MONITORING_RISK_INTERPRETATION: "medical_monitoring",
    AiTaskType.SUBJECT_TIMELINE_DERIVATION: "medical_monitoring",
    AiTaskType.PATIENT_PROFILE_DERIVATION: "medical_monitoring",
    AiTaskType.ELIGIBILITY_RULE_REVIEW: "eligibility_review",
    AiTaskType.TFL_GENERATION_ASSIST: "data_analysis_tfl",
    AiTaskType.ANALYSIS_RESULT_EXPLANATION: "data_analysis_tfl",
    AiTaskType.MEDICAL_WRITING_REVISION: "medical_writing",
    AiTaskType.PROTOCOL_FULL_DRAFT: "medical_writing",
    AiTaskType.DOCUMENT_SECTION_EXTRACTION: "medical_writing",
    AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING: "medical_writing",
    AiTaskType.REGULATORY_TRANSLATION_ZH: "medical_writing",
    AiTaskType.SAFETY_CASE_MEDICAL_REVIEW: "safety_pv",
    AiTaskType.SIGNAL_NARRATIVE_SYNTHESIS: "safety_pv",
}

TASK_ALLOWED_MODULES = {
    task_type: {module} for task_type, module in TASK_DEFAULT_MODULE.items()
}
TASK_ALLOWED_MODULES[AiTaskType.PROTOCOL_RULE_EXTRACTION] = {
    "eligibility_review",
    "medical_monitoring",
}

TASK_ALLOWED_REGISTERED_SOURCE_KINDS = {
    AiTaskType.MEDICAL_WRITING_REVISION: {"protocol_docx_selection"},
}

SERVER_PROMPT_VERSIONS = {
    task_type: f"{task_type.value}_v0_1" for task_type in AiTaskType
}
SERVER_PROMPT_VERSIONS[AiTaskType.MEDICAL_WRITING_REVISION] = (
    MEDICAL_WRITING_REVISION_PROMPT_VERSION
)
SERVER_PROMPT_VERSIONS[AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING] = (
    "protocol_synopsis_structuring_v0_9"
)
SERVER_PROMPT_VERSIONS[AiTaskType.REGULATORY_TRANSLATION_ZH] = (
    "regulatory_translation_zh_v0_5"
)
SERVER_PROMPT_VERSIONS[AiTaskType.PROTOCOL_FULL_DRAFT] = (
    "protocol_full_draft_v0_11"
)

GLOBAL_FORBIDDEN_SOURCE_IDS = {
    "generated_html_reference",
    "legacy_deep_dive_report",
    "previous_ai_summary",
}

TASK_FORBIDDEN_SOURCE_IDS = {
    AiTaskType.MONITORING_RISK_INTERPRETATION: {
        "existing_ae_mh_report",
        "existing_patient_profile_html",
        "existing_subject_timeline_html",
    },
    AiTaskType.SUBJECT_TIMELINE_DERIVATION: {
        "existing_subject_timeline_html",
    },
    AiTaskType.PATIENT_PROFILE_DERIVATION: {
        "existing_patient_profile_html",
    },
}


@dataclass(frozen=True)
class TaskAiRoutePolicy:
    provider_name: str
    transport_name: str
    base_url: str
    allowed_models: frozenset[str]


_DIRECT_DEEPSEEK_PRO_POLICY = TaskAiRoutePolicy(
    provider_name="deepseek",
    transport_name="openai_compatible",
    base_url=DIRECT_DEEPSEEK_BASE_URL,
    allowed_models=frozenset({DIRECT_DEEPSEEK_MODEL}),
)
_DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY = TaskAiRoutePolicy(
    provider_name="deepseek",
    transport_name="openai_compatible",
    base_url=DIRECT_DEEPSEEK_BASE_URL,
    allowed_models=frozenset(
        {DIRECT_DEEPSEEK_TRANSLATION_SUPPORT_MODEL, DIRECT_DEEPSEEK_MODEL}
    ),
)
_LOCAL_DEEPSEEK_COMPATIBLE_POLICY = TaskAiRoutePolicy(
    provider_name="deepseek",
    transport_name="openai_compatible",
    base_url=next(iter(DEEPSEEK_COMPATIBLE_GATEWAY_BASE_URLS)),
    allowed_models=DEEPSEEK_COMPATIBLE_GATEWAY_MODELS,
)
_ALIBABA_QWEN38_POLICY = TaskAiRoutePolicy(
    provider_name=ALIBABA_TOKEN_PLAN_PROVIDER,
    transport_name="openai_compatible",
    base_url=ALIBABA_TOKEN_PLAN_BASE_URL,
    allowed_models=frozenset({ALIBABA_TOKEN_PLAN_MODEL}),
)
_OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY = TaskAiRoutePolicy(
    provider_name=OPENCODE_GO_PROVIDER,
    transport_name="openai_compatible",
    base_url=OPENCODE_GO_BASE_URL,
    allowed_models=frozenset({OPENCODE_GO_MODEL}),
)
_CMS_ROUTER_DEEPSEEK_LATEST_POLICY = TaskAiRoutePolicy(
    provider_name="cms-router",
    transport_name="openai_compatible",
    base_url="http://127.0.0.1:20128/v1",
    allowed_models=frozenset({"deepseek-latest-cloud"}),
)
# Route mirrors the owner's actual MTPLX deployment as discovered on
# 2026-09-23 (LOCAL_ENDPOINT_DISCOVERY_0923V1.json): the server runs on
# 127.0.0.1:8002 and advertises the API id "mtplx-flash-next-optimized-
# speed"; the HF-style directory name is not the served id.
_MTPLX_QWEN38_SPEED_POLICY = TaskAiRoutePolicy(
    provider_name="mtplx",
    transport_name="openai_compatible",
    base_url="http://127.0.0.1:8002/v1",
    allowed_models=frozenset({
        "mtplx-flash-next-optimized-speed",
    }),
)

# Medical-writing semantic tasks accept only explicit product-owned routes.
# The active profile determines the default. MTPLX, OpenCode Go and CMS Router
# are explicit choices and may also be arranged into the fallback chain.
TASK_AI_ROUTE_POLICIES = {
    AiTaskType.MEDICAL_WRITING_REVISION: (
        _MTPLX_QWEN38_SPEED_POLICY,
        _OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY,
        _CMS_ROUTER_DEEPSEEK_LATEST_POLICY,
        _ALIBABA_QWEN38_POLICY,
        _DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY,
        _LOCAL_DEEPSEEK_COMPATIBLE_POLICY,
    ),
    AiTaskType.PROTOCOL_FULL_DRAFT: (
        _MTPLX_QWEN38_SPEED_POLICY,
        _OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY,
        _CMS_ROUTER_DEEPSEEK_LATEST_POLICY,
        _ALIBABA_QWEN38_POLICY,
        _DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY,
        _LOCAL_DEEPSEEK_COMPATIBLE_POLICY,
    ),
    AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING: (
        _MTPLX_QWEN38_SPEED_POLICY,
        _OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY,
        _CMS_ROUTER_DEEPSEEK_LATEST_POLICY,
        _ALIBABA_QWEN38_POLICY,
        _DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY,
    ),
    AiTaskType.DOCUMENT_SECTION_EXTRACTION: (
        _MTPLX_QWEN38_SPEED_POLICY,
        _OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY,
        _CMS_ROUTER_DEEPSEEK_LATEST_POLICY,
        _ALIBABA_QWEN38_POLICY,
        _DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY,
        _LOCAL_DEEPSEEK_COMPATIBLE_POLICY,
    ),
    AiTaskType.REGULATORY_TRANSLATION_ZH: (
        _MTPLX_QWEN38_SPEED_POLICY,
        _OPENCODE_GO_DEEPSEEK_V41_FLASH_POLICY,
        _CMS_ROUTER_DEEPSEEK_LATEST_POLICY,
        _ALIBABA_QWEN38_POLICY,
        _DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY,
    ),
}


@dataclass(frozen=True)
class AiExecutionResolution:
    project_id: str
    module: str
    task_type: AiTaskType
    prompt_version: str
    allowed_sources: List[AiTaskSourceRef]
    forbidden_source_ids: List[str]
    user_instruction: str
    request_origin: str
    data_classification: str
    deployment_profile: str
    policy_decision_id: str
    provider_name: str
    model_name: str
    transport_name: str
    base_url: str
    required_response_model: str
    test_only_provider_injection: bool
    task_context: Dict[str, Any]
    # Frozen independent-AI route identity captured once at policy resolution.
    # Provider construction must consume only these values; a later dynamic
    # route mutation must never alter them.
    route_profile_id: str
    route_profile_revision: int
    route_identity_hash: str
    route_timeout_seconds: float
    route_api_key_env: str
    route_thinking: str = "enabled"
    route_reasoning_effort: str = "max"


class AiExecutionPolicyResolver:
    """Resolve all effective AI settings before a provider can be selected."""

    def __init__(
        self,
        deployment_profile: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        transport_name: str | None = None,
        base_url: str | None = None,
        test_only_provider_injection: bool = False,
    ):
        self._dynamic_runtime = all(
            value is None
            for value in (
                deployment_profile,
                provider_name,
                model_name,
                transport_name,
                base_url,
            )
        )
        self.test_only_provider_injection = bool(test_only_provider_injection)
        if self._dynamic_runtime:
            self._capture_dynamic_route()
            return
        runtime_values = os.environ
        self.deployment_profile = (
            deployment_profile
            if deployment_profile is not None
            else runtime_values.get("WORKBENCH_AI_DEPLOYMENT_PROFILE", "")
        ).strip() or "disabled"
        configured_model = (
            model_name
            if model_name is not None
            else runtime_values.get("WORKBENCH_AI_MODEL", "")
        ).strip()
        configured_provider = (
            provider_name
            if provider_name is not None
            else runtime_values.get("WORKBENCH_AI_PROVIDER", "")
        ).strip()
        self.model_name = configured_model or "not_configured"
        self.provider_name = configured_provider or (
            "openai_compatible" if configured_model else "disabled"
        )
        configured_transport = (
            transport_name
            if transport_name is not None
            else runtime_values.get("WORKBENCH_AI_TRANSPORT", "")
        ).strip()
        configured_base_url = (
            base_url
            if base_url is not None
            else runtime_values.get("WORKBENCH_AI_BASE_URL", "")
        ).strip()
        if self.provider_name == "deepseek" and not configured_base_url:
            configured_base_url = DIRECT_DEEPSEEK_BASE_URL
        self.transport_name = configured_transport or "openai_compatible"
        self.base_url = configured_base_url.rstrip("/")
        # Statically configured resolvers (including test-provider injection)
        # carry no runtime profile identity; the frozen route is exactly the
        # explicit configuration handed to the resolver.
        self.required_response_model = self.model_name
        self.route_profile_id = ""
        self.route_profile_revision = 0
        self.route_timeout_seconds = 300.0
        self.route_api_key_env = ""
        self.route_thinking = "enabled"
        self.route_reasoning_effort = "max"

    def _apply_route_profile(
        self,
        profile: AiProviderProfile,
        values: Dict[str, str],
        *,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Freeze resolver route fields from one settings profile + env overlay."""
        self.deployment_profile = (
            values.get("WORKBENCH_AI_DEPLOYMENT_PROFILE", "").strip()
            or "disabled"
        )
        self.model_name = (
            values.get("WORKBENCH_AI_MODEL", "").strip() or "not_configured"
        )
        self.provider_name = (
            values.get("WORKBENCH_AI_PROVIDER", "").strip()
            or ("openai_compatible" if self.model_name != "not_configured" else "disabled")
        )
        self.transport_name = (
            values.get("WORKBENCH_AI_TRANSPORT", "").strip()
            or "openai_compatible"
        )
        configured_base_url = values.get("WORKBENCH_AI_BASE_URL", "").strip()
        if self.provider_name == "deepseek" and not configured_base_url:
            configured_base_url = DIRECT_DEEPSEEK_BASE_URL
        self.base_url = configured_base_url.rstrip("/")
        self.required_response_model = (
            values.get("WORKBENCH_AI_EXPECTED_RESPONSE_MODEL", "").strip()
            or self.model_name
        )
        self.route_profile_id = profile.profile_id
        self.route_profile_revision = profile.revision
        self.route_timeout_seconds = float(profile.timeout_seconds)
        self.route_api_key_env = profile.api_key_env
        self.route_thinking = thinking or profile.thinking
        self.route_reasoning_effort = reasoning_effort or profile.reasoning_effort

    def _capture_revision_cloud_route(self) -> bool:
        """Owner decision 2026-09-23: revision tasks route to cloud.

        The local MTPLX speed model cannot reliably satisfy the medical-
        writing revision contract (2-4 textually distinct candidates), so
        MEDICAL_WRITING_REVISION resolves its primary route from the first
        enabled cloud profile in the approved fallback chain.  Other tasks
        keep the bound primary (local-first).  Returns True when a cloud
        route was applied; False leaves the bound primary in place.
        """
        store = runtime_ai_settings_store()
        for route in store.fallback_chain():
            try:
                profile = store.profile(route.profile_id)
            except KeyError:
                continue
            if not profile.enabled or profile.deployment_scope != "cloud":
                continue
            self._apply_route_profile(
                profile,
                store.profile_env(profile, dict(os.environ)),
                thinking=route.thinking,
                reasoning_effort=route.reasoning_effort,
            )
            return True
        return False

    def _capture_dynamic_route(self) -> None:
        """Freeze the effective independent-AI route from one settings read.

        ``runtime_ai_env()`` resolves the profile and the env overlay in two
        separate reads, so a binding/profile mutation landing between them
        could tear the route identity. Reading the effective profile once and
        deriving the env overlay from that same object keeps every frozen
        route attribute mutually consistent.
        """
        store = runtime_ai_settings_store()
        profile = store.effective_independent_profile()
        base_values = dict(os.environ)
        if profile is None or not profile.enabled:
            # The disabled overlay mapping is owned by the settings store.
            values = AiRuntimeSettingsStore._disabled_env(base_values)
        else:
            values = store.profile_env(profile, base_values)
        self.deployment_profile = (
            values.get("WORKBENCH_AI_DEPLOYMENT_PROFILE", "").strip()
            or "disabled"
        )
        self.model_name = (
            values.get("WORKBENCH_AI_MODEL", "").strip() or "not_configured"
        )
        self.provider_name = (
            values.get("WORKBENCH_AI_PROVIDER", "").strip()
            or ("openai_compatible" if self.model_name != "not_configured" else "disabled")
        )
        self.transport_name = (
            values.get("WORKBENCH_AI_TRANSPORT", "").strip()
            or "openai_compatible"
        )
        configured_base_url = values.get("WORKBENCH_AI_BASE_URL", "").strip()
        if self.provider_name == "deepseek" and not configured_base_url:
            configured_base_url = DIRECT_DEEPSEEK_BASE_URL
        self.base_url = configured_base_url.rstrip("/")
        self.required_response_model = (
            values.get("WORKBENCH_AI_EXPECTED_RESPONSE_MODEL", "").strip()
            or self.model_name
        )
        self.route_profile_id = profile.profile_id if profile is not None else ""
        self.route_profile_revision = profile.revision if profile is not None else 0
        self.route_timeout_seconds = (
            float(profile.timeout_seconds) if profile is not None else 300.0
        )
        self.route_api_key_env = profile.api_key_env if profile is not None else ""
        self.route_thinking = profile.thinking if profile is not None else "enabled"
        self.route_reasoning_effort = (
            profile.reasoning_effort if profile is not None else "max"
        )

    def _refresh_dynamic_route(self) -> None:
        if not self._dynamic_runtime:
            return
        self._capture_dynamic_route()

    def route_identity_snapshot(
        self,
        *,
        refresh: bool = True,
        task_type: str | None = None,
    ) -> Dict[str, Any]:
        """Return the current complete route identity without credentials.

        Durable callers persist this snapshot and later compare the executing
        ``AiTaskRun.route_identity_hash`` with ``identity_sha256``. They must
        never rebuild a provider from these fields themselves.  Pass the
        task_type so task-scoped routing (revision→cloud) is reflected in
        the submit-time identity.
        """
        if refresh:
            self._refresh_dynamic_route()
        if task_type:
            try:
                if self._task_type(task_type) == AiTaskType.MEDICAL_WRITING_REVISION:
                    self._capture_revision_cloud_route()
            except AiExecutionPolicyDenied:
                pass
        payload = {
            "schema_version": "independent_ai_route_snapshot_v1",
            "role_id": "independent_ai",
            "profile_id": self.route_profile_id,
            "profile_revision": self.route_profile_revision,
            "provider": self.provider_name,
            "model": self.model_name,
            "base_url": self.base_url,
            "transport": self.transport_name,
            "expected_response_model": self.required_response_model,
            "deployment_profile": self.deployment_profile,
        }
        identity_sha256 = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {**payload, "identity_sha256": identity_sha256}

    def _route_identity_hash(self) -> str:
        return str(
            self.route_identity_snapshot(refresh=False)["identity_sha256"]
        )

    def resolve_registered(
        self,
        project_id: str,
        request: AiTaskFromRegistryRequest,
        source_registry,
    ) -> AiExecutionResolution:
        self._refresh_dynamic_route()
        task_type = self._task_type(request.task_type)
        if task_type == AiTaskType.ELIGIBILITY_RULE_REVIEW:
            raise AiExecutionPolicyDenied(
                "eligibility rule review requires the trusted server batch service"
            )
        prompt_version = self._validate_common(
            request.module,
            task_type,
            request.expected_prompt_version,
        )
        task_context = dict(request.task_context)
        if task_type == AiTaskType.MEDICAL_WRITING_REVISION and task_context:
            task_context = self._validate_medical_writing_revision_context(task_context)
        elif task_context:
            raise AiExecutionPolicyDenied(
                "task_context is reserved for trusted task-specific services"
            )
        source_ids = list(request.source_ids)
        if not source_ids:
            raise AiExecutionPolicyDenied("source_ids is required")
        if len(source_ids) != len(set(source_ids)):
            raise AiExecutionPolicyDenied("duplicate source_ids are not allowed")

        try:
            spans = source_registry.store.get_spans(project_id, source_ids)
        except (KeyError, ValueError) as exc:
            raise AiExecutionPolicyDenied(str(exc)) from exc
        entries_by_id = {
            entry.entry_id: entry for entry in source_registry.list_entries(project_id)
        }
        expected_entry_ids = list(request.expected_source_entry_ids)
        if len(expected_entry_ids) != len(set(expected_entry_ids)):
            raise AiExecutionPolicyDenied("duplicate expected_source_entry_ids are not allowed")
        resolved_entry_ids = {span.entry_id for span in spans}
        if task_type == AiTaskType.MEDICAL_WRITING_REVISION and not expected_entry_ids:
            raise AiExecutionPolicyDenied(
                "medical writing revision requires expected_source_entry_ids"
            )
        if expected_entry_ids and resolved_entry_ids != set(expected_entry_ids):
            raise AiExecutionPolicyDenied(
                "registered source entry does not match expected_source_entry_ids"
            )
        classifications = []
        for span in spans:
            if span.project_id != project_id:
                raise AiExecutionPolicyDenied("registered source must belong to the canonical project")
            if span.module != request.module:
                raise AiExecutionPolicyDenied(
                    "registered source must belong to the same module as the AI task"
                )
            entry = entries_by_id.get(span.entry_id)
            if entry is None:
                raise AiExecutionPolicyDenied(
                    f"registered source entry is unavailable for span {span.source_id}"
                )
            allowed_source_kinds = TASK_ALLOWED_REGISTERED_SOURCE_KINDS.get(task_type)
            if allowed_source_kinds is not None and entry.source_kind not in allowed_source_kinds:
                raise AiExecutionPolicyDenied(
                    f"registered source kind {entry.source_kind} is not allowed for {task_type.value}"
                )
            if task_type == AiTaskType.MEDICAL_WRITING_REVISION:
                document_token = str(entry.metadata.get("document_token", ""))
                if not document_token:
                    raise AiExecutionPolicyDenied(
                        "medical writing registered source is missing document version identity"
                    )
                try:
                    latest_entry_id = source_registry.latest_entry_id(
                        project_id,
                        request.module,
                        entry.source_kind,
                        document_token,
                    )
                except KeyError as exc:
                    raise AiExecutionPolicyDenied(str(exc)) from exc
                if entry.entry_id != latest_entry_id:
                    raise AiExecutionPolicyDenied(
                        "stale registered medical writing source is not allowed"
                    )
            classifications.append(self._entry_classification(entry.source_kind))

        data_classification = self._highest_classification(classifications)
        self._enforce_deployment_profile(data_classification)
        self._enforce_task_ai_route_policy(task_type)
        forbidden = self._forbidden_sources(task_type, request.forbidden_source_ids)
        self._deny_selected_forbidden(source_ids, forbidden)
        return AiExecutionResolution(
            project_id=project_id,
            module=request.module,
            task_type=task_type,
            prompt_version=prompt_version,
            allowed_sources=[
                AiTaskSourceRef(
                    source_id=span.source_id,
                    source_type=span.source_type,
                    title=span.title,
                    locator=span.locator,
                    text_preview=span.text_preview,
                    project_id=span.project_id,
                    module=span.module,
                    source_entry_id=span.entry_id,
                )
                for span in spans
            ],
            forbidden_source_ids=forbidden,
            user_instruction=request.user_instruction,
            request_origin="registered_sources",
            data_classification=data_classification,
            deployment_profile=self.deployment_profile,
            policy_decision_id=self._decision_id(
                project_id,
                request.module,
                task_type,
                prompt_version,
                source_ids,
                forbidden,
                data_classification,
                "registered_sources",
                task_context,
            ),
            provider_name=self.provider_name,
            model_name=self.model_name,
            transport_name=self.transport_name,
            base_url=self.base_url,
            required_response_model=self.required_response_model,
            test_only_provider_injection=self.test_only_provider_injection,
            task_context=task_context,
            route_profile_id=self.route_profile_id,
            route_profile_revision=self.route_profile_revision,
            route_identity_hash=self._route_identity_hash(),
            route_timeout_seconds=self.route_timeout_seconds,
            route_api_key_env=self.route_api_key_env,
            route_thinking=self.route_thinking,
            route_reasoning_effort=self.route_reasoning_effort,
        )

    def resolve_internal(
        self,
        project_id: str,
        request: AiTaskRequest,
    ) -> AiExecutionResolution:
        self._refresh_dynamic_route()
        task_type = self._task_type(request.task_type)
        if task_type == AiTaskType.MEDICAL_WRITING_REVISION:
            self._capture_revision_cloud_route()
        prompt_version = self._validate_common(
            request.module,
            task_type,
            request.prompt_version,
        )
        sources = list(request.allowed_sources)
        task_context = dict(request.task_context)
        if task_type == AiTaskType.ELIGIBILITY_RULE_REVIEW:
            task_context = self._validate_eligibility_task_context(task_context)
        elif task_type == AiTaskType.REGULATORY_TRANSLATION_ZH:
            task_context = self._validate_regulatory_translation_context(task_context)
        elif task_type == AiTaskType.PROTOCOL_FULL_DRAFT:
            task_context = self._validate_protocol_full_draft_context(task_context)
        elif task_type == AiTaskType.MEDICAL_WRITING_REVISION and task_context:
            task_context = self._validate_medical_writing_revision_context(task_context)
        elif task_context:
            raise AiExecutionPolicyDenied(
                "task_context is reserved for trusted task-specific services"
            )
        if not sources:
            raise AiExecutionPolicyDenied("trusted internal AI task requires at least one source")
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise AiExecutionPolicyDenied("trusted internal AI source IDs must be unique")
        for source in sources:
            if source.project_id != project_id:
                raise AiExecutionPolicyDenied(
                    "trusted internal source must belong to the canonical project"
                )
            if source.module != request.module:
                raise AiExecutionPolicyDenied(
                    "trusted internal source must belong to the same module as the AI task"
                )
        data_classification = self._highest_classification(
            [self._source_type_classification(source.source_type) for source in sources]
        )
        self._enforce_deployment_profile(data_classification)
        self._enforce_task_ai_route_policy(task_type)
        forbidden = self._forbidden_sources(task_type, request.forbidden_source_ids)
        self._deny_selected_forbidden(source_ids, forbidden)
        return AiExecutionResolution(
            project_id=project_id,
            module=request.module,
            task_type=task_type,
            prompt_version=prompt_version,
            allowed_sources=sources,
            forbidden_source_ids=forbidden,
            user_instruction=request.user_instruction,
            request_origin="trusted_server_source",
            data_classification=data_classification,
            deployment_profile=self.deployment_profile,
            policy_decision_id=self._decision_id(
                project_id,
                request.module,
                task_type,
                prompt_version,
                source_ids,
                forbidden,
                data_classification,
                "trusted_server_source",
                task_context,
            ),
            provider_name=self.provider_name,
            model_name=self.model_name,
            transport_name=self.transport_name,
            base_url=self.base_url,
            required_response_model=self.required_response_model,
            test_only_provider_injection=self.test_only_provider_injection,
            task_context=task_context,
            route_profile_id=self.route_profile_id,
            route_profile_revision=self.route_profile_revision,
            route_identity_hash=self._route_identity_hash(),
            route_timeout_seconds=self.route_timeout_seconds,
            route_api_key_env=self.route_api_key_env,
            route_thinking=self.route_thinking,
            route_reasoning_effort=self.route_reasoning_effort,
        )

    def resolve_internal_for_profile(
        self,
        project_id: str,
        request: AiTaskRequest,
        profile: AiProviderProfile,
    ) -> AiExecutionResolution:
        """Validate the same trusted request against one configured route.

        This is used only after a terminal, eligible provider failure. The
        request, sources, prompt and task context are rebuilt from the
        canonical request; no prior model output is forwarded.
        """
        resolver = AiExecutionPolicyResolver(
            deployment_profile=profile.deployment_profile,
            provider_name=profile.provider,
            model_name=profile.model,
            transport_name=profile.transport,
            base_url=profile.base_url,
        )
        resolution = resolver.resolve_internal(project_id, request)
        identity = {
            "schema_version": "independent_ai_route_snapshot_v1",
            "role_id": "independent_ai",
            "profile_id": profile.profile_id,
            "profile_revision": profile.revision,
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url.rstrip("/"),
            "transport": profile.transport,
            "expected_response_model": profile.expected_response_model or profile.model,
            "deployment_profile": profile.deployment_profile,
        }
        identity_sha256 = sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return replace(
            resolution,
            required_response_model=profile.expected_response_model or profile.model,
            route_profile_id=profile.profile_id,
            route_profile_revision=profile.revision,
            route_identity_hash=identity_sha256,
            route_timeout_seconds=float(profile.timeout_seconds),
            route_api_key_env=profile.api_key_env,
            route_thinking=profile.thinking,
            route_reasoning_effort=profile.reasoning_effort,
        )

    def resolve_registered_for_profile(
        self,
        project_id: str,
        request: Any,
        source_registry: Any,
        profile: AiProviderProfile,
    ) -> AiExecutionResolution:
        """Rebuild a registered request against an explicit fallback route."""
        resolver = AiExecutionPolicyResolver(
            deployment_profile=profile.deployment_profile,
            provider_name=profile.provider,
            model_name=profile.model,
            transport_name=profile.transport,
            base_url=profile.base_url,
        )
        resolution = resolver.resolve_registered(project_id, request, source_registry)
        identity = {
            "schema_version": "independent_ai_route_snapshot_v1",
            "role_id": "independent_ai",
            "profile_id": profile.profile_id,
            "profile_revision": profile.revision,
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url.rstrip("/"),
            "transport": profile.transport,
            "expected_response_model": profile.expected_response_model or profile.model,
            "deployment_profile": profile.deployment_profile,
        }
        identity_sha256 = sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return replace(
            resolution,
            required_response_model=profile.expected_response_model or profile.model,
            route_profile_id=profile.profile_id,
            route_profile_revision=profile.revision,
            route_identity_hash=identity_sha256,
            route_timeout_seconds=float(profile.timeout_seconds),
            route_api_key_env=profile.api_key_env,
            route_thinking=profile.thinking,
            route_reasoning_effort=profile.reasoning_effort,
        )

    def _validate_regulatory_translation_context(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        required = {"glossary_version", "source_span_revision", "document_sha256"}
        if set(context) != required:
            raise AiExecutionPolicyDenied(
                "regulatory translation task_context keys must match the server contract"
            )
        for key in ("glossary_version", "source_span_revision"):
            if not isinstance(context.get(key), str) or not context[key].strip():
                raise AiExecutionPolicyDenied(
                    f"regulatory translation task_context.{key} must be a non-empty string"
                )
        document_sha256 = context.get("document_sha256")
        if (
            not isinstance(document_sha256, str)
            or len(document_sha256) != 64
            or any(character not in "0123456789abcdef" for character in document_sha256)
        ):
            raise AiExecutionPolicyDenied(
                "regulatory translation document_sha256 must be lowercase SHA-256"
            )
        return dict(context)

    def _validate_eligibility_task_context(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        required = {
            "batch_id",
            "subject_token",
            "criterion_kind",
            "criterion_uids",
            "rule_revision",
            "subject_source_revision",
            "packet_digest",
            "allowed_evidence_ids",
        }
        if set(context) != required:
            raise AiExecutionPolicyDenied(
                "eligibility task_context keys must match the server contract"
            )
        for key in (
            "batch_id",
            "subject_token",
            "criterion_kind",
            "rule_revision",
            "subject_source_revision",
            "packet_digest",
        ):
            if not isinstance(context.get(key), str) or not context[key].strip():
                raise AiExecutionPolicyDenied(
                    f"eligibility task_context.{key} must be a non-empty string"
                )
        if context["criterion_kind"] not in {"inclusion", "exclusion"}:
            raise AiExecutionPolicyDenied(
                "eligibility task_context.criterion_kind is invalid"
            )
        criterion_uids = context.get("criterion_uids")
        if (
            not isinstance(criterion_uids, list)
            or not criterion_uids
            or len(criterion_uids) > 8
            or any(not isinstance(value, str) or not value for value in criterion_uids)
            or len(criterion_uids) != len(set(criterion_uids))
        ):
            raise AiExecutionPolicyDenied(
                "eligibility task_context.criterion_uids must contain 1 to 8 unique IDs"
            )
        evidence_ids = context.get("allowed_evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or any(not isinstance(value, str) or not value for value in evidence_ids)
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            raise AiExecutionPolicyDenied(
                "eligibility task_context.allowed_evidence_ids must be unique IDs"
            )
        return context

    def _validate_protocol_full_draft_context(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if set(context) != PROTOCOL_FULL_DRAFT_CONTEXT_REQUIRED_KEYS:
            raise AiExecutionPolicyDenied(
                "protocol full-draft task_context keys must match the server contract"
            )
        for key in ("draft_version", "marker_open", "marker_close"):
            if not isinstance(context.get(key), str) or not context[key]:
                raise AiExecutionPolicyDenied(
                    f"protocol full-draft task_context.{key} must be a non-empty string"
                )
        section_ids = context.get("section_ids")
        if (
            not isinstance(section_ids, list)
            or not section_ids
            or len(section_ids) != len(set(section_ids))
            or not all(isinstance(value, str) and value.strip() for value in section_ids)
        ):
            raise AiExecutionPolicyDenied(
                "protocol full-draft task_context.section_ids must contain unique non-empty strings"
            )
        minimum = context.get("minimum_body_chars")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or not 20 <= minimum <= 2_000:
            raise AiExecutionPolicyDenied(
                "protocol full-draft task_context.minimum_body_chars must be between 20 and 2000"
            )
        if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > 32_768:
            raise AiExecutionPolicyDenied(
                "protocol full-draft task_context exceeds 32 KiB"
            )
        return context

    def _validate_medical_writing_revision_context(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        revision_required = {
            "revision_intent",
            "intent_label",
            "directional_goal",
            "preservation_rules",
            "candidate_count",
            "candidate_blueprints",
        }
        table_required = {
            "context_type",
            "working_copy_id",
            "working_copy_revision",
            "table_version",
            "block_hash",
            "block_id",
            "table_id",
            "row_id",
            "column_id",
            "cell_id",
            "selected_text",
            "source_kind",
            "is_source_linked",
            "table_title",
            "table_domain",
            "row_label",
            "column_label",
            "column_semantic_role",
            "column_window",
            "target_row_window",
            "adjacent_rows",
            "relevant_notes",
        }
        optional_plan_key = "protocol_assembly_plan"
        is_table_context = "context_type" in context
        required = revision_required | (table_required if is_table_context else set())
        if optional_plan_key in context:
            required.add(optional_plan_key)
        if set(context) != required:
            raise AiExecutionPolicyDenied(
                "medical writing revision task_context keys must match the server contract"
            )
        plan_pin = context.get(optional_plan_key)
        if plan_pin is not None:
            if not isinstance(plan_pin, dict) or set(plan_pin) != {
                "plan_id",
                "plan_revision",
                "plan_sha256",
            }:
                raise AiExecutionPolicyDenied(
                    "medical writing revision protocol_assembly_plan must contain exactly "
                    "plan_id, plan_revision, and plan_sha256"
                )
            if (
                not isinstance(plan_pin.get("plan_id"), str)
                or not plan_pin["plan_id"].strip()
                or not isinstance(plan_pin.get("plan_revision"), int)
                or isinstance(plan_pin["plan_revision"], bool)
                or plan_pin["plan_revision"] < 1
                or not isinstance(plan_pin.get("plan_sha256"), str)
                or len(plan_pin["plan_sha256"]) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in plan_pin["plan_sha256"]
                )
            ):
                raise AiExecutionPolicyDenied(
                    "medical writing revision protocol_assembly_plan identity is invalid"
                )
        if context.get("revision_intent") not in {
            "medical_writing_revision",
            "regulatory_tone",
            "consistency_check",
            "evidence_gap",
        }:
            raise AiExecutionPolicyDenied("medical writing revision intent is invalid")
        for key in ("intent_label", "directional_goal"):
            if not isinstance(context.get(key), str) or not context[key].strip():
                raise AiExecutionPolicyDenied(
                    f"medical writing revision task_context.{key} must be a non-empty string"
                )
        count = context.get("candidate_count")
        blueprints = context.get("candidate_blueprints")
        rules = context.get("preservation_rules")
        if not isinstance(count, int) or not 3 <= count <= 5:
            raise AiExecutionPolicyDenied(
                "medical writing revision candidate_count must be between 3 and 5"
            )
        if (
            not isinstance(blueprints, list)
            or len(blueprints) != count
            or not all(isinstance(item, str) and item.strip() for item in blueprints)
        ):
            raise AiExecutionPolicyDenied(
                "medical writing revision candidate_blueprints must match candidate_count"
            )
        if (
            not isinstance(rules, list)
            or not rules
            or not all(isinstance(item, str) and item.strip() for item in rules)
        ):
            raise AiExecutionPolicyDenied(
                "medical writing revision preservation_rules must be a non-empty string array"
            )
        if not is_table_context:
            if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > 32_768:
                raise AiExecutionPolicyDenied(
                    "medical writing revision task_context exceeds 32 KiB"
                )
            return context
        if context.get("context_type") != "working_copy_table_cell":
            raise AiExecutionPolicyDenied(
                "medical writing table task_context.context_type is invalid"
            )
        for key in (
            "working_copy_id",
            "block_id",
            "table_id",
            "row_id",
            "column_id",
            "cell_id",
            "block_hash",
            "source_kind",
        ):
            if not isinstance(context.get(key), str) or not context[key].strip():
                raise AiExecutionPolicyDenied(
                    f"medical writing table task_context.{key} must be a non-empty string"
                )
        if len(context["block_hash"]) != 64 or any(
            char not in "0123456789abcdef" for char in context["block_hash"]
        ):
            raise AiExecutionPolicyDenied(
                "medical writing table task_context.block_hash must be lowercase SHA-256"
            )
        for key in ("working_copy_revision", "table_version"):
            if not isinstance(context.get(key), int) or context[key] < 0:
                raise AiExecutionPolicyDenied(
                    f"medical writing table task_context.{key} must be a nonnegative integer"
                )
        if not isinstance(context.get("is_source_linked"), bool):
            raise AiExecutionPolicyDenied(
                "medical writing table task_context.is_source_linked must be boolean"
            )
        if not isinstance(context.get("column_semantic_role"), str) or len(
            context["column_semantic_role"]
        ) > 120:
            raise AiExecutionPolicyDenied(
                "medical writing table task_context.column_semantic_role must be a bounded string"
            )
        for key in ("column_window", "target_row_window", "adjacent_rows", "relevant_notes"):
            if not isinstance(context.get(key), list):
                raise AiExecutionPolicyDenied(
                    f"medical writing table task_context.{key} must be an array"
                )
        for item in context["column_window"]:
            if not isinstance(item, dict) or set(item) != {
                "column_id",
                "label",
                "semantic_role",
            }:
                raise AiExecutionPolicyDenied(
                    "medical writing table task_context.column_window entries are invalid"
                )
            if not all(isinstance(item[key], str) for key in item):
                raise AiExecutionPolicyDenied(
                    "medical writing table task_context.column_window values must be strings"
                )
        if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > 32_768:
            raise AiExecutionPolicyDenied(
                "medical writing table task_context exceeds 32 KiB"
            )
        return context

    def _task_type(self, value: str) -> AiTaskType:
        try:
            return AiTaskType(value)
        except ValueError as exc:
            raise AiExecutionPolicyDenied(f"unsupported AI task_type: {value}") from exc

    def _validate_common(
        self,
        module: str,
        task_type: AiTaskType,
        expected_prompt_version: str,
    ) -> str:
        if module not in TASK_ALLOWED_MODULES[task_type]:
            raise AiExecutionPolicyDenied(
                f"AI task {task_type.value} is not allowed in module {module}"
            )
        effective_prompt = SERVER_PROMPT_VERSIONS[task_type]
        if expected_prompt_version and expected_prompt_version != effective_prompt:
            raise AiExecutionPolicyDenied(
                f"prompt version mismatch: expected server version {effective_prompt}"
            )
        return effective_prompt

    def _forbidden_sources(
        self,
        task_type: AiTaskType,
        client_exclusions: Sequence[str],
    ) -> List[str]:
        return sorted(
            GLOBAL_FORBIDDEN_SOURCE_IDS
            | TASK_FORBIDDEN_SOURCE_IDS.get(task_type, set())
            | {value for value in client_exclusions if value}
        )

    def _deny_selected_forbidden(
        self,
        source_ids: Sequence[str],
        forbidden_source_ids: Sequence[str],
    ) -> None:
        overlap = sorted(set(source_ids).intersection(forbidden_source_ids))
        if overlap:
            raise AiExecutionPolicyDenied(
                f"source ids cannot be both selected and forbidden: {overlap}"
            )

    def _entry_classification(self, source_kind: str) -> str:
        if source_kind in {
            "listing_file",
            "raw_subject_bundle_inventory",
            "safety_signal_package_inventory",
        }:
            return "sensitive_subject_data"
        return "confidential_clinical_document"

    def _source_type_classification(self, source_type: str) -> str:
        normalized = source_type.lower()
        if any(token in normalized for token in ("listing", "raw_subject", "patient", "safety_case")):
            return "sensitive_subject_data"
        return "confidential_clinical_document"

    def _highest_classification(self, values: Sequence[str]) -> str:
        if "sensitive_subject_data" in values:
            return "sensitive_subject_data"
        return "confidential_clinical_document"

    def _enforce_deployment_profile(self, data_classification: str) -> None:
        clinical_profiles = {"local_private_clinical", "approved_private_clinical"}
        document_profiles = clinical_profiles | {"approved_private_documents"}
        if self.deployment_profile not in document_profiles:
            raise AiExecutionPolicyDenied(
                "AI deployment profile is disabled or unapproved; configure "
                "WORKBENCH_AI_DEPLOYMENT_PROFILE before provider selection"
            )
        if data_classification == "sensitive_subject_data" and self.deployment_profile not in clinical_profiles:
            raise AiExecutionPolicyDenied(
                f"deployment profile {self.deployment_profile} does not allow {data_classification}"
            )

    def _enforce_task_ai_route_policy(self, task_type: AiTaskType) -> None:
        policies = TASK_AI_ROUTE_POLICIES.get(task_type)
        if policies is None or self.test_only_provider_injection:
            return
        for policy in policies:
            if (
                self.provider_name == policy.provider_name
                and self.transport_name == policy.transport_name
                and self.base_url == policy.base_url
                and self.model_name in policy.allowed_models
            ):
                return
        matching_provider_policies = tuple(
            policy for policy in policies if policy.provider_name == self.provider_name
        )
        errors = []
        if not matching_provider_policies:
            errors.append(
                "provider must be one of "
                + ", ".join(sorted({policy.provider_name for policy in policies}))
            )
        else:
            if self.transport_name not in {
                policy.transport_name for policy in matching_provider_policies
            }:
                errors.append("transport must be openai_compatible")
            if self.base_url not in {
                policy.base_url for policy in matching_provider_policies
            }:
                errors.append(
                    "base URL must be one of "
                    + ", ".join(
                        sorted({policy.base_url for policy in matching_provider_policies})
                    )
                )
            allowed_models = {
                model
                for policy in matching_provider_policies
                for model in policy.allowed_models
            }
            if self.model_name not in allowed_models:
                errors.append(
                    "model must be one of " + ", ".join(sorted(allowed_models))
                )
        allowed_routes = "; ".join(
            (
                f"{policy.provider_name} via {policy.transport_name} at "
                f"{policy.base_url} using "
                f"{','.join(sorted(policy.allowed_models))}"
            )
            for policy in policies
        )
        raise AiExecutionPolicyDenied(
            f"AI task {task_type.value} requires a product-owned approved direct "
            f"route: {'; '.join(errors)}; allowed routes: {allowed_routes}"
        )

    def _decision_id(
        self,
        project_id: str,
        module: str,
        task_type: AiTaskType,
        prompt_version: str,
        source_ids: Sequence[str],
        forbidden_source_ids: Sequence[str],
        data_classification: str,
        request_origin: str,
        task_context: Dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "project_id": project_id,
            "module": module,
            "task_type": task_type.value,
            "prompt_version": prompt_version,
            "source_ids": sorted(source_ids),
            "forbidden_source_ids": sorted(forbidden_source_ids),
            "data_classification": data_classification,
            "deployment_profile": self.deployment_profile,
            "request_origin": request_origin,
            "task_context": task_context or {},
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "transport_name": self.transport_name,
            "base_url": self.base_url,
            "required_response_model": self.required_response_model,
            "route_profile_id": self.route_profile_id,
            "route_profile_revision": self.route_profile_revision,
            "route_identity_hash": self._route_identity_hash(),
            "test_only_provider_injection": self.test_only_provider_injection,
        }
        digest = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        return f"policy_{digest}"
