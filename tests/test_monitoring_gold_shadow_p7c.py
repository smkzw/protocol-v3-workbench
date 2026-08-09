from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackLifecycleError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    RuleDiagnosticCase,
    RuleGoldStandardCase,
    diagnostic_case_set_content_sha256,
    gold_case_set_content_sha256,
    shadow_coverage_content_sha256,
    shadow_diagnostic_results_content_sha256,
    validate_rule_clinical_compatibility,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _gold_case_source,
    _rule,
    _start_shadow_pack,
    _store_p7c_release_evidence,
    _version,
)


class _ProjectAuthority:
    def __init__(self) -> None:
        self.invalid_projects: set[str] = set()

    def validate(self, case: object, _rule: object) -> None:
        if getattr(case, "project_id") in self.invalid_projects:
            raise ValueError("authoritative source drift")


def _ready_shadow(
    db_path: Path,
    *,
    authority: _ProjectAuthority | None = None,
):
    authority = authority or _ProjectAuthority()
    repository = MonitoringProtocolRuleRepository(
        db_path,
        gold_case_authority=authority.validate,
    )
    version = repository.register_protocol_version(
        _version(
            "p7c-primary",
            "V1.0",
            "2026-01-01",
            effective_from="2026-01-10",
        )
    )
    fact = repository.store_fact(_fact(version))
    lifecycle, shadow, rules = _start_shadow_pack(
        repository,
        version,
        [_rule(version, fact)],
    )
    return repository, lifecycle, shadow, rules[0], authority


def _boolean_case(
    rule,
    *,
    label: str,
    expected_match: bool,
    coverage_labels: tuple[str, ...],
    trigger: bool,
) -> RuleGoldStandardCase:
    locator, source = _gold_case_source(rule, label)
    return RuleGoldStandardCase.create(
        **source,
        project_id=rule.project_id,
        rule_key=rule.rule_key,
        case_label=label,
        input_record={
            "SUBJID": f"P7C-{label}",
            "EXDESC": "漏服" if trigger else "__P7C_NO_MATCH__",
            "evidence_span_ids": [locator],
        },
        observed_domains=rule.required_domains,
        expected_match=expected_match,
        coverage_labels=coverage_labels,
        medical_rationale=f"P7C {label} 布尔用例。",
        evidence_locators=[locator],
    )


def _diagnostic_case(
    rule,
    *,
    label: str = "diagnostic-missing-domain",
    determinate: bool = False,
) -> RuleDiagnosticCase:
    locator, source = _gold_case_source(rule, label)
    return RuleDiagnosticCase.create(
        **source,
        project_id=rule.project_id,
        rule_key=rule.rule_key,
        case_label=label,
        input_record={
            "SUBJID": f"P7C-{label}",
            "EXDESC": "__P7C_NO_MATCH__",
            "evidence_span_ids": [locator],
        },
        observed_domains=rule.required_domains if determinate else ("ZZ",),
        expected_diagnostic_category="missing_input",
        expected_diagnostic_code="missing_required_domains",
        medical_rationale="缺少规则所需数据域时必须返回不可判定。",
        evidence_locators=[locator],
    )


def _store_boolean_coverage(
    repository: MonitoringProtocolRuleRepository,
    rule,
    *,
    positive: bool = True,
    negative: bool = True,
    boundary: bool = True,
    diagnostic: bool = True,
) -> None:
    cases: list[RuleGoldStandardCase] = []
    if positive:
        cases.append(
            _boolean_case(
                rule,
                label="positive",
                expected_match=True,
                coverage_labels=("positive",),
                trigger=True,
            )
        )
    if negative:
        cases.append(
            _boolean_case(
                rule,
                label="negative",
                expected_match=False,
                coverage_labels=("negative",),
                trigger=False,
            )
        )
    if boundary:
        cases.append(
            _boolean_case(
                rule,
                label="boundary",
                expected_match=False,
                coverage_labels=("negative", "boundary"),
                trigger=False,
            )
        )
    repository.store_gold_cases(cases)
    if diagnostic:
        repository.store_diagnostic_cases((_diagnostic_case(rule),))


