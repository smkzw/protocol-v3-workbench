from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    MonitoringProtocolStateConflictError,
    ProtocolApplicabilityUnresolvedError,
    RulePackLifecycleError,
    RulePackRevisionConflictError,
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
    MonitoringRulePack,
    ProtocolFact,
    RuleGoldStandardCase,
    RuleShadowCaseResult,
    RuleShadowRun,
    gold_case_set_content_sha256,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _full_identity,
    _gold_case_source,
    _publish_pack,
    _rule,
    _rule_with_identity,
    _store_p7c_release_evidence,
    _version,
)


def _repository_with_candidate_rule(path: Path):
    repository = MonitoringProtocolRuleRepository(path)
    repository.bind_gold_case_authority(lambda _case, _rule: None)
    version = repository.register_protocol_version(
        _version(
            "proj_alpha",
            "V1.0",
            "2026-01-01",
            effective_from="2026-01-10",
        )
    )
    fact = repository.store_fact(_fact(version))
    rule = replace(_rule(version, fact), status="candidate")
    lifecycle = MonitoringRuleLifecycleService(
        repository,
        clock=lambda: "2026-01-15T00:00:00+00:00",
    )
    draft = lifecycle.create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=[rule],
        created_by="rule_author",
    )
    return repository, lifecycle, version, fact, rule, draft


def _registered_case(rule: MonitoringRuleDefinition, label: str):
    locator, source = _gold_case_source(rule, label)
    return RuleGoldStandardCase.create(
        **source,
        project_id=rule.project_id,
        rule_key=rule.rule_key,
        case_label=label,
        input_record={
            "SUBJID": "LIFECYCLE-001",
            "EXDESC": "按计划服药",
            "evidence_span_ids": [locator],
        },
        observed_domains=rule.required_domains,
        expected_match=False,
        medical_rationale="阴性金标准。",
        evidence_locators=[locator],
    )


def _insert_shadow_run_raw(
    path: Path,
    run: RuleShadowRun,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO monitoring_rule_shadow_runs (
                shadow_run_id, project_id, rule_pack_id, batch_id,
                status, case_count, passed_count, failed_count,
                results_json, case_set_content_sha256,
                completed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.shadow_run_id,
                run.project_id,
                run.rule_pack_id,
                run.batch_id,
                run.status,
                run.case_count,
                run.passed_count,
                run.failed_count,
                json.dumps(
                    [asdict(result) for result in run.results],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                run.case_set_content_sha256,
                run.completed_at,
                run.completed_at,
            ),
        )


def test_lifecycle_rejects_skips_and_direct_terminal_storage() -> None:
    with TemporaryDirectory() as directory:
        repository, lifecycle, version, _, rule, draft = (
            _repository_with_candidate_rule(Path(directory) / "rules.sqlite3")
        )

        with pytest.raises(RulePackLifecycleError, match="draft -> confirmed"):
            repository.advance_rule_pack_stage(
                draft.rule_pack_id,
                target_status="confirmed",
                actor="medical_manager",
            )
        with pytest.raises(RulePackLifecycleError, match="confirmed rules"):
            lifecycle.start_shadow(
                draft.rule_pack_id,
                started_by="shadow_operator",
            )

        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        with pytest.raises(RulePackLifecycleError, match="shadow -> published"):
            repository.advance_rule_pack_stage(
                shadow.rule_pack_id,
                target_status="published",
                actor="medical_manager",
            )
        with pytest.raises(RulePackLifecycleError, match="trusted shadow run"):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id="",
                confirmed_by="medical_manager",
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="MonitoringRuleLifecycleService",
        ):
            MonitoringRulePack.create(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                pack_revision=repository.next_pack_revision(version.project_id),
                status="published",
                applicability_status=version.applicability_status,
                rules=[replace(confirmed_rule, status="enabled")],
                created_by="medical_manager",
                published_at="2026-01-15T00:00:00+00:00",
            )
        terminal = replace(
            draft,
            status="published",
            published_at="2026-01-15T00:00:00+00:00",
        )
        with pytest.raises(RulePackLifecycleError, match="direct rule pack"):
            repository.store_rule_pack(
                terminal,
                [replace(confirmed_rule, status="enabled")],
            )


