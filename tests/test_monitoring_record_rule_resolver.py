from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from services.api.app.monitoring_batch_repository import (
    DiffReadyBatch,
    FrozenBatchMappingContract,
    NormalizedRow,
)
from services.api.app.monitoring_batch_rule_runner import MonitoringBatchRuleRunner
from services.api.app.monitoring_daily_run_repository import (
    DailyRunInput,
    DailyRunOutputConflictError,
    MonitoringDailyRunRepositoryError,
    MonitoringDailyRunRepository,
    _content_sha256,
)
from services.api.app.monitoring_daily_run_service import (
    MonitoringDailyRunService,
    MonitoringDailyRunServiceError,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    ProtocolApplicabilityConflictError,
    ProtocolApplicabilityUnresolvedError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringRuleDefinition,
)
from services.api.app.monitoring_record_rule_resolver import (
    MonitoringRecordRuleResolver,
    RecordRuleAggregateIdentityError,
)
from tests.test_monitoring_protocol_rule_repository_hardening import (
    _assignment,
    _site_version,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _publish_pack,
    _rule,
)


def _row(
    domain: str,
    business_key: str,
    *,
    site: str,
    subject: str,
    event_date: str,
    description: str = "",
    row_number: int,
) -> NormalizedRow:
    data = {
        "SITEID": site,
        "SUBJID": subject,
        "visit": "W1",
    }
    if domain == "EX":
        data.update(
            {
                "EXDAT": event_date,
                "date": event_date,
                "EXDESC": description,
            }
        )
    elif domain == "CM":
        data.update({"CMSTDAT": event_date, "CMTRT": description})
    return NormalizedRow(
        business_key=business_key,
        domain=domain,
        data=data,
        source_locator={
            "source_entry_id": "source-listing",
            "source_content_sha256": "f" * 64,
            "sheet": domain,
            "row": row_number,
        },
        row_fingerprint=(f"{row_number:x}" * 64)[:64],
    )


def _mapping_contract(
    batch: DiffReadyBatch,
    *,
    fields: tuple[dict[str, object], ...] | None = None,
    mapping_revision: str | None = None,
    mapping_sha256: str = "1" * 64,
    mapping_content_sha256: str = "2" * 64,
) -> FrozenBatchMappingContract:
    if fields is None:
        fields = tuple(
            {
                "domain": domain,
                "source_field": source_field,
                "recommended_role": role,
                "field_kind": "source_metadata"
                if role in {"site_identifier", "subject_identifier"}
                else "source_collected",
            }
            for domain in sorted({row.domain.upper() for row in batch.rows})
            for source_field, role in (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                (
                    "CMSTDAT" if domain == "CM" else "EXDAT",
                    "conmed_start_date"
                    if domain == "CM"
                    else "actual_dose_date",
                ),
            )
        )
    return FrozenBatchMappingContract(
        schema_version="monitoring_project_mapping_v2",
        batch_id=batch.batch_id,
        project_id=batch.project_id,
        batch_version=batch.version,
        mapping_revision=mapping_revision or str(batch.mapping_revision),
        mapping_sha256=mapping_sha256,
        mapping_content_sha256=mapping_content_sha256,
        source_batch_id="mapping-source-batch",
        source_profile_sha256="3" * 64,
        fields=fields,
        semantic_quality_report_sha256="4" * 64,
        capability_manifest_sha256="5" * 64,
        activation_disposition="activate_full",
        effective_capabilities_sha256="6" * 64,
        effective_capabilities=(
            "raw_source_review",
            "subject_timeline",
            "patient_profile",
            "ae_mh_reconciliation",
            "standard_coding_rules",
            "precise_temporal_rules",
            "lab_ctcae_rules",
            "protocol_medication_rules",
            "ip_exposure_adherence",
            "scale_recalculation",
        ),
        capability_states=tuple(
            {
                "capability_id": capability_id,
                "state": "ready",
                "blocking_finding_group_ids": [],
                "limitation_codes": [],
            }
            for capability_id in (
                "raw_source_review",
                "subject_timeline",
                "patient_profile",
                "ae_mh_reconciliation",
                "standard_coding_rules",
                "precise_temporal_rules",
                "lab_ctcae_rules",
                "protocol_medication_rules",
                "ip_exposure_adherence",
                "scale_recalculation",
            )
        ),
    )


_RULE_IDENTITY = {
    "mapping_revision": "mapping-v1",
    "mapping_content_sha256": "2" * 64,
    "capability_manifest_sha256": "5" * 64,
    "effective_capabilities_sha256": "6" * 64,
}


def _identified_rule(rule: MonitoringRuleDefinition, **identity_overrides):
    """Rebuild a rule through create() with immutable mapping identity."""
    identity = {**_RULE_IDENTITY, **identity_overrides}
    return MonitoringRuleDefinition.create(
        project_id=rule.project_id,
        protocol_version_id=rule.protocol_version_id,
        rule_key=rule.rule_key,
        rule_family=rule.rule_family,
        status=rule.status,
        title=rule.title,
        executor=rule.executor,
        required_domains=rule.required_domains,
        preconditions=rule.preconditions,
        trigger_expression=rule.trigger_expression,
        exclusions=rule.exclusions,
        severity=rule.severity,
        confidence=rule.confidence,
        evidence_template=rule.evidence_template,
        fact_revision_ids=rule.fact_revision_ids,
        source_entry_id=rule.source_entry_id,
        source_locator=rule.source_locator,
        source_text=rule.source_text,
        source_refs=rule.source_refs,
        field_lineage=rule.field_lineage,
        clinical_domain=rule.clinical_domain,
        mapping_revision=identity["mapping_revision"],
        mapping_content_sha256=identity["mapping_content_sha256"],
        capability_manifest_sha256=identity["capability_manifest_sha256"],
        effective_capabilities_sha256=identity["effective_capabilities_sha256"],
    )


