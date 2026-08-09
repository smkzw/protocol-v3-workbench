from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    RuleRiskBinding,
)
from tests.test_monitoring_protocol_rules import _fact, _rule, _version


def _changed_rule_packs(repository: MonitoringProtocolRuleRepository):
    version = repository.register_protocol_version(
        _version(
            "proj_alpha",
            "V1.0",
            "2026-01-01",
            effective_from="2026-01-10",
        )
    )
    fact = repository.store_fact(_fact(version))
    lifecycle = MonitoringRuleLifecycleService(repository)
    previous_rule = _rule(version, fact, trigger_value="漏服")
    previous_pack = lifecycle.create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=[replace(previous_rule, status="candidate")],
        created_by="rule_author",
    )
    current_rule = _rule(version, fact, trigger_value="多服")
    current_pack = lifecycle.create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=[replace(current_rule, status="candidate")],
        created_by="rule_author",
    )
    return previous_pack, previous_rule, current_pack, current_rule


def test_re_review_requires_an_injected_trusted_risk_validator() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        previous_pack, previous_rule, current_pack, _ = _changed_rule_packs(
            repository
        )
        binding = RuleRiskBinding(
            risk_instance_id="risk-known",
            project_id="proj_alpha",
            rule_key=previous_rule.rule_key,
            evaluated_rule_revision_id=previous_rule.rule_revision_id,
        )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="validator is not configured",
        ):
            MonitoringProtocolRuleService(repository).schedule_re_reviews(
                previous_rule_pack_id=previous_pack.rule_pack_id,
                current_rule_pack_id=current_pack.rule_pack_id,
                risk_bindings=[binding],
            )


@pytest.mark.parametrize(
    ("binding_update", "message"),
    (
        ({"project_id": "proj_other"}, "another project"),
        (
            {"evaluated_rule_revision_id": "rule-revision-forged"},
            "revision is not present",
        ),
        ({"risk_instance_id": "risk-unknown"}, "trusted risk repository"),
    ),
)
def test_re_review_rejects_cross_project_forged_revision_and_unknown_risk(
    binding_update: dict[str, str],
    message: str,
) -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        previous_pack, previous_rule, current_pack, _ = _changed_rule_packs(
            repository
        )
        values = {
            "risk_instance_id": "risk-known",
            "project_id": "proj_alpha",
            "rule_key": previous_rule.rule_key,
            "evaluated_rule_revision_id": previous_rule.rule_revision_id,
            **binding_update,
        }
        service = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=lambda binding: (
                binding.risk_instance_id == "risk-known"
            ),
        )

        with pytest.raises(MonitoringProtocolRuleError, match=message):
            service.schedule_re_reviews(
                previous_rule_pack_id=previous_pack.rule_pack_id,
                current_rule_pack_id=current_pack.rule_pack_id,
                risk_bindings=[RuleRiskBinding(**values)],
            )


def test_re_review_accepts_only_the_trusted_previous_pack_binding() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        previous_pack, previous_rule, current_pack, current_rule = (
            _changed_rule_packs(repository)
        )
        service = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=lambda binding: (
                binding.risk_instance_id == "risk-known"
            ),
        )

        tasks = service.schedule_re_reviews(
            previous_rule_pack_id=previous_pack.rule_pack_id,
            current_rule_pack_id=current_pack.rule_pack_id,
            risk_bindings=[
                RuleRiskBinding(
                    risk_instance_id="risk-known",
                    project_id="proj_alpha",
                    rule_key=previous_rule.rule_key,
                    evaluated_rule_revision_id=previous_rule.rule_revision_id,
                )
            ],
        )

        assert len(tasks) == 1
        assert tasks[0].previous_rule_revision_id == previous_rule.rule_revision_id
        assert tasks[0].current_rule_revision_id == current_rule.rule_revision_id


def test_cross_record_evidence_keeps_raw_rows_search_scope_and_locators() -> None:
    with TemporaryDirectory() as directory:
        service = MonitoringProtocolRuleService(
            MonitoringProtocolRuleRepository(
                Path(directory) / "rules.sqlite3"
            )
        )
        version = _version("proj_alpha", "V1.0", "2026-01-01")
        fact = _fact(version)
        rule = MonitoringRuleDefinition.create(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rule_key="safety.ae_missing.after_abnormal_lab",
            rule_family="ae_mh_missing_review",
            status="enabled",
            title="异常实验室检查后未找到对应 AE 记录",
            executor="cross_record",
            required_domains=["LB", "AE"],
            preconditions={"exists": {"field": "SUBJID"}},
            trigger_expression={
                "no_corresponding_record": {
                    "domain": "AE",
                    "field": "AETERM",
                    "value": "肝功能异常",
                }
            },
            exclusions={"exists": {"field": "MEDICAL_EXCLUSION"}},
            severity="high",
            confidence="deterministic",
            evidence_template="{LBDTC} {VISIT} {LBTEST} {LBORRES}",
            fact_revision_ids=[fact.fact_revision_id],
            source_entry_id=fact.source_entry_id,
            source_locator=fact.source_locator,
            source_text=fact.source_text,
        )
        current = {
            "SUBJID": "S01003",
            "LBDTC": "2026-07-12",
            "VISIT": "V3D8",
            "LBTEST": "ALT",
            "LBORRES": "186 IU/L",
            "source_locator": {
                "sheet": "LB",
                "row": 18,
            },
        }
        previous = {
            "SUBJID": "S01003",
            "LBDTC": "2026-06-28",
            "LBTEST": "ALT",
            "LBORRES": "32 IU/L",
            "source_locator": {
                "sheet": "LB",
                "row": 7,
            },
        }
        related = {
            "AE": [
                {
                    "SUBJID": "S01003",
                    "AETERM": "头痛",
                    "AESTDTC": "2026-07-10",
                    "source_locator": {
                        "sheet": "AE",
                        "row": 4,
                    },
                }
            ]
        }

        result = service.evaluate_record(
            rule,
            current,
            observed_domains=["LB", "AE"],
            previous_record=previous,
            related_records=related,
        )

        assert result.matched is True
        assert result.evidence["current_record"]["raw_data"]["LBORRES"] == "186 IU/L"
        assert result.evidence["previous_record"]["raw_data"]["LBORRES"] == "32 IU/L"
        assert result.evidence["related_records"]["AE"][0]["raw_data"]["AETERM"] == "头痛"
        assert result.evidence["current_record"]["source_locators"] == [
            {"sheet": "LB", "row": 18}
        ]
        query = result.evidence["missing_record_queries"][0]
        assert query == {
            "domain": "AE",
            "match_field": "AETERM",
            "expected_value": "肝功能异常",
            "searched_record_count": 1,
            "matching_record_count": 0,
            "missing": True,
            "searched_source_locators": [{"sheet": "AE", "row": 4}],
        }
        assert result.evidence["search_scope"]["subject_id"] == "S01003"
        assert result.evidence["search_scope"]["related_record_counts"] == {
            "AE": 1
        }