def test_shadow_confirmation_rejects_failed_external_and_unregistered_evidence() -> (
    None
):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(path)
        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        registered = _registered_case(confirmed_rule, "registered-negative")
        repository.store_gold_cases([registered])

        failed_run = RuleShadowRun.create(
            project_id=rule.project_id,
            rule_pack_id=shadow.rule_pack_id,
            batch_id="failed-shadow",
            results=[
                RuleShadowCaseResult(
                    case_id=registered.case_id,
                    rule_key=rule.rule_key,
                    rule_revision_id=rule.rule_revision_id,
                    expected_match=False,
                    actual_match=True,
                    passed=False,
                    evidence_summary="registered case failed",
                )
            ],
            case_set_content_sha256=gold_case_set_content_sha256([registered]),
            completed_at="2026-01-15T00:00:00+00:00",
        )
        repository.store_shadow_run(failed_run)
        with pytest.raises(RulePackLifecycleError, match="pass every case"):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=failed_run.shadow_run_id,
                confirmed_by="medical_manager",
            )

        external = RuleGoldStandardCase.create(
            **_gold_case_source(confirmed_rule, "external-only")[1],
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            case_label="external-only",
            input_record={"SUBJID": "EXT-001", "EXDESC": "按计划服药"},
            observed_domains=rule.required_domains,
            expected_match=False,
            medical_rationale="开发期外部输入。",
            evidence_locators=[
                _gold_case_source(confirmed_rule, "external-only")[0]
            ],
        )
        external_run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="external-shadow",
            cases=[external],
        )
        assert external_run.persisted is False
        with pytest.raises(
            RulePackLifecycleError,
            match="repository-registered shadow run",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=external_run.shadow_run_id,
                confirmed_by="medical_manager",
            )

        unregistered_result = RuleShadowCaseResult(
            case_id="unregistered-case",
            rule_key=rule.rule_key,
            rule_revision_id=rule.rule_revision_id,
            expected_match=False,
            actual_match=False,
            passed=True,
            evidence_summary="forged external result",
        )
        unregistered_run = RuleShadowRun.create(
            project_id=rule.project_id,
            rule_pack_id=shadow.rule_pack_id,
            batch_id="unregistered-shadow",
            results=[unregistered_result],
            case_set_content_sha256="0" * 64,
            completed_at="2026-01-15T00:01:00+00:00",
        )
        _insert_shadow_run_raw(path, unregistered_run)
        with pytest.raises(RulePackLifecycleError, match="unregistered"):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=unregistered_run.shadow_run_id,
                confirmed_by="medical_manager",
            )


def test_shadow_case_cannot_self_report_pass_on_result_mismatch() -> None:
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="cannot pass when actual_match differs",
    ):
        RuleShadowCaseResult(
            case_id="case-forged-pass",
            rule_key="protocol_execution.visit_window",
            rule_revision_id="monrule_forged",
            expected_match=False,
            actual_match=True,
            passed=True,
            evidence_summary="forged pass",
        )


def test_shadow_confirmation_rejects_foreign_project_storage_anomaly() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(path)
        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        registered = _registered_case(confirmed_rule, "foreign-run-case")
        repository.store_gold_cases([registered])
        foreign_run = RuleShadowRun.create(
            project_id="proj_other",
            rule_pack_id=shadow.rule_pack_id,
            batch_id="foreign-shadow",
            results=[
                RuleShadowCaseResult(
                    case_id=registered.case_id,
                    rule_key=rule.rule_key,
                    rule_revision_id=rule.rule_revision_id,
                    expected_match=False,
                    actual_match=False,
                    passed=True,
                    evidence_summary="forged foreign result",
                )
            ],
            case_set_content_sha256=gold_case_set_content_sha256([registered]),
            completed_at="2026-01-15T00:00:00+00:00",
        )
        _insert_shadow_run_raw(path, foreign_run)

        with pytest.raises(
            RulePackLifecycleError,
            match="another project or rule pack",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=foreign_run.shadow_run_id,
                confirmed_by="medical_manager",
            )