def _runtime(
    tmp_path: Path,
    *,
    identified: bool = True,
    rule_identity: dict[str, str] | None = None,
    second_rule_identity: dict[str, str] | None = None,
):
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version_1 = repository.register_protocol_version(
        _site_version("proj_record_runtime", "V1.0", "a")
    )
    version_2 = repository.register_protocol_version(
        _site_version("proj_record_runtime", "V2.0", "b")
    )
    assignments = (
        repository.create_applicability_assignment(
            _assignment(
                version_1,
                centre_id="001",
                effective_from="2026-01-01",
                effective_to="2026-12-31",
            )
        ),
        repository.create_applicability_assignment(
            _assignment(
                version_2,
                centre_id="002",
                effective_from="2026-01-01",
                effective_to="2026-12-31",
            )
        ),
        repository.create_applicability_assignment(
            _assignment(
                version_2,
                centre_id="001",
                subject_id="S009",
                effective_from="2026-01-15",
                effective_to="2026-01-20",
            )
        ),
    )
    for assignment in assignments:
        repository.transition_applicability_assignment(
            assignment.project_id,
            assignment.assignment_id,
            expected_state_version=1,
            status="confirmed",
            actor="medical_manager",
        )
    fact_1 = repository.store_fact(_fact(version_1))
    fact_2 = repository.store_fact(_fact(version_2))
    rule_1 = _rule(version_1, fact_1)
    rule_2 = _rule(version_2, fact_2)
    identity = dict(rule_identity or _RULE_IDENTITY)
    # Rules with empty identity can no longer be confirmed or published
    # through the repository gates; publish with a complete identity first,
    # then blank the stored columns directly to simulate a legacy pack.
    blanked_fields = (
        tuple(_RULE_IDENTITY)
        if not identified
        else tuple(field for field in _RULE_IDENTITY if not identity.get(field))
    )
    publish_identity = {
        **identity,
        **{field: _RULE_IDENTITY[field] for field in blanked_fields},
    }
    rule_1 = _identified_rule(rule_1, **publish_identity)
    rule_2 = _identified_rule(
        rule_2,
        **{**publish_identity, **(second_rule_identity or {})},
    )
    pack_1 = _publish_pack(repository, version_1, [rule_1])
    pack_2 = _publish_pack(repository, version_2, [rule_2])
    if blanked_fields:
        connection = sqlite3.connect(repository.db_path)
        try:
            assignments = ", ".join(
                f"{field} = ''" for field in blanked_fields
            )
            connection.execute(
                f"UPDATE monitoring_rule_definitions SET {assignments}",
            )
            connection.commit()
        finally:
            connection.close()
    rows = (
        _row(
            "EX",
            "EX|001|S001|1",
            site="001",
            subject="S001",
            event_date="2026-01-10",
            description="漏服",
            row_number=2,
        ),
        _row(
            "EX",
            "EX|002|S002|1",
            site="002",
            subject="S002",
            event_date="2026-01-10",
            description="漏服",
            row_number=3,
        ),
        _row(
            "CM",
            "CM|001|S009|1",
            site="001",
            subject="S009",
            event_date="2026-01-10",
            description="甲氨蝶呤",
            row_number=4,
        ),
        _row(
            "EX",
            "EX|001|S009|1",
            site="001",
            subject="S009",
            event_date="2026-01-16",
            description="漏服",
            row_number=5,
        ),
        _row(
            "EX",
            "EX|003|S003|1",
            site="003",
            subject="S003",
            event_date="2026-01-10",
            description="漏服",
            row_number=6,
        ),
    )
    batch = DiffReadyBatch(
        batch_id="batch-record-resolution",
        project_id="proj_record_runtime",
        state="frozen",
        version=7,
        expected_domains=("CM", "EX"),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=rows,
        schema_fields=tuple(
            sorted(
                {
                    (row.domain, field, row.domain)
                    for row in rows
                    for field in row.data
                }
            )
        ),
    )
    resolver = MonitoringRecordRuleResolver(repository)
    runner = MonitoringBatchRuleRunner(MonitoringProtocolRuleService(repository))
    return repository, resolver, runner, batch, pack_1, pack_2, assignments


