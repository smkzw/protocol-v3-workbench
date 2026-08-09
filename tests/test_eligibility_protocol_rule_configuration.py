import pytest

from services.api.app import eligibility
from services.api.app.eligibility_protocol_rules import (
    EligibilityProtocolRuleService,
)


def test_protocol_rule_service_configuration_replaces_active_service() -> None:
    original = eligibility.protocol_rule_service
    first = EligibilityProtocolRuleService(configs=())
    second = EligibilityProtocolRuleService(configs=())
    try:
        eligibility.configure_protocol_rule_service(first)
        assert eligibility.protocol_rule_service is first
        eligibility.configure_protocol_rule_service(second)
        assert eligibility.protocol_rule_service is second
        with pytest.raises(KeyError, match="not configured"):
            eligibility.protocol_rule_service.rules_for_project("proj_unknown")
    finally:
        eligibility.configure_protocol_rule_service(original)


def test_protocol_rule_service_configuration_rejects_invalid_service() -> None:
    with pytest.raises(TypeError, match="rules_for_project"):
        eligibility.configure_protocol_rule_service(None)  # type: ignore[arg-type]
