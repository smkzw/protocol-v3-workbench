"""Actual SQLite competing start between lookup and insert; no real provider."""
import hashlib
from app.protocol_workflow.agent1.research_seed import PreparedSeedRequest, prepare_seed_request
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.canonical.hashing import canonical_json
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body


def test_competing_compiler_start_returns_first_pinned_run_without_call(tmp_path):
    opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])
    factory = create_product_seed_factory(
        storage_config={'backend':'sqlite','path':str(tmp_path/'race.db')},
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=100_000, credential_resolver=lambda:'synthetic-key', http_opener=opener)
    original = prepare_seed_request('相同请求只整理一次', ())
    changed = original.to_payload()
    changed['output_schema']['title'] = 'another compiler package'
    text = canonical_json(changed)
    recompiled = PreparedSeedRequest(text, hashlib.sha256(text.encode()).hexdigest())
    loser = factory('seed-race-project')
    actual_start = loser.runtime.start_run
    winner = factory('seed-race-project')
    def winner_commits_between_lookup_and_insert(*args, **kwargs):
        winner.start(original)
        return actual_start(*args, **kwargs)
    loser.runtime.start_run = winner_commits_between_lookup_and_insert
    run_id = loser.start(recompiled)
    assert run_id == winner.run_id(original)
    assert opener.calls == 0
    from app.protocol_workflow.graph.runtime import EVENT_RUN_STARTED
    event = next(e for e in winner.runtime.read_events(run_id) if e.event_type == EVENT_RUN_STARTED)
    assert event.payload['root_payloads']['research_intake'] == original.to_payload()
    result = winner.resume(run_id)
    assert result['status'] == 'needs_information'
    assert opener.calls == 1
