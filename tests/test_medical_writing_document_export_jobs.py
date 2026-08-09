from __future__ import annotations

import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import pytest

from packages.contracts.workbench_contracts import (
    DurableJobNotFound,
    DurableJobRequestConflict,
)
from services.api.app.medical_writing_document_export_jobs import (
    DOCUMENT_EXPORT_JOB_TYPE,
    MedicalWritingDocumentExportArtifactUnavailable,
    MedicalWritingDocumentExportCallbacks,
    MedicalWritingDocumentExportJobService,
    MedicalWritingRenderedDocument,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobWorker,
)


PROJECT_A = "project-docx-a"
PROJECT_B = "project-docx-b"
DOCX_BYTES = b"PK\x03\x04fake-docx-package"


@dataclass
class CallbackHarness:
    fail_stage: str = ""
    block_stage: str = ""
    calls: list[str] = field(default_factory=list)
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)

    def _run(self, stage: str, value):
        self.calls.append(stage)
        if self.block_stage == stage:
            self.entered.set()
            assert self.release.wait(3.0)
        if self.fail_stage == stage:
            raise RuntimeError(f"{stage} failed")
        return value

    def callbacks(self) -> MedicalWritingDocumentExportCallbacks:
        return MedicalWritingDocumentExportCallbacks(
            verify_export_conditions=lambda context: self._run(
                "verify",
                {"project_id": context.project_id, "mode": context.mode},
            ),
            assemble_sections=lambda context, verified: self._run(
                "assemble",
                {**verified, "sections": ["方案标题", "研究设计"]},
            ),
            process_sources_and_citations=lambda context, assembled: self._run(
                "sources",
                {**assembled, "references": ["ref-1"]},
            ),
            render_docx=lambda context, prepared: self._run(
                "render",
                MedicalWritingRenderedDocument(
                    content=DOCX_BYTES,
                    filename=f"{context.project_id}-{context.mode}.docx",
                    metadata={
                        "mode": context.mode,
                        "section_count": len(prepared["sections"]),
                        "reference_count": len(prepared["references"]),
                    },
                ),
            ),
        )


@dataclass
class ServiceFixture:
    root: Path
    harness: CallbackHarness

    def __post_init__(self):
        self.store = DurableJobStore(
            self.root / "jobs.sqlite3",
            lease_seconds=5.0,
            heartbeat_interval_seconds=0.05,
        )
        self.worker = DurableJobWorker(
            self.store,
            enable_sweeper=False,
        )
        self.service = MedicalWritingDocumentExportJobService(
            self.store,
            self.worker,
            self.root / "artifacts",
            self.harness.callbacks(),
        )

    def close(self):
        self.worker.shutdown(timeout=2.0)


