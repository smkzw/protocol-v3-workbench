from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    MonitoringRulePack,
    ProtocolFact,
    ProtocolSourceVersion,
    RuleGoldStandardCase,
    RuleGoldRecordFieldBinding,
    RuleGoldSourceRowBinding,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)


def _rule(
    trigger_expression: Mapping[str, Any],
    *,
    status: str = "enabled",
    executor: str = "field_predicate",
    required_domains: tuple[str, ...] = ("EX",),
    project_id: str = "proj_alpha",
    protocol_version_id: str = "version-proj-alpha",
    fact_revision_id: str = "fact-proj-alpha",
) -> MonitoringRuleDefinition:
    fields = {"SUBJID", "__RULE_EXCLUDED__"}

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in {
                    "field",
                    "other_field",
                    "numerator_field",
                    "denominator_field",
                    "related_field",
                    "current_field",
                    "related_date_field",
                    "current_date_field",
                }:
                    fields.add(str(item))
                else:
                    collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(trigger_expression)
    source_hash = sha256(f"{project_id}:fail-closed".encode("utf-8")).hexdigest()
    lineage = {
        f"field_{index}": {
            "field": field_name,
            "domain": required_domains[0],
            "lineage": {
                "source_type": "raw_listing_field",
                "source_locator": (
                    f"listing:{source_hash}:sheet:{required_domains[0]}:"
                    f"header:1:field:{field_name}"
                ),
            },
        }
        for index, field_name in enumerate(sorted(fields), start=1)
    }
    return MonitoringRuleDefinition.create(
        project_id=project_id,
        protocol_version_id=protocol_version_id,
        rule_key="data_quality.fail_closed.review",
        rule_family="data_quality",
        clinical_domain="data_quality",
        status=status,
        title="缺失或无效输入需关闭求值",
        executor=executor,
        required_domains=required_domains,
        preconditions={"exists": {"field": "SUBJID"}},
        trigger_expression=trigger_expression,
        exclusions={"exists": {"field": "__RULE_EXCLUDED__"}},
        severity="high",
        confidence="deterministic",
        evidence_template="{SUBJID} 规则条件满足，需医学复核。",
        fact_revision_ids=[fact_revision_id],
        source_entry_id="protocol-source",
        source_locator="docx:p12",
        source_text="方案要求对相关原始记录进行医学复核。",
        field_lineage=lineage,
        mapping_revision="mapping-v1",
        mapping_content_sha256="2" * 64,
        capability_manifest_sha256="5" * 64,
        effective_capabilities_sha256="6" * 64,
    )


def _evaluate(
    rule: MonitoringRuleDefinition,
    record: Mapping[str, Any],
    *,
    observed_domains: tuple[str, ...] = ("EX",),
    previous_record: Mapping[str, Any] | None = None,
    related_records: Mapping[str, list[Mapping[str, Any]]] | None = None,
    **kwargs: Any,
):
    service = object.__new__(MonitoringProtocolRuleService)
    return service.evaluate_record(
        rule,
        record,
        observed_domains=observed_domains,
        previous_record=previous_record,
        related_records=related_records,
        **kwargs,
    )


@pytest.mark.parametrize(
    "trigger_expression",
    (
        {"not": {"eq": {"field": "STATUS", "value": "ok"}}},
        {"ne": {"field": "STATUS", "value": "ok"}},
        {"not_in": {"field": "STATUS", "value": ["ok", "done"]}},
    ),
)
def test_missing_comparison_inputs_remain_indeterminate_under_negative_operators(
    trigger_expression: Mapping[str, Any],
) -> None:
    result = _evaluate(
        _rule(trigger_expression),
        {
            "SUBJID": "S001",
            "__source_locator__": "listing:EX:row:1",
        },
    )

    assert result.matched is False
    assert result.evidence["evaluation_state"] == "indeterminate"
    assert (
        result.evidence["predicate_trace"]["trigger"]["state"]
        == "indeterminate"
    )


