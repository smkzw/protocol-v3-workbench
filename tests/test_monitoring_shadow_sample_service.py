from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    SourceRegistrationResult,
    SourceRegistryEntry,
)
from services.api.app.medical_monitoring_router import (
    create_medical_monitoring_router,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_gold_case_authority import (
    MonitoringGoldCaseAuthority,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepositoryError,
    MonitoringProtocolRuleRepository,
    RulePackLifecycleError,
    RulePackRevisionConflictError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    RuleGoldStandardCase,
    ShadowSampleMedicalConfirmation,
    ShadowProvisionalSample,
    ShadowProvisionalSampleSet,
)
from services.api.app.monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_shadow_sample_service import (
    MonitoringShadowSampleError,
    MonitoringShadowSampleService,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _full_identity,
    _gold_case_source,
    _rule,
    _rule_with_identity,
    _start_shadow_pack,
    _version,
)

PROJECT = "proj_shadow_sample"
OTHER_PROJECT = "proj_shadow_other"
MAPPING_REVISION = "mapping-revision-001"
MAPPING_CONTENT_SHA256 = "a" * 64
CAPABILITY_MANIFEST_SHA256 = "b" * 64


class _RegistryReader:
    def __init__(self, results: tuple[SourceRegistrationResult, ...] = ()):
        self.results = list(results)

    def add(self, result: SourceRegistrationResult) -> None:
        self.results.append(result)

    def list_results(self, project_id: str) -> list[SourceRegistrationResult]:
        return [
            result
            for result in self.results
            if result.entry.project_id == project_id
        ]


class _FakeSourceRegistry:
    def __init__(self):
        self._entries: dict[tuple[str, str], Any] = {}

    def add_entry(self, project_id: str, entry_id: str, content_hash: str):
        self._entries[(project_id, entry_id)] = SimpleNamespace(
            entry_id=entry_id,
            project_id=project_id,
            module="medical_monitoring",
            source_kind="edc_data_listing",
            public_title="EDC Data Listing",
            content_hash=content_hash,
            parser_status="parsed",
        )

    def list_entries(self, project_id: str):
        return [
            entry
            for (entry_project, _entry_id), entry in self._entries.items()
            if entry_project == project_id
        ]

    def current_content_validation(self, project_id: str, source_entry_id: str):
        entry = self._entries.get((project_id, source_entry_id))
        if entry is None:
            return None
        return SimpleNamespace(
            technical_status="ready",
            use_status="allowed",
            file_sha256=entry.content_hash,
        )


class _EmptyRiskRepository:
    def list_current(self, *_args, **_kwargs):
        return []


@dataclass(frozen=True)
class _BatchInfo:
    batch_id: str
    entry_id: str
    content_hash: str


@dataclass
class _Fixture:
    root: Path
    project_id: str
    batches: MonitoringBatchRepository
    repository: MonitoringProtocolRuleRepository
    rule_service: MonitoringProtocolRuleService
    authoring: MonitoringRuleAuthoringService
    sample_service: MonitoringShadowSampleService
    registry_reader: _RegistryReader
    source_registry: _FakeSourceRegistry
    pack: Any
    rules: list
    batch: _BatchInfo


def _ex_row(
    entry_id: str,
    content_hash: str,
    subject: str,
    dose: Any,
    description: str,
    row_number: int,
) -> dict[str, Any]:
    return {
        "business_key": f"EX:{subject}",
        "domain": "EX",
        "data": {
            "SUBJID": subject,
            "EXDOSE": dose,
            "EXDESC": description,
        },
        "source_locator": {
            "source_entry_id": entry_id,
            "source_content_sha256": content_hash,
            "sheet": "EX",
            "row": row_number,
        },
    }


def _ex_rows(entry_id: str, content_hash: str) -> tuple[dict[str, Any], ...]:
    return (
        _ex_row(entry_id, content_hash, "S001", 20, "受试者自述漏服一次", 2),
        _ex_row(entry_id, content_hash, "S002", 20, "每日一次", 3),
        _ex_row(entry_id, content_hash, "S003", 5, "每日一次", 4),
        _ex_row(entry_id, content_hash, "S004", "不详", "每日一次", 5),
    )


def _ex_rows_variant(
    entry_id: str, content_hash: str
) -> tuple[dict[str, Any], ...]:
    return (
        _ex_row(entry_id, content_hash, "S101", 20, "受试者自述漏服两次", 2),
        _ex_row(entry_id, content_hash, "S102", 20, "每日一次", 3),
        _ex_row(entry_id, content_hash, "S103", 5, "每日一次", 4),
        _ex_row(entry_id, content_hash, "S104", "不详", "每日一次", 5),
    )


def _ex_rows_without_positive(
    entry_id: str, content_hash: str
) -> tuple[dict[str, Any], ...]:
    return tuple(_ex_rows(entry_id, content_hash)[1:])


def _v2_mapping(
    *,
    mapping_revision: str = MAPPING_REVISION,
    mapping_content_sha256: str = MAPPING_CONTENT_SHA256,
    capability_manifest_sha256: str = CAPABILITY_MANIFEST_SHA256,
) -> dict[str, Any]:
    return {
        "schema_version": "monitoring_project_mapping_v2",
        "mapping_revision": mapping_revision,
        "mapping_content_sha256": mapping_content_sha256,
        "source_profile_sha256": "d" * 64,
        "source_batch_id": "source-batch-1",
        "fields": [
            {
                "domain": "EX",
                "source_field": "SUBJID",
                "recommended_role": "subject_id",
            },
            {
                "domain": "EX",
                "source_field": "EXDOSE",
                "recommended_role": "dose",
            },
            {
                "domain": "EX",
                "source_field": "EXDESC",
                "recommended_role": "treatment_description",
            },
        ],
        "semantic_quality_report_sha256": "e" * 64,
        "capability_manifest_sha256": capability_manifest_sha256,
        "effective_capabilities_sha256": "f" * 64,
        "activation_disposition": "activate_full",
        "effective_capabilities": [],
        "capability_states": [],
    }


def _make_batch(
    batches: MonitoringBatchRepository,
    root: Path,
    *,
    project_id: str,
    key: str,
    rows_factory: Callable[[str, str], tuple[dict[str, Any], ...]] = _ex_rows,
    mapping: dict[str, Any] | None = None,
    mapping_revision: str = MAPPING_REVISION,
    freeze: bool = True,
) -> _BatchInfo:
    file_path = root / f"{key}-listing.xlsx"
    file_path.write_bytes(f"PK\x03\x04{key}-listing".encode("utf-8"))
    content_hash = sha256(file_path.read_bytes()).hexdigest()
    entry_id = f"listing-{content_hash[:16]}"
    source = batches.register_source(
        project_id=project_id,
        source_entry_id=entry_id,
        validation_id=f"validation-{key}",
        validation_revision=1,
        validator_version="source-content-v2",
        validation_use_status="allowed",
        role="edc_data_listing",
        source_class="raw_full_snapshot",
        file_path=file_path,
        parser_version="listing-parser-v1",
    )
    created = batches.create_batch(
        project_id=project_id,
        idempotency_key=f"{key}:create",
        expected_domains=("EX",),
    )
    attached = batches.attach_source(
        batch_id=created.batch.batch_id,
        source_id=source.source_id,
        expected_version=created.batch.version,
        idempotency_key=f"{key}:attach",
    )
    materialized = batches.replace_rows(
        batch_id=created.batch.batch_id,
        rows=rows_factory(entry_id, content_hash),
        expected_version=attached.batch.version,
        idempotency_key=f"{key}:rows",
    )
    batch = materialized.batch
    parsed = batches.transition_batch(
        batch_id=batch.batch_id,
        target_state="parsed",
        expected_version=batch.version,
        idempotency_key=f"{key}:parsed",
    )
    evidenced = batches.record_validation_evidence(
        batch_id=batch.batch_id,
        mapping_revision=mapping_revision,
        mapping=mapping if mapping is not None else _v2_mapping(
            mapping_revision=mapping_revision
        ),
        expected_domains=("EX",),
        full_snapshot_proof={
            "confirmed": True,
            "basis": "完整 listing",
            "confirmed_by": "medical_manager",
        },
        expected_version=parsed.batch.version,
        idempotency_key=f"{key}:evidence",
    )
    validated = batches.transition_batch(
        batch_id=batch.batch_id,
        target_state="validated",
        expected_version=evidenced.batch.version,
        idempotency_key=f"{key}:validated",
    )
    confirmed = batches.transition_batch(
        batch_id=batch.batch_id,
        target_state="confirmed",
        expected_version=validated.batch.version,
        idempotency_key=f"{key}:confirmed",
    )
    if freeze:
        batch = batches.transition_batch(
            batch_id=batch.batch_id,
            target_state="frozen",
            expected_version=confirmed.batch.version,
            idempotency_key=f"{key}:frozen",
        ).batch
    return _BatchInfo(
        batch_id=batch.batch_id,
        entry_id=entry_id,
        content_hash=content_hash,
    )


def _registration(
    project_id: str, batch: _BatchInfo
) -> SourceRegistrationResult:
    return SourceRegistrationResult(
        entry=SourceRegistryEntry(
            entry_id=batch.entry_id,
            project_id=project_id,
            module="medical_monitoring",
            source_kind="edc_data_listing",
            public_title="EDC Data Listing",
            content_hash=batch.content_hash,
            size_bytes=1,
            parser_status="parsed",
            parser_version="listing-parser-v1",
            created_at=datetime.now(timezone.utc),
        ),
        spans=[],
    )


def _blank_stored_rule_identity(db_path: Path, rules: Any) -> None:
    """Blank the four immutable identity columns in place, simulating a
    legacy pack that predates the identity contract."""
    connection = sqlite3.connect(db_path)
    try:
        placeholders = ", ".join("?" for _ in rules)
        connection.execute(
            "UPDATE monitoring_rule_definitions SET "
            "mapping_revision = '', mapping_content_sha256 = '', "
            "capability_manifest_sha256 = '', "
            "effective_capabilities_sha256 = '' "
            f"WHERE rule_revision_id IN ({placeholders})",
            tuple(rule.rule_revision_id for rule in rules),
        )
        connection.commit()
    finally:
        connection.close()


def _shadow_rule(version: Any, fact: Any) -> Any:
    lineage_hash = sha256(
        f"{version.project_id}:shadow-sample-lineage".encode("utf-8")
    ).hexdigest()
    base = replace(
        _rule(version, fact),
        preconditions={
            "all": [
                {"exists": {"field": "SUBJID"}},
                {"gte": {"field": "EXDOSE", "value": 10}},
            ]
        },
        field_lineage={
            role: {
                "field": field_name,
                "domain": "EX",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        f"listing:{lineage_hash}:sheet:EX:"
                        f"header:1:field:{field_name}"
                    ),
                },
            }
            for role, field_name in (
                ("subject_id", "SUBJID"),
                ("dose", "EXDOSE"),
                ("treatment_description", "EXDESC"),
            )
        },
        evidence_template="用药记录：{EXDESC}",
    )
    return _rule_with_identity(
        base,
        **_full_identity(
            mapping_revision=MAPPING_REVISION,
            mapping_content_sha256=MAPPING_CONTENT_SHA256,
            capability_manifest_sha256=CAPABILITY_MANIFEST_SHA256,
            effective_capabilities_sha256="f" * 64,
        ),
    )