def _wait_for_status(service, project_id, job_id, expected, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = service.status(project_id, job_id)
        if record.status == expected:
            return record
        time.sleep(0.01)
    record = service.status(project_id, job_id)
    raise AssertionError(
        f"job did not reach {expected}: {record.status} {record.error_summary}"
    )


def _start(service, project_id=PROJECT_A, key="export-001", **kwargs):
    return service.start(
        project_id,
        mode=kwargs.pop("mode", "draft_preview"),
        idempotency_key=key,
        actor="medical_manager_test",
        payload=kwargs.pop("payload", {"document_revision": 7}),
        input_hash=kwargs.pop("input_hash", "a" * 64),
        **kwargs,
    )


def test_executes_five_real_stages_with_stable_monotonic_progress(tmp_path):
    harness = CallbackHarness(block_stage="render")
    fixture = ServiceFixture(tmp_path, harness)
    captured_progress = []
    real_heartbeat = fixture.store.heartbeat

    def capture_heartbeat(
        project_id,
        job_id,
        claim_token,
        progress=None,
    ):
        if progress is not None:
            captured_progress.append(progress)
        return real_heartbeat(project_id, job_id, claim_token, progress)

    fixture.store.heartbeat = capture_heartbeat
    try:
        started = _start(fixture.service)
        assert harness.entered.wait(2.0)

        running = fixture.service.status(PROJECT_A, started.job_id)
        assert running.status == "running"
        assert running.progress.phase == "rendering_docx"
        assert running.progress.step == 4
        assert running.progress.step_total == 5
        assert running.progress.percent == pytest.approx(0.65)
        assert running.progress.message == "正在渲染 DOCX 文档"

        harness.release.set()
        completed = _wait_for_status(
            fixture.service, PROJECT_A, started.job_id, "completed"
        )
        assert harness.calls == ["verify", "assemble", "sources", "render"]
        assert completed.progress.phase == "completed"
        assert completed.progress.step == 5
        assert completed.progress.step_total == 5
        assert completed.progress.percent == 1.0
        assert completed.progress.message == "DOCX 导出已完成"
        stage_progress = captured_progress[:6]
        assert [item.phase for item in stage_progress] == [
            "validating_export",
            "assembling_sections",
            "processing_sources_and_citations",
            "rendering_docx",
            "hashing_and_packaging",
            "completed",
        ]
        assert [item.step for item in stage_progress] == [1, 2, 3, 4, 5, 5]
        assert all(item.step_total == 5 for item in stage_progress)
        assert [item.percent for item in stage_progress] == sorted(
            item.percent for item in stage_progress
        )
        assert all(item.message for item in stage_progress)
    finally:
        harness.release.set()
        fixture.close()


def test_completed_artifact_is_external_to_sqlite_and_survives_service_refresh(
    tmp_path,
):
    fixture = ServiceFixture(tmp_path, CallbackHarness())
    try:
        started = _start(fixture.service)
        completed = _wait_for_status(
            fixture.service, PROJECT_A, started.job_id, "completed"
        )
        assert completed.job_type == DOCUMENT_EXPORT_JOB_TYPE
        assert completed.output_hash
        assert "fake-docx-package" not in completed.payload_json
        first_artifact = fixture.service.read_artifact(
            PROJECT_A, started.job_id
        )
        assert first_artifact.path.read_bytes() == DOCX_BYTES
        assert first_artifact.path.is_file()
        assert first_artifact.size_bytes == len(DOCX_BYTES)
        assert first_artifact.metadata["section_count"] == 2

        with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
            row = connection.execute(
                "SELECT payload_json, artifact_locator FROM durable_mw_jobs "
                "WHERE job_id = ?",
                (started.job_id,),
            ).fetchone()
        assert DOCX_BYTES not in row[0].encode("utf-8")
        assert DOCX_BYTES not in row[1].encode("utf-8")
    finally:
        fixture.close()

    refreshed = ServiceFixture(tmp_path, CallbackHarness(fail_stage="verify"))
    try:
        recovered_status = refreshed.service.status(PROJECT_A, started.job_id)
        assert recovered_status.status == "completed"
        recovered_artifact = refreshed.service.read_artifact(
            PROJECT_A, started.job_id
        )
        assert recovered_artifact.sha256 == completed.output_hash
        assert recovered_artifact.path.read_bytes() == DOCX_BYTES
        assert refreshed.harness.calls == []
    finally:
        refreshed.close()


@pytest.mark.parametrize(
    ("fail_stage", "phase", "step", "percent", "stage_label"),
    [
        (
            "sources",
            "processing_sources_and_citations",
            3,
            0.45,
            "处理来源/引用",
        ),
        ("render", "rendering_docx", 4, 0.65, "渲染 DOCX"),
    ],
)
def test_failure_preserves_last_progress_and_identifies_stage(
    tmp_path,
    fail_stage,
    phase,
    step,
    percent,
    stage_label,
):
    fixture = ServiceFixture(tmp_path, CallbackHarness(fail_stage=fail_stage))
    try:
        started = _start(fixture.service, key=f"fail-{fail_stage}")
        failed = _wait_for_status(
            fixture.service, PROJECT_A, started.job_id, "failed"
        )
        assert failed.progress.phase == phase
        assert failed.progress.step == step
        assert failed.progress.step_total == 5
        assert failed.progress.percent == pytest.approx(percent)
        assert failed.progress.percent < 1.0
        assert f"阶段：{stage_label}" in failed.error_summary
        assert not list((tmp_path / "artifacts").rglob("*.docx"))
        with pytest.raises(MedicalWritingDocumentExportArtifactUnavailable):
            fixture.service.read_artifact(PROJECT_A, started.job_id)
    finally:
        fixture.close()


def test_start_is_idempotent_rejects_changed_request_and_isolates_projects(
    tmp_path,
):
    harness = CallbackHarness(block_stage="verify")
    fixture = ServiceFixture(tmp_path, harness)
    try:
        first = _start(fixture.service, key="same-key")
        assert harness.entered.wait(2.0)
        duplicate = _start(fixture.service, key="same-key")
        assert duplicate.job_id == first.job_id
        assert duplicate.reused is True

        with pytest.raises(DurableJobRequestConflict):
            _start(
                fixture.service,
                key="same-key",
                payload={"document_revision": 8},
            )

        other_project = _start(
            fixture.service,
            project_id=PROJECT_B,
            key="same-key",
        )
        assert other_project.job_id != first.job_id
        with pytest.raises(DurableJobNotFound):
            fixture.service.status(PROJECT_B, first.job_id)
        with pytest.raises(DurableJobNotFound):
            fixture.service.status(PROJECT_A, other_project.job_id)
    finally:
        harness.release.set()
        fixture.close()


def test_queued_job_recovers_after_worker_refresh(tmp_path):
    first = ServiceFixture(tmp_path, CallbackHarness())
    try:
        started = _start(first.service, key="recover-queued", wake=False)
        assert first.service.status(PROJECT_A, started.job_id).status == "queued"
    finally:
        first.close()

    refreshed = ServiceFixture(tmp_path, CallbackHarness())
    try:
        assert refreshed.service.recover() >= 1
        completed = _wait_for_status(
            refreshed.service,
            PROJECT_A,
            started.job_id,
            "completed",
        )
        assert completed.progress.percent == 1.0
        assert refreshed.service.read_artifact(
            PROJECT_A, started.job_id
        ).path.read_bytes() == DOCX_BYTES
    finally:
        refreshed.close()


def test_artifact_reader_rejects_cross_project_and_tampering(tmp_path):
    fixture = ServiceFixture(tmp_path, CallbackHarness())
    try:
        started = _start(fixture.service, key="integrity")
        _wait_for_status(fixture.service, PROJECT_A, started.job_id, "completed")
        with pytest.raises(DurableJobNotFound):
            fixture.service.read_artifact(PROJECT_B, started.job_id)

        artifact = fixture.service.read_artifact(PROJECT_A, started.job_id)
        artifact.path.write_bytes(b"PK\x03\x04tampered")
        with pytest.raises(
            MedicalWritingDocumentExportArtifactUnavailable,
            match="integrity check failed",
        ):
            fixture.service.read_artifact(PROJECT_A, started.job_id)
    finally:
        fixture.close()
