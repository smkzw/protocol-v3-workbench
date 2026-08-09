from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.api.app.medical_monitoring_router import (
    ApplicabilityConfirmationRequest,
    ApplicabilityRetirementRequest,
    AutomaticShadowRunRequest,
    ProtocolFactConfirmationRequest,
    RuleConfirmationRequest,
    RulePackActorRequest,
    RulePackDraftRequest,
    ShadowConfirmationRequest,
)


def _fact_confirmation(**overrides):
    payload = {
        "expected_state_version": 1,
        "fact_type": "eligibility",
        "deterministic_template": {},
    }
    payload.update(overrides)
    return ProtocolFactConfirmationRequest(**payload)


def _rule_confirmation(**overrides):
    payload = {"expected_state_version": 1}
    payload.update(overrides)
    return RuleConfirmationRequest(**payload)


@pytest.mark.parametrize(
    "build",
    (
        lambda value: ApplicabilityConfirmationRequest(
            expected_state_version=value
        ),
        lambda value: ApplicabilityRetirementRequest(
            expected_state_version=value
        ),
        lambda value: _fact_confirmation(expected_state_version=value),
        lambda value: _rule_confirmation(expected_state_version=value),
        lambda value: RulePackDraftRequest(
            protocol_version_id="version-1",
            fact_revision_ids=["fact-1"],
            expected_pack_revision=value,
        ),
        lambda value: RulePackActorRequest(expected_pack_revision=value),
        lambda value: AutomaticShadowRunRequest(
            batch_id="batch-1",
            expected_pack_revision=value,
        ),
        lambda value: ShadowConfirmationRequest(
            expected_pack_revision=value,
        ),
    ),
)
@pytest.mark.parametrize("value", (True, False, "1", "0"))
def test_authoring_cas_fields_reject_bool_like_values(build, value) -> None:
    with pytest.raises(ValidationError):
        build(value)


@pytest.mark.parametrize(
    "build",
    (
        lambda value: _fact_confirmation(reauthenticated=value),
        lambda value: _rule_confirmation(reauthenticated=value),
        lambda value: RulePackActorRequest(reauthenticated=value),
        lambda value: ShadowConfirmationRequest(reauthenticated=value),
    ),
)
@pytest.mark.parametrize("value", (0, 1, "false", "true"))
def test_authoring_reauthentication_rejects_bool_like_values(build, value) -> None:
    with pytest.raises(ValidationError):
        build(value)


def test_optional_pack_revision_accepts_none_and_strict_positive_int() -> None:
    assert (
        RulePackDraftRequest(
            protocol_version_id="version-1",
            fact_revision_ids=["fact-1"],
            expected_pack_revision=None,
        ).expected_pack_revision
        is None
    )
    assert (
        RulePackActorRequest(expected_pack_revision=2).expected_pack_revision
        == 2
    )