def test_nan_ratio_remains_indeterminate_when_negated() -> None:
    result = _evaluate(
        _rule(
            {
                "not": {
                    "ratio_range": {
                        "numerator_field": "ACTUAL",
                        "denominator_field": "PLANNED",
                        "multiplier": 100,
                        "min_value": 80,
                        "max_value": 120,
                    }
                }
            }
        ),
        {
            "SUBJID": "S001",
            "ACTUAL": "NaN",
            "PLANNED": 10,
            "__source_locator__": "listing:EX:row:2",
        },
    )

    child = result.evidence["predicate_trace"]["trigger"]["children"][0]
    assert result.matched is False
    assert child["state"] == "indeterminate"
    assert child["numerator_value"] == "NaN"
    assert child["computed_ratio"] is None


@pytest.mark.parametrize("value", (float("nan"), float("inf"), "Infinity"))
def test_non_finite_values_do_not_make_ne_match(value: Any) -> None:
    result = _evaluate(
        _rule({"ne": {"field": "STATUS", "value": "ok"}}),
        {
            "SUBJID": "S001",
            "STATUS": value,
            "__source_locator__": "listing:EX:row:2b",
        },
    )

    assert result.matched is False
    assert (
        result.evidence["predicate_trace"]["trigger"]["state"]
        == "indeterminate"
    )


def test_missing_previous_value_does_not_make_negated_changed_match() -> None:
    result = _evaluate(
        _rule({"not": {"changed": {"field": "EXDOSE"}}}),
        {
            "SUBJID": "S001",
            "EXDOSE": 10,
            "__source_locator__": "listing:EX:row:3",
        },
    )

    assert result.matched is False
    assert result.evidence["evaluation_state"] == "indeterminate"


def test_invalid_related_date_makes_absence_query_indeterminate() -> None:
    rule = _rule(
        {
            "no_corresponding_record": {
                "domain": "AE",
                "match": [
                    {
                        "related_field": "SUBJID",
                        "current_field": "SUBJID",
                        "operator": "eq",
                    }
                ],
                "date_window": {
                    "related_date_field": "AESTDTC",
                    "current_date_field": "LBDTC",
                    "min_days": -7,
                    "max_days": 7,
                },
            }
        },
        executor="cross_record",
        required_domains=("LB", "AE"),
    )
    result = _evaluate(
        rule,
        {
            "SUBJID": "S001",
            "LBDTC": "2026-07-20",
            "__source_locator__": "listing:LB:row:4",
        },
        observed_domains=("LB", "AE"),
        related_records={
            "AE": [
                {
                    "SUBJID": "S001",
                    "AESTDTC": "not-a-date",
                    "__source_locator__": "listing:AE:row:9",
                }
            ]
        },
    )

    trace = result.evidence["predicate_trace"]["trigger"]
    query = result.evidence["missing_record_queries"][0]
    assert result.matched is False
    assert trace["state"] == "indeterminate"
    assert trace["indeterminate_record_count"] == 1
    assert query["missing"] is False
    assert query["unmatched_reasons"][0]["reasons"] == [
        "date_window_indeterminate"
    ]
    assert query["row_evaluations"][0]["date_window"][
        "related_date_value"
    ] == "not-a-date"


def test_absence_query_requires_explicit_complete_search_domain() -> None:
    rule = _rule(
        {
            "no_corresponding_record": {
                "domain": "AE",
                "field": "AETERM",
                "value": "肝功能异常",
            }
        },
        executor="cross_record",
        required_domains=("LB", "AE"),
    )
    current = {
        "SUBJID": "S001",
        "__source_locator__": "listing:LB:row:5",
    }

    incomplete = _evaluate(
        rule,
        current,
        observed_domains=("LB", "AE"),
        related_records={},
    )
    complete = _evaluate(
        rule,
        current,
        observed_domains=("LB", "AE"),
        related_records={
            "AE": [
                {
                    "AETERM": "头痛",
                    "__source_locator__": "listing:AE:row:10",
                }
            ]
        },
    )

    assert incomplete.matched is False
    assert incomplete.evidence["evaluation_state"] == "indeterminate"
    assert complete.matched is True
    assert complete.evidence["evidence_ready"] is True
    assert complete.evidence["missing_record_queries"][0][
        "searched_source_locators"
    ] == ["listing:AE:row:10"]


