"""Inject a crash after fake model return, before chunk persistence.

Only synthetic fixtures and a temporary real SQLite store; no external calls,
no real process is killed. This does not test the v3 reservation implementation.
"""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

fixtures = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tests/test_medical_writing_full_draft.py'))
case = fixtures['FullDraftServiceTests']()
case.setUp()
try:
    project = case.repo.project_id
    job_id, _ = case.full.submit_durable(project, case.store)
    claim = case.store.claim(project, job_id)
    executor = fixtures['ProtocolFullDraftExecutor'](case.full)
    with patch.object(case.full, '_write_json_atomic', side_effect=SystemExit('synthetic crash before chunk write')):
        try:
            executor.execute(claim.job, claim.claim_token, lambda: False, lambda _: True)
        except SystemExit:
            pass
        else:
            raise AssertionError('Expected injected crash window')
    assert case.runner.calls == 1
    assert case.store.get(project, job_id).status == 'running'
    future = datetime.now(timezone.utc) + timedelta(seconds=601)
    with patch('services.api.app.medical_writing_durable_jobs._utcnow', return_value=future):
        assert case.store.recover_on_startup() == 1
        resumed = case.store.claim(project, job_id)
        assert resumed.claimed
        result = executor.execute(resumed.job, resumed.claim_token, lambda: False, lambda _: True)
    assert not result.error, result.error
    assert case.runner.calls == 2
    print(json.dumps({'case': 'model_return_before_chunk_persistence_then_recovery',
                      'same_job_id': resumed.job.job_id == job_id,
                      'fake_model_calls': case.runner.calls, 'real_model_calls': 0,
                      'outcome': 'recovery executes missing chunk again'}, ensure_ascii=False))
finally:
    case.tearDown()
