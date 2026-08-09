"""Project-neutral study onboarding contract for medical monitoring.

The contract deliberately refers to source-registry identities rather than local
filesystem paths. It is a validation/serialization boundary only; runtime source
resolution and adapter registration remain separate, controlled work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

from .monitoring_mapping_contract import (
    MonitoringFieldKind,
    validate_monitoring_mapping_semantics,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
_PATH_SEGMENT_RE = re.compile(r"(?:^|[/\\])(?:\.|\.\.)(?:[/\\]|$)")

CORE_CAPABILITY_IDS = (
    "subject_timeline",
    "patient_profile",
    "precise_temporal_rules",
    "lab_ctcae_rules",
    "scale_recalculation",
    "ae_risk_assessment",
    "vitals_risk_assessment",
    "ecg_risk_assessment",
)


class StudyMonitoringConfigError(ValueError):
    """Raised when a project-neutral study configuration is unsafe or incomplete."""


class StudySourceKind(str, Enum):
    LISTING = "listing"
    PROTOCOL = "protocol"
    SUPPLEMENTAL_LISTING = "supplemental_listing"
    DICTIONARY = "dictionary"
    SOURCE_METADATA = "source_metadata"


class StudyCapabilityState(str, Enum):
    FULL = "full"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StudyMonitoringConfigError(f"{field} is required")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _required(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise StudyMonitoringConfigError(f"{field} contains unsupported characters")
    return text


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise StudyMonitoringConfigError(f"{field} must be a lowercase SHA-256")
    return value


def _text_tuple(values: Any, field: str, *, required: bool = False) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise StudyMonitoringConfigError(f"{field} must be a list")
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    if required and not result:
        raise StudyMonitoringConfigError(f"{field} must be non-empty")
    return tuple(result)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping_items(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    """Return object entries while keeping malformed payloads fail-closed."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise StudyMonitoringConfigError(f"{field} must be a list")
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise StudyMonitoringConfigError(f"{field}[{index}] must be an object")
        items.append(item)
    return tuple(items)


@dataclass(frozen=True)
class StudySourceBinding:
    """A versioned source-registry reference, never a local file path."""

    binding_id: str
    kind: StudySourceKind
    registry_ref: str
    source_revision: str
    content_sha256: str
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        if not isinstance(self.kind, StudySourceKind):
            try:
                object.__setattr__(self, "kind", StudySourceKind(self.kind))
            except ValueError as exc:
                raise StudyMonitoringConfigError("kind is invalid") from exc
        registry_ref = _required(self.registry_ref, "registry_ref")
        if _ABSOLUTE_PATH_RE.match(registry_ref) or _PATH_SEGMENT_RE.search(registry_ref):
            raise StudyMonitoringConfigError(
                "registry_ref must be an opaque source-registry reference, not a local path"
            )
        object.__setattr__(self, "registry_ref", registry_ref)
        object.__setattr__(self, "source_revision", _identifier(self.source_revision, "source_revision"))
        object.__setattr__(self, "content_sha256", _sha256(self.content_sha256, "content_sha256"))
        object.__setattr__(self, "required", bool(self.required))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass(frozen=True)