def test_record_resolution_selects_exact_assignment_and_pack_per_anchor(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, pack_1, pack_2, assignments = _runtime(
        tmp_path
    )

    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    by_key = {item.current_business_key: item for item in plan.bindings}

    assert len(plan.bindings) == 4
    assert len(plan.diagnostics) == 1
    assert plan.diagnostics[0].code == "monitoring_protocol_applicability_unresolved"
    assert by_key["EX|001|S001|1"].rule_pack_id == pack_1.rule_pack_id
    assert by_key["EX|002|S002|1"].rule_pack_id == pack_2.rule_pack_id
    assert by_key["CM|001|S009|1"].rule_pack_id == pack_1.rule_pack_id
    assert by_key["EX|001|S009|1"].rule_pack_id == pack_2.rule_pack_id
    assert by_key["EX|001|S009|1"].assignment_id == assignments[2].assignment_id
    assert by_key["EX|001|S009|1"].assignment_state_version == 2
    assert {
        item.rule_pack_content_sha256 for item in plan.bindings
    } == {pack_1.content_sha256, pack_2.content_sha256}

    runner.run = Mock(wraps=runner.run)
    result = resolver.run_resolved(batch, plan, runner)
    assert runner.run.call_count == 2
    assert result["rule_pack_id"] == ""
    assert result["rule_pack_ids"] == sorted(
        [pack_1.rule_pack_id, pack_2.rule_pack_id]
    )
    assert result["resolved_record_count"] == 4
    assert result["failed_resolution_count"] == 1
    assert result["analysis_complete"] is False
    assert {
        candidate["protocol_resolution"]["rule_pack_id"]
        for candidate in result["candidates"]
    } == {pack_1.rule_pack_id, pack_2.rule_pack_id}
    assert all(
        candidate["current_business_key"] != "EX|003|S003|1"
        for candidate in result["candidates"]
    )


def test_record_resolution_never_calls_applicability_without_exact_event_date(
    tmp_path: Path,
) -> None:
    repository = Mock()
    repository.list_rule_packs.return_value = ()
    resolver = MonitoringRecordRuleResolver(repository)
    row = _row(
        "EX",
        "EX|001|S001|1",
        site="001",
        subject="S001",
        event_date="",
        description="漏服",
        row_number=2,
    )
    batch = DiffReadyBatch(
        batch_id="batch-missing-date",
        project_id="proj_record_runtime",
        state="frozen",
        version=1,
        expected_domains=("EX",),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=(row,),
        schema_fields=(("EX", "EXDESC", "EX"),),
    )

    plan = resolver.resolve_batch(batch, _mapping_contract(batch))

    assert not plan.bindings
    assert plan.diagnostics[0].code == "monitoring_record_event_date_missing"
    repository.resolve_protocol_applicability.assert_not_called()


def test_record_resolution_allows_omitted_subject_for_centre_assignment(
    tmp_path: Path,
) -> None:
    _repository, resolver, _runner, batch, pack_1, _pack_2, assignments = _runtime(
        tmp_path
    )
    centre_only = _row(
        "EX",
        "EX|001|NO-SUBJECT|1",
        site="001",
        subject="",
        event_date="2026-01-10",
        description="中心级记录",
        row_number=2,
    )

    centre_batch = replace(batch, rows=(centre_only,))
    plan = resolver.resolve_batch(
        centre_batch,
        _mapping_contract(centre_batch),
    )

    assert not plan.diagnostics
    assert len(plan.bindings) == 1
    binding = plan.bindings[0]
    assert binding.subject_id == ""
    assert binding.assignment_id == assignments[0].assignment_id
    assert binding.rule_pack_id == pack_1.rule_pack_id


@pytest.mark.parametrize(
    ("data_updates", "expected_code"),
    (
        ({"EXDAT": "2026/01/10"}, "monitoring_record_event_date_invalid"),
        (
            {"EXDAT": "2026-01-10", "EXSTDTC": "2026-01-11"},
            "monitoring_record_event_date_conflict",
        ),
    ),
)
def test_record_resolution_closes_before_applicability_for_invalid_or_conflicting_date(
    tmp_path: Path,
    data_updates: dict[str, str],
    expected_code: str,
) -> None:
    repository = Mock()
    repository.list_rule_packs.return_value = ()
    resolver = MonitoringRecordRuleResolver(repository)
    original = _row(
        "EX",
        "EX|001|S001|1",
        site="001",
        subject="S001",
        event_date="2026-01-10",
        description="漏服",
        row_number=2,
    )
    row = replace(original, data={**original.data, **data_updates})
    batch = DiffReadyBatch(
        batch_id="batch-invalid-date",
        project_id="proj_record_runtime",
        state="frozen",
        version=1,
        expected_domains=("EX",),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=(row,),
        schema_fields=(("EX", "EXDAT", "EX"),),
    )

    mapping = _mapping_contract(batch)
    if "EXSTDTC" in data_updates:
        mapping = replace(
            mapping,
            fields=(
                *mapping.fields,
                {
                    "domain": "EX",
                    "source_field": "EXSTDTC",
                    "recommended_role": "exposure_start_date",
                    "field_kind": "source_collected",
                },
            ),
        )
    plan = resolver.resolve_batch(batch, mapping)

    assert not plan.bindings
    assert plan.diagnostics[0].code == expected_code
    repository.resolve_protocol_applicability.assert_not_called()


@pytest.mark.parametrize(
    ("centre_field", "subject_field", "date_field"),
    (
        ("VendorCentreCode", "VendorPatientKey", "DosePerformedOn"),
        ("研究中心编号", "项目受试者号", "实际给药日期"),
    ),
)
def test_record_resolution_uses_confirmed_custom_or_chinese_anchor_fields(
    tmp_path: Path,
    centre_field: str,
    subject_field: str,
    date_field: str,
) -> None:
    _repository, resolver, _runner, batch, pack_1, _pack_2, _assignments = (
        _runtime(tmp_path)
    )
    source = _row(
        "EX",
        "EX|CUSTOM|1",
        site="",
        subject="",
        event_date="",
        description="漏服",
        row_number=2,
    )
    row = replace(
        source,
        data={
            centre_field: "001",
            subject_field: "S001",
            date_field: "2026-01-10",
            "EXDESC": "漏服",
        },
    )
    custom_batch = replace(
        batch,
        rows=(row,),
        expected_domains=("EX",),
        schema_fields=tuple(
            ("EX", field, "EX")
            for field in (
                centre_field,
                subject_field,
                date_field,
                "EXDESC",
            )
        ),
    )
    mapping = _mapping_contract(
        custom_batch,
        fields=(
            {
                "domain": "EX",
                "source_field": centre_field,
                "recommended_role": "study_site_identifier",
                "field_kind": "source_metadata",
            },
            {
                "domain": "EX",
                "source_field": subject_field,
                "recommended_role": "study_subject_identifier",
                "field_kind": "source_metadata",
            },
            {
                "domain": "EX",
                "source_field": date_field,
                "recommended_role": "investigational_product_administration_date",
                "field_kind": "source_collected",
            },
        ),
    )

    plan = resolver.resolve_batch(custom_batch, mapping)

    assert not plan.diagnostics
    binding = plan.bindings[0]
    assert binding.rule_pack_id == pack_1.rule_pack_id
    assert binding.centre_id == "001"
    assert binding.subject_id == "S001"
    assert binding.event_date == "2026-01-10"
    assert binding.centre_source_fields == (centre_field,)
    assert binding.subject_source_fields == (subject_field,)
    assert binding.event_date_source_fields == (date_field,)
    assert binding.compatibility_fallback_roles == ()


def test_rux_business_date_ignores_pagelmdt_and_freezes_mapping_identity(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = (
        _runtime(tmp_path)
    )
    row = replace(
        batch.rows[0],
        data={
            **batch.rows[0].data,
            "EXDAT": "2026-01-10",
            "PAGELMDT": "2026-07-29T16:04:03",
        },
    )
    rux_batch = replace(
        batch,
        rows=(row,),
        expected_domains=("EX",),
    )
    mapping = _mapping_contract(
        rux_batch,
        fields=(
            {
                "domain": "EX",
                "source_field": "SITEID",
                "recommended_role": "site_identifier",
                "field_kind": "source_metadata",
            },
            {
                "domain": "EX",
                "source_field": "SUBJID",
                "recommended_role": "subject_identifier",
                "field_kind": "source_metadata",
            },
            {
                "domain": "EX",
                "source_field": "EXDAT",
                "recommended_role": "actual_dose_date",
                "field_kind": "source_collected",
            },
            {
                "domain": "EX",
                "source_field": "PAGELMDT",
                "recommended_role": "page_last_modified_datetime",
                "field_kind": "source_metadata",
            },
        ),
        mapping_sha256="4" * 64,
        mapping_content_sha256="5" * 64,
    )

    plan = resolver.resolve_batch(rux_batch, mapping)
    result = resolver.run_resolved(rux_batch, plan, runner)

    assert not plan.diagnostics
    assert plan.bindings[0].event_date == "2026-01-10"
    assert plan.bindings[0].event_date_source_fields == ("EXDAT",)
    assert result["field_mapping_identity"] == mapping.identity_dict()
    assert plan.field_mapping_identity["mapping_sha256"] == "4" * 64
    assert plan.field_mapping_identity["mapping_content_sha256"] == "5" * 64


@pytest.mark.parametrize(
    ("fields", "data_updates", "expected_code"),
    (
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                ("EXDAT", "source_modification_date"),
            ),
            {},
            "monitoring_record_event_date_mapping_missing",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                ("EXDAT", "actual_dose_date"),
                ("EXSTDTC", "exposure_start_date"),
            ),
            {"EXSTDTC": "2026-01-11"},
            "monitoring_record_event_date_conflict",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                ("PAGELMDT", "actual_dose_date"),
            ),
            {"PAGELMDT": "2026-01-10"},
            "monitoring_record_event_date_mapping_excluded",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                ("DOB", "event_date"),
            ),
            {"DOB": "1985-03-12"},
            "monitoring_record_event_date_mapping_excluded",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_identifier"),
                ("LASTMODIFIEDDATE", "event_date"),
            ),
            {"LASTMODIFIEDDATE": "2026-07-29"},
            "monitoring_record_event_date_mapping_excluded",
        ),
    ),
)
def test_record_resolution_closes_on_missing_conflicting_or_excluded_mapping(
    tmp_path: Path,
    fields: tuple[tuple[str, str], ...],
    data_updates: dict[str, str],
    expected_code: str,
) -> None:
    repository = Mock()
    resolver = MonitoringRecordRuleResolver(repository)
    original = _row(
        "EX",
        "EX|MAPPING-CLOSED|1",
        site="001",
        subject="S001",
        event_date="2026-01-10",
        row_number=2,
    )
    row = replace(original, data={**original.data, **data_updates})
    batch = DiffReadyBatch(
        batch_id="batch-mapping-closed",
        project_id="proj_record_runtime",
        state="frozen",
        version=1,
        expected_domains=("EX",),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=(row,),
    )
    mapping = _mapping_contract(
        batch,
        fields=tuple(
            {
                "domain": "EX",
                "source_field": source_field,
                "recommended_role": role,
                "field_kind": "source_metadata"
                if role.endswith("identifier")
                else "source_collected",
            }
            for source_field, role in fields
        ),
    )

    plan = resolver.resolve_batch(batch, mapping)

    assert not plan.bindings
    assert plan.diagnostics[0].code == expected_code
    repository.resolve_protocol_applicability.assert_not_called()