def test_successful_release_chain_persists_across_restart_with_lineage() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        base = _rule(version, fact)
        lineage_rule = MonitoringRuleDefinition.create(
            project_id=base.project_id,
            protocol_version_id=base.protocol_version_id,
            rule_key=base.rule_key,
            rule_family=base.rule_family,
            status="enabled",
            title=base.title,
            executor=base.executor,
            required_domains=base.required_domains,
            preconditions=base.preconditions,
            trigger_expression=base.trigger_expression,
            exclusions=base.exclusions,
            severity=base.severity,
            confidence=base.confidence,
            evidence_template=base.evidence_template,
            fact_revision_ids=base.fact_revision_ids,
            source_entry_id=base.source_entry_id,
            source_locator=base.source_locator,
            source_text=base.source_text,
            field_lineage=base.field_lineage,
            **_full_identity(),
        )

        published = _publish_pack(
            repository,
            version,
            [lineage_rule],
            clock="2026-01-15T00:00:00+00:00",
        )
        packs = repository.list_rule_packs(version.project_id)
        assert [pack.status for pack in packs] == [
            "draft",
            "shadow",
            "confirmed",
            "published",
        ]
        assert [pack.pack_revision for pack in packs] == [1, 2, 3, 4]
        for previous, current in zip(packs, packs[1:]):
            metadata = repository.rule_pack_lifecycle(current.rule_pack_id)
            assert metadata["predecessor_rule_pack_id"] == previous.rule_pack_id
            assert metadata["transition_actor"]
        confirmed_metadata = repository.rule_pack_lifecycle(packs[2].rule_pack_id)
        assert confirmed_metadata["shadow_run_id"]

        restarted = MonitoringProtocolRuleRepository(path)
        restarted.bind_gold_case_authority(lambda _case, _rule: None)
        current, rules = restarted.current_published_pack(
            version.project_id,
            as_of="2026-01-20",
        )
        assert current.rule_pack_id == published.rule_pack_id
        assert rules[0].status == "enabled"
        assert (
            rules[0].field_lineage["treatment_description"]["domain"]
            == "EX"
        )
        assert restarted.integrity_check() == "ok"


def test_published_rules_and_facts_are_immutable() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        published = _publish_pack(repository, version, [rule])
        _, published_rules = repository.rule_pack(published.rule_pack_id)
        enabled = published_rules[0]

        with pytest.raises(
            MonitoringProtocolStateConflictError,
            match="published rule pack",
        ):
            repository.transition_rule_status(
                enabled.rule_revision_id,
                expected_state_version=enabled.state_version,
                status="disabled",
                actor="medical_manager",
            )
        with pytest.raises(
            MonitoringProtocolStateConflictError,
            match="published rule pack",
        ):
            repository.transition_fact_status(
                fact.fact_revision_id,
                expected_state_version=fact.state_version,
                status="superseded",
                actor="medical_manager",
            )


def test_rule_confirmation_uses_compare_and_swap_under_concurrency() -> None:
    with TemporaryDirectory() as directory:
        repository, _, _, _, rule, _ = _repository_with_candidate_rule(
            Path(directory) / "rules.sqlite3"
        )
        barrier = Barrier(2)

        def confirm(actor: str) -> str:
            barrier.wait()
            try:
                MonitoringRuleLifecycleService(repository).confirm_rule(
                    rule.rule_revision_id,
                    expected_state_version=1,
                    confirmed_by=actor,
                )
                return "confirmed"
            except MonitoringProtocolStateConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(confirm, ("medical_manager_a", "medical_manager_b"))
            )

        assert sorted(outcomes) == ["confirmed", "conflict"]


def test_historical_as_of_replays_the_pack_published_at_that_time() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        first_fact = repository.store_fact(
            _fact(version, source_text="研究药物漏服需复核。")
        )
        first_rule = _rule(version, first_fact, trigger_value="漏服")
        first = _publish_pack(
            repository,
            version,
            [first_rule],
            clock="2026-01-15T00:00:00+00:00",
        )

        second_fact = repository.store_fact(
            ProtocolFact.create(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                fact_key=first_fact.fact_key,
                fact_type=first_fact.fact_type,
                status="medically_confirmed",
                title=first_fact.title,
                normalized_payload={
                    "frequency": "BID",
                    "route": "oral",
                    "review": "missed_or_extra",
                },
                source_entry_id=first_fact.source_entry_id,
                source_locator="docx:table:6:row:11",
                source_text="研究药物漏服或多服均需复核。",
                supersedes_fact_revision_id=first_fact.fact_revision_id,
            )
        )
        second_rule = replace(
            _rule(
                version,
                second_fact,
                trigger_value="漏服|多服",
            ),
            supersedes_rule_revision_id=first_rule.rule_revision_id,
        )
        second = _publish_pack(
            repository,
            version,
            [second_rule],
            clock="2026-02-15T00:00:00+00:00",
        )

        january, january_rules = repository.current_published_pack(
            version.project_id,
            as_of="2026-01-20",
        )
        march, march_rules = repository.current_published_pack(
            version.project_id,
            as_of="2026-03-01",
        )
        assert january.rule_pack_id == first.rule_pack_id
        assert january_rules[0].rule_revision_id == first_rule.rule_revision_id
        assert january_rules[0].source_text == "研究药物漏服需复核。"
        assert march.rule_pack_id == second.rule_pack_id
        assert march_rules[0].rule_revision_id == second_rule.rule_revision_id
        assert march_rules[0].source_text == "研究药物漏服或多服均需复核。"


