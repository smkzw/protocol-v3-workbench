from __future__ import annotations

from hashlib import sha256
import json
from types import SimpleNamespace

from services.api.app import main as app_main
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_source_packet import MonitoringAiSourcePacket
from services.api.app.monitoring_ai_service import PROMPT_VERSION_BY_TASK
from services.api.app.monitoring_protocol_preparation_service import (
    PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS,
)


def test_startup_retires_old_prompt_contracts_before_waking_worker(
    monkeypatch,
) -> None:
    events: list[tuple[str, str, str, frozenset]] = []

    def supersede(
        *,
        task_type,
        current_prompt_version,
        legacy_terminal_prompt_versions=(),
    ):
        events.append(
            (
                "supersede",
                task_type.value,
                current_prompt_version,
                frozenset(legacy_terminal_prompt_versions),
            )
        )
        return 0

    monkeypatch.setattr(
        app_main.monitoring_ai_repository,
        "supersede_prompt_versions_except",
        supersede,
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_repository,
        "expire_exhausted_leases",
        lambda: events.append(("expire", "", "", frozenset())),
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_worker,
        "wake",
        lambda: events.append(("wake", "", "", frozenset())),
    )

    app_main._recover_monitoring_ai_jobs()

    expected = [
        (
            "supersede",
            task_type.value,
            PROMPT_VERSION_BY_TASK[task_type],
            (
                PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
                if task_type
                == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
                else frozenset()
            ),
        )
        for task_type in MonitoringAiTaskType
    ]
    assert events == expected + [
        ("expire", "", "", frozenset()),
        ("wake", "", "", frozenset()),
    ]


def test_source_job_recovery_preserves_pre_fact_revision_hash(
    monkeypatch,
) -> None:
    current_revision = MonitoringAiInputRevision(
        project_id="project-recovery",
        batch_revision="source-registry:revision-a",
        protocol_version="protocol-revision-a",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-protocol",
                source_content_sha256="a" * 64,
            ),
        ),
    )
    legacy_payload = current_revision.model_dump(
        mode="json",
        exclude={"fact_revision", "source_binding_revision"},
    )
    legacy_hash = sha256(
        json.dumps(
            legacy_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert legacy_hash == current_revision.revision_sha256

    job = SimpleNamespace(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        project_id="project-recovery",
        job_id="job-recovery",
        input_revision=current_revision,
        input_revision_sha256=legacy_hash,
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_repository,
        "input_payload",
        lambda _project_id, _job_id: {"source_ids": ["span-1"]},
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_source_packet_resolver,
        "resolve",
        lambda _project_id, _source_ids: MonitoringAiSourcePacket(
            input_revision=current_revision,
            source_ids=("span-1",),
            evidence_packet=(),
        ),
    )

    assert app_main._current_monitoring_ai_revision(job) == legacy_hash


def test_nonempty_fact_revision_remains_part_of_revision_hash() -> None:
    base = MonitoringAiInputRevision(
        project_id="project-recovery",
        protocol_version="protocol-revision-a",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-protocol",
                source_content_sha256="a" * 64,
            ),
        ),
    )
    fact_bound = base.model_copy(update={"fact_revision": "fact-1:v2"})

    assert fact_bound.revision_sha256 != base.revision_sha256


def test_nonempty_source_binding_revision_remains_part_of_hash() -> None:
    base = MonitoringAiInputRevision(
        project_id="project-recovery",
        batch_revision="batch-revision-a",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256="b" * 64,
            ),
        ),
    )
    binding_bound = base.model_copy(
        update={"source_binding_revision": "source-binding:revision-a"}
    )

    assert binding_bound.revision_sha256 != base.revision_sha256


def test_main_listing_revision_path_delegates_to_lightweight_helper(
    monkeypatch,
) -> None:
    revision = MonitoringAiInputRevision(
        project_id="project-recovery",
        batch_revision="batch-revision-a",
    )
    job = SimpleNamespace(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        project_id="project-recovery",
        job_id="job-listing-recovery",
        input_revision=revision,
        input_revision_sha256=revision.revision_sha256,
    )
    calls = []
    monkeypatch.setattr(
        app_main,
        "current_monitoring_ai_revision",
        lambda repository, batch_repository, current_job: (
            calls.append((repository, batch_repository, current_job))
            or "c" * 64
        ),
    )

    assert app_main._current_monitoring_ai_revision(job) == "c" * 64
    assert calls == [
        (
            app_main.monitoring_ai_repository,
            app_main.monitoring_batch_repository,
            job,
        )
    ]


def test_source_job_recovery_detects_real_revision_change(
    monkeypatch,
) -> None:
    frozen_revision = MonitoringAiInputRevision(
        project_id="project-recovery",
        protocol_version="protocol-revision-a",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-protocol",
                source_content_sha256="a" * 64,
            ),
        ),
    )
    current_revision = frozen_revision.model_copy(
        update={
            "sources": (
                MonitoringAiSourceBinding(
                    source_entry_id="source-protocol",
                    source_content_sha256="b" * 64,
                ),
            )
        }
    )
    job = SimpleNamespace(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        project_id="project-recovery",
        job_id="job-recovery",
        input_revision=frozen_revision,
        input_revision_sha256=frozen_revision.revision_sha256,
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_repository,
        "input_payload",
        lambda _project_id, _job_id: {"source_ids": ["span-1"]},
    )
    monkeypatch.setattr(
        app_main.monitoring_ai_source_packet_resolver,
        "resolve",
        lambda _project_id, _source_ids: MonitoringAiSourcePacket(
            input_revision=current_revision,
            source_ids=("span-1",),
            evidence_packet=(),
        ),
    )

    assert (
        app_main._current_monitoring_ai_revision(job)
        == current_revision.revision_sha256
    )
