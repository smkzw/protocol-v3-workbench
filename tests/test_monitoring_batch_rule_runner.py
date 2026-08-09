from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping

import pytest

from services.api.app.monitoring_batch_repository import (
    DiffReadyBatch,
    NormalizedRow,
)
from services.api.app.monitoring_batch_rule_runner import (
    BatchRuleRunResult,
    MonitoringBatchRuleRunner,
    MonitoringBatchRuleRunnerError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import MonitoringRuleDefinition


PROJECT_ID = "proj_batch_rule_runner"
PACK_ID = "monpack_batch_rule_runner"
SOURCE_HASH = "a" * 64


@dataclass(frozen=True)
class _PublishedPack:
    rule_pack_id: str = PACK_ID
    project_id: str = PROJECT_ID
    status: str = "published"


class _RuleRepository:
    def __init__(self, rules: Iterable[MonitoringRuleDefinition]):
        self.rules = tuple(rules)

    def rule_pack(
        self,
        rule_pack_id: str,
    ) -> tuple[_PublishedPack, tuple[MonitoringRuleDefinition, ...]]:
        assert rule_pack_id == PACK_ID
        return _PublishedPack(), self.rules


def _raw_lineage(domain: str, field: str) -> dict[str, Any]:
    return {
        "source_type": "raw_listing_field",
        "source_locator": (
            f"listing:{SOURCE_HASH}:sheet:{domain}:header:1:field:{field}"
        ),
    }


def _derived_lineage(
    *,
    field: str,
    input_roles: Iterable[str],
    expression: str,
    unit: str,
) -> dict[str, Any]:
    return {
        "source_type": "auditable_base_value",
        "input_field_roles": list(input_roles),
        "calculation_expression": expression,
        "unit_literal": unit,
        "source_locator": (
            f"listing:{SOURCE_HASH}:derived:field:{field}:header-source"
        ),
    }


def _rule(
    *,
    key: str,
    family: str,
    required_domains: tuple[str, ...],
    preconditions: Mapping[str, Any],
    trigger: Mapping[str, Any],
    lineage: Mapping[str, Mapping[str, Any]],
    executor: str = "field_predicate",
    clinical_domain: str = "",
) -> MonitoringRuleDefinition:
    return MonitoringRuleDefinition.create(
        project_id=PROJECT_ID,
        protocol_version_id="protov_batch_rule_runner",
        rule_key=key,
        rule_family=family,
        status="enabled",
        title=f"{key} test",
        executor=executor,
        required_domains=required_domains,
        preconditions=preconditions,
        trigger_expression=trigger,
        exclusions={"missing": {"field": "SUBJID"}},
        severity="high",
        confidence="deterministic",
        evidence_template="{SUBJID}",
        fact_revision_ids=[f"fact_{key.replace('.', '_')}"],
        source_entry_id="source_protocol",
        source_locator="docx:paragraph:10",
        source_text="用于批次规则运行器测试的已确认方案条款。",
        clinical_domain=clinical_domain,
        field_lineage=lineage,
    )


def _row(
    domain: str,
    business_key: str,
    data: Mapping[str, Any],
    row_number: int,
) -> NormalizedRow:
    payload = {"domain": domain, "data": dict(data)}
    return NormalizedRow(
        business_key=business_key,
        domain=domain,
        data=dict(data),
        source_locator={
            "source_entry_id": "source_listing",
            "source_content_sha256": SOURCE_HASH,
            "sheet": domain,
            "row": row_number,
        },
        row_fingerprint=sha256(repr(payload).encode("utf-8")).hexdigest(),
    )


def _batch(
    rows: Iterable[NormalizedRow],
    *,
    domains: Iterable[str],
) -> DiffReadyBatch:
    rows_value = tuple(rows)
    schema_fields = tuple(
        sorted(
            {
                (row.domain, field, row.domain)
                for row in rows_value
                for field in row.data
            }
        )
    )
    return DiffReadyBatch(
        batch_id="batch_rule_runner_001",
        project_id=PROJECT_ID,
        state="frozen",
        version=7,
        expected_domains=tuple(sorted(set(domains))),
        mapping_revision="maprev_003",
        source_bindings=(("source_listing", SOURCE_HASH),),
        source_hashes=(SOURCE_HASH,),
        rows=rows_value,
        schema_fields=schema_fields,
    )


def _runner(*rules: MonitoringRuleDefinition) -> MonitoringBatchRuleRunner:
    repository = _RuleRepository(rules)
    return MonitoringBatchRuleRunner(
        MonitoringProtocolRuleService(repository)  # type: ignore[arg-type]
    )


def _capabilities(**states: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "capability_id": capability_id,
            "state": state,
            "blocking_finding_group_ids": (
                ["finding-test"] if state == "blocked_by_quality" else []
            ),
            "limitation_codes": (
                [f"{capability_id}_limited"]
                if state != "ready"
                else []
            ),
        }
        for capability_id, state in sorted(states.items())
    )