def test_record_resolution_audits_closed_compatibility_fallback(
    tmp_path: Path,
) -> None:
    _repository, resolver, _runner, batch, _pack_1, _pack_2, _assignments = (
        _runtime(tmp_path)
    )
    compatibility_batch = replace(
        batch,
        rows=(batch.rows[0],),
        expected_domains=("EX",),
    )
    mapping = _mapping_contract(
        compatibility_batch,
        fields=(
            {
                "domain": "EX",
                "source_field": "EXDESC",
                "recommended_role": "exposure_description",
                "field_kind": "source_collected",
            },
        ),
    )

    plan = resolver.resolve_batch(compatibility_batch, mapping)

    assert not plan.diagnostics
    binding = plan.bindings[0]
    assert binding.compatibility_fallback_roles == (
        "centre",
        "subject",
        "event_date",
    )
    assert binding.centre_source_fields == ("SITEID",)
    assert binding.subject_source_fields == ("SUBJID",)
    assert binding.event_date_source_fields == ("EXDAT",)


@pytest.mark.parametrize(
    ("fields", "data_updates", "expected_code"),
    (
        (
            (
                ("SITEID", "site_display_label"),
                ("SUBJID", "subject_identifier"),
                ("EXDAT", "actual_dose_date"),
            ),
            {},
            "monitoring_record_centre_mapping_missing",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("CENTERID", "centre_identifier"),
                ("SUBJID", "subject_identifier"),
                ("EXDAT", "actual_dose_date"),
            ),
            {"CENTERID": "002"},
            "monitoring_record_centre_identifier_conflict",
        ),
        (
            (
                ("SITEID", "site_identifier"),
                ("SUBJID", "subject_display_label"),
                ("EXDAT", "actual_dose_date"),
            ),
            {},
            "monitoring_record_subject_mapping_missing",
        ),
    ),
)
def test_identifier_mapping_missing_or_conflict_fails_closed(
    fields: tuple[tuple[str, str], ...],
    data_updates: dict[str, str],
    expected_code: str,
) -> None:
    repository = Mock()
    resolver = MonitoringRecordRuleResolver(repository)
    original = _row(
        "EX",
        "EX|IDENTITY-CLOSED|1",
        site="001",
        subject="S001",
        event_date="2026-01-10",
        row_number=2,
    )
    row = replace(original, data={**original.data, **data_updates})
    batch = DiffReadyBatch(
        batch_id="batch-identity-closed",
        project_id="proj_record_runtime",
        state="frozen",
        version=1,
        expected_domains=("EX",),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=(row,),
    )
    mapping = _mapping_contract(
        batch,
        fields=tuple(
            {
                "domain": "EX",
                "source_field": source_field,
                "recommended_role": role,
                "field_kind": "source_metadata"
                if "identifier" in role
                else "source_collected",
            }
            for source_field, role in fields
        ),
    )

    plan = resolver.resolve_batch(batch, mapping)

    assert not plan.bindings
    assert plan.diagnostics[0].code == expected_code
    repository.resolve_protocol_applicability.assert_not_called()


@pytest.mark.parametrize(
    ("lookup_error", "expected_code"),
    (
        (
            ProtocolApplicabilityUnresolvedError("no published pack"),
            "monitoring_record_rule_pack_unresolved",
        ),
        (
            ProtocolApplicabilityConflictError("multiple published packs"),
            "monitoring_record_rule_pack_conflict",
        ),
    ),
)
def test_record_resolution_returns_stable_diagnostic_for_pack_lookup_failure(
    tmp_path: Path,
    lookup_error: Exception,
    expected_code: str,
) -> None:
    repository = Mock()
    repository.resolve_protocol_applicability.return_value = SimpleNamespace(
        resolved=True,
        diagnostic_code="monitoring_protocol_applicability_resolved",
        diagnostic_message="resolved",
        protocol_version_id="protov-exact",
        assignment=SimpleNamespace(
            assignment_id="protoapp-exact",
            state_version=2,
        ),
    )
    repository.published_pack_for_protocol_version.side_effect = lookup_error
    resolver = MonitoringRecordRuleResolver(repository)
    row = _row(
        "EX",
        "EX|001|S001|1",
        site="001",
        subject="S001",
        event_date="2026-01-10",
        description="漏服",
        row_number=2,
    )
    batch = DiffReadyBatch(
        batch_id="batch-pack-failure",
        project_id="proj_record_runtime",
        state="frozen",
        version=1,
        expected_domains=("EX",),
        mapping_revision="mapping-v1",
        source_bindings=(("source-listing", "f" * 64),),
        source_hashes=("f" * 64,),
        rows=(row,),
        schema_fields=(("EX", "EXDAT", "EX"),),
    )

    plan = resolver.resolve_batch(batch, _mapping_contract(batch))

    assert not plan.bindings
    assert plan.diagnostics[0].code == expected_code
    assert plan.diagnostics[0].details == {
        "protocol_version_id": "protov-exact"
    }