def test_matching_condition_without_current_locator_fails_evidence_gate() -> None:
    result = _evaluate(
        _rule({"eq": {"field": "STATUS", "value": "review"}}),
        {"SUBJID": "S001", "STATUS": "review"},
    )

    assert result.matched is False
    assert result.evidence["predicate_matched_before_evidence_gate"] is True
    assert result.evidence["evidence_ready"] is False
    assert {
        item["kind"] for item in result.evidence["missing_evidence"]
    } == {"current_record_locator"}


def test_absence_match_requires_locator_on_every_searched_related_row() -> None:
    rule = _rule(
        {
            "no_corresponding_record": {
                "domain": "AE",
                "field": "AETERM",
                "value": "肝功能异常",
            }
        },
        executor="cross_record",
        required_domains=("LB", "AE"),
    )
    result = _evaluate(
        rule,
        {
            "SUBJID": "S001",
            "__source_locator__": "listing:LB:row:6",
        },
        observed_domains=("LB", "AE"),
        related_records={"AE": [{"AETERM": "头痛"}]},
    )

    assert result.matched is False
    assert result.evidence["predicate_matched_before_evidence_gate"] is True
    assert result.evidence["evidence_ready"] is False
    assert any(
        item["kind"] == "related_record_locator"
        for item in result.evidence["missing_evidence"]
    )


def test_candidate_rule_cannot_execute_even_in_shadow_mode() -> None:
    candidate = _rule(
        {"eq": {"field": "STATUS", "value": "review"}},
        status="candidate",
    )
    record = {
        "SUBJID": "S001",
        "STATUS": "review",
        "__source_locator__": "listing:EX:row:7",
    }

    with pytest.raises(
        MonitoringProtocolRuleError,
        match="candidate rules cannot be executed",
    ):
        _evaluate(candidate, record)
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="candidate rules cannot be executed",
    ):
        _evaluate(
            candidate,
            record,
            allow_non_enabled=True,
            validation_mode="shadow",
        )


def test_confirmed_rule_requires_explicit_shadow_mode() -> None:
    confirmed = _rule(
        {"eq": {"field": "STATUS", "value": "review"}},
        status="confirmed",
    )
    record = {
        "SUBJID": "S001",
        "STATUS": "review",
        "__source_locator__": "listing:EX:row:8",
    }

    with pytest.raises(
        MonitoringProtocolRuleError,
        match="requires status=enabled",
    ):
        _evaluate(confirmed, record)
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="only in shadow",
    ):
        _evaluate(confirmed, record, allow_non_enabled=True)

    result = _evaluate(
        confirmed,
        record,
        allow_non_enabled=True,
        validation_mode="shadow",
    )
    assert result.matched is True


def _stored_shadow_pack(
    repository: MonitoringProtocolRuleRepository,
) -> tuple[MonitoringRulePack, MonitoringRuleDefinition]:
    version = repository.register_protocol_version(
        ProtocolSourceVersion.create(
            project_id="proj_alpha",
            protocol_code="ALPHA-001",
            version_label="V1.0",
            version_date="2026-01-01",
            source_entry_id="protocol-source",
            source_title="ALPHA-001 研究方案",
            content_sha256="a" * 64,
        )
    )
    fact = repository.store_fact(
        ProtocolFact.create(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            fact_key="data_quality.review",
            fact_type="data_quality",
            status="medically_confirmed",
            title="数据质量复核",
            normalized_payload={"review": True},
            source_entry_id=version.source_entry_id,
            source_locator="docx:p12",
            source_text="方案要求对相关原始记录进行医学复核。",
        )
    )
    rule = _rule(
        {"eq": {"field": "STATUS", "value": "review"}},
        status="candidate",
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_revision_id=fact.fact_revision_id,
    )
    lifecycle = MonitoringRuleLifecycleService(repository)
    draft = lifecycle.create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=[rule],
        created_by="rule_author",
    )
    confirmed = lifecycle.confirm_rule(
        rule.rule_revision_id,
        expected_state_version=1,
        confirmed_by="medical_manager",
    )
    pack = lifecycle.start_shadow(
        draft.rule_pack_id,
        started_by="shadow_operator",
    )
    return pack, confirmed


