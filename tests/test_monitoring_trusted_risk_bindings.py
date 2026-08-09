from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
    TrustedRiskBindingConflictError,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import RuleRiskBinding
from tests.test_monitoring_protocol_rules import _fact, _rule, _version


def _repository_with_rule(path: Path):
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
    MonitoringRuleLifecycleService(repository).create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=[replace(rule, status="candidate")],
        created_by="rule_author",
    )
    return repository, rule


def test_trusted_binding_rejects_forged_revision_and_cross_project_or_rule() -> None:
    with TemporaryDirectory() as directory:
        repository, rule = _repository_with_rule(
            Path(directory) / "rules.sqlite3"
        )
        valid = RuleRiskBinding(
            risk_instance_id="risk-001",
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            evaluated_rule_revision_id=rule.rule_revision_id,
        )

        with pytest.raises(
            MonitoringProtocolRecordNotFound,
            match="rule revision not found",
        ):
            repository.store_trusted_risk_binding(
                RuleRiskBinding(
                    risk_instance_id=valid.risk_instance_id,
                    project_id=valid.project_id,
                    rule_key=valid.rule_key,
                    evaluated_rule_revision_id="forged-rule-revision",
                )
            )

        for invalid in (
            RuleRiskBinding(
                risk_instance_id=valid.risk_instance_id,
                project_id="proj_other",
                rule_key=valid.rule_key,
                evaluated_rule_revision_id=valid.evaluated_rule_revision_id,
            ),
            RuleRiskBinding(
                risk_instance_id=valid.risk_instance_id,
                project_id=valid.project_id,
                rule_key="study_treatment.adherence.other",
                evaluated_rule_revision_id=valid.evaluated_rule_revision_id,
            ),
        ):
            with pytest.raises(
                TrustedRiskBindingConflictError,
                match="does not match",
            ):
                repository.store_trusted_risk_binding(invalid)

        assert repository.has_trusted_risk_binding(valid) is False


def test_trusted_binding_is_exact_idempotent_and_survives_restart() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "rules.sqlite3"
        repository, rule = _repository_with_rule(db_path)
        binding = RuleRiskBinding(
            risk_instance_id="risk-001",
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            evaluated_rule_revision_id=rule.rule_revision_id,
        )

        assert repository.store_trusted_risk_binding(binding) == binding
        assert repository.store_trusted_risk_binding(binding) == binding
        assert repository.has_trusted_risk_binding(binding) is True
        assert repository.has_trusted_risk_binding(
            RuleRiskBinding(
                risk_instance_id="risk-002",
                project_id=binding.project_id,
                rule_key=binding.rule_key,
                evaluated_rule_revision_id=binding.evaluated_rule_revision_id,
            )
        ) is False

        with sqlite3.connect(db_path) as connection:
            binding_count = connection.execute(
                "SELECT COUNT(*) FROM monitoring_trusted_rule_risk_bindings"
            ).fetchone()[0]
            event_count = connection.execute(
                """
                SELECT COUNT(*) FROM monitoring_protocol_rule_events
                WHERE aggregate_type = 'trusted_rule_risk_binding'
                  AND event_type = 'registered'
                """
            ).fetchone()[0]
        assert binding_count == 1
        assert event_count == 1

        restarted = MonitoringProtocolRuleRepository(db_path)
        assert restarted.has_trusted_risk_binding(binding) is True
        assert restarted.integrity_check() == "ok"


def test_existing_database_without_binding_table_is_migrated_on_restart() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "rules.sqlite3"
        repository, rule = _repository_with_rule(db_path)
        with repository._connect() as connection:
            connection.execute(
                "DROP TABLE monitoring_trusted_rule_risk_bindings"
            )

        restarted = MonitoringProtocolRuleRepository(db_path)
        binding = RuleRiskBinding(
            risk_instance_id="risk-after-migration",
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            evaluated_rule_revision_id=rule.rule_revision_id,
        )
        restarted.store_trusted_risk_binding(binding)
        assert restarted.has_trusted_risk_binding(binding) is True


def test_repository_validator_composes_with_selective_re_review_service() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(
            Path(directory) / "rules.sqlite3"
        )
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
        current_rule = _rule(version, fact, trigger_value="漏服|多服")
        current_pack = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=[replace(current_rule, status="candidate")],
            created_by="rule_author",
        )
        binding = RuleRiskBinding(
            risk_instance_id="risk-001",
            project_id=previous_rule.project_id,
            rule_key=previous_rule.rule_key,
            evaluated_rule_revision_id=previous_rule.rule_revision_id,
        )
        repository.store_trusted_risk_binding(binding)

        service = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=repository.has_trusted_risk_binding,
        )
        tasks = service.schedule_re_reviews(
            previous_rule_pack_id=previous_pack.rule_pack_id,
            current_rule_pack_id=current_pack.rule_pack_id,
            risk_bindings=[binding],
        )

        assert len(tasks) == 1
        assert tasks[0].risk_instance_id == binding.risk_instance_id
        assert (
            tasks[0].previous_rule_revision_id
            == binding.evaluated_rule_revision_id
        )