def test_rule_result_round_trip_validates_persisted_output_hash() -> None:
    rule = _rule(
        key="ae.roundtrip",
        family="ae_mh_missing_review",
        required_domains=("AE",),
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={"eq": {"field": "AETERM", "value": "头痛"}},
        lineage={
            "subject": {
                "domain": "AE",
                "field": "SUBJID",
                "lineage": _raw_lineage("AE", "SUBJID"),
            },
            "term": {
                "domain": "AE",
                "field": "AETERM",
                "lineage": _raw_lineage("AE", "AETERM"),
            },
        },
    )
    result = _runner(rule).run(
        _batch(
            (_row("AE", "AE|S001|1", {"SUBJID": "S001", "AETERM": "头痛"}, 2),),
            domains=("AE",),
        ),
        rule_pack_id=PACK_ID,
    )

    restored = BatchRuleRunResult.from_dict(result.to_dict())

    assert restored == result
    corrupted = result.to_dict()
    corrupted["candidates"][0]["evidence_summary"] = "被篡改的证据"
    with pytest.raises(
        MonitoringBatchRuleRunnerError,
        match="output hash validation",
    ):
        BatchRuleRunResult.from_dict(corrupted)


@pytest.mark.parametrize("malformed", (int("1" * 64), "A" * 64, " " + "a" * 64))
def test_rule_result_rejects_noncanonical_persisted_output_hash(malformed: object) -> None:
    rule = _rule(
        key="ae.raw-output-hash",
        family="ae_mh_missing_review",
        required_domains=("AE",),
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={"eq": {"field": "AETERM", "value": "头痛"}},
        lineage={
            "subject": {
                "domain": "AE",
                "field": "SUBJID",
                "lineage": _raw_lineage("AE", "SUBJID"),
            },
            "term": {
                "domain": "AE",
                "field": "AETERM",
                "lineage": _raw_lineage("AE", "AETERM"),
            },
        },
    )
    result = _runner(rule).run(
        _batch(
            (_row("AE", "AE|S001|1", {"SUBJID": "S001", "AETERM": "头痛"}, 2),),
            domains=("AE",),
        ),
        rule_pack_id=PACK_ID,
    )
    corrupted = result.to_dict()
    corrupted["output_sha256"] = malformed

    with pytest.raises(
        MonitoringBatchRuleRunnerError,
        match="output hash is noncanonical",
    ):
        BatchRuleRunResult.from_dict(corrupted)


def _ae_mh_rule() -> MonitoringRuleDefinition:
    return _rule(
        key="ae_mh.batch_cross_domain",
        family="ae_mh_missing_review",
        required_domains=("AE", "MH"),
        executor="cross_record",
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={
            "no_corresponding_record": {
                "domain": "MH",
                "match": [
                    {
                        "related_field": "MHTERM",
                        "current_field": "AETERM",
                    }
                ],
            }
        },
        lineage={
            "ae_subject": {
                "field": "SUBJID",
                "domain": "AE",
                "lineage": _raw_lineage("AE", "SUBJID"),
            },
            "ae_term": {
                "field": "AETERM",
                "domain": "AE",
                "lineage": _raw_lineage("AE", "AETERM"),
            },
            "mh_subject": {
                "field": "SUBJID",
                "domain": "MH",
                "lineage": _raw_lineage("MH", "SUBJID"),
            },
            "mh_term": {
                "field": "MHTERM",
                "domain": "MH",
                "lineage": _raw_lineage("MH", "MHTERM"),
            },
        },
    )


