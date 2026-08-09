from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rules import (
    ProtocolFact,
    ProtocolSourceVersion,
)
from services.api.app.shared_protocol_fact_projection import (
    ConfirmedProtocolFactRecord,
    MedicalWritingProtocolFactReadAdapter,
    MonitoringProtocolFactReadAdapter,
    SharedProtocolFactDTO,
    SharedProtocolFactProjectionService,
    UnsafeProtocolFactProjection,
    _is_sha256,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("malformed", [f" {'a' * 64}", "A" * 64, 123])
def test_shared_source_hash_shape_is_not_normalized(malformed: object) -> None:
    assert _is_sha256(malformed) is False


def test_shared_source_hash_shape_accepts_only_exact_lowercase_digest() -> None:
    assert _is_sha256("a" * 64) is True


@pytest.mark.parametrize("hash_field", ["state_sha256", "quote_sha256"])
@pytest.mark.parametrize("malformed", [f" {'a' * 64}", "A" * 64])
def test_medical_writing_source_hashes_are_not_normalized(
    hash_field: str,
    malformed: str,
) -> None:
    project_id = f"project_{hash_field}"
    journey = _writing_journey(project_id)
    definition = journey.study_definition
    if hash_field == "state_sha256":
        definition.state_sha256 = malformed
    else:
        definition.field_states["framing.indication"].evidence[0].quote_sha256 = (
            malformed
        )

    adapter = MedicalWritingProtocolFactReadAdapter(
        _JourneyReader({project_id: journey})
    )

    assert adapter.read_confirmed(project_id) == ()


def _protocol_version(
    repository: MonitoringProtocolRuleRepository,
    project_id: str,
    *,
    label: str = "V1.0",
) -> ProtocolSourceVersion:
    version = ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code=f"{project_id}-protocol",
        version_label=label,
        version_date="2026-01-01",
        source_entry_id=f"source_{project_id}_{label}",
        source_title=f"{project_id} protocol {label}",
        content_sha256=_sha(f"{project_id}:{label}"),
        status="confirmed",
        applicability_status="version_date_only",
    )
    return repository.register_protocol_version(version)


def _monitoring_fact(
    repository: MonitoringProtocolRuleRepository,
    version: ProtocolSourceVersion,
    *,
    fact_key: str = "visit_window_w4",
    source_text: str = "第4周访视允许窗口为计划日上下3天。",
    status: str = "medically_confirmed",
    payload: dict | None = None,
    supersedes_fact_revision_id: str = "",
) -> ProtocolFact:
    fact = ProtocolFact.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_key=fact_key,
        fact_type="visit_window",
        status="ai_candidate",
        title="第4周访视窗口",
        normalized_payload=payload
        or {
            "deterministic_template": {
                "visit": "W4",
                "window_before_days": 3,
                "window_after_days": 3,
            }
        },
        source_entry_id=version.source_entry_id,
        source_locator="docx:table:1:row:4",
        source_text=source_text,
        supersedes_fact_revision_id=supersedes_fact_revision_id,
    )
    stored = repository.store_fact(fact)
    if status == "medically_confirmed":
        return repository.transition_fact_status(
            stored.fact_revision_id,
            expected_state_version=stored.state_version,
            status="medically_confirmed",
            actor="medical_manager",
        )
    return stored


def _writing_journey(
    project_id: str,
    *,
    status: str = "confirmed",
    source_id: str = "source_synopsis_001",
    locator: str = "docx:paragraph:2",
    value: str = "类风湿关节炎",
    revision: int = 3,
    with_source: bool = True,
):
    evidence = (
        [
            SimpleNamespace(
                source_id=source_id,
                extraction_revision="synopsis_extract_v2",
                evidence_span_id="span_indication",
                locator=locator,
                quote_sha256=_sha("适应症：类风湿关节炎"),
            )
        ]
        if with_source
        else []
    )
    definition = SimpleNamespace(
        definition_id=f"mwdef_{project_id}",
        project_id=project_id,
        revision=revision,
        state_sha256=_sha(f"{project_id}:definition:{revision}"),
        framing={"indication": value},
        picos={},
        field_states={
            "framing.indication": SimpleNamespace(
                status=status,
                evidence=evidence,
                confirmed_by="medical_manager" if status == "confirmed" else "",
                confirmed_at=(
                    datetime(2026, 7, 29, tzinfo=timezone.utc)
                    if status == "confirmed"
                    else None
                ),
            )
        },
    )
    return SimpleNamespace(project_id=project_id, study_definition=definition)


class _JourneyReader:
    def __init__(self, journeys):
        self._journeys = dict(journeys)

    def get(self, project_id: str):
        if project_id not in self._journeys:
            raise KeyError(project_id)
        return self._journeys[project_id]


