from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_DEPLOYMENT_PROFILE = "local_private_clinical"
DEFAULT_PROFILE_ID = "independent_ai__mtplx_qwen38_flash_next_speed"
SETTINGS_SCHEMA_VERSION = "ai_provider_registry_v1"
ALIBABA_TOKEN_PLAN_API_KEY_ENV = "ALIBABA_TOKEN_PLAN_CN_API_KEY"
ALIBABA_TOKEN_PLAN_API_KEY_ENV_ALIASES = (
    ALIBABA_TOKEN_PLAN_API_KEY_ENV,
    "ALIBABA_CODING_PLAN_API_KEY",
)


@dataclass(frozen=True)
class AiProviderPreset:
    preset_id: str
    provider: str
    label: str
    base_url: str
    default_model: str
    api_key_env: str
    deployment_scope: str
    discovery_mode: str
    transport: str = "openai_compatible"
    requires_api_key: bool = True
    thinking: str = "enabled"
    reasoning_effort: str = "max"


@dataclass(frozen=True)
class AiProviderProfile:
    profile_id: str
    provider: str
    label: str
    base_url: str
    model: str
    transport: str = "openai_compatible"
    deployment_profile: str = DEFAULT_DEPLOYMENT_PROFILE
    timeout_seconds: float = 300.0
    expected_response_model: str = ""
    api_key_env: str = ""
    deployment_scope: str = "cloud"
    discovery_mode: str = "models_endpoint"
    enabled: bool = True
    revision: int = 1
    thinking: str = "enabled"
    reasoning_effort: str = "max"


@dataclass(frozen=True)
class AiFallbackRoute:
    profile_id: str
    thinking: str = "enabled"
    reasoning_effort: str = "max"


class AiFallbackChainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routes: list[dict[str, str]] = Field(default_factory=list, max_length=2)

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized = []
        seen = set()
        for item in value:
            profile_id = str(item.get("profile_id", "")).strip()
            thinking = str(item.get("thinking", "enabled")).strip().lower()
            effort = str(item.get("reasoning_effort", "max")).strip().lower()
            if not profile_id or profile_id in seen:
                raise ValueError("fallback routes require unique profile_id values")
            if thinking not in {"enabled", "disabled"}:
                raise ValueError("fallback thinking must be enabled or disabled")
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise ValueError("unsupported fallback reasoning_effort")
            seen.add(profile_id)
            normalized.append({
                "profile_id": profile_id,
                "thinking": thinking,
                "reasoning_effort": effort,
            })
        return normalized


class AiProviderProfileUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=2, max_length=80)
    provider: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=2, max_length=120)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    transport: str = "openai_compatible"
    deployment_profile: str = DEFAULT_DEPLOYMENT_PROFILE
    timeout_seconds: float = Field(default=300.0, ge=10.0, le=1800.0)
    expected_response_model: str = ""
    api_key_env: str = ""
    deployment_scope: str = "cloud"
    discovery_mode: str = "models_endpoint"
    enabled: bool = True
    thinking: str = "enabled"
    reasoning_effort: str = "max"
    api_key: Optional[str] = Field(default=None, max_length=4096)
    activate: bool = False

    @field_validator("profile_id", "provider", "transport")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
            for character in cleaned
        ):
            raise ValueError("identifier contains unsupported characters")
        return cleaned

    @field_validator(
        "label",
        "base_url",
        "model",
        "deployment_profile",
        "expected_response_model",
        "api_key_env",
        "deployment_scope",
        "discovery_mode",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("thinking")
    @classmethod
    def validate_thinking(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"enabled", "disabled"}:
            raise ValueError("thinking must be enabled or disabled")
        return cleaned

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported reasoning_effort")
        return cleaned


class AiProviderActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=2, max_length=80)


class AiProviderProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=2, max_length=80)
    model: str = Field(default="", max_length=160)

    @field_validator("model")
    @classmethod
    def strip_model(cls, value: str) -> str:
        return value.strip()


