"""Split public/audit exception cards for the Agent⑤ user-communication surface.

Design authority: design sections 5.4 (Agent⑤ is the user-side communication
role) and 18 (typed errors carry a user-explained view and a controlled audit
view), plus the finite error catalog (``protocol_workflow.errors``).

An :class:`ExceptionCard` is immutable and closed.  Its ``public`` payload is
built ONLY from the catalog's Chinese-native public message, responsible-area
label, retryability and next-step copy (exactly
:meth:`ProtocolWorkflowError.to_public_payload`); its ``audit`` payload
carries the machine code, phase, object ID, attempt, owner enum, recovery
action and audit detail/context — deliberately separated so raw code, paths,
tracebacks, ``log``/backend labels, ``门``/``信号`` jargon and programmer
labels can never leak into the medical-writer interface.  The public-copy
scan is enforced at the model level, so the card is fail-closed by shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from packages.contracts.workbench_contracts.protocol_v3 import (
    AwareDateTime,
    JsonValue,
    NonEmptyText,
    StableId,
)

from app.protocol_workflow.errors import (
    GATE_PHASE,
    ProtocolErrorOwner,
    RecoveryAction,
    parse_error_code,
)

__all__ = [
    "ExceptionCard",
    "ExceptionCardAuditPayload",
    "ExceptionCardPublicPayload",
]


#: Tokens that must never appear in a public exception-card payload: raw
#: machine codes, paths, tracebacks, log/backend/checkpoint labels, gate or
#: signal jargon (门 / 信号) and programmer labels.  This mirrors the finite
#: error catalog's own public-copy discipline and the Task 1.9 authority
#: requirement that public copy stays Chinese-native and implementation-free.
_PUBLIC_CARD_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "mw-pro-",
    "prompt",
    "api_key",
    "password",
    "token",
    "credential",
    "secret",
    "authorization",
    "bearer ",
    "checkpoint",
    "backend",
    "traceback",
    "错误码",
    "日志",
    "凭证",
    "产物",
    "基线",
    "构建",
    "log",
    "gate",
    "门",
    "信号",
    "\\",
    "/",
)


def _scan_public_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"public exception card {field_name} is required")
    if "\n" in value or "\r" in value:
        raise ValueError(f"public exception card {field_name} must be a single line")
    lowered = value.casefold()
    for token in _PUBLIC_CARD_FORBIDDEN_TOKENS:
        if token.casefold() in lowered:
            raise ValueError(
                f"public exception card {field_name} must not contain internal "
                f"implementation wording: {token!r}"
            )
    return value


class ExceptionCardPublicPayload(BaseModel):
    """The medical-writer-facing card payload.

    Every field is catalog-derived Chinese-native copy only: message,
    responsible area, retryability and next step.  The payload is validated
    against the forbidden-token scan at construction, so no raw code, path,
    traceback, ``log``, ``门``, ``信号`` or programmer label can be carried.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    message: NonEmptyText
    responsible_area: NonEmptyText
    can_retry: bool
    next_step: NonEmptyText

    @model_validator(mode="after")
    def _public_copy_is_clean(self) -> ExceptionCardPublicPayload:
        _scan_public_text(self.message, field_name="message")
        _scan_public_text(self.responsible_area, field_name="responsible_area")
        _scan_public_text(self.next_step, field_name="next_step")
        return self


class ExceptionCardAuditPayload(BaseModel):
    """The controlled machine/audit record for the same exception.

    Machine code, phase, object ID, owner enum, recovery action, attempt and
    audit detail/context live here and only here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    error_code: NonEmptyText
    phase: int
    object_id: NonEmptyText
    owner: NonEmptyText
    retryable: bool
    recovery_action: NonEmptyText
    attempt: int
    audit_detail: NonEmptyText
    audit_context: dict[NonEmptyText, JsonValue]

    @field_validator("error_code")
    @classmethod
    def _code_is_registered(cls, value: str) -> str:
        parse_error_code(value)
        return value

    @field_validator("owner")
    @classmethod
    def _owner_is_registered(cls, value: str) -> str:
        ProtocolErrorOwner(value)
        return value

    @field_validator("recovery_action")
    @classmethod
    def _recovery_is_registered(cls, value: str) -> str:
        RecoveryAction(value)
        return value

    @model_validator(mode="after")
    def _audit_consistency(self) -> ExceptionCardAuditPayload:
        parts = parse_error_code(self.error_code)
        if GATE_PHASE[parts.gate] != self.phase:
            raise ValueError("audit phase does not match the error code gate")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("audit attempt must be a positive integer")
        return self


class ExceptionCard(BaseModel):
    """An immutable exception card with strictly separated public/audit views.

    Produced by :meth:`Agent5Coordinator.to_exception_card` from a
    :class:`ProtocolWorkflowError`; the public view is exactly the catalog's
    public payload and the audit view is exactly the error's audit payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    card_id: StableId
    created_at: AwareDateTime
    public: ExceptionCardPublicPayload
    audit: ExceptionCardAuditPayload
