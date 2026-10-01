"""AGG25-P0-2: entry-B synopsis import route freeze must cover the whole
fallback chain, refreeze on drift instead of dead-ending, classify failures
structurally, and never silently bypass the arbiter for managed endpoints.
"""
from __future__ import annotations

import importlib
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MTPLX_V1 = "http://127.0.0.1:8002/v1"


def _service(tmp_path):
    from services.api.app.medical_writing_synopsis_import import (
        MedicalWritingSynopsisImportService,
    )

    return MedicalWritingSynopsisImportService(
        artifact_root=tmp_path / "artifacts",
        ai_task_runner=SimpleNamespace(policy_resolver=None),
        db_path=tmp_path / "jobs.sqlite3",
    )


def _identity(provider="omlx", model="m-primary", base_url=MTPLX_V1,
              profile_id="primary", revision=3):
    return {
        "schema_version": "independent_ai_route_snapshot_v1",
        "role_id": "independent_ai",
        "profile_id": profile_id,
        "profile_revision": revision,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "transport": "openai_compatible",
        "expected_response_model": model,
        "deployment_profile": "local",
    }


def _normalized(candidate):
    from services.api.app.medical_writing_synopsis_import import (
        _normalize_route_snapshot,
    )

    snapshot, _hash = _normalize_route_snapshot(candidate)
    return snapshot


def _run(hash_value):
    return SimpleNamespace(
        route_identity_hash=hash_value,
        run_id="run-1",
        actual_response_model="m",
        provider="omlx",
        model_name="m",
        status="completed",
        validation_errors=[],
        error_message="",
        artifacts=[],
    )


def test_frozen_chain_accepts_fallback_run_hash(tmp_path):
    service = _service(tmp_path)
    primary = _normalized(_identity())
    fallback = _normalized(_identity(provider="deepseek", model="m-fallback",
                                     base_url="https://cloud.example/v1",
                                     profile_id="fb1"))
    frozen = {**primary, "fallback_chain": [fallback]}
    run = _run(fallback["identity_sha256"])
    run_id, _, _ = service._validate_ai_run_route(run, frozen)
    assert run_id == "run-1"


def test_frozen_chain_still_rejects_outside_routes(tmp_path):
    service = _service(tmp_path)
    primary = _normalized(_identity())
    run = _run("0" * 64)
    with pytest.raises(RuntimeError, match="frozen synopsis route"):
        service._validate_ai_run_route(run, primary)


def test_reconcile_accepts_current_route_inside_frozen_chain(tmp_path):
    service = _service(tmp_path)
    primary = _normalized(_identity())
    fallback = _normalized(_identity(provider="deepseek", model="m-fallback",
                                     base_url="https://cloud.example/v1",
                                     profile_id="fb1"))
    frozen = {**primary, "fallback_chain": [fallback]}

    class _Resolver:
        def route_identity_snapshot(self, refresh=True):
            return fallback

    service.ai_task_runner = SimpleNamespace(policy_resolver=_Resolver())
    snap, hash_value = service._reconcile_route(frozen, primary["identity_sha256"])
    assert hash_value == primary["identity_sha256"]


def test_reconcile_refreezes_when_route_left_the_frozen_chain(tmp_path):
    service = _service(tmp_path)
    primary = _normalized(_identity())
    drifted = _normalized(_identity(model="m-new", profile_id="new-primary"))

    class _Resolver:
        def route_identity_snapshot(self, refresh=True):
            return drifted

    service.ai_task_runner = SimpleNamespace(policy_resolver=_Resolver())
    snap, hash_value = service._reconcile_route(
        primary, primary["identity_sha256"])
    assert hash_value == drifted["identity_sha256"]
    assert hash_value != primary["identity_sha256"]


def test_failure_codes_are_structured():
    from services.api.app.medical_writing_synopsis_import import (
        _classify_import_failure,
    )

    offline = urllib.error.URLError("connection refused")
    assert _classify_import_failure(offline) == "local_model_offline"
    drifted = RuntimeError(
        "synopsis import route configuration changed after task start")
    assert _classify_import_failure(drifted) == "route_config_changed"
    binding = RuntimeError(
        "binding_base_url_mismatch: 8000/v1 vs managed 8001")
    assert _classify_import_failure(binding) == "binding_mismatch"
    assert _classify_import_failure(ValueError("x")) == "import_failed"