def _build_fixture(
    root: Path,
    *,
    project_id: str = PROJECT,
    rows_factory: Callable[[str, str], tuple[dict[str, Any], ...]] = _ex_rows,
    mapping_revision: str = MAPPING_REVISION,
    identified: bool = True,
) -> _Fixture:
    batches = MonitoringBatchRepository(
        root / "batches.sqlite3",
        root / "batch_objects",
    )
    batch = _make_batch(
        batches,
        root,
        project_id=project_id,
        key="main",
        rows_factory=rows_factory,
        mapping_revision=mapping_revision,
    )
    registry_reader = _RegistryReader((_registration(project_id, batch),))
    source_registry = _FakeSourceRegistry()
    source_registry.add_entry(project_id, batch.entry_id, batch.content_hash)
    authority = MonitoringGoldCaseAuthority(
        registry_reader,
        batches,
    )
    repository = MonitoringProtocolRuleRepository(
        root / "rules.sqlite3",
        gold_case_authority=authority.validate,
    )
    version = repository.register_protocol_version(
        _version(project_id, "V1.0", "2026-01-01", effective_from="2026-01-10")
    )
    fact = repository.store_fact(_fact(version))
    # Rules without immutable identity can no longer be confirmed through
    # the lifecycle gates; build a valid shadow pack first, then blank the
    # stored identity columns directly to simulate a legacy pack.
    rule = _shadow_rule(version, fact)
    _lifecycle, pack, confirmed_rules = _start_shadow_pack(
        repository,
        version,
        [rule],
    )
    if not identified:
        _blank_stored_rule_identity(repository.db_path, confirmed_rules)
    rule_service = MonitoringProtocolRuleService(repository)
    authoring = MonitoringRuleAuthoringService(
        repository=repository,
        lifecycle_service=MonitoringRuleLifecycleService(repository),
        protocol_rule_service=rule_service,
        ai_repository=MonitoringAiRepository(root / "ai.sqlite3"),
        source_registry=source_registry,
    )
    sample_service = MonitoringShadowSampleService(
        repository=repository,
        batch_repository=batches,
        protocol_rule_service=rule_service,
        rule_authoring_service=authoring,
    )
    return _Fixture(
        root=root,
        project_id=project_id,
        batches=batches,
        repository=repository,
        rule_service=rule_service,
        authoring=authoring,
        sample_service=sample_service,
        registry_reader=registry_reader,
        source_registry=source_registry,
        pack=pack,
        rules=confirmed_rules,
        batch=batch,
    )


def _add_batch(
    fixture: _Fixture,
    *,
    project_id: str,
    key: str,
    rows_factory: Callable[[str, str], tuple[dict[str, Any], ...]] = _ex_rows,
) -> _BatchInfo:
    batch = _make_batch(
        fixture.batches,
        fixture.root,
        project_id=project_id,
        key=key,
        rows_factory=rows_factory,
    )
    fixture.registry_reader.add(_registration(project_id, batch))
    fixture.source_registry.add_entry(
        project_id,
        batch.entry_id,
        batch.content_hash,
    )
    return batch


def _add_project(
    fixture: _Fixture,
    project_id: str,
    key: str,
) -> tuple[Any, list, _BatchInfo]:
    batch = _add_batch(fixture, project_id=project_id, key=key)
    version = fixture.repository.register_protocol_version(
        _version(project_id, "V1.0", "2026-01-01", effective_from="2026-01-10")
    )
    fact = fixture.repository.store_fact(_fact(version))
    rule = _shadow_rule(version, fact)
    _lifecycle, pack, confirmed_rules = _start_shadow_pack(
        fixture.repository,
        version,
        [rule],
    )
    return pack, confirmed_rules, batch


def _client(fixture: _Fixture) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_medical_monitoring_router(
            risk_repository=_EmptyRiskRepository(),
            protocol_rule_service=fixture.rule_service,
            protocol_rule_authoring_service=fixture.authoring,
            protocol_rule_shadow_sample_service=fixture.sample_service,
            require_server_principal=False,
        )
    )
    return TestClient(app)


def _prepare(
    fixture: _Fixture,
    *,
    project_id: str = PROJECT,
    rule_pack_id: str = "",
    batch_id: str = "",
):
    return fixture.sample_service.prepare_and_run(
        project_id=project_id,
        rule_pack_id=rule_pack_id or fixture.pack.rule_pack_id,
        batch_id=batch_id or fixture.batch.batch_id,
        actor="medical_manager",
    )


def _revision_ids(fixture: _Fixture) -> list[str]:
    return [rule.rule_revision_id for rule in fixture.rules]