PROVIDER_PRESETS: tuple[AiProviderPreset, ...] = (
    AiProviderPreset(
        preset_id="alibaba_token_plan",
        provider="alibaba_token_plan",
        label="阿里云 Token Plan",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.8-max-preview",
        api_key_env=ALIBABA_TOKEN_PLAN_API_KEY_ENV,
        deployment_scope="cloud",
        discovery_mode="manual_plus_probe",
    ),
    AiProviderPreset(
        preset_id="opencode_go",
        provider="opencode-go",
        label="OpenCode Go",
        base_url="https://opencode.ai/zen/go/v1",
        default_model="deepseek-v4.1-flash",
        api_key_env="OPENCODE_API_KEY",
        deployment_scope="cloud",
        discovery_mode="manual_plus_probe",
    ),
    AiProviderPreset(
        preset_id="cms_router",
        provider="cms-router",
        label="CMS Router / OmniRoute",
        base_url="http://127.0.0.1:20128/v1",
        default_model="deepseek-latest-cloud",
        api_key_env="CMS_ROUTER_API_KEY",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
    ),
    AiProviderPreset(
        preset_id="mtplx",
        provider="mtplx",
        label="MTPLX 本地模型",
        base_url="http://127.0.0.1:11234/v1",
        default_model="Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
        requires_api_key=False,
        reasoning_effort="medium",
    ),
    AiProviderPreset(
        preset_id="deepseek",
        provider="deepseek",
        label="DeepSeek 官方 API",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        deployment_scope="cloud",
        discovery_mode="models_endpoint",
    ),
    AiProviderPreset(
        preset_id="kimi",
        provider="kimi",
        label="Kimi 官方 API",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k3",
        api_key_env="MOONSHOT_API_KEY",
        deployment_scope="cloud",
        discovery_mode="models_endpoint",
    ),
    AiProviderPreset(
        preset_id="bigmodel",
        provider="bigmodel",
        label="智谱 BigModel 官方 API",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.5",
        api_key_env="ZHIPU_API_KEY",
        deployment_scope="cloud",
        discovery_mode="manual_plus_probe",
    ),
    AiProviderPreset(
        preset_id="ollama",
        provider="ollama",
        label="Ollama 本地服务",
        base_url="http://127.0.0.1:11434/v1",
        default_model="",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="ollama_tags",
        requires_api_key=False,
    ),
    AiProviderPreset(
        preset_id="llama_cpp",
        provider="llama_cpp",
        label="llama.cpp Server",
        base_url="http://127.0.0.1:8080/v1",
        default_model="",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
        requires_api_key=False,
    ),
    AiProviderPreset(
        preset_id="vllm",
        provider="vllm",
        label="vLLM OpenAI Server",
        base_url="http://127.0.0.1:8000/v1",
        default_model="",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
        requires_api_key=False,
    ),
    AiProviderPreset(
        preset_id="omlx",
        provider="omlx",
        label="oMLX 本地服务",
        base_url="http://127.0.0.1:8000/v1",
        default_model="",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
        requires_api_key=False,
    ),
    AiProviderPreset(
        preset_id="vmlx",
        provider="vmlx",
        label="vMLX 本地服务",
        base_url="http://127.0.0.1:8000/v1",
        default_model="",
        api_key_env="",
        deployment_scope="loopback",
        discovery_mode="models_endpoint",
        requires_api_key=False,
    ),
    AiProviderPreset(
        preset_id="openai_compatible",
        provider="openai_compatible",
        label="自定义 OpenAI-compatible",
        base_url="",
        default_model="",
        api_key_env="WORKBENCH_AI_API_KEY",
        deployment_scope="custom",
        discovery_mode="models_endpoint",
    ),
    AiProviderPreset(
        preset_id="paddle_official",
        provider="paddle_official",
        label="PaddleOCR-VL-1.6 官方异步 API",
        base_url="https://paddleocr.aistudio-app.com",
        default_model="PaddleOCR-VL-1.6",
        api_key_env="PADDLE_OCR_API_KEY",
        deployment_scope="cloud",
        discovery_mode="manual_plus_probe",
        transport="paddle_async_job",
    ),
)