def test_record_snapshot_rejects_assignment_or_pack_identity_tampering(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    payload["record_rule_resolutions"][0]["assignment_state_version"] += 1

    run_repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = run_repository.create_or_get(
        DailyRunInput(
            project_id=batch.project_id,
            batch_id=batch.batch_id,
            baseline_batch_id=None,
            batch_version=batch.version,
            mapping_revision=batch.mapping_revision,
            rule_pack_revision="",
            engine_version="monitoring-rule-engine/1",
            diff_algorithm_version="monitoring-diff/2",
            rule_resolution_mode="record_applicability",
            rule_identity_sha256="e" * 64,
        ),
        idempotency_key="record-mode-tamper",
    ).run
    rules = run_repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )

    with pytest.raises(
        DailyRunOutputConflictError,
        match="resolution identity hash",
    ):
        run_repository.save_rule_snapshot(
            rules.project_id,
            rules.run_id,
            input_sha256="a" * 64,
            payload=payload,
            expected_version=rules.version,
            actor="orchestrator",
        )


def test_record_snapshot_rejects_frozen_mapping_identity_tampering(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    payload["field_mapping_identity"]["mapping_sha256"] = "9" * 64

    run_repository = MonitoringDailyRunRepository(tmp_path / "mapping-daily.sqlite3")
    created = run_repository.create_or_get(
        DailyRunInput(
            project_id=batch.project_id,
            batch_id=batch.batch_id,
            baseline_batch_id=None,
            batch_version=batch.version,
            mapping_revision=batch.mapping_revision,
            rule_pack_revision="",
            engine_version="monitoring-rule-engine/1",
            diff_algorithm_version="monitoring-diff/2",
            rule_resolution_mode="record_applicability",
            rule_identity_sha256="e" * 64,
        ),
        idempotency_key="record-mapping-tamper",
    ).run
    rules = run_repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )

    with pytest.raises(
        DailyRunOutputConflictError,
        match="resolution identity hash",
    ):
        run_repository.save_rule_snapshot(
            rules.project_id,
            rules.run_id,
            input_sha256="a" * 64,
            payload=payload,
            expected_version=rules.version,
            actor="orchestrator",
        )


