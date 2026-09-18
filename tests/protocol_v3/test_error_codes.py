from __future__ import annotations

import pytest

from services.api.app.protocol_workflow.errors import (
    ERROR_CATALOG,
    MalformedProtocolErrorCode,
    ProtocolErrorCode,
    ProtocolErrorDefinition,
    ProtocolErrorOwner,
    ProtocolWorkflowError,
    RecoveryAction,
    UnknownProtocolErrorCode,
    get_error_definition,
    parse_error_code,
)


def _workflow_error(**overrides):
    payload = {
        "code": ProtocolErrorCode.E1_PROTOCOL_DOWNLOAD_INCOMPLETE,
        "object_id": "source-plan:uc301:r3",
        "owner": ProtocolErrorOwner.EVIDENCE_AGENT,
        "retryable": True,
        "attempt": 2,
        "audit_detail": "2 linked protocol artifacts are not present in the immutable store",
        "audit_context": {
            "source_plan_revision": 3,
            "missing_artifact_count": 2,
            "internal_path": "/runtime/private/source-plan.json",
        },
    }
    payload.update(overrides)
    return ProtocolWorkflowError(**payload)


def test_error_code_parser_round_trips_every_registered_code() -> None:
    assert set(ERROR_CATALOG) == set(ProtocolErrorCode)
    for code, definition in ERROR_CATALOG.items():
        parts = parse_error_code(code.value)
        assert parts.code == code.value
        assert definition.code is code


def test_catalog_covers_every_implementation_phase_and_required_gate() -> None:
    assert {definition.phase for definition in ERROR_CATALOG.values()} == set(range(9))
    gates = {parse_error_code(code.value).gate for code in ERROR_CATALOG}
    assert {"E0", "E1", "E2", "E3", "D1", "W1", "Q1", "F1"} <= gates


def test_catalog_includes_required_execution_and_word_causes() -> None:
    causes = {parse_error_code(code.value).cause for code in ERROR_CATALOG}
    assert {
        "CAS",
        "STALE",
        "UNKNOWN_OUTCOME",
        "CHECKPOINT_EVENT_MISMATCH",
        "WORD_RECEIPT_STALE",
    } <= causes


def test_all_registered_public_copy_is_native_chinese() -> None:
    for definition in ERROR_CATALOG.values():
        assert any("\u3400" <= char <= "\u9fff" for char in definition.public_message)
        assert any("\u3400" <= char <= "\u9fff" for char in definition.public_next_step)


@pytest.mark.parametrize(
    "value",
    (
        "MW-PRO-E1-SOURCE",
        "MW-PRO-E1-SOURCE-bad",
        "MW_PRO_E1_SOURCE_BAD",
        " MW-PRO-E1-SOURCE-OCR_UNREADABLE",
        "MW-PRO-X9-SOURCE-UNKNOWN",
    ),
)
def test_malformed_code_fails(value: str) -> None:
    with pytest.raises(MalformedProtocolErrorCode):
        parse_error_code(value)


def test_well_formed_but_unknown_code_fails_registry_lookup() -> None:
    with pytest.raises(UnknownProtocolErrorCode):
        get_error_definition("MW-PRO-E1-SOURCE-UNREGISTERED_CAUSE")


def test_definition_rejects_missing_owner_and_retryability() -> None:
    with pytest.raises(ValueError, match="owner"):
        ProtocolErrorDefinition(
            code=ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE,
            phase=4,
            owner=None,  # type: ignore[arg-type]
            retryable=True,
            recovery_action=RecoveryAction.REVISE_SEARCH_SCOPE,
            public_message="竞品与证据检索范围尚不完整。",
            public_next_step="请完善研究信息后重新检索。",
        )
    with pytest.raises(ValueError, match="retryable"):
        ProtocolErrorDefinition(
            code=ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE,
            phase=4,
            owner=ProtocolErrorOwner.EVIDENCE_AGENT,
            retryable=None,  # type: ignore[arg-type]
            recovery_action=RecoveryAction.REVISE_SEARCH_SCOPE,
            public_message="竞品与证据检索范围尚不完整。",
            public_next_step="请完善研究信息后重新检索。",
        )