def provider_presets() -> list[dict[str, Any]]:
    return [asdict(item) for item in PROVIDER_PRESETS]


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class LocalCredentialStore:
    """Small local credential envelope for the single-machine deployment.

    The browser never receives credentials. The encryption key and ciphertext
    are separate 0600 files so a later private deployment can replace this
    adapter with its platform secret manager without changing provider records.
    """

    def __init__(self, root: Path):
        self.key_path = root / "ai_provider_master.key"
        self.secret_path = root / "ai_provider_secrets.json"

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            _atomic_write(self.key_path, Fernet.generate_key().decode("ascii"))
        key = self.key_path.read_text(encoding="utf-8").strip().encode("ascii")
        return Fernet(key)

    def _load(self) -> dict[str, str]:
        if not self.secret_path.exists():
            return {}
        try:
            payload = json.loads(self.secret_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def has(self, profile_id: str) -> bool:
        return bool(self.get(profile_id))

    def get(self, profile_id: str) -> str:
        token = self._load().get(profile_id, "")
        if not token:
            return ""
        try:
            return self._fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            return ""

    def set(self, profile_id: str, value: str) -> None:
        secrets = self._load()
        if value:
            secrets[profile_id] = (
                self._fernet().encrypt(value.encode("utf-8")).decode("ascii")
            )
        else:
            secrets.pop(profile_id, None)
        _atomic_write(
            self.secret_path,
            json.dumps(secrets, ensure_ascii=False, indent=2, sort_keys=True),
        )


class AiRuntimeSettingsStore:
    def __init__(self, settings_path: Path):
        self.settings_path = settings_path
        self.credentials = LocalCredentialStore(settings_path.parent)

    @staticmethod
    def api_key_env_names(profile: AiProviderProfile) -> tuple[str, ...]:
        names = [profile.api_key_env]
        if profile.provider == "alibaba_token_plan":
            names.extend(ALIBABA_TOKEN_PLAN_API_KEY_ENV_ALIASES)
        return tuple(dict.fromkeys(name for name in names if name))

    def api_key_configured(
        self,
        profile: AiProviderProfile,
        values: Dict[str, str] | None = None,
    ) -> bool:
        environment = os.environ if values is None else values
        return self.credentials.has(profile.profile_id) or any(
            bool(environment.get(name, "").strip())
            for name in self.api_key_env_names(profile)
        )

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "active_profile_id": "",
            "revision": 0,
            "profiles": [],
            "fallback_chain": [
                asdict(
                    AiFallbackRoute(
                        profile_id="independent_ai__opencode_go_deepseek_v41_flash",
                        reasoning_effort="max",
                    )
                ),
                asdict(
                    AiFallbackRoute(
                        profile_id="independent_ai__cms_router_deepseek_latest_cloud",
                        reasoning_effort="max",
                    )
                ),
            ],
        }

    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return self._empty()
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if payload.get("schema_version") != SETTINGS_SCHEMA_VERSION:
            return self._empty()
        payload.setdefault("profiles", [])
        payload.setdefault("active_profile_id", "")
        payload.setdefault("revision", 0)
        payload.setdefault("fallback_chain", [])
        return payload

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        next_payload = {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "active_profile_id": str(payload.get("active_profile_id", "")),
            "revision": int(current.get("revision", 0)) + 1,
            "profiles": list(payload.get("profiles", [])),
            "fallback_chain": list(payload.get("fallback_chain", [])),
        }
        _atomic_write(
            self.settings_path,
            json.dumps(next_payload, ensure_ascii=False, indent=2, sort_keys=True),
        )
        return next_payload

    def profiles(self) -> list[AiProviderProfile]:
        result = []
        for item in self.load().get("profiles", []):
            try:
                result.append(AiProviderProfile(**item))
            except (TypeError, ValueError):
                continue
        return result

    def active_profile(self) -> AiProviderProfile | None:
        payload = self.load()
        active_id = str(payload.get("active_profile_id", ""))
        return next(
            (profile for profile in self.profiles() if profile.profile_id == active_id),
            None,
        )

    def profile(self, profile_id: str) -> AiProviderProfile:
        profile = next(
            (item for item in self.profiles() if item.profile_id == profile_id),
            None,
        )
        if profile is None:
            raise KeyError(profile_id)
        return profile

    def upsert(
        self,
        profile: AiProviderProfile,
        *,
        api_key: str | None = None,
        activate: bool = False,
        activate_if_empty: bool = True,
    ) -> dict[str, Any]:
        payload = self.load()
        existing_payload = next(
            (
                item
                for item in payload.get("profiles", [])
                if item.get("profile_id") == profile.profile_id
            ),
            None,
        )
        existing_profile = None
        if existing_payload is not None:
            try:
                existing_profile = AiProviderProfile(**existing_payload)
            except (TypeError, ValueError):
                existing_profile = None

        if existing_profile is None:
            persisted_profile = replace(profile, revision=1)
        else:
            existing_without_revision = asdict(existing_profile)
            incoming_without_revision = asdict(profile)
            existing_without_revision.pop("revision", None)
            incoming_without_revision.pop("revision", None)
            next_revision = existing_profile.revision
            if incoming_without_revision != existing_without_revision:
                next_revision += 1
            persisted_profile = replace(profile, revision=next_revision)

        profiles = [
            item
            for item in payload.get("profiles", [])
            if item.get("profile_id") != profile.profile_id
        ]
        profiles.append(asdict(persisted_profile))
        payload["profiles"] = profiles
        if activate or (activate_if_empty and not payload.get("active_profile_id")):
            payload["active_profile_id"] = profile.profile_id
        if api_key is not None:
            self.credentials.set(profile.profile_id, api_key.strip())
        return self.save(payload)

    def delete(self, profile_id: str) -> dict[str, Any]:
        payload = self.load()
        profiles = list(payload.get("profiles", []))
        if profile_id not in {
            str(item.get("profile_id", "")) for item in profiles
        }:
            raise KeyError(profile_id)
        payload["profiles"] = [
            item
            for item in profiles
            if str(item.get("profile_id", "")) != profile_id
        ]
        if payload.get("active_profile_id") == profile_id:
            payload["active_profile_id"] = ""
        self.credentials.set(profile_id, "")
        return self.save(payload)

    def activate(self, profile_id: str) -> dict[str, Any]:
        payload = self.load()
        if profile_id not in {
            str(item.get("profile_id", "")) for item in payload.get("profiles", [])
        }:
            raise KeyError(profile_id)
        payload["active_profile_id"] = profile_id
        return self.save(payload)

    def fallback_chain(self) -> list[AiFallbackRoute]:
        routes = []
        for item in self.load().get("fallback_chain", []):
            try:
                routes.append(AiFallbackRoute(**item))
            except (TypeError, ValueError):
                continue
        return routes

    def set_fallback_chain(self, routes: Iterable[AiFallbackRoute]) -> dict[str, Any]:
        payload = self.load()
        normalized = list(routes)
        profile_by_id = {item.profile_id: item for item in self.profiles()}
        active = self.effective_independent_profile()
        seen = set()
        for route in normalized:
            profile = profile_by_id.get(route.profile_id)
            if profile is None or not profile.enabled:
                raise KeyError(route.profile_id)
            if active is not None and route.profile_id == active.profile_id:
                raise ValueError("active profile must not be repeated in fallback chain")
            if route.profile_id in seen:
                raise ValueError("fallback profile IDs must be unique")
            seen.add(route.profile_id)
        payload["fallback_chain"] = [asdict(item) for item in normalized]
        return self.save(payload)

    def public_payload(self) -> dict[str, Any]:
        payload = self.load()
        public_profiles = []
        for item in payload.get("profiles", []):
            profile_id = str(item.get("profile_id", ""))
            profile = dict(item)
            profile_definition = AiProviderProfile(
                **{
                    key: value
                    for key, value in item.items()
                    if key in AiProviderProfile.__dataclass_fields__
                }
            )
            profile["api_key_configured"] = self.api_key_configured(
                profile_definition
            )
            public_profiles.append(profile)
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "active_profile_id": payload.get("active_profile_id", ""),
            "revision": payload.get("revision", 0),
            "profiles": public_profiles,
            "fallback_chain": [asdict(item) for item in self.fallback_chain()],
            "presets": provider_presets(),
        }

    def active_env(self, base_env: Dict[str, str] | None = None) -> dict[str, str]:
        values = dict(os.environ if base_env is None else base_env)
        profile = self.effective_independent_profile()
        if profile is None or not profile.enabled:
            return self._disabled_env(values)
        return self.profile_env(profile, values)

    def effective_independent_profile(self) -> AiProviderProfile | None:
        """Resolve the comprehensive-AI role as the runtime source of truth."""

        active = self.active_profile()
        explicit = os.environ.get("WORKBENCH_AI_ROLE_SETTINGS_PATH", "").strip()
        role_settings_path = (
            Path(explicit).expanduser()
            if explicit
            else self.settings_path.parent / "ai_role_bindings.json"
        )
        if not role_settings_path.exists():
            return active
        try:
            payload = json.loads(role_settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return active
        if payload.get("schema_version") not in {
            "ai_role_bindings_v1",
            "ai_role_bindings_v2",
        }:
            return active
        binding = payload.get("bindings", {}).get("independent_ai")
        if not isinstance(binding, dict):
            return active
        if not bool(binding.get("enabled", True)):
            return None
        profile_id = str(binding.get("profile_id", "")).strip()
        model = str(binding.get("model", "")).strip()
        if not profile_id or not model:
            return None
        try:
            profile = self.profile(profile_id)
        except KeyError:
            return None
        if profile.model != model:
            return None
        return profile

    @staticmethod
    def _disabled_env(values: Dict[str, str]) -> dict[str, str]:
        disabled = dict(values)
        disabled.update(
            {
                "WORKBENCH_AI_PROVIDER": "disabled",
                "WORKBENCH_AI_MODEL": "",
                "WORKBENCH_AI_BASE_URL": "",
                "WORKBENCH_AI_API_KEY": "",
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "disabled",
            }
        )
        return disabled

    def profile_env(
        self,
        profile: AiProviderProfile,
        base_env: Dict[str, str] | None = None,
    ) -> dict[str, str]:
        values = dict(os.environ if base_env is None else base_env)
        api_key = self.credentials.get(profile.profile_id) or next(
            (
                values.get(name, "").strip()
                for name in self.api_key_env_names(profile)
                if name and values.get(name, "").strip()
            ),
            "",
        )
        api_key = api_key or values.get("WORKBENCH_AI_API_KEY", "").strip()
        if not api_key and profile.deployment_scope == "loopback":
            # The generic OpenAI-compatible client requires a non-empty
            # bearer value. Local MTPLX/llama-compatible servers commonly do
            # not authenticate, so use a fixed non-secret transport token.
            api_key = "local-loopback"
        values.update(
            {
                "WORKBENCH_AI_PROVIDER": profile.provider,
                "WORKBENCH_AI_TRANSPORT": profile.transport,
                "WORKBENCH_AI_BASE_URL": profile.base_url,
                "WORKBENCH_AI_MODEL": profile.model,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": profile.deployment_profile,
                "WORKBENCH_AI_TIMEOUT_SECONDS": str(profile.timeout_seconds),
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": (
                    profile.expected_response_model or profile.model
                ),
                "WORKBENCH_AI_API_KEY": api_key,
                "WORKBENCH_AI_THINKING": profile.thinking,
                "WORKBENCH_AI_REASONING_EFFORT": profile.reasoning_effort,
            }
        )
        if profile.api_key_env and api_key:
            values[profile.api_key_env] = api_key
        return values