def test_record_snapshot_requires_explicit_optional_subject_identity(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    del payload["record_rule_resolutions"][0]["subject_id"]
    payload["resolution_sha256"] = _content_sha256(
        {
            "project_id": payload["project_id"],
            "batch_id": payload["batch_id"],
            "field_mapping_identity": payload["field_mapping_identity"],
            "bindings": payload["record_rule_resolutions"],
            "diagnostics": payload["record_resolution_diagnostics"],
        }
    )

    with pytest.raises(
        DailyRunOutputConflictError,
        match="record rule binding is incomplete",
    ):
        MonitoringDailyRunRepository._validate_record_rule_snapshot_payload(payload)


def test_record_snapshot_resolution_hash_requires_exact_lowercase_bytes(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    payload["resolution_sha256"] = f" {payload['resolution_sha256']}"

    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="resolution_sha256 must be a SHA-256 hex digest",
    ):
        MonitoringDailyRunRepository._validate_record_rule_snapshot_payload(payload)


def test_record_snapshot_rejects_non_string_mapping_content_hash(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    payload["field_mapping_identity"]["mapping_content_sha256"] = int("2" * 64)

    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="mapping_content_sha256 must be a SHA-256 hex digest",
    ):
        MonitoringDailyRunRepository._validate_record_rule_snapshot_payload(payload)


def test_record_snapshot_rejects_non_string_rule_pack_content_hash(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    plan = resolver.resolve_batch(batch, _mapping_contract(batch))
    payload = resolver.run_resolved(batch, plan, runner)
    payload["record_rule_resolutions"][0]["rule_pack_content_sha256"] = int(
        "3" * 64
    )
    payload["resolution_sha256"] = _content_sha256(
        {
            "project_id": payload["project_id"],
            "batch_id": payload["batch_id"],
            "field_mapping_identity": payload["field_mapping_identity"],
            "bindings": payload["record_rule_resolutions"],
            "diagnostics": payload["record_resolution_diagnostics"],
        }
    )

    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="rule_pack_content_sha256 must be a SHA-256 hex digest",
    ):
        MonitoringDailyRunRepository._validate_record_rule_snapshot_payload(payload)


@pytest.mark.parametrize(
    "field",
    (
        "mapping_content_sha256",
        "capability_manifest_sha256",
        "effective_capabilities_sha256",
    ),
)
@pytest.mark.parametrize("malformed", (int("7" * 64), "A" * 64, " " + "8" * 64))
def test_record_aggregate_rejects_noncanonical_rule_identity_hash(
    tmp_path: Path,
    field: str,
    malformed: object,
) -> None:
    repository, resolver, _runner, _batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    original_lookup = repository.published_pack_for_protocol_version

    def tampered_lookup(project_id: str, protocol_version_id: str):
        pack, rules = original_lookup(project_id, protocol_version_id)
        return pack, tuple(replace(rule, **{field: malformed}) for rule in rules)

    repository.published_pack_for_protocol_version = tampered_lookup

    with pytest.raises(
        RecordRuleAggregateIdentityError,
        match="规则聚合身份字段",
    ) as raised:
        resolver.aggregate_identity("proj_record_runtime")

    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


@pytest.mark.parametrize("malformed", (int("9" * 64), "B" * 64, " " + "a" * 64))
def test_record_aggregate_rejects_noncanonical_pack_content_hash(
    tmp_path: Path,
    malformed: object,
) -> None:
    repository, resolver, _runner, _batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    original_lookup = repository.published_pack_for_protocol_version

    def tampered_lookup(project_id: str, protocol_version_id: str):
        pack, rules = original_lookup(project_id, protocol_version_id)
        return replace(pack, content_sha256=malformed), rules

    repository.published_pack_for_protocol_version = tampered_lookup

    with pytest.raises(
        RecordRuleAggregateIdentityError,
        match="规则聚合身份字段 rule_pack_content_sha256",
    ) as raised:
        resolver.aggregate_identity("proj_record_runtime")

    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def test_daily_run_freezes_multi_pack_record_identities_and_stops_partial(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, pack_1, pack_2, _assignments = _runtime(
        tmp_path
    )
    runtime_batch = SimpleNamespace(
        **batch.__dict__,
        active_mapping_revision=batch.mapping_revision,
    )
    batch_repository = Mock()
    batch_repository.get_batch.return_value = runtime_batch
    batch_repository.load_diff_ready_batch.return_value = runtime_batch
    batch_repository.load_frozen_mapping_contract.return_value = (
        _mapping_contract(batch)
    )
    run_repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")

    project_pack_resolver = Mock(
        return_value=SimpleNamespace(
            rule_pack_revision="obsolete-project-pack",
            engine_version="obsolete-project-engine",
            resolution_mode="project_effective",
        )
    )
    service = MonitoringDailyRunService(
        run_repository=run_repository,
        batch_repository=batch_repository,
        batch_service=Mock(),
        rule_runtime_resolver=project_pack_resolver,
        rule_runner=runner,
        record_rule_resolver=resolver,
    )
    prepared = service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-mode-prepare",
        actor="medical_manager",
    ).run
    assert prepared.rule_resolution_mode == "record_applicability"
    assert prepared.rule_pack_revision == ""
    project_pack_resolver.assert_not_called()
    processing = service.process_prepared(
        project_id=batch.project_id,
        run_id=prepared.run_id,
        expected_version=prepared.version,
        owner="worker-1",
    ).run

    result = service.execute_rules(
        project_id=batch.project_id,
        run_id=processing.run_id,
        expected_version=processing.version,
        owner="worker-2",
    )

    assert result.run.status == "analysis_partial"
    assert result.next_action == "review_rule_resolution"
    snapshot = result.rule_snapshot
    assert snapshot.resolution_mode == "record_applicability"
    assert snapshot.rule_pack_id == ""
    assert snapshot.payload["rule_pack_ids"] == sorted(
        [pack_1.rule_pack_id, pack_2.rule_pack_id]
    )
    assert snapshot.payload["field_mapping_identity"] == _mapping_contract(
        batch
    ).identity_dict()
    assert batch_repository.load_frozen_mapping_contract.call_args_list == [
        call(batch.batch_id),
        call(batch.batch_id),
    ]
    assert len(snapshot.payload["record_rule_resolutions"]) == 4
    response = result.to_dict()["rule_result"]
    assert response["resolution_mode"] == "record_applicability"
    assert response["analysis_complete"] is False
    assert response["failed_resolution_count"] == 1
    assert response["resolution_diagnostics"][0]["code"] == (
        "monitoring_protocol_applicability_unresolved"
    )
    for binding in snapshot.payload["record_rule_resolutions"]:
        assert binding["assignment_id"].startswith("protoapp_")
        assert binding["assignment_state_version"] == 2
        assert binding["protocol_version_id"].startswith("protov_")
        assert binding["rule_pack_id"].startswith("monpack_")
        assert binding["rule_pack_revision"] >= 1
        assert len(binding["rule_pack_content_sha256"]) == 64


def test_record_run_reuses_frozen_resolution_after_post_snapshot_crash(
    tmp_path: Path,
) -> None:
    _repository, resolver, runner, batch, _pack_1, _pack_2, _assignments = _runtime(
        tmp_path
    )
    runtime_batch = SimpleNamespace(
        **batch.__dict__,
        active_mapping_revision=batch.mapping_revision,
    )
    batch_repository = Mock()
    batch_repository.get_batch.return_value = runtime_batch
    batch_repository.load_diff_ready_batch.return_value = runtime_batch
    batch_repository.load_frozen_mapping_contract.return_value = (
        _mapping_contract(batch)
    )
    run_repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    resolver.resolve_batch = Mock(wraps=resolver.resolve_batch)
    service = MonitoringDailyRunService(
        run_repository=run_repository,
        batch_repository=batch_repository,
        batch_service=Mock(),
        rule_runtime_resolver=Mock(),
        rule_runner=runner,
        record_rule_resolver=resolver,
    )
    prepared = service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-mode-crash-prepare",
        actor="medical_manager",
    ).run
    processing = service.process_prepared(
        project_id=batch.project_id,
        run_id=prepared.run_id,
        expected_version=prepared.version,
        owner="worker-1",
    ).run

    original_transition = run_repository.transition
    crashed = False

    def crash_after_snapshot(*args, **kwargs):
        nonlocal crashed
        if kwargs.get("target_status") == "analysis_partial" and not crashed:
            crashed = True
            raise RuntimeError("simulated crash after rule snapshot")
        return original_transition(*args, **kwargs)

    run_repository.transition = crash_after_snapshot
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.execute_rules(
            project_id=batch.project_id,
            run_id=processing.run_id,
            expected_version=processing.version,
            owner="worker-crash",
        )
    frozen_snapshot = run_repository.get_rule_snapshot(
        batch.project_id,
        processing.run_id,
    )
    current = run_repository.get(batch.project_id, processing.run_id)
    assert frozen_snapshot is not None
    assert current.status == "rules_running"
    assert resolver.resolve_batch.call_count == 1
    assert batch_repository.load_frozen_mapping_contract.call_count == 2

    run_repository.transition = original_transition
    resumed = service.execute_rules(
        project_id=batch.project_id,
        run_id=current.run_id,
        expected_version=current.version,
        owner="worker-recovery",
    )

    assert resumed.run.status == "analysis_partial"
    assert resumed.rule_snapshot.snapshot_id == frozen_snapshot.snapshot_id
    assert resolver.resolve_batch.call_count == 1
    assert batch_repository.load_frozen_mapping_contract.call_count == 3