def _repository_counts(
    repository: MonitoringProtocolRuleRepository,
) -> dict[str, int]:
    tables = {
        "gold": "monitoring_rule_gold_cases",
        "diagnostic": "monitoring_rule_diagnostic_cases",
        "runs": "monitoring_rule_shadow_runs",
        "sets": "monitoring_shadow_sample_sets",
        "confirmations": "monitoring_shadow_sample_confirmations",
    }
    with repository._connect() as connection:
        return {
            key: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for key, table in tables.items()
        }


def _atomic_repository_counts(
    repository: MonitoringProtocolRuleRepository,
) -> dict[str, int]:
    # `_repository_counts` is imported by other test modules with exact
    # whole-dict expectations, so the events table is counted through this
    # separate helper used only by the atomic-commit tests below.
    counts = dict(_repository_counts(repository))
    with repository._connect() as connection:
        counts["events"] = connection.execute(
            "SELECT COUNT(*) FROM monitoring_protocol_rule_events"
        ).fetchone()[0]
    return counts


def _rebuild_set(
    sample_set: ShadowProvisionalSampleSet,
    **overrides: Any,
) -> ShadowProvisionalSampleSet:
    payload: dict[str, Any] = {
        "project_id": sample_set.project_id,
        "rule_pack_id": sample_set.rule_pack_id,
        "batch_id": sample_set.batch_id,
        "batch_version": sample_set.batch_version,
        "batch_revision": sample_set.batch_revision,
        "mapping_revision": sample_set.mapping_revision,
        "mapping_content_sha256": sample_set.mapping_content_sha256,
        "capability_manifest_sha256": sample_set.capability_manifest_sha256,
        "effective_capabilities_sha256": (
            sample_set.effective_capabilities_sha256
        ),
        "rule_revision_ids": sample_set.rule_revision_ids,
        "samples": sample_set.samples,
        "created_by": "medical_manager",
        "created_at": "2026-07-30T00:00:00+00:00",
    }
    payload.update(overrides)
    return ShadowProvisionalSampleSet.create(**payload)


def _rebuild_sample(
    sample: ShadowProvisionalSample,
    **overrides: Any,
) -> ShadowProvisionalSample:
    payload: dict[str, Any] = {
        "project_id": sample.project_id,
        "rule_key": sample.rule_key,
        "rule_revision_id": sample.rule_revision_id,
        "bucket": sample.bucket,
        "case_label": sample.case_label,
        "business_key": sample.business_key,
        "input_record": sample.input_record,
        "related_records": sample.related_records,
        "observed_domains": sample.observed_domains,
        "evidence_locators": sample.evidence_locators,
        "source_row_bindings": sample.source_row_bindings,
        "actual_matched": sample.actual_matched,
        "actual_evaluation_state": sample.actual_evaluation_state,
        "actual_diagnostic_code": sample.actual_diagnostic_code,
        "evidence_summary": sample.evidence_summary,
    }
    payload.update(overrides)
    return ShadowProvisionalSample.create(**payload)


def test_prepare_stores_only_provisional_sample_set() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))

        inspection = _prepare(fixture)

        assert inspection.reused is False
        assert inspection.pack.rule_pack_id == fixture.pack.rule_pack_id
        sample_set = inspection.sample_set
        assert sample_set.rule_pack_id == fixture.pack.rule_pack_id
        assert sample_set.batch_id == fixture.batch.batch_id
        assert sample_set.mapping_revision == MAPPING_REVISION
        assert tuple(sorted(sample_set.rule_revision_ids)) == tuple(
            sorted(_revision_ids(fixture))
        )
        assert len(sample_set.samples) == 4
        by_bucket = {sample.bucket: sample for sample in sample_set.samples}
        assert set(by_bucket) == {
            "positive",
            "negative",
            "boundary",
            "diagnostic",
        }
        positive = by_bucket["positive"]
        assert positive.actual_matched is True
        assert positive.actual_evaluation_state == "true"
        assert positive.actual_diagnostic_code == ""
        for bucket in ("negative", "boundary"):
            assert by_bucket[bucket].actual_matched is False
            assert by_bucket[bucket].actual_evaluation_state == "false"
            assert by_bucket[bucket].actual_diagnostic_code == ""
        diagnostic = by_bucket["diagnostic"]
        assert diagnostic.actual_matched is False
        assert diagnostic.actual_evaluation_state == "indeterminate"
        assert diagnostic.actual_diagnostic_code == "indeterminate_predicate"
        for sample in sample_set.samples:
            assert sample.rule_key == fixture.rules[0].rule_key
            assert sample.rule_revision_id == (
                fixture.rules[0].rule_revision_id
            )
            assert not hasattr(sample, "expected_match")
            assert not hasattr(sample, "expected_diagnostic_category")
            assert not hasattr(sample, "expected_diagnostic_code")
            assert not hasattr(sample, "coverage_labels")
        assert not hasattr(sample_set, "status")
        assert not hasattr(fixture.sample_service, "_existing_run")
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 1,
            "confirmations": 0,
        }


def test_persisted_shadow_sample_set_hash_shape_is_rejected_on_read() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)

        with sqlite3.connect(fixture.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_shadow_sample_sets "
                "SET mapping_content_sha256 = ? WHERE sample_set_id = ?",
                (
                    inspection.sample_set.mapping_content_sha256.upper(),
                    inspection.sample_set.sample_set_id,
                ),
            )

        with pytest.raises(
            MonitoringProtocolRuleRepositoryError,
            match="mapping_content_sha256 is not canonical",
        ):
            fixture.repository.shadow_sample_sets(PROJECT)


def test_shadow_sample_hash_factories_require_exact_lowercase_hex() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        valid = "a" * 64

        for field in (
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
        ):
            for malformed in (f" {valid}", valid.upper(), 123):
                with pytest.raises(
                    MonitoringProtocolRuleError,
                    match=f"{field} must be a lowercase SHA-256 digest",
                ):
                    _rebuild_set(
                        inspection.sample_set,
                        **{field: malformed},
                    )

        for malformed in (f" {valid}", valid.upper(), 123):
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="sample_set_content_sha256 must be a lowercase SHA-256 digest",
            ):
                ShadowSampleMedicalConfirmation.create(
                    project_id=PROJECT,
                    rule_pack_id=fixture.pack.rule_pack_id,
                    sample_set_id=inspection.sample_set.sample_set_id,
                    sample_set_content_sha256=malformed,
                    trusted_shadow_run_id="shadow-run-hash-shape",
                    confirmed_by="medical_manager",
                    confirmed_at="2026-07-30T00:00:00+00:00",
                )


def test_shadow_batch_source_hash_comparison_is_exact() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        diff_batch = fixture.batches.load_diff_ready_batch(
            fixture.batch.batch_id
        )
        registry_key = (PROJECT, fixture.batch.entry_id)
        entry = fixture.source_registry._entries[registry_key]
        original = entry.content_hash

        for malformed in (f" {original}", original.upper(), 123):
            entry.content_hash = malformed
            with pytest.raises(
                MonitoringRuleAuthoringError,
                match="文件内容已变化，请重新执行基本信息与内容校验",
            ):
                fixture.sample_service.rule_authoring_service._usable_source(
                    PROJECT,
                    fixture.batch.entry_id,
                    source_kind="edc_data_listing",
                )

        entry.content_hash = original
        usable_source = (
            fixture.sample_service.rule_authoring_service._usable_source
        )
        fixture.sample_service.rule_authoring_service._usable_source = (
            lambda _project_id, _source_entry_id, *, source_kind: entry
        )
        for malformed in (f" {original}", original.upper(), 123):
            entry.content_hash = malformed
            with pytest.raises(
                MonitoringShadowSampleError,
                match="冻结批次绑定的来源文件内容已变化",
            ):
                fixture.sample_service._batch_source(PROJECT, diff_batch)

        entry.content_hash = original
        fixture.sample_service.rule_authoring_service._usable_source = (
            usable_source
        )
        source = fixture.sample_service._batch_source(PROJECT, diff_batch)
        assert source.source_entry_id == fixture.batch.entry_id
        assert source.source_content_sha256 == original