def _ae_first_last_ex_rule() -> MonitoringRuleDefinition:
    return _rule(
        key="ae.batch_first_last_actual_dose",
        family="cross_domain_consistency",
        clinical_domain="safety",
        required_domains=("AE", "EX"),
        executor="cross_record",
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={
            "date_compare": {
                "field": "AESTDAT",
                "other_field": "FIRST_EXDAT",
                "relation": "before",
            }
        },
        lineage={
            "ae_subject": {
                "field": "SUBJID",
                "domain": "AE",
                "lineage": _raw_lineage("AE", "SUBJID"),
            },
            "ae_date": {
                "field": "AESTDAT",
                "domain": "AE",
                "lineage": _raw_lineage("AE", "AESTDAT"),
            },
            "ex_date": {
                "field": "EXDAT",
                "domain": "EX",
                "lineage": _raw_lineage("EX", "EXDAT"),
            },
            "first_ex": {
                "field": "FIRST_EXDAT",
                "domain": "AE",
                "lineage": _derived_lineage(
                    field="FIRST_EXDAT",
                    input_roles=("ex_date",),
                    expression="minimum(ex_date)",
                    unit="ISO-8601 date",
                ),
            },
            "last_ex": {
                "field": "LAST_EXDAT",
                "domain": "AE",
                "lineage": _derived_lineage(
                    field="LAST_EXDAT",
                    input_roles=("ex_date",),
                    expression="maximum(ex_date)",
                    unit="ISO-8601 date",
                ),
            },
        },
    )


def _lab_delta_rule() -> MonitoringRuleDefinition:
    return _rule(
        key="lab.batch_absolute_delta",
        family="data_quality",
        clinical_domain="data_quality",
        required_domains=("LB",),
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={"gt": {"field": "ABS_DELTA", "value": 0}},
        lineage={
            "lb_subject": {
                "field": "SUBJID",
                "domain": "LB",
                "lineage": _raw_lineage("LB", "SUBJID"),
            },
            "raw_result": {
                "field": "LBORRESN",
                "domain": "LB",
                "lineage": _raw_lineage("LB", "LBORRESN"),
            },
            "raw_reference": {
                "field": "LBORNRHI",
                "domain": "LB",
                "lineage": _raw_lineage("LB", "LBORNRHI"),
            },
            "absolute_delta": {
                "field": "ABS_DELTA",
                "domain": "LB",
                "lineage": _derived_lineage(
                    field="ABS_DELTA",
                    input_roles=("raw_result", "raw_reference"),
                    expression="abs(raw_result - raw_reference)",
                    unit="IU/L",
                ),
            },
        },
    )


def _study_treatment_rule() -> MonitoringRuleDefinition:
    return _rule(
        key="study_treatment.batch_ex_only",
        family="study_treatment_change",
        clinical_domain="study_treatment",
        required_domains=("EX",),
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={"eq": {"field": "EXTRT", "value": "研究药物A"}},
        lineage={
            "ex_subject": {
                "field": "SUBJID",
                "domain": "EX",
                "lineage": _raw_lineage("EX", "SUBJID"),
            },
            "ex_treatment": {
                "field": "EXTRT",
                "domain": "EX",
                "lineage": _raw_lineage("EX", "EXTRT"),
            },
        },
    )


def _cm_visit_rule() -> MonitoringRuleDefinition:
    return _rule(
        key="cm.batch_visit_boundary",
        family="cross_domain_consistency",
        clinical_domain="protocol_deviation",
        required_domains=("CM", "SV"),
        executor="temporal",
        preconditions={"exists": {"field": "SUBJID"}},
        trigger={
            "date_compare": {
                "field": "CMSTDAT",
                "other_field": "VISDAT",
                "relation": "after",
            }
        },
        lineage={
            "cm_subject": {
                "field": "SUBJID",
                "domain": "CM",
                "lineage": _raw_lineage("CM", "SUBJID"),
            },
            "cm_start": {
                "field": "CMSTDAT",
                "domain": "CM",
                "lineage": _raw_lineage("CM", "CMSTDAT"),
            },
            "visit_date": {
                "field": "VISDAT",
                "domain": "SV",
                "lineage": _raw_lineage("SV", "VISDAT"),
            },
        },
    )