def test_gateway_fail_closed_when_arbiter_unresolved(monkeypatch, tmp_path):
    gw = importlib.import_module("services.api.app.ai_gateway")
    orch_mod = importlib.import_module(
        "services.api.app.model_lifecycle_orchestrator")
    orch_mod.reset_managed_cache({MTPLX_V1})

    class _Broken:
        def handles_endpoint(self, base_url):
            raise RuntimeError("arbiter exploded")

    class _Resp:
        status = 200

        def read(self):
            return json.dumps({
                "model": "m",
                "choices": [{"message": {"role": "assistant",
                                         "content": "{\"ok\": true}"}}],
            }).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(gw.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp())
    orch_mod.set_arbiter(_Broken())
    try:
        provider = gw.OpenAICompatibleAiProvider(
            base_url=MTPLX_V1, api_key="k", model_name="m", max_attempts=1)
        envelope = gw.AiPromptEnvelope(
            task_id="t", task_type=gw.AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="v1", system_prompt="s", payload={"x": 1})
        with pytest.raises(gw.AiProviderRuntimeError) as excinfo:
            provider.run(envelope)
        code = (getattr(excinfo.value, "diagnostics", {}) or {}).get(
            "failure_code")
        assert code == "managed_arbiter_unavailable", code

        # a non-managed endpoint still dispatches untouched
        cloud = gw.OpenAICompatibleAiProvider(
            base_url="https://cloud.example/v1", api_key="k", model_name="m",
            max_attempts=1)
        assert cloud.run(envelope) == {"ok": True}
    finally:
        orch_mod.set_arbiter(None)
        orch_mod.reset_managed_cache(None)


# ---------------------------------------------------------------------------
# Deferred paths (round25 retest open P0): the chunk worker / cold recovery /
# resume paths kept calling the removed `_assert_current_route_matches`, so
# every entry-B chunk AI call crashed with AttributeError.  All three paths
# must use the same reconcile contract as the sync path: accept any route
# inside the frozen chain, re-freeze (persisted) on drift, never dead-end.
# ---------------------------------------------------------------------------

_DOCX_CT = ("application/vnd.openxmlformats-officedocument.wordprocessingml"
            ".document")


def _docx_bytes(text: str) -> bytes:
    import io
    import zipfile

    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>方案摘要</w:t></w:r></w:p><w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:sectPr/></w:body>
