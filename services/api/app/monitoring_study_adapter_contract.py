"""Read-only translation from a study config to an adapter-neutral binding.

This module is deliberately not an adapter registry implementation.  It produces
immutable, hash-bound evidence that a future registry *could* consume.  It never
resolves a local path, calls an adapter, writes a registry, or touches runtime data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .monitoring_study_config import (
    CORE_CAPABILITY_IDS,
    StudyCapability,
    StudyCapabilityState,
    StudyMonitoringConfig,
    StudyMonitoringConfigError,
    StudySourceBinding,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRANSLATION_REVISION = "study-adapter-binding-v1"
_ADAPTER_CAPABILITY_MISSING = "adapter_capability_missing"


class StudyAdapterContractError(StudyMonitoringConfigError):
    """Raised when a config/adapter translation cannot be proven safe."""


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StudyAdapterContractError(f"{field} is required")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _required(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise StudyAdapterContractError(f"{field} contains unsupported characters")
    return text


def _sha256(value: Any, field: str) -> str:
    text = _required(value, field).lower()
    if not _SHA256_RE.fullmatch(text):
        raise StudyAdapterContractError(f"{field} must be a lowercase SHA-256")
    return text


def _text_tuple(values: Any, field: str, *, required: bool = False) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise StudyAdapterContractError(f"{field} must be a list")
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    if required and not result:
        raise StudyAdapterContractError(f"{field} must be non-empty")
    return tuple(result)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _source_payload(binding: StudySourceBinding) -> dict[str, str]:
    """Exclude study-local binding id/required flags from registry identity."""
    return {
        "kind": binding.kind.value,
        "registry_ref": binding.registry_ref,
        "source_revision": binding.source_revision,
        "content_sha256": binding.content_sha256,
    }


@dataclass(frozen=True)
class StudyAdapterDescriptor:
    """A declarative adapter identity; it contains no executable adapter object."""

    adapter_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    config_sha256: str
    source_binding_ids: tuple[str, ...]
    supported_capability_ids: tuple[str, ...] = ()
    translation_revision: str = _TRANSLATION_REVISION
    read_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(self, "adapter_key", _identifier(self.adapter_key, "adapter_key"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "trial_id", _identifier(self.trial_id, "trial_id"))
        object.__setattr__(self, "config_sha256", _sha256(self.config_sha256, "config_sha256"))
        source_ids = _text_tuple(
            self.source_binding_ids,
            "source_binding_ids",
            required=True,
        )
        if any(not _SAFE_ID_RE.fullmatch(item) for item in source_ids):
            raise StudyAdapterContractError("source_binding_ids contain unsupported characters")
        if len(source_ids) != len(set(source_ids)):
            raise StudyAdapterContractError("source_binding_ids must be unique")
        capability_ids = _text_tuple(
            self.supported_capability_ids,
            "supported_capability_ids",
        )
        unknown = set(capability_ids) - set(CORE_CAPABILITY_IDS)
        if unknown:
            raise StudyAdapterContractError(
                "supported_capability_ids contain unknown capabilities: "
                + ", ".join(sorted(unknown))
            )
        translation_revision = _required(
            self.translation_revision,
            "translation_revision",
        )
        if not _SAFE_ID_RE.fullmatch(translation_revision):
            raise StudyAdapterContractError(
                "translation_revision contains unsupported characters"
            )
        if self.read_only is not True:
            raise StudyAdapterContractError("adapter descriptor must remain read-only")
        object.__setattr__(self, "source_binding_ids", source_ids)
        object.__setattr__(self, "supported_capability_ids", capability_ids)
        object.__setattr__(self, "translation_revision", translation_revision)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_binding_ids"] = list(self.source_binding_ids)
        payload["supported_capability_ids"] = list(self.supported_capability_ids)
        return payload


@dataclass(frozen=True)
class StudySourceRegistrySnapshot:
    """Deterministic, immutable source identities selected by a translation."""

    bindings: tuple[StudySourceBinding, ...]
    registry_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        bindings = tuple(self.bindings)
        if any(not isinstance(item, StudySourceBinding) for item in bindings):
            raise StudyAdapterContractError("registry bindings must be source binding objects")
        by_ref: dict[str, StudySourceBinding] = {}
        for binding in bindings:
            previous = by_ref.get(binding.registry_ref)
            previous_identity = (
                previous.kind.value,
                previous.source_revision,
                previous.content_sha256,
            ) if previous is not None else None
            identity = (
                binding.kind.value,
                binding.source_revision,
                binding.content_sha256,
            )
            if previous is not None and previous_identity != identity:
                raise StudyAdapterContractError(
                    "conflicting source registry identities for " + binding.registry_ref
                )
            by_ref[binding.registry_ref] = binding
        ordered = tuple(
            sorted(
                by_ref.values(),
                key=lambda item: (
                    item.registry_ref,
                    item.kind.value,
                    item.source_revision,
                    item.content_sha256,
                ),
            )
        )
        if not ordered:
            raise StudyAdapterContractError("source registry snapshot must not be empty")
        object.__setattr__(self, "bindings", ordered)
        object.__setattr__(self, "registry_sha256", _digest(self._payload()))

    @classmethod
    def from_bindings(
        cls,
        bindings: Iterable[StudySourceBinding],
    ) -> "StudySourceRegistrySnapshot":
        return cls(tuple(bindings))

    def _payload(self) -> dict[str, Any]:
        return {"bindings": [_source_payload(item) for item in self.bindings]}

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "registry_sha256": self.registry_sha256}


def _translated_capabilities(
    config: StudyMonitoringConfig,
    supported_capability_ids: tuple[str, ...],
) -> tuple[StudyCapability, ...]:
    supported = set(supported_capability_ids)
    result: list[StudyCapability] = []
    for capability in config.capabilities:
        if (
            capability.state == StudyCapabilityState.FULL
            and capability.capability_id not in supported
        ):
            result.append(
                StudyCapability(
                    capability_id=capability.capability_id,
                    state=StudyCapabilityState.UNAVAILABLE,
                    limitation_codes=(_ADAPTER_CAPABILITY_MISSING,),
                    evidence_ids=capability.evidence_ids,
                )
            )
        else:
            result.append(capability)
    return tuple(result)


@dataclass(frozen=True)
class StudyAdapterBinding:
    """The read-only result passed to a future adapter registry."""

    adapter_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    config_sha256: str
    source_binding_ids: tuple[str, ...]
    registry: StudySourceRegistrySnapshot
    field_mappings: tuple[Mapping[str, Any], ...]
    treatment_identity: Mapping[str, str]
    capabilities: tuple[StudyCapability, ...]
    translation_revision: str = _TRANSLATION_REVISION
    read_only: bool = True
    binding_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(self, "adapter_key", _identifier(self.adapter_key, "adapter_key"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "trial_id", _identifier(self.trial_id, "trial_id"))
        object.__setattr__(self, "config_sha256", _sha256(self.config_sha256, "config_sha256"))
        source_ids = _text_tuple(
            self.source_binding_ids,
            "source_binding_ids",
            required=True,
        )
        if len(source_ids) != len(set(source_ids)):
            raise StudyAdapterContractError("translated source binding ids must be unique")
        if not isinstance(self.registry, StudySourceRegistrySnapshot):
            raise StudyAdapterContractError("registry must be a source registry snapshot")
        mappings = tuple(self.field_mappings)
        if any(not isinstance(item, Mapping) for item in mappings):
            raise StudyAdapterContractError("field_mappings must contain objects")
        mapping_ids = [str(item.get("mapping_id", "")).strip() for item in mappings]
        if any(not item for item in mapping_ids) or len(mapping_ids) != len(set(mapping_ids)):
            raise StudyAdapterContractError("translated mapping ids must be present and unique")
        if not isinstance(self.treatment_identity, Mapping):
            raise StudyAdapterContractError("treatment_identity must be an object")
        treatment = {
            str(key).strip(): str(value).strip()
            for key, value in self.treatment_identity.items()
        }
        required_roles = {
            "investigational_product_role",
            "concomitant_medication_role",
            "background_treatment_role",
        }
        if not required_roles.issubset(treatment) or any(
            not treatment[key] for key in required_roles
        ):
            raise StudyAdapterContractError(
                "translated treatment identity must declare all treatment roles"
            )
        if len({treatment[key] for key in required_roles}) != len(required_roles):
            raise StudyAdapterContractError("translated treatment identity roles must remain distinct")
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, StudyCapability) for item in capabilities):
            raise StudyAdapterContractError("translated capabilities must be capability objects")
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise StudyAdapterContractError("translated capability ids must be unique")
        missing_capabilities = set(CORE_CAPABILITY_IDS) - {
            item.capability_id for item in capabilities
        }
        if missing_capabilities:
            raise StudyAdapterContractError(
                "translated capabilities must be explicit: "
                + ", ".join(sorted(missing_capabilities))
            )
        translation_revision = _required(
            self.translation_revision,
            "translation_revision",
        )
        if not _SAFE_ID_RE.fullmatch(translation_revision):
            raise StudyAdapterContractError(
                "translation_revision contains unsupported characters"
            )
        if self.read_only is not True:
            raise StudyAdapterContractError("adapter binding must remain read-only")
        object.__setattr__(self, "source_binding_ids", source_ids)
        object.__setattr__(self, "field_mappings", mappings)
        object.__setattr__(self, "treatment_identity", treatment)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "translation_revision", translation_revision)
        object.__setattr__(self, "binding_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "config_sha256": self.config_sha256,
            "source_binding_ids": list(self.source_binding_ids),
            "registry": self.registry.to_dict(),
            "field_mappings": [dict(item) for item in self.field_mappings],
            "treatment_identity": dict(sorted(self.treatment_identity.items())),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "translation_revision": self.translation_revision,
            "read_only": self.read_only,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "binding_sha256": self.binding_sha256}


def translate_study_config_to_adapter_binding(
    config: StudyMonitoringConfig,
    descriptor: StudyAdapterDescriptor,
) -> StudyAdapterBinding:
    """Translate without invoking or registering the described adapter."""
    if not isinstance(config, StudyMonitoringConfig):
        raise StudyAdapterContractError("config must be a StudyMonitoringConfig")
    if not isinstance(descriptor, StudyAdapterDescriptor):
        raise StudyAdapterContractError("descriptor must be a StudyAdapterDescriptor")
    if (descriptor.project_id, descriptor.trial_id) != (config.project_id, config.trial_id):
        raise StudyAdapterContractError("adapter descriptor study identity does not match config")
    if descriptor.config_sha256 != config.config_sha256:
        raise StudyAdapterContractError("adapter descriptor config_sha256 does not match config")

    available = {item.binding_id: item for item in config.source_bindings}
    selected_ids = set(descriptor.source_binding_ids)
    unknown = selected_ids - set(available)
    if unknown:
        raise StudyAdapterContractError(
            "adapter descriptor references unknown source bindings: "
            + ", ".join(sorted(unknown))
        )
    missing_required = {
        item.binding_id
        for item in config.source_bindings
        if item.required and item.binding_id not in selected_ids
    }
    if missing_required:
        raise StudyAdapterContractError(
            "adapter descriptor omits required source bindings: "
            + ", ".join(sorted(missing_required))
        )
    selected = tuple(
        item for item in config.source_bindings if item.binding_id in selected_ids
    )
    registry = StudySourceRegistrySnapshot.from_bindings(selected)
    return StudyAdapterBinding(
        adapter_id=descriptor.adapter_id,
        adapter_key=descriptor.adapter_key,
        project_id=config.project_id,
        trial_id=config.trial_id,
        config_sha256=config.config_sha256,
        source_binding_ids=tuple(sorted(selected_ids)),
        registry=registry,
        field_mappings=tuple(item.to_dict() for item in config.field_mappings),
        treatment_identity=config.treatment_identity.to_dict(),
        capabilities=_translated_capabilities(config, descriptor.supported_capability_ids),
        translation_revision=descriptor.translation_revision,
    )


__all__ = [
    "StudyAdapterBinding",
    "StudyAdapterContractError",
    "StudyAdapterDescriptor",
    "StudySourceRegistrySnapshot",
    "translate_study_config_to_adapter_binding",
]
