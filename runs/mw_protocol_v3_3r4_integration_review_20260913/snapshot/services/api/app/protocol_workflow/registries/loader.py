"""Strict fail-closed loader for the Protocol v3 role and skill registries.

See :mod:`app.protocol_workflow.registries` for the design authority and the
offline discipline this module enforces.  The two public entry points are
:func:`load_role_registry` and :func:`load_skill_registry`; both accept either
a filesystem path or an already-parsed ``dict`` and return immutable typed
documents.

The registry documents are closed (``extra="forbid"`` Pydantic models).  The
loader additionally applies semantic fail-closed rules that Pydantic field
validation cannot express on its own:

* the role registry must declare *exactly* the four product AI roles and obey
  the role/thinking discipline (OCR and translation freeze effort to ``none``
  and expose no thinking control; LLM and OCR/translation-support may
  configure thinking/effort);
* every ``allowed_efforts`` value is a member of the canonical
  :class:`ReasoningEffort` closed set;
* credential-shaped keys/values and path-escaping ``allowed_paths`` entries
  are rejected before any object is constructed;
* skill entries build canonical :class:`SkillDefinition` objects from the
  representable fields and carry the remaining registry metadata verbatim.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    ReasoningEffort,
    SideEffectKind,
    SkillDefinition,
)

__all__ = [
    "CREDENTIAL_KEY_RE",
    "CREDENTIAL_VALUE_RE",
    "PATH_ESCAPE_RE",
    "REGISTRY_SCHEMA_VERSIONS",
    "RegistryDocumentError",
    "RegistryLoadError",
    "RoleEntry",
    "RoleRegistryDocument",
    "SkillEntry",
    "SkillRegistryDocument",
    "load_role_registry",
    "load_skill_registry",
]


# ---------------------------------------------------------------------------
# Closed sets and credential / path-escape scanners
# ---------------------------------------------------------------------------

#: Closed set of role kinds for the four product AI roles (design section 17.1).
PRODUCT_ROLE_KINDS = frozenset({"llm", "ocr", "translation", "ocr_translation_support"})

#: Roles whose ``thinking_configurable`` flag must be ``True``.
THINKING_CAPABLE_KINDS = frozenset({"llm", "ocr_translation_support"})

#: Roles whose effort must be frozen to ``none`` and must expose no thinking.
EFFORT_FROZEN_KINDS = frozenset({"ocr", "translation"})

#: The two thinking-frozen roles must only permit the ``none`` effort.
_FROZEN_EFFORTS = frozenset({ReasoningEffort.NONE.value})

#: Closed set of valid ``schema_version`` values for registry documents.
REGISTRY_SCHEMA_VERSIONS = {
    "role": "protocol-v3-role-registry.v1",
    "skill": "protocol-v3-skill-registry.v1",
}

#: Keys that smell like credentials.  Matched case-insensitively against the
#: whole key.  Registry documents must be credential-free.
CREDENTIAL_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|"
    r"access[_-]?key|bearer|authorization)"
)

#: Values that smell like credentials (bearer tokens, private key headers,
#: long hex/base64 secrets preceded by a credential-shaped key).  Used as a
#: defence-in-depth scan in addition to the key scan.
CREDENTIAL_VALUE_RE = re.compile(
    r"(?i)(Bearer\s+[A-Za-z0-9._\-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)

#: ``allowed_paths`` entries must be repository-relative and must not escape.
#: Absolute paths, home expansion and parent traversal are all rejected.
PATH_ESCAPE_RE = re.compile(
    r"(^\s*/)|(^~/)|(^~$)|(\.\./)|(\.\.\\)|(^[A-Za-z]:)|(^\\\\)|\\"
)

#: The five ``agent_role`` values permitted by the canonical SkillDefinition.
_AGENT_ROLES = frozenset(
    {"coordinator", "corpus", "design_and_summary", "full_draft", "quality_control"}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryDocumentError(ValueError):
    """Raised when a registry document violates the closed/fail-closed rules."""


#: Alias retained for callers that treat registry load failures uniformly.
RegistryLoadError = RegistryDocumentError


# ---------------------------------------------------------------------------
# Credential / path scanning helpers
# ---------------------------------------------------------------------------


def _scan_credentials(node: Any, location: str) -> None:
    """Recursively reject credential-shaped keys or values.

    ``location`` is a dotted path used only to produce a precise message.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            child = f"{location}.{key}"
            if isinstance(key, str) and CREDENTIAL_KEY_RE.search(key):
                raise RegistryDocumentError(
                    f"credential-shaped key rejected at {child!r}: {key!r}"
                )
            if isinstance(value, str) and CREDENTIAL_VALUE_RE.search(value):
                raise RegistryDocumentError(
                    f"credential-shaped value rejected at {child!r}"
                )
            _scan_credentials(value, child)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            _scan_credentials(item, f"{location}[{index}]")


