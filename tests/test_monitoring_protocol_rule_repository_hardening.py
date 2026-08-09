from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
    MonitoringProtocolStateConflictError,
    ProtocolApplicabilityConflictError,
    ProtocolApplicabilityUnresolvedError,
    RulePackLifecycleError,
    RulePackPublicationError,
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
    ProtocolApplicabilityAssignment,
    ProtocolSourceVersion,
    RuleGoldStandardCase,
    RuleRiskBinding,
    RuleReReviewTask,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _gold_case_source,
    _pack,
    _publish_pack,
    _rule,
    _start_shadow_pack,
    _store_p7c_release_evidence,
    _version,
)


def test_rule_pack_store_preserves_revision_identity_for_legacy_unit_lineage() -> None:
    """Legacy unit normalization must not mutate the revision-bearing rule."""

    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version("proj_identity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        base_rule = _rule(version, fact, status="candidate")
        legacy_lineage = deepcopy(base_rule.field_lineage)
        legacy_lineage["derived_event_date"] = {
            "field": "DERIVED_EVENT_DATE",
            "domain": "EX",
            "lineage": {
                "source_type": "auditable_base_value",
                "input_field_roles": ["event_date"],
                "calculation_expression": "minimum(event_date)",
                "unit": "ISO-8601 date",
                "source_locator": (
                    "listing:test:derived:field:DERIVED_EVENT_DATE:header-source"
                ),
            },
        }
        legacy_rule = MonitoringRuleDefinition.create(
            project_id=base_rule.project_id,
            protocol_version_id=base_rule.protocol_version_id,
            rule_key=base_rule.rule_key,
            rule_family=base_rule.rule_family,
            status=base_rule.status,
            title=base_rule.title,
            executor=base_rule.executor,
            required_domains=base_rule.required_domains,
            preconditions=base_rule.preconditions,
            trigger_expression=base_rule.trigger_expression,
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
            field_lineage=legacy_lineage,
            mapping_revision=base_rule.mapping_revision,
            mapping_content_sha256=base_rule.mapping_content_sha256,
            capability_manifest_sha256=base_rule.capability_manifest_sha256,
            effective_capabilities_sha256=base_rule.effective_capabilities_sha256,
        )
        original_revision_id = legacy_rule.rule_revision_id

        stored_pack = repository.store_rule_pack(
            _pack(repository, version, [legacy_rule], status="draft"),
            [legacy_rule],
        )
        _loaded_pack, loaded_rules = repository.rule_pack(stored_pack.rule_pack_id)

        assert loaded_rules[0].rule_revision_id == original_revision_id
        assert loaded_rules[0].field_lineage["derived_event_date"]["lineage"][
            "unit"
        ] == "ISO-8601 date"


def test_persisted_legacy_lifecycle_flag_rejects_truthy_text() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        candidate_rule = _rule(version, fact, status="candidate")
        draft = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[candidate_rule],
            created_by="rule_author",
        )

        with sqlite3.connect(repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_pack_lifecycle "
                "SET legacy_read_only = ? WHERE rule_pack_id = ?",
                ("false", draft.rule_pack_id),
            )

        with pytest.raises(RulePackLifecycleError, match="legacy_read_only"):
            repository.rule_pack_lifecycle(draft.rule_pack_id)


def test_persisted_gold_case_expected_match_rejects_truthy_text() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        confirmed_rule = confirmed_rules[0]
        locator, source = _gold_case_source(confirmed_rule, "strict-bool")
        case = RuleGoldStandardCase.create(
            **source,
            project_id=confirmed_rule.project_id,
            rule_key=confirmed_rule.rule_key,
            case_label="strict-bool",
            input_record={
                "SUBJID": "S001",
                "EXDESC": "漏服",
                "evidence_span_ids": [locator],
            },
            observed_domains=confirmed_rule.required_domains,
            expected_match=True,
            coverage_labels=("positive",),
            medical_rationale="严格布尔回归夹具。",
            evidence_locators=[locator],
        )
        repository.store_gold_cases([case])

        with sqlite3.connect(repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_gold_cases "
                "SET expected_match = ? WHERE case_id = ?",
                ("false", case.case_id),
            )

        with pytest.raises(RulePackLifecycleError, match="expected_match"):
            repository.gold_cases(version.project_id)