def default_settings_path() -> Path:
    explicit = os.environ.get("WORKBENCH_AI_SETTINGS_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    project_root = Path(__file__).resolve().parents[5]
    runtime_root = Path(
        os.environ.get("WORKBENCH_RUNTIME_DIR", str(project_root / "runtime"))
    )
    return runtime_root / "ai_provider_settings.json"


def runtime_ai_settings_store() -> AiRuntimeSettingsStore:
    return AiRuntimeSettingsStore(default_settings_path())


def runtime_ai_env(base_env: Dict[str, str] | None = None) -> dict[str, str]:
    return runtime_ai_settings_store().active_env(base_env)


class ModelDiscoveryError(RuntimeError):
    """Model catalog discovery failure with the failing layer preserved.

    R04: 401/403, 404, other HTTP statuses, transport failures and JSON
    shape problems carry different remediation actions; collapsing them
    into one untyped message hid the actionable difference.  The endpoint
    is echoed without credentials; request bodies never carry clinical
    content.  Subclasses RuntimeError so existing handlers keep working.
    """

    def __init__(
        self, layer: str, endpoint: str, *, status: int | None = None
    ) -> None:
        self.layer = layer
        self.endpoint = endpoint
        self.status = status
        detail = f"model discovery failed at {layer} for {endpoint}"
        if status is not None:
            detail = f"{detail} (HTTP {status})"
        super().__init__(detail)


def _discovery_loopback(endpoint: str) -> bool:
    """True when the endpoint host is a loopback address (R04: no proxy)."""
    try:
        host = (urlparse(endpoint).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "::1", "localhost"}


def discover_models(
    profile: AiProviderProfile,
    api_key: str = "",
    *,
    timeout_seconds: float = 10.0,
) -> list[str]:
    if profile.discovery_mode == "manual_plus_probe":
        return [profile.model] if profile.model else []
    if profile.discovery_mode == "ollama_tags":
        endpoint = profile.base_url.rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = endpoint[:-3]
        endpoint = f"{endpoint}/api/tags"
    else:
        endpoint = f"{profile.base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # R04: loopback discovery must bypass system/env proxies; cloud
    # endpoints keep the default opener policy.
    opener: urllib.request.OpenerDirector = urllib.request.build_opener()
    if _discovery_loopback(endpoint):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        layer = {
            401: "auth_required",
            403: "auth_required",
            404: "path_not_found",
        }.get(exc.code, f"http_{exc.code}")
        raise ModelDiscoveryError(layer, endpoint, status=exc.code) from None
    except (OSError, urllib.error.URLError) as exc:
        raise ModelDiscoveryError("transport_error", endpoint) from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ModelDiscoveryError("invalid_json", endpoint) from exc
    if not isinstance(payload, dict):
        raise ModelDiscoveryError("invalid_schema", endpoint)
    if profile.discovery_mode == "ollama_tags":
        candidates: Iterable[Any] = payload.get("models", [])
        return sorted(
            {
                str(item.get("name") or item.get("model"))
                for item in candidates
                if isinstance(item, dict) and (item.get("name") or item.get("model"))
            }
        )
    candidates = payload.get("data", [])
    return sorted(
        {
            str(item.get("id"))
            for item in candidates
            if isinstance(item, dict) and item.get("id")
        }
    )
