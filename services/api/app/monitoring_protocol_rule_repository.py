from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable, Iterator, Sequence

from .monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    MonitoringRulePack,
    FACT_TYPE_CLINICAL_DOMAIN,
    INITIAL_RELEASE_RULE_FAMILIES,
    ProtocolApplicabilityAssignment,
    ProtocolApplicabilityResolution,
    ProtocolFact,
    ProtocolSourceVersion,
    RULE_FAMILY_CLINICAL_DOMAINS,
    RuleSourceReference,
    RuleDiagnosticCase,
    RuleFamilyCoverageSnapshot,
    RuleGoldSourceRowBinding,
    RuleGoldStandardCase,
    RuleRevisionCoverageSnapshot,
    RuleRiskBinding,
    RuleReReviewTask,
    RuleShadowCaseResult,
    RuleShadowDiagnosticResult,
    RuleShadowRun,
    ShadowProvisionalSample,
    ShadowProvisionalSampleSet,
    ShadowSampleMedicalConfirmation,
    diagnostic_case_set_content_sha256,
    gold_case_set_content_sha256,
    shadow_coverage_content_sha256,
    shadow_diagnostic_results_content_sha256,
    validate_predicate_expression,
    validate_rule_clinical_compatibility,
    validate_rule_field_lineage,
)


class MonitoringProtocolRuleRepositoryError(MonitoringProtocolRuleError):
    pass


class ProtocolVersionConflictError(MonitoringProtocolRuleRepositoryError):
    pass


class ProtocolApplicabilityConflictError(MonitoringProtocolRuleRepositoryError):
    pass


class ProtocolApplicabilityUnresolvedError(MonitoringProtocolRuleRepositoryError):
    pass


class RulePackRevisionConflictError(MonitoringProtocolRuleRepositoryError):
    pass


class RulePackPublicationError(MonitoringProtocolRuleRepositoryError):
    pass


class RulePackLifecycleError(RulePackPublicationError):
    pass


class MonitoringProtocolRecordNotFound(MonitoringProtocolRuleRepositoryError):
    pass


class MonitoringProtocolStateConflictError(MonitoringProtocolRuleRepositoryError):
    pass


class TrustedRiskBindingConflictError(MonitoringProtocolRuleRepositoryError):
    pass