class StudyTreatmentIdentity:
    """Explicit roles keep investigational and non-investigational treatment separate."""

    investigational_product_role: str
    concomitant_medication_role: str
    background_treatment_role: str

    def __post_init__(self) -> None:
        values = {
            "investigational_product_role": _required(
                self.investigational_product_role,
                "investigational_product_role",
            ),
            "concomitant_medication_role": _required(
                self.concomitant_medication_role,
                "concomitant_medication_role",
            ),
            "background_treatment_role": _required(
                self.background_treatment_role,
                "background_treatment_role",
            ),
        }
        if len(set(values.values())) != len(values):
            raise StudyMonitoringConfigError("treatment identity roles must remain distinct")
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class StudyFieldMapping:
    mapping_id: str
    domain: str
    target_field: str
    source_fields: tuple[str, ...]
    recommended_role: str
    field_kind: MonitoringFieldKind
    standards_reference: Mapping[str, Any] | None = None
    derivation_lineage: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_id", _identifier(self.mapping_id, "mapping_id"))
        object.__setattr__(self, "domain", _required(self.domain, "domain"))
        object.__setattr__(self, "target_field", _required(self.target_field, "target_field"))
        object.__setattr__(
            self,
            "source_fields",
            _text_tuple(self.source_fields, "source_fields", required=False),
        )
        object.__setattr__(self, "recommended_role", _required(self.recommended_role, "recommended_role"))
        if not isinstance(self.field_kind, MonitoringFieldKind):
            try:
                object.__setattr__(self, "field_kind", MonitoringFieldKind(self.field_kind))
            except ValueError as exc:
                raise StudyMonitoringConfigError("field_kind is invalid") from exc
        if self.standards_reference is not None and not isinstance(
            self.standards_reference, Mapping
        ):
            raise StudyMonitoringConfigError("standards_reference must be an object")
        if self.derivation_lineage is not None and not isinstance(
            self.derivation_lineage, Mapping
        ):
            raise StudyMonitoringConfigError("derivation_lineage must be an object")
        standards = (
            dict(self.standards_reference)
            if self.standards_reference is not None
            else None
        )
        lineage = (
            dict(self.derivation_lineage)
            if self.derivation_lineage is not None
            else None
        )
        validate_monitoring_mapping_semantics(
            domain=self.domain,
            source_field=self.target_field,
            recommended_role=self.recommended_role,
            field_kind=self.field_kind,
            standards_reference=standards,
            derivation_lineage=lineage,
        )
        object.__setattr__(self, "standards_reference", standards)
        object.__setattr__(self, "derivation_lineage", lineage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "domain": self.domain,
            "target_field": self.target_field,
            "source_fields": list(self.source_fields),
            "recommended_role": self.recommended_role,
            "field_kind": self.field_kind.value,
            "standards_reference": dict(self.standards_reference) if self.standards_reference else None,
            "derivation_lineage": dict(self.derivation_lineage) if self.derivation_lineage else None,
        }