def test_boolean_labels_are_closed_and_diagnostics_are_independent() -> None:
    version = _version(
        "p7c-labels",
        "V1.0",
        "2026-01-01",
        effective_from="2026-01-10",
    )
    rule = _rule(version, _fact(version))
    boundary = _boolean_case(
        rule,
        label="closed-boundary",
        expected_match=False,
        coverage_labels=("negative", "boundary"),
        trigger=False,
    )
    assert boundary.coverage_labels == ("boundary", "negative")

    with pytest.raises(MonitoringProtocolRuleError, match="coverage_label"):
        _boolean_case(
            rule,
            label="unknown-label",
            expected_match=False,
            coverage_labels=("negative", "near_threshold"),
            trigger=False,
        )
    with pytest.raises(MonitoringProtocolRuleError, match="requires positive"):
        _boolean_case(
            rule,
            label="wrong-polarity",
            expected_match=True,
            coverage_labels=("negative",),
            trigger=True,
        )

    diagnostic = _diagnostic_case(rule)
    assert "expected_match" not in diagnostic.public_dict()
    assert diagnostic.case_id.startswith("diagcase_")
    assert boundary.case_id.startswith("goldcase_")


def test_shadow_freezes_complete_sets_results_and_coverage_hashes(
    tmp_path: Path,
) -> None:
    repository, _lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "rules.sqlite3"
    )
    _store_p7c_release_evidence(repository, [rule])

    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="p7c-complete",
    )
    gold_cases = repository.gold_cases(
        rule.project_id,
        rule_revision_ids=(rule.rule_revision_id,),
    )
    diagnostic_cases = repository.diagnostic_cases(
        rule.project_id,
        rule_revision_ids=(rule.rule_revision_id,),
    )

    assert run.case_count == 2
    assert run.diagnostic_case_count == 1
    assert run.diagnostic_passed_count == 1
    assert run.case_set_content_sha256 == gold_case_set_content_sha256(gold_cases)
    assert run.diagnostic_case_set_content_sha256 == (
        diagnostic_case_set_content_sha256(diagnostic_cases)
    )
    assert run.diagnostic_results_content_sha256 == (
        shadow_diagnostic_results_content_sha256(run.diagnostic_results)
    )
    assert run.coverage_content_sha256 == shadow_coverage_content_sha256(
        run.rule_coverages,
        run.family_coverages,
    )
    assert (
        run.rule_coverages[0].positive_count,
        run.rule_coverages[0].negative_count,
        run.rule_coverages[0].boundary_count,
        run.rule_coverages[0].diagnostic_indeterminate_count,
    ) == (1, 1, 1, 1)
    family = next(
        item
        for item in run.family_coverages
        if item.rule_family == rule.rule_family
    )
    assert len(family.authoritative_projects) == 2


@pytest.mark.parametrize(
    ("coverage", "missing"),
    (
        (
            {
                "positive": False,
                "negative": True,
                "boundary": False,
                "diagnostic": False,
            },
            "positive",
        ),
        (
            {
                "positive": True,
                "negative": True,
                "boundary": False,
                "diagnostic": True,
            },
            "boundary",
        ),
        (
            {
                "positive": True,
                "negative": True,
                "boundary": True,
                "diagnostic": False,
            },
            "diagnostic_indeterminate",
        ),
    ),
)
def test_publication_closes_on_each_per_rule_coverage_gap(
    tmp_path: Path,
    coverage: dict[str, bool],
    missing: str,
) -> None:
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / f"{missing}.sqlite3"
    )
    _store_boolean_coverage(repository, rule, **coverage)
    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id=f"missing-{missing}",
    )
    confirmed = lifecycle.confirm_shadow(
        shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    )

    with pytest.raises(RulePackLifecycleError, match=missing):
        lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )


def test_diagnostic_case_returning_false_cannot_pass_shadow(
    tmp_path: Path,
) -> None:
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "diagnostic-false.sqlite3"
    )
    _store_boolean_coverage(
        repository,
        rule,
        diagnostic=False,
    )
    repository.store_diagnostic_cases(
        (_diagnostic_case(rule, determinate=True),)
    )

    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="diagnostic-false",
    )

    assert run.diagnostic_failed_count == 1
    assert run.diagnostic_results[0].actual_state == "false"
    assert run.release_gate_eligible is False
    with pytest.raises(RulePackLifecycleError, match="pass every case"):
        lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )


def test_shadow_confirmation_rejects_case_added_after_frozen_run(
    tmp_path: Path,
) -> None:
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "set-drift.sqlite3"
    )
    _store_p7c_release_evidence(repository, [rule])
    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="before-drift",
    )
    repository.store_gold_cases(
        (
            _boolean_case(
                rule,
                label="late-negative",
                expected_match=False,
                coverage_labels=("negative",),
                trigger=False,
            ),
        )
    )

    with pytest.raises(RulePackLifecycleError, match="complete current gold case set"):
        lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )


def test_second_project_with_only_negative_does_not_satisfy_family_gate(
    tmp_path: Path,
) -> None:
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "negative-only-second-project.sqlite3"
    )
    _store_p7c_release_evidence(
        repository,
        [rule],
        secondary_coverage="negative_only",
    )

    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="negative-only-second-project",
    )
    family = next(
        item
        for item in run.family_coverages
        if item.rule_family == rule.rule_family
    )
    secondary_project = f"fixture-secondary-{rule.rule_family}"
    assert family.authoritative_projects == (rule.project_id,)
    assert {
        case.coverage_labels
        for case in repository.gold_cases(secondary_project)
    } == {("negative",)}
    assert repository.diagnostic_cases(secondary_project) == ()
    confirmed = lifecycle.confirm_shadow(
        shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    )
    with pytest.raises(RulePackLifecycleError, match="at least two"):
        lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )


def test_second_project_with_complete_four_class_evidence_satisfies_family_gate(
    tmp_path: Path,
) -> None:
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "complete-second-project.sqlite3"
    )
    _store_p7c_release_evidence(repository, [rule])

    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="complete-second-project",
    )
    family = next(
        item
        for item in run.family_coverages
        if item.rule_family == rule.rule_family
    )
    assert family.authoritative_projects == (
        f"fixture-secondary-{rule.rule_family}",
        rule.project_id,
    )
    assert run.release_gate_eligible is True
    confirmed = lifecycle.confirm_shadow(
        shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    )
    published = lifecycle.publish(
        confirmed.rule_pack_id,
        published_by="medical_manager",
    )
    assert published.status == "published"


def test_untrusted_second_project_does_not_satisfy_family_gate(
    tmp_path: Path,
) -> None:
    authority = _ProjectAuthority()
    repository, lifecycle, shadow, rule, _authority = _ready_shadow(
        tmp_path / "cross-project.sqlite3",
        authority=authority,
    )
    _store_p7c_release_evidence(repository, [rule])
    authority.invalid_projects.add(
        f"fixture-secondary-{rule.rule_family}"
    )

    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="untrusted-second-project",
    )
    family = next(
        item
        for item in run.family_coverages
        if item.rule_family == rule.rule_family
    )
    assert family.authoritative_projects == (rule.project_id,)
    confirmed = lifecycle.confirm_shadow(
        shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    )
    with pytest.raises(RulePackLifecycleError, match="at least two"):
        lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )


def test_sqlite_p7c_migration_is_idempotent_and_legacy_cases_stay_unqualified(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE monitoring_rule_gold_cases (
                case_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_revision_id TEXT NOT NULL DEFAULT '',
                source_entry_id TEXT NOT NULL DEFAULT '',
                source_content_sha256 TEXT NOT NULL DEFAULT '',
                source_revision TEXT NOT NULL DEFAULT '',
                batch_revision TEXT NOT NULL DEFAULT '',
                case_label TEXT NOT NULL,
                input_record_json TEXT NOT NULL,
                previous_record_json TEXT NOT NULL,
                related_records_json TEXT NOT NULL,
                observed_domains_json TEXT NOT NULL,
                expected_match INTEGER NOT NULL,
                medical_rationale TEXT NOT NULL,
                evidence_locators_json TEXT NOT NULL,
                source_row_bindings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE monitoring_rule_shadow_runs (
                shadow_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_pack_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                case_count INTEGER NOT NULL,
                passed_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                results_json TEXT NOT NULL,
                case_set_content_sha256 TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO monitoring_rule_gold_cases VALUES (
                'legacy-case', 'legacy-project', 'legacy.rule', 'legacy-revision',
                'legacy-source',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'legacy-source-revision', 'legacy-batch-revision', 'legacy case',
                '{"SUBJID":"001"}', '{}', '{}', '["EX"]', 0,
                'legacy rationale',
                '["listing:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:sheet:EX:row:2"]',
                '[]', '2026-01-01T00:00:00+00:00'
            );
            """
        )

    MonitoringProtocolRuleRepository(db_path)
    repository = MonitoringProtocolRuleRepository(db_path)
    with sqlite3.connect(db_path) as connection:
        gold_columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_rule_gold_cases)"
            )
        ]
        shadow_columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_rule_shadow_runs)"
            )
        ]
        assert gold_columns.count("coverage_labels_json") == 1
        assert shadow_columns.count("diagnostic_results_json") == 1
        assert shadow_columns.count("coverage_content_sha256") == 1

    legacy = repository.gold_cases("legacy-project")[0]
    assert legacy.coverage_labels == ()


@pytest.mark.parametrize("domain", ("EX", "EC", "DA", "IP"))
def test_cm_and_study_treatment_domains_remain_closed(domain: str) -> None:
    validate_rule_clinical_compatibility(
        rule_family="study_treatment_change",
        clinical_domain="study_treatment",
        required_domains=(domain,),
    )
    with pytest.raises(MonitoringProtocolRuleError, match="must not use CM"):
        validate_rule_clinical_compatibility(
            rule_family="study_treatment_change",
            clinical_domain="study_treatment",
            required_domains=(domain, "CM"),
        )
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="must not use EX, EC, DA or IP",
    ):
        validate_rule_clinical_compatibility(
            rule_family="concomitant_medication_policy",
            clinical_domain="concomitant_medication",
            required_domains=("CM", domain),
        )


def test_j07_alone_does_not_infer_live_vaccine(tmp_path: Path) -> None:
    version = _version(
        "p7c-vaccine",
        "V1.0",
        "2026-01-01",
        effective_from="2026-01-10",
    )
    rule = _rule(
        version,
        _fact(
            version,
            key="concomitant_medication.live_vaccine",
            fact_type="concomitant_medication_prohibited",
        ),
        rule_key="concomitant_medication.live_vaccine",
        rule_family="concomitant_medication_policy",
        trigger_value="活疫苗|减毒活疫苗",
    )
    result = MonitoringProtocolRuleService(
        MonitoringProtocolRuleRepository(tmp_path / "j07.sqlite3")
    ).evaluate_record(
        rule,
        {
            "SUBJID": "P7C-J07",
            "EXDESC": "疫苗接种",
            "ATC": "J07",
            "evidence_span_ids": ("listing:test:sheet:CM:row:2",),
        },
        observed_domains=("CM",),
    )

    assert result.matched is False
    assert result.evidence["evaluation_state"] == "false"
