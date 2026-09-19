from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ai_runtime_settings import (
    AiProviderProfile,
    AiRuntimeSettingsStore,
    _atomic_write,
    discover_models,
    runtime_ai_settings_store,
)


ROLE_SETTINGS_SCHEMA_VERSION = "ai_role_bindings_v2"
LEGACY_ROLE_SETTINGS_SCHEMA_VERSION = "ai_role_bindings_v1"
INDEPENDENT_AI_ROLE = "independent_ai"
OCR_ROLE = "ocr"
TRANSLATION_BODY_ROLE = "translation_body"
TRANSLATION_SUPPORT_ROLE = "translation_support"

# Kept as a migration source for pre-v2 files. New bindings never share it.
LOCAL_OMLX_PROFILE_ID = "local_omlx"
OCR_OMLX_PROFILE_ID = "ocr_local_omlx"
OCR_PADDLE_PROFILE_ID = "ocr_paddle_official"
TRANSLATION_BODY_OMLX_PROFILE_ID = "translation_body_local_omlx"
TRANSLATION_SUPPORT_PROFILE_ID = "deepseek_translation_support"
INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID = "independent_ai__deepseek_v4_flash"
DEFAULT_OCR_MODEL = "GLM-OCR-bf16"
PADDLE_OCR_MODEL = "PaddleOCR-VL-1.6"
GATE_TRANSLATION_BODY_MODEL = "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
DEFAULT_TRANSLATION_SUPPORT_MODEL = "deepseek-v4-flash"
THINKING_ENABLED = "enabled"
THINKING_DISABLED = "disabled"
THINKING_MODES: frozenset[str] = frozenset({THINKING_ENABLED, THINKING_DISABLED})
REASONING_EFFORTS: frozenset[str] = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)
THINKING_CONFIGURABLE_ROLES: frozenset[str] = frozenset(
    {INDEPENDENT_AI_ROLE, TRANSLATION_SUPPORT_ROLE}
)

# The gate is deliberately not a model owner. This empty compatibility
# constant prevents older imports from failing while making the new contract
# explicit in code and tests.
GATE_OWNED_ROLES: frozenset[str] = frozenset()

OCR_SPECIALIZED_MODEL_ALLOWLIST: frozenset[str] = frozenset(
    {
        DEFAULT_OCR_MODEL,
        PADDLE_OCR_MODEL,
        "PaddleOCR",
        "models--PaddlePaddle--PaddleOCR-VL-1.6",
    }
)


@dataclass(frozen=True)
class AiRoleDefinition:
    role_id: str
    label: str
    description: str
    recommendation: str
    default_model: str
    requires_local_inventory: bool = False


@dataclass(frozen=True)
class AiRoleBinding:
    role_id: str
    profile_id: str
    model: str
    enabled: bool = True
    thinking: str = THINKING_DISABLED
    reasoning_effort: str = "low"
    capability_status: str = "unverified"
    capability_reason: str = ""
    capability_evidence_profile_id: str = ""
    capability_evidence_model: str = ""
    capability_verified_at: str = ""


class AiRoleBindingUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=2, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    thinking: str = THINKING_DISABLED
    reasoning_effort: str = "low"

    @field_validator("profile_id", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("thinking")
    @classmethod
    def validate_thinking(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in THINKING_MODES:
            raise ValueError("thinking must be enabled or disabled")
        return cleaned

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in REASONING_EFFORTS:
            raise ValueError(
                "reasoning_effort must be low, medium, high, xhigh or max"
            )
        return cleaned


ROLE_DEFINITIONS: tuple[AiRoleDefinition, ...] = (
    AiRoleDefinition(
        role_id=INDEPENDENT_AI_ROLE,
        label="综合AI",
        description="竞品分析、方案设计、候选生成、修订与一致性核查。",
        recommendation="默认使用 DeepSeek V4 Flash（最大推理）；可在获准的私有化模型之间切换。",
        default_model="qwen3.8-max-preview",
    ),
    AiRoleDefinition(
        role_id=OCR_ROLE,
        label="OCR AI",
        description="扫描方案、量表及图表页面的文字与版面识别。",
        recommendation="推荐 PaddleOCR-VL-1.6 官方异步 API 为首选；不可用时回退本机 GLM-OCR。非专用模型须通过真实视觉探针。",
        default_model=PADDLE_OCR_MODEL,
    ),
    AiRoleDefinition(
        role_id=TRANSLATION_BODY_ROLE,
        label="翻译AI",
        description="英文 Protocol/SAP 等文档按章节分块翻译为监管中文。",
        recommendation="普通大模型推荐 1M 上下文高性价比模型如 DeepSeek V4 Flash；专用翻译推荐 Hy-MT2。",
        default_model=GATE_TRANSLATION_BODY_MODEL,
    ),
    AiRoleDefinition(
        role_id=TRANSLATION_SUPPORT_ROLE,
        label="翻译辅助LLM",
        description="Protocol 分段、chunk 拼接、译后 QC、多 OCR 结果重点一致性核查与语料候选分析。",
        recommendation="推荐 1M 上下文高性价比模型如 DeepSeek V4 Flash；仅做结构与质控，不替代正文翻译AI或OCR原文。",
        default_model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
    ),
)
ROLE_DEFINITION_BY_ID = {item.role_id: item for item in ROLE_DEFINITIONS}


def _normalize_binding(binding: AiRoleBinding) -> AiRoleBinding:
    """Normalize persisted role options while preserving legacy bindings.

    Thinking controls are deliberately limited to the comprehensive LLM and
    translation-support assistant. OCR and body translation keep explicit
    disabled/low values so an accidental legacy field cannot silently alter a
    specialized transport or the shared oMLX gate.
    """

    thinking = str(binding.thinking or THINKING_DISABLED).strip().lower()
    if thinking not in THINKING_MODES:
        thinking = THINKING_DISABLED
    effort = str(binding.reasoning_effort or "low").strip().lower()
    if effort not in REASONING_EFFORTS:
        effort = "low"
    if binding.role_id not in THINKING_CONFIGURABLE_ROLES:
        thinking = THINKING_DISABLED
        effort = "low"
    return replace(binding, thinking=thinking, reasoning_effort=effort)


def default_role_settings_path() -> Path:
    explicit = os.environ.get("WORKBENCH_AI_ROLE_SETTINGS_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return runtime_ai_settings_store().settings_path.parent / "ai_role_bindings.json"


def _builtin_profiles() -> tuple[AiProviderProfile, ...]:
    return (
        AiProviderProfile(
            profile_id=LOCAL_OMLX_PROFILE_ID,
            provider="omlx",
            label="本机 oMLX（兼容旧配置）",
            base_url="http://127.0.0.1:8000/v1",
            model=DEFAULT_OCR_MODEL,
            expected_response_model=DEFAULT_OCR_MODEL,
            deployment_scope="loopback",
            discovery_mode="models_endpoint",
            enabled=True,
        ),
        AiProviderProfile(
            profile_id=OCR_OMLX_PROFILE_ID,
            provider="omlx",
            label="本机 oMLX OCR",
            base_url="http://127.0.0.1:8000/v1",
            model=DEFAULT_OCR_MODEL,
            expected_response_model=DEFAULT_OCR_MODEL,
            deployment_scope="loopback",
            discovery_mode="models_endpoint",
            enabled=True,
        ),
        AiProviderProfile(
            profile_id=OCR_PADDLE_PROFILE_ID,
            provider="paddle_official",
            label="PaddleOCR-VL-1.6 官方异步 API",
            base_url="https://paddleocr.aistudio-app.com",
            model=PADDLE_OCR_MODEL,
            expected_response_model=PADDLE_OCR_MODEL,
            api_key_env="PADDLE_OCR_API_KEY",
            deployment_scope="cloud",
            discovery_mode="manual_plus_probe",
            transport="paddle_async_job",
            enabled=True,
        ),
        AiProviderProfile(
            profile_id=TRANSLATION_BODY_OMLX_PROFILE_ID,
            provider="omlx",
            label="本机 oMLX 翻译",
            base_url="http://127.0.0.1:8000/v1",
            model=GATE_TRANSLATION_BODY_MODEL,
            expected_response_model=GATE_TRANSLATION_BODY_MODEL,
            deployment_scope="loopback",
            discovery_mode="models_endpoint",
            enabled=True,
        ),
        AiProviderProfile(
            profile_id=TRANSLATION_SUPPORT_PROFILE_ID,
            provider="deepseek",
            label="DeepSeek 翻译辅助",
            base_url="https://api.deepseek.com/v1",
            model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
            expected_response_model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
            api_key_env="DEEPSEEK_API_KEY",
            deployment_scope="cloud",
            discovery_mode="models_endpoint",
            enabled=True,
        ),
        AiProviderProfile(
            profile_id=INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID,
            provider="deepseek",
            label="DeepSeek V4 Flash 综合AI",
            base_url="https://api.deepseek.com/v1",
            model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
            expected_response_model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
            api_key_env="DEEPSEEK_API_KEY",
            deployment_scope="cloud",
            discovery_mode="models_endpoint",
            enabled=True,
        ),
    )


_BUILTIN_ROLE_PROFILE_IDS = {
    INDEPENDENT_AI_ROLE: {INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID},
    OCR_ROLE: {OCR_OMLX_PROFILE_ID, OCR_PADDLE_PROFILE_ID},
    TRANSLATION_BODY_ROLE: {TRANSLATION_BODY_OMLX_PROFILE_ID},
    TRANSLATION_SUPPORT_ROLE: {TRANSLATION_SUPPORT_PROFILE_ID},
}


def _role_profile_id(role_id: str, profile_id: str) -> str:
    if profile_id in _BUILTIN_ROLE_PROFILE_IDS.get(role_id, set()):
        return profile_id
    prefix = f"{role_id}__"
    if profile_id.startswith(prefix):
        return profile_id
    return f"{prefix}{profile_id}"[:80]


def _ocr_capability(binding: AiRoleBinding) -> tuple[str, str]:
    if binding.model.strip().casefold() in {
        item.casefold() for item in OCR_SPECIALIZED_MODEL_ALLOWLIST
    }:
        return "specialized_whitelisted", "专用 OCR 模型已进入白名单"
    if (
        binding.capability_status == "visual_probe_passed"
        and binding.capability_evidence_profile_id == binding.profile_id
        and binding.capability_evidence_model == binding.model
        and binding.capability_verified_at
    ):
        return "visual_probe_passed", "已通过真实图像文字识别探针"
    return (
        "blocked_unverified_visual",
        "非专用 OCR 模型尚未通过真实视觉能力探针，当前不可运行",
    )


class AiRoleRuntimeSettingsStore:
    def __init__(
        self,
        settings_path: Path,
        provider_store: AiRuntimeSettingsStore | None = None,
        gate_model_resolver: Any | None = None,
    ):
        self.settings_path = settings_path
        self.provider_store = provider_store or runtime_ai_settings_store()

    def ensure_builtin_profiles(self) -> None:
        profiles = {item.profile_id: item for item in self.provider_store.profiles()}
        legacy_omlx = profiles.get(LOCAL_OMLX_PROFILE_ID)
        deepseek_support = profiles.get(TRANSLATION_SUPPORT_PROFILE_ID)
        for builtin in _builtin_profiles():
            if builtin.profile_id in profiles:
                # The comprehensive and translation-support roles are
                # intentionally separate provider profiles, but may use the
                # same locally stored DeepSeek credential.  Copying the
                # encrypted value during first migration keeps the new
                # role-specific profile ready without exposing the secret or
                # making the browser share a credential record.
                if (
                    builtin.profile_id == INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID
                    and deepseek_support is not None
                    and not self.provider_store.credentials.has(builtin.profile_id)
                ):
                    support_key = self.provider_store.credentials.get(
                        deepseek_support.profile_id
                    )
                    if support_key:
                        self.provider_store.credentials.set(
                            builtin.profile_id, support_key
                        )
                continue
            source = legacy_omlx if legacy_omlx and builtin.provider == "omlx" else None
            if source is not None:
                builtin = replace(
                    builtin,
                    base_url=source.base_url,
                    transport=source.transport,
                    deployment_profile=source.deployment_profile,
                    timeout_seconds=source.timeout_seconds,
                    api_key_env=source.api_key_env,
                    deployment_scope=source.deployment_scope,
                    discovery_mode=source.discovery_mode,
                    enabled=source.enabled,
                )
                api_key = self.provider_store.credentials.get(source.profile_id)
            else:
                api_key = (
                    self.provider_store.credentials.get(
                        deepseek_support.profile_id
                    )
                    if (
                        builtin.profile_id == INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID
                        and deepseek_support is not None
                    )
                    else ""
                )
            self.provider_store.upsert(
                builtin,
                api_key=api_key,
                activate_if_empty=False,
            )

    def _default_bindings(self) -> dict[str, AiRoleBinding]:
        # Paddle is the preferred default for new OCR role settings.
        # An explicit user choice persisted in the settings file is never
        # overwritten — ``load`` returns the persisted binding, and this
        # method only fills in defaults for missing roles.
        ocr_profile_id = OCR_PADDLE_PROFILE_ID
        ocr_model = PADDLE_OCR_MODEL
        return {
            INDEPENDENT_AI_ROLE: AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id=INDEPENDENT_AI_DEEPSEEK_FLASH_PROFILE_ID,
                model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
                enabled=True,
                thinking=THINKING_ENABLED,
                reasoning_effort="max",
            ),
            OCR_ROLE: AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id=ocr_profile_id,
                model=ocr_model,
                enabled=True,
                thinking=THINKING_DISABLED,
                reasoning_effort="low",
            ),
            TRANSLATION_BODY_ROLE: AiRoleBinding(
                role_id=TRANSLATION_BODY_ROLE,
                profile_id=TRANSLATION_BODY_OMLX_PROFILE_ID,
                model=GATE_TRANSLATION_BODY_MODEL,
                enabled=True,
                thinking=THINKING_DISABLED,
                reasoning_effort="low",
            ),
            TRANSLATION_SUPPORT_ROLE: AiRoleBinding(
                role_id=TRANSLATION_SUPPORT_ROLE,
                profile_id=TRANSLATION_SUPPORT_PROFILE_ID,
                model=DEFAULT_TRANSLATION_SUPPORT_MODEL,
                enabled=True,
                thinking=THINKING_ENABLED,
                reasoning_effort="max",
            ),
        }

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": ROLE_SETTINGS_SCHEMA_VERSION,
            "revision": 0,
            "bindings": {
                role_id: asdict(binding)
                for role_id, binding in self._default_bindings().items()
            },
        }

    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return self._empty()
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if payload.get("schema_version") not in {
            ROLE_SETTINGS_SCHEMA_VERSION,
            LEGACY_ROLE_SETTINGS_SCHEMA_VERSION,
        }:
            return self._empty()
        defaults = self._default_bindings()
        bindings = payload.get("bindings", {})
        normalized: dict[str, dict[str, Any]] = {}
        for role_id in ROLE_DEFINITION_BY_ID:
            candidate = bindings.get(role_id)
            try:
                binding = AiRoleBinding(**candidate)
                binding = _normalize_binding(replace(binding, role_id=role_id))
            except (TypeError, ValueError):
                binding = _normalize_binding(defaults[role_id])
            normalized[role_id] = asdict(binding)
        return {
            "schema_version": ROLE_SETTINGS_SCHEMA_VERSION,
            "revision": int(payload.get("revision", 0)),
            "bindings": normalized,
        }

    def save(self, bindings: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        payload = {
            "schema_version": ROLE_SETTINGS_SCHEMA_VERSION,
            "revision": int(current.get("revision", 0)) + 1,
            "bindings": bindings,
        }
        _atomic_write(
            self.settings_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )
        return payload

    def _isolate_binding_profile(self, binding: AiRoleBinding) -> AiRoleBinding:
        if not binding.profile_id:
            return binding
        profile = self.provider_store.profile(binding.profile_id)
        target_id = _role_profile_id(binding.role_id, binding.profile_id)
        if target_id != binding.profile_id or profile.model != binding.model:
            target = replace(
                profile,
                profile_id=target_id,
                label=f"{profile.label} · {ROLE_DEFINITION_BY_ID[binding.role_id].label}",
                model=binding.model,
                expected_response_model=binding.model,
            )
            self.provider_store.upsert(
                target,
                api_key=self.provider_store.credentials.get(profile.profile_id),
                activate_if_empty=False,
            )
            profile = target
        return replace(binding, profile_id=profile.profile_id, model=profile.model)

    def migrate(self) -> dict[str, Any]:
        self.ensure_builtin_profiles()
        payload = self.load()
        normalized: dict[str, dict[str, Any]] = {}
        for role_id, raw in payload["bindings"].items():
            binding = _normalize_binding(AiRoleBinding(**raw))
            try:
                binding = self._isolate_binding_profile(binding)
            except KeyError:
                pass
            if role_id == OCR_ROLE:
                status, reason = _ocr_capability(binding)
                binding = replace(
                    binding,
                    capability_status=status,
                    capability_reason=reason,
                )
            normalized[role_id] = asdict(binding)
        if normalized != payload["bindings"] or payload["schema_version"] != ROLE_SETTINGS_SCHEMA_VERSION:
            payload = self.save(normalized)
        return payload

    def binding(self, role_id: str) -> AiRoleBinding:
        if role_id not in ROLE_DEFINITION_BY_ID:
            raise KeyError(role_id)
        item = self.migrate()["bindings"][role_id]
        return AiRoleBinding(**item)

    def upsert(self, binding: AiRoleBinding) -> dict[str, Any]:
        if binding.role_id not in ROLE_DEFINITION_BY_ID:
            raise KeyError(binding.role_id)
        binding = _normalize_binding(binding)
        self.ensure_builtin_profiles()
        isolated = self._isolate_binding_profile(binding)
        if isolated.role_id == OCR_ROLE:
            try:
                current = self.binding(OCR_ROLE)
            except (KeyError, ValueError):
                current = None
            if (
                current is not None
                and current.profile_id == isolated.profile_id
                and current.model == isolated.model
                and current.capability_status == "visual_probe_passed"
            ):
                isolated = replace(
                    isolated,
                    capability_status=current.capability_status,
                    capability_reason=current.capability_reason,
                    capability_evidence_profile_id=current.capability_evidence_profile_id,
                    capability_evidence_model=current.capability_evidence_model,
                    capability_verified_at=current.capability_verified_at,
                )
            status, reason = _ocr_capability(isolated)
            isolated = replace(
                isolated,
                capability_status=status,
                capability_reason=reason,
            )
        payload = self.load()
        payload["bindings"][binding.role_id] = asdict(isolated)
        if isolated.role_id == INDEPENDENT_AI_ROLE:
            self.provider_store.activate(isolated.profile_id)
        return self.save(payload["bindings"])

    def record_ocr_visual_probe(
        self,
        *,
        profile_id: str,
        model: str,
    ) -> dict[str, Any]:
        binding = self.binding(OCR_ROLE)
        if binding.profile_id != profile_id or binding.model != model:
            raise ValueError("OCR 角色配置已变化，请刷新后重新验证视觉能力")
        if model.strip().casefold() in {
            item.casefold() for item in OCR_SPECIALIZED_MODEL_ALLOWLIST
        }:
            status = "specialized_whitelisted"
            reason = "专用 OCR 模型已进入白名单"
        else:
            status = "visual_probe_passed"
            reason = "已通过真实图像文字识别探针"
        verified = replace(
            binding,
            capability_status=status,
            capability_reason=reason,
            capability_evidence_profile_id=profile_id,
            capability_evidence_model=model,
            capability_verified_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = self.load()
        payload["bindings"][OCR_ROLE] = asdict(verified)
        return self.save(payload["bindings"])

    def sync_independent_from_active(self) -> dict[str, Any]:
        active = self.provider_store.active_profile()
        if active is None:
            return self.migrate()
        return self.upsert(
            AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id=active.profile_id,
                model=active.model,
                enabled=active.enabled,
            )
        )

    def role_env(
        self,
        role_id: str,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        binding = self.binding(role_id)
        profile = self.provider_store.profile(binding.profile_id)
        if not binding.enabled or not profile.enabled:
            raise ValueError(f"{role_id} role or provider profile is disabled")
        if binding.model != profile.model:
            raise ValueError(f"{role_id} binding model does not match provider profile")
        values = self.provider_store.profile_env(profile, base_env)
        values["WORKBENCH_AI_MODEL"] = binding.model
        # The response-model expectation is the profile's calibrated identity
        # (providers may rename served ids — DeepSeek v4-flash now responds as
        # deepseek-flash).  The binding model is the REQUEST name; collapsing
        # the expectation onto it made every frozen-route check fail.
        values["WORKBENCH_AI_EXPECTED_RESPONSE_MODEL"] = (
            profile.expected_response_model or profile.model
        )
        values["WORKBENCH_AI_ROLE"] = role_id
        values["WORKBENCH_AI_THINKING"] = binding.thinking
        values["WORKBENCH_AI_REASONING_EFFORT"] = binding.reasoning_effort
        return values

    def _local_inventory(
        self,
        profiles: dict[str, AiProviderProfile],
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        inventories: dict[str, list[str]] = {}
        errors: dict[str, str] = {}
        for profile_id in {
            binding.profile_id
            for binding in self._bindings().values()
            if binding.profile_id in profiles
            and profiles[binding.profile_id].deployment_scope == "loopback"
        }:
            profile = profiles[profile_id]
            try:
                inventories[profile_id] = discover_models(
                    profile,
                    self.provider_store.credentials.get(profile_id),
                    timeout_seconds=2.0,
                )
            except RuntimeError as exc:
                inventories[profile_id] = []
                errors[profile_id] = str(exc)
        return inventories, errors

    def _bindings(self) -> dict[str, AiRoleBinding]:
        return {
            role_id: AiRoleBinding(**item)
            for role_id, item in self.migrate()["bindings"].items()
        }

    def public_payload(self) -> dict[str, Any]:
        role_payload = self.migrate()
        profiles = {
            item.profile_id: item for item in self.provider_store.profiles()
        }
        inventories, inventory_errors = self._local_inventory(profiles)
        public_roles = []
        for definition in ROLE_DEFINITIONS:
            binding = AiRoleBinding(**role_payload["bindings"][definition.role_id])
            profile = profiles.get(binding.profile_id)
            blocked_reason = ""
            availability = "unverified"
            available_models: list[str] = []
            if profile is None:
                blocked_reason = "所选连接不存在"
                availability = "unavailable"
            else:
                available_models = inventories.get(profile.profile_id, [])
                api_key_configured = self.provider_store.api_key_configured(
                    profile
                )
                if not binding.enabled or not profile.enabled:
                    blocked_reason = "该角色或连接已停用"
                    availability = "unavailable"
                elif definition.role_id == OCR_ROLE and binding.capability_status == "blocked_unverified_visual":
                    blocked_reason = binding.capability_reason
                    availability = "unavailable"
                elif profile.deployment_scope == "loopback":
                    if profile.profile_id in inventory_errors:
                        blocked_reason = "本地服务不可达，无法确认模型库存"
                        availability = "unavailable"
                    elif binding.model not in available_models:
                        blocked_reason = f"所选模型未安装：{binding.model}"
                        availability = "unavailable"
                    else:
                        availability = "available"
                elif profile.api_key_env and not api_key_configured:
                    blocked_reason = "API Key 未配置"
                    availability = "unavailable"
                else:
                    availability = "configured"

            public_roles.append(
                {
                    "role_id": definition.role_id,
                    "label": definition.label,
                    "description": definition.description,
                    "recommendation": definition.recommendation,
                    "default_model": definition.default_model,
                    "requires_local_inventory": definition.requires_local_inventory,
                    "profile_id": binding.profile_id,
                    "model": binding.model,
                    "enabled": binding.enabled,
                    "thinking": binding.thinking,
                    "reasoning_effort": binding.reasoning_effort,
                    "thinking_configurable": definition.role_id in THINKING_CONFIGURABLE_ROLES,
                    "thinking_modes": sorted(THINKING_MODES)
                    if definition.role_id in THINKING_CONFIGURABLE_ROLES
                    else [THINKING_DISABLED],
                    "reasoning_efforts": sorted(REASONING_EFFORTS)
                    if definition.role_id in THINKING_CONFIGURABLE_ROLES
                    else ["low"],
                    "availability": availability,
                    "ready": availability in {"available", "configured"},
                    "blocked_reason": blocked_reason,
                    "available_models": available_models,
                    "gate_owned_model": False,
                    "model_editable": True,
                    "capability_status": binding.capability_status,
                    "capability_reason": binding.capability_reason,
                    "execution_binding_consumed": (
                        availability in {"available", "configured"}
                        and binding.enabled
                        and profile is not None
                        and profile.enabled
                        and binding.model == profile.model
                    ),
                }
            )
        return {
            "role_schema_version": ROLE_SETTINGS_SCHEMA_VERSION,
            "role_revision": role_payload["revision"],
            "roles": public_roles,
            "local_model_inventories": inventories,
            "local_inventory_errors": inventory_errors,
        }


def runtime_ai_role_settings_store() -> AiRoleRuntimeSettingsStore:
    return AiRoleRuntimeSettingsStore(
        default_role_settings_path(),
        runtime_ai_settings_store(),
    )


def combined_ai_settings_payload() -> dict[str, Any]:
    provider_store = runtime_ai_settings_store()
    roles = AiRoleRuntimeSettingsStore(
        default_role_settings_path(),
        provider_store,
    ).public_payload()
    return {
        **provider_store.public_payload(),
        **roles,
    }