def test_aggregate_identity_is_deterministic_and_project_scoped(
    tmp_path: Path,
) -> None:
    repository, resolver, _runner, _batch, pack_1, pack_2, assignments = _runtime(
        tmp_path
    )

    aggregate = resolver.aggregate_identity("proj_record_runtime")
    again = resolver.aggregate_identity("proj_record_runtime")

    assert aggregate == again
    assert len(aggregate.identity_sha256) == 64
    assert aggregate.identity_sha256 != ""
    assert aggregate.mapping_revision == "mapping-v1"
    assert aggregate.mapping_content_sha256 == "2" * 64
    assert aggregate.capability_manifest_sha256 == "5" * 64
    assert aggregate.effective_capabilities_sha256 == "6" * 64
    assert aggregate.applicability_dimensions == (
        "centre_id",
        "subject_id",
        "event_date",
    )
    assert {pack[0] for pack in aggregate.packs} == {
        pack_1.rule_pack_id,
        pack_2.rule_pack_id,
    }
    assert {item[0] for item in aggregate.assignments} == {
        assignment.assignment_id for assignment in assignments
    }
    assert aggregate.rule_revision_ids == tuple(
        sorted(
            {
                rule_revision_id
                for pack in (pack_1, pack_2)
                for rule_revision_id in pack.rule_revision_ids
            }
        )
    )

    foreign_version = repository.register_protocol_version(
        _site_version("proj_foreign", "V9.0", "c")
    )
    foreign_assignment = repository.create_applicability_assignment(
        _assignment(foreign_version, centre_id="001")
    )
    repository.transition_applicability_assignment(
        foreign_assignment.project_id,
        foreign_assignment.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    foreign_fact = repository.store_fact(
        _fact(
            foreign_version,
            key="concomitant_medication.prohibited",
            fact_type="concomitant_medication_prohibited",
        )
    )
    _publish_pack(
        repository,
        foreign_version,
        [
            _identified_rule(
                _rule(
                    foreign_version,
                    foreign_fact,
                    rule_key="concomitant_medication.prohibited",
                    rule_family="concomitant_medication_policy",
                    trigger_value="甲氨蝶呤",
                )
            )
        ],
    )

    isolated = resolver.aggregate_identity("proj_record_runtime")
    assert isolated == aggregate
    foreign = resolver.aggregate_identity("proj_foreign")
    assert foreign.project_id == "proj_foreign"
    assert foreign.identity_sha256 != aggregate.identity_sha256
    assert {pack[0] for pack in foreign.packs}.isdisjoint(
        {pack_1.rule_pack_id, pack_2.rule_pack_id}
    )


def test_aggregate_identity_requires_assignments_and_published_packs(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    resolver = MonitoringRecordRuleResolver(repository)

    with pytest.raises(RecordRuleAggregateIdentityError) as raised:
        resolver.aggregate_identity("proj_empty")
    assert raised.value.code == "monitoring_rule_pack_required"

    version = repository.register_protocol_version(
        _site_version("proj_unpublished", "V1.0", "a")
    )
    assignment = repository.create_applicability_assignment(
        _assignment(version, centre_id="001")
    )
    repository.transition_applicability_assignment(
        assignment.project_id,
        assignment.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    with pytest.raises(RecordRuleAggregateIdentityError) as raised:
        resolver.aggregate_identity("proj_unpublished")
    assert raised.value.code == "monitoring_rule_pack_required"


def test_aggregate_identity_fails_closed_on_legacy_pack_without_rule_identity(
    tmp_path: Path,
) -> None:
    _repository, resolver, _runner, _batch, _pack_1, _pack_2, _assignments = (
        _runtime(tmp_path, identified=False)
    )

    with pytest.raises(RecordRuleAggregateIdentityError) as raised:
        resolver.aggregate_identity("proj_record_runtime")
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def test_aggregate_identity_fails_closed_on_mixed_mapping_identities(
    tmp_path: Path,
) -> None:
    _repository, resolver, _runner, _batch, _pack_1, _pack_2, _assignments = (
        _runtime(
            tmp_path,
            second_rule_identity={
                "mapping_revision": "mapping-v0",
                "mapping_content_sha256": "7" * 64,
            },
        )
    )

    with pytest.raises(RecordRuleAggregateIdentityError) as raised:
        resolver.aggregate_identity("proj_record_runtime")
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def test_aggregate_identity_fails_closed_on_missing_effective_capabilities_hash(
    tmp_path: Path,
) -> None:
    _repository, resolver, _runner, _batch, _pack_1, _pack_2, _assignments = (
        _runtime(
            tmp_path,
            rule_identity={
                **_RULE_IDENTITY,
                "effective_capabilities_sha256": "",
            },
        )
    )

    with pytest.raises(RecordRuleAggregateIdentityError) as raised:
        resolver.aggregate_identity("proj_record_runtime")
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def _service_stack(
    tmp_path: Path,
    *,
    identified: bool = True,
    rule_identity: dict[str, str] | None = None,
    second_rule_identity: dict[str, str] | None = None,
    active_mapping: str | None = "matching",
):
    (
        repository,
        resolver,
        runner,
        batch,
        pack_1,
        pack_2,
        assignments,
    ) = _runtime(
        tmp_path,
        identified=identified,
        rule_identity=rule_identity,
        second_rule_identity=second_rule_identity,
    )
    runtime_batch = SimpleNamespace(
        **batch.__dict__,
        active_mapping_revision=batch.mapping_revision,
    )
    batch_repository = Mock()
    batch_repository.get_batch.return_value = runtime_batch
    batch_repository.load_diff_ready_batch.return_value = runtime_batch
    batch_repository.load_frozen_mapping_contract.return_value = (
        _mapping_contract(batch)
    )
    run_repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    service_kwargs: dict[str, object] = {}
    if active_mapping == "matching":
        service_kwargs["active_mapping_resolver"] = lambda project_id: (
            SimpleNamespace(
                mapping_revision="mapping-v1",
                mapping_content_sha256="2" * 64,
                capability_manifest_sha256="5" * 64,
                effective_capabilities_sha256="6" * 64,
            )
        )
    elif active_mapping == "drifted":
        service_kwargs["active_mapping_resolver"] = lambda project_id: (
            SimpleNamespace(
                mapping_revision="mapping-v1",
                mapping_content_sha256="9" * 64,
                capability_manifest_sha256="5" * 64,
                effective_capabilities_sha256="6" * 64,
            )
        )
    elif active_mapping == "effective_drifted":
        service_kwargs["active_mapping_resolver"] = lambda project_id: (
            SimpleNamespace(
                mapping_revision="mapping-v1",
                mapping_content_sha256="2" * 64,
                capability_manifest_sha256="5" * 64,
                effective_capabilities_sha256="8" * 64,
            )
        )
    service = MonitoringDailyRunService(
        run_repository=run_repository,
        batch_repository=batch_repository,
        batch_service=Mock(),
        rule_runtime_resolver=Mock(),
        rule_runner=runner,
        record_rule_resolver=resolver,
        **service_kwargs,
    )
    return SimpleNamespace(
        service=service,
        resolver=resolver,
        runner=runner,
        batch=batch,
        repository=repository,
        run_repository=run_repository,
        batch_repository=batch_repository,
        pack_1=pack_1,
        pack_2=pack_2,
        assignments=assignments,
    )


def test_record_readiness_prepare_and_execute_freeze_aggregate_identity(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path)
    batch = stack.batch
    aggregate = stack.resolver.aggregate_identity(batch.project_id)

    readiness = stack.service.start_readiness(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
    )

    assert readiness["ready"] is True
    assert readiness["rule_resolution_mode"] == "record_applicability"
    assert readiness["rule_pack_revision"] == aggregate.identity_sha256
    assert readiness["next_action"] == "start_daily_run"

    prepared = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-identity-prepare",
        actor="medical_manager",
    ).run
    assert prepared.rule_resolution_mode == "record_applicability"
    assert prepared.rule_pack_revision == ""
    assert prepared.rule_identity_sha256 == aggregate.identity_sha256
    stack.service.rule_runtime_resolver.assert_not_called()

    processing = stack.service.process_prepared(
        project_id=batch.project_id,
        run_id=prepared.run_id,
        expected_version=prepared.version,
        owner="worker-1",
    ).run
    result = stack.service.execute_rules(
        project_id=batch.project_id,
        run_id=processing.run_id,
        expected_version=processing.version,
        owner="worker-2",
    )
    assert result.run.status == "analysis_partial"
    assert result.rule_snapshot.resolution_mode == "record_applicability"
    frozen = stack.run_repository.get(batch.project_id, prepared.run_id)
    assert frozen.rule_identity_sha256 == aggregate.identity_sha256


def test_record_readiness_fails_closed_on_legacy_pack_without_rule_identity(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path, identified=False)

    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )

    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_unverifiable"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="record-legacy-prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"
    assert stack.run_repository.list_runs(stack.batch.project_id) == ()


def test_record_readiness_fails_closed_on_mixed_rule_identities(
    tmp_path: Path,
) -> None:
    stack = _service_stack(
        tmp_path,
        second_rule_identity={
            "mapping_revision": "mapping-v0",
            "mapping_content_sha256": "7" * 64,
        },
    )

    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )

    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_unverifiable"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="record-mixed-prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"