def test_legacy_database_opens_but_existing_packs_remain_read_only() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        published = _publish_pack(repository, version, [_rule(version, fact)])
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE monitoring_rule_pack_lifecycle")

        restarted = MonitoringProtocolRuleRepository(path)
        restarted.bind_gold_case_authority(lambda _case, _rule: None)
        metadata = restarted.rule_pack_lifecycle(published.rule_pack_id)
        assert metadata["lifecycle_version"] == 0
        assert metadata["legacy_read_only"] is True
        restored, rules = restarted.rule_pack(published.rule_pack_id)
        assert restored.rule_pack_id == published.rule_pack_id
        assert rules[0].status == "enabled"
        with pytest.raises(RulePackLifecycleError, match="legacy"):
            restarted.advance_rule_pack_stage(
                published.rule_pack_id,
                target_status="retired",
                actor="medical_manager",
            )
        with pytest.raises(
            ProtocolApplicabilityUnresolvedError,
            match="no published rule pack",
        ):
            restarted.current_published_pack(
                version.project_id,
                as_of="2026-02-01",
            )


def test_rule_pack_read_rejects_semantically_valid_content_hash_tamper() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, _lifecycle, _version, _fact, _rule, draft = (
            _repository_with_candidate_rule(path)
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_packs SET content_sha256 = ? "
                "WHERE rule_pack_id = ?",
                ("f" * 64, draft.rule_pack_id),
            )

        with pytest.raises(
            RulePackLifecycleError,
            match="stored rule pack identity or content hash mismatch",
        ):
            repository.rule_pack(draft.rule_pack_id)


@pytest.mark.parametrize("corruption", ("rule_state", "fact_state", "snapshot"))
def test_current_published_pack_fails_closed_on_storage_corruption(
    corruption: str,
) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        published = _publish_pack(repository, version, [rule])
        with sqlite3.connect(path) as connection:
            if corruption == "rule_state":
                connection.execute(
                    """
                    UPDATE monitoring_rule_definition_state
                    SET status = 'disabled'
                    WHERE rule_revision_id = ?
                    """,
                    (rule.rule_revision_id,),
                )
            elif corruption == "fact_state":
                connection.execute(
                    """
                    UPDATE monitoring_protocol_fact_state
                    SET status = 'superseded'
                    WHERE fact_revision_id = ?
                    """,
                    (fact.fact_revision_id,),
                )
            else:
                connection.execute(
                    """
                    UPDATE monitoring_rule_pack_items
                    SET fact_statuses_json = '{}'
                    WHERE rule_pack_id = ?
                    """,
                    (published.rule_pack_id,),
                )

        with pytest.raises(RulePackLifecycleError):
            repository.current_published_pack(
                version.project_id,
                as_of="2026-02-01",
            )


@pytest.mark.parametrize(
    ("case_project", "case_rule"),
    (
        ("proj_other", "study_treatment.adherence.missed_dose"),
        ("proj_alpha", "study_treatment.adherence.unknown"),
    ),
)
def test_gold_case_storage_requires_project_and_rule_ownership(
    case_project: str,
    case_rule: str,
) -> None:
    with TemporaryDirectory() as directory:
        repository, _, _, _, stored_rule, _ = _repository_with_candidate_rule(
            Path(directory) / "rules.sqlite3"
        )
        case = RuleGoldStandardCase.create(
            **_gold_case_source(stored_rule, "ownership-check")[1],
            project_id=case_project,
            rule_key=case_rule,
            case_label="ownership-check",
            input_record={"SUBJID": "OWN-001"},
            observed_domains=["EX"],
            expected_match=False,
            medical_rationale="归属校验。",
            evidence_locators=[
                _gold_case_source(stored_rule, "ownership-check")[0]
            ],
        )
        with pytest.raises(RulePackLifecycleError, match="exact stored rule revision"):
            repository.store_gold_cases([case])


