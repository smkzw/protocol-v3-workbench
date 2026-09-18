"""Read-only projection shared by source and design proposal graphs."""


def proposal_outcome(runtime, plan, run_id, validator_node_id, *, snapshot=None, refresh_once=True):
    snapshot = snapshot or runtime.load_run(plan, run_id)
    if snapshot.status.value == "blocked":
        blocked = [node for node in snapshot.nodes if node.status.value in {"blocked_unknown", "failed"}]
        if blocked and all(node.status.value == "blocked_unknown" and runtime.node_has_live_dispatch(run_id, node.node_id)
                           for node in blocked):
            return {"status":"running", "validation":None, "can_resume":False}
        if refresh_once:
            # The owner may have committed just before releasing its lease.
            return proposal_outcome(runtime, plan, run_id, validator_node_id,
                                    snapshot=runtime.load_run(plan,run_id), refresh_once=False)
    if snapshot.status.value != "completed":
        return {"status":snapshot.status.value, "validation":None,
                "can_resume":snapshot.status.value == "running"}
    validation = next(e.payload["output"] for e in reversed(runtime.read_events(run_id))
                      if e.event_type == "graph_node_result" and e.payload["node_id"] == validator_node_id)
    return {"status":validation["status"], "validation":validation, "can_resume":False}