</w:document>'''.encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _provider_payload() -> dict:
    return {
        "task_id": "fake_chunk",
        "task_type": "protocol_synopsis_structuring",
        "provider": "omlx",
        "model": "m",
        "prompt_version": "protocol_synopsis_structuring_v0_9",
        "input_source_ids": [],
        "forbidden_source_ids": [],
        "findings": [],
        "evidence_spans": [],
        "uncertainties": [],
        "needs_medical_confirmation": True,
        "schema_version": "ai_task_output_v0_1",
        "study_definition": {
            "framing": {
                "protocol_id": "TEST-001",
                "document_title": "Test Synopsis",
                "indication": "测试适应症",
                "clinicaltrials_condition_term": "Test",
                "study_phase": "II期",
                "intrinsic_objectives": ["概念验证"],
                "investigational_product": "TEST-DRUG",
                "target_mechanism": "test",
                "design_pattern": "随机、双盲",
                "population_intent": "测试人群",
            },
            "picos": {
                "design_archetype": "randomized_confirmatory",
                "population_summary": "测试人群",
                "intervention_summary": "TEST-DRUG",
                "comparator_summary": "安慰剂",
                "primary_endpoint": "第12周应答率",
                "study_epochs": ["筛选期", "治疗期"],
                "assessment_instruments": [],
                "safety_endpoints": ["AE、SAE发生率"],
            },
            "synopsis_text": "本研究评价TEST-DRUG的安全性。",
            "missing_fields": [],
            "conflict_notes": [],
            "field_evidence_span_ids": {},
        },
    }


class _ScriptedRunner:
    """Runner stub with a scriptable effective route and run hash."""

    def __init__(self, snapshot, chain=None, run_hash=None):
        self._snapshot = snapshot
        self._chain = list(chain or [])
        self._run_hash = run_hash or snapshot["identity_sha256"]

    def route_identity_snapshot(self, refresh=True):
        return self._snapshot

    def fallback_chain_identities(self):
        return list(self._chain)

    def submit_internal(self, project_id, request):
        return SimpleNamespace(
            route_identity_hash=self._run_hash,
            run_id="run-1",
            actual_response_model="m",
            provider="omlx",
            model_name="m",
            status="completed",
            validation_errors=[],
            error_message="",
            artifacts=[SimpleNamespace(
                artifact_type="provider_output",
                payload=_provider_payload(),
            )],
        )


def _job_service(tmp_path, runner):
    from services.api.app.medical_writing_synopsis_import import (
        MedicalWritingSynopsisImportService,
    )

    return MedicalWritingSynopsisImportService(
        artifact_root=tmp_path / "artifacts",
        ai_task_runner=runner,
        db_path=tmp_path / "jobs.sqlite3",
    )


def _start_frozen_job(service, project_id, key):
    """Start a one-chunk import job with the auto worker suppressed; returns
    once the parse thread has persisted the job + chunk rows."""
    import time as _t

    service._shutdown_requested = True  # keep the auto-spawned worker away
    service.start_job(
        project_id,
        filename="synopsis.docx",
        content_type=_DOCX_CT,
        payload=_docx_bytes("方案摘要：测试适应症II期研究。"),
        expected_indication="测试适应症",
        actor="medical_manager",
        idempotency_key=key,
    )
    deadline = _t.monotonic() + 15.0
    while _t.monotonic() < deadline:
        with service._connect() as conn:
            row = conn.execute(
                "SELECT route_snapshot_json FROM medical_writing_synopsis_imports "
                "WHERE project_id=? AND idempotency_key=?",
                (project_id, key),
            ).fetchone()
            chunks = conn.execute(
                "SELECT COUNT(*) AS n FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id=? AND idempotency_key=?",
                (project_id, key),
            ).fetchone()
        if row and row["route_snapshot_json"] and chunks and int(chunks["n"]) >= 1:
            return
        _t.sleep(0.05)
    raise AssertionError("job/chunk rows were not persisted within 15s")


def _job_row(service, project_id, key):
    with service._connect() as conn:
        return conn.execute(
            "SELECT status, error_message, route_identity_hash "
            "FROM medical_writing_synopsis_imports "
            "WHERE project_id=? AND idempotency_key=?",
            (project_id, key),
        ).fetchone()


def _chunk_hashes(service, project_id, key):
    with service._connect() as conn:
        return [r["route_identity_hash"] for r in conn.execute(
            "SELECT route_identity_hash FROM medical_writing_synopsis_import_chunks "
            "WHERE project_id=? AND idempotency_key=? ORDER BY chunk_index",
            (project_id, key),
        ).fetchall()]


def test_chunk_worker_accepts_fallback_run_inside_frozen_chain(tmp_path):
    primary = _normalized(_identity())
    fallback = _normalized(_identity(provider="deepseek", model="m-fallback",
                                     base_url="https://cloud.example/v1",
                                     profile_id="fb1"))
    runner = _ScriptedRunner(primary, chain=[fallback],
                             run_hash=fallback["identity_sha256"])
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_chunk", "fw-chunk")
    with service._connect() as conn:
        job = conn.execute(
            "SELECT route_identity_hash FROM medical_writing_synopsis_imports "
            "WHERE project_id=? AND idempotency_key=?",
            ("proj_fw_chunk", "fw-chunk"),
        ).fetchone()
        source = service._load_source_from_db(
            conn, "proj_fw_chunk", "fw-chunk")
    service._shutdown_requested = False
    # Pre-fix this worker path raised AttributeError on every chunk AI call.
    service._run_chunked_worker(
        project_id="proj_fw_chunk", idempotency_key="fw-chunk",
        source_id=source.source_id, source=source, actor="medical_manager",
        expected_indication="测试适应症",
        route_identity_hash=job["route_identity_hash"],
    )
    row = _job_row(service, "proj_fw_chunk", "fw-chunk")
    assert row["status"] == "completed", row["error_message"]


def test_chunk_worker_refreezes_when_route_drifted_mid_job(tmp_path):
    primary = _normalized(_identity())
    drifted = _normalized(_identity(model="m-new", profile_id="new-primary"))
    runner = _ScriptedRunner(primary, chain=[],
                             run_hash=primary["identity_sha256"])
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_drift", "fw-drift")
    # the effective route drifts AFTER the job froze the primary route
    runner._snapshot = drifted
    runner._run_hash = drifted["identity_sha256"]
    with service._connect() as conn:
        source = service._load_source_from_db(conn, "proj_fw_drift", "fw-drift")
    service._shutdown_requested = False
    service._run_chunked_worker(
        project_id="proj_fw_drift", idempotency_key="fw-drift",
        source_id=source.source_id, source=source, actor="medical_manager",
        expected_indication="测试适应症",
        route_identity_hash=primary["identity_sha256"],
    )
    row = _job_row(service, "proj_fw_drift", "fw-drift")
    assert row["status"] == "completed", row["error_message"]
    assert row["route_identity_hash"] == drifted["identity_sha256"]
    assert _chunk_hashes(service, "proj_fw_drift", "fw-drift") == [
        drifted["identity_sha256"]]


def _mark_resume_ready(service, project_id, key):
    with service._connect() as connection:
        connection.execute(
            "UPDATE medical_writing_synopsis_imports "
            "SET status = 'failed', phase = 'failed' "
            "WHERE project_id=? AND idempotency_key=?",
            (project_id, key),
        )
        connection.execute(
            "UPDATE medical_writing_synopsis_import_chunks "
            "SET status = 'failed', attempt_count = 1 "
            "WHERE project_id=? AND idempotency_key=?",
            (project_id, key),
        )
        connection.commit()


def test_resume_reconciles_instead_of_attribute_error(tmp_path):
    primary = _normalized(_identity())
    runner = _ScriptedRunner(primary)
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_resume", "fw-resume")
    _mark_resume_ready(service, "proj_fw_resume", "fw-resume")
    # worker still suppressed: resume requeues without spawning
    service.resume_job("proj_fw_resume", "fw-resume", actor="medical_manager")
    row = _job_row(service, "proj_fw_resume", "fw-resume")
    assert row["status"] == "pending"
    assert row["error_message"] == ""
    assert row["route_identity_hash"] == primary["identity_sha256"]
    assert set(_chunk_hashes(service, "proj_fw_resume", "fw-resume")) == {
        primary["identity_sha256"]}


def test_resume_refreezes_drifted_route(tmp_path):
    primary = _normalized(_identity())
    drifted = _normalized(_identity(model="m-new", profile_id="new-primary"))
    runner = _ScriptedRunner(drifted)
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_resume2", "fw-resume2")
    _mark_resume_ready(service, "proj_fw_resume2", "fw-resume2")
    service.resume_job("proj_fw_resume2", "fw-resume2", actor="medical_manager")
    row = _job_row(service, "proj_fw_resume2", "fw-resume2")
    assert row["status"] == "pending"
    assert row["route_identity_hash"] == drifted["identity_sha256"]
    assert set(_chunk_hashes(service, "proj_fw_resume2", "fw-resume2")) == {
        drifted["identity_sha256"]}


def test_recovery_reconciles_instead_of_attribute_error(tmp_path):
    primary = _normalized(_identity())
    runner = _ScriptedRunner(primary)
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_rec", "fw-rec")
    with service._connect() as connection:
        connection.execute(
            "UPDATE medical_writing_synopsis_imports SET status = 'pending' "
            "WHERE project_id=? AND idempotency_key=?",
            ("proj_fw_rec", "fw-rec"),
        )
        connection.execute(
            "UPDATE medical_writing_synopsis_import_chunks "
            "SET status = 'running', "
            "lease_expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE project_id=? AND idempotency_key=?",
            ("proj_fw_rec", "fw-rec"),
        )
        connection.commit()
    requeued = service.recover_stale_jobs()
    assert requeued == 1
    row = _job_row(service, "proj_fw_rec", "fw-rec")
    assert row["status"] != "failed", row["error_message"]
    assert row["error_message"] == ""
    assert row["route_identity_hash"] == primary["identity_sha256"]


def test_recovery_refreezes_drifted_route(tmp_path):
    primary = _normalized(_identity())
    drifted = _normalized(_identity(model="m-new", profile_id="new-primary"))
    runner = _ScriptedRunner(drifted)
    service = _job_service(tmp_path, runner)
    _start_frozen_job(service, "proj_fw_rec2", "fw-rec2")
    with service._connect() as connection:
        connection.execute(
            "UPDATE medical_writing_synopsis_imports SET status = 'pending' "
            "WHERE project_id=? AND idempotency_key=?",
            ("proj_fw_rec2", "fw-rec2"),
        )
        connection.execute(
            "UPDATE medical_writing_synopsis_import_chunks "
            "SET status = 'running', "
            "lease_expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE project_id=? AND idempotency_key=?",
            ("proj_fw_rec2", "fw-rec2"),
        )
        connection.commit()
    requeued = service.recover_stale_jobs()
    assert requeued == 1
    row = _job_row(service, "proj_fw_rec2", "fw-rec2")
    assert row["status"] != "failed", row["error_message"]
    assert row["route_identity_hash"] == drifted["identity_sha256"]
    assert set(_chunk_hashes(service, "proj_fw_rec2", "fw-rec2")) == {
        drifted["identity_sha256"]}