def test_publish_fails_closed_when_gold_case_set_changes_after_confirmation() -> None:
    with TemporaryDirectory() as directory:
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(
            Path(directory) / "rules.sqlite3"
        )
        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        first_case = _registered_case(confirmed_rule, "frozen-before-confirm")
        repository.store_gold_cases([first_case])
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="frozen-before-confirm",
        )
        confirmed_pack = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )

        repository.store_gold_cases(
            [_registered_case(confirmed_rule, "added-after-confirm")]
        )
        with pytest.raises(
            RulePackLifecycleError,
            match="complete current gold case set|changed after validation",
        ):
            lifecycle.publish(
                confirmed_pack.rule_pack_id,
                published_by="medical_manager",
            )


@pytest.mark.parametrize(
    "mutation",
    ("wrong_rule_revision", "wrong_source_hash", "empty_locator"),
)
def test_gold_case_release_binding_rejects_forged_revision_source_or_locator(
    mutation: str,
) -> None:
    with TemporaryDirectory() as directory:
        repository, _, _, _, rule, _ = _repository_with_candidate_rule(
            Path(directory) / "rules.sqlite3"
        )
        case = _registered_case(rule, f"forged-{mutation}")
        if mutation == "wrong_rule_revision":
            forged = RuleGoldStandardCase.create(
                project_id=case.project_id,
                rule_key=case.rule_key,
                rule_revision_id="monrule_000000000000000000000000",
                source_entry_id=case.source_entry_id,
                source_content_sha256=case.source_content_sha256,
                source_revision=case.source_revision,
                batch_revision=case.batch_revision,
                case_label=case.case_label,
                input_record=case.input_record,
                previous_record=case.previous_record,
                related_records=case.related_records,
                observed_domains=case.observed_domains,
                expected_match=case.expected_match,
                medical_rationale=case.medical_rationale,
                evidence_locators=case.evidence_locators,
            )
        elif mutation == "wrong_source_hash":
            forged = replace(case, source_content_sha256="f" * 64)
        else:
            forged = replace(case, evidence_locators=())
        with pytest.raises(RulePackLifecycleError):
            repository.store_gold_cases([forged])


@pytest.mark.parametrize(
    "lineage",
    (
        {},
        {
            "review_status": {
                "field": "EXDESC",
                "domain": "EX",
                "lineage": {
                    "source_type": "model_output",
                    "source_locator": "model:review_status",
                },
            }
        },
    ),
)
def test_strict_draft_rejects_empty_or_conclusion_lineage(
    lineage: dict[str, object],
) -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = replace(
            _rule(version, fact),
            status="candidate",
            field_lineage=lineage,
        )
        lifecycle = MonitoringRuleLifecycleService(repository)
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="field_lineage|field lineage",
        ):
            lifecycle.create_draft(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
            )