def test_cas_state_transitions_preserve_immutable_revision_identity_and_audit() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        initial_version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        candidate_fact = repository.store_fact(
            _fact(initial_version, status="ai_candidate")
        )
        candidate_rule = _rule(
            initial_version,
            candidate_fact,
            status="candidate",
        )
        effective_version = repository.transition_protocol_version_state(
            initial_version.protocol_version_id,
            expected_state_version=1,
            status="confirmed",
            applicability_status="project_effective_confirmed",
            operational_effective_from="2026-01-10",
        )
        confirmed_fact = repository.transition_fact_status(
            candidate_fact.fact_revision_id,
            expected_state_version=1,
            status="medically_confirmed",
            actor="medical_manager",
        )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-01-15T00:00:00+00:00",
        )
        draft_pack = lifecycle.create_draft(
            project_id=initial_version.project_id,
            protocol_version_id=initial_version.protocol_version_id,
            rules=[candidate_rule],
            created_by="rule_author",
        )
        confirmed_rule = lifecycle.confirm_rule(
            candidate_rule.rule_revision_id,
            expected_state_version=1,
            confirmed_by="medical_manager",
        )

        assert effective_version.protocol_version_id == initial_version.protocol_version_id
        assert confirmed_fact.fact_revision_id == candidate_fact.fact_revision_id
        assert confirmed_rule.rule_revision_id == candidate_rule.rule_revision_id
        assert (effective_version.state_version, confirmed_fact.state_version, confirmed_rule.state_version) == (
            2,
            2,
            2,
        )

        with pytest.raises(MonitoringProtocolStateConflictError, match="current 2"):
            repository.transition_rule_status(
                candidate_rule.rule_revision_id,
                expected_state_version=1,
                status="disabled",
            )

        shadow = lifecycle.start_shadow(
            draft_pack.rule_pack_id,
            started_by="shadow_operator",
        )
        _store_p7c_release_evidence(repository, [confirmed_rule])
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="cas-shadow",
        )
        confirmed_pack = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        published = lifecycle.publish(
            confirmed_pack.rule_pack_id,
            published_by="medical_manager",
        )
        current, current_rules = repository.current_published_pack(
            effective_version.project_id,
            as_of="2026-02-01",
        )
        assert current.rule_pack_id == published.rule_pack_id
        assert current_rules[0].status == "enabled"
        assert current_rules[0].state_version == 3

        with sqlite3.connect(repository.db_path) as connection:
            event_types = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT aggregate_type FROM monitoring_protocol_rule_events
                    WHERE event_type = 'transitioned'
                    """
                )
            }
        assert event_types == {
            "protocol_version_state",
            "protocol_fact_state",
            "rule_definition_state",
        }


def test_superseded_protocol_cannot_be_published_or_returned_as_current() -> None:
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
        _publish_pack(repository, version, [rule])

        superseded = repository.transition_protocol_version_state(
            version.protocol_version_id,
            expected_state_version=1,
            status="superseded",
            applicability_status=version.applicability_status,
            operational_effective_from=version.operational_effective_from,
        )
        assert superseded.status == "superseded"
        with pytest.raises(ProtocolApplicabilityUnresolvedError):
            repository.current_published_pack(
                version.project_id,
                as_of="2026-02-01",
            )

        with pytest.raises(RulePackPublicationError, match="non-superseded"):
            _publish_pack(
                repository,
                version,
                [_rule(version, fact, trigger_value="多服")],
            )


def test_cm_fact_cannot_publish_as_study_treatment_change_rule() -> None:
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
        cm_fact = repository.store_fact(
            _fact(
                version,
                key="concomitant_medication.prohibited.other_c5",
                fact_type="concomitant_medication_prohibited",
                source_text="研究期间禁止使用其他 C5 抑制剂。",
            )
        )
        invalid_rule = _rule(
            version,
            cm_fact,
            rule_key="study_treatment.change.other_c5",
            rule_family="study_treatment_change",
        )
        invalid_rule = replace(invalid_rule, status="candidate")
        with pytest.raises(
            RulePackPublicationError,
            match="fact clinical domain concomitant_medication",
        ):
            repository.store_rule_pack(
                _pack(repository, version, [invalid_rule], status="draft"),
                [invalid_rule],
            )


def test_rule_source_reference_must_match_bound_fact_source() -> None:
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
        valid_lineage = _rule(version, fact).field_lineage
        wrong_source_rule = MonitoringRuleDefinition.create(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rule_key="study_treatment.adherence.wrong_source",
            rule_family="study_treatment_adherence",
            status="enabled",
            title="研究药物依从性记录需复核",
            executor="field_predicate",
            required_domains=["EX"],
            preconditions={"exists": {"field": "SUBJID"}},
            trigger_expression={"regex": {"field": "EXDESC", "value": "漏服"}},
            exclusions={"missing": {"field": "EXDESC"}},
            severity="high",
            confidence="deterministic",
            evidence_template="{EXDESC}",
            fact_revision_ids=[fact.fact_revision_id],
            source_entry_id=fact.source_entry_id,
            source_locator="docx:paragraph:999",
            source_text="与事实无关的方案原文。",
            field_lineage=valid_lineage,
        )
        wrong_source_rule = replace(wrong_source_rule, status="candidate")
        with pytest.raises(RulePackPublicationError, match="do not match"):
            repository.store_rule_pack(
                _pack(repository, version, [wrong_source_rule], status="draft"),
                [wrong_source_rule],
            )


@pytest.mark.parametrize(
    ("expression", "message"),
    (
        (
            {"date_delta_days": {"field": "AESTDTC", "value": 7}},
            "field, other_field and value",
        ),
        (
            {"date_delta_days": {"field": "AESTDTC", "other_field": "EXSTDTC", "value": -1}},
            "non-negative number",
        ),
        (
            {"no_corresponding_record": {"field": "AETERM"}},
            "domain alone or domain, field and value",
        ),
        (
            {"no_corresponding_record": {"domain": ""}},
            "domain is required",
        ),
    ),
)
def test_predicate_operator_schemas_fail_closed(
    expression: dict,
    message: str,
) -> None:
    version = _version("proj_alpha", "V1.0", "2026-01-01")
    fact = _fact(version)
    with pytest.raises(MonitoringProtocolRuleError, match=message):
        MonitoringRuleDefinition.create(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rule_key="study_treatment.adherence.invalid_predicate",
            rule_family="study_treatment_adherence",
            status="candidate",
            title="无效谓词不得入库",
            executor="temporal",
            required_domains=["EX"],
            preconditions={"exists": {"field": "SUBJID"}},
            trigger_expression=expression,
            exclusions={"exists": {"field": "__RULE_EXCLUDED__"}},
            severity="high",
            confidence="deterministic",
            evidence_template="{SUBJID}",
            fact_revision_ids=[fact.fact_revision_id],
            source_entry_id=fact.source_entry_id,
            source_locator=fact.source_locator,
            source_text=fact.source_text,
        )


def test_existing_sqlite_schema_is_migrated_without_losing_rows() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version, status="ai_candidate"))

        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE monitoring_protocol_fact_state")
            connection.commit()

        reopened = MonitoringProtocolRuleRepository(path)
        restored = reopened.facts_for_version(version.protocol_version_id)
        assert restored[0].fact_revision_id == fact.fact_revision_id
        assert restored[0].status == "ai_candidate"
        assert restored[0].clinical_domain == "study_treatment"
        assert reopened.integrity_check() == "ok"


def test_persisted_protocol_fact_source_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_fact_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_protocol_facts SET source_text = ? "
                "WHERE fact_revision_id = ?",
                ("语义有效但被篡改的方案事实。", fact.fact_revision_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted protocol fact source hash or identity mismatch",
        ):
            repository.facts_for_version(version.protocol_version_id)


def test_persisted_protocol_version_content_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_version_integrity", "V1.0", "2026-01-01")
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_protocol_versions SET content_sha256 = ? "
                "WHERE protocol_version_id = ?",
                ("f" * 64, version.protocol_version_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted protocol source version identity mismatch",
        ):
            repository.protocol_version(version.protocol_version_id)


def test_persisted_protocol_version_content_digest_shape_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_version_digest_shape", "V1.0", "2026-01-01")
        )

        for malformed in (f" {'a' * 64}", "A" * 64, 123):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_protocol_versions "
                    "SET content_sha256 = ? WHERE protocol_version_id = ?",
                    (malformed, version.protocol_version_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted protocol source version is invalid",
            ):
                repository.protocol_version(version.protocol_version_id)


def test_persisted_applicability_assignment_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _site_version("proj_assignment_integrity", "V1.0", "a")
        )
        assignment = repository.create_applicability_assignment(
            _assignment(version)
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_protocol_applicability_assignments "
                "SET evidence_text = ? WHERE assignment_id = ?",
                (
                    "语义有效但被篡改的适用性证据。",
                    assignment.assignment_id,
                ),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted protocol applicability assignment identity mismatch",
        ):
            repository.applicability_assignment(
                assignment.project_id,
                assignment.assignment_id,
            )


def test_applicability_assignment_source_hash_shape_fails_closed() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _site_version("proj_assignment_digest_shape", "V1.0", "a")
        )
        assignment = _assignment(version)
        for malformed in (f" {'a' * 64}", "A" * 64, 123):
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="evidence_source_content_sha256 must be a canonical lowercase SHA-256 digest",
            ):
                ProtocolApplicabilityAssignment.create(
                    project_id=assignment.project_id,
                    protocol_version_id=assignment.protocol_version_id,
                    centre_id=assignment.centre_id,
                    subject_id=assignment.subject_id,
                    operational_effective_from=(
                        assignment.operational_effective_from
                    ),
                    operational_effective_to=assignment.operational_effective_to,
                    evidence_text=assignment.evidence_text,
                    evidence_source_content_sha256=malformed,
                    evidence_source_entry_id=assignment.evidence_source_entry_id,
                    evidence_locator=assignment.evidence_locator,
                    created_by=assignment.created_by,
                )

        stored = repository.create_applicability_assignment(assignment)
        for malformed in (f" {'a' * 64}", "A" * 64, 123):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_protocol_applicability_assignments "
                    "SET evidence_source_content_sha256 = ? "
                    "WHERE assignment_id = ?",
                    (malformed, stored.assignment_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted protocol applicability assignment is invalid",
            ):
                repository.applicability_assignment(
                    stored.project_id,
                    stored.assignment_id,
                )
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_protocol_applicability_assignments "
                    "SET evidence_source_content_sha256 = ? "
                    "WHERE assignment_id = ?",
                    (stored.evidence_source_content_sha256, stored.assignment_id),
                )


def test_persisted_protocol_rule_source_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_rule_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact, status="candidate")
        draft = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_definitions SET source_text = ? "
                "WHERE rule_revision_id = ?",
                ("语义有效但被篡改的规则来源。", rule.rule_revision_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted monitoring rule source hash or identity mismatch",
        ):
            repository.rule_source(draft.rule_pack_id, rule.rule_key)


def test_persisted_protocol_rule_source_hash_shape_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_rule_source_digest_shape", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact, status="candidate")
        draft = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )
        for malformed in (f" {'a' * 64}", rule.source_text_sha256.upper(), 123):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_definitions SET source_text_sha256 = ? "
                    "WHERE rule_revision_id = ?",
                    (malformed, rule.rule_revision_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted monitoring rule source hash or identity mismatch",
            ):
                repository.rule_source(draft.rule_pack_id, rule.rule_key)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_definitions SET source_text_sha256 = ? "
                    "WHERE rule_revision_id = ?",
                    (rule.source_text_sha256, rule.rule_revision_id),
                )


def test_persisted_protocol_rule_mapping_digest_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_rule_identity_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact, status="candidate")
        draft = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[rule],
            created_by="rule_author",
        )

        for malformed in (f" {'2' * 64}", "A" * 64, 123):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_definitions "
                    "SET mapping_content_sha256 = ? "
                    "WHERE rule_revision_id = ?",
                    (malformed, rule.rule_revision_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted monitoring rule is invalid",
            ):
                repository.rule_source(draft.rule_pack_id, rule.rule_key)


def test_persisted_shadow_run_content_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_shadow_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="shadow-integrity",
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_shadow_runs SET "
                "case_set_content_sha256 = ? WHERE shadow_run_id = ?",
                ("f" * 64, run.shadow_run_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted monitoring shadow run identity or content mismatch",
        ):
            repository.shadow_runs(version.project_id)


def test_persisted_shadow_run_hash_shape_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_shadow_hash_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        run = MonitoringProtocolRuleService(repository).run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="shadow-hash-shape",
        )
        canonical = {
            "case_set_content_sha256": run.case_set_content_sha256,
            "diagnostic_case_set_content_sha256": (
                run.diagnostic_case_set_content_sha256
            ),
            "diagnostic_results_content_sha256": (
                run.diagnostic_results_content_sha256
            ),
            "coverage_content_sha256": run.coverage_content_sha256,
        }

        for field, original in canonical.items():
            for malformed in (f" {original}", original.upper(), 123):
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        f"UPDATE monitoring_rule_shadow_runs SET {field} = ? "
                        "WHERE shadow_run_id = ?",
                        (malformed, run.shadow_run_id),
                    )
                with pytest.raises(
                    MonitoringProtocolRuleError,
                    match="persisted monitoring shadow run",
                ):
                    repository.shadow_runs(version.project_id)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        f"UPDATE monitoring_rule_shadow_runs SET {field} = ? "
                        "WHERE shadow_run_id = ?",
                        (original, run.shadow_run_id),
                    )


def test_persisted_gold_case_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_gold_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        case = repository.gold_cases(version.project_id)[0]

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_gold_cases SET case_label = ? "
                "WHERE case_id = ?",
                ("语义有效但被篡改的金标准案例。", case.case_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted gold standard case identity or content mismatch",
        ):
            repository.gold_cases(version.project_id)


def test_persisted_gold_source_row_fingerprint_shape_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_gold_row_fingerprint_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        case = repository.gold_cases(version.project_id)[0]

        with sqlite3.connect(path) as connection:
            original_json = connection.execute(
                "SELECT source_row_bindings_json "
                "FROM monitoring_rule_gold_cases WHERE case_id = ?",
                (case.case_id,),
            ).fetchone()[0]
        bindings = json.loads(original_json)
        assert bindings and isinstance(bindings[0], dict)
        original_fingerprint = bindings[0]["row_fingerprint"]

        for malformed in (
            f" {original_fingerprint}",
            original_fingerprint.upper(),
            123,
        ):
            tampered = [dict(item) for item in bindings]
            tampered[0]["row_fingerprint"] = malformed
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_gold_cases "
                    "SET source_row_bindings_json = ? WHERE case_id = ?",
                    (json.dumps(tampered, ensure_ascii=False), case.case_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="gold source row binding|persisted gold standard case",
            ):
                repository.gold_cases(version.project_id)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_gold_cases "
                    "SET source_row_bindings_json = ? WHERE case_id = ?",
                    (original_json, case.case_id),
                )


def test_persisted_diagnostic_case_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_diagnostic_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        case = repository.diagnostic_cases(version.project_id)[0]

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_diagnostic_cases "
                "SET expected_diagnostic_code = ? WHERE case_id = ?",
                ("tampered_diagnostic_code", case.case_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted diagnostic case identity or content mismatch",
        ):
            repository.diagnostic_cases(version.project_id)


def test_persisted_case_source_hash_shape_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_case_hash_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        gold_case = repository.gold_cases(version.project_id)[0]
        diagnostic_case = repository.diagnostic_cases(version.project_id)[0]

        for malformed in (f" {'a' * 64}", "A" * 64, 123):
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_gold_cases "
                    "SET source_content_sha256 = ? WHERE case_id = ?",
                    (malformed, gold_case.case_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted gold standard case is invalid",
            ):
                repository.gold_cases(version.project_id)

            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_gold_cases "
                    "SET source_content_sha256 = ? WHERE case_id = ?",
                    (gold_case.source_content_sha256, gold_case.case_id),
                )
                connection.execute(
                    "UPDATE monitoring_rule_diagnostic_cases "
                    "SET source_content_sha256 = ? WHERE case_id = ?",
                    (malformed, diagnostic_case.case_id),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="persisted diagnostic case is invalid",
            ):
                repository.diagnostic_cases(version.project_id)

            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE monitoring_rule_diagnostic_cases "
                    "SET source_content_sha256 = ? WHERE case_id = ?",
                    (
                        diagnostic_case.source_content_sha256,
                        diagnostic_case.case_id,
                    ),
                )


def test_persisted_case_locator_hash_case_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        version = repository.register_protocol_version(
            _version("proj_case_locator_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        lifecycle, _shadow, confirmed_rules = _start_shadow_pack(
            repository,
            version,
            [_rule(version, fact)],
        )
        del lifecycle
        _store_p7c_release_evidence(repository, confirmed_rules)
        gold_case = repository.gold_cases(version.project_id)[0]
        diagnostic_case = repository.diagnostic_cases(version.project_id)[0]

        for table, case, read_cases, locator_column in (
            (
                "monitoring_rule_gold_cases",
                gold_case,
                repository.gold_cases,
                "gold standard",
            ),
            (
                "monitoring_rule_diagnostic_cases",
                diagnostic_case,
                repository.diagnostic_cases,
                "diagnostic",
            ),
        ):
            with sqlite3.connect(path) as connection:
                original_locators_json = connection.execute(
                    f"SELECT evidence_locators_json FROM {table} "
                    "WHERE case_id = ?",
                    (case.case_id,),
                ).fetchone()[0]
                original_bindings_json = connection.execute(
                    f"SELECT source_row_bindings_json FROM {table} "
                    "WHERE case_id = ?",
                    (case.case_id,),
                ).fetchone()[0]
            locators = json.loads(original_locators_json)
            bindings = json.loads(original_bindings_json)
            assert locators and bindings
            digest = case.source_content_sha256
            tampered_locators = [
                locator.replace(digest, digest.upper())
                for locator in locators
            ]
            tampered_bindings = [dict(item) for item in bindings]
            for binding in tampered_bindings:
                binding["source_locator"] = binding["source_locator"].replace(
                    digest,
                    digest.upper(),
                )
            with sqlite3.connect(path) as connection:
                connection.execute(
                    f"UPDATE {table} SET evidence_locators_json = ?, "
                    "source_row_bindings_json = ? WHERE case_id = ?",
                    (
                        json.dumps(tampered_locators, ensure_ascii=False),
                        json.dumps(tampered_bindings, ensure_ascii=False),
                        case.case_id,
                    ),
                )
            with pytest.raises(
                MonitoringProtocolRuleError,
                match=(
                    f"persisted {locator_column} case is invalid|"
                    "evidence locators must bind source_content_sha256"
                ),
            ):
                read_cases(version.project_id)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    f"UPDATE {table} SET evidence_locators_json = ?, "
                    "source_row_bindings_json = ? WHERE case_id = ?",
                    (
                        original_locators_json,
                        original_bindings_json,
                        case.case_id,
                    ),
                )


def test_persisted_re_review_task_tamper_fails_closed_on_read() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_re_review_integrity", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        previous_rule = _rule(version, fact, trigger_value="漏服")
        current_rule = _rule(version, fact, trigger_value="多服")
        previous_pack = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[replace(previous_rule, status="candidate")],
            created_by="rule_author",
        )
        current_pack = MonitoringRuleLifecycleService(repository).create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[replace(current_rule, status="candidate")],
            created_by="rule_author",
        )
        tasks = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=lambda binding: (
                binding.risk_instance_id == "risk-001"
            ),
        ).schedule_re_reviews(
            previous_rule_pack_id=previous_pack.rule_pack_id,
            current_rule_pack_id=current_pack.rule_pack_id,
            risk_bindings=[
                RuleRiskBinding(
                    risk_instance_id="risk-001",
                    project_id=version.project_id,
                    rule_key=previous_rule.rule_key,
                    evaluated_rule_revision_id=previous_rule.rule_revision_id,
                )
            ],
        )
        assert len(tasks) == 1

        with sqlite3.connect(path) as connection:
            reason_hash = connection.execute(
                "SELECT reason_sha256 FROM monitoring_rule_re_review_tasks "
                "WHERE task_id = ?",
                (tasks[0].task_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE monitoring_rule_re_review_tasks SET reason_sha256 = ? "
                "WHERE task_id = ?",
                (reason_hash.upper(), tasks[0].task_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted re-review task reason hash is not canonical",
        ):
            repository.list_re_review_tasks(version.project_id)

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_re_review_tasks SET reason_sha256 = ?, reason = ? "
                "WHERE task_id = ?",
                (
                    reason_hash,
                    "语义有效但被篡改的复核理由。",
                    tasks[0].task_id,
                ),
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="persisted re-review task reason hash mismatch",
        ):
            repository.list_re_review_tasks(version.project_id)


def test_persisted_re_review_task_status_round_trips_as_mutable_state() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        version = repository.register_protocol_version(
            _version("proj_re_review_status", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        previous_rule = _rule(version, fact, trigger_value="漏服")
        current_rule = _rule(version, fact, trigger_value="多服")
        lifecycle = MonitoringRuleLifecycleService(repository)
        previous_pack = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[replace(previous_rule, status="candidate")],
            created_by="rule_author",
        )
        current_pack = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[replace(current_rule, status="candidate")],
            created_by="rule_author",
        )
        tasks = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=lambda _binding: True,
        ).schedule_re_reviews(
            previous_rule_pack_id=previous_pack.rule_pack_id,
            current_rule_pack_id=current_pack.rule_pack_id,
            risk_bindings=[
                RuleRiskBinding(
                    risk_instance_id="risk-001",
                    project_id=version.project_id,
                    rule_key=previous_rule.rule_key,
                    evaluated_rule_revision_id=previous_rule.rule_revision_id,
                )
            ],
        )
        assert tasks[0].status == "open"

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_rule_re_review_tasks SET status = ? "
                "WHERE task_id = ?",
                ("completed", tasks[0].task_id),
            )

        restored = repository.list_re_review_tasks(version.project_id)
        assert restored[0].task_id == tasks[0].task_id
        assert restored[0].status == "completed"


def test_existing_re_review_schema_is_migrated_and_reason_hash_backfilled() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "rules.sqlite3"
        repository = MonitoringProtocolRuleRepository(path)
        task = RuleReReviewTask.create(
            binding=RuleRiskBinding(
                risk_instance_id="risk-legacy",
                project_id="proj_re_review_migration",
                rule_key="study_treatment.adherence.migration",
                evaluated_rule_revision_id="rule-revision-previous",
            ),
            current_rule_revision_id="rule-revision-current",
            reason="迁移后仍需保留理由完整性。",
        )
        repository.store_re_review_tasks([task])

        with sqlite3.connect(path) as connection:
            connection.execute(
                "ALTER TABLE monitoring_rule_re_review_tasks "
                "DROP COLUMN reason_sha256"
            )

        restarted = MonitoringProtocolRuleRepository(path)
        restored = restarted.list_re_review_tasks(task.project_id)
        assert restored == (task,)
        with sqlite3.connect(path) as connection:
            reason_sha256 = connection.execute(
                "SELECT reason_sha256 FROM monitoring_rule_re_review_tasks "
                "WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()[0]
        assert len(reason_sha256) == 64


def _site_version(project_id: str, label: str, digest: str) -> ProtocolSourceVersion:
    return ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code=f"{project_id}-PROTOCOL",
        version_label=label,
        version_date="2026-01-01",
        source_entry_id=f"source-{label}",
        source_title=f"研究方案 {label}",
        content_sha256=digest * 64,
        applicability_status="site_specific",
    )


def _assignment(
    version: ProtocolSourceVersion,
    *,
    centre_id: str = "001",
    subject_id: str = "",
    effective_from: str = "2026-01-01",
    effective_to: str = "2026-01-31",
) -> ProtocolApplicabilityAssignment:
    return ProtocolApplicabilityAssignment.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        centre_id=centre_id,
        subject_id=subject_id,
        operational_effective_from=effective_from,
        operational_effective_to=effective_to,
        evidence_text="中心确认该方案版本在所列日期区间内投入实际执行。",
        evidence_source_content_sha256=version.content_sha256,
        evidence_source_entry_id=f"evidence-{version.version_label}",
        evidence_locator=f"approval:centre:{centre_id}:{subject_id or 'all'}",
        created_by="medical_manager",
    )


def test_site_applicability_resolution_is_exact_cas_guarded_and_fail_closed(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version_1 = repository.register_protocol_version(
        _site_version("proj_alpha", "V1.0", "a")
    )
    version_2 = repository.register_protocol_version(
        _site_version("proj_alpha", "V2.0", "b")
    )
    centre_v1 = repository.create_applicability_assignment(
        _assignment(version_1)
    )
    centre_v2 = repository.create_applicability_assignment(
        _assignment(
            version_2,
            effective_from="2026-02-01",
            effective_to="2026-12-31",
        )
    )
    subject_v2 = repository.create_applicability_assignment(
        _assignment(
            version_2,
            subject_id="0007",
            effective_from="2026-01-15",
            effective_to="2026-01-20",
        )
    )
    for assignment in (centre_v1, centre_v2, subject_v2):
        repository.transition_applicability_assignment(
            "proj_alpha",
            assignment.assignment_id,
            expected_state_version=1,
            status="confirmed",
            actor="medical_manager",
        )

    subject = repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        subject_id="0007",
        event_date="2026-01-16",
    )
    assert subject.resolved is True
    assert subject.protocol_version_id == version_2.protocol_version_id
    assert subject.assignment is not None
    assert subject.assignment.subject_id == "0007"
    centre = repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        subject_id="0008",
        event_date="2026-01-16",
    )
    assert centre.protocol_version_id == version_1.protocol_version_id
    assert repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="1",
        subject_id="0007",
        event_date="2026-01-16",
    ).diagnostic_code == "monitoring_protocol_applicability_unresolved"
    assert repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        subject_id="7",
        event_date="2026-01-16",
    ).protocol_version_id == version_1.protocol_version_id

    retired = repository.transition_applicability_assignment(
        "proj_alpha",
        subject_v2.assignment_id,
        expected_state_version=2,
        status="retired",
        actor="medical_manager",
    )
    assert retired.state_version == 3
    after_retirement = repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        subject_id="0007",
        event_date="2026-01-16",
    )
    assert after_retirement.protocol_version_id == version_1.protocol_version_id
    with pytest.raises(MonitoringProtocolStateConflictError, match="current 3"):
        repository.transition_applicability_assignment(
            "proj_alpha",
            subject_v2.assignment_id,
            expected_state_version=2,
            status="retired",
            actor="medical_manager",
        )
    with pytest.raises(MonitoringProtocolRecordNotFound):
        repository.applicability_assignment(
            "proj_other",
            centre_v1.assignment_id,
        )


def test_site_assignment_overlap_and_unconfirmed_inputs_never_resolve(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version_1 = repository.register_protocol_version(
        _site_version("proj_alpha", "V1.0", "a")
    )
    version_2 = repository.register_protocol_version(
        _site_version("proj_alpha", "V2.0", "b")
    )
    confirmed = repository.create_applicability_assignment(
        _assignment(version_1)
    )
    repository.transition_applicability_assignment(
        "proj_alpha",
        confirmed.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    overlapping = repository.create_applicability_assignment(
        _assignment(
            version_2,
            effective_from="2026-01-31",
            effective_to="2026-02-10",
        )
    )
    with pytest.raises(ProtocolApplicabilityConflictError, match="overlap"):
        repository.transition_applicability_assignment(
            "proj_alpha",
            overlapping.assignment_id,
            expected_state_version=1,
            status="confirmed",
            actor="medical_manager",
        )
    assert repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        event_date="2026-02-05",
    ).diagnostic_code == "monitoring_protocol_applicability_unresolved"
    invalid = repository.resolve_protocol_applicability(
        "proj_alpha",
        centre_id="001",
        event_date="protocol-V2-2026",
    )
    assert invalid.diagnostic_code == "monitoring_protocol_applicability_input_invalid"
    assert "fallback" in invalid.diagnostic_message


def test_site_specific_publication_requires_confirmed_assignment(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = repository.register_protocol_version(
        _site_version("proj_alpha", "V1.0", "a")
    )
    fact = repository.store_fact(_fact(version))
    rule = _rule(version, fact)
    candidate = repository.create_applicability_assignment(_assignment(version))

    with pytest.raises(
        RulePackPublicationError,
        match="confirmed applicability evidence",
    ):
        _publish_pack(repository, version, [rule])

    repository.transition_applicability_assignment(
        "proj_alpha",
        candidate.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    confirmed_pack = next(
        pack
        for pack in repository.list_rule_packs("proj_alpha")
        if pack.status == "confirmed"
    )
    published = MonitoringRuleLifecycleService(repository).publish(
        confirmed_pack.rule_pack_id,
        published_by="medical_manager",
    )
    assert published.status == "published"
    resolved_pack, resolved_rules = repository.published_pack_for_protocol_version(
        version.project_id,
        version.protocol_version_id,
    )
    assert resolved_pack.rule_pack_id == published.rule_pack_id
    assert resolved_pack.content_sha256 == published.content_sha256
    assert resolved_rules[0].status == "enabled"


def test_protocol_version_pack_lookup_closes_on_absent_or_multiple_published_packs(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = repository.register_protocol_version(
        _site_version("proj_alpha", "V1.0", "a")
    )
    unbound_version = repository.register_protocol_version(
        _site_version("proj_alpha", "V2.0", "b")
    )
    assignment = repository.create_applicability_assignment(_assignment(version))
    repository.transition_applicability_assignment(
        version.project_id,
        assignment.assignment_id,
        expected_state_version=1,
        status="confirmed",
        actor="medical_manager",
    )
    fact = repository.store_fact(_fact(version))
    first = _publish_pack(repository, version, [_rule(version, fact)])

    with pytest.raises(
        ProtocolApplicabilityUnresolvedError,
        match="no complete published rule pack",
    ):
        repository.published_pack_for_protocol_version(
            unbound_version.project_id,
            unbound_version.protocol_version_id,
        )

    second = _publish_pack(
        repository,
        version,
        [_rule(version, fact, trigger_value="多服")],
        clock="2026-02-15T00:00:00+00:00",
    )
    assert first.rule_pack_id != second.rule_pack_id
    with pytest.raises(
        ProtocolApplicabilityConflictError,
        match="multiple published rule packs",
    ):
        repository.published_pack_for_protocol_version(
            version.project_id,
            version.protocol_version_id,
        )