def test_cross_domain_records_are_joined_within_subject_only() -> None:
    batch = _batch(
        (
            _row("AE", "AE|A|1", {"SUBJID": "A", "AETERM": "头痛"}, 2),
            _row("MH", "MH|A|1", {"SUBJID": "A", "MHTERM": "高血压"}, 2),
            _row("AE", "AE|B|1", {"SUBJID": "B", "AETERM": "头痛"}, 3),
            _row("MH", "MH|B|1", {"SUBJID": "B", "MHTERM": "头痛"}, 3),
        ),
        domains=("AE", "MH"),
    )

    result = _runner(_ae_mh_rule()).run(batch, rule_pack_id=PACK_ID)

    assert [(item.subject_id, item.current_business_key) for item in result.candidates] == [
        ("A", "AE|A|1")
    ]
    candidate = result.candidates[0]
    related = candidate.evaluation["evidence"]["related_records"]["MH"]
    assert [item["raw_data"]["SUBJID"] for item in related] == ["A"]
    assert related[0]["source_locators"] == [
        {
            "source_entry_id": "source_listing",
            "source_content_sha256": SOURCE_HASH,
            "sheet": "MH",
            "row": 2,
        }
    ]


def test_minimum_and_maximum_derived_dates_preserve_all_input_locators() -> None:
    batch = _batch(
        (
            _row(
                "AE",
                "AE|A|1",
                {"SUBJID": "A", "AESTDAT": "2025-01-02"},
                2,
            ),
            _row(
                "EX",
                "EX|A|1",
                {"SUBJID": "A", "EXDAT": "2025-01-10"},
                2,
            ),
            _row(
                "EX",
                "EX|A|2",
                {"SUBJID": "A", "EXDAT": "2025-02-10"},
                3,
            ),
        ),
        domains=("AE", "EX"),
    )

    result = _runner(_ae_first_last_ex_rule()).run(
        batch,
        rule_pack_id=PACK_ID,
    )

    assert len(result.candidates) == 1
    raw = result.candidates[0].evaluation["evidence"]["current_record"][
        "raw_data"
    ]
    assert raw["FIRST_EXDAT"] == "2025-01-10"
    assert raw["LAST_EXDAT"] == "2025-02-10"
    assert raw["__auditable_base_values__"]["FIRST_EXDAT"][
        "input_locators"
    ] == [
        {
            "source_entry_id": "source_listing",
            "source_content_sha256": SOURCE_HASH,
            "sheet": "EX",
            "row": 2,
        },
        {
            "source_entry_id": "source_listing",
            "source_content_sha256": SOURCE_HASH,
            "sheet": "EX",
            "row": 3,
        },
    ]


def test_arithmetic_and_abs_derive_deterministic_candidate() -> None:
    batch = _batch(
        (
            _row(
                "LB",
                "LB|A|1",
                {
                    "SUBJID": "A",
                    "LBORRESN": "25",
                    "LBORNRHI": "<20",
                },
                2,
            ),
        ),
        domains=("LB",),
    )

    result = _runner(_lab_delta_rule()).run(batch, rule_pack_id=PACK_ID)

    assert len(result.candidates) == 1
    raw = result.candidates[0].evaluation["evidence"]["current_record"][
        "raw_data"
    ]
    assert raw["ABS_DELTA"] == "5"
    assert raw["__auditable_base_values__"]["ABS_DELTA"][
        "calculation_expression"
    ] == "abs(raw_result - raw_reference)"


def test_missing_field_is_indeterminate_and_diagnostic_not_candidate() -> None:
    batch = _batch(
        (
            _row(
                "LB",
                "LB|A|1",
                {"SUBJID": "A", "LBORRESN": "25"},
                2,
            ),
        ),
        domains=("LB",),
    )

    result = _runner(_lab_delta_rule()).run(batch, rule_pack_id=PACK_ID)

    assert result.candidates == ()
    assert {"raw_field_missing", "derived_input_missing", "evaluation_indeterminate"}.issubset(
        {item.code for item in result.diagnostics}
    )