def test_legacy_shadow_run_without_case_snapshot_hash_cannot_be_confirmed() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(
            path
        )
        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        repository.store_gold_cases(
            [_registered_case(confirmed_rule, "legacy-run")]
        )
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="legacy-run",
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE monitoring_rule_shadow_runs
                SET case_set_content_sha256 = ''
                WHERE shadow_run_id = ?
                """,
                (run.shadow_run_id,),
            )
        with pytest.raises(
            RulePackLifecycleError,
            match="legacy shadow run",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=run.shadow_run_id,
                confirmed_by="medical_manager",
            )


def test_indeterminate_negative_gold_case_cannot_pass_strict_shadow() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        base_rule = _rule(version, fact)
        candidate_rule = MonitoringRuleDefinition.create(
            project_id=base_rule.project_id,
            protocol_version_id=base_rule.protocol_version_id,
            rule_key=base_rule.rule_key,
            rule_family=base_rule.rule_family,
            status="candidate",
            title=base_rule.title,
            executor=base_rule.executor,
            required_domains=base_rule.required_domains,
            preconditions=base_rule.preconditions,
            trigger_expression={"gt": {"field": "EXDESC", "value": 1}},
            exclusions=base_rule.exclusions,
            severity=base_rule.severity,
            confidence=base_rule.confidence,
            evidence_template=base_rule.evidence_template,
            fact_revision_ids=base_rule.fact_revision_ids,
            source_entry_id=base_rule.source_entry_id,
            source_locator=base_rule.source_locator,
            source_text=base_rule.source_text,
            clinical_domain=base_rule.clinical_domain,
            source_refs=base_rule.source_refs,
            field_lineage=base_rule.field_lineage,
            **_full_identity(),
        )
        lifecycle = MonitoringRuleLifecycleService(repository)
        draft = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[candidate_rule],
            created_by="rule_author",
        )
        confirmed_rule = lifecycle.confirm_rule(
            candidate_rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        locator, source = _gold_case_source(
            confirmed_rule,
            "indeterminate-negative",
        )
        case = RuleGoldStandardCase.create(
            **source,
            project_id=version.project_id,
            rule_key=confirmed_rule.rule_key,
            case_label="indeterminate-negative",
            input_record={
                "SUBJID": "LIFECYCLE-INDET-001",
                "EXDESC": "not-a-number",
                "evidence_span_ids": [locator],
            },
            observed_domains=confirmed_rule.required_domains,
            expected_match=False,
            medical_rationale="不确定结果不得冒充阴性金标准。",
            evidence_locators=[locator],
        )
        repository.store_gold_cases([case])

        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="indeterminate-negative",
        )

        assert run.case_count == 1
        assert run.passed_count == 0
        assert run.failed_count == 1
        assert run.results[0].actual_match is False
        assert run.results[0].passed is False
        assert run.release_gate_eligible is False
        with pytest.raises(RulePackLifecycleError, match="pass every case"):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=run.shadow_run_id,
                confirmed_by="medical_manager",
            )


def test_draft_pack_rejects_confirmed_rule_without_identity() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version(
                "proj_identity_gate",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = replace(
            _rule(version, fact),
            status="confirmed",
            mapping_revision="",
            mapping_content_sha256="",
            capability_manifest_sha256="",
            effective_capabilities_sha256="",
        )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        with pytest.raises(
            RulePackLifecycleError,
            match="immutable mapping identity",
        ):
            lifecycle.create_draft(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
            )


_IDENTITY_FIELDS = (
    "mapping_revision",
    "mapping_content_sha256",
    "capability_manifest_sha256",
    "effective_capabilities_sha256",
)


@pytest.mark.parametrize("field", _IDENTITY_FIELDS)
def test_rule_confirmation_fails_closed_on_each_missing_identity_field(
    field: str,
) -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version(
                "proj_identity_gate",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact, status="candidate")
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )
        connection = sqlite3.connect(repository.db_path)
        try:
            connection.execute(
                f"UPDATE monitoring_rule_definitions SET {field} = ''"
            )
            connection.commit()
        finally:
            connection.close()

        with pytest.raises(
            MonitoringProtocolStateConflictError,
            match="complete immutable mapping identity",
        ):
            lifecycle.confirm_rule(
                rule.rule_revision_id,
                expected_state_version=1,
                confirmed_by="medical_manager",
            )


@pytest.mark.parametrize("field", _IDENTITY_FIELDS)
def test_mixed_rule_pack_identity_fails_closed_on_shadow(field: str) -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version(
                "proj_identity_mixed",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule_a = _rule(version, fact, status="candidate")
        override = (
            "mapping-v9" if field == "mapping_revision" else "9" * 64
        )
        rule_b = _rule_with_identity(
            _rule(
                version,
                fact,
                status="candidate",
                rule_key="study_treatment.adherence.dose_change",
            ),
            **_full_identity(**{field: override}),
        )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        draft = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule_a, rule_b],
            created_by="rule_author",
        )
        lifecycle.confirm_rule(
            rule_a.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        lifecycle.confirm_rule(
            rule_b.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )

        with pytest.raises(RulePackLifecycleError, match="uniform"):
            lifecycle.start_shadow(
                draft.rule_pack_id,
                started_by="shadow_operator",
            )


def test_draft_pack_rejects_confirmed_rule_missing_effective_hash() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version(
                "proj_identity_gate",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = replace(
            _rule(version, fact),
            status="confirmed",
            effective_capabilities_sha256="",
        )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        with pytest.raises(
            RulePackLifecycleError,
            match="immutable mapping identity",
        ):
            lifecycle.create_draft(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
            )


def test_confirmed_rule_with_identity_enters_shadow_without_second_approval(
) -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version(
                "proj_identity_shadow",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        base = _rule(version, fact, status="candidate")
        rule = replace(
            _rule_with_identity(
                base,
                mapping_revision="mapping-revision-001",
                mapping_content_sha256="a" * 64,
                capability_manifest_sha256="b" * 64,
                effective_capabilities_sha256="c" * 64,
                recommendation_candidate_id="candidate-001",
            ),
            status="confirmed",
        )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        draft = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )
        _, stored_rules = repository.rule_pack(draft.rule_pack_id)
        assert stored_rules[0].status == "confirmed"
        assert stored_rules[0].mapping_revision == "mapping-revision-001"
        assert stored_rules[0].mapping_content_sha256 == "a" * 64
        assert stored_rules[0].capability_manifest_sha256 == "b" * 64
        assert stored_rules[0].effective_capabilities_sha256 == "c" * 64
        assert stored_rules[0].recommendation_candidate_id == "candidate-001"

        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        assert shadow.status == "shadow"


def _pack_table_counts(path: Path, project_id: str) -> tuple[int, int]:
    with sqlite3.connect(path) as connection:
        packs = connection.execute(
            "SELECT COUNT(*) FROM monitoring_rule_packs WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        lifecycle_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM monitoring_rule_pack_lifecycle l
            JOIN monitoring_rule_packs p
              ON p.rule_pack_id = l.rule_pack_id
            WHERE p.project_id = ?
            """,
            (project_id,),
        ).fetchone()[0]
    return int(packs), int(lifecycle_rows)


