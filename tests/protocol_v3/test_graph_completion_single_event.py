"""Two recovery readers must publish one completion for the same durable results."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_graph_runtime import _runtime, _probe_services, _probe_plan, _root_inputs


def test_two_stale_completion_views_append_once(tmp_path, monkeypatch):
    executions = {}
    runtime = _runtime(tmp_path, _probe_services(executions))
    plan = _probe_plan()
    run = 'run:single-completion'
    runtime.start_run(plan, workflow_run_id=run, root_inputs=_root_inputs())
    runtime.run_to_completion(run)
    runtime.record_decision(run, node_id='lock_node', decision_id='decision:complete',
        actor_id='user:synthetic', value={'approved':True}, reason='合成恢复测试')
    # Hold precisely the gap after the last result and before completion.
    with monkeypatch.context() as patch:
        patch.setattr(type(runtime), '_finish_run_if_complete', lambda *args: None)
        runtime.advance(run)
    assert not any(e.event_type == 'graph_run_completed' for e in runtime.read_events(run))
    runtimes = [_runtime(tmp_path, _probe_services(executions)) for _ in range(2)]
    views = [r._load(run, caller_plan=plan) for r in runtimes]
    barrier = Barrier(2)
    def finish(index):
        barrier.wait(timeout=5)
        runtimes[index]._finish_run_if_complete(run, views[index])
    before = dict(executions)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finish, range(2)))
    events = runtime.read_events(run)
    assert sum(e.event_type == 'graph_run_completed' for e in events) == 1
    assert executions == before
    assert runtime.load_run(plan, run).status.value == 'completed'