_STRICT_LIFECYCLE_VERSION = 1
_RULE_PACK_STAGE_TRANSITIONS = {
    "draft": "shadow",
    "shadow": "confirmed",
    "confirmed": "published",
}
_RULE_PACK_IDENTITY_FIELDS = (
    "mapping_revision",
    "mapping_content_sha256",
    "capability_manifest_sha256",
    "effective_capabilities_sha256",
)
_RULE_PACK_IDENTITY_SHA256_FIELDS = (
    "mapping_content_sha256",
    "capability_manifest_sha256",
    "effective_capabilities_sha256",
)
_RULE_PACK_IDENTITY_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sqlite_bool(value: Any, field: str) -> bool:
    """Read a SQLite INTEGER boolean without accepting arbitrary truthiness."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    raise RulePackLifecycleError(f"{field} must be SQLite boolean 0 or 1")


def _assert_rules_share_complete_mapping_identity(
    rules: Sequence[MonitoringRuleDefinition],
) -> None:
    """Fail closed unless every rule carries the same complete 4-tuple.

    A confirmed rule, pack transition, or shadow path must not run on an
    empty, partial, or mixed immutable mapping identity.
    """
    for rule in rules:
        mapping_revision = str(getattr(rule, "mapping_revision", "") or "").strip()
        missing = ["mapping_revision"] if not mapping_revision else []
        if missing:
            raise RulePackLifecycleError(
                f"rule {rule.rule_key} has an incomplete immutable mapping "
                f"identity: missing {missing}"
            )
        for field in _RULE_PACK_IDENTITY_SHA256_FIELDS:
            value = getattr(rule, field, None)
            if not isinstance(value, str) or _RULE_PACK_IDENTITY_SHA256_RE.fullmatch(
                value
            ) is None:
                raise RulePackLifecycleError(
                    f"rule {rule.rule_key} has a non-canonical {field}"
                )
    for field in _RULE_PACK_IDENTITY_FIELDS:
        if field == "mapping_revision":
            values = {
                str(getattr(rule, field, "") or "").strip()
                for rule in rules
            }
        else:
            values = {getattr(rule, field, None) for rule in rules}
        if len(values) != 1:
            raise RulePackLifecycleError(
                f"rule pack rules do not share a uniform {field}"
            )


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _loads(value: str) -> Any:
    return json.loads(value)


class MonitoringProtocolRuleRepository:
    """Durable project-neutral protocol fact and monitoring rule store."""

    def __init__(
        self,
        db_path: Path,
        *,
        gold_case_authority: (
            Callable[
                [
                    RuleGoldStandardCase | RuleDiagnosticCase,
                    MonitoringRuleDefinition,
                ],
                None,
            ]
            | None
        ) = None,
    ):
        self.db_path = Path(db_path)
        self._gold_case_authority = gold_case_authority
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def bind_gold_case_authority(
        self,
        validator: Callable[
            [
                RuleGoldStandardCase | RuleDiagnosticCase,
                MonitoringRuleDefinition,
            ],
            None,
        ],
    ) -> None:
        if self._gold_case_authority is not None and self._gold_case_authority is not validator:
            raise RulePackLifecycleError(
                "gold standard case authority is already configured"
            )
        self._gold_case_authority = validator

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_versions (
                protocol_version_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                protocol_code TEXT NOT NULL,
                version_label TEXT NOT NULL,
                version_date TEXT NOT NULL,
                source_entry_id TEXT NOT NULL,
                source_title TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                applicability_status TEXT NOT NULL,
                operational_effective_from TEXT NOT NULL,
                operational_effective_to TEXT NOT NULL,
                predecessor_version_id TEXT NOT NULL,
                amendment_source_entry_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, protocol_code, version_label, version_date)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_facts (
                fact_revision_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                protocol_version_id TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                fact_type TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                normalized_payload_json TEXT NOT NULL,
                source_entry_id TEXT NOT NULL,
                source_locator TEXT NOT NULL,
                source_text TEXT NOT NULL,
                source_text_sha256 TEXT NOT NULL,
                clinical_domain TEXT NOT NULL DEFAULT '',
                applicability_json TEXT NOT NULL,
                supersedes_fact_revision_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(protocol_version_id, fact_key, fact_revision_id),
                FOREIGN KEY(protocol_version_id)
                    REFERENCES monitoring_protocol_versions(protocol_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_definitions (
                rule_revision_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                protocol_version_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_family TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                executor TEXT NOT NULL,
                required_domains_json TEXT NOT NULL,
                preconditions_json TEXT NOT NULL,
                trigger_expression_json TEXT NOT NULL,
                exclusions_json TEXT NOT NULL,
                severity TEXT NOT NULL,
                confidence TEXT NOT NULL,
                evidence_template TEXT NOT NULL,
                fact_revision_ids_json TEXT NOT NULL,
                source_entry_id TEXT NOT NULL,
                source_locator TEXT NOT NULL,
                source_text TEXT NOT NULL,
                source_text_sha256 TEXT NOT NULL,
                clinical_domain TEXT NOT NULL DEFAULT '',
                source_refs_json TEXT NOT NULL DEFAULT '[]',
                field_lineage_json TEXT NOT NULL DEFAULT '{}',
                mapping_revision TEXT NOT NULL DEFAULT '',
                mapping_content_sha256 TEXT NOT NULL DEFAULT '',
                capability_manifest_sha256 TEXT NOT NULL DEFAULT '',
                effective_capabilities_sha256 TEXT NOT NULL DEFAULT '',
                recommendation_candidate_id TEXT NOT NULL DEFAULT '',
                supersedes_rule_revision_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(protocol_version_id)
                    REFERENCES monitoring_protocol_versions(protocol_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_version_state (
                protocol_version_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                applicability_status TEXT NOT NULL,
                operational_effective_from TEXT NOT NULL,
                operational_effective_to TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(protocol_version_id)
                    REFERENCES monitoring_protocol_versions(protocol_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_applicability_assignments (
                assignment_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                protocol_version_id TEXT NOT NULL,
                centre_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                operational_effective_from TEXT NOT NULL,
                operational_effective_to TEXT NOT NULL,
                evidence_text TEXT NOT NULL,
                evidence_source_content_sha256 TEXT NOT NULL,
                evidence_source_entry_id TEXT NOT NULL,
                evidence_locator TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(protocol_version_id)
                    REFERENCES monitoring_protocol_versions(protocol_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_applicability_assignment_state (
                assignment_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(assignment_id)
                    REFERENCES monitoring_protocol_applicability_assignments(assignment_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_fact_state (
                fact_revision_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(fact_revision_id)
                    REFERENCES monitoring_protocol_facts(fact_revision_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_definition_state (
                rule_revision_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(rule_revision_id)
                    REFERENCES monitoring_rule_definitions(rule_revision_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_packs (
                rule_pack_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                protocol_version_id TEXT NOT NULL,
                pack_revision INTEGER NOT NULL,
                status TEXT NOT NULL,
                applicability_status TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                created_by TEXT NOT NULL,
                retrospective_policy TEXT NOT NULL,
                published_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, pack_revision),
                FOREIGN KEY(protocol_version_id)
                    REFERENCES monitoring_protocol_versions(protocol_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_gold_cases (
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
                coverage_labels_json TEXT NOT NULL DEFAULT '[]',
                medical_rationale TEXT NOT NULL,
                evidence_locators_json TEXT NOT NULL,
                source_row_bindings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_diagnostic_cases (
                case_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_revision_id TEXT NOT NULL,
                source_entry_id TEXT NOT NULL,
                source_content_sha256 TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                batch_revision TEXT NOT NULL,
                case_label TEXT NOT NULL,
                input_record_json TEXT NOT NULL,
                previous_record_json TEXT NOT NULL,
                related_records_json TEXT NOT NULL,
                observed_domains_json TEXT NOT NULL,
                expected_diagnostic_category TEXT NOT NULL,
                expected_diagnostic_code TEXT NOT NULL,
                medical_rationale TEXT NOT NULL,
                evidence_locators_json TEXT NOT NULL,
                source_row_bindings_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_shadow_runs (
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
                diagnostic_case_count INTEGER NOT NULL DEFAULT 0,
                diagnostic_passed_count INTEGER NOT NULL DEFAULT 0,
                diagnostic_failed_count INTEGER NOT NULL DEFAULT 0,
                diagnostic_results_json TEXT NOT NULL DEFAULT '[]',
                diagnostic_case_set_content_sha256 TEXT NOT NULL DEFAULT '',
                diagnostic_results_content_sha256 TEXT NOT NULL DEFAULT '',
                rule_coverages_json TEXT NOT NULL DEFAULT '[]',
                family_coverages_json TEXT NOT NULL DEFAULT '[]',
                coverage_content_sha256 TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(rule_pack_id, batch_id, shadow_run_id),
                FOREIGN KEY(rule_pack_id)
                    REFERENCES monitoring_rule_packs(rule_pack_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_shadow_sample_sets (
                sample_set_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_pack_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                batch_version INTEGER NOT NULL,
                batch_revision TEXT NOT NULL,
                mapping_revision TEXT NOT NULL,
                mapping_content_sha256 TEXT NOT NULL,
                capability_manifest_sha256 TEXT NOT NULL,
                effective_capabilities_sha256 TEXT NOT NULL,
                rule_revision_ids_json TEXT NOT NULL,
                samples_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(rule_pack_id)
                    REFERENCES monitoring_rule_packs(rule_pack_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_shadow_sample_confirmations (
                confirmation_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_pack_id TEXT NOT NULL,
                sample_set_id TEXT NOT NULL,
                sample_set_content_sha256 TEXT NOT NULL,
                trusted_shadow_run_id TEXT NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                FOREIGN KEY(sample_set_id)
                    REFERENCES monitoring_shadow_sample_sets(sample_set_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_sample_sets_pack
                ON monitoring_shadow_sample_sets(project_id, rule_pack_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_sample_confirmation_pack
                ON monitoring_shadow_sample_confirmations(
                    project_id, rule_pack_id
                )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_pack_items (
                rule_pack_id TEXT NOT NULL,
                rule_revision_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_status_snapshot TEXT NOT NULL DEFAULT '',
                rule_state_version_snapshot INTEGER NOT NULL DEFAULT 0,
                fact_statuses_json TEXT NOT NULL DEFAULT '{}',
                fact_state_versions_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(rule_pack_id, rule_revision_id),
                UNIQUE(rule_pack_id, rule_key),
                FOREIGN KEY(rule_pack_id)
                    REFERENCES monitoring_rule_packs(rule_pack_id),
                FOREIGN KEY(rule_revision_id)
                    REFERENCES monitoring_rule_definitions(rule_revision_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_pack_lifecycle (
                rule_pack_id TEXT PRIMARY KEY,
                lifecycle_version INTEGER NOT NULL,
                predecessor_rule_pack_id TEXT NOT NULL,
                transition_actor TEXT NOT NULL,
                transition_at TEXT NOT NULL,
                shadow_run_id TEXT NOT NULL,
                legacy_read_only INTEGER NOT NULL,
                FOREIGN KEY(rule_pack_id)
                    REFERENCES monitoring_rule_packs(rule_pack_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_rule_re_review_tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                risk_instance_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                previous_rule_revision_id TEXT NOT NULL,
                current_rule_revision_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                reason_sha256 TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(
                    project_id,
                    risk_instance_id,
                    previous_rule_revision_id,
                    current_rule_revision_id
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_trusted_rule_risk_bindings (
                project_id TEXT NOT NULL,
                risk_instance_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                evaluated_rule_revision_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    project_id,
                    risk_instance_id,
                    rule_key,
                    evaluated_rule_revision_id
                ),
                FOREIGN KEY(evaluated_rule_revision_id)
                    REFERENCES monitoring_rule_definitions(rule_revision_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_protocol_rule_events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_protocol_versions_project
                ON monitoring_protocol_versions(project_id, version_date)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_protocol_applicability_scope
                ON monitoring_protocol_applicability_assignments(
                    project_id, centre_id, subject_id,
                    operational_effective_from, operational_effective_to
                )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_protocol_applicability_version
                ON monitoring_protocol_applicability_assignments(
                    project_id, protocol_version_id
                )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_protocol_facts_version
                ON monitoring_protocol_facts(protocol_version_id, fact_key, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_definitions_version
                ON monitoring_rule_definitions(protocol_version_id, rule_key, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_packs_project
                ON monitoring_rule_packs(project_id, pack_revision, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_review_project
                ON monitoring_rule_re_review_tasks(project_id, status, rule_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trusted_rule_risk_binding
                ON monitoring_trusted_rule_risk_bindings(
                    project_id, risk_instance_id, rule_key
                )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_gold_project
                ON monitoring_rule_gold_cases(project_id, rule_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_diagnostic_project
                ON monitoring_rule_diagnostic_cases(project_id, rule_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_shadow_project
                ON monitoring_rule_shadow_runs(project_id, rule_pack_id, completed_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rule_pack_lifecycle_predecessor
                ON monitoring_rule_pack_lifecycle(predecessor_rule_pack_id)
            """,
        )
        with self._connect() as connection:
            for statement in statements:
                connection.execute(statement)
            self._ensure_column(
                connection,
                "monitoring_rule_packs",
                "retrospective_policy",
                "TEXT NOT NULL DEFAULT 'open_risks_only'",
            )
            self._ensure_column(
                connection,
                "monitoring_protocol_applicability_assignments",
                "evidence_source_content_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "monitoring_protocol_facts",
                "clinical_domain",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_definitions",
                "clinical_domain",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_definitions",
                "source_refs_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_definitions",
                "field_lineage_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            for column in (
                "mapping_revision",
                "mapping_content_sha256",
                "capability_manifest_sha256",
                "effective_capabilities_sha256",
                "recommendation_candidate_id",
            ):
                self._ensure_column(
                    connection,
                    "monitoring_rule_definitions",
                    column,
                    "TEXT NOT NULL DEFAULT ''",
                )
            for column, definition in (
                ("rule_revision_id", "TEXT NOT NULL DEFAULT ''"),
                ("source_entry_id", "TEXT NOT NULL DEFAULT ''"),
                ("source_content_sha256", "TEXT NOT NULL DEFAULT ''"),
                ("source_revision", "TEXT NOT NULL DEFAULT ''"),
                ("batch_revision", "TEXT NOT NULL DEFAULT ''"),
                ("source_row_bindings_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("coverage_labels_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                self._ensure_column(
                    connection,
                    "monitoring_rule_gold_cases",
                    column,
                    definition,
                )
            self._ensure_column(
                connection,
                "monitoring_rule_shadow_runs",
                "case_set_content_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_re_review_tasks",
                "reason_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            legacy_re_review_rows = connection.execute(
                """
                SELECT task_id, reason
                FROM monitoring_rule_re_review_tasks
                WHERE reason_sha256 = ''
                """
            ).fetchall()
            for legacy_re_review_row in legacy_re_review_rows:
                connection.execute(
                    """
                    UPDATE monitoring_rule_re_review_tasks
                    SET reason_sha256 = ?
                    WHERE task_id = ?
                    """,
                    (
                        sha256(
                            str(legacy_re_review_row["reason"] or "")
                            .encode("utf-8")
                        ).hexdigest(),
                        legacy_re_review_row["task_id"],
                    ),
                )
            for column, definition in (
                ("diagnostic_case_count", "INTEGER NOT NULL DEFAULT 0"),
                ("diagnostic_passed_count", "INTEGER NOT NULL DEFAULT 0"),
                ("diagnostic_failed_count", "INTEGER NOT NULL DEFAULT 0"),
                ("diagnostic_results_json", "TEXT NOT NULL DEFAULT '[]'"),
                (
                    "diagnostic_case_set_content_sha256",
                    "TEXT NOT NULL DEFAULT ''",
                ),
                (
                    "diagnostic_results_content_sha256",
                    "TEXT NOT NULL DEFAULT ''",
                ),
                ("rule_coverages_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("family_coverages_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("coverage_content_sha256", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(
                    connection,
                    "monitoring_rule_shadow_runs",
                    column,
                    definition,
                )
            self._ensure_column(
                connection,
                "monitoring_rule_pack_items",
                "rule_status_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_pack_items",
                "rule_state_version_snapshot",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_pack_items",
                "fact_statuses_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "monitoring_rule_pack_items",
                "fact_state_versions_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            now = _utc_now_text()
            connection.execute(
                """
                INSERT OR IGNORE INTO monitoring_protocol_version_state (
                    protocol_version_id, status, applicability_status,
                    operational_effective_from, operational_effective_to,
                    state_version, updated_at
                )
                SELECT protocol_version_id, status, applicability_status,
                       operational_effective_from, operational_effective_to, 1, ?
                FROM monitoring_protocol_versions
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO monitoring_protocol_fact_state (
                    fact_revision_id, status, state_version, updated_at
                )
                SELECT fact_revision_id, status, 1, ?
                FROM monitoring_protocol_facts
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO monitoring_rule_definition_state (
                    rule_revision_id, status, state_version, updated_at
                )
                SELECT rule_revision_id, status, 1, ?
                FROM monitoring_rule_definitions
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO monitoring_rule_pack_lifecycle (
                    rule_pack_id, lifecycle_version, predecessor_rule_pack_id,
                    transition_actor, transition_at, shadow_run_id,
                    legacy_read_only
                )
                SELECT rule_pack_id, 0, '', 'legacy_migration',
                       created_at, '', 1
                FROM monitoring_rule_packs
                """,
            )

    def register_protocol_version(
        self,
        version: ProtocolSourceVersion,
    ) -> ProtocolSourceVersion:
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE project_id = ? AND protocol_code = ?
                  AND version_label = ? AND version_date = ?
                """,
                (
                    version.project_id,
                    version.protocol_code,
                    version.version_label,
                    version.version_date,
                ),
            ).fetchone()
            if existing is not None:
                restored = self._protocol_version_from_row(existing)
                if self._protocol_version_immutable(restored) != self._protocol_version_immutable(version):
                    raise ProtocolVersionConflictError(
                        "same protocol version label/date has different content or metadata"
                    )
                return self._protocol_version_with_state(connection, existing)
            if version.predecessor_version_id:
                predecessor = connection.execute(
                    """
                    SELECT project_id FROM monitoring_protocol_versions
                    WHERE protocol_version_id = ?
                    """,
                    (version.predecessor_version_id,),
                ).fetchone()
                if predecessor is None:
                    raise MonitoringProtocolRecordNotFound(
                        "predecessor protocol version not found"
                    )
                if predecessor["project_id"] != version.project_id:
                    raise ProtocolVersionConflictError(
                        "predecessor protocol version belongs to another project"
                    )
            self._assert_applicability_does_not_overlap(connection, version)
            now = _utc_now_text()
            connection.execute(
                """
                INSERT INTO monitoring_protocol_versions (
                    protocol_version_id, project_id, protocol_code,
                    version_label, version_date, source_entry_id, source_title,
                    content_sha256, status, applicability_status,
                    operational_effective_from, operational_effective_to,
                    predecessor_version_id, amendment_source_entry_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.protocol_version_id,
                    version.project_id,
                    version.protocol_code,
                    version.version_label,
                    version.version_date,
                    version.source_entry_id,
                    version.source_title,
                    version.content_sha256,
                    version.status,
                    version.applicability_status,
                    version.operational_effective_from,
                    version.operational_effective_to,
                    version.predecessor_version_id,
                    version.amendment_source_entry_id,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_protocol_version_state (
                    protocol_version_id, status, applicability_status,
                    operational_effective_from, operational_effective_to,
                    state_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    version.protocol_version_id,
                    version.status,
                    version.applicability_status,
                    version.operational_effective_from,
                    version.operational_effective_to,
                    now,
                ),
            )
            self._event(
                connection,
                version.project_id,
                "protocol_version",
                version.protocol_version_id,
                "registered",
                version.public_dict(),
            )
        return version

    def protocol_version(self, protocol_version_id: str) -> ProtocolSourceVersion:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE protocol_version_id = ?
                """,
                (protocol_version_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            return self._protocol_version_with_state(connection, row)

    def list_protocol_versions(self, project_id: str) -> tuple[ProtocolSourceVersion, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE project_id = ?
                ORDER BY version_date, protocol_version_id
                """,
                (project_id,),
            ).fetchall()
            return tuple(
                self._protocol_version_with_state(connection, row) for row in rows
            )

    def create_applicability_assignment(
        self,
        assignment: ProtocolApplicabilityAssignment,
    ) -> ProtocolApplicabilityAssignment:
        with self._transaction() as connection:
            version_row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE protocol_version_id = ?
                """,
                (assignment.protocol_version_id,),
            ).fetchone()
            if version_row is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            version = self._protocol_version_with_state(connection, version_row)
            if version.project_id != assignment.project_id:
                raise ProtocolVersionConflictError(
                    "applicability assignment protocol version belongs to another project"
                )
            if version.applicability_status != "site_specific":
                raise ProtocolApplicabilityConflictError(
                    "applicability assignments require a site_specific protocol version"
                )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_protocol_applicability_assignments
                WHERE assignment_id = ?
                """,
                (assignment.assignment_id,),
            ).fetchone()
            if existing is not None:
                return self._applicability_assignment_with_state(connection, existing)
            now = _utc_now_text()
            connection.execute(
                """
                INSERT INTO monitoring_protocol_applicability_assignments (
                    assignment_id, project_id, protocol_version_id,
                    centre_id, subject_id, operational_effective_from,
                    operational_effective_to, evidence_text,
                    evidence_source_content_sha256,
                    evidence_source_entry_id, evidence_locator,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment.assignment_id,
                    assignment.project_id,
                    assignment.protocol_version_id,
                    assignment.centre_id,
                    assignment.subject_id,
                    assignment.operational_effective_from,
                    assignment.operational_effective_to,
                    assignment.evidence_text,
                    assignment.evidence_source_content_sha256,
                    assignment.evidence_source_entry_id,
                    assignment.evidence_locator,
                    assignment.created_by,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_protocol_applicability_assignment_state (
                    assignment_id, status, state_version, updated_by, updated_at
                ) VALUES (?, 'candidate', 1, ?, ?)
                """,
                (assignment.assignment_id, assignment.created_by, now),
            )
            self._event(
                connection,
                assignment.project_id,
                "protocol_applicability_assignment",
                assignment.assignment_id,
                "created",
                assignment.public_dict(),
            )
        return assignment

    def list_applicability_assignments(
        self,
        project_id: str,
        *,
        protocol_version_id: str = "",
    ) -> tuple[ProtocolApplicabilityAssignment, ...]:
        parameters: list[Any] = [str(project_id)]
        where = "WHERE project_id = ?"
        if protocol_version_id:
            where += " AND protocol_version_id = ?"
            parameters.append(str(protocol_version_id))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM monitoring_protocol_applicability_assignments
                {where}
                ORDER BY centre_id, subject_id, operational_effective_from,
                         assignment_id
                """,
                parameters,
            ).fetchall()
            return tuple(
                self._applicability_assignment_with_state(connection, row)
                for row in rows
            )

    def applicability_assignment(
        self,
        project_id: str,
        assignment_id: str,
    ) -> ProtocolApplicabilityAssignment:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_applicability_assignments
                WHERE project_id = ? AND assignment_id = ?
                """,
                (project_id, assignment_id),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound(
                    "protocol applicability assignment not found"
                )
            return self._applicability_assignment_with_state(connection, row)

    def transition_applicability_assignment(
        self,
        project_id: str,
        assignment_id: str,
        *,
        expected_state_version: int,
        status: str,
        actor: str,
    ) -> ProtocolApplicabilityAssignment:
        target = str(status or "").strip().lower()
        normalized_actor = str(actor or "").strip()
        if not normalized_actor:
            raise MonitoringProtocolStateConflictError(
                "applicability assignment transition actor is required"
            )
        allowed = {
            "candidate": {"confirmed"},
            "confirmed": {"retired"},
            "retired": set(),
        }
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_applicability_assignments
                WHERE project_id = ? AND assignment_id = ?
                """,
                (project_id, assignment_id),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound(
                    "protocol applicability assignment not found"
                )
            current = self._applicability_assignment_with_state(connection, row)
            if current.state_version != int(expected_state_version):
                raise MonitoringProtocolStateConflictError(
                    "protocol applicability assignment state expected "
                    f"{expected_state_version}, current {current.state_version}"
                )
            if target not in allowed[current.status]:
                raise MonitoringProtocolStateConflictError(
                    "invalid protocol applicability assignment transition: "
                    f"{current.status} -> {target}"
                )
            if target == "confirmed":
                version_row = connection.execute(
                    """
                    SELECT * FROM monitoring_protocol_versions
                    WHERE protocol_version_id = ?
                    """,
                    (current.protocol_version_id,),
                ).fetchone()
                version = self._protocol_version_with_state(connection, version_row)
                if (
                    version.status != "confirmed"
                    or version.applicability_status != "site_specific"
                ):
                    raise ProtocolApplicabilityConflictError(
                        "confirmed assignment requires a confirmed site_specific protocol version"
                    )
                self._assert_assignment_does_not_overlap(
                    connection,
                    current,
                    exclude_assignment_id=current.assignment_id,
                )
            updated = connection.execute(
                """
                UPDATE monitoring_protocol_applicability_assignment_state
                SET status = ?, state_version = state_version + 1,
                    updated_by = ?, updated_at = ?
                WHERE assignment_id = ? AND state_version = ?
                """,
                (
                    target,
                    normalized_actor,
                    _utc_now_text(),
                    assignment_id,
                    expected_state_version,
                ),
            )
            if updated.rowcount != 1:
                raise MonitoringProtocolStateConflictError(
                    "protocol applicability assignment changed concurrently"
                )
            transitioned = replace(
                current,
                status=target,
                state_version=current.state_version + 1,
            )
            self._event(
                connection,
                current.project_id,
                "protocol_applicability_assignment_state",
                current.assignment_id,
                "transitioned",
                {
                    "from_status": current.status,
                    "to_status": target,
                    "from_state_version": current.state_version,
                    "to_state_version": transitioned.state_version,
                    "actor": normalized_actor,
                },
            )
            return transitioned

    def resolve_protocol_applicability(
        self,
        project_id: str,
        *,
        centre_id: str,
        subject_id: str = "",
        event_date: str,
    ) -> ProtocolApplicabilityResolution:
        project = str(project_id or "").strip()
        centre = str(centre_id or "").strip()
        subject = str(subject_id or "").strip()
        event = str(event_date or "").strip()
        if not project or not centre or not event:
            return ProtocolApplicabilityResolution(
                resolved=False,
                diagnostic_code="monitoring_protocol_applicability_input_invalid",
                diagnostic_message=(
                    "project_id, centre_id and event_date are required; "
                    "no fallback date or identifier is permitted"
                ),
                project_id=project,
                centre_id=centre,
                subject_id=subject,
                event_date=event,
            )
        try:
            event = date.fromisoformat(event).isoformat()
        except ValueError:
            return ProtocolApplicabilityResolution(
                resolved=False,
                diagnostic_code="monitoring_protocol_applicability_input_invalid",
                diagnostic_message=(
                    "event_date must be an ISO date; no fallback date is permitted"
                ),
                project_id=project,
                centre_id=centre,
                subject_id=subject,
                event_date=event,
            )
        with self._connect() as connection:
            scopes = (subject, "") if subject else ("",)
            for scoped_subject in scopes:
                rows = connection.execute(
                    """
                    SELECT a.*
                    FROM monitoring_protocol_applicability_assignments a
                    JOIN monitoring_protocol_applicability_assignment_state s
                      ON s.assignment_id = a.assignment_id
                    JOIN monitoring_protocol_version_state vs
                      ON vs.protocol_version_id = a.protocol_version_id
                    WHERE a.project_id = ?
                      AND a.centre_id = ?
                      AND a.subject_id = ?
                      AND s.status = 'confirmed'
                      AND vs.status = 'confirmed'
                      AND vs.applicability_status = 'site_specific'
                      AND a.operational_effective_from <= ?
                      AND a.operational_effective_to >= ?
                    ORDER BY a.assignment_id
                    """,
                    (project, centre, scoped_subject, event, event),
                ).fetchall()
                if len(rows) > 1:
                    return ProtocolApplicabilityResolution(
                        resolved=False,
                        diagnostic_code="monitoring_protocol_applicability_conflict",
                        diagnostic_message=(
                            "multiple confirmed protocol applicability assignments "
                            "match the exact scope and event date"
                        ),
                        project_id=project,
                        centre_id=centre,
                        subject_id=subject,
                        event_date=event,
                    )
                if len(rows) == 1:
                    assignment = self._applicability_assignment_with_state(
                        connection, rows[0]
                    )
                    return ProtocolApplicabilityResolution(
                        resolved=True,
                        diagnostic_code="monitoring_protocol_applicability_resolved",
                        diagnostic_message=(
                            "confirmed subject assignment selected"
                            if scoped_subject
                            else "confirmed centre assignment selected"
                        ),
                        project_id=project,
                        centre_id=centre,
                        subject_id=subject,
                        event_date=event,
                        protocol_version_id=assignment.protocol_version_id,
                        assignment=assignment,
                    )
        return ProtocolApplicabilityResolution(
            resolved=False,
            diagnostic_code="monitoring_protocol_applicability_unresolved",
            diagnostic_message=(
                "no confirmed exact-scope assignment covers the event date; "
                "protocol date, ethics date, training date, first observed use "
                "and file name are not fallback evidence"
            ),
            project_id=project,
            centre_id=centre,
            subject_id=subject,
            event_date=event,
        )

    def store_fact(self, fact: ProtocolFact) -> ProtocolFact:
        with self._transaction() as connection:
            version = connection.execute(
                """
                SELECT project_id FROM monitoring_protocol_versions
                WHERE protocol_version_id = ?
                """,
                (fact.protocol_version_id,),
            ).fetchone()
            if version is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            if version["project_id"] != fact.project_id:
                raise ProtocolVersionConflictError(
                    "protocol fact belongs to another project"
                )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_protocol_facts
                WHERE fact_revision_id = ?
                """,
                (fact.fact_revision_id,),
            ).fetchone()
            if existing is not None:
                restored = self._fact_from_row(existing)
                if self._fact_immutable(restored) != self._fact_immutable(fact):
                    raise ProtocolVersionConflictError(
                        "fact revision identity has conflicting content"
                    )
                return self._fact_with_state(connection, existing)
            if fact.state_version != 1:
                raise MonitoringProtocolStateConflictError(
                    "new fact revisions must start at state_version 1"
                )
            if fact.supersedes_fact_revision_id:
                predecessor = connection.execute(
                    """
                    SELECT project_id, fact_key
                    FROM monitoring_protocol_facts
                    WHERE fact_revision_id = ?
                    """,
                    (fact.supersedes_fact_revision_id,),
                ).fetchone()
                if (
                    predecessor is None
                    or predecessor["project_id"] != fact.project_id
                    or predecessor["fact_key"] != fact.fact_key
                ):
                    raise ProtocolVersionConflictError(
                        "superseded fact revision must exist in the same project "
                        "and fact_key lineage"
                    )
            connection.execute(
                """
                INSERT INTO monitoring_protocol_facts (
                    fact_revision_id, project_id, protocol_version_id,
                    fact_key, fact_type, status, title,
                    normalized_payload_json, source_entry_id, source_locator,
                    source_text, source_text_sha256, applicability_json,
                    clinical_domain, supersedes_fact_revision_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_revision_id,
                    fact.project_id,
                    fact.protocol_version_id,
                    fact.fact_key,
                    fact.fact_type,
                    fact.status,
                    fact.title,
                    _json(fact.normalized_payload),
                    fact.source_entry_id,
                    fact.source_locator,
                    fact.source_text,
                    fact.source_text_sha256,
                    _json(fact.applicability),
                    fact.clinical_domain,
                    fact.supersedes_fact_revision_id,
                    _utc_now_text(),
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_protocol_fact_state (
                    fact_revision_id, status, state_version, updated_at
                ) VALUES (?, ?, 1, ?)
                """,
                (fact.fact_revision_id, fact.status, _utc_now_text()),
            )
            self._event(
                connection,
                fact.project_id,
                "protocol_fact",
                fact.fact_revision_id,
                "stored",
                fact.public_dict(),
            )
        return fact

    def facts_for_version(
        self,
        protocol_version_id: str,
        *,
        statuses: Iterable[str] = (),
    ) -> tuple[ProtocolFact, ...]:
        status_values = tuple(sorted({str(item).strip() for item in statuses if str(item).strip()}))
        query = """
            SELECT f.* FROM monitoring_protocol_facts f
            JOIN monitoring_protocol_fact_state s
              ON s.fact_revision_id = f.fact_revision_id
            WHERE f.protocol_version_id = ?
        """
        parameters: list[Any] = [protocol_version_id]
        if status_values:
            query += f" AND s.status IN ({','.join('?' for _ in status_values)})"
            parameters.extend(status_values)
        query += " ORDER BY fact_type, fact_key, fact_revision_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return tuple(self._fact_with_state(connection, row) for row in rows)

    def transition_protocol_version_state(
        self,
        protocol_version_id: str,
        *,
        expected_state_version: int,
        status: str,
        applicability_status: str,
        operational_effective_from: str = "",
        operational_effective_to: str = "",
    ) -> ProtocolSourceVersion:
        candidate_status = str(status or "").strip().lower()
        candidate_applicability = str(applicability_status or "").strip().lower()
        allowed_status_transitions = {
            "draft": {"confirmed", "superseded"},
            "confirmed": {"confirmed", "superseded"},
            "superseded": {"superseded"},
        }
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM monitoring_protocol_versions WHERE protocol_version_id = ?",
                (protocol_version_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            current = self._protocol_version_with_state(connection, row)
            if current.state_version != int(expected_state_version):
                raise MonitoringProtocolStateConflictError(
                    f"protocol version state expected {expected_state_version}, current {current.state_version}"
                )
            if candidate_status not in allowed_status_transitions.get(current.status, set()):
                raise MonitoringProtocolStateConflictError(
                    f"invalid protocol version status transition: {current.status} -> {candidate_status}"
                )
            candidate = ProtocolSourceVersion(
                **{
                    **asdict(current),
                    "status": candidate_status,
                    "applicability_status": candidate_applicability,
                    "operational_effective_from": operational_effective_from,
                    "operational_effective_to": operational_effective_to,
                    "state_version": current.state_version + 1,
                }
            )
            self._validate_protocol_state(candidate)
            self._assert_applicability_does_not_overlap(
                connection, candidate, exclude_protocol_version_id=protocol_version_id
            )
            updated = connection.execute(
                """
                UPDATE monitoring_protocol_version_state
                SET status = ?, applicability_status = ?,
                    operational_effective_from = ?, operational_effective_to = ?,
                    state_version = state_version + 1, updated_at = ?
                WHERE protocol_version_id = ? AND state_version = ?
                """,
                (
                    candidate.status,
                    candidate.applicability_status,
                    candidate.operational_effective_from,
                    candidate.operational_effective_to,
                    _utc_now_text(),
                    protocol_version_id,
                    expected_state_version,
                ),
            )
            if updated.rowcount != 1:
                raise MonitoringProtocolStateConflictError(
                    "protocol version state changed concurrently"
                )
            self._event(
                connection,
                current.project_id,
                "protocol_version_state",
                protocol_version_id,
                "transitioned",
                {
                    "from": self._protocol_state_payload(current),
                    "to": self._protocol_state_payload(candidate),
                    "expected_state_version": expected_state_version,
                },
            )
            return candidate

    def transition_fact_status(
        self,
        fact_revision_id: str,
        *,
        expected_state_version: int,
        status: str,
        actor: str = "",
    ) -> ProtocolFact:
        allowed = {
            "ai_candidate": {"medically_confirmed", "missing_source", "superseded"},
            "missing_source": {"ai_candidate", "superseded"},
            "medically_confirmed": {"medically_confirmed", "superseded"},
            "superseded": {"superseded"},
        }
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM monitoring_protocol_facts WHERE fact_revision_id = ?",
                (fact_revision_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound("protocol fact not found")
            current = self._fact_with_state(connection, row)
            next_status = str(status or "").strip().lower()
            if current.state_version != int(expected_state_version):
                raise MonitoringProtocolStateConflictError(
                    f"protocol fact state expected {expected_state_version}, current {current.state_version}"
                )
            if next_status not in allowed.get(current.status, set()):
                raise MonitoringProtocolStateConflictError(
                    f"invalid protocol fact status transition: {current.status} -> {next_status}"
                )
            normalized_actor = str(actor or "").strip()
            if (
                current.status == "ai_candidate"
                and next_status == "medically_confirmed"
                and not normalized_actor
            ):
                raise MonitoringProtocolStateConflictError(
                    "medical fact confirmation requires a confirming actor"
                )
            if self._fact_is_bound_to_published_pack(
                connection,
                fact_revision_id,
            ):
                raise MonitoringProtocolStateConflictError(
                    "facts bound to a published rule pack are immutable"
                )
            updated = connection.execute(
                """
                UPDATE monitoring_protocol_fact_state
                SET status = ?, state_version = state_version + 1, updated_at = ?
                WHERE fact_revision_id = ? AND state_version = ?
                """,
                (next_status, _utc_now_text(), fact_revision_id, expected_state_version),
            )
            if updated.rowcount != 1:
                raise MonitoringProtocolStateConflictError(
                    "protocol fact state changed concurrently"
                )
            candidate = replace(
                current,
                status=next_status,
                state_version=current.state_version + 1,
            )
            self._event(
                connection,
                current.project_id,
                "protocol_fact_state",
                fact_revision_id,
                "transitioned",
                {
                    "from_status": current.status,
                    "to_status": next_status,
                    "from_state_version": current.state_version,
                    "to_state_version": candidate.state_version,
                    "actor": normalized_actor,
                },
            )
            return candidate

    def transition_rule_status(
        self,
        rule_revision_id: str,
        *,
        expected_state_version: int,
        status: str,
        actor: str = "",
    ) -> MonitoringRuleDefinition:
        allowed = {
            "candidate": {"confirmed", "disabled", "superseded"},
            "confirmed": {"enabled", "disabled", "superseded"},
            "enabled": {"enabled", "disabled", "superseded"},
            "disabled": {"confirmed", "superseded"},
            "superseded": {"superseded"},
        }
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM monitoring_rule_definitions WHERE rule_revision_id = ?",
                (rule_revision_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound("rule definition not found")
            current = self._rule_with_state(connection, row)
            next_status = str(status or "").strip().lower()
            if current.state_version != int(expected_state_version):
                raise MonitoringProtocolStateConflictError(
                    f"rule state expected {expected_state_version}, current {current.state_version}"
                )
            if next_status not in allowed.get(current.status, set()):
                raise MonitoringProtocolStateConflictError(
                    f"invalid rule status transition: {current.status} -> {next_status}"
                )
            normalized_actor = str(actor or "").strip()
            if next_status == "enabled":
                raise MonitoringProtocolStateConflictError(
                    "rules may be enabled only by the lifecycle publish transaction"
                )
            if (
                current.status == "candidate"
                and next_status == "confirmed"
                and not normalized_actor
            ):
                raise MonitoringProtocolStateConflictError(
                    "rule confirmation requires a confirming actor"
                )
            if current.status == "candidate" and next_status == "confirmed":
                missing_identity = [
                    field
                    for field in _RULE_PACK_IDENTITY_FIELDS
                    if not str(getattr(current, field, "") or "").strip()
                ]
                if missing_identity:
                    raise MonitoringProtocolStateConflictError(
                        "rule confirmation requires the complete immutable "
                        f"mapping identity: missing {missing_identity}"
                    )
            if self._rule_is_in_published_pack(connection, rule_revision_id):
                raise MonitoringProtocolStateConflictError(
                    "rules in a published rule pack are immutable"
                )
            updated = connection.execute(
                """
                UPDATE monitoring_rule_definition_state
                SET status = ?, state_version = state_version + 1, updated_at = ?
                WHERE rule_revision_id = ? AND state_version = ?
                """,
                (next_status, _utc_now_text(), rule_revision_id, expected_state_version),
            )
            if updated.rowcount != 1:
                raise MonitoringProtocolStateConflictError(
                    "rule state changed concurrently"
                )
            candidate = replace(
                current,
                status=next_status,
                state_version=current.state_version + 1,
            )
            self._event(
                connection,
                current.project_id,
                "rule_definition_state",
                rule_revision_id,
                "transitioned",
                {
                    "from_status": current.status,
                    "to_status": next_status,
                    "from_state_version": current.state_version,
                    "to_state_version": candidate.state_version,
                    "actor": normalized_actor,
                },
            )
            return candidate

    def next_pack_revision(self, project_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(pack_revision), 0) AS current_revision
                FROM monitoring_rule_packs WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        return int(row["current_revision"]) + 1

    def latest_rule_pack(self, project_id: str) -> MonitoringRulePack | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_rule_packs
                WHERE project_id = ?
                ORDER BY pack_revision DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if row is None:
                return None
            return self._pack_from_row(row, connection)

    def store_rule_pack(
        self,
        pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
    ) -> MonitoringRulePack:
        rule_by_id = {rule.rule_revision_id: rule for rule in rules}
        if tuple(sorted(rule_by_id)) != tuple(sorted(pack.rule_revision_ids)):
            raise RulePackPublicationError(
                "rule pack membership does not match supplied rules"
            )
        if pack.status != "draft":
            raise RulePackLifecycleError(
                "direct rule pack storage permits only draft; terminal stages require LifecycleService"
            )
        if pack.published_at:
            raise RulePackLifecycleError("draft rule pack must not have published_at")
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM monitoring_rule_packs
                WHERE rule_pack_id = ?
                """,
                (pack.rule_pack_id,),
            ).fetchone()
            if existing is not None:
                restored = self._pack_from_row(existing, connection)
                if restored != pack:
                    raise RulePackRevisionConflictError(
                        "rule pack identity has conflicting content"
                    )
                return restored
            same_revision = connection.execute(
                """
                SELECT rule_pack_id FROM monitoring_rule_packs
                WHERE project_id = ? AND pack_revision = ?
                """,
                (pack.project_id, pack.pack_revision),
            ).fetchone()
            if same_revision is not None:
                raise RulePackRevisionConflictError(
                    "pack revision already exists for project"
                )
            expected_revision = connection.execute(
                """
                SELECT COALESCE(MAX(pack_revision), 0) + 1 AS expected_revision
                FROM monitoring_rule_packs WHERE project_id = ?
                """,
                (pack.project_id,),
            ).fetchone()["expected_revision"]
            if int(expected_revision) != pack.pack_revision:
                raise RulePackRevisionConflictError(
                    f"expected pack revision {expected_revision}"
                )
            version_row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE protocol_version_id = ?
                """,
                (pack.protocol_version_id,),
            ).fetchone()
            if version_row is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            version = self._protocol_version_with_state(connection, version_row)
            if version.project_id != pack.project_id:
                raise ProtocolVersionConflictError(
                    "rule pack protocol version belongs to another project"
                )
            if pack.applicability_status != version.applicability_status:
                raise RulePackLifecycleError(
                    "draft rule pack applicability must match its protocol version"
                )
            all_fact_ids: set[str] = set()
            for rule in rules:
                all_fact_ids.update(rule.fact_revision_ids)
            facts = self._facts_by_id(connection, all_fact_ids)
            if set(facts) != all_fact_ids:
                missing = sorted(all_fact_ids - set(facts))
                raise RulePackPublicationError(
                    f"rule pack references missing protocol facts: {missing}"
                )
            for rule in rules:
                if rule.project_id != pack.project_id:
                    raise RulePackPublicationError(
                        "rule pack contains another project"
                    )
                if rule.protocol_version_id != pack.protocol_version_id:
                    raise RulePackPublicationError(
                        "rule pack contains another protocol version"
                    )
                if rule.status not in {"candidate", "confirmed"}:
                    raise RulePackLifecycleError(
                        "draft rule pack may contain only candidate or confirmed rules"
                    )
                if rule.status == "confirmed" and not (
                    rule.mapping_revision
                    and rule.mapping_content_sha256
                    and rule.capability_manifest_sha256
                    and rule.effective_capabilities_sha256
                ):
                    raise RulePackLifecycleError(
                        "confirmed rules in a draft rule pack require "
                        "immutable mapping identity"
                    )
                if rule.state_version != 1:
                    raise MonitoringProtocolStateConflictError(
                        "new rule revisions must start at state_version 1"
                    )
                validate_predicate_expression(rule.preconditions)
                validate_predicate_expression(rule.trigger_expression)
                validate_predicate_expression(rule.exclusions)
                validate_rule_clinical_compatibility(
                    rule_family=rule.rule_family,
                    clinical_domain=rule.clinical_domain,
                    required_domains=rule.required_domains,
                )
                validate_rule_field_lineage(
                    # Validation normalizes legacy unit contracts in-place;
                    # keep the revision-bearing rule payload immutable.
                    field_lineage=dict(rule.field_lineage),
                    preconditions=rule.preconditions,
                    trigger_expression=rule.trigger_expression,
                    exclusions=rule.exclusions,
                    evidence_template=rule.evidence_template,
                    required_domains=rule.required_domains,
                )
                expected_fact_domains = RULE_FAMILY_CLINICAL_DOMAINS[rule.rule_family]
                source_refs = {
                    item.fact_revision_id: item for item in rule.source_refs
                }
                if set(source_refs) != set(rule.fact_revision_ids):
                    raise RulePackPublicationError(
                        "rule source_refs must bind every and only referenced fact"
                    )
                for fact_id in rule.fact_revision_ids:
                    fact = facts[fact_id]
                    if fact.project_id != pack.project_id:
                        raise RulePackPublicationError(
                            "rule references another project fact"
                        )
                    if fact.protocol_version_id != pack.protocol_version_id:
                        raise RulePackPublicationError(
                            "rule references another protocol version fact"
                        )
                    if fact.status != "medically_confirmed":
                        raise RulePackPublicationError(
                            "draft rules must be compiled from medically confirmed facts"
                        )
                    if fact.clinical_domain not in expected_fact_domains:
                        raise RulePackPublicationError(
                            f"rule family {rule.rule_family} is incompatible with fact clinical domain {fact.clinical_domain}"
                        )
                    source_ref = source_refs[fact_id]
                    if (
                        source_ref.source_entry_id != fact.source_entry_id
                        or source_ref.source_locator != fact.source_locator
                        or source_ref.source_text_sha256 != fact.source_text_sha256
                    ):
                        raise RulePackPublicationError(
                            "rule source_refs do not match the bound protocol fact source"
                        )

            now = _utc_now_text()
            for rule in rules:
                if rule.supersedes_rule_revision_id:
                    predecessor = connection.execute(
                        """
                        SELECT project_id, rule_key
                        FROM monitoring_rule_definitions
                        WHERE rule_revision_id = ?
                        """,
                        (rule.supersedes_rule_revision_id,),
                    ).fetchone()
                    if (
                        predecessor is None
                        or predecessor["project_id"] != rule.project_id
                        or predecessor["rule_key"] != rule.rule_key
                    ):
                        raise RulePackRevisionConflictError(
                            "superseded rule revision must exist in the same "
                            "project and rule_key lineage"
                        )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO monitoring_rule_definitions (
                        rule_revision_id, project_id, protocol_version_id,
                        rule_key, rule_family, status, title, executor,
                        required_domains_json, preconditions_json,
                        trigger_expression_json, exclusions_json, severity,
                        confidence, evidence_template, fact_revision_ids_json,
                        source_entry_id, source_locator, source_text,
                        source_text_sha256, clinical_domain, source_refs_json,
                        field_lineage_json, mapping_revision,
                        mapping_content_sha256, capability_manifest_sha256,
                        effective_capabilities_sha256,
                        recommendation_candidate_id,
                        supersedes_rule_revision_id,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule.rule_revision_id,
                        rule.project_id,
                        rule.protocol_version_id,
                        rule.rule_key,
                        rule.rule_family,
                        rule.status,
                        rule.title,
                        rule.executor,
                        _json(rule.required_domains),
                        _json(rule.preconditions),
                        _json(rule.trigger_expression),
                        _json(rule.exclusions),
                        rule.severity,
                        rule.confidence,
                        rule.evidence_template,
                        _json(rule.fact_revision_ids),
                        rule.source_entry_id,
                        rule.source_locator,
                        rule.source_text,
                        rule.source_text_sha256,
                        rule.clinical_domain,
                        _json([asdict(item) for item in rule.source_refs]),
                        _json(rule.field_lineage),
                        rule.mapping_revision,
                        rule.mapping_content_sha256,
                        rule.capability_manifest_sha256,
                        rule.effective_capabilities_sha256,
                        rule.recommendation_candidate_id,
                        rule.supersedes_rule_revision_id,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO monitoring_rule_definition_state (
                        rule_revision_id, status, state_version, updated_at
                    ) VALUES (?, ?, 1, ?)
                    """,
                    (rule.rule_revision_id, rule.status, now),
                )
                restored_rule = self._rule_by_id(connection, rule.rule_revision_id)
                if self._rule_immutable(restored_rule) != self._rule_immutable(rule):
                    raise RulePackRevisionConflictError(
                        "rule revision identity has conflicting content"
                    )
                if restored_rule.status not in {"candidate", "confirmed"}:
                    raise RulePackLifecycleError(
                        "draft rule pack may contain only candidate or "
                        "confirmed rule states"
                    )
                if restored_rule.status == "confirmed" and not (
                    restored_rule.mapping_revision
                    and restored_rule.mapping_content_sha256
                    and restored_rule.capability_manifest_sha256
                ):
                    raise RulePackLifecycleError(
                        "confirmed rule states in a draft rule pack require "
                        "immutable mapping identity"
                    )
            self._insert_rule_pack_record(
                connection,
                pack,
                tuple(
                    self._rule_by_id(connection, rule.rule_revision_id)
                    for rule in rules
                ),
                predecessor_rule_pack_id="",
                actor=pack.created_by,
                transition_at=now,
                shadow_run_id="",
            )
        return pack

    def advance_rule_pack_stage(
        self,
        predecessor_rule_pack_id: str,
        *,
        target_status: str,
        actor: str,
        shadow_run_id: str = "",
        transition_at: str = "",
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        predecessor_rule_pack_id = str(predecessor_rule_pack_id or "").strip()
        target_status = str(target_status or "").strip().lower()
        normalized_actor = str(actor or "").strip()
        transition_at = str(transition_at or "").strip() or _utc_now_text()
        if not predecessor_rule_pack_id:
            raise RulePackLifecycleError("predecessor rule pack is required")
        if not normalized_actor:
            raise RulePackLifecycleError("lifecycle transition actor is required")
        try:
            datetime.fromisoformat(transition_at)
        except ValueError as exc:
            raise RulePackLifecycleError(
                "transition_at must be an ISO datetime"
            ) from exc

        with self._transaction() as connection:
            predecessor_row = connection.execute(
                "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
                (predecessor_rule_pack_id,),
            ).fetchone()
            if predecessor_row is None:
                raise MonitoringProtocolRecordNotFound("predecessor rule pack not found")
            predecessor = self._pack_from_row(predecessor_row, connection)
            if expected_pack_revision is not None and int(
                expected_pack_revision
            ) != predecessor.pack_revision:
                raise RulePackRevisionConflictError(
                    f"expected pack revision {expected_pack_revision} but "
                    f"predecessor is at revision {predecessor.pack_revision}"
                )
            lifecycle = connection.execute(
                """
                SELECT * FROM monitoring_rule_pack_lifecycle
                WHERE rule_pack_id = ?
                """,
                (predecessor_rule_pack_id,),
            ).fetchone()
            if (
                lifecycle is None
                or int(lifecycle["lifecycle_version"]) != _STRICT_LIFECYCLE_VERSION
                or _sqlite_bool(lifecycle["legacy_read_only"], "legacy_read_only")
            ):
                raise RulePackLifecycleError(
                    "legacy rule packs are read-only and cannot continue a lifecycle"
                )
            expected_target = _RULE_PACK_STAGE_TRANSITIONS.get(predecessor.status)
            if expected_target != target_status:
                replayed = self._replay_advanced_stage(
                    connection,
                    predecessor,
                    target_status=target_status,
                    shadow_run_id=shadow_run_id,
                )
                if replayed is not None:
                    return replayed
                raise RulePackLifecycleError(
                    f"invalid rule pack lifecycle transition: "
                    f"{predecessor.status} -> {target_status}"
                )
            try:
                self._assert_latest_pack_for_rule_set(
                    connection,
                    predecessor,
                )
            except RulePackLifecycleError:
                replayed = self._replay_advanced_stage(
                    connection,
                    predecessor,
                    target_status=target_status,
                    shadow_run_id=shadow_run_id,
                )
                if replayed is not None:
                    return replayed
                raise

            version_row = connection.execute(
                """
                SELECT * FROM monitoring_protocol_versions
                WHERE protocol_version_id = ?
                """,
                (predecessor.protocol_version_id,),
            ).fetchone()
            if version_row is None:
                raise MonitoringProtocolRecordNotFound("protocol version not found")
            version = self._protocol_version_with_state(connection, version_row)
            if version.project_id != predecessor.project_id:
                raise ProtocolVersionConflictError(
                    "rule pack protocol version belongs to another project"
                )

            current_rules = self._current_rules_for_pack(
                connection,
                predecessor.rule_pack_id,
            )
            if tuple(sorted(rule.rule_revision_id for rule in current_rules)) != tuple(
                sorted(predecessor.rule_revision_ids)
            ):
                raise RulePackLifecycleError(
                    "predecessor rule pack membership is incomplete"
                )
            non_confirmed = sorted(
                rule.rule_key for rule in current_rules if rule.status != "confirmed"
            )
            if non_confirmed:
                raise RulePackLifecycleError(
                    f"{target_status} requires confirmed rules: {non_confirmed}"
                )
            self._assert_rules_bind_confirmed_facts(
                connection,
                predecessor,
                current_rules,
            )
            _assert_rules_share_complete_mapping_identity(current_rules)

            normalized_shadow_run_id = str(shadow_run_id or "").strip()
            if target_status == "confirmed":
                if not normalized_shadow_run_id:
                    raise RulePackLifecycleError(
                        "confirmed stage requires a trusted shadow run"
                    )
                self._validate_shadow_evidence(
                    connection,
                    predecessor,
                    current_rules,
                    normalized_shadow_run_id,
                )
            elif normalized_shadow_run_id:
                raise RulePackLifecycleError(
                    "shadow_run_id is accepted only when confirming a shadow pack"
                )

            if target_status == "published":
                if version.status != "confirmed":
                    raise RulePackPublicationError(
                        "published rule pack requires a confirmed, non-superseded protocol version"
                    )
                if version.applicability_status == "project_effective_confirmed":
                    if (
                        predecessor.applicability_status
                        != "project_effective_confirmed"
                        or not version.operational_effective_from
                    ):
                        raise RulePackPublicationError(
                            "published rule pack requires confirmed project operational applicability"
                        )
                elif version.applicability_status == "site_specific":
                    if predecessor.applicability_status != "site_specific":
                        raise RulePackPublicationError(
                            "site_specific rule pack applicability does not match its protocol version"
                        )
                    confirmed_assignment = connection.execute(
                        """
                        SELECT 1
                        FROM monitoring_protocol_applicability_assignments a
                        JOIN monitoring_protocol_applicability_assignment_state s
                          ON s.assignment_id = a.assignment_id
                        WHERE a.project_id = ?
                          AND a.protocol_version_id = ?
                          AND s.status = 'confirmed'
                        LIMIT 1
                        """,
                        (version.project_id, version.protocol_version_id),
                    ).fetchone()
                    if confirmed_assignment is None:
                        raise RulePackPublicationError(
                            "site_specific publication requires confirmed applicability evidence"
                        )
                else:
                    raise RulePackPublicationError(
                        "published rule pack requires confirmed operational applicability"
                    )
                release_shadow_run_id = self._validate_release_shadow_evidence(
                    connection,
                    predecessor,
                    current_rules,
                )
                enabled_rules: list[MonitoringRuleDefinition] = []
                for rule in current_rules:
                    updated = connection.execute(
                        """
                        UPDATE monitoring_rule_definition_state
                        SET status = 'enabled',
                            state_version = state_version + 1,
                            updated_at = ?
                        WHERE rule_revision_id = ?
                          AND state_version = ?
                          AND status = 'confirmed'
                        """,
                        (
                            transition_at,
                            rule.rule_revision_id,
                            rule.state_version,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise MonitoringProtocolStateConflictError(
                            "rule state changed concurrently during publish"
                        )
                    enabled = replace(
                        rule,
                        status="enabled",
                        state_version=rule.state_version + 1,
                    )
                    enabled_rules.append(enabled)
                    self._event(
                        connection,
                        rule.project_id,
                        "rule_definition_state",
                        rule.rule_revision_id,
                        "transitioned",
                        {
                            "from_status": "confirmed",
                            "to_status": "enabled",
                            "from_state_version": rule.state_version,
                            "to_state_version": enabled.state_version,
                            "actor": normalized_actor,
                            "reason": "lifecycle_publish",
                        },
                    )
                stage_rules = tuple(enabled_rules)
            else:
                stage_rules = current_rules
                release_shadow_run_id = normalized_shadow_run_id

            expected_revision = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(pack_revision), 0) + 1
                    FROM monitoring_rule_packs
                    WHERE project_id = ?
                    """,
                    (predecessor.project_id,),
                ).fetchone()[0]
            )
            pack = MonitoringRulePack.create(
                project_id=predecessor.project_id,
                protocol_version_id=predecessor.protocol_version_id,
                pack_revision=expected_revision,
                status=target_status,
                applicability_status=predecessor.applicability_status,
                rules=stage_rules,
                created_by=normalized_actor,
                retrospective_policy=predecessor.retrospective_policy,
                published_at=transition_at if target_status == "published" else "",
                _lifecycle_authorized=True,
            )
            self._insert_rule_pack_record(
                connection,
                pack,
                stage_rules,
                predecessor_rule_pack_id=predecessor.rule_pack_id,
                actor=normalized_actor,
                transition_at=transition_at,
                shadow_run_id=release_shadow_run_id,
            )
            return pack

    def rule_pack(
        self,
        rule_pack_id: str,
    ) -> tuple[MonitoringRulePack, tuple[MonitoringRuleDefinition, ...]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
                (rule_pack_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound("rule pack not found")
            pack = self._pack_from_row(row, connection)
            rules = self._rules_for_pack(connection, rule_pack_id)
        return pack, rules

    def list_rule_packs(
        self,
        project_id: str,
    ) -> tuple[MonitoringRulePack, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_rule_packs
                WHERE project_id = ?
                ORDER BY pack_revision
                """,
                (project_id,),
            ).fetchall()
            packs = tuple(self._pack_from_row(row, connection) for row in rows)
        return packs

    def rule_pack_lifecycle(self, rule_pack_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_rule_pack_lifecycle
                WHERE rule_pack_id = ?
                """,
                (rule_pack_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound(
                    "rule pack lifecycle metadata not found"
                )
            return {
                "rule_pack_id": row["rule_pack_id"],
                "lifecycle_version": int(row["lifecycle_version"]),
                "predecessor_rule_pack_id": row["predecessor_rule_pack_id"],
                "transition_actor": row["transition_actor"],
                "transition_at": row["transition_at"],
                "shadow_run_id": row["shadow_run_id"],
                "legacy_read_only": _sqlite_bool(
                    row["legacy_read_only"],
                    "legacy_read_only",
                ),
            }

    def rule_pack_stage_ancestor(
        self,
        project_id: str,
        rule_pack_id: str,
        *,
        status: str,
    ) -> MonitoringRulePack | None:
        """Walk the lifecycle chain backwards to the nearest stage match.

        Returns the given pack itself when it already carries the requested
        status, otherwise the nearest predecessor with that status. Cycles,
        cross-project links and missing chain rows fail closed; reaching
        the draft root (or a chain end) without a match returns None.
        """
        target = str(status).strip()
        visited: set[str] = set()
        current_id = str(rule_pack_id).strip()
        with self._connect() as connection:
            while True:
                if current_id in visited:
                    raise RulePackLifecycleError(
                        "rule pack lifecycle contains a cycle"
                    )
                visited.add(current_id)
                row = connection.execute(
                    "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
                    (current_id,),
                ).fetchone()
                if row is None:
                    raise RulePackLifecycleError(
                        "rule pack lifecycle chain is missing a pack row"
                    )
                pack = self._pack_from_row(row, connection)
                if pack.project_id != project_id:
                    raise RulePackLifecycleError(
                        "rule pack lifecycle chain crosses project boundaries"
                    )
                if pack.status == target:
                    return pack
                if pack.status == "draft":
                    return None
                lifecycle = connection.execute(
                    """
                    SELECT predecessor_rule_pack_id
                    FROM monitoring_rule_pack_lifecycle
                    WHERE rule_pack_id = ?
                    """,
                    (current_id,),
                ).fetchone()
                if lifecycle is None:
                    raise RulePackLifecycleError(
                        "rule pack lifecycle chain is missing lifecycle metadata"
                    )
                predecessor_id = str(
                    lifecycle["predecessor_rule_pack_id"] or ""
                ).strip()
                if not predecessor_id:
                    return None
                current_id = predecessor_id

    def current_published_pack(
        self,
        project_id: str,
        *,
        as_of: str,
    ) -> tuple[MonitoringRulePack, tuple[MonitoringRuleDefinition, ...]]:
        try:
            datetime.fromisoformat(as_of)
        except ValueError as exc:
            raise MonitoringProtocolRuleRepositoryError(
                "as_of must be an ISO date or datetime"
            ) from exc
        as_of_date = as_of[:10]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*
                FROM monitoring_rule_packs p
                JOIN monitoring_protocol_versions v
                  ON v.protocol_version_id = p.protocol_version_id
                JOIN monitoring_protocol_version_state vs
                  ON vs.protocol_version_id = v.protocol_version_id
                JOIN monitoring_rule_pack_lifecycle l
                  ON l.rule_pack_id = p.rule_pack_id
                WHERE p.project_id = ?
                  AND p.status = 'published'
                  AND p.applicability_status = 'project_effective_confirmed'
                  AND vs.status = 'confirmed'
                  AND vs.applicability_status = 'project_effective_confirmed'
                  AND vs.operational_effective_from <> ''
                  AND vs.operational_effective_from <= ?
                  AND (
                    vs.operational_effective_to = ''
                    OR vs.operational_effective_to >= ?
                  )
                  AND l.lifecycle_version = ?
                  AND l.legacy_read_only = 0
                  AND p.published_at <> ''
                  AND substr(p.published_at, 1, 10) <= ?
                ORDER BY vs.operational_effective_from DESC,
                         p.pack_revision DESC
                """,
                (
                    project_id,
                    as_of_date,
                    as_of_date,
                    _STRICT_LIFECYCLE_VERSION,
                    as_of_date,
                ),
            ).fetchall()
            if not rows:
                raise ProtocolApplicabilityUnresolvedError(
                    "no published rule pack has confirmed applicability for the requested date"
                )
            if len(rows) > 1:
                first_version = rows[0]["protocol_version_id"]
                conflicting_versions = {
                    row["protocol_version_id"] for row in rows if row["protocol_version_id"] != first_version
                }
                if conflicting_versions:
                    raise ProtocolApplicabilityConflictError(
                        "multiple protocol versions are effective for the requested date"
                    )
            pack = self._pack_from_row(rows[0], connection)
            rules = self._assert_published_pack_integrity(connection, pack)
        return pack, rules

    def published_pack_for_protocol_version(
        self,
        project_id: str,
        protocol_version_id: str,
    ) -> tuple[MonitoringRulePack, tuple[MonitoringRuleDefinition, ...]]:
        """Return the one complete published pack bound to an exact protocol version."""
        project = str(project_id or "").strip()
        version_id = str(protocol_version_id or "").strip()
        if not project or not version_id:
            raise MonitoringProtocolRuleRepositoryError(
                "project_id and protocol_version_id are required"
            )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*
                FROM monitoring_rule_packs p
                JOIN monitoring_protocol_versions v
                  ON v.protocol_version_id = p.protocol_version_id
                JOIN monitoring_protocol_version_state vs
                  ON vs.protocol_version_id = v.protocol_version_id
                JOIN monitoring_rule_pack_lifecycle l
                  ON l.rule_pack_id = p.rule_pack_id
                WHERE p.project_id = ?
                  AND p.protocol_version_id = ?
                  AND v.project_id = p.project_id
                  AND p.status = 'published'
                  AND p.published_at <> ''
                  AND vs.status = 'confirmed'
                  AND p.applicability_status = vs.applicability_status
                  AND l.lifecycle_version = ?
                  AND l.legacy_read_only = 0
                ORDER BY p.pack_revision, p.rule_pack_id
                """,
                (project, version_id, _STRICT_LIFECYCLE_VERSION),
            ).fetchall()
            if not rows:
                raise ProtocolApplicabilityUnresolvedError(
                    "no complete published rule pack is bound to the resolved "
                    "protocol version"
                )
            if len(rows) > 1:
                raise ProtocolApplicabilityConflictError(
                    "multiple published rule packs are bound to the resolved "
                    "protocol version"
                )
            pack = self._pack_from_row(rows[0], connection)
            rules = self._assert_published_pack_integrity(connection, pack)
        return pack, rules

    def rule_source(
        self,
        rule_pack_id: str,
        rule_key: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT d.*
                FROM monitoring_rule_pack_items i
                JOIN monitoring_rule_definitions d
                  ON d.rule_revision_id = i.rule_revision_id
                WHERE i.rule_pack_id = ? AND i.rule_key = ?
                """,
                (rule_pack_id, rule_key),
            ).fetchone()
        if row is None:
            raise MonitoringProtocolRecordNotFound("rule source not found")
        rule = self._rule_from_row(row)
        return {
            "rule_key": rule.rule_key,
            "rule_revision_id": rule.rule_revision_id,
            "title": rule.title,
            "source_text": rule.source_text,
            "primary_summary": f"方案原文：{rule.source_text}",
            "source_entry_id": rule.source_entry_id,
            "source_locator": rule.source_locator,
            "source_refs": [item.public_dict() for item in rule.source_refs],
        }

    def store_re_review_tasks(
        self,
        tasks: Iterable[RuleReReviewTask],
    ) -> tuple[RuleReReviewTask, ...]:
        stored: list[RuleReReviewTask] = []
        with self._transaction() as connection:
            for task in tasks:
                existing = connection.execute(
                    """
                    SELECT * FROM monitoring_rule_re_review_tasks
                    WHERE task_id = ?
                    """,
                    (task.task_id,),
                ).fetchone()
                if existing is not None:
                    stored.append(self._re_review_from_row(existing))
                    continue
                now = _utc_now_text()
                connection.execute(
                    """
                    INSERT INTO monitoring_rule_re_review_tasks (
                        task_id, project_id, risk_instance_id, rule_key,
                        previous_rule_revision_id, current_rule_revision_id,
                        reason, reason_sha256, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.project_id,
                        task.risk_instance_id,
                        task.rule_key,
                        task.previous_rule_revision_id,
                        task.current_rule_revision_id,
                        task.reason,
                        sha256(task.reason.encode("utf-8")).hexdigest(),
                        task.status,
                        now,
                        now,
                    ),
                )
                stored.append(task)
                self._event(
                    connection,
                    task.project_id,
                    "rule_re_review",
                    task.task_id,
                    "created",
                    asdict(task),
                )
        return tuple(stored)

    def list_re_review_tasks(
        self,
        project_id: str,
        *,
        status: str = "",
    ) -> tuple[RuleReReviewTask, ...]:
        query = """
            SELECT * FROM monitoring_rule_re_review_tasks
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if status:
            query += " AND status = ?"
            parameters.append(status)
        query += " ORDER BY created_at, task_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._re_review_from_row(row) for row in rows)

    def store_gold_cases(
        self,
        cases: Iterable[RuleGoldStandardCase],
    ) -> tuple[RuleGoldStandardCase, ...]:
        stored: list[RuleGoldStandardCase] = []
        with self._transaction() as connection:
            for case in cases:
                stored.append(self._store_gold_case(connection, case))
        return tuple(stored)

    def _store_gold_case(
        self,
        connection: sqlite3.Connection,
        case: RuleGoldStandardCase,
    ) -> RuleGoldStandardCase:
        owned_rule = connection.execute(
            """
            SELECT *
            FROM monitoring_rule_definitions
            WHERE rule_revision_id = ?
            """,
            (case.rule_revision_id,),
        ).fetchone()
        if (
            owned_rule is None
            or owned_rule["project_id"] != case.project_id
            or owned_rule["rule_key"] != case.rule_key
        ):
            raise RulePackLifecycleError(
                "gold standard case must bind the exact stored rule revision, "
                "project_id and rule_key"
            )
        exact_rule = self._rule_with_state(connection, owned_rule)
        self._validate_gold_case_release_binding(
            case,
            rule=exact_rule,
        )
        existing = connection.execute(
            """
            SELECT * FROM monitoring_rule_gold_cases
            WHERE case_id = ?
            """,
            (case.case_id,),
        ).fetchone()
        if existing is not None:
            restored = self._gold_case_from_row(existing)
            if restored != case:
                raise RulePackRevisionConflictError(
                    "gold standard case identity has conflicting content"
                )
            return restored
        connection.execute(
            """
            INSERT INTO monitoring_rule_gold_cases (
                case_id, project_id, rule_key, rule_revision_id,
                source_entry_id, source_content_sha256,
                source_revision, batch_revision, case_label,
                input_record_json, previous_record_json,
                related_records_json, observed_domains_json,
                expected_match, coverage_labels_json, medical_rationale,
                evidence_locators_json, source_row_bindings_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case.case_id,
                case.project_id,
                case.rule_key,
                case.rule_revision_id,
                case.source_entry_id,
                case.source_content_sha256,
                case.source_revision,
                case.batch_revision,
                case.case_label,
                _json(case.input_record),
                _json(case.previous_record),
                _json(case.related_records),
                _json(case.observed_domains),
                int(case.expected_match),
                _json(case.coverage_labels),
                case.medical_rationale,
                _json(case.evidence_locators),
                _json(
                    [
                        {
                            **asdict(binding),
                            "record_roles": list(binding.record_roles),
                        }
                        for binding in case.source_row_bindings
                    ]
                ),
                _utc_now_text(),
            ),
        )
        self._event(
            connection,
            case.project_id,
            "rule_gold_case",
            case.case_id,
            "stored",
            case.public_dict(),
        )
        return case

    def gold_cases(
        self,
        project_id: str,
        *,
        rule_keys: Iterable[str] = (),
        rule_revision_ids: Iterable[str] = (),
    ) -> tuple[RuleGoldStandardCase, ...]:
        keys = tuple(sorted({str(item).strip() for item in rule_keys if str(item).strip()}))
        revision_ids = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in rule_revision_ids
                    if str(item).strip()
                }
            )
        )
        query = """
            SELECT * FROM monitoring_rule_gold_cases
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if keys:
            query += f" AND rule_key IN ({','.join('?' for _ in keys)})"
            parameters.extend(keys)
        if revision_ids:
            query += (
                f" AND rule_revision_id IN "
                f"({','.join('?' for _ in revision_ids)})"
            )
            parameters.extend(revision_ids)
        query += " ORDER BY rule_key, case_label, case_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._gold_case_from_row(row) for row in rows)

    def store_diagnostic_cases(
        self,
        cases: Iterable[RuleDiagnosticCase],
    ) -> tuple[RuleDiagnosticCase, ...]:
        stored: list[RuleDiagnosticCase] = []
        with self._transaction() as connection:
            for case in cases:
                stored.append(self._store_diagnostic_case(connection, case))
        return tuple(stored)

    def store_shadow_promotion(
        self,
        gold_cases: Iterable[RuleGoldStandardCase],
        diagnostic_cases: Iterable[RuleDiagnosticCase],
    ) -> tuple[
        tuple[RuleGoldStandardCase, ...],
        tuple[RuleDiagnosticCase, ...],
    ]:
        """Store one shadow-confirmation promotion atomically.

        Both case families commit inside a single transaction so a failed
        medical confirmation never leaves trusted cases behind: any error
        rolls the whole promotion back.
        """
        stored_gold: list[RuleGoldStandardCase] = []
        stored_diagnostic: list[RuleDiagnosticCase] = []
        with self._transaction() as connection:
            for case in gold_cases:
                stored_gold.append(self._store_gold_case(connection, case))
            for case in diagnostic_cases:
                stored_diagnostic.append(
                    self._store_diagnostic_case(connection, case)
                )
        return tuple(stored_gold), tuple(stored_diagnostic)

    def commit_shadow_sample_confirmation(
        self,
        *,
        gold_cases: Iterable[RuleGoldStandardCase],
        diagnostic_cases: Iterable[RuleDiagnosticCase],
        run: RuleShadowRun,
        confirmation: ShadowSampleMedicalConfirmation,
    ) -> tuple[
        tuple[RuleGoldStandardCase, ...],
        tuple[RuleDiagnosticCase, ...],
        RuleShadowRun,
        ShadowSampleMedicalConfirmation,
    ]:
        """Atomically commit one shadow medical confirmation.

        Promoted cases, the trusted shadow run and the confirmation record
        (including their audit events) commit in a single transaction: any
        validation or write failure rolls the entire confirmation attempt
        back while pre-existing independent evidence stays untouched.
        """
        with self._transaction() as connection:
            stored_gold = tuple(
                self._store_gold_case(connection, case) for case in gold_cases
            )
            stored_diagnostic = tuple(
                self._store_diagnostic_case(connection, case)
                for case in diagnostic_cases
            )
            stored_run = self._store_shadow_run(connection, run)
            stored_confirmation = self._store_shadow_sample_confirmation(
                connection, confirmation
            )
        return stored_gold, stored_diagnostic, stored_run, stored_confirmation

    def _store_diagnostic_case(
        self,
        connection: sqlite3.Connection,
        case: RuleDiagnosticCase,
    ) -> RuleDiagnosticCase:
        owned_rule = connection.execute(
            """
            SELECT *
            FROM monitoring_rule_definitions
            WHERE rule_revision_id = ?
            """,
            (case.rule_revision_id,),
        ).fetchone()
        if (
            owned_rule is None
            or owned_rule["project_id"] != case.project_id
            or owned_rule["rule_key"] != case.rule_key
        ):
            raise RulePackLifecycleError(
                "diagnostic case must bind the exact stored rule revision, "
                "project_id and rule_key"
            )
        exact_rule = self._rule_with_state(connection, owned_rule)
        self._validate_diagnostic_case_release_binding(
            case,
            rule=exact_rule,
        )
        existing = connection.execute(
            """
            SELECT * FROM monitoring_rule_diagnostic_cases
            WHERE case_id = ?
            """,
            (case.case_id,),
        ).fetchone()
        if existing is not None:
            restored = self._diagnostic_case_from_row(existing)
            if restored != case:
                raise RulePackRevisionConflictError(
                    "diagnostic case identity has conflicting content"
                )
            return restored
        connection.execute(
            """
            INSERT INTO monitoring_rule_diagnostic_cases (
                case_id, project_id, rule_key, rule_revision_id,
                source_entry_id, source_content_sha256,
                source_revision, batch_revision, case_label,
                input_record_json, previous_record_json,
                related_records_json, observed_domains_json,
                expected_diagnostic_category,
                expected_diagnostic_code, medical_rationale,
                evidence_locators_json, source_row_bindings_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case.case_id,
                case.project_id,
                case.rule_key,
                case.rule_revision_id,
                case.source_entry_id,
                case.source_content_sha256,
                case.source_revision,
                case.batch_revision,
                case.case_label,
                _json(case.input_record),
                _json(case.previous_record),
                _json(case.related_records),
                _json(case.observed_domains),
                case.expected_diagnostic_category,
                case.expected_diagnostic_code,
                case.medical_rationale,
                _json(case.evidence_locators),
                _json(
                    [
                        {
                            **asdict(binding),
                            "record_roles": list(binding.record_roles),
                        }
                        for binding in case.source_row_bindings
                    ]
                ),
                _utc_now_text(),
            ),
        )
        self._event(
            connection,
            case.project_id,
            "rule_diagnostic_case",
            case.case_id,
            "stored",
            case.public_dict(),
        )
        return case

    def diagnostic_cases(
        self,
        project_id: str,
        *,
        rule_keys: Iterable[str] = (),
        rule_revision_ids: Iterable[str] = (),
    ) -> tuple[RuleDiagnosticCase, ...]:
        keys = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in rule_keys
                    if str(item).strip()
                }
            )
        )
        revision_ids = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in rule_revision_ids
                    if str(item).strip()
                }
            )
        )
        query = """
            SELECT * FROM monitoring_rule_diagnostic_cases
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if keys:
            query += f" AND rule_key IN ({','.join('?' for _ in keys)})"
            parameters.extend(keys)
        if revision_ids:
            query += (
                f" AND rule_revision_id IN "
                f"({','.join('?' for _ in revision_ids)})"
            )
            parameters.extend(revision_ids)
        query += " ORDER BY rule_key, case_label, case_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._diagnostic_case_from_row(row) for row in rows)

    def shadow_case_sets(
        self,
        rule_pack_id: str,
    ) -> tuple[
        tuple[RuleGoldStandardCase, ...],
        tuple[RuleDiagnosticCase, ...],
        tuple[RuleRevisionCoverageSnapshot, ...],
        tuple[RuleFamilyCoverageSnapshot, ...],
    ]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_rule_packs
                WHERE rule_pack_id = ?
                """,
                (rule_pack_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound(
                    "rule pack not found"
                )
            pack = self._pack_from_row(row, connection)
            rules = self._current_rules_for_pack(
                connection,
                rule_pack_id,
            )
            revision_ids = tuple(
                rule.rule_revision_id for rule in rules
            )
            gold_rows = connection.execute(
                f"""
                SELECT * FROM monitoring_rule_gold_cases
                WHERE project_id = ?
                  AND rule_revision_id IN (
                    {','.join('?' for _ in revision_ids)}
                  )
                ORDER BY case_id
                """,
                (pack.project_id, *revision_ids),
            ).fetchall()
            diagnostic_rows = connection.execute(
                f"""
                SELECT * FROM monitoring_rule_diagnostic_cases
                WHERE project_id = ?
                  AND rule_revision_id IN (
                    {','.join('?' for _ in revision_ids)}
                  )
                ORDER BY case_id
                """,
                (pack.project_id, *revision_ids),
            ).fetchall()
            gold_cases = tuple(
                self._gold_case_from_row(item) for item in gold_rows
            )
            diagnostic_cases = tuple(
                self._diagnostic_case_from_row(item)
                for item in diagnostic_rows
            )
            for case in gold_cases:
                self._validate_gold_case_release_binding(
                    case,
                    rule=self._rule_by_id(
                        connection,
                        case.rule_revision_id,
                    ),
                )
            for case in diagnostic_cases:
                self._validate_diagnostic_case_release_binding(
                    case,
                    rule=self._rule_by_id(
                        connection,
                        case.rule_revision_id,
                    ),
                )
            rule_coverages, family_coverages = (
                self._recompute_coverage_snapshots(
                    connection,
                    pack,
                    rules,
                    gold_cases,
                    diagnostic_cases,
                )
            )
        return (
            gold_cases,
            diagnostic_cases,
            rule_coverages,
            family_coverages,
        )

    def shadow_coverage_snapshots_for_cases(
        self,
        rule_pack_id: str,
        gold_cases: Sequence[RuleGoldStandardCase],
        diagnostic_cases: Sequence[RuleDiagnosticCase],
    ) -> tuple[
        tuple[RuleRevisionCoverageSnapshot, ...],
        tuple[RuleFamilyCoverageSnapshot, ...],
    ]:
        """Recompute coverage snapshots for a caller-supplied case set.

        Loads the pack and its current rules exactly like
        `shadow_case_sets`, then recomputes the coverage snapshots against
        the (merged) case set provided by the caller. Read-only: no table
        is written.
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_rule_packs
                WHERE rule_pack_id = ?
                """,
                (rule_pack_id,),
            ).fetchone()
            if row is None:
                raise MonitoringProtocolRecordNotFound(
                    "rule pack not found"
                )
            pack = self._pack_from_row(row, connection)
            rules = self._current_rules_for_pack(
                connection,
                rule_pack_id,
            )
            return self._recompute_coverage_snapshots(
                connection,
                pack,
                rules,
                tuple(gold_cases),
                tuple(diagnostic_cases),
                extra_family_gold_cases=tuple(gold_cases),
                extra_family_diagnostic_cases=tuple(diagnostic_cases),
            )

    def store_shadow_run(self, run: RuleShadowRun) -> RuleShadowRun:
        with self._transaction() as connection:
            return self._store_shadow_run(connection, run)

    def _store_shadow_run(
        self,
        connection: sqlite3.Connection,
        run: RuleShadowRun,
    ) -> RuleShadowRun:
        pack = connection.execute(
            """
            SELECT p.*, l.lifecycle_version,
                   l.legacy_read_only
            FROM monitoring_rule_packs p
            LEFT JOIN monitoring_rule_pack_lifecycle l
              ON l.rule_pack_id = p.rule_pack_id
            WHERE p.rule_pack_id = ?
            """,
            (run.rule_pack_id,),
        ).fetchone()
        if pack is None:
            raise MonitoringProtocolRecordNotFound("rule pack not found")
        if pack["project_id"] != run.project_id:
            raise RulePackPublicationError(
                "shadow run rule pack belongs to another project"
            )
        if (
            pack["status"] != "shadow"
            or pack["lifecycle_version"] is None
            or int(pack["lifecycle_version"]) != _STRICT_LIFECYCLE_VERSION
            or _sqlite_bool(pack["legacy_read_only"], "legacy_read_only")
        ):
            raise RulePackLifecycleError(
                "shadow runs may be stored only for a strict shadow pack"
            )
        shadow_pack = self._pack_from_row(pack, connection)
        self._assert_latest_pack_for_rule_set(connection, shadow_pack)
        shadow_rules = self._current_rules_for_pack(
            connection,
            run.rule_pack_id,
        )
        if any(rule.status != "confirmed" for rule in shadow_rules):
            raise RulePackLifecycleError(
                "shadow runs require currently confirmed rule states"
            )
        _assert_rules_share_complete_mapping_identity(shadow_rules)
        if (
            run.status != "completed"
            or run.case_count <= 0
            or run.case_count != len(run.results)
            or run.passed_count + run.failed_count != run.case_count
            or run.passed_count != sum(result.passed for result in run.results)
            or run.failed_count != sum(not result.passed for result in run.results)
            or len({result.case_id for result in run.results})
            != len(run.results)
            or run.diagnostic_case_count != len(run.diagnostic_results)
            or (
                run.diagnostic_passed_count
                + run.diagnostic_failed_count
                != run.diagnostic_case_count
            )
            or run.diagnostic_passed_count
            != sum(result.passed for result in run.diagnostic_results)
            or run.diagnostic_failed_count
            != sum(not result.passed for result in run.diagnostic_results)
            or len(
                {result.case_id for result in run.diagnostic_results}
            )
            != len(run.diagnostic_results)
        ):
            raise RulePackLifecycleError(
                "shadow run result counts or case identities are invalid"
            )
        frozen_cases = self._validate_shadow_run_cases(
            connection,
            run.project_id,
            run.rule_pack_id,
            run.results,
        )
        if (
            not run.case_set_content_sha256
            or run.case_set_content_sha256
            != gold_case_set_content_sha256(frozen_cases)
        ):
            raise RulePackLifecycleError(
                "shadow run gold case snapshot hash does not match the complete "
                "repository case set"
            )
        frozen_diagnostic_cases = (
            self._validate_shadow_run_diagnostic_cases(
                connection,
                run.project_id,
                run.rule_pack_id,
                run.diagnostic_results,
            )
        )
        if (
            not run.diagnostic_case_set_content_sha256
            or run.diagnostic_case_set_content_sha256
            != diagnostic_case_set_content_sha256(
                frozen_diagnostic_cases
            )
        ):
            raise RulePackLifecycleError(
                "shadow run diagnostic case snapshot hash does not match "
                "the complete repository diagnostic case set"
            )
        if (
            not run.diagnostic_results_content_sha256
            or run.diagnostic_results_content_sha256
            != shadow_diagnostic_results_content_sha256(
                run.diagnostic_results
            )
        ):
            raise RulePackLifecycleError(
                "shadow run diagnostic result snapshot hash is invalid"
            )
        if run.rule_coverages or run.family_coverages:
            expected_rule_coverages, expected_family_coverages = (
                self._recompute_coverage_snapshots(
                    connection,
                    shadow_pack,
                    self._current_rules_for_pack(
                        connection,
                        run.rule_pack_id,
                    ),
                    frozen_cases,
                    frozen_diagnostic_cases,
                )
            )
            if (
                run.rule_coverages != expected_rule_coverages
                or run.family_coverages != expected_family_coverages
                or not run.coverage_content_sha256
                or run.coverage_content_sha256
                != shadow_coverage_content_sha256(
                    expected_rule_coverages,
                    expected_family_coverages,
                )
            ):
                raise RulePackLifecycleError(
                    "shadow run coverage snapshot does not match repository evidence"
                )
        existing = connection.execute(
            """
            SELECT * FROM monitoring_rule_shadow_runs
            WHERE shadow_run_id = ?
            """,
            (run.shadow_run_id,),
        ).fetchone()
        if existing is not None:
            restored = self._shadow_run_from_row(existing)
            if restored != run:
                raise RulePackRevisionConflictError(
                    "shadow run identity has conflicting content"
                )
            return restored
        connection.execute(
            """
            INSERT INTO monitoring_rule_shadow_runs (
                shadow_run_id, project_id, rule_pack_id, batch_id,
                status, case_count, passed_count, failed_count,
                results_json, case_set_content_sha256,
                diagnostic_case_count, diagnostic_passed_count,
                diagnostic_failed_count, diagnostic_results_json,
                diagnostic_case_set_content_sha256,
                diagnostic_results_content_sha256,
                rule_coverages_json, family_coverages_json,
                coverage_content_sha256,
                completed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _json([asdict(item) for item in run.results]),
                run.case_set_content_sha256,
                run.diagnostic_case_count,
                run.diagnostic_passed_count,
                run.diagnostic_failed_count,
                _json(
                    [
                        asdict(item)
                        for item in run.diagnostic_results
                    ]
                ),
                run.diagnostic_case_set_content_sha256,
                run.diagnostic_results_content_sha256,
                _json(
                    [asdict(item) for item in run.rule_coverages]
                ),
                _json(
                    [asdict(item) for item in run.family_coverages]
                ),
                run.coverage_content_sha256,
                run.completed_at,
                _utc_now_text(),
            ),
        )
        self._event(
            connection,
            run.project_id,
            "rule_shadow_run",
            run.shadow_run_id,
            "completed",
            run.public_dict(),
        )
        return run

    def shadow_runs(
        self,
        project_id: str,
        *,
        rule_pack_id: str = "",
    ) -> tuple[RuleShadowRun, ...]:
        query = """
            SELECT * FROM monitoring_rule_shadow_runs
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if rule_pack_id:
            query += " AND rule_pack_id = ?"
            parameters.append(rule_pack_id)
        query += " ORDER BY completed_at, shadow_run_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._shadow_run_from_row(row) for row in rows)

    def store_shadow_sample_set(
        self,
        sample_set: ShadowProvisionalSampleSet,
    ) -> ShadowProvisionalSampleSet:
        with self._transaction() as connection:
            pack = connection.execute(
                """
                SELECT project_id, status
                FROM monitoring_rule_packs
                WHERE rule_pack_id = ?
                """,
                (sample_set.rule_pack_id,),
            ).fetchone()
            if pack is None:
                raise MonitoringProtocolRecordNotFound("rule pack not found")
            if pack["project_id"] != sample_set.project_id:
                raise RulePackPublicationError(
                    "shadow sample set rule pack belongs to another project"
                )
            if pack["status"] != "shadow":
                raise RulePackLifecycleError(
                    "shadow sample sets may be stored only for a "
                    "shadow-stage rule pack"
                )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_shadow_sample_sets
                WHERE sample_set_id = ?
                """,
                (sample_set.sample_set_id,),
            ).fetchone()
            if existing is not None:
                restored = self._shadow_sample_set_from_row(existing)
                if restored != sample_set:
                    raise RulePackRevisionConflictError(
                        "shadow sample set identity has conflicting content"
                    )
                return restored
            connection.execute(
                """
                INSERT INTO monitoring_shadow_sample_sets (
                    sample_set_id, project_id, rule_pack_id, batch_id,
                    batch_version, batch_revision, mapping_revision,
                    mapping_content_sha256, capability_manifest_sha256,
                    effective_capabilities_sha256, rule_revision_ids_json,
                    samples_json, content_sha256, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_set.sample_set_id,
                    sample_set.project_id,
                    sample_set.rule_pack_id,
                    sample_set.batch_id,
                    sample_set.batch_version,
                    sample_set.batch_revision,
                    sample_set.mapping_revision,
                    sample_set.mapping_content_sha256,
                    sample_set.capability_manifest_sha256,
                    sample_set.effective_capabilities_sha256,
                    _json(sample_set.rule_revision_ids),
                    _json(
                        [item.public_dict() for item in sample_set.samples]
                    ),
                    sample_set.content_sha256,
                    sample_set.created_by,
                    sample_set.created_at,
                ),
            )
            self._event(
                connection,
                sample_set.project_id,
                "shadow_sample_set",
                sample_set.sample_set_id,
                "stored",
                sample_set.public_dict(),
            )
        return sample_set

    def shadow_sample_set(
        self,
        sample_set_id: str,
    ) -> ShadowProvisionalSampleSet:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_shadow_sample_sets
                WHERE sample_set_id = ?
                """,
                (sample_set_id,),
            ).fetchone()
        if row is None:
            raise MonitoringProtocolRecordNotFound(
                "shadow sample set not found"
            )
        return self._shadow_sample_set_from_row(row)

    def shadow_sample_sets(
        self,
        project_id: str,
        *,
        rule_pack_id: str = "",
    ) -> tuple[ShadowProvisionalSampleSet, ...]:
        query = """
            SELECT * FROM monitoring_shadow_sample_sets
            WHERE project_id = ?
        """
        parameters: list[Any] = [project_id]
        if rule_pack_id:
            query += " AND rule_pack_id = ?"
            parameters.append(rule_pack_id)
        query += " ORDER BY created_at, sample_set_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._shadow_sample_set_from_row(row) for row in rows)

    def store_shadow_sample_confirmation(
        self,
        confirmation: ShadowSampleMedicalConfirmation,
    ) -> ShadowSampleMedicalConfirmation:
        with self._transaction() as connection:
            return self._store_shadow_sample_confirmation(
                connection,
                confirmation,
            )

    def _store_shadow_sample_confirmation(
        self,
        connection: sqlite3.Connection,
        confirmation: ShadowSampleMedicalConfirmation,
    ) -> ShadowSampleMedicalConfirmation:
        set_row = connection.execute(
            """
            SELECT * FROM monitoring_shadow_sample_sets
            WHERE sample_set_id = ?
            """,
            (confirmation.sample_set_id,),
        ).fetchone()
        if set_row is None:
            raise MonitoringProtocolRecordNotFound(
                "shadow sample set not found"
            )
        sample_set = self._shadow_sample_set_from_row(set_row)
        if (
            sample_set.project_id != confirmation.project_id
            or sample_set.rule_pack_id != confirmation.rule_pack_id
        ):
            raise RulePackPublicationError(
                "shadow sample confirmation binds another project "
                "or rule pack"
            )
        if (
            sample_set.content_sha256
            != confirmation.sample_set_content_sha256
        ):
            raise RulePackRevisionConflictError(
                "shadow sample confirmation does not match the stored "
                "sample set content"
            )
        run_row = connection.execute(
            """
            SELECT project_id, rule_pack_id
            FROM monitoring_rule_shadow_runs
            WHERE shadow_run_id = ?
            """,
            (confirmation.trusted_shadow_run_id,),
        ).fetchone()
        if run_row is None:
            raise MonitoringProtocolRecordNotFound(
                "trusted shadow run not found"
            )
        if (
            run_row["project_id"] != confirmation.project_id
            or run_row["rule_pack_id"] != confirmation.rule_pack_id
        ):
            raise RulePackPublicationError(
                "shadow sample confirmation trusted run belongs to "
                "another project or rule pack"
            )
        existing = connection.execute(
            """
            SELECT * FROM monitoring_shadow_sample_confirmations
            WHERE confirmation_id = ?
            """,
            (confirmation.confirmation_id,),
        ).fetchone()
        if existing is not None:
            restored = self._shadow_sample_confirmation_from_row(existing)
            if restored != confirmation:
                raise RulePackRevisionConflictError(
                    "shadow sample confirmation identity has "
                    "conflicting content"
                )
            return restored
        connection.execute(
            """
            INSERT INTO monitoring_shadow_sample_confirmations (
                confirmation_id, project_id, rule_pack_id, sample_set_id,
                sample_set_content_sha256, trusted_shadow_run_id,
                confirmed_by, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                confirmation.confirmation_id,
                confirmation.project_id,
                confirmation.rule_pack_id,
                confirmation.sample_set_id,
                confirmation.sample_set_content_sha256,
                confirmation.trusted_shadow_run_id,
                confirmation.confirmed_by,
                confirmation.confirmed_at,
            ),
        )
        self._event(
            connection,
            confirmation.project_id,
            "shadow_sample_confirmation",
            confirmation.confirmation_id,
            "confirmed",
            confirmation.public_dict(),
        )
        return confirmation

    def shadow_sample_confirmation(
        self,
        project_id: str,
        rule_pack_id: str,
    ) -> ShadowSampleMedicalConfirmation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_shadow_sample_confirmations
                WHERE project_id = ? AND rule_pack_id = ?
                ORDER BY confirmed_at, confirmation_id
                LIMIT 1
                """,
                (project_id, rule_pack_id),
            ).fetchone()
        if row is None:
            return None
        return self._shadow_sample_confirmation_from_row(row)

    def shadow_sample_confirmation_by_id(
        self,
        confirmation_id: str,
    ) -> ShadowSampleMedicalConfirmation:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_shadow_sample_confirmations
                WHERE confirmation_id = ?
                """,
                (confirmation_id,),
            ).fetchone()
        if row is None:
            raise MonitoringProtocolRecordNotFound(
                "shadow sample confirmation not found"
            )
        return self._shadow_sample_confirmation_from_row(row)

    @staticmethod
    def _shadow_sample_set_from_row(
        row: sqlite3.Row,
    ) -> ShadowProvisionalSampleSet:
        try:
            def text(value: Any, field: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise MonitoringProtocolRuleRepositoryError(
                        f"persisted shadow sample set {field} is invalid"
                    )
                return value

            def digest(value: Any, field: str, *, required: bool = True) -> str:
                raw = value if isinstance(value, str) else ""
                if raw != raw.strip():
                    raise MonitoringProtocolRuleRepositoryError(
                        f"persisted shadow sample set {field} is invalid"
                    )
                if not raw:
                    if required:
                        raise MonitoringProtocolRuleRepositoryError(
                            f"persisted shadow sample set {field} is invalid"
                        )
                    return raw
                if len(raw) != 64 or any(
                    character not in "0123456789abcdef" for character in raw
                ):
                    raise MonitoringProtocolRuleRepositoryError(
                        f"persisted shadow sample set {field} is not canonical"
                    )
                return raw

            sample_set_id = text(row["sample_set_id"], "sample_set_id")
            project_id = text(row["project_id"], "project_id")
            rule_pack_id = text(row["rule_pack_id"], "rule_pack_id")
            batch_id = text(row["batch_id"], "batch_id")
            batch_version = row["batch_version"]
            if (
                isinstance(batch_version, bool)
                or not isinstance(batch_version, int)
                or batch_version < 1
            ):
                raise MonitoringProtocolRuleRepositoryError(
                    "persisted shadow sample set batch_version is invalid"
                )
            batch_revision = text(row["batch_revision"], "batch_revision")
            mapping_revision = text(row["mapping_revision"], "mapping_revision")
            mapping_content_sha256 = digest(
                row["mapping_content_sha256"],
                "mapping_content_sha256",
            )
            capability_manifest_sha256 = digest(
                row["capability_manifest_sha256"],
                "capability_manifest_sha256",
            )
            effective_capabilities_sha256 = digest(
                row["effective_capabilities_sha256"],
                "effective_capabilities_sha256",
                required=False,
            )
            content_sha256 = digest(row["content_sha256"], "content_sha256")
            created_by = text(row["created_by"], "created_by")
            created_at = text(row["created_at"], "created_at")
            datetime.fromisoformat(created_at)

            raw_revision_ids = _loads(row["rule_revision_ids_json"])
            if (
                not isinstance(raw_revision_ids, list)
                or not raw_revision_ids
                or any(
                    not isinstance(item, str)
                    or not item
                    or item.strip() != item
                    for item in raw_revision_ids
                )
                or len(raw_revision_ids) != len(set(raw_revision_ids))
            ):
                raise MonitoringProtocolRuleRepositoryError(
                    "persisted shadow sample set rule revision ids are invalid"
                )

            raw_samples = _loads(row["samples_json"])
            if not isinstance(raw_samples, list) or not raw_samples:
                raise MonitoringProtocolRuleRepositoryError(
                    "persisted shadow sample set samples are invalid"
                )
            samples: list[ShadowProvisionalSample] = []
            for item in raw_samples:
                if not isinstance(item, dict):
                    raise MonitoringProtocolRuleRepositoryError(
                        "persisted shadow sample set sample payload is invalid"
                    )
                payload = dict(item)
                stored_sample_id = payload.pop("sample_id", None)
                if (
                    not isinstance(stored_sample_id, str)
                    or not stored_sample_id
                    or stored_sample_id.strip() != stored_sample_id
                ):
                    raise MonitoringProtocolRuleRepositoryError(
                        "persisted shadow sample set sample identity is invalid"
                    )
                sample = ShadowProvisionalSample.create(**payload)
                if sample.sample_id != stored_sample_id:
                    raise MonitoringProtocolRuleRepositoryError(
                        "stored shadow sample does not match its declared identity"
                    )
                samples.append(sample)
            restored = ShadowProvisionalSampleSet.create(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                batch_id=batch_id,
                batch_version=batch_version,
                batch_revision=batch_revision,
                mapping_revision=mapping_revision,
                mapping_content_sha256=mapping_content_sha256,
                capability_manifest_sha256=capability_manifest_sha256,
                effective_capabilities_sha256=effective_capabilities_sha256,
                rule_revision_ids=raw_revision_ids,
                samples=samples,
                created_by=created_by,
                created_at=created_at,
            )
            if (
                restored.sample_set_id != sample_set_id
                or restored.content_sha256 != content_sha256
            ):
                raise MonitoringProtocolRuleRepositoryError(
                    "stored shadow sample set does not match its declared identity"
                )
            return restored
        except MonitoringProtocolRuleRepositoryError:
            raise
        except (KeyError, TypeError, ValueError, MonitoringProtocolRuleError) as exc:
            raise MonitoringProtocolRuleRepositoryError(
                "persisted shadow sample set is invalid"
            ) from exc

    @staticmethod
    def _shadow_sample_confirmation_from_row(
        row: sqlite3.Row,
    ) -> ShadowSampleMedicalConfirmation:
        try:
            def text(value: Any, field: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise MonitoringProtocolRuleRepositoryError(
                        f"persisted shadow sample confirmation {field} is invalid"
                    )
                return value

            def digest(value: Any) -> str:
                raw = value if isinstance(value, str) else ""
                if len(raw) != 64 or any(
                    character not in "0123456789abcdef" for character in raw
                ):
                    raise MonitoringProtocolRuleRepositoryError(
                        "persisted shadow sample confirmation hash is not canonical"
                    )
                return raw

            confirmation_id = text(row["confirmation_id"], "confirmation_id")
            project_id = text(row["project_id"], "project_id")
            rule_pack_id = text(row["rule_pack_id"], "rule_pack_id")
            sample_set_id = text(row["sample_set_id"], "sample_set_id")
            sample_set_content_sha256 = digest(
                row["sample_set_content_sha256"]
            )
            trusted_shadow_run_id = text(
                row["trusted_shadow_run_id"],
                "trusted_shadow_run_id",
            )
            confirmed_by = text(row["confirmed_by"], "confirmed_by")
            confirmed_at = text(row["confirmed_at"], "confirmed_at")
            datetime.fromisoformat(confirmed_at)
            restored = ShadowSampleMedicalConfirmation.create(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                sample_set_id=sample_set_id,
                sample_set_content_sha256=sample_set_content_sha256,
                trusted_shadow_run_id=trusted_shadow_run_id,
                confirmed_by=confirmed_by,
                confirmed_at=confirmed_at,
            )
            if restored.confirmation_id != confirmation_id:
                raise MonitoringProtocolRuleRepositoryError(
                    "stored shadow sample confirmation does not match its "
                    "declared identity"
                )
            return restored
        except MonitoringProtocolRuleRepositoryError:
            raise
        except (KeyError, TypeError, ValueError, MonitoringProtocolRuleError) as exc:
            raise MonitoringProtocolRuleRepositoryError(
                "persisted shadow sample confirmation is invalid"
            ) from exc

    def integrity_check(self) -> str:
        with self._connect() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return str(result)

    def store_trusted_risk_binding(
        self,
        binding: RuleRiskBinding,
    ) -> RuleRiskBinding:
        return self.store_trusted_risk_bindings((binding,))[0]

    def store_trusted_risk_bindings(
        self,
        bindings: Sequence[RuleRiskBinding],
    ) -> tuple[RuleRiskBinding, ...]:
        normalized = tuple(self._normalize_risk_binding(item) for item in bindings)
        with self._transaction() as connection:
            for binding in normalized:
                self._validate_risk_binding_rule(connection, binding)
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO monitoring_trusted_rule_risk_bindings (
                        project_id, risk_instance_id, rule_key,
                        evaluated_rule_revision_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        binding.project_id,
                        binding.risk_instance_id,
                        binding.rule_key,
                        binding.evaluated_rule_revision_id,
                        _utc_now_text(),
                    ),
                )
                if inserted.rowcount == 1:
                    self._event(
                        connection,
                        binding.project_id,
                        "trusted_rule_risk_binding",
                        binding.risk_instance_id,
                        "registered",
                        asdict(binding),
                    )
        return normalized

    def has_trusted_risk_binding(self, binding: RuleRiskBinding) -> bool:
        normalized = self._normalize_risk_binding(binding)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM monitoring_trusted_rule_risk_bindings b
                JOIN monitoring_rule_definitions d
                  ON d.rule_revision_id = b.evaluated_rule_revision_id
                WHERE b.project_id = ?
                  AND b.risk_instance_id = ?
                  AND b.rule_key = ?
                  AND b.evaluated_rule_revision_id = ?
                  AND d.project_id = b.project_id
                  AND d.rule_key = b.rule_key
                """,
                (
                    normalized.project_id,
                    normalized.risk_instance_id,
                    normalized.rule_key,
                    normalized.evaluated_rule_revision_id,
                ),
            ).fetchone()
        return row is not None

    def _insert_rule_pack_record(
        self,
        connection: sqlite3.Connection,
        pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
        *,
        predecessor_rule_pack_id: str,
        actor: str,
        transition_at: str,
        shadow_run_id: str,
    ) -> None:
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
                pack.rule_pack_id,
                pack.project_id,
                pack.protocol_version_id,
                pack.pack_revision,
                pack.status,
                pack.applicability_status,
                pack.content_sha256,
                pack.created_by,
                pack.retrospective_policy,
                pack.published_at,
                transition_at,
            ),
        )
        for rule in rules:
            facts = self._facts_by_id(connection, rule.fact_revision_ids)
            if set(facts) != set(rule.fact_revision_ids):
                raise RulePackPublicationError(
                    "rule pack snapshot references missing protocol facts"
                )
            connection.execute(
                """
                INSERT INTO monitoring_rule_pack_items (
                    rule_pack_id, rule_revision_id, rule_key,
                    rule_status_snapshot, rule_state_version_snapshot,
                    fact_statuses_json, fact_state_versions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack.rule_pack_id,
                    rule.rule_revision_id,
                    rule.rule_key,
                    rule.status,
                    rule.state_version,
                    _json(
                        {
                            fact_id: facts[fact_id].status
                            for fact_id in sorted(facts)
                        }
                    ),
                    _json(
                        {
                            fact_id: facts[fact_id].state_version
                            for fact_id in sorted(facts)
                        }
                    ),
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
                pack.rule_pack_id,
                _STRICT_LIFECYCLE_VERSION,
                predecessor_rule_pack_id,
                actor,
                transition_at,
                shadow_run_id,
            ),
        )
        self._event(
            connection,
            pack.project_id,
            "rule_pack",
            pack.rule_pack_id,
            "stored",
            pack.public_dict(),
        )
        self._event(
            connection,
            pack.project_id,
            "rule_pack_lifecycle",
            pack.rule_pack_id,
            "stage_created",
            {
                "stage": pack.status,
                "pack_revision": pack.pack_revision,
                "predecessor_rule_pack_id": predecessor_rule_pack_id,
                "actor": actor,
                "transition_at": transition_at,
                "shadow_run_id": shadow_run_id,
                "lifecycle_version": _STRICT_LIFECYCLE_VERSION,
            },
        )

    def _replay_advanced_stage(
        self,
        connection: sqlite3.Connection,
        predecessor: MonitoringRulePack,
        *,
        target_status: str,
        shadow_run_id: str,
    ) -> MonitoringRulePack | None:
        """Return the already-recorded successor when this transition replayed.

        Returns None when the predecessor has no single direct successor that
        proves this exact transition already happened; callers then keep the
        existing strict error behavior.
        """
        rows = connection.execute(
            """
            SELECT p.*, l.shadow_run_id AS lifecycle_shadow_run_id
            FROM monitoring_rule_pack_lifecycle l
            JOIN monitoring_rule_packs p
              ON p.rule_pack_id = l.rule_pack_id
            WHERE l.predecessor_rule_pack_id = ?
            """,
            (predecessor.rule_pack_id,),
        ).fetchall()
        if len(rows) != 1:
            return None
        if rows[0]["project_id"] != predecessor.project_id:
            raise RulePackRevisionConflictError(
                "rule pack successor belongs to another project"
            )
        if rows[0]["protocol_version_id"] != predecessor.protocol_version_id:
            raise RulePackRevisionConflictError(
                "rule pack successor belongs to another protocol version"
            )
        successor = self._pack_from_row(rows[0], connection)
        if successor.project_id != predecessor.project_id:
            raise RulePackRevisionConflictError(
                "rule pack successor belongs to another project"
            )
        if successor.status != target_status:
            return None
        if tuple(sorted(successor.rule_revision_ids)) != tuple(
            sorted(predecessor.rule_revision_ids)
        ):
            return None
        if target_status == "confirmed":
            recorded = str(rows[0]["lifecycle_shadow_run_id"] or "").strip()
            requested = str(shadow_run_id or "").strip()
            if recorded != requested:
                raise RulePackRevisionConflictError(
                    "shadow confirmation was already recorded with a "
                    "different shadow run"
                )
        return successor

    def _assert_latest_pack_for_rule_set(
        self,
        connection: sqlite3.Connection,
        predecessor: MonitoringRulePack,
    ) -> None:
        rows = connection.execute(
            """
            SELECT * FROM monitoring_rule_packs
            WHERE project_id = ?
            ORDER BY pack_revision DESC
            """,
            (predecessor.project_id,),
        ).fetchall()
        expected_ids = tuple(sorted(predecessor.rule_revision_ids))
        for row in rows:
            candidate = self._pack_from_row(row, connection)
            if tuple(sorted(candidate.rule_revision_ids)) != expected_ids:
                continue
            if candidate.rule_pack_id != predecessor.rule_pack_id:
                raise RulePackLifecycleError(
                    "predecessor is not the latest project pack for this rule revision set"
                )
            return
        raise RulePackLifecycleError("predecessor rule revision set was not found")

    def _assert_rules_bind_confirmed_facts(
        self,
        connection: sqlite3.Connection,
        pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
    ) -> None:
        fact_ids = {
            fact_id for rule in rules for fact_id in rule.fact_revision_ids
        }
        facts = self._facts_by_id(connection, fact_ids)
        if set(facts) != fact_ids:
            raise RulePackPublicationError(
                "rule pack references missing protocol facts"
            )
        for fact in facts.values():
            if (
                fact.project_id != pack.project_id
                or fact.protocol_version_id != pack.protocol_version_id
            ):
                raise RulePackPublicationError(
                    "rule pack references a fact outside its project or protocol version"
                )
            if fact.status != "medically_confirmed":
                raise RulePackPublicationError(
                    "rule pack lifecycle requires medically confirmed facts"
                )
        for rule in rules:
            validate_rule_field_lineage(
                field_lineage=dict(rule.field_lineage),
                preconditions=rule.preconditions,
                trigger_expression=rule.trigger_expression,
                exclusions=rule.exclusions,
                evidence_template=rule.evidence_template,
                required_domains=rule.required_domains,
            )

    def _validate_release_shadow_evidence(
        self,
        connection: sqlite3.Connection,
        confirmed_pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
    ) -> str:
        if confirmed_pack.status != "confirmed":
            raise RulePackLifecycleError(
                "release evidence must be validated from a confirmed pack"
            )
        lifecycle = connection.execute(
            """
            SELECT * FROM monitoring_rule_pack_lifecycle
            WHERE rule_pack_id = ?
            """,
            (confirmed_pack.rule_pack_id,),
        ).fetchone()
        if (
            lifecycle is None
            or int(lifecycle["lifecycle_version"]) != _STRICT_LIFECYCLE_VERSION
            or _sqlite_bool(lifecycle["legacy_read_only"], "legacy_read_only")
            or not lifecycle["shadow_run_id"]
            or not lifecycle["predecessor_rule_pack_id"]
        ):
            raise RulePackLifecycleError(
                "confirmed pack is missing frozen strict shadow evidence"
            )
        shadow_row = connection.execute(
            "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
            (lifecycle["predecessor_rule_pack_id"],),
        ).fetchone()
        if shadow_row is None:
            raise RulePackLifecycleError(
                "confirmed pack shadow predecessor is missing"
            )
        shadow_pack = self._pack_from_row(shadow_row, connection)
        if (
            shadow_pack.status != "shadow"
            or shadow_pack.project_id != confirmed_pack.project_id
            or tuple(sorted(shadow_pack.rule_revision_ids))
            != tuple(sorted(confirmed_pack.rule_revision_ids))
        ):
            raise RulePackLifecycleError(
                "confirmed pack shadow predecessor does not match its rule set"
            )
        self._validate_shadow_evidence(
            connection,
            shadow_pack,
            rules,
            lifecycle["shadow_run_id"],
        )
        release_run_row = connection.execute(
            """
            SELECT * FROM monitoring_rule_shadow_runs
            WHERE shadow_run_id = ?
            """,
            (lifecycle["shadow_run_id"],),
        ).fetchone()
        if release_run_row is None:
            raise RulePackLifecycleError(
                "confirmed pack shadow evidence is missing"
            )
        self._assert_release_coverage(
            self._shadow_run_from_row(release_run_row)
        )
        return str(lifecycle["shadow_run_id"])

    def _validate_shadow_run_cases(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        rule_pack_id: str,
        results: Sequence[RuleShadowCaseResult],
    ) -> tuple[RuleGoldStandardCase, ...]:
        pack_rules = {
            row["rule_key"]: row["rule_revision_id"]
            for row in connection.execute(
                """
                SELECT rule_key, rule_revision_id
                FROM monitoring_rule_pack_items
                WHERE rule_pack_id = ?
                """,
                (rule_pack_id,),
            ).fetchall()
        }
        case_ids = tuple(result.case_id for result in results)
        if not case_ids:
            raise RulePackLifecycleError("shadow evidence requires registered cases")
        rows = connection.execute(
            f"""
            SELECT *
            FROM monitoring_rule_gold_cases
            WHERE case_id IN ({','.join('?' for _ in case_ids)})
            """,
            case_ids,
        ).fetchall()
        by_id = {row["case_id"]: row for row in rows}
        if set(by_id) != set(case_ids):
            raise RulePackLifecycleError(
                "shadow run contains unregistered or external cases"
            )
        for result in results:
            case_row = by_id[result.case_id]
            if (
                case_row["project_id"] != project_id
                or case_row["rule_key"] != result.rule_key
                or case_row["rule_revision_id"] != result.rule_revision_id
                or pack_rules.get(result.rule_key) != result.rule_revision_id
            ):
                raise RulePackLifecycleError(
                    "shadow run case does not belong to the exact pack rule revision"
                )
            expected_match = _sqlite_bool(
                case_row["expected_match"],
                "expected_match",
            )
            if (
                result.expected_match != expected_match
                or (
                    result.passed
                    and result.expected_match != result.actual_match
                )
            ):
                raise RulePackLifecycleError(
                    "shadow run result does not match its registered gold case outcome"
                )
        expected_rows = connection.execute(
            f"""
            SELECT *
            FROM monitoring_rule_gold_cases
            WHERE project_id = ?
              AND rule_revision_id IN (
                {','.join('?' for _ in pack_rules.values())}
              )
            """,
            (project_id, *pack_rules.values()),
        ).fetchall()
        expected_by_id = {row["case_id"]: row for row in expected_rows}
        if not expected_by_id or set(expected_by_id) != set(case_ids):
            raise RulePackLifecycleError(
                "shadow run must cover the complete current gold case set for the "
                "exact pack rule revisions"
            )
        cases = tuple(
            self._gold_case_from_row(expected_by_id[case_id])
            for case_id in sorted(expected_by_id)
        )
        for case in cases:
            self._validate_gold_case_release_binding(
                case,
                rule=self._rule_by_id(connection, case.rule_revision_id),
            )
        return cases

    def _validate_shadow_run_diagnostic_cases(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        rule_pack_id: str,
        results: Sequence[RuleShadowDiagnosticResult],
    ) -> tuple[RuleDiagnosticCase, ...]:
        pack_rules = {
            row["rule_key"]: row["rule_revision_id"]
            for row in connection.execute(
                """
                SELECT rule_key, rule_revision_id
                FROM monitoring_rule_pack_items
                WHERE rule_pack_id = ?
                """,
                (rule_pack_id,),
            ).fetchall()
        }
        case_ids = tuple(result.case_id for result in results)
        by_id: dict[str, sqlite3.Row] = {}
        if case_ids:
            rows = connection.execute(
                f"""
                SELECT *
                FROM monitoring_rule_diagnostic_cases
                WHERE case_id IN ({','.join('?' for _ in case_ids)})
                """,
                case_ids,
            ).fetchall()
            by_id = {row["case_id"]: row for row in rows}
            if set(by_id) != set(case_ids):
                raise RulePackLifecycleError(
                    "shadow run contains unregistered diagnostic cases"
                )
            for result in results:
                case_row = by_id[result.case_id]
                if (
                    case_row["project_id"] != project_id
                    or case_row["rule_key"] != result.rule_key
                    or case_row["rule_revision_id"]
                    != result.rule_revision_id
                    or pack_rules.get(result.rule_key)
                    != result.rule_revision_id
                    or case_row["expected_diagnostic_category"]
                    != result.expected_diagnostic_category
                    or case_row["expected_diagnostic_code"]
                    != result.expected_diagnostic_code
                ):
                    raise RulePackLifecycleError(
                        "shadow diagnostic result does not belong to the exact "
                        "pack rule revision or frozen expectation"
                    )
        expected_rows = connection.execute(
            f"""
            SELECT *
            FROM monitoring_rule_diagnostic_cases
            WHERE project_id = ?
              AND rule_revision_id IN (
                {','.join('?' for _ in pack_rules.values())}
              )
            """,
            (project_id, *pack_rules.values()),
        ).fetchall()
        expected_by_id = {row["case_id"]: row for row in expected_rows}
        if set(expected_by_id) != set(case_ids):
            raise RulePackLifecycleError(
                "shadow run must cover the complete current diagnostic case set "
                "for the exact pack rule revisions"
            )
        cases = tuple(
            self._diagnostic_case_from_row(expected_by_id[case_id])
            for case_id in sorted(expected_by_id)
        )
        for case in cases:
            self._validate_diagnostic_case_release_binding(
                case,
                rule=self._rule_by_id(connection, case.rule_revision_id),
            )
        return cases

    def _recompute_coverage_snapshots(
        self,
        connection: sqlite3.Connection,
        pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
        cases: Sequence[RuleGoldStandardCase],
        diagnostic_cases: Sequence[RuleDiagnosticCase],
        *,
        extra_family_gold_cases: Sequence[RuleGoldStandardCase] = (),
        extra_family_diagnostic_cases: Sequence[RuleDiagnosticCase] = (),
    ) -> tuple[
        tuple[RuleRevisionCoverageSnapshot, ...],
        tuple[RuleFamilyCoverageSnapshot, ...],
    ]:
        cases_by_revision: dict[str, list[RuleGoldStandardCase]] = {}
        for case in cases:
            cases_by_revision.setdefault(case.rule_revision_id, []).append(case)
        diagnostics_by_revision: dict[str, list[RuleDiagnosticCase]] = {}
        for case in diagnostic_cases:
            diagnostics_by_revision.setdefault(
                case.rule_revision_id,
                [],
            ).append(case)
        rule_coverages = tuple(
            RuleRevisionCoverageSnapshot(
                rule_key=rule.rule_key,
                rule_revision_id=rule.rule_revision_id,
                rule_family=rule.rule_family,
                positive_count=sum(
                    "positive" in case.coverage_labels
                    for case in cases_by_revision.get(
                        rule.rule_revision_id,
                        (),
                    )
                ),
                negative_count=sum(
                    "negative" in case.coverage_labels
                    for case in cases_by_revision.get(
                        rule.rule_revision_id,
                        (),
                    )
                ),
                boundary_count=sum(
                    "boundary" in case.coverage_labels
                    for case in cases_by_revision.get(
                        rule.rule_revision_id,
                        (),
                    )
                ),
                diagnostic_indeterminate_count=len(
                    diagnostics_by_revision.get(
                        rule.rule_revision_id,
                        (),
                    )
                ),
                authoritative_projects=tuple(
                    sorted(
                        {
                            case.project_id
                            for case in (
                                *cases_by_revision.get(
                                    rule.rule_revision_id,
                                    (),
                                ),
                                *diagnostics_by_revision.get(
                                    rule.rule_revision_id,
                                    (),
                                ),
                            )
                        }
                    )
                ),
            )
            for rule in sorted(
                rules,
                key=lambda item: item.rule_revision_id,
            )
        )
        families = sorted({rule.rule_family for rule in rules})
        family_coverages = tuple(
            RuleFamilyCoverageSnapshot(
                rule_family=rule_family,
                authoritative_projects=(
                    self._authoritative_projects_for_family(
                        connection,
                        rule_family,
                        extra_gold_cases=extra_family_gold_cases,
                        extra_diagnostic_cases=extra_family_diagnostic_cases,
                    )
                ),
            )
            for rule_family in families
        )
        return rule_coverages, family_coverages

    def _authoritative_projects_for_family(
        self,
        connection: sqlite3.Connection,
        rule_family: str,
        *,
        extra_gold_cases: Sequence[RuleGoldStandardCase] = (),
        extra_diagnostic_cases: Sequence[RuleDiagnosticCase] = (),
    ) -> tuple[str, ...]:
        gold_rows = connection.execute(
            """
            SELECT c.*
            FROM monitoring_rule_gold_cases c
            JOIN monitoring_rule_definitions d
              ON d.rule_revision_id = c.rule_revision_id
            WHERE d.rule_family = ?
              AND d.project_id = c.project_id
              AND d.rule_key = c.rule_key
            """,
            (rule_family,),
        ).fetchall()
        diagnostic_rows = connection.execute(
            """
            SELECT c.*
            FROM monitoring_rule_diagnostic_cases c
            JOIN monitoring_rule_definitions d
              ON d.rule_revision_id = c.rule_revision_id
            WHERE d.rule_family = ?
              AND d.project_id = c.project_id
              AND d.rule_key = c.rule_key
            """,
            (rule_family,),
        ).fetchall()
        gold_by_revision: dict[str, list[sqlite3.Row]] = {}
        for row in gold_rows:
            gold_by_revision.setdefault(
                str(row["rule_revision_id"]),
                [],
            ).append(row)
        diagnostics_by_revision: dict[str, list[sqlite3.Row]] = {}
        for row in diagnostic_rows:
            diagnostics_by_revision.setdefault(
                str(row["rule_revision_id"]),
                [],
            ).append(row)
        # Overlay caller-supplied (not yet persisted) cases so coverage can
        # be projected for the state the database will have after an atomic
        # commit; cases already persisted are skipped by identity.
        persisted_gold_ids = {str(row["case_id"]) for row in gold_rows}
        extra_gold_by_revision: dict[str, list[RuleGoldStandardCase]] = {}
        for case in extra_gold_cases:
            if case.case_id in persisted_gold_ids:
                continue
            extra_gold_by_revision.setdefault(
                case.rule_revision_id,
                [],
            ).append(case)
        persisted_diagnostic_ids = {
            str(row["case_id"]) for row in diagnostic_rows
        }
        extra_diagnostics_by_revision: dict[
            str, list[RuleDiagnosticCase]
        ] = {}
        for case in extra_diagnostic_cases:
            if case.case_id in persisted_diagnostic_ids:
                continue
            extra_diagnostics_by_revision.setdefault(
                case.rule_revision_id,
                [],
            ).append(case)

        projects: set[str] = set()
        revision_ids = sorted(
            set(gold_by_revision)
            | set(diagnostics_by_revision)
            | set(extra_gold_by_revision)
            | set(extra_diagnostics_by_revision)
        )
        for rule_revision_id in revision_ids:
            try:
                rule = self._rule_by_id(
                    connection,
                    rule_revision_id,
                )
                gold_cases = (
                    *(
                        self._gold_case_from_row(row)
                        for row in gold_by_revision.get(
                            rule_revision_id,
                            (),
                        )
                    ),
                    *extra_gold_by_revision.get(rule_revision_id, ()),
                )
                diagnostic_cases = (
                    *(
                        self._diagnostic_case_from_row(row)
                        for row in diagnostics_by_revision.get(
                            rule_revision_id,
                            (),
                        )
                    ),
                    *extra_diagnostics_by_revision.get(
                        rule_revision_id,
                        (),
                    ),
                )
                for case in gold_cases:
                    self._validate_gold_case_release_binding(
                        case,
                        rule=rule,
                    )
                for case in diagnostic_cases:
                    self._validate_diagnostic_case_release_binding(
                        case,
                        rule=rule,
                    )
            except RulePackLifecycleError:
                continue
            if (
                any("positive" in case.coverage_labels for case in gold_cases)
                and any(
                    "negative" in case.coverage_labels
                    for case in gold_cases
                )
                and any(
                    "boundary" in case.coverage_labels
                    for case in gold_cases
                )
                and diagnostic_cases
            ):
                projects.add(rule.project_id)
        return tuple(sorted(projects))

    @staticmethod
    def _assert_release_coverage(run: RuleShadowRun) -> None:
        if not run.rule_coverages or not run.coverage_content_sha256:
            raise RulePackLifecycleError(
                "legacy shadow run lacks P7C release coverage"
            )
        for coverage in run.rule_coverages:
            missing: list[str] = []
            if coverage.positive_count < 1:
                missing.append("positive")
            if coverage.negative_count < 1:
                missing.append("negative")
            if coverage.boundary_count < 1:
                missing.append("boundary")
            if coverage.diagnostic_indeterminate_count < 1:
                missing.append("diagnostic_indeterminate")
            if len(coverage.authoritative_projects) < 1:
                missing.append("authoritative_project")
            if missing:
                raise RulePackLifecycleError(
                    "rule revision is not release eligible; "
                    f"rule_revision_id={coverage.rule_revision_id}, "
                    f"missing={missing}"
                )
        family_by_name = {
            coverage.rule_family: coverage
            for coverage in run.family_coverages
        }
        for coverage in run.rule_coverages:
            if coverage.rule_family not in INITIAL_RELEASE_RULE_FAMILIES:
                continue
            family = family_by_name.get(coverage.rule_family)
            if family is None or len(family.authoritative_projects) < 2:
                raise RulePackLifecycleError(
                    "initial release rule_family requires at least two "
                    "authoritative projects; "
                    f"rule_family={coverage.rule_family}"
                )

    def _validate_shadow_evidence(
        self,
        connection: sqlite3.Connection,
        shadow_pack: MonitoringRulePack,
        rules: Sequence[MonitoringRuleDefinition],
        shadow_run_id: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT * FROM monitoring_rule_shadow_runs
            WHERE shadow_run_id = ?
            """,
            (shadow_run_id,),
        ).fetchone()
        if row is None:
            raise RulePackLifecycleError(
                "confirmed stage requires a repository-registered shadow run"
            )
        run = self._shadow_run_from_row(row)
        if (
            run.project_id != shadow_pack.project_id
            or run.rule_pack_id != shadow_pack.rule_pack_id
        ):
            raise RulePackLifecycleError(
                "shadow run belongs to another project or rule pack"
            )
        if (
            run.status != "completed"
            or run.case_count <= 0
            or run.case_count != len(run.results)
            or run.passed_count != run.case_count
            or run.failed_count != 0
            or any(not result.passed for result in run.results)
            or run.diagnostic_case_count != len(run.diagnostic_results)
            or run.diagnostic_passed_count != run.diagnostic_case_count
            or run.diagnostic_failed_count != 0
            or any(not result.passed for result in run.diagnostic_results)
        ):
            raise RulePackLifecycleError(
                "shadow run must contain at least one Boolean case and pass "
                "every case across the Boolean and diagnostic sets"
            )
        frozen_cases = self._validate_shadow_run_cases(
            connection,
            run.project_id,
            run.rule_pack_id,
            run.results,
        )
        expected_revisions = {
            rule.rule_key: rule.rule_revision_id for rule in rules
        }
        if any(
            case.rule_revision_id != expected_revisions.get(case.rule_key)
            for case in frozen_cases
        ):
            raise RulePackLifecycleError(
                "shadow run gold cases do not match the exact pack rule revisions"
            )
        if not run.case_set_content_sha256:
            raise RulePackLifecycleError(
                "legacy shadow run without a frozen case snapshot cannot be released"
            )
        if run.case_set_content_sha256 != gold_case_set_content_sha256(frozen_cases):
            raise RulePackLifecycleError(
                "shadow gold case set changed after validation"
            )
        frozen_diagnostic_cases = self._validate_shadow_run_diagnostic_cases(
            connection,
            run.project_id,
            run.rule_pack_id,
            run.diagnostic_results,
        )
        if (
            not run.diagnostic_case_set_content_sha256
            or run.diagnostic_case_set_content_sha256
            != diagnostic_case_set_content_sha256(
                frozen_diagnostic_cases
            )
        ):
            raise RulePackLifecycleError(
                "shadow diagnostic case set changed after validation"
            )
        if (
            not run.diagnostic_results_content_sha256
            or run.diagnostic_results_content_sha256
            != shadow_diagnostic_results_content_sha256(
                run.diagnostic_results
            )
        ):
            raise RulePackLifecycleError(
                "shadow diagnostic result set changed after validation"
            )
        expected_rule_coverages, expected_family_coverages = (
            self._recompute_coverage_snapshots(
                connection,
                shadow_pack,
                rules,
                frozen_cases,
                frozen_diagnostic_cases,
            )
        )
        if (
            run.rule_coverages != expected_rule_coverages
            or run.family_coverages != expected_family_coverages
            or not run.coverage_content_sha256
            or run.coverage_content_sha256
            != shadow_coverage_content_sha256(
                expected_rule_coverages,
                expected_family_coverages,
            )
        ):
            raise RulePackLifecycleError(
                "shadow coverage snapshot changed after validation"
            )

    def _rule_is_in_published_pack(
        self,
        connection: sqlite3.Connection,
        rule_revision_id: str,
    ) -> bool:
        return (
            connection.execute(
                """
                SELECT 1
                FROM monitoring_rule_pack_items i
                JOIN monitoring_rule_packs p
                  ON p.rule_pack_id = i.rule_pack_id
                WHERE i.rule_revision_id = ?
                  AND p.status = 'published'
                LIMIT 1
                """,
                (rule_revision_id,),
            ).fetchone()
            is not None
        )

    def _fact_is_bound_to_published_pack(
        self,
        connection: sqlite3.Connection,
        fact_revision_id: str,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT d.fact_revision_ids_json
            FROM monitoring_rule_pack_items i
            JOIN monitoring_rule_packs p
              ON p.rule_pack_id = i.rule_pack_id
            JOIN monitoring_rule_definitions d
              ON d.rule_revision_id = i.rule_revision_id
            WHERE p.status = 'published'
            """
        ).fetchall()
        return any(
            fact_revision_id in set(_loads(row["fact_revision_ids_json"]))
            for row in rows
        )

    def _assert_published_pack_integrity(
        self,
        connection: sqlite3.Connection,
        pack: MonitoringRulePack,
    ) -> tuple[MonitoringRuleDefinition, ...]:
        lifecycle = connection.execute(
            """
            SELECT * FROM monitoring_rule_pack_lifecycle
            WHERE rule_pack_id = ?
            """,
            (pack.rule_pack_id,),
        ).fetchone()
        if lifecycle is None:
            raise RulePackLifecycleError(
                "published rule pack is missing lifecycle metadata"
            )
        lifecycle_version = int(lifecycle["lifecycle_version"])
        if lifecycle_version not in {0, _STRICT_LIFECYCLE_VERSION}:
            raise RulePackLifecycleError(
                "published rule pack has an unsupported lifecycle version"
            )
        if lifecycle_version == _STRICT_LIFECYCLE_VERSION:
            if _sqlite_bool(lifecycle["legacy_read_only"], "legacy_read_only"):
                raise RulePackLifecycleError(
                    "strict published rule pack is unexpectedly read-only"
                )
            self._validate_strict_lifecycle_chain(connection, pack)

        snapshot_rules = self._rules_for_pack(connection, pack.rule_pack_id)
        current_rules = self._current_rules_for_pack(
            connection,
            pack.rule_pack_id,
        )
        expected_ids = tuple(sorted(pack.rule_revision_ids))
        if (
            tuple(sorted(rule.rule_revision_id for rule in snapshot_rules))
            != expected_ids
            or tuple(sorted(rule.rule_revision_id for rule in current_rules))
            != expected_ids
        ):
            raise RulePackLifecycleError(
                "published rule pack membership is incomplete"
            )
        if any(rule.status != "enabled" for rule in snapshot_rules):
            raise RulePackLifecycleError(
                "published rule pack snapshot contains a non-enabled rule"
            )
        if any(rule.status != "enabled" for rule in current_rules):
            raise RulePackLifecycleError(
                "published rule pack current rule state is not enabled"
            )
        for rule in current_rules:
            validate_rule_field_lineage(
                field_lineage=dict(rule.field_lineage),
                preconditions=rule.preconditions,
                trigger_expression=rule.trigger_expression,
                exclusions=rule.exclusions,
                evidence_template=rule.evidence_template,
                required_domains=rule.required_domains,
            )
        if lifecycle_version == _STRICT_LIFECYCLE_VERSION:
            confirmed_row = connection.execute(
                "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
                (lifecycle["predecessor_rule_pack_id"],),
            ).fetchone()
            if confirmed_row is None:
                raise RulePackLifecycleError(
                    "published pack confirmed predecessor is missing"
                )
            confirmed_pack = self._pack_from_row(confirmed_row, connection)
            shadow_run_id = self._validate_release_shadow_evidence(
                connection,
                confirmed_pack,
                current_rules,
            )
            if lifecycle["shadow_run_id"] != shadow_run_id:
                raise RulePackLifecycleError(
                    "published pack shadow evidence binding is inconsistent"
                )

        items = connection.execute(
            """
            SELECT * FROM monitoring_rule_pack_items
            WHERE rule_pack_id = ?
            """,
            (pack.rule_pack_id,),
        ).fetchall()
        item_by_rule = {row["rule_revision_id"]: row for row in items}
        for rule in current_rules:
            facts = self._facts_by_id(connection, rule.fact_revision_ids)
            if set(facts) != set(rule.fact_revision_ids):
                raise RulePackLifecycleError(
                    "published rule pack references missing facts"
                )
            for fact in facts.values():
                if (
                    fact.project_id != pack.project_id
                    or fact.protocol_version_id != pack.protocol_version_id
                    or fact.status != "medically_confirmed"
                ):
                    raise RulePackLifecycleError(
                        "published rule pack fact binding is no longer confirmed "
                        "or project-consistent"
                    )
            if lifecycle_version == _STRICT_LIFECYCLE_VERSION:
                item = item_by_rule[rule.rule_revision_id]
                snapshot_statuses = _loads(item["fact_statuses_json"])
                snapshot_versions = _loads(item["fact_state_versions_json"])
                if (
                    set(snapshot_statuses) != set(rule.fact_revision_ids)
                    or set(snapshot_versions) != set(rule.fact_revision_ids)
                    or any(
                        status != "medically_confirmed"
                        for status in snapshot_statuses.values()
                    )
                    or any(int(value) < 1 for value in snapshot_versions.values())
                ):
                    raise RulePackLifecycleError(
                        "published rule pack fact snapshot is invalid"
                    )

        rebuilt = MonitoringRulePack.create(
            project_id=pack.project_id,
            protocol_version_id=pack.protocol_version_id,
            pack_revision=pack.pack_revision,
            status=pack.status,
            applicability_status=pack.applicability_status,
            rules=snapshot_rules,
            created_by=pack.created_by,
            retrospective_policy=pack.retrospective_policy,
            published_at=pack.published_at,
            _lifecycle_authorized=True,
        )
        if (
            rebuilt.rule_pack_id != pack.rule_pack_id
            or rebuilt.content_sha256 != pack.content_sha256
        ):
            raise RulePackLifecycleError(
                "published rule pack content snapshot failed integrity validation"
            )
        return snapshot_rules

    def _validate_strict_lifecycle_chain(
        self,
        connection: sqlite3.Connection,
        terminal_pack: MonitoringRulePack,
    ) -> None:
        current = terminal_pack
        visited: set[str] = set()
        while True:
            if current.rule_pack_id in visited:
                raise RulePackLifecycleError("rule pack lifecycle contains a cycle")
            visited.add(current.rule_pack_id)
            lifecycle = connection.execute(
                """
                SELECT * FROM monitoring_rule_pack_lifecycle
                WHERE rule_pack_id = ?
                """,
                (current.rule_pack_id,),
            ).fetchone()
            if (
                lifecycle is None
                or int(lifecycle["lifecycle_version"])
                != _STRICT_LIFECYCLE_VERSION
                or _sqlite_bool(lifecycle["legacy_read_only"], "legacy_read_only")
            ):
                raise RulePackLifecycleError(
                    "strict lifecycle chain contains legacy or missing metadata"
                )
            if not lifecycle["transition_actor"] or not lifecycle["transition_at"]:
                raise RulePackLifecycleError(
                    "strict lifecycle stage is missing actor or transition time"
                )
            try:
                datetime.fromisoformat(lifecycle["transition_at"])
            except ValueError as exc:
                raise RulePackLifecycleError(
                    "strict lifecycle transition time is invalid"
                ) from exc
            if (
                current.status == "published"
                and current.published_at != lifecycle["transition_at"]
            ):
                raise RulePackLifecycleError(
                    "published lifecycle time does not match published_at"
                )
            self._assert_strict_pack_snapshot_integrity(
                connection,
                current,
            )
            predecessor_id = lifecycle["predecessor_rule_pack_id"]
            if current.status == "draft":
                if predecessor_id:
                    raise RulePackLifecycleError(
                        "draft lifecycle stage must not have a predecessor"
                    )
                return
            expected_predecessor = {
                "shadow": "draft",
                "confirmed": "shadow",
                "published": "confirmed",
            }.get(current.status)
            if expected_predecessor is None or not predecessor_id:
                raise RulePackLifecycleError(
                    "strict lifecycle stage has an invalid predecessor"
                )
            row = connection.execute(
                "SELECT * FROM monitoring_rule_packs WHERE rule_pack_id = ?",
                (predecessor_id,),
            ).fetchone()
            if row is None:
                raise RulePackLifecycleError(
                    "strict lifecycle predecessor is missing"
                )
            predecessor = self._pack_from_row(row, connection)
            if (
                predecessor.status != expected_predecessor
                or predecessor.project_id != current.project_id
                or predecessor.protocol_version_id != current.protocol_version_id
                or tuple(sorted(predecessor.rule_revision_ids))
                != tuple(sorted(current.rule_revision_ids))
                or predecessor.pack_revision >= current.pack_revision
            ):
                raise RulePackLifecycleError(
                    "strict lifecycle predecessor does not match stage, project, "
                    "protocol, rules, or revision ordering"
                )
            if current.status == "confirmed" and not lifecycle["shadow_run_id"]:
                raise RulePackLifecycleError(
                    "confirmed lifecycle stage is missing shadow evidence"
                )
            if current.status == "confirmed":
                shadow_row = connection.execute(
                    """
                    SELECT * FROM monitoring_rule_shadow_runs
                    WHERE shadow_run_id = ?
                    """,
                    (lifecycle["shadow_run_id"],),
                ).fetchone()
                if shadow_row is None:
                    raise RulePackLifecycleError(
                        "confirmed lifecycle shadow evidence is missing"
                    )
                shadow_run = self._shadow_run_from_row(shadow_row)
                if (
                    shadow_run.project_id != current.project_id
                    or shadow_run.rule_pack_id != predecessor.rule_pack_id
                    or shadow_run.case_count <= 0
                    or shadow_run.passed_count != shadow_run.case_count
                    or shadow_run.failed_count != 0
                    or any(not result.passed for result in shadow_run.results)
                ):
                    raise RulePackLifecycleError(
                        "confirmed lifecycle shadow evidence is invalid"
                    )
                self._validate_shadow_run_cases(
                    connection,
                    shadow_run.project_id,
                    shadow_run.rule_pack_id,
                    shadow_run.results,
                )
            current = predecessor

    def _assert_strict_pack_snapshot_integrity(
        self,
        connection: sqlite3.Connection,
        pack: MonitoringRulePack,
    ) -> None:
        rules = self._rules_for_pack(connection, pack.rule_pack_id)
        # A draft may legitimately snapshot recommendation-adopted rules
        # that were born confirmed (adoption is the medical decision);
        # later stages remain single-status.
        expected_statuses = {
            "draft": {"candidate", "confirmed"},
            "shadow": {"confirmed"},
            "confirmed": {"confirmed"},
            "published": {"enabled"},
        }.get(pack.status)
        if expected_statuses is None:
            raise RulePackLifecycleError(
                "strict lifecycle contains an unsupported rule pack stage"
            )
        if (
            tuple(sorted(rule.rule_revision_id for rule in rules))
            != tuple(sorted(pack.rule_revision_ids))
            or any(rule.status not in expected_statuses for rule in rules)
        ):
            raise RulePackLifecycleError(
                "strict lifecycle rule snapshot does not match its stage"
            )
        items = connection.execute(
            """
            SELECT * FROM monitoring_rule_pack_items
            WHERE rule_pack_id = ?
            """,
            (pack.rule_pack_id,),
        ).fetchall()
        item_by_rule = {row["rule_revision_id"]: row for row in items}
        for rule in rules:
            item = item_by_rule.get(rule.rule_revision_id)
            if item is None:
                raise RulePackLifecycleError(
                    "strict lifecycle rule snapshot item is missing"
                )
            fact_statuses = _loads(item["fact_statuses_json"])
            fact_versions = _loads(item["fact_state_versions_json"])
            if (
                set(fact_statuses) != set(rule.fact_revision_ids)
                or set(fact_versions) != set(rule.fact_revision_ids)
                or any(
                    status != "medically_confirmed"
                    for status in fact_statuses.values()
                )
                or any(int(value) < 1 for value in fact_versions.values())
            ):
                raise RulePackLifecycleError(
                    "strict lifecycle fact snapshot is invalid"
                )
        rebuilt = MonitoringRulePack.create(
            project_id=pack.project_id,
            protocol_version_id=pack.protocol_version_id,
            pack_revision=pack.pack_revision,
            status=pack.status,
            applicability_status=pack.applicability_status,
            rules=rules,
            created_by=pack.created_by,
            retrospective_policy=pack.retrospective_policy,
            published_at=pack.published_at,
            _lifecycle_authorized=True,
        )
        if (
            rebuilt.rule_pack_id != pack.rule_pack_id
            or rebuilt.content_sha256 != pack.content_sha256
        ):
            raise RulePackLifecycleError(
                "strict lifecycle rule pack snapshot failed content validation"
            )

    def _assert_applicability_does_not_overlap(
        self,
        connection: sqlite3.Connection,
        version: ProtocolSourceVersion,
        *,
        exclude_protocol_version_id: str = "",
    ) -> None:
        if version.applicability_status != "project_effective_confirmed":
            return
        rows = connection.execute(
            """
            SELECT s.operational_effective_from, s.operational_effective_to
            FROM monitoring_protocol_versions v
            JOIN monitoring_protocol_version_state s
              ON s.protocol_version_id = v.protocol_version_id
            WHERE v.project_id = ?
              AND s.status <> 'superseded'
              AND s.applicability_status = 'project_effective_confirmed'
              AND s.operational_effective_from <> ''
              AND v.protocol_version_id <> ?
            """,
            (version.project_id, exclude_protocol_version_id),
        ).fetchall()
        start = version.operational_effective_from
        end = version.operational_effective_to or "9999-12-31"
        for row in rows:
            other_start = row["operational_effective_from"]
            other_end = row["operational_effective_to"] or "9999-12-31"
            if start <= other_end and other_start <= end:
                raise ProtocolApplicabilityConflictError(
                    "confirmed project protocol applicability intervals overlap"
                )

    def _assert_assignment_does_not_overlap(
        self,
        connection: sqlite3.Connection,
        assignment: ProtocolApplicabilityAssignment,
        *,
        exclude_assignment_id: str = "",
    ) -> None:
        row = connection.execute(
            """
            SELECT a.assignment_id
            FROM monitoring_protocol_applicability_assignments a
            JOIN monitoring_protocol_applicability_assignment_state s
              ON s.assignment_id = a.assignment_id
            WHERE a.project_id = ?
              AND a.centre_id = ?
              AND a.subject_id = ?
              AND s.status = 'confirmed'
              AND a.assignment_id <> ?
              AND a.operational_effective_from <= ?
              AND a.operational_effective_to >= ?
            LIMIT 1
            """,
            (
                assignment.project_id,
                assignment.centre_id,
                assignment.subject_id,
                exclude_assignment_id,
                assignment.operational_effective_to,
                assignment.operational_effective_from,
            ),
        ).fetchone()
        if row is not None:
            raise ProtocolApplicabilityConflictError(
                "confirmed protocol applicability intervals overlap for the exact scope"
            )

    def _facts_by_id(
        self,
        connection: sqlite3.Connection,
        fact_ids: Iterable[str],
    ) -> dict[str, ProtocolFact]:
        requested = tuple(sorted(set(fact_ids)))
        if not requested:
            return {}
        rows = connection.execute(
            f"""
            SELECT * FROM monitoring_protocol_facts
            WHERE fact_revision_id IN ({','.join('?' for _ in requested)})
            """,
            requested,
        ).fetchall()
        return {
            row["fact_revision_id"]: self._fact_with_state(connection, row)
            for row in rows
        }

    def _rules_for_pack(
        self,
        connection: sqlite3.Connection,
        rule_pack_id: str,
    ) -> tuple[MonitoringRuleDefinition, ...]:
        rows = connection.execute(
            """
            SELECT d.*,
                   i.rule_status_snapshot AS pack_rule_status_snapshot,
                   i.rule_state_version_snapshot AS pack_rule_state_version_snapshot
            FROM monitoring_rule_pack_items i
            JOIN monitoring_rule_definitions d
              ON d.rule_revision_id = i.rule_revision_id
            WHERE i.rule_pack_id = ?
            ORDER BY i.rule_key
            """,
            (rule_pack_id,),
        ).fetchall()
        rules: list[MonitoringRuleDefinition] = []
        for row in rows:
            current = self._rule_with_state(connection, row)
            snapshot_status = row["pack_rule_status_snapshot"]
            if snapshot_status:
                current = replace(
                    current,
                    status=snapshot_status,
                    state_version=int(row["pack_rule_state_version_snapshot"]),
                )
            rules.append(current)
        return tuple(rules)

    def _current_rules_for_pack(
        self,
        connection: sqlite3.Connection,
        rule_pack_id: str,
    ) -> tuple[MonitoringRuleDefinition, ...]:
        rows = connection.execute(
            """
            SELECT d.*
            FROM monitoring_rule_pack_items i
            JOIN monitoring_rule_definitions d
              ON d.rule_revision_id = i.rule_revision_id
            WHERE i.rule_pack_id = ?
            ORDER BY i.rule_key
            """,
            (rule_pack_id,),
        ).fetchall()
        return tuple(self._rule_with_state(connection, row) for row in rows)

    def _rule_by_id(
        self,
        connection: sqlite3.Connection,
        rule_revision_id: str,
    ) -> MonitoringRuleDefinition:
        row = connection.execute(
            """
            SELECT * FROM monitoring_rule_definitions
            WHERE rule_revision_id = ?
            """,
            (rule_revision_id,),
        ).fetchone()
        if row is None:
            raise MonitoringProtocolRecordNotFound("rule definition not found")
        return self._rule_with_state(connection, row)

    @staticmethod
    def _normalize_risk_binding(binding: RuleRiskBinding) -> RuleRiskBinding:
        normalized = RuleRiskBinding(
            risk_instance_id=str(binding.risk_instance_id or "").strip(),
            project_id=str(binding.project_id or "").strip(),
            rule_key=str(binding.rule_key or "").strip().lower(),
            evaluated_rule_revision_id=str(
                binding.evaluated_rule_revision_id or ""
            ).strip(),
        )
        missing = [
            field_name
            for field_name, value in asdict(normalized).items()
            if not value
        ]
        if missing:
            raise TrustedRiskBindingConflictError(
                f"trusted risk binding requires: {', '.join(missing)}"
            )
        return normalized

    def _validate_gold_case_release_binding(
        self,
        case: RuleGoldStandardCase,
        *,
        rule: MonitoringRuleDefinition,
    ) -> None:
        required = {
            "rule_revision_id": case.rule_revision_id,
            "source_entry_id": case.source_entry_id,
            "source_content_sha256": case.source_content_sha256,
            "source_revision": case.source_revision,
            "batch_revision": case.batch_revision,
        }
        missing = sorted(name for name, value in required.items() if not str(value).strip())
        if not case.source_row_bindings:
            missing.append("source_row_bindings")
        elif any(not binding.field_bindings for binding in case.source_row_bindings):
            missing.append("source_row_field_bindings")
        if not case.coverage_labels:
            missing.append("coverage_labels")
        if missing:
            raise RulePackLifecycleError(
                "legacy or incomplete gold cases are not release eligible: "
                f"{missing}"
            )
        digest = case.source_content_sha256
        if (
            not isinstance(digest, str)
            or _RULE_PACK_IDENTITY_SHA256_RE.fullmatch(digest) is None
        ):
            raise RulePackLifecycleError(
                "gold standard case source_content_sha256 is invalid"
            )
        if not case.evidence_locators or any(
            not isinstance(locator, str) or digest not in locator
            for locator in case.evidence_locators
        ):
            raise RulePackLifecycleError(
                "gold standard case evidence locators must bind its source hash"
            )
        try:
            rebuilt = RuleGoldStandardCase.create(
                project_id=case.project_id,
                rule_key=case.rule_key,
                rule_revision_id=case.rule_revision_id,
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
                coverage_labels=case.coverage_labels,
                medical_rationale=case.medical_rationale,
                evidence_locators=case.evidence_locators,
                source_row_bindings=case.source_row_bindings,
            )
        except MonitoringProtocolRuleError as exc:
            raise RulePackLifecycleError(str(exc)) from exc
        if rebuilt.case_id != case.case_id:
            raise RulePackLifecycleError(
                "gold standard case_id does not match its immutable content"
            )
        if self._gold_case_authority is None:
            raise RulePackLifecycleError(
                "gold standard case authoritative source/batch validator is not configured"
            )
        try:
            self._gold_case_authority(case, rule)
        except RulePackLifecycleError:
            raise
        except Exception as exc:
            raise RulePackLifecycleError(str(exc)) from exc

    def _validate_diagnostic_case_release_binding(
        self,
        case: RuleDiagnosticCase,
        *,
        rule: MonitoringRuleDefinition,
    ) -> None:
        required = {
            "rule_revision_id": case.rule_revision_id,
            "source_entry_id": case.source_entry_id,
            "source_content_sha256": case.source_content_sha256,
            "source_revision": case.source_revision,
            "batch_revision": case.batch_revision,
            "expected_diagnostic_category": (
                case.expected_diagnostic_category
            ),
            "expected_diagnostic_code": case.expected_diagnostic_code,
        }
        missing = sorted(
            name for name, value in required.items() if not str(value).strip()
        )
        if not case.source_row_bindings:
            missing.append("source_row_bindings")
        elif any(
            not binding.field_bindings
            for binding in case.source_row_bindings
        ):
            missing.append("source_row_field_bindings")
        if missing:
            raise RulePackLifecycleError(
                "incomplete diagnostic cases are not release eligible: "
                f"{missing}"
            )
        digest = case.source_content_sha256
        if (
            not isinstance(digest, str)
            or _RULE_PACK_IDENTITY_SHA256_RE.fullmatch(digest) is None
        ):
            raise RulePackLifecycleError(
                "diagnostic case source_content_sha256 is invalid"
            )
        if not case.evidence_locators or any(
            not isinstance(locator, str) or digest not in locator
            for locator in case.evidence_locators
        ):
            raise RulePackLifecycleError(
                "diagnostic case evidence locators must bind its source hash"
            )
        try:
            rebuilt = RuleDiagnosticCase.create(
                project_id=case.project_id,
                rule_key=case.rule_key,
                rule_revision_id=case.rule_revision_id,
                source_entry_id=case.source_entry_id,
                source_content_sha256=case.source_content_sha256,
                source_revision=case.source_revision,
                batch_revision=case.batch_revision,
                case_label=case.case_label,
                input_record=case.input_record,
                previous_record=case.previous_record,
                related_records=case.related_records,
                observed_domains=case.observed_domains,
                expected_diagnostic_category=(
                    case.expected_diagnostic_category
                ),
                expected_diagnostic_code=case.expected_diagnostic_code,
                medical_rationale=case.medical_rationale,
                evidence_locators=case.evidence_locators,
                source_row_bindings=case.source_row_bindings,
            )
        except MonitoringProtocolRuleError as exc:
            raise RulePackLifecycleError(str(exc)) from exc
        if rebuilt.case_id != case.case_id:
            raise RulePackLifecycleError(
                "diagnostic case_id does not match its immutable content"
            )
        if self._gold_case_authority is None:
            raise RulePackLifecycleError(
                "diagnostic case authoritative source/batch validator is not configured"
            )
        try:
            self._gold_case_authority(case, rule)
        except RulePackLifecycleError:
            raise
        except Exception as exc:
            raise RulePackLifecycleError(str(exc)) from exc

    @staticmethod
    def _validate_risk_binding_rule(
        connection: sqlite3.Connection,
        binding: RuleRiskBinding,
    ) -> None:
        row = connection.execute(
            """
            SELECT project_id, rule_key
            FROM monitoring_rule_definitions
            WHERE rule_revision_id = ?
            """,
            (binding.evaluated_rule_revision_id,),
        ).fetchone()
        if row is None:
            raise MonitoringProtocolRecordNotFound(
                "trusted risk binding rule revision not found"
            )
        if (
            row["project_id"] != binding.project_id
            or row["rule_key"] != binding.rule_key
        ):
            raise TrustedRiskBindingConflictError(
                "trusted risk binding does not match rule project and rule_key"
            )

    def _pack_from_row(
        self,
        row: sqlite3.Row,
        connection: sqlite3.Connection,
    ) -> MonitoringRulePack:
        items = connection.execute(
            """
            SELECT rule_revision_id FROM monitoring_rule_pack_items
            WHERE rule_pack_id = ?
            ORDER BY rule_revision_id
            """,
            (row["rule_pack_id"],),
        ).fetchall()
        stored_rule_revision_ids = tuple(
            sorted(str(item["rule_revision_id"]) for item in items)
        )
        snapshot_rules = self._rules_for_pack(connection, row["rule_pack_id"])
        snapshot_rule_revision_ids = tuple(
            sorted(rule.rule_revision_id for rule in snapshot_rules)
        )
        if snapshot_rule_revision_ids != stored_rule_revision_ids:
            raise RulePackLifecycleError(
                "stored rule pack membership does not match its item snapshots"
            )
        # Preserve the existing legacy/identity gate: an identity-incomplete
        # pack is returned for the downstream readiness diagnostic rather than
        # being reclassified as a generic content-drift error here.
        if any(
            not str(getattr(rule, field, "") or "").strip()
            for rule in snapshot_rules
            for field in _RULE_PACK_IDENTITY_FIELDS
        ):
            return MonitoringRulePack(
                rule_pack_id=row["rule_pack_id"],
                project_id=row["project_id"],
                protocol_version_id=row["protocol_version_id"],
                pack_revision=int(row["pack_revision"]),
                status=row["status"],
                applicability_status=row["applicability_status"],
                rule_revision_ids=stored_rule_revision_ids,
                content_sha256=row["content_sha256"],
                created_by=row["created_by"],
                retrospective_policy=row["retrospective_policy"],
                published_at=row["published_at"],
            )
        try:
            rebuilt = MonitoringRulePack.create(
                project_id=row["project_id"],
                protocol_version_id=row["protocol_version_id"],
                pack_revision=int(row["pack_revision"]),
                status=row["status"],
                applicability_status=row["applicability_status"],
                rules=snapshot_rules,
                created_by=row["created_by"],
                retrospective_policy=row["retrospective_policy"],
                published_at=row["published_at"],
                _lifecycle_authorized=True,
            )
        except MonitoringProtocolRuleError as exc:
            raise RulePackLifecycleError(
                "stored rule pack snapshot is invalid"
            ) from exc
        if (
            rebuilt.rule_pack_id != row["rule_pack_id"]
            or rebuilt.content_sha256 != row["content_sha256"]
        ):
            raise RulePackLifecycleError(
                "stored rule pack identity or content hash mismatch"
            )
        return MonitoringRulePack(
            rule_pack_id=row["rule_pack_id"],
            project_id=row["project_id"],
            protocol_version_id=row["protocol_version_id"],
            pack_revision=int(row["pack_revision"]),
            status=row["status"],
            applicability_status=row["applicability_status"],
            rule_revision_ids=stored_rule_revision_ids,
            content_sha256=row["content_sha256"],
            created_by=row["created_by"],
            retrospective_policy=row["retrospective_policy"],
            published_at=row["published_at"],
        )

    @staticmethod
    def _protocol_version_immutable(version: ProtocolSourceVersion) -> dict[str, Any]:
        value = asdict(version)
        for key in (
            "status",
            "applicability_status",
            "operational_effective_from",
            "operational_effective_to",
            "state_version",
        ):
            value.pop(key, None)
        return value

    @staticmethod
    def _fact_immutable(fact: ProtocolFact) -> dict[str, Any]:
        value = asdict(fact)
        value.pop("status", None)
        value.pop("state_version", None)
        return value

    @staticmethod
    def _rule_immutable(rule: MonitoringRuleDefinition) -> dict[str, Any]:
        value = asdict(rule)
        value.pop("status", None)
        value.pop("state_version", None)
        return value

    @staticmethod
    def _protocol_state_payload(version: ProtocolSourceVersion) -> dict[str, Any]:
        return {
            "status": version.status,
            "applicability_status": version.applicability_status,
            "operational_effective_from": version.operational_effective_from,
            "operational_effective_to": version.operational_effective_to,
            "state_version": version.state_version,
        }

    @staticmethod
    def _validate_protocol_state(version: ProtocolSourceVersion) -> None:
        if version.status not in {"draft", "confirmed", "superseded"}:
            raise MonitoringProtocolStateConflictError(
                "invalid protocol version status"
            )
        if version.applicability_status not in {
            "version_date_only",
            "project_effective_confirmed",
            "site_specific",
        }:
            raise MonitoringProtocolStateConflictError(
                "invalid protocol applicability status"
            )
        for field_name, value in (
            ("operational_effective_from", version.operational_effective_from),
            ("operational_effective_to", version.operational_effective_to),
        ):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise MonitoringProtocolStateConflictError(
                        f"{field_name} must be an ISO date"
                    ) from exc
        if (
            version.applicability_status == "project_effective_confirmed"
            and not version.operational_effective_from
        ):
            raise MonitoringProtocolStateConflictError(
                "confirmed project applicability requires operational_effective_from"
            )
        if (
            version.operational_effective_from
            and version.operational_effective_to
            and version.operational_effective_to < version.operational_effective_from
        ):
            raise MonitoringProtocolStateConflictError(
                "operational_effective_to precedes operational_effective_from"
            )

    def _protocol_version_with_state(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> ProtocolSourceVersion:
        version = self._protocol_version_from_row(row)
        state = connection.execute(
            """
            SELECT * FROM monitoring_protocol_version_state
            WHERE protocol_version_id = ?
            """,
            (version.protocol_version_id,),
        ).fetchone()
        if state is None:
            return version
        return replace(
            version,
            status=state["status"],
            applicability_status=state["applicability_status"],
            operational_effective_from=state["operational_effective_from"],
            operational_effective_to=state["operational_effective_to"],
            state_version=int(state["state_version"]),
        )

    def _applicability_assignment_with_state(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> ProtocolApplicabilityAssignment:
        state = connection.execute(
            """
            SELECT * FROM monitoring_protocol_applicability_assignment_state
            WHERE assignment_id = ?
            """,
            (row["assignment_id"],),
        ).fetchone()
        assignment = ProtocolApplicabilityAssignment(
            assignment_id=row["assignment_id"],
            project_id=row["project_id"],
            protocol_version_id=row["protocol_version_id"],
            centre_id=row["centre_id"],
            subject_id=row["subject_id"],
            operational_effective_from=row["operational_effective_from"],
            operational_effective_to=row["operational_effective_to"],
            status=state["status"] if state is not None else "candidate",
            evidence_text=row["evidence_text"],
            evidence_source_content_sha256=row[
                "evidence_source_content_sha256"
            ],
            evidence_source_entry_id=row["evidence_source_entry_id"],
            evidence_locator=row["evidence_locator"],
            created_by=row["created_by"],
            state_version=1,
        )
        try:
            rebuilt = ProtocolApplicabilityAssignment.create(
                project_id=assignment.project_id,
                protocol_version_id=assignment.protocol_version_id,
                centre_id=assignment.centre_id,
                subject_id=assignment.subject_id,
                operational_effective_from=assignment.operational_effective_from,
                operational_effective_to=assignment.operational_effective_to,
                evidence_text=assignment.evidence_text,
                evidence_source_content_sha256=(
                    assignment.evidence_source_content_sha256
                ),
                evidence_source_entry_id=assignment.evidence_source_entry_id,
                evidence_locator=assignment.evidence_locator,
                created_by=assignment.created_by,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted protocol applicability assignment is invalid"
            ) from exc
        if rebuilt.assignment_id != assignment.assignment_id:
            raise MonitoringProtocolRuleError(
                "persisted protocol applicability assignment identity mismatch"
            )
        if state is None:
            return assignment
        return replace(
            assignment,
            status=state["status"],
            state_version=int(state["state_version"]),
        )

    def _fact_with_state(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> ProtocolFact:
        fact = self._fact_from_row(row)
        state = connection.execute(
            """
            SELECT * FROM monitoring_protocol_fact_state
            WHERE fact_revision_id = ?
            """,
            (fact.fact_revision_id,),
        ).fetchone()
        if state is None:
            return fact
        return replace(
            fact,
            status=state["status"],
            state_version=int(state["state_version"]),
        )

    def _rule_with_state(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> MonitoringRuleDefinition:
        rule = self._rule_from_row(row)
        state = connection.execute(
            """
            SELECT * FROM monitoring_rule_definition_state
            WHERE rule_revision_id = ?
            """,
            (rule.rule_revision_id,),
        ).fetchone()
        if state is None:
            return rule
        return replace(
            rule,
            status=state["status"],
            state_version=int(state["state_version"]),
        )

    @staticmethod
    def _protocol_version_from_row(row: sqlite3.Row) -> ProtocolSourceVersion:
        version = ProtocolSourceVersion(
            protocol_version_id=row["protocol_version_id"],
            project_id=row["project_id"],
            protocol_code=row["protocol_code"],
            version_label=row["version_label"],
            version_date=row["version_date"],
            source_entry_id=row["source_entry_id"],
            source_title=row["source_title"],
            content_sha256=row["content_sha256"],
            status=row["status"],
            applicability_status=row["applicability_status"],
            operational_effective_from=row["operational_effective_from"],
            operational_effective_to=row["operational_effective_to"],
            predecessor_version_id=row["predecessor_version_id"],
            amendment_source_entry_id=row["amendment_source_entry_id"],
            state_version=1,
        )
        try:
            rebuilt = ProtocolSourceVersion.create(
                project_id=version.project_id,
                protocol_code=version.protocol_code,
                version_label=version.version_label,
                version_date=version.version_date,
                source_entry_id=version.source_entry_id,
                source_title=version.source_title,
                content_sha256=version.content_sha256,
                status=version.status,
                applicability_status=version.applicability_status,
                operational_effective_from=version.operational_effective_from,
                operational_effective_to=version.operational_effective_to,
                predecessor_version_id=version.predecessor_version_id,
                amendment_source_entry_id=version.amendment_source_entry_id,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted protocol source version is invalid"
            ) from exc
        if (
            rebuilt.protocol_version_id != version.protocol_version_id
            or MonitoringProtocolRuleRepository._protocol_version_immutable(
                rebuilt
            )
            != MonitoringProtocolRuleRepository._protocol_version_immutable(
                version
            )
        ):
            raise MonitoringProtocolRuleError(
                "persisted protocol source version identity mismatch"
            )
        return version

    @staticmethod
    def _fact_from_row(row: sqlite3.Row) -> ProtocolFact:
        fact = ProtocolFact(
            fact_revision_id=row["fact_revision_id"],
            project_id=row["project_id"],
            protocol_version_id=row["protocol_version_id"],
            fact_key=row["fact_key"],
            fact_type=row["fact_type"],
            status=row["status"],
            title=row["title"],
            normalized_payload=_loads(row["normalized_payload_json"]),
            source_entry_id=row["source_entry_id"],
            source_locator=row["source_locator"],
            source_text=row["source_text"],
            source_text_sha256=row["source_text_sha256"],
            applicability=_loads(row["applicability_json"]),
            supersedes_fact_revision_id=row["supersedes_fact_revision_id"],
            clinical_domain=(
                row["clinical_domain"]
                if "clinical_domain" in row.keys() and row["clinical_domain"]
                else FACT_TYPE_CLINICAL_DOMAIN[row["fact_type"]]
            ),
            state_version=1,
        )
        try:
            rebuilt = ProtocolFact.create(
                project_id=fact.project_id,
                protocol_version_id=fact.protocol_version_id,
                fact_key=fact.fact_key,
                fact_type=fact.fact_type,
                status=fact.status,
                title=fact.title,
                normalized_payload=fact.normalized_payload,
                source_entry_id=fact.source_entry_id,
                source_locator=fact.source_locator,
                source_text=fact.source_text,
                applicability=fact.applicability,
                supersedes_fact_revision_id=fact.supersedes_fact_revision_id,
                clinical_domain=fact.clinical_domain,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted protocol fact is invalid"
            ) from exc
        if (
            rebuilt.fact_revision_id != fact.fact_revision_id
            or rebuilt.source_text_sha256 != fact.source_text_sha256
            or MonitoringProtocolRuleRepository._fact_immutable(rebuilt)
            != MonitoringProtocolRuleRepository._fact_immutable(fact)
        ):
            raise MonitoringProtocolRuleError(
                "persisted protocol fact source hash or identity mismatch"
            )
        return fact

    @staticmethod
    def _rule_from_row(row: sqlite3.Row) -> MonitoringRuleDefinition:
        fact_revision_ids = tuple(_loads(row["fact_revision_ids_json"]))
        source_refs_raw = (
            _loads(row["source_refs_json"])
            if "source_refs_json" in row.keys() and row["source_refs_json"]
            else []
        )
        if source_refs_raw:
            source_refs = tuple(
                RuleSourceReference.create(**item) for item in source_refs_raw
            )
        else:
            source_refs = tuple(
                RuleSourceReference.create(
                    fact_revision_id=fact_revision_id,
                    source_entry_id=row["source_entry_id"],
                    source_locator=row["source_locator"],
                    source_text=row["source_text"],
                    source_text_sha256=row["source_text_sha256"],
                )
                for fact_revision_id in fact_revision_ids
            )
        inferred_domains = RULE_FAMILY_CLINICAL_DOMAINS[row["rule_family"]]
        clinical_domain = (
            row["clinical_domain"]
            if "clinical_domain" in row.keys() and row["clinical_domain"]
            else (
                next(iter(inferred_domains))
                if len(inferred_domains) == 1
                else "data_quality"
            )
        )
        rule = MonitoringRuleDefinition(
            rule_revision_id=row["rule_revision_id"],
            project_id=row["project_id"],
            protocol_version_id=row["protocol_version_id"],
            rule_key=row["rule_key"],
            rule_family=row["rule_family"],
            status=row["status"],
            title=row["title"],
            executor=row["executor"],
            required_domains=tuple(_loads(row["required_domains_json"])),
            preconditions=_loads(row["preconditions_json"]),
            trigger_expression=_loads(row["trigger_expression_json"]),
            exclusions=_loads(row["exclusions_json"]),
            severity=row["severity"],
            confidence=row["confidence"],
            evidence_template=row["evidence_template"],
            fact_revision_ids=fact_revision_ids,
            source_entry_id=row["source_entry_id"],
            source_locator=row["source_locator"],
            source_text=row["source_text"],
            source_text_sha256=row["source_text_sha256"],
            supersedes_rule_revision_id=row["supersedes_rule_revision_id"],
            clinical_domain=clinical_domain,
            source_refs=source_refs,
            field_lineage=(
                _loads(row["field_lineage_json"])
                if "field_lineage_json" in row.keys()
                and row["field_lineage_json"]
                else {}
            ),
            mapping_revision=(
                row["mapping_revision"]
                if "mapping_revision" in row.keys() and row["mapping_revision"]
                else ""
            ),
            mapping_content_sha256=(
                row["mapping_content_sha256"]
                if "mapping_content_sha256" in row.keys()
                and row["mapping_content_sha256"]
                else ""
            ),
            capability_manifest_sha256=(
                row["capability_manifest_sha256"]
                if "capability_manifest_sha256" in row.keys()
                and row["capability_manifest_sha256"]
                else ""
            ),
            effective_capabilities_sha256=(
                row["effective_capabilities_sha256"]
                if "effective_capabilities_sha256" in row.keys()
                and row["effective_capabilities_sha256"]
                else ""
            ),
            recommendation_candidate_id=(
                row["recommendation_candidate_id"]
                if "recommendation_candidate_id" in row.keys()
                and row["recommendation_candidate_id"]
                else ""
            ),
            state_version=1,
        )
        identity_values = tuple(
            str(getattr(rule, field, "") or "").strip()
            for field in _RULE_PACK_IDENTITY_FIELDS
        )
        # Preserve the established downstream diagnostic for legacy/partial
        # mapping identity; the readiness gate must name that gap precisely.
        # Complete identity is the opt-in for strict read-side revalidation.
        if not all(identity_values):
            return rule
        expected_source_sha256 = sha256(
            rule.source_text.encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(rule.source_text_sha256, str)
            or _RULE_PACK_IDENTITY_SHA256_RE.fullmatch(
                rule.source_text_sha256
            ) is None
            or rule.source_text_sha256 != expected_source_sha256
        ):
            raise MonitoringProtocolRuleError(
                "persisted monitoring rule source hash or identity mismatch"
            )
        try:
            rebuilt = MonitoringRuleDefinition.create(
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
                supersedes_rule_revision_id=rule.supersedes_rule_revision_id,
                clinical_domain=rule.clinical_domain,
                source_refs=rule.source_refs,
                field_lineage=rule.field_lineage,
                mapping_revision=rule.mapping_revision,
                mapping_content_sha256=rule.mapping_content_sha256,
                capability_manifest_sha256=rule.capability_manifest_sha256,
                effective_capabilities_sha256=rule.effective_capabilities_sha256,
                recommendation_candidate_id=rule.recommendation_candidate_id,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted monitoring rule is invalid"
            ) from exc
        if (
            rebuilt.rule_revision_id != rule.rule_revision_id
            or MonitoringProtocolRuleRepository._rule_immutable(rebuilt)
            != MonitoringProtocolRuleRepository._rule_immutable(rule)
        ):
            raise MonitoringProtocolRuleError(
                "persisted monitoring rule source hash or identity mismatch"
            )
        return rule

    @staticmethod
    def _re_review_from_row(row: sqlite3.Row) -> RuleReReviewTask:
        task = RuleReReviewTask(
            task_id=row["task_id"],
            project_id=row["project_id"],
            risk_instance_id=row["risk_instance_id"],
            rule_key=row["rule_key"],
            previous_rule_revision_id=row["previous_rule_revision_id"],
            current_rule_revision_id=row["current_rule_revision_id"],
            reason=row["reason"],
            status=row["status"],
        )
        persisted_reason_sha256 = (
            row["reason_sha256"] if "reason_sha256" in row.keys() else ""
        )
        if persisted_reason_sha256:
            if (
                not isinstance(persisted_reason_sha256, str)
                or persisted_reason_sha256 != persisted_reason_sha256.strip()
                or persisted_reason_sha256 != persisted_reason_sha256.lower()
                or len(persisted_reason_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in persisted_reason_sha256
                )
            ):
                raise MonitoringProtocolRuleError(
                    "persisted re-review task reason hash is not canonical"
                )
        if persisted_reason_sha256 and persisted_reason_sha256 != sha256(
            task.reason.encode("utf-8")
        ).hexdigest():
            raise MonitoringProtocolRuleError(
                "persisted re-review task reason hash mismatch"
            )
        # Review status is a lifecycle field and may change independently;
        # the task identity and rationale lineage remain immutable. Rebuild
        # those fields through the canonical factory so row tampering cannot
        # silently produce a foreign or semantically different task.
        try:
            rebuilt = RuleReReviewTask.create(
                binding=RuleRiskBinding(
                    risk_instance_id=task.risk_instance_id,
                    project_id=task.project_id,
                    rule_key=task.rule_key,
                    evaluated_rule_revision_id=task.previous_rule_revision_id,
                ),
                current_rule_revision_id=task.current_rule_revision_id,
                reason=task.reason,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted re-review task is invalid"
            ) from exc
        if (
            rebuilt.task_id != task.task_id
            or rebuilt.project_id != task.project_id
            or rebuilt.risk_instance_id != task.risk_instance_id
            or rebuilt.rule_key != task.rule_key
            or rebuilt.previous_rule_revision_id
            != task.previous_rule_revision_id
            or rebuilt.current_rule_revision_id
            != task.current_rule_revision_id
            or rebuilt.reason != task.reason
        ):
            raise MonitoringProtocolRuleError(
                "persisted re-review task identity or content mismatch"
            )
        return task

    @staticmethod
    def _gold_case_from_row(row: sqlite3.Row) -> RuleGoldStandardCase:
        case = RuleGoldStandardCase(
            case_id=row["case_id"],
            project_id=row["project_id"],
            rule_key=row["rule_key"],
            rule_revision_id=row["rule_revision_id"],
            source_entry_id=row["source_entry_id"],
            source_content_sha256=row["source_content_sha256"],
            source_revision=row["source_revision"],
            batch_revision=row["batch_revision"],
            case_label=row["case_label"],
            input_record=_loads(row["input_record_json"]),
            previous_record=_loads(row["previous_record_json"]),
            related_records=_loads(row["related_records_json"]),
            observed_domains=tuple(_loads(row["observed_domains_json"])),
            expected_match=_sqlite_bool(row["expected_match"], "expected_match"),
            coverage_labels=tuple(
                _loads(row["coverage_labels_json"])
                if "coverage_labels_json" in row.keys()
                and row["coverage_labels_json"]
                else []
            ),
            medical_rationale=row["medical_rationale"],
            evidence_locators=tuple(_loads(row["evidence_locators_json"])),
            source_row_bindings=tuple(
                RuleGoldSourceRowBinding.from_mapping(item)
                for item in (
                    _loads(row["source_row_bindings_json"])
                    if "source_row_bindings_json" in row.keys()
                    and row["source_row_bindings_json"]
                    else []
                )
            ),
        )
        # The pre-coverage-label schema is intentionally retained for legacy
        # migration diagnostics; complete modern cases opt in to strict
        # factory reconstruction below.
        if not case.coverage_labels:
            return case
        try:
            rebuilt = RuleGoldStandardCase.create(
                project_id=case.project_id,
                rule_key=case.rule_key,
                rule_revision_id=case.rule_revision_id,
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
                coverage_labels=case.coverage_labels,
                medical_rationale=case.medical_rationale,
                evidence_locators=case.evidence_locators,
                source_row_bindings=case.source_row_bindings,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted gold standard case is invalid"
            ) from exc
        if rebuilt != case:
            raise MonitoringProtocolRuleError(
                "persisted gold standard case identity or content mismatch"
            )
        return case

    @staticmethod
    def _diagnostic_case_from_row(row: sqlite3.Row) -> RuleDiagnosticCase:
        case = RuleDiagnosticCase(
            case_id=row["case_id"],
            project_id=row["project_id"],
            rule_key=row["rule_key"],
            rule_revision_id=row["rule_revision_id"],
            source_entry_id=row["source_entry_id"],
            source_content_sha256=row["source_content_sha256"],
            source_revision=row["source_revision"],
            batch_revision=row["batch_revision"],
            case_label=row["case_label"],
            input_record=_loads(row["input_record_json"]),
            previous_record=_loads(row["previous_record_json"]),
            related_records=_loads(row["related_records_json"]),
            observed_domains=tuple(_loads(row["observed_domains_json"])),
            expected_diagnostic_category=row[
                "expected_diagnostic_category"
            ],
            expected_diagnostic_code=row["expected_diagnostic_code"],
            medical_rationale=row["medical_rationale"],
            evidence_locators=tuple(_loads(row["evidence_locators_json"])),
            source_row_bindings=tuple(
                RuleGoldSourceRowBinding.from_mapping(item)
                for item in _loads(row["source_row_bindings_json"])
            ),
        )
        try:
            rebuilt = RuleDiagnosticCase.create(
                project_id=case.project_id,
                rule_key=case.rule_key,
                rule_revision_id=case.rule_revision_id,
                source_entry_id=case.source_entry_id,
                source_content_sha256=case.source_content_sha256,
                source_revision=case.source_revision,
                batch_revision=case.batch_revision,
                case_label=case.case_label,
                input_record=case.input_record,
                previous_record=case.previous_record,
                related_records=case.related_records,
                observed_domains=case.observed_domains,
                expected_diagnostic_category=case.expected_diagnostic_category,
                expected_diagnostic_code=case.expected_diagnostic_code,
                medical_rationale=case.medical_rationale,
                evidence_locators=case.evidence_locators,
                source_row_bindings=case.source_row_bindings,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted diagnostic case is invalid"
            ) from exc
        if rebuilt != case:
            raise MonitoringProtocolRuleError(
                "persisted diagnostic case identity or content mismatch"
            )
        return case

    @staticmethod
    def _shadow_run_from_row(row: sqlite3.Row) -> RuleShadowRun:
        results = tuple(
            RuleShadowCaseResult(**item)
            for item in _loads(row["results_json"])
        )
        diagnostic_results = tuple(
            RuleShadowDiagnosticResult(**item)
            for item in _loads(row["diagnostic_results_json"])
        )
        rule_coverages = tuple(
            RuleRevisionCoverageSnapshot(
                **{
                    **item,
                    "authoritative_projects": tuple(
                        item["authoritative_projects"]
                    ),
                }
            )
            for item in _loads(row["rule_coverages_json"])
        )
        family_coverages = tuple(
            RuleFamilyCoverageSnapshot(
                rule_family=item["rule_family"],
                authoritative_projects=tuple(item["authoritative_projects"]),
            )
            for item in _loads(row["family_coverages_json"])
        )
        restored = RuleShadowRun(
            shadow_run_id=row["shadow_run_id"],
            project_id=row["project_id"],
            rule_pack_id=row["rule_pack_id"],
            batch_id=row["batch_id"],
            status=row["status"],
            case_count=int(row["case_count"]),
            passed_count=int(row["passed_count"]),
            failed_count=int(row["failed_count"]),
            results=results,
            case_set_content_sha256=row["case_set_content_sha256"],
            completed_at=row["completed_at"],
            diagnostic_case_count=int(row["diagnostic_case_count"]),
            diagnostic_passed_count=int(
                row["diagnostic_passed_count"]
            ),
            diagnostic_failed_count=int(row["diagnostic_failed_count"]),
            diagnostic_results=diagnostic_results,
            diagnostic_case_set_content_sha256=row[
                "diagnostic_case_set_content_sha256"
            ],
            diagnostic_results_content_sha256=row[
                "diagnostic_results_content_sha256"
            ],
            rule_coverages=rule_coverages,
            family_coverages=family_coverages,
            coverage_content_sha256=row["coverage_content_sha256"],
        )
        # Preserve established downstream lifecycle diagnostics for legacy
        # rows that predate the complete snapshot metadata, and for the
        # explicit missing-gold-hash gate. Complete modern rows opt in to
        # strict read-side identity revalidation below.
        if not restored.case_set_content_sha256:
            return restored
        if (
            not restored.diagnostic_case_set_content_sha256
            and not restored.diagnostic_results_content_sha256
            and not restored.coverage_content_sha256
            and not restored.diagnostic_results
            and not restored.rule_coverages
            and not restored.family_coverages
        ):
            return restored
        try:
            rebuilt = RuleShadowRun.create(
                project_id=restored.project_id,
                rule_pack_id=restored.rule_pack_id,
                batch_id=restored.batch_id,
                results=restored.results,
                case_set_content_sha256=restored.case_set_content_sha256,
                completed_at=restored.completed_at,
                diagnostic_results=restored.diagnostic_results,
                diagnostic_case_set_sha256=(
                    restored.diagnostic_case_set_content_sha256
                ),
                rule_coverages=restored.rule_coverages,
                family_coverages=restored.family_coverages,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringProtocolRuleError(
                "persisted monitoring shadow run is invalid"
            ) from exc
        if rebuilt != restored:
            raise MonitoringProtocolRuleError(
                "persisted monitoring shadow run identity or content mismatch"
            )
        return restored

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        project_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Any,
    ) -> None:
        connection.execute(
            """
            INSERT INTO monitoring_protocol_rule_events (
                project_id, aggregate_type, aggregate_id,
                event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                aggregate_type,
                aggregate_id,
                event_type,
                _json(payload),
                _utc_now_text(),
            ),
        )