def _scan_paths(entries: tuple[str, ...], location: str) -> None:
    for index, value in enumerate(entries):
        if PATH_ESCAPE_RE.search(value):
            raise RegistryDocumentError(
                f"escaping or absolute path rejected at {location}[{index}]: {value!r}"
            )


def _reject_unknown(value: Any, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise RegistryDocumentError(
            f"unknown {label}: {value!r}; allowed: {sorted(allowed)}"
        )


# ---------------------------------------------------------------------------
# Role registry
# ---------------------------------------------------------------------------


class _TargetProfile(BaseModel):
    """Credential-free target profile recorded for a product AI role."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    harness: str = Field(min_length=1)
    regions: tuple[str, ...] = Field(min_length=1)
    sensitivity_tier: str = Field(min_length=1)
    declared_runtime_note: str = Field(min_length=1)

    @field_validator("sensitivity_tier")
    @classmethod
    def _tier_must_be_known(cls, value: str) -> str:
        allowed = {
            "public",
            "internal",
            "confidential",
            "restricted",
        }
        if value not in allowed:
            raise ValueError(
                f"unknown sensitivity_tier: {value!r}; allowed: {sorted(allowed)}"
            )
        return value


class RoleEntry(BaseModel):
    """A single registered product AI role."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role_id: str = Field(min_length=3, max_length=160)
    role_kind: str
    description: str = Field(min_length=1)
    thinking_configurable: bool
    default_effort: str
    allowed_efforts: tuple[str, ...] = Field(min_length=1)
    target_profile: _TargetProfile

    @field_validator("role_id")
    @classmethod
    def _stable_id(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*", value):
            raise ValueError(f"malformed role_id (stable id): {value!r}")
        return value

    @field_validator("role_kind")
    @classmethod
    def _role_kind_closed(cls, value: str) -> str:
        _reject_unknown(value, PRODUCT_ROLE_KINDS, "role_kind")
        return value

    @field_validator("default_effort", "allowed_efforts")
    @classmethod
    def _effort_in_canonical_set(cls, value: Any) -> Any:
        allowed = {member.value for member in ReasoningEffort}
        values = value if isinstance(value, tuple) else (value,)
        for item in values:
            if item not in allowed:
                raise ValueError(
                    f"unknown effort: {item!r}; allowed: {sorted(allowed)}"
                )
        return value

    @model_validator(mode="after")
    def _enforce_thinking_discipline(self) -> RoleEntry:
        # Thinking-capable roles must flag configurable; frozen roles must not.
        if self.role_kind in THINKING_CAPABLE_KINDS and not self.thinking_configurable:
            raise ValueError(
                f"role_kind {self.role_kind!r} must set thinking_configurable=true"
            )
        if self.role_kind in EFFORT_FROZEN_KINDS and self.thinking_configurable:
            raise ValueError(
                f"role_kind {self.role_kind!r} must set thinking_configurable=false"
            )
        # Frozen roles permit only effort=none.
        if self.role_kind in EFFORT_FROZEN_KINDS:
            if set(self.allowed_efforts) != _FROZEN_EFFORTS:
                raise ValueError(
                    f"role_kind {self.role_kind!r} must freeze allowed_efforts to "
                    f"{{'none'}}; got {sorted(set(self.allowed_efforts))}"
                )
            if self.default_effort != ReasoningEffort.NONE.value:
                raise ValueError(
                    f"role_kind {self.role_kind!r} must freeze default_effort to 'none'"
                )
        # default_effort must be among allowed_efforts.
        if self.default_effort not in self.allowed_efforts:
            raise ValueError("default_effort must be a member of allowed_efforts")
        return self


class RoleRegistryDocument(BaseModel):
    """Closed, versioned role registry document."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: str
    generated_for: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    roles: tuple[RoleEntry, ...] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _version_closed(cls, value: str) -> str:
        expected = REGISTRY_SCHEMA_VERSIONS["role"]
        if value != expected:
            raise ValueError(
                f"unknown role schema_version: {value!r}; expected {expected!r}"
            )
        return value

    @model_validator(mode="after")
    def _exactly_four_product_roles_unique(self) -> RoleRegistryDocument:
        ids = [role.role_id for role in self.roles]
        if len(ids) != len(set(ids)):
            duplicates = sorted({role_id for role_id in ids if ids.count(role_id) > 1})
            raise ValueError(f"duplicate role_id values: {duplicates}")
        kinds = [role.role_kind for role in self.roles]
        if sorted(kinds) != sorted(PRODUCT_ROLE_KINDS):
            raise ValueError(
                f"registry must declare exactly the four product role kinds "
                f"{sorted(PRODUCT_ROLE_KINDS)}; got {sorted(kinds)}"
            )
        if len(self.roles) != 4:
            raise ValueError(
                f"registry must declare exactly four roles; got {len(self.roles)}"
            )
        return self


# ---------------------------------------------------------------------------
# Skill registry
# ---------------------------------------------------------------------------


class _Applicability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    status: str
    triggering_fact_paths: tuple[str, ...] = Field(min_length=1)

    @field_validator("status")
    @classmethod
    def _status_closed(cls, value: str) -> str:
        allowed = {"applicable", "conditional", "not_applicable"}
        _reject_unknown(value, allowed, "applicability.status")
        return value

    @field_validator("triggering_fact_paths")
    @classmethod
    def _paths_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item.strip():
                raise ValueError("triggering_fact_paths must not contain blanks")
        return value


class _IdempotencyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    mode: str = Field(min_length=1)
    key_basis: str = Field(min_length=1)


class _Rollback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    method: str = Field(min_length=1)
    preserves: tuple[str, ...] = Field(min_length=1)


class SkillEntry(BaseModel):
    """A registered skill plus the registry metadata the canonical
    :class:`SkillDefinition` does not carry."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    skill_definition_id: str
    skill_version: str = Field(min_length=1)
    agent_role: str
    input_schema_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    side_effect_kind: str
    acceptance_test_ids: tuple[str, ...] = Field(min_length=1)
    applicability: _Applicability
    idempotency_policy: _IdempotencyPolicy
    error_codes: tuple[str, ...] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    tool_versions: Mapping[str, str] = Field(min_length=1)
    rollback: _Rollback

    @field_validator("skill_definition_id", "acceptance_test_ids")
    @classmethod
    def _stable_ids(cls, value: Any) -> Any:
        values = value if isinstance(value, tuple) else (value,)
        for item in values:
            if not re.fullmatch(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*", item):
                raise ValueError(f"malformed stable id: {item!r}")
        return value

    @field_validator("agent_role")
    @classmethod
    def _agent_role_closed(cls, value: str) -> str:
        _reject_unknown(value, _AGENT_ROLES, "agent_role")
        return value

    @field_validator("side_effect_kind")
    @classmethod
    def _side_effect_closed(cls, value: str) -> str:
        allowed = {member.value for member in SideEffectKind}
        _reject_unknown(value, allowed, "side_effect_kind")
        return value

    @field_validator("allowed_paths")
    @classmethod
    def _paths_no_escape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _scan_paths(value, "allowed_paths")
        return value

    @model_validator(mode="after")
    def _unique_collections(self) -> SkillEntry:
        for attr in (
            "allowed_tools",
            "allowed_paths",
            "acceptance_test_ids",
            "evidence_requirements",
            "error_codes",
        ):
            collection = getattr(self, attr)
            if len(collection) != len(set(collection)):
                raise ValueError(f"{attr} must not contain duplicates")
        object.__setattr__(
            self, "tool_versions", MappingProxyType(dict(self.tool_versions))
        )
        return self

    @field_serializer("tool_versions")
    def _serialize_tool_versions(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    def to_skill_definition(self) -> SkillDefinition:
        """Build the canonical :class:`SkillDefinition` from the fields the
        contract is able to represent.

        The remaining registry metadata (applicability, idempotency policy,
        error codes, prompt/tool versions, rollback) is intentionally not on
        the canonical contract and stays on this entry.  The skill is frozen.
        """
        return SkillDefinition(
            skill_definition_id=self.skill_definition_id,
            skill_version=self.skill_version,
            agent_role=self.agent_role,  # type: ignore[arg-type]
            input_schema_ref=self.input_schema_ref,
            output_schema_ref=self.output_schema_ref,
            evidence_requirements=self.evidence_requirements,
            allowed_tools=self.allowed_tools,
            allowed_paths=self.allowed_paths,
            side_effect_kind=SideEffectKind(self.side_effect_kind),
            acceptance_test_ids=self.acceptance_test_ids,
            canonical_state=CanonicalState.FROZEN,
        )


class SkillRegistryDocument(BaseModel):
    """Closed, versioned skill registry document."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: str
    generated_for: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    skills: tuple[SkillEntry, ...] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _version_closed(cls, value: str) -> str:
        expected = REGISTRY_SCHEMA_VERSIONS["skill"]
        if value != expected:
            raise ValueError(
                f"unknown skill schema_version: {value!r}; expected {expected!r}"
            )
        return value

    @model_validator(mode="after")
    def _unique_skill_ids(self) -> SkillRegistryDocument:
        ids = [skill.skill_definition_id for skill in self.skills]
        if len(ids) != len(set(ids)):
            duplicates = sorted(
                {skill_id for skill_id in ids if ids.count(skill_id) > 1}
            )
            raise ValueError(f"duplicate skill_definition_id values: {duplicates}")
        return self

    def skill_definitions(self) -> tuple[SkillDefinition, ...]:
        """Build the canonical SkillDefinition objects for every entry."""
        return tuple(skill.to_skill_definition() for skill in self.skills)


# ---------------------------------------------------------------------------
# Public load entry points
# ---------------------------------------------------------------------------


def _load_json(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        # Defensive copy so the caller cannot mutate the parsed document.
        return json.loads(json.dumps(dict(source), ensure_ascii=False, sort_keys=True))
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RegistryDocumentError(
            f"registry document must be a JSON object; got {type(data).__name__}"
        )
    return data


def load_role_registry(
    source: str | Path | Mapping[str, Any],
) -> RoleRegistryDocument:
    """Load and validate the role registry document fail-closed.

    ``source`` is a path to ``role_registry.json`` or an already-parsed
    mapping.  Raises :class:`RegistryDocumentError` (a ``ValueError``) for any
    closed-set, schema-version, credential, path-escape, duplicate or
    role-thinking violation.
    """
    data = _load_json(source)
    _scan_credentials(data, "role-registry")
    try:
        document = RoleRegistryDocument.model_validate(data)
    except ValidationError as exc:
        raise RegistryDocumentError(f"role registry failed closed: {exc}") from exc
    return document


def load_skill_registry(
    source: str | Path | Mapping[str, Any],
) -> SkillRegistryDocument:
    """Load and validate the skill registry document fail-closed.

    Builds canonical :class:`SkillDefinition` objects via
    :meth:`SkillRegistryDocument.skill_definitions`.  Raises
    :class:`RegistryDocumentError` for any closed-set, schema-version,
    credential, path-escape, duplicate or stable-id violation.
    """
    data = _load_json(source)
    _scan_credentials(data, "skill-registry")
    try:
        document = SkillRegistryDocument.model_validate(data)
    except ValidationError as exc:
        raise RegistryDocumentError(f"skill registry failed closed: {exc}") from exc
    # Eagerly construct the canonical SkillDefinition objects so a
    # representability gap surfaces here, not at first dispatch.
    document.skill_definitions()
    return document