def _shadow_pack_with_trusted_run(path: Path):
    repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(path)
    confirmed_rule = lifecycle.confirm_rule(
        rule.rule_revision_id,
        expected_state_version=1,
        confirmed_by="medical_manager",
    )
    shadow = lifecycle.start_shadow(
        draft.rule_pack_id,
        started_by="shadow_operator",
    )
    _store_p7c_release_evidence(repository, [confirmed_rule])
    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id="replay-shadow",
    )
    return repository, lifecycle, draft, shadow, run


def test_duplicate_draft_creation_replays_existing_pack() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, version, fact, rule, draft = (
            _repository_with_candidate_rule(path)
        )

        replayed = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )

        assert replayed.rule_pack_id == draft.rule_pack_id
        assert replayed.pack_revision == draft.pack_revision
        assert (
            repository.next_pack_revision(version.project_id)
            == draft.pack_revision + 1
        )
        assert _pack_table_counts(path, version.project_id) == (1, 1)

        changed_rule = replace(
            _rule(version, fact, trigger_value="多服"),
            status="candidate",
        )
        follow_up = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[changed_rule],
            created_by="rule_author",
        )
        assert follow_up.rule_pack_id != draft.rule_pack_id
        assert follow_up.pack_revision == draft.pack_revision + 1
        assert _pack_table_counts(path, version.project_id) == (2, 2)


def test_start_shadow_retry_with_original_draft_replays_existing_shadow() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(
            path
        )
        lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        assert _pack_table_counts(path, draft.project_id) == (2, 2)

        replayed = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )

        assert replayed.rule_pack_id == shadow.rule_pack_id
        assert replayed.status == "shadow"
        assert _pack_table_counts(path, draft.project_id) == (2, 2)
        assert repository.latest_rule_pack(draft.project_id) is not None


def test_confirm_shadow_replays_same_run_and_conflicts_on_different_run() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, shadow, run = _shadow_pack_with_trusted_run(path)
        confirmed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        assert _pack_table_counts(path, shadow.project_id) == (3, 3)

        replayed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        assert replayed.rule_pack_id == confirmed.rule_pack_id
        assert replayed.status == "confirmed"
        assert _pack_table_counts(path, shadow.project_id) == (3, 3)

        with pytest.raises(
            RulePackRevisionConflictError,
            match="different shadow run",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id="monrun_different_shadow_run",
                confirmed_by="medical_manager",
            )
        assert _pack_table_counts(path, shadow.project_id) == (3, 3)
        assert repository.latest_rule_pack(shadow.project_id) is not None