def test_persisted_shadow_sample_set_batch_version_does_not_coerce_text() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)

        with sqlite3.connect(fixture.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_shadow_sample_sets "
                "SET batch_version = ? WHERE sample_set_id = ?",
                ("not-an-int", inspection.sample_set.sample_set_id),
            )

        with pytest.raises(
            MonitoringProtocolRuleRepositoryError,
            match="batch_version is invalid",
        ):
            fixture.repository.shadow_sample_sets(PROJECT)


def test_persisted_shadow_sample_confirmation_hash_must_remain_canonical() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        confirmation, _run = fixture.sample_service.confirm_samples(
            project_id=PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
            sample_set_id=inspection.sample_set.sample_set_id,
            actor="medical_manager",
        )

        with sqlite3.connect(fixture.repository.db_path) as connection:
            connection.execute(
                "UPDATE monitoring_shadow_sample_confirmations "
                "SET sample_set_content_sha256 = ? WHERE confirmation_id = ?",
                (
                    confirmation.sample_set_content_sha256.upper(),
                    confirmation.confirmation_id,
                ),
            )

        with pytest.raises(
            MonitoringProtocolRuleRepositoryError,
            match="hash is not canonical",
        ):
            fixture.repository.shadow_sample_confirmation(
                PROJECT,
                fixture.pack.rule_pack_id,
            )


def test_automatic_shadow_runs_router_contract() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        client = _client(fixture)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"
        pack_id = fixture.pack.rule_pack_id
        url = f"{base}/rule-packs/{pack_id}/automatic-shadow-runs"

        stale = client.post(
            url,
            json={
                "batch_id": fixture.batch.batch_id,
                "actor": "medical_manager",
                "expected_pack_revision": 999,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == (
            "monitoring_rule_pack_revision_stale"
        )

        created = client.post(
            url,
            json={
                "batch_id": fixture.batch.batch_id,
                "actor": "medical_manager",
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["project_id"] == PROJECT
        assert payload["reused"] is False
        assert payload["pack"]["rule_pack_id"] == pack_id
        assert payload["state"] == {
            "code": "shadow_inspection_provisional",
            "label": "自动影子样本待医学确认",
        }
        assert "shadow_run" not in payload
        inspection = payload["inspection"]
        assert inspection["status"] == "provisional"
        assert inspection["rule_pack_id"] == pack_id
        assert inspection["batch_id"] == fixture.batch.batch_id
        assert inspection["mapping_revision"] == MAPPING_REVISION
        assert inspection["sample_count"] == 4
        assert len(inspection["samples"]) == 4
        sample = inspection["samples"][0]
        assert set(sample) == {
            "sample_id",
            "rule_key",
            "bucket",
            "case_label",
            "business_key",
            "actual_matched",
            "actual_evaluation_state",
            "actual_diagnostic_code",
            "evidence_summary",
        }
        for forbidden in (
            "shadow_passed",
            "expected_match",
            "shadow_run_id",
            "trusted",
            "content_sha256",
            "row_fingerprint",
            "source_text_sha256",
        ):
            assert forbidden not in created.text

        replayed = client.post(
            url,
            json={
                "batch_id": fixture.batch.batch_id,
                "actor": "medical_manager",
            },
        )
        assert replayed.status_code == 200
        assert replayed.json()["reused"] is True
        assert (
            replayed.json()["inspection"]["sample_set_id"]
            == inspection["sample_set_id"]
        )

        removed_gold = client.post(
            f"{base}/rule-packs/{pack_id}/gold-cases",
            json={},
        )
        assert removed_gold.status_code in {404, 405}
        removed_diagnostic = client.post(
            f"{base}/rule-packs/{pack_id}/diagnostic-cases",
            json={},
        )
        assert removed_diagnostic.status_code in {404, 405}

        runs = client.get(f"{base}/rule-packs/{pack_id}/shadow-runs")
        assert runs.status_code == 200
        assert runs.json()["items"] == []

        sample_sets = client.get(
            f"{base}/rule-packs/{pack_id}/shadow-sample-sets"
        )
        assert sample_sets.status_code == 200
        items = sample_sets.json()["items"]
        assert len(items) == 1
        assert items[0]["sample_set_id"] == inspection["sample_set_id"]
        assert items[0]["status"] == "provisional"

        other_base = (
            f"/api/projects/{OTHER_PROJECT}/modules/medical-monitoring"
        )
        foreign_sets = client.get(
            f"{other_base}/rule-packs/{pack_id}/shadow-sample-sets"
        )
        assert foreign_sets.status_code == 404
        foreign_runs = client.get(
            f"{other_base}/rule-packs/{pack_id}/shadow-runs"
        )
        assert foreign_runs.status_code == 404


def test_provisional_samples_cannot_confirm_or_publish() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        pack_id = fixture.pack.rule_pack_id
        sample_set_id = inspection.sample_set.sample_set_id

        with pytest.raises(RulePackLifecycleError):
            fixture.authoring.confirm_shadow(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                shadow_run_id="monshrun_bogus",
                confirmed_by="medical_manager",
            )
        with pytest.raises(RulePackLifecycleError):
            fixture.authoring.confirm_shadow(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                shadow_run_id=sample_set_id,
                confirmed_by="medical_manager",
            )
        with pytest.raises(MonitoringRuleAuthoringError) as publish:
            fixture.authoring.publish(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                published_by="medical_manager",
            )
        assert publish.value.code == "monitoring_rule_pack_stage_conflict"
        assert publish.value.http_status == 409

        with pytest.raises(MonitoringRuleAuthoringError) as neither:
            fixture.authoring.confirm_shadow(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                confirmed_by="medical_manager",
            )
        assert (
            neither.value.code
            == "monitoring_shadow_confirmation_target_invalid"
        )
        assert neither.value.http_status == 409
        with pytest.raises(MonitoringRuleAuthoringError) as both:
            fixture.authoring.confirm_shadow(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                shadow_run_id="monshrun_bogus",
                sample_set_id=sample_set_id,
                confirmed_by="medical_manager",
            )
        assert (
            both.value.code == "monitoring_shadow_confirmation_target_invalid"
        )
        assert both.value.http_status == 409
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 1,
            "confirmations": 0,
        }


def test_confirm_samples_promotes_and_replays_deterministically() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        batch_b = _add_batch(
            fixture,
            project_id=PROJECT,
            key="batch-b",
            rows_factory=_ex_rows_variant,
        )
        pack_id = fixture.pack.rule_pack_id
        inspection_a = _prepare(fixture)
        inspection_b = _prepare(fixture, batch_id=batch_b.batch_id)
        sample_set_a = inspection_a.sample_set
        assert (
            inspection_b.sample_set.sample_set_id
            != sample_set_a.sample_set_id
        )

        confirmation, run = fixture.sample_service.confirm_samples(
            project_id=PROJECT,
            rule_pack_id=pack_id,
            sample_set_id=sample_set_a.sample_set_id,
            actor="medical_manager",
        )

        assert run.status == "completed"
        assert run.failed_count == 0
        assert run.diagnostic_failed_count == 0
        assert confirmation.sample_set_id == sample_set_a.sample_set_id
        assert confirmation.trusted_shadow_run_id == run.shadow_run_id
        gold = fixture.repository.gold_cases(
            PROJECT,
            rule_revision_ids=_revision_ids(fixture),
        )
        assert len(gold) == 3
        assert sorted(case.expected_match for case in gold) == [
            False,
            False,
            True,
        ]
        coverage_sets = {
            frozenset(case.coverage_labels) for case in gold
        }
        assert coverage_sets == {
            frozenset({"positive"}),
            frozenset({"negative"}),
            frozenset({"negative", "boundary"}),
        }
        diagnostics = fixture.repository.diagnostic_cases(
            PROJECT,
            rule_revision_ids=_revision_ids(fixture),
        )
        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        assert diagnostic.expected_diagnostic_category == "invalid_input"
        assert diagnostic.expected_diagnostic_code == (
            "indeterminate_predicate"
        )
        for case in (*gold, *diagnostics):
            assert sample_set_a.sample_set_id in case.medical_rationale
            assert "medical_manager" not in case.medical_rationale

        retry_confirmation, retry_run = (
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                sample_set_id=sample_set_a.sample_set_id,
                actor="medical_manager",
            )
        )
        assert retry_confirmation.confirmation_id == (
            confirmation.confirmation_id
        )
        assert retry_run.shadow_run_id == run.shadow_run_id
        assert _repository_counts(fixture.repository) == {
            "gold": 3,
            "diagnostic": 1,
            "runs": 1,
            "sets": 2,
            "confirmations": 1,
        }

        outcome = fixture.authoring.confirm_shadow(
            project_id=PROJECT,
            rule_pack_id=pack_id,
            sample_set_id=sample_set_a.sample_set_id,
            confirmed_by="medical_manager",
        )
        assert outcome.pack.status == "confirmed"
        assert outcome.confirmation is not None
        assert outcome.confirmation.confirmation_id == (
            confirmation.confirmation_id
        )
        assert outcome.shadow_run_id == run.shadow_run_id

        retry_outcome = fixture.authoring.confirm_shadow(
            project_id=PROJECT,
            rule_pack_id=pack_id,
            sample_set_id=sample_set_a.sample_set_id,
            confirmed_by="medical_manager",
        )
        assert retry_outcome.pack.rule_pack_id == outcome.pack.rule_pack_id
        assert retry_outcome.confirmation is not None
        assert retry_outcome.confirmation.confirmation_id == (
            confirmation.confirmation_id
        )
        assert retry_outcome.shadow_run_id == run.shadow_run_id
        assert _repository_counts(fixture.repository) == {
            "gold": 3,
            "diagnostic": 1,
            "runs": 1,
            "sets": 2,
            "confirmations": 1,
        }

        with pytest.raises(MonitoringRuleAuthoringError) as conflict:
            fixture.authoring.confirm_shadow(
                project_id=PROJECT,
                rule_pack_id=pack_id,
                sample_set_id=inspection_b.sample_set.sample_set_id,
                confirmed_by="medical_manager",
            )
        assert (
            conflict.value.code == "monitoring_shadow_confirmation_conflict"
        )
        assert conflict.value.http_status == 409
        assert _repository_counts(fixture.repository) == {
            "gold": 3,
            "diagnostic": 1,
            "runs": 1,
            "sets": 2,
            "confirmations": 1,
        }


def test_confirmation_rejects_batch_revision_drift() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        batch_b = _add_batch(
            fixture,
            project_id=PROJECT,
            key="batch-b",
            rows_factory=_ex_rows_variant,
        )
        inspection = _prepare(fixture)
        sample_set = inspection.sample_set
        batch_b_version = fixture.batches.get_batch(
            batch_b.batch_id
        ).version

        forged = _rebuild_set(
            sample_set,
            batch_id=batch_b.batch_id,
            batch_version=batch_b_version,
        )
        assert forged.sample_set_id != sample_set.sample_set_id
        fixture.repository.store_shadow_sample_set(forged)

        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=forged.sample_set_id,
                actor="medical_manager",
            )
        assert drift.value.code == "monitoring_shadow_confirmation_drift"
        assert drift.value.http_status == 409
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 2,
            "confirmations": 0,
        }