def _gold_case(
    rule: MonitoringRuleDefinition,
    *,
    project_id: str = "proj_alpha",
) -> RuleGoldStandardCase:
    source_hash = sha256(
        f"{project_id}:{rule.rule_revision_id}:gold".encode("utf-8")
    ).hexdigest()
    source_locator = f"listing:{source_hash}:sheet:EX:row:1"
    return RuleGoldStandardCase.create(
        project_id=project_id,
        rule_key=rule.rule_key,
        rule_revision_id=rule.rule_revision_id,
        source_entry_id=f"source-{source_hash[:16]}",
        source_content_sha256=source_hash,
        source_revision="source-revision-1",
        batch_revision="batch-revision-1",
        case_label=f"{project_id} confirmed shadow case",
        input_record={"SUBJID": "GOLD-01", "STATUS": "review"},
        observed_domains=["EX"],
        expected_match=True,
        medical_rationale="原始记录满足确定性复核条件。",
        evidence_locators=[source_locator],
        source_row_bindings=[
            RuleGoldSourceRowBinding.create(
                business_key="synthetic:EX:1",
                domain="EX",
                source_locator=source_locator,
                row_fingerprint=sha256(source_locator.encode("utf-8")).hexdigest(),
                record_roles=("current",),
                field_bindings=(
                    RuleGoldRecordFieldBinding.create(
                        record_role="current",
                        record_field="SUBJID",
                        source_field="SUBJID",
                    ),
                ),
            )
        ],
    )


def test_repository_case_is_trusted_but_not_p7c_release_eligible() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        pack, rule = _stored_shadow_pack(repository)
        repository.store_gold_cases([_gold_case(rule)])

        run = MonitoringProtocolRuleService(
            repository
        ).run_shadow_validation(
            rule_pack_id=pack.rule_pack_id,
            batch_id="trusted-shadow",
        )

        assert run.passed_count == 1
        assert run.case_source == "repository_registered"
        assert run.trusted_for_release is True
        assert run.release_gate_eligible is False
        assert run.persisted is True
        assert len(repository.shadow_runs("proj_alpha")) == 1


def test_cross_project_shadow_case_is_rejected() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        pack, rule = _stored_shadow_pack(repository)

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="another project",
        ):
            MonitoringProtocolRuleService(
                repository
            ).run_shadow_validation(
                rule_pack_id=pack.rule_pack_id,
                batch_id="foreign-shadow",
                cases=[_gold_case(rule, project_id="proj_other")],
            )


def test_external_same_project_cases_are_untrusted_and_not_persisted() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        pack, rule = _stored_shadow_pack(repository)

        run = MonitoringProtocolRuleService(
            repository
        ).run_shadow_validation(
            rule_pack_id=pack.rule_pack_id,
            batch_id="external-shadow",
            cases=[_gold_case(rule)],
        )

        assert run.passed_count == 1
        assert run.case_source == "external_development"
        assert run.trusted_for_release is False
        assert run.release_gate_eligible is False
        assert run.persisted is False
        assert run.repository_support_required is True
        assert "untrusted_external" in run.results[0].evidence_summary
        assert run.public_dict()["trusted_for_release"] is False
        assert run.public_dict()["repository_support_required"] is True
        assert repository.shadow_runs("proj_alpha") == ()