def test_publish_retry_replays_published_pack() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        _, lifecycle, _, shadow, run = _shadow_pack_with_trusted_run(path)
        confirmed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        published = lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )
        assert _pack_table_counts(path, shadow.project_id) == (4, 4)

        replayed = lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )

        assert replayed.rule_pack_id == published.rule_pack_id
        assert replayed.status == "published"
        assert _pack_table_counts(path, shadow.project_id) == (4, 4)


def test_expected_pack_revision_guards_draft_creation() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = replace(_rule(version, fact), status="candidate")
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )

        with pytest.raises(
            RulePackRevisionConflictError,
            match="expected pack revision",
        ):
            lifecycle.create_draft(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
                expected_pack_revision=2,
            )
        assert _pack_table_counts(path, version.project_id) == (0, 0)

        draft = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
            expected_pack_revision=1,
        )
        replayed = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
            expected_pack_revision=draft.pack_revision,
        )
        assert replayed.rule_pack_id == draft.rule_pack_id
        assert _pack_table_counts(path, version.project_id) == (1, 1)

        with pytest.raises(
            RulePackRevisionConflictError,
            match="expected pack revision",
        ):
            lifecycle.create_draft(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
                expected_pack_revision=99,
            )
        assert _pack_table_counts(path, version.project_id) == (1, 1)


def test_expected_pack_revision_guards_each_stage_transition() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, _, _, rule, draft = _repository_with_candidate_rule(
            path
        )
        confirmed_rule = lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )

        with pytest.raises(
            RulePackRevisionConflictError,
            match="expected pack revision",
        ):
            lifecycle.start_shadow(
                draft.rule_pack_id,
                started_by="shadow_operator",
                expected_pack_revision=draft.pack_revision + 1,
            )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
            expected_pack_revision=draft.pack_revision,
        )
        assert shadow.status == "shadow"

        _store_p7c_release_evidence(repository, [confirmed_rule])
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="revision-guard-shadow",
        )
        with pytest.raises(
            RulePackRevisionConflictError,
            match="expected pack revision",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=run.shadow_run_id,
                confirmed_by="medical_manager",
                expected_pack_revision=draft.pack_revision,
            )
        confirmed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
            expected_pack_revision=shadow.pack_revision,
        )
        assert confirmed.status == "confirmed"

        with pytest.raises(
            RulePackRevisionConflictError,
            match="expected pack revision",
        ):
            lifecycle.publish(
                confirmed.rule_pack_id,
                published_by="medical_manager",
                expected_pack_revision=shadow.pack_revision,
            )
        published = lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
            expected_pack_revision=confirmed.pack_revision,
        )
        assert published.status == "published"
        assert _pack_table_counts(path, draft.project_id) == (4, 4)


def test_stage_replay_never_returns_successor_from_another_project() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository, lifecycle, version, _, rule, draft = (
            _repository_with_candidate_rule(path)
        )
        lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                DELETE FROM monitoring_rule_pack_lifecycle
                WHERE rule_pack_id = ?
                """,
                (shadow.rule_pack_id,),
            )
            connection.execute(
                """
                INSERT INTO monitoring_rule_packs (
                    rule_pack_id, project_id, protocol_version_id,
                    pack_revision, status, applicability_status,
                    content_sha256, created_by, retrospective_policy,
                    published_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "monpack_foreign_replay_successor",
                    "proj_other",
                    version.protocol_version_id,
                    1,
                    "shadow",
                    version.applicability_status,
                    "0" * 64,
                    "intruder",
                    "open_risks_only",
                    "",
                    "2026-01-15T00:00:00+00:00",
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_rule_pack_lifecycle (
                    rule_pack_id, lifecycle_version, predecessor_rule_pack_id,
                    transition_actor, transition_at, shadow_run_id,
                    legacy_read_only
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "monpack_foreign_replay_successor",
                    1,
                    draft.rule_pack_id,
                    "intruder",
                    "2026-01-15T00:00:00+00:00",
                    "",
                ),
            )

        with pytest.raises(
            RulePackRevisionConflictError,
            match="another project",
        ):
            lifecycle.start_shadow(
                draft.rule_pack_id,
                started_by="shadow_operator",
            )
        # The intentionally malformed foreign row remains persisted, but the
        # strict pack reader must fail closed rather than hydrate it as a pack.
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT 1 FROM monitoring_rule_packs WHERE project_id = ?",
                ("proj_other",),
            ).fetchone() is not None