def test_confirmation_rejects_mapping_contract_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)

        original = fixture.batches.load_frozen_mapping_contract

        def drifted_contract(batch_id: str):
            return replace(
                original(batch_id),
                mapping_content_sha256="0" * 64,
            )

        monkeypatch.setattr(
            fixture.batches,
            "load_frozen_mapping_contract",
            drifted_contract,
        )

        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=inspection.sample_set.sample_set_id,
                actor="medical_manager",
            )
        assert drift.value.code == "monitoring_shadow_confirmation_drift"
        assert drift.value.http_status == 409
        assert _repository_counts(fixture.repository)["confirmations"] == 0


def test_confirmation_rejects_rule_drift_and_conflicting_identity() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        sample_set = inspection.sample_set

        forged = _rebuild_set(
            sample_set,
            rule_revision_ids=(
                *sample_set.rule_revision_ids,
                "monrule_forged",
            ),
        )
        fixture.repository.store_shadow_sample_set(forged)
        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=forged.sample_set_id,
                actor="medical_manager",
            )
        assert drift.value.code == "monitoring_shadow_confirmation_drift"
        assert drift.value.http_status == 409

        conflicting = replace(
            sample_set,
            mapping_content_sha256="0" * 64,
        )
        assert conflicting.sample_set_id == sample_set.sample_set_id
        with pytest.raises(RulePackRevisionConflictError):
            fixture.repository.store_shadow_sample_set(conflicting)
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 2,
            "confirmations": 0,
        }


def test_confirmation_rejects_outcome_drift() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        sample_set = inspection.sample_set
        positive = next(
            sample
            for sample in sample_set.samples
            if sample.bucket == "positive"
        )

        forged_sample = _rebuild_sample(
            positive,
            actual_matched=False,
            actual_evaluation_state="false",
        )
        forged = _rebuild_set(
            sample_set,
            samples=tuple(
                forged_sample
                if sample.sample_id == positive.sample_id
                else sample
                for sample in sample_set.samples
            ),
        )
        fixture.repository.store_shadow_sample_set(forged)

        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=forged.sample_set_id,
                actor="medical_manager",
            )
        assert (
            drift.value.code
            == "monitoring_shadow_confirmation_outcome_drift"
        )
        assert drift.value.http_status == 409
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 2,
            "confirmations": 0,
        }


def test_confirmation_enforces_project_and_pack_scope() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        sample_set_id = inspection.sample_set.sample_set_id

        with pytest.raises(MonitoringRuleAuthoringError) as missing:
            fixture.sample_service.confirm_samples(
                project_id=OTHER_PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=sample_set_id,
                actor="medical_manager",
            )
        assert missing.value.code == "monitoring_rule_pack_not_found"
        assert missing.value.http_status == 404

        version2 = fixture.repository.register_protocol_version(
            _version(
                PROJECT,
                "V2.0",
                "2026-06-01",
            )
        )
        fact2 = fixture.repository.store_fact(_fact(version2))
        rule2 = _shadow_rule(version2, fact2)
        _lifecycle2, pack2, _rules2 = _start_shadow_pack(
            fixture.repository,
            version2,
            [rule2],
        )

        with pytest.raises(MonitoringShadowSampleError) as scope:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=pack2.rule_pack_id,
                sample_set_id=sample_set_id,
                actor="medical_manager",
            )
        assert (
            scope.value.code
            == "monitoring_shadow_sample_set_scope_conflict"
        )
        assert scope.value.http_status == 409
        assert _repository_counts(fixture.repository)["confirmations"] == 0


def test_prepare_is_batch_scoped_without_cross_batch_reuse() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        batch_b = _add_batch(
            fixture,
            project_id=PROJECT,
            key="batch-b",
            rows_factory=_ex_rows_variant,
        )

        inspection_a = _prepare(fixture)
        inspection_b = _prepare(fixture, batch_id=batch_b.batch_id)

        assert inspection_a.reused is False
        assert inspection_b.reused is False
        assert (
            inspection_a.sample_set.sample_set_id
            != inspection_b.sample_set.sample_set_id
        )
        keys_a = {
            sample.business_key
            for sample in inspection_a.sample_set.samples
        }
        keys_b = {
            sample.business_key
            for sample in inspection_b.sample_set.samples
        }
        assert keys_a != keys_b
        assert keys_a.isdisjoint(keys_b)

        retry_a = _prepare(fixture)
        assert retry_a.reused is True
        assert (
            retry_a.sample_set.sample_set_id
            == inspection_a.sample_set.sample_set_id
        )
        assert not hasattr(fixture.sample_service, "_existing_run")
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 2,
            "confirmations": 0,
        }