class _FixedReadAdapter:
    def __init__(self, module_name: str, records):
        self.module_name = module_name
        self._records = tuple(records)

    def read_confirmed(self, project_id: str):
        return tuple(
            item for item in self._records if item.project_id == project_id
        )


def _service(
    repository: MonitoringProtocolRuleRepository,
    journeys,
) -> SharedProtocolFactProjectionService:
    return SharedProtocolFactProjectionService(
        [
            MonitoringProtocolFactReadAdapter(repository),
            MedicalWritingProtocolFactReadAdapter(_JourneyReader(journeys)),
        ]
    )


def test_projects_dual_module_confirmed_facts_with_source_lineage(
    tmp_path: Path,
) -> None:
    project_id = "project_alpha"
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = _protocol_version(repository, project_id)
    monitoring_fact = _monitoring_fact(repository, version)
    service = _service(
        repository,
        {project_id: _writing_journey(project_id)},
    )

    projected = service.project(project_id, consumer="medical_writing")

    assert {item.confirmed_by_module for item in projected} == {
        "medical_monitoring",
        "medical_writing",
    }
    monitoring = next(
        item
        for item in projected
        if item.confirmed_by_module == "medical_monitoring"
    )
    assert monitoring.fact_path == "visit_window_w4"
    assert monitoring.source_entry_id == version.source_entry_id
    assert monitoring.source_revision == version.content_sha256
    assert monitoring.locator == "docx:table:1:row:4"
    assert monitoring.confirmed_revision == (
        f"{monitoring_fact.fact_revision_id}:state-2"
    )
    writing = next(
        item
        for item in projected
        if item.confirmed_by_module == "medical_writing"
    )
    assert writing.fact_path == "framing.indication"
    assert writing.value == "类风湿关节炎"
    assert writing.source_revision == "synopsis_extract_v2"
    assert writing.locator == "docx:paragraph:2"
    assert writing.status == "confirmed"
    assert service.project(project_id, consumer="medical_writing") == projected


def test_candidates_conflicts_unknown_and_source_less_writing_do_not_project(
    tmp_path: Path,
) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = _protocol_version(repository, "project_candidates")
    _monitoring_fact(
        repository,
        version,
        fact_key="candidate_only",
        status="ai_candidate",
    )

    for state in (
        "extracted_candidate",
        "manual_candidate",
        "conflict",
        "missing",
        "deferred",
    ):
        project_id = f"project_{state}"
        service = _service(
            repository,
            {project_id: _writing_journey(project_id, status=state)},
        )
        assert service.project(
            project_id,
            consumer="medical_monitoring",
        ) == ()

    source_less = "project_source_less"
    service = _service(
        repository,
        {
            source_less: _writing_journey(
                source_less,
                with_source=False,
            )
        },
    )
    assert service.project(
        source_less,
        consumer="medical_monitoring",
    ) == ()
    assert service.project(
        "project_candidates",
        consumer="medical_writing",
    ) == ()


def test_superseded_monitoring_revision_is_not_exposed(tmp_path: Path) -> None:
    project_id = "project_revision"
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = _protocol_version(repository, project_id)
    first = _monitoring_fact(
        repository,
        version,
        source_text="旧访视窗口为上下5天。",
    )
    second = _monitoring_fact(
        repository,
        version,
        source_text="修订后访视窗口为上下3天。",
        supersedes_fact_revision_id=first.fact_revision_id,
    )
    repository.transition_fact_status(
        first.fact_revision_id,
        expected_state_version=first.state_version,
        status="superseded",
        actor="medical_manager",
    )

    projected = SharedProtocolFactProjectionService(
        [MonitoringProtocolFactReadAdapter(repository)]
    ).project(project_id, consumer="medical_writing")

    assert len(projected) == 1
    assert second.fact_revision_id in projected[0].confirmed_revision
    assert first.fact_revision_id not in projected[0].confirmed_revision


def test_current_writing_revision_replaces_previous_projection(
    tmp_path: Path,
) -> None:
    project_id = "project_writing_revision"
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    journeys = {
        project_id: _writing_journey(
            project_id,
            value="类风湿关节炎",
            revision=2,
        )
    }
    reader = _JourneyReader(journeys)
    service = SharedProtocolFactProjectionService(
        [MedicalWritingProtocolFactReadAdapter(reader)]
    )
    old = service.project(project_id, consumer="medical_monitoring")
    journeys[project_id] = _writing_journey(
        project_id,
        value="银屑病关节炎",
        revision=3,
    )
    reader._journeys = journeys
    current = service.project(project_id, consumer="medical_monitoring")

    assert [item.value for item in old] == ["类风湿关节炎"]
    assert [item.value for item in current] == ["银屑病关节炎"]
    assert old[0].fact_id != current[0].fact_id
    assert all("revision-2" not in item.confirmed_revision for item in current)