def test_workflow_error_rejects_missing_object_identity_owner_and_retryability() -> None:
    with pytest.raises(ValueError, match="object_id"):
        _workflow_error(object_id="")
    with pytest.raises(ValueError, match="owner"):
        _workflow_error(owner=None)
    with pytest.raises(ValueError, match="retryable"):
        _workflow_error(retryable=None)


def test_runtime_owner_and_retryability_must_match_registry() -> None:
    with pytest.raises(ValueError, match="owner must match"):
        _workflow_error(owner=ProtocolErrorOwner.COORDINATOR_AGENT)
    with pytest.raises(ValueError, match="retryable must match"):
        _workflow_error(retryable=False)


def test_public_payload_is_native_chinese_and_excludes_audit_identity() -> None:
    error = _workflow_error()
    public_payload = error.to_public_payload()
    serialized = repr(public_payload).casefold()

    assert set(public_payload) == {
        "message",
        "responsible_area",
        "can_retry",
        "next_step",
    }
    assert public_payload["responsible_area"] == "资料与证据整理"
    assert public_payload["can_retry"] is True
    assert str(error) == public_payload["message"]
    for internal_value in (
        error.code.value,
        error.object_id,
        error.audit_detail,
        "/runtime/private/source-plan.json",
        "audit_context",
    ):
        assert internal_value.casefold() not in serialized


def test_audit_payload_retains_complete_machine_explanation() -> None:
    error = _workflow_error()
    audit_payload = error.to_audit_payload()

    assert audit_payload == {
        "error_code": "MW-PRO-E1-PROTOCOL-DOWNLOAD_INCOMPLETE",
        "phase": 4,
        "object_id": "source-plan:uc301:r3",
        "owner": "evidence_agent",
        "retryable": True,
        "recovery_action": "complete_source_processing",
        "attempt": 2,
        "audit_detail": "2 linked protocol artifacts are not present in the immutable store",
        "audit_context": {
            "source_plan_revision": 3,
            "missing_artifact_count": 2,
            "internal_path": "/runtime/private/source-plan.json",
        },
    }


@pytest.mark.parametrize(
    "public_message",
    (
        "Gate E0 未通过，请查看 log。",
        "请查看 /runtime/private/task.json 后重试。",
        "请核对 MW-PRO-E0-SEARCH-SCOPE_INCOMPLETE。",
        "Please retry the search.",
    ),
)
def test_public_copy_cannot_use_internal_or_programmer_facing_wording(
    public_message: str,
) -> None:
    with pytest.raises(ValueError, match="internal implementation wording|native Chinese copy"):
        ProtocolErrorDefinition(
            code=ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE,
            phase=4,
            owner=ProtocolErrorOwner.EVIDENCE_AGENT,
            retryable=True,
            recovery_action=RecoveryAction.REVISE_SEARCH_SCOPE,
            public_message=public_message,
            public_next_step="请重新检索。",
        )


def test_error_catalog_and_context_are_immutable_views() -> None:
    with pytest.raises(TypeError):
        ERROR_CATALOG[ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE] = None  # type: ignore[index]
    error = _workflow_error()
    with pytest.raises(TypeError):
        error.audit_context["missing_artifact_count"] = 0  # type: ignore[index]


@pytest.mark.parametrize(
    ("attribute", "value"),
    (
        ("definition", get_error_definition(ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE)),
        ("owner", ProtocolErrorOwner.COORDINATOR_AGENT),
        ("retryable", False),
        ("object_id", "source-plan:other"),
        ("_owner", ProtocolErrorOwner.COORDINATOR_AGENT),
    ),
)
def test_workflow_error_cannot_be_mutated_after_construction(
    attribute: str,
    value: object,
) -> None:
    error = _workflow_error()
    with pytest.raises(AttributeError, match="immutable"):
        setattr(error, attribute, value)


def test_workflow_error_survives_generator_context_cleanup():
    from contextlib import contextmanager

    @contextmanager
    def transaction():
        yield

    error = _workflow_error()
    with pytest.raises(ProtocolWorkflowError) as caught:
        with transaction():
            raise error
    assert caught.value is error
    assert error.__traceback__ is not None