def test_cm_never_impersonates_study_treatment_domain() -> None:
    batch = _batch(
        (
            _row(
                "CM",
                "CM|A|1",
                {
                    "SUBJID": "A",
                    "CMTRT": "研究药物A",
                    "EXTRT": "研究药物A",
                },
                2,
            ),
        ),
        domains=("CM",),
    )

    result = _runner(_study_treatment_rule()).run(
        batch,
        rule_pack_id=PACK_ID,
    )

    assert result.candidates == ()
    diagnostic = next(
        item for item in result.diagnostics if item.code == "missing_anchor_domain"
    )
    assert diagnostic.current_domain == "EX"
    assert diagnostic.details["available_domains"] == ["CM"]
    assert diagnostic.details["study_treatment_domains_are_distinct"] is True


def test_unique_cross_domain_current_value_is_used_with_its_source() -> None:
    batch = _batch(
        (
            _row(
                "CM",
                "CM|A|1",
                {"SUBJID": "A", "CMSTDAT": "2025-01-20"},
                2,
            ),
            _row(
                "SV",
                "SV|A|1",
                {"SUBJID": "A", "VISDAT": "2025-01-10"},
                2,
            ),
        ),
        domains=("CM", "SV"),
    )

    result = _runner(_cm_visit_rule()).run(batch, rule_pack_id=PACK_ID)

    assert len(result.candidates) == 1
    evidence = result.candidates[0].evaluation["evidence"]["current_record"]
    assert evidence["raw_data"]["VISDAT"] == "2025-01-10"
    assert {
        "source_entry_id": "source_listing",
        "source_content_sha256": SOURCE_HASH,
        "sheet": "SV",
        "row": 2,
    } in evidence["source_locators"]


def test_missing_required_related_domain_is_indeterminate() -> None:
    batch = _batch(
        (_row("AE", "AE|A|1", {"SUBJID": "A", "AETERM": "头痛"}, 2),),
        domains=("AE",),
    )

    result = _runner(_ae_mh_rule()).run(batch, rule_pack_id=PACK_ID)

    assert result.candidates == ()
    diagnostic = next(
        item
        for item in result.diagnostics
        if item.code == "evaluation_indeterminate"
    )
    assert diagnostic.details["missing_required_domains"] == ["MH"]


def test_repeated_run_is_byte_stable_and_bound_to_batch_and_rule_revision() -> None:
    batch = _batch(
        (
            _row(
                "LB",
                "LB|A|1",
                {
                    "SUBJID": "A",
                    "LBORRESN": "25",
                    "LBORNRHI": "20",
                },
                2,
            ),
        ),
        domains=("LB",),
    )
    runner = _runner(_lab_delta_rule())

    first = runner.run(batch, rule_pack_id=PACK_ID)
    second = runner.run(batch, rule_pack_id=PACK_ID)

    assert first == second
    assert first.output_sha256 == second.output_sha256
    assert first.candidates[0].batch_id == batch.batch_id
    assert first.candidates[0].rule_revision_id == first.rule_revision_ids[0]


def test_blocked_capability_skips_rule_with_explicit_incomplete_diagnostic() -> None:
    batch = _batch(
        (
            _row(
                "EX",
                "EX|A|1",
                {"SUBJID": "A", "EXTRT": "研究药物A"},
                2,
            ),
        ),
        domains=("EX",),
    )

    result = _runner(_study_treatment_rule()).run(
        batch,
        rule_pack_id=PACK_ID,
        capability_states=_capabilities(
            protocol_medication_rules="blocked_by_quality",
        ),
    )

    assert result.candidates == ()
    diagnostic = next(
        item
        for item in result.diagnostics
        if item.code == "monitoring_capability_unavailable"
    )
    assert diagnostic.details["capability_id"] == "protocol_medication_rules"
    assert diagnostic.details["rule_execution_skipped"] is True


def test_limited_capability_runs_its_safe_rule_subset() -> None:
    batch = _batch(
        (
            _row(
                "CM",
                "CM|A|1",
                {"SUBJID": "A", "CMSTDAT": "2025-01-20"},
                2,
            ),
            _row(
                "SV",
                "SV|A|1",
                {"SUBJID": "A", "VISDAT": "2025-01-10"},
                2,
            ),
        ),
        domains=("CM", "SV"),
    )

    result = _runner(_cm_visit_rule()).run(
        batch,
        rule_pack_id=PACK_ID,
        capability_states=_capabilities(
            precise_temporal_rules="limited",
            protocol_medication_rules="ready",
        ),
    )

    assert len(result.candidates) == 1
    assert not any(
        item.code.startswith("monitoring_capability_")
        for item in result.diagnostics
    )