@dataclass(frozen=True)
class StudyCapability:
    capability_id: str
    state: StudyCapabilityState
    limitation_codes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        capability_id = _identifier(self.capability_id, "capability_id")
        if capability_id not in CORE_CAPABILITY_IDS:
            raise StudyMonitoringConfigError(f"unsupported capability_id: {capability_id}")
        object.__setattr__(self, "capability_id", capability_id)
        if not isinstance(self.state, StudyCapabilityState):
            try:
                object.__setattr__(self, "state", StudyCapabilityState(self.state))
            except ValueError as exc:
                raise StudyMonitoringConfigError("capability state is invalid") from exc
        limitations = _text_tuple(self.limitation_codes, "limitation_codes")
        evidence = _text_tuple(self.evidence_ids, "evidence_ids")
        if self.state != StudyCapabilityState.FULL and not limitations:
            raise StudyMonitoringConfigError(
                f"{capability_id} limited/unavailable requires limitation_codes"
            )
        object.__setattr__(self, "limitation_codes", limitations)
        object.__setattr__(self, "evidence_ids", evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "state": self.state.value,
            "limitation_codes": list(self.limitation_codes),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class StudyMonitoringConfig:
    project_id: str
    trial_id: str
    display_label: str
    source_bindings: tuple[StudySourceBinding, ...]
    field_mappings: tuple[StudyFieldMapping, ...]
    treatment_identity: StudyTreatmentIdentity
    capabilities: tuple[StudyCapability, ...]
    protocol_rule_pack_revision: str
    display_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "trial_id", _identifier(self.trial_id, "trial_id"))
        object.__setattr__(self, "display_label", _required(self.display_label, "display_label"))
        object.__setattr__(
            self,
            "protocol_rule_pack_revision",
            _identifier(self.protocol_rule_pack_revision, "protocol_rule_pack_revision"),
        )
        sources = tuple(self.source_bindings)
        mappings = tuple(self.field_mappings)
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, StudySourceBinding) for item in sources):
            raise StudyMonitoringConfigError("source_bindings must contain source binding objects")
        if any(not isinstance(item, StudyFieldMapping) for item in mappings):
            raise StudyMonitoringConfigError("field_mappings must contain mapping objects")
        if any(not isinstance(item, StudyCapability) for item in capabilities):
            raise StudyMonitoringConfigError("capabilities must contain capability objects")
        if not isinstance(self.treatment_identity, StudyTreatmentIdentity):
            raise StudyMonitoringConfigError("treatment_identity must be a treatment identity object")
        if len({item.binding_id for item in sources}) != len(sources):
            raise StudyMonitoringConfigError("source binding ids must be unique")
        if len({item.mapping_id for item in mappings}) != len(mappings):
            raise StudyMonitoringConfigError("mapping ids must be unique")
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise StudyMonitoringConfigError("capability ids must be unique")
        required_kinds = {item.kind for item in sources if item.required}
        if StudySourceKind.LISTING not in required_kinds:
            raise StudyMonitoringConfigError("a required listing source binding is required")
        if StudySourceKind.PROTOCOL not in required_kinds:
            raise StudyMonitoringConfigError("a required protocol source binding is required")
        declared_capabilities = {item.capability_id for item in capabilities}
        missing_capabilities = set(CORE_CAPABILITY_IDS) - declared_capabilities
        if missing_capabilities:
            raise StudyMonitoringConfigError(
                "all core capabilities must be explicit: "
                + ", ".join(sorted(missing_capabilities))
            )
        if not isinstance(self.display_labels, Mapping):
            raise StudyMonitoringConfigError("display_labels must be an object")
        raw_labels = dict(self.display_labels)
        labels = {
            str(key).strip(): str(value).strip()
            for key, value in raw_labels.items()
        }
        if any(not key or not value for key, value in labels.items()):
            raise StudyMonitoringConfigError("display_labels cannot contain blank keys or values")
        object.__setattr__(self, "source_bindings", sources)
        object.__setattr__(self, "field_mappings", mappings)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "display_labels", labels)

    def _payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "display_label": self.display_label,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "field_mappings": [item.to_dict() for item in self.field_mappings],
            "treatment_identity": self.treatment_identity.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "protocol_rule_pack_revision": self.protocol_rule_pack_revision,
            "display_labels": dict(sorted(self.display_labels.items())),
        }

    @property
    def config_sha256(self) -> str:
        return _digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "config_sha256": self.config_sha256}

    def capability(self, capability_id: str) -> StudyCapability:
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise StudyMonitoringConfigError(f"capability is not declared: {capability_id}")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StudyMonitoringConfig":
        if not isinstance(payload, Mapping):
            raise StudyMonitoringConfigError("study config must be an object")
        config = cls(
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            display_label=payload.get("display_label", ""),
            source_bindings=tuple(
                StudySourceBinding(
                    binding_id=item.get("binding_id", ""),
                    kind=item.get("kind", ""),
                    registry_ref=item.get("registry_ref", ""),
                    source_revision=item.get("source_revision", ""),
                    content_sha256=item.get("content_sha256", ""),
                    required=item.get("required", True),
                )
                for item in _mapping_items(payload.get("source_bindings", ()), "source_bindings")
            ),
            field_mappings=tuple(
                StudyFieldMapping(
                    mapping_id=item.get("mapping_id", ""),
                    domain=item.get("domain", ""),
                    target_field=item.get("target_field", ""),
                    source_fields=item.get("source_fields", ()),
                    recommended_role=item.get("recommended_role", ""),
                    field_kind=item.get("field_kind", ""),
                    standards_reference=item.get("standards_reference"),
                    derivation_lineage=item.get("derivation_lineage"),
                )
                for item in _mapping_items(payload.get("field_mappings", ()), "field_mappings")
            ),
            treatment_identity=StudyTreatmentIdentity(
                **dict(payload.get("treatment_identity", {}))
                if isinstance(payload.get("treatment_identity", {}), Mapping)
                else {},
            ),
            capabilities=tuple(
                StudyCapability(
                    capability_id=item.get("capability_id", ""),
                    state=item.get("state", ""),
                    limitation_codes=item.get("limitation_codes", ()),
                    evidence_ids=item.get("evidence_ids", ()),
                )
                for item in _mapping_items(payload.get("capabilities", ()), "capabilities")
            ),
            protocol_rule_pack_revision=payload.get("protocol_rule_pack_revision", ""),
            display_labels=payload.get("display_labels", {}),
        )
        declared_hash = payload.get("config_sha256", "")
        if declared_hash not in ("", None) and (
            not isinstance(declared_hash, str)
            or not _SHA256_RE.fullmatch(declared_hash)
        ):
            raise StudyMonitoringConfigError(
                "config_sha256 must be a lowercase SHA-256"
            )
        if declared_hash not in ("", None) and declared_hash != config.config_sha256:
            raise StudyMonitoringConfigError("config_sha256 does not match canonical content")
        return config


__all__ = [
    "CORE_CAPABILITY_IDS",
    "StudyCapability",
    "StudyCapabilityState",
    "StudyFieldMapping",
    "StudyMonitoringConfig",
    "StudyMonitoringConfigError",
    "StudySourceBinding",
    "StudySourceKind",
    "StudyTreatmentIdentity",
]