def test_record_mapping_drift_fails_closed_on_readiness_and_prepare(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path, active_mapping="drifted")

    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )

    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_drift"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="record-drift-prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_drift"
    assert stack.run_repository.list_runs(stack.batch.project_id) == ()


def test_record_readiness_fails_closed_on_missing_effective_capabilities_hash(
    tmp_path: Path,
) -> None:
    stack = _service_stack(
        tmp_path,
        rule_identity={
            **_RULE_IDENTITY,
            "effective_capabilities_sha256": "",
        },
    )

    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )

    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_unverifiable"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="record-effective-missing-prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_unverifiable"
    assert stack.run_repository.list_runs(stack.batch.project_id) == ()


def test_record_effective_capabilities_drift_fails_closed_on_readiness_and_prepare(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path, active_mapping="effective_drifted")

    readiness = stack.service.start_readiness(
        project_id=stack.batch.project_id,
        batch_id=stack.batch.batch_id,
    )

    assert readiness["ready"] is False
    assert readiness["state_code"] == "monitoring_rule_pack_identity_drift"
    assert readiness["next_action"] == "prepare_rule_pack"
    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.prepare(
            project_id=stack.batch.project_id,
            batch_id=stack.batch.batch_id,
            idempotency_key="record-effective-drift-prepare",
            actor="medical_manager",
        )
    assert raised.value.code == "monitoring_rule_pack_identity_drift"
    assert stack.run_repository.list_runs(stack.batch.project_id) == ()


def test_record_execute_fails_closed_when_assignments_change_after_prepare(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path)
    batch = stack.batch
    prepared = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-mutate-prepare",
        actor="medical_manager",
    ).run
    processing = stack.service.process_prepared(
        project_id=batch.project_id,
        run_id=prepared.run_id,
        expected_version=prepared.version,
        owner="worker-1",
    ).run

    version_3 = stack.repository.register_protocol_version(
        _site_version(batch.project_id, "V3.0", "d")
    )
    fact_3 = stack.repository.store_fact(_fact(version_3))
    assignment_3 = stack.repository.create_applicability_assignment(
        _assignment(
            version_3,
            centre_id="003",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
        )
    )
    stack.repository.transition_applicability_assignment(
        assignment_3.project_id,
        assignment_3.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    _publish_pack(
        stack.repository,
        version_3,
        [_identified_rule(_rule(version_3, fact_3))],
    )
    stack.runner.run = Mock(wraps=stack.runner.run)

    with pytest.raises(MonitoringDailyRunServiceError) as raised:
        stack.service.execute_rules(
            project_id=batch.project_id,
            run_id=processing.run_id,
            expected_version=processing.version,
            owner="worker-2",
        )

    assert raised.value.code == "monitoring_rule_identity_changed"
    assert stack.runner.run.call_count == 0
    assert (
        stack.run_repository.get_rule_snapshot(batch.project_id, prepared.run_id)
        is None
    )
    current = stack.run_repository.get(batch.project_id, prepared.run_id)
    assert current.status == "rules_running"
    assert current.rule_identity_sha256 == prepared.rule_identity_sha256

    with pytest.raises(MonitoringDailyRunServiceError) as repeated:
        stack.service.execute_rules(
            project_id=batch.project_id,
            run_id=current.run_id,
            expected_version=current.version,
            owner="worker-3",
        )

    assert repeated.value.code == "monitoring_rule_identity_changed"
    reread = stack.run_repository.get(batch.project_id, prepared.run_id)
    assert reread.status == "rules_running"
    assert reread.rule_identity_sha256 == prepared.rule_identity_sha256
    assert reread.input_sha256 == current.input_sha256
    assert (
        stack.run_repository.get_rule_snapshot(batch.project_id, prepared.run_id)
        is None
    )
    assert stack.runner.run.call_count == 0


def test_record_prepare_is_idempotent_with_identical_frozen_identity(
    tmp_path: Path,
) -> None:
    stack = _service_stack(tmp_path)
    batch = stack.batch

    first = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-idempotent-prepare",
        actor="medical_manager",
    )
    replay = stack.service.prepare(
        project_id=batch.project_id,
        batch_id=batch.batch_id,
        idempotency_key="record-idempotent-prepare",
        actor="medical_manager",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.run.run_id == first.run.run_id
    assert replay.run.rule_identity_sha256 == first.run.rule_identity_sha256
    assert replay.run.input_sha256 == first.run.input_sha256
    assert len(stack.run_repository.list_runs(batch.project_id)) == 1
