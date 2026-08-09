from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Sequence

from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackRevisionConflictError,
)
from .monitoring_protocol_rules import (
    MonitoringRuleDefinition,
    MonitoringRulePack,
)


class MonitoringRuleLifecycleService:
    """Strict medical-monitoring rule confirmation and release workflow."""

    def __init__(
        self,
        repository: MonitoringProtocolRuleRepository,
        *,
        clock: Callable[[], datetime | str] | None = None,
    ):
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_draft_from_confirmed_facts(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        rules: Sequence[MonitoringRuleDefinition],
        created_by: str,
        retrospective_policy: str = "open_risks_only",
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        version = self.repository.protocol_version(protocol_version_id)
        prospective_revision = self.repository.next_pack_revision(project_id)
        pack = MonitoringRulePack.create(
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            pack_revision=prospective_revision,
            status="draft",
            applicability_status=version.applicability_status,
            rules=rules,
            created_by=created_by,
            retrospective_policy=retrospective_policy,
        )
        latest = self.repository.latest_rule_pack(project_id)
        if (
            latest is not None
            and latest.status == "draft"
            and latest.content_sha256 == pack.content_sha256
            and latest.retrospective_policy == pack.retrospective_policy
            and latest.protocol_version_id == pack.protocol_version_id
            and latest.applicability_status == pack.applicability_status
        ):
            if expected_pack_revision is not None and int(
                expected_pack_revision
            ) != latest.pack_revision:
                raise RulePackRevisionConflictError(
                    f"expected pack revision {expected_pack_revision} but the "
                    f"identical draft already exists at revision "
                    f"{latest.pack_revision}"
                )
            return latest
        if expected_pack_revision is not None and int(
            expected_pack_revision
        ) != prospective_revision:
            raise RulePackRevisionConflictError(
                f"expected pack revision {expected_pack_revision} but the "
                f"next project pack revision is {prospective_revision}"
            )
        return self.repository.store_rule_pack(pack, rules)

    def create_draft(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        rules: Sequence[MonitoringRuleDefinition],
        created_by: str,
        retrospective_policy: str = "open_risks_only",
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        return self.create_draft_from_confirmed_facts(
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            rules=rules,
            created_by=created_by,
            retrospective_policy=retrospective_policy,
            expected_pack_revision=expected_pack_revision,
        )

    def confirm_rule(
        self,
        rule_revision_id: str,
        *,
        expected_state_version: int,
        confirmed_by: str,
    ) -> MonitoringRuleDefinition:
        return self.repository.transition_rule_status(
            rule_revision_id,
            expected_state_version=expected_state_version,
            status="confirmed",
            actor=confirmed_by,
        )

    def start_shadow(
        self,
        draft_rule_pack_id: str,
        *,
        started_by: str,
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        return self.repository.advance_rule_pack_stage(
            draft_rule_pack_id,
            target_status="shadow",
            actor=started_by,
            transition_at=self._now_text(),
            expected_pack_revision=expected_pack_revision,
        )

    def confirm_shadow(
        self,
        shadow_rule_pack_id: str,
        *,
        shadow_run_id: str,
        confirmed_by: str,
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        return self.repository.advance_rule_pack_stage(
            shadow_rule_pack_id,
            target_status="confirmed",
            actor=confirmed_by,
            shadow_run_id=shadow_run_id,
            transition_at=self._now_text(),
            expected_pack_revision=expected_pack_revision,
        )

    def publish(
        self,
        confirmed_rule_pack_id: str,
        *,
        published_by: str,
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        return self.repository.advance_rule_pack_stage(
            confirmed_rule_pack_id,
            target_status="published",
            actor=published_by,
            transition_at=self._now_text(),
            expected_pack_revision=expected_pack_revision,
        )

    def _now_text(self) -> str:
        value = self._clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        text = str(value or "").strip()
        datetime.fromisoformat(text)
        return text