def test_project_isolation_and_closed_consumer_allowlist(tmp_path: Path) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    alpha = _protocol_version(repository, "project_alpha")
    beta = _protocol_version(repository, "project_beta")
    _monitoring_fact(repository, alpha, fact_key="alpha_window")
    _monitoring_fact(repository, beta, fact_key="beta_window")
    service = _service(
        repository,
        {
            "project_alpha": _writing_journey("project_alpha"),
            "project_beta": _writing_journey(
                "project_beta",
                value="系统性红斑狼疮",
            ),
        },
    )

    alpha_projection = service.project(
        "project_alpha",
        consumer="medical_monitoring",
    )
    assert {item.project_id for item in alpha_projection} == {"project_alpha"}
    assert all("beta" not in item.fact_path for item in alpha_projection)

    dashboard = service.project("project_alpha", consumer="dashboard")
    assert dashboard
    assert {item.confirmed_by_module for item in dashboard} == {
        "medical_writing"
    }
    with pytest.raises(ValueError, match="consumer must be"):
        service.project("project_alpha", consumer="safety_pv")


def test_conflicting_confirmed_values_for_same_semantic_key_fail_closed() -> None:
    common = dict(
        project_id="project_conflict",
        fact_type="study_definition",
        fact_path="framing.indication",
        source_revision="revision-1",
        locator="docx:paragraph:2",
        confirmed_revision="confirmed-revision-1",
    )
    monitoring_record = ConfirmedProtocolFactRecord(
        **common,
        value="类风湿关节炎",
        source_entry_id="source_monitoring",
        confirmed_by_module="medical_monitoring",
    )
    writing_record = ConfirmedProtocolFactRecord(
        **common,
        value="银屑病关节炎",
        source_entry_id="source_writing",
        confirmed_by_module="medical_writing",
    )
    service = SharedProtocolFactProjectionService(
        [
            _FixedReadAdapter("medical_monitoring", [monitoring_record]),
            _FixedReadAdapter("medical_writing", [writing_record]),
        ]
    )

    assert service.project(
        "project_conflict",
        consumer="medical_writing",
    ) == ()


def test_unsafe_metadata_and_local_paths_never_enter_dto(tmp_path: Path) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    version = _protocol_version(repository, "project_unsafe")
    _monitoring_fact(
        repository,
        version,
        fact_key="prompt_leak",
        payload={
            "deterministic_template": {
                "system_prompt": "internal instruction",
                "threshold": 3,
            }
        },
    )
    unsafe_writing = _writing_journey(
        "project_unsafe_writing",
        locator="/Users/example/private/protocol.docx",
    )
    service = _service(
        repository,
        {"project_unsafe_writing": unsafe_writing},
    )

    assert service.project(
        "project_unsafe",
        consumer="medical_writing",
    ) == ()
    assert service.project(
        "project_unsafe_writing",
        consumer="medical_monitoring",
    ) == ()
    assert [item.name for item in fields(SharedProtocolFactDTO)] == [
        "fact_id",
        "project_id",
        "fact_type",
        "fact_path",
        "value",
        "source_entry_id",
        "source_revision",
        "locator",
        "confirmed_by_module",
        "confirmed_revision",
        "consumer",
        "status",
    ]
    with pytest.raises(UnsafeProtocolFactProjection):
        SharedProtocolFactDTO(
            fact_id="sharedpf_" + "a" * 32,
            project_id="project_direct",
            fact_type="study_definition",
            fact_path="framing.indication",
            value={"internal_log": "must not cross the boundary"},
            source_entry_id="source_001",
            source_revision="revision_001",
            locator="/private/tmp/source.docx",
            confirmed_by_module="medical_writing",
            confirmed_revision="definition_001:revision-1",
            consumer="medical_monitoring",
        )


def test_projection_adapters_expose_no_write_methods(tmp_path: Path) -> None:
    repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    adapters = (
        MonitoringProtocolFactReadAdapter(repository),
        MedicalWritingProtocolFactReadAdapter(_JourneyReader({})),
    )
    forbidden_verbs = (
        "create",
        "delete",
        "insert",
        "save",
        "store",
        "transition",
        "update",
        "write",
    )

    for adapter in adapters:
        public_callables = {
            name
            for name in dir(adapter)
            if not name.startswith("_") and callable(getattr(adapter, name))
        }
        assert public_callables == {"read_confirmed"}
        assert not any(
            name.startswith(forbidden_verbs) for name in public_callables
        )