def test_confirmed_pack_publishes_after_two_project_coverage() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        pack_b, _rules_b, batch_b = _add_project(
            fixture,
            OTHER_PROJECT,
            "second",
        )
        inspection_b = _prepare(
            fixture,
            project_id=OTHER_PROJECT,
            rule_pack_id=pack_b.rule_pack_id,
            batch_id=batch_b.batch_id,
        )
        outcome_b = fixture.authoring.confirm_shadow(
            project_id=OTHER_PROJECT,
            rule_pack_id=pack_b.rule_pack_id,
            sample_set_id=inspection_b.sample_set.sample_set_id,
            confirmed_by="medical_manager",
        )
        assert outcome_b.pack.status == "confirmed"

        inspection_a = _prepare(fixture)
        outcome_a = fixture.authoring.confirm_shadow(
            project_id=PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
            sample_set_id=inspection_a.sample_set.sample_set_id,
            confirmed_by="medical_manager",
        )
        assert outcome_a.pack.status == "confirmed"
        assert outcome_a.confirmation is not None

        published = fixture.authoring.publish(
            project_id=PROJECT,
            rule_pack_id=outcome_a.pack.rule_pack_id,
            published_by="medical_manager",
        )
        assert published.status == "published"

        runs = fixture.repository.shadow_runs(
            PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
        )
        assert len(runs) == 1
        run = runs[0]
        assert run.shadow_run_id == outcome_a.shadow_run_id
        assert run.failed_count == 0
        assert run.diagnostic_failed_count == 0
        gold = fixture.repository.gold_cases(
            PROJECT,
            rule_revision_ids=_revision_ids(fixture),
        )
        assert sorted(result.case_id for result in run.results) == sorted(
            case.case_id for case in gold
        )

        with pytest.raises(MonitoringRuleAuthoringError) as stage:
            fixture.sample_service.prepare_and_run(
                project_id=PROJECT,
                rule_pack_id=outcome_a.pack.rule_pack_id,
                batch_id=fixture.batch.batch_id,
                actor="medical_manager",
            )
        assert stage.value.code == "monitoring_rule_pack_stage_conflict"
        assert stage.value.http_status == 409


def test_prepare_rejects_cross_project_and_unfrozen_batches() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = _build_fixture(root)
        foreign = _make_batch(
            fixture.batches,
            root,
            project_id=OTHER_PROJECT,
            key="foreign",
        )
        unfrozen = _make_batch(
            fixture.batches,
            root,
            project_id=PROJECT,
            key="unfrozen",
            freeze=False,
        )

        with pytest.raises(MonitoringShadowSampleError) as cross_project:
            fixture.sample_service.prepare_and_run(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                batch_id=foreign.batch_id,
                actor="medical_manager",
            )
        assert cross_project.value.code == "monitoring_shadow_batch_not_found"
        assert cross_project.value.http_status == 404

        with pytest.raises(MonitoringShadowSampleError) as not_frozen:
            fixture.sample_service.prepare_and_run(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                batch_id=unfrozen.batch_id,
                actor="medical_manager",
            )
        assert not_frozen.value.code == "monitoring_shadow_batch_not_frozen"
        assert not_frozen.value.http_status == 409


def test_prepare_detects_mapping_drift() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(
            Path(directory),
            mapping_revision="mapping-revision-other",
        )

        with pytest.raises(MonitoringShadowSampleError) as drift:
            _prepare(fixture)
        assert drift.value.code == "monitoring_shadow_mapping_drift"
        assert drift.value.http_status == 409


def test_prepare_rejects_identity_less_rules() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory), identified=False)

        with pytest.raises(MonitoringShadowSampleError) as unverifiable:
            _prepare(fixture)
        assert (
            unverifiable.value.code
            == "monitoring_shadow_rule_identity_unverifiable"
        )
        assert unverifiable.value.http_status == 409


def test_prepare_fail_closed_when_bucket_missing() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(
            Path(directory),
            rows_factory=_ex_rows_without_positive,
        )
        rule = fixture.rules[0]

        with pytest.raises(MonitoringShadowSampleError) as incomplete:
            _prepare(fixture)
        assert (
            incomplete.value.code
            == "monitoring_shadow_sample_buckets_incomplete"
        )
        assert incomplete.value.http_status == 422
        assert rule.rule_key in incomplete.value.message
        assert "positive" in incomplete.value.message
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 0,
            "confirmations": 0,
        }


def _capture_failed_pre_run_promotion(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Force the pre-promotion revalidation gate to fail and capture the
    exact in-memory promotion cases the service built before any write."""
    inspection = _prepare(fixture)
    captured: dict[str, Any] = {}
    original = fixture.rule_service.run_shadow_validation

    def intercepted(**kwargs: Any):
        if kwargs.get("cases") is not None:
            captured["gold_cases"] = list(kwargs["cases"])
            captured["diagnostic_cases"] = list(
                kwargs.get("diagnostic_cases") or ()
            )
            return SimpleNamespace(
                failed_count=1,
                diagnostic_failed_count=0,
            )
        return original(**kwargs)

    monkeypatch.setattr(
        fixture.rule_service,
        "run_shadow_validation",
        intercepted,
    )
    with pytest.raises(MonitoringShadowSampleError) as failure:
        fixture.sample_service.confirm_samples(
            project_id=PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
            sample_set_id=inspection.sample_set.sample_set_id,
            actor="medical_manager",
        )
    assert failure.value.code == "monitoring_shadow_confirmation_run_failed"
    assert failure.value.http_status == 409
    assert len(captured["gold_cases"]) == 3
    assert len(captured["diagnostic_cases"]) == 1
    return captured


def test_confirm_samples_pre_run_failure_leaves_no_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))

        _capture_failed_pre_run_promotion(fixture, monkeypatch)

        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 1,
            "confirmations": 0,
        }


def test_confirm_samples_rejects_outcomes_without_ready_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        original = fixture.rule_service.evaluate_record

        def not_ready(*args: Any, **kwargs: Any):
            evaluation = original(*args, **kwargs)
            return replace(
                evaluation,
                evidence={**evaluation.evidence, "evidence_ready": False},
            )

        monkeypatch.setattr(
            fixture.rule_service,
            "evaluate_record",
            not_ready,
        )

        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service.confirm_samples(
                project_id=PROJECT,
                rule_pack_id=fixture.pack.rule_pack_id,
                sample_set_id=inspection.sample_set.sample_set_id,
                actor="medical_manager",
            )
        assert (
            drift.value.code
            == "monitoring_shadow_confirmation_outcome_drift"
        )
        assert drift.value.http_status == 409
        assert _repository_counts(fixture.repository) == {
            "gold": 0,
            "diagnostic": 0,
            "runs": 0,
            "sets": 1,
            "confirmations": 0,
        }


def test_store_shadow_promotion_rolls_back_entire_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        captured = _capture_failed_pre_run_promotion(fixture, monkeypatch)
        gold_cases = captured["gold_cases"]
        diagnostic_cases = captured["diagnostic_cases"]

        tampered = replace(
            gold_cases[1],
            rule_revision_id="monrule_missing",
        )
        with pytest.raises(RulePackLifecycleError):
            fixture.repository.store_shadow_promotion(
                [gold_cases[0], tampered],
                diagnostic_cases,
            )
        counts = _repository_counts(fixture.repository)
        assert counts["gold"] == 0
        assert counts["diagnostic"] == 0

        stored_gold, stored_diagnostic = (
            fixture.repository.store_shadow_promotion(
                gold_cases,
                diagnostic_cases,
            )
        )
        assert [case.case_id for case in stored_gold] == [
            case.case_id for case in gold_cases
        ]
        assert [case.case_id for case in stored_diagnostic] == [
            case.case_id for case in diagnostic_cases
        ]
        counts = _repository_counts(fixture.repository)
        assert counts["gold"] == 3
        assert counts["diagnostic"] == 1


def _confirmed_and_published_packs(fixture: _Fixture):
    pack_b, _rules_b, batch_b = _add_project(
        fixture,
        OTHER_PROJECT,
        "second",
    )
    inspection_b = _prepare(
        fixture,
        project_id=OTHER_PROJECT,
        rule_pack_id=pack_b.rule_pack_id,
        batch_id=batch_b.batch_id,
    )
    outcome_b = fixture.authoring.confirm_shadow(
        project_id=OTHER_PROJECT,
        rule_pack_id=pack_b.rule_pack_id,
        sample_set_id=inspection_b.sample_set.sample_set_id,
        confirmed_by="medical_manager",
    )
    assert outcome_b.pack.status == "confirmed"
    inspection = _prepare(fixture)
    outcome = fixture.authoring.confirm_shadow(
        project_id=PROJECT,
        rule_pack_id=fixture.pack.rule_pack_id,
        sample_set_id=inspection.sample_set.sample_set_id,
        confirmed_by="medical_manager",
    )
    assert outcome.pack.status == "confirmed"
    published = fixture.authoring.publish(
        project_id=PROJECT,
        rule_pack_id=outcome.pack.rule_pack_id,
        published_by="medical_manager",
    )
    assert published.status == "published"
    return inspection, outcome.pack, published


def test_lineage_evidence_projects_shadow_stage_across_lifecycle() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection, confirmed_pack, published_pack = (
            _confirmed_and_published_packs(fixture)
        )
        shadow_pack_id = fixture.pack.rule_pack_id

        for stage_pack in (confirmed_pack, published_pack):
            evidence = fixture.sample_service.lineage_evidence(
                project_id=PROJECT,
                rule_pack_id=stage_pack.rule_pack_id,
            )
            assert evidence.project_id == PROJECT
            assert evidence.rule_pack_id == stage_pack.rule_pack_id
            assert evidence.shadow_rule_pack_id == shadow_pack_id
            assert len(evidence.sample_sets) == 1
            assert (
                evidence.sample_sets[0].sample_set_id
                == inspection.sample_set.sample_set_id
            )
            assert evidence.confirmation is not None
            assert evidence.confirmation.rule_pack_id == shadow_pack_id
            assert (
                evidence.confirmation.sample_set_id
                == inspection.sample_set.sample_set_id
            )

        direct = fixture.sample_service.lineage_evidence(
            project_id=PROJECT,
            rule_pack_id=shadow_pack_id,
        )
        assert direct.shadow_rule_pack_id == shadow_pack_id
        assert len(direct.sample_sets) == 1
        assert direct.confirmation is not None

        draft_pack_id = fixture.repository.rule_pack_lifecycle(
            shadow_pack_id
        )["predecessor_rule_pack_id"]
        empty = fixture.sample_service.lineage_evidence(
            project_id=PROJECT,
            rule_pack_id=draft_pack_id,
        )
        assert empty.shadow_rule_pack_id == ""
        assert empty.sample_sets == ()
        assert empty.confirmation is None

        for stage_pack in (confirmed_pack, published_pack):
            with pytest.raises(MonitoringShadowSampleError) as missing:
                fixture.sample_service.lineage_evidence(
                    project_id=OTHER_PROJECT,
                    rule_pack_id=stage_pack.rule_pack_id,
                )
            assert missing.value.code == "monitoring_rule_pack_not_found"
            assert missing.value.http_status == 404


def test_shadow_lineage_evidence_router_contract() -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection, confirmed_pack, published_pack = (
            _confirmed_and_published_packs(fixture)
        )
        client = _client(fixture)
        base = f"/api/projects/{PROJECT}/modules/medical-monitoring"
        shadow_pack_id = fixture.pack.rule_pack_id

        for stage_pack in (confirmed_pack, published_pack):
            response = client.get(
                f"{base}/rule-packs/{stage_pack.rule_pack_id}"
                "/shadow-lineage-evidence"
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["project_id"] == PROJECT
            assert payload["rule_pack_id"] == stage_pack.rule_pack_id
            assert payload["shadow_rule_pack_id"] == shadow_pack_id
            assert len(payload["items"]) == 1
            assert (
                payload["items"][0]["sample_set_id"]
                == inspection.sample_set.sample_set_id
            )
            confirmation = payload["confirmation"]
            assert confirmation is not None
            assert set(confirmation) == {
                "confirmation_id",
                "sample_set_id",
                "trusted_shadow_run_id",
                "confirmed_at",
            }
            assert (
                confirmation["sample_set_id"]
                == inspection.sample_set.sample_set_id
            )

        other_base = (
            f"/api/projects/{OTHER_PROJECT}/modules/medical-monitoring"
        )
        foreign = client.get(
            f"{other_base}/rule-packs/{published_pack.rule_pack_id}"
            "/shadow-lineage-evidence"
        )
        assert foreign.status_code == 404
        assert foreign.json()["detail"]["code"] == (
            "monitoring_rule_pack_not_found"
        )


def _confirm_samples_call(fixture: _Fixture, sample_set_id: str):
    return fixture.sample_service.confirm_samples(
        project_id=PROJECT,
        rule_pack_id=fixture.pack.rule_pack_id,
        sample_set_id=sample_set_id,
        actor="medical_manager",
    )


def _fail_repository_boundary_once(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    failure_label: str,
) -> None:
    original = getattr(MonitoringProtocolRuleRepository, method_name)
    calls = {"count": 0}

    def flaky(*args: Any, **kwargs: Any):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError(f"injected {failure_label} failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        MonitoringProtocolRuleRepository,
        method_name,
        flaky,
    )


def _assert_atomic_commit_rollback_and_recovery(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    method_name: str,
    failure_label: str,
) -> None:
    inspection = _prepare(fixture)
    before = _atomic_repository_counts(fixture.repository)
    _fail_repository_boundary_once(monkeypatch, method_name, failure_label)

    with pytest.raises(
        RuntimeError,
        match=f"injected {failure_label} failure",
    ):
        _confirm_samples_call(fixture, inspection.sample_set.sample_set_id)
    # The single-transaction commit rolled back completely: not even an
    # audit event survives the injected boundary failure.
    assert _atomic_repository_counts(fixture.repository) == before

    # No dirty state: the same confirmation act retries cleanly through
    # the recovered boundary.
    confirmation, run = _confirm_samples_call(
        fixture,
        inspection.sample_set.sample_set_id,
    )
    committed = _atomic_repository_counts(fixture.repository)
    assert committed["gold"] == before["gold"] + 3
    assert committed["diagnostic"] == before["diagnostic"] + 1
    assert committed["runs"] == before["runs"] + 1
    assert committed["sets"] == before["sets"]
    assert committed["confirmations"] == before["confirmations"] + 1
    assert committed["events"] == before["events"] + 6

    # Idempotent replay of the recorded act: same identities, zero new
    # rows.
    replay_confirmation, replay_run = _confirm_samples_call(
        fixture,
        inspection.sample_set.sample_set_id,
    )
    assert replay_confirmation.confirmation_id == (
        confirmation.confirmation_id
    )
    assert replay_run.shadow_run_id == run.shadow_run_id
    assert _atomic_repository_counts(fixture.repository) == committed


def test_confirm_samples_atomic_commit_rolls_back_on_promotion_entry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        _assert_atomic_commit_rollback_and_recovery(
            fixture,
            monkeypatch,
            method_name="_store_gold_case",
            failure_label="promotion-entry",
        )


def test_confirm_samples_atomic_commit_rolls_back_after_first_case_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        _assert_atomic_commit_rollback_and_recovery(
            fixture,
            monkeypatch,
            method_name="_store_diagnostic_case",
            failure_label="diagnostic-entry",
        )


def test_confirm_samples_atomic_commit_rolls_back_on_trusted_run_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        _assert_atomic_commit_rollback_and_recovery(
            fixture,
            monkeypatch,
            method_name="_store_shadow_run",
            failure_label="trusted-run",
        )


def test_confirm_samples_atomic_commit_rolls_back_on_confirmation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        _assert_atomic_commit_rollback_and_recovery(
            fixture,
            monkeypatch,
            method_name="_store_shadow_sample_confirmation",
            failure_label="confirmation",
        )


def test_confirm_samples_atomic_commit_preserves_independent_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        # Independent pre-registered evidence: a second project completes
        # its own full shadow confirmation before the main project starts.
        pack_b, _rules_b, batch_b = _add_project(
            fixture,
            OTHER_PROJECT,
            "second",
        )
        inspection_b = _prepare(
            fixture,
            project_id=OTHER_PROJECT,
            rule_pack_id=pack_b.rule_pack_id,
            batch_id=batch_b.batch_id,
        )
        outcome_b = fixture.authoring.confirm_shadow(
            project_id=OTHER_PROJECT,
            rule_pack_id=pack_b.rule_pack_id,
            sample_set_id=inspection_b.sample_set.sample_set_id,
            confirmed_by="medical_manager",
        )
        assert outcome_b.pack.status == "confirmed"
        other_gold = fixture.repository.gold_cases(OTHER_PROJECT)
        other_diagnostic = fixture.repository.diagnostic_cases(
            OTHER_PROJECT
        )
        other_runs = fixture.repository.shadow_runs(OTHER_PROJECT)
        other_confirmation = fixture.repository.shadow_sample_confirmation(
            OTHER_PROJECT,
            pack_b.rule_pack_id,
        )
        assert other_gold and other_diagnostic and other_runs
        assert other_confirmation is not None

        inspection = _prepare(fixture)
        before = _atomic_repository_counts(fixture.repository)

        def boom(*args: Any, **kwargs: Any):
            raise RuntimeError("injected confirmation failure")

        monkeypatch.setattr(
            MonitoringProtocolRuleRepository,
            "_store_shadow_sample_confirmation",
            boom,
        )
        with pytest.raises(
            RuntimeError,
            match="injected confirmation failure",
        ):
            _confirm_samples_call(
                fixture,
                inspection.sample_set.sample_set_id,
            )

        # The whole main-project attempt rolled back; the second
        # project's independent evidence is byte-identical.
        assert _atomic_repository_counts(fixture.repository) == before
        assert fixture.repository.gold_cases(PROJECT) == ()
        assert fixture.repository.diagnostic_cases(PROJECT) == ()
        assert fixture.repository.shadow_runs(PROJECT) == ()
        assert (
            fixture.repository.shadow_sample_confirmation(
                PROJECT,
                fixture.pack.rule_pack_id,
            )
            is None
        )
        assert fixture.repository.gold_cases(OTHER_PROJECT) == other_gold
        assert (
            fixture.repository.diagnostic_cases(OTHER_PROJECT)
            == other_diagnostic
        )
        assert fixture.repository.shadow_runs(OTHER_PROJECT) == other_runs
        assert (
            fixture.repository.shadow_sample_confirmation(
                OTHER_PROJECT,
                pack_b.rule_pack_id,
            )
            == other_confirmation
        )


def test_commit_shadow_sample_confirmation_matches_legacy_trusted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        inspection = _prepare(fixture)
        captured: dict[str, Any] = {}
        original_commit = fixture.repository.commit_shadow_sample_confirmation

        def intercepted(**kwargs: Any):
            captured.update(kwargs)
            return original_commit(**kwargs)

        monkeypatch.setattr(
            fixture.repository,
            "commit_shadow_sample_confirmation",
            intercepted,
        )

        confirmation, run_view = _confirm_samples_call(
            fixture,
            inspection.sample_set.sample_set_id,
        )

        trusted_run = captured["run"]
        runs = fixture.repository.shadow_runs(
            PROJECT,
            rule_pack_id=fixture.pack.rule_pack_id,
        )
        assert len(runs) == 1
        stored_run = runs[0]
        # The run content computed before the atomic commit is exactly
        # what the repository persisted.
        assert stored_run == trusted_run
        assert confirmation.trusted_shadow_run_id == (
            trusted_run.shadow_run_id
        )
        assert run_view.shadow_run_id == trusted_run.shadow_run_id
        assert run_view.case_source == "repository_registered"
        assert run_view.trusted_for_release is True
        assert run_view.persisted is True
        # Legacy equivalence: recomputing the trusted run from the
        # repository case set after the commit yields identical content;
        # only the completion timestamp differs.
        legacy_run = fixture.rule_service.compute_repository_shadow_run(
            rule_pack_id=fixture.pack.rule_pack_id,
            batch_id=fixture.batch.batch_id,
        )
        assert legacy_run.shadow_run_id == stored_run.shadow_run_id
        assert (
            replace(legacy_run, completed_at=stored_run.completed_at)
            == stored_run
        )


_IDENTITY_FIELD_OVERRIDES = {
    "mapping_revision": "mapping-revision-999",
    "mapping_content_sha256": "0" * 64,
    "capability_manifest_sha256": "0" * 64,
    "effective_capabilities_sha256": "0" * 64,
}


def _identity_fixture_rule(fixture: _Fixture, **overrides: Any):
    identity = _full_identity(effective_capabilities_sha256="f" * 64)
    identity.update(overrides)
    return _rule_with_identity(fixture.rules[0], **identity)


@pytest.mark.parametrize("field", sorted(_IDENTITY_FIELD_OVERRIDES))
def test_verified_identity_rejects_mixed_four_tuple(field: str) -> None:
    """A single divergent member of the 4-tuple fails closed."""
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        divergent = _identity_fixture_rule(
            fixture,
            **{field: _IDENTITY_FIELD_OVERRIDES[field]},
        )

        with pytest.raises(MonitoringShadowSampleError) as unverifiable:
            fixture.sample_service._verified_rule_mapping_identity(
                [fixture.rules[0], divergent]
            )
        assert (
            unverifiable.value.code
            == "monitoring_shadow_rule_identity_unverifiable"
        )
        assert unverifiable.value.http_status == 409


@pytest.mark.parametrize("field", sorted(_IDENTITY_FIELD_OVERRIDES))
def test_verified_identity_rejects_empty_member(field: str) -> None:
    """An empty identity member fails closed alongside a complete rule."""
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        # The model constructor already rejects partial identity; blank the
        # stored field directly to simulate a legacy pre-contract rule.
        emptied = replace(fixture.rules[0], **{field: ""})

        with pytest.raises(MonitoringShadowSampleError) as unverifiable:
            fixture.sample_service._verified_rule_mapping_identity(
                [fixture.rules[0], emptied]
            )
        assert (
            unverifiable.value.code
            == "monitoring_shadow_rule_identity_unverifiable"
        )
        assert unverifiable.value.http_status == 409


def test_frozen_batch_rejects_effective_capability_mismatch() -> None:
    """The frozen batch contract is validated against all four identity
    fields, including effective capabilities."""
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        drifted = _identity_fixture_rule(
            fixture,
            effective_capabilities_sha256="0" * 64,
        )

        with pytest.raises(MonitoringShadowSampleError) as drift:
            fixture.sample_service._frozen_batch(
                fixture.project_id,
                fixture.batch.batch_id,
                rules=[drifted],
                mapping_revision=MAPPING_REVISION,
            )
        assert drift.value.code == "monitoring_shadow_mapping_drift"
        assert drift.value.http_status == 409


def test_manual_shadow_route_shares_identity_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manual trusted-shadow path must not bypass the same identity
    gate that the automatic sample path enforces."""
    with TemporaryDirectory() as directory:
        fixture = _build_fixture(Path(directory))
        rule = fixture.rules[0]
        locator, source = _gold_case_source(rule, "manual-gate")
        case = RuleGoldStandardCase.create(
            **source,
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            case_label="manual-gate",
            input_record={
                "SUBJID": "MANUAL-GATE",
                "EXDESC": "P7C_POSITIVE",
                "evidence_span_ids": [locator],
            },
            observed_domains=rule.required_domains,
            expected_match=True,
            coverage_labels=("positive",),
            medical_rationale="手动影子路径身份门禁夹具。",
            evidence_locators=[locator],
        )
        monkeypatch.setattr(
            fixture.repository,
            "shadow_case_sets",
            lambda rule_pack_id: ((case,), (), (), ()),
        )
        _blank_stored_rule_identity(fixture.repository.db_path, fixture.rules)

        with pytest.raises(RulePackLifecycleError) as blocked:
            fixture.rule_service.run_shadow_validation(
                rule_pack_id=fixture.pack.rule_pack_id,
                batch_id=fixture.batch.batch_id,
            )
        assert "immutable mapping identity" in str(blocked.value)
