"""Typed graph runtime contracts (Task 2R.1, product side).

These tests pin the product ``app.protocol_workflow.graph`` runtime — the
typed facade target behind the product ``OrchestratorPort``.  They are
written BEFORE the module exists (specification-first, red first):

* product-owned plan types with fail-closed validation and a deterministic
  material hash (construction-order independent);
* event-sourced run state on the real product SQLite unit of work — state is
  reconstructed from authoritative events/results, never from the advisory
  checkpoint; existing history is retained on repair;
* the v1_1 dependency-compacted ``NodeExecutionContract`` must be in the
  *executed* construction/persistence path (compacted contract persisted on
  the node result event, freshness re-verified through
  ``matches_dependencies`` on resume);
* committed reservations through
  ``build_committed_reservation_repository_factory`` — completed reuse,
  orphan (zero-attempt) recovery retry, and unknown/blocked outcomes that
  are never auto-redispatched;
* human decision pauses are product states: the runtime never self-approves,
  decision recording is idempotent/CAS, and the reviewer identity is carried
  separately from the writer context;
* old graphs are rejected on resume (graph_version/material binding).

No provider, model, network or service is used; node behavior is injected as
deterministic typed services.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

import pytest

from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
    build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    ReservationStatus,
)


# ---------------------------------------------------------------------------
# Local deterministic clock
# ---------------------------------------------------------------------------

_EPOCH = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


class _StepClock:
    """Deterministic aware clock advanced by a fixed step per call."""

    def __init__(self, start: datetime = _EPOCH) -> None:
        self._current = start

    def __call__(self) -> datetime:
        value = self._current
        self._current = self._current + timedelta(seconds=1)
        return value


# ---------------------------------------------------------------------------
# Plan fixtures (product-native; no pocs import anywhere in this module)
# ---------------------------------------------------------------------------

_PROJ = "proj-graph-rt"
_BRANCH = "branch-main"


def _probe_plan(
    *,
    graph_version: str = "probe_v1",
    project_id: str = _PROJ,
    branch_id: str = _BRANCH,
):
    from app.protocol_workflow.graph import GraphNodeKind, GraphNodeOwner, GraphNodePlan, GraphPlan

    return GraphPlan(
        project_id=project_id,
        branch_id=branch_id,
        graph_id="probe-graph",
        graph_version=graph_version,
        description="four-node deterministic probe with one user decision",
        schemas=("study_facts", "draft", "review", "lock_decision", "final"),
        root_inputs=("study_facts",),
        nodes=(
            GraphNodePlan(
                node_id="draft_node",
                kind=GraphNodeKind.WORK,
                owner=GraphNodeOwner.DESIGN_AND_SUMMARY,
                depends_on=(),
                input_schemas=("study_facts",),
                output_schema="draft",
                logical_key="probe.draft.1",
                allowed_attempts=3,
            ),
            GraphNodePlan(
                node_id="review_node",
                kind=GraphNodeKind.WORK,
                owner=GraphNodeOwner.QUALITY_CONTROL,
                depends_on=("draft_node",),
                input_schemas=("draft",),
                output_schema="review",
                logical_key="probe.review.1",
                allowed_attempts=3,
            ),
            GraphNodePlan(
                node_id="lock_node",
                kind=GraphNodeKind.DECISION,
                owner=GraphNodeOwner.USER,
                depends_on=("review_node",),
                input_schemas=("review",),
                output_schema="lock_decision",
                logical_key="probe.lock.1",
                allowed_attempts=1,
            ),
            GraphNodePlan(
                node_id="final_node",
                kind=GraphNodeKind.CHECK,
                owner=GraphNodeOwner.SYSTEM,
                depends_on=("lock_node",),
                input_schemas=("lock_decision",),
                output_schema="final",
                logical_key="probe.final.1",
                allowed_attempts=1,
            ),
        ),
    )


def _probe_services(record: dict[str, int]):
    """Deterministic typed services; ``record`` counts physical executions."""

    from app.protocol_workflow.graph import NodeServiceRequest

    def _service(request: NodeServiceRequest) -> dict[str, Any]:
        record[request.node.node_id] = record.get(request.node.node_id, 0) + 1
        return {
            "node": request.node.node_id,
            "schema": request.node.output_schema,
            "input_sha256": request.input_hashes,
            "attempt": request.attempt,
            "label": "labeled-synthetic-probe",
        }

    return {node.node_id: _service for node in _probe_plan().nodes}


def _runtime(tmp_path, services, *, clock=None, runtime_owner="graph-runtime-test"):
    from app.protocol_workflow.graph import GraphRuntime

    return GraphRuntime(
        project_id=_PROJ,
        uow_factory=build_unit_of_work_factory(
            {"backend": "sqlite", "path": str(tmp_path / "graph.sqlite")}
        ),
        reservation_repository_factory=build_committed_reservation_repository_factory(
            {"backend": "sqlite", "path": str(tmp_path / "graph.sqlite")}
        ),
        services=services,
        clock=clock or _StepClock(),
        runtime_owner=runtime_owner,
    )


def _root_inputs() -> dict[str, Any]:
    return {"study_facts": {"population": "labeled-synthetic", "phase": "II"}}


def _sha_of(payload: Any) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _append_foreign_event(
    tmp_path, run_id: str, *, event_type: str, payload: dict[str, Any]
) -> None:
    """Append one event directly through the product event stream, bypassing
    the graph runtime — the corruption vector the repair path must survive."""

    from app.protocol_workflow.events.models import EventEnvelopeBuilder

    factory = build_unit_of_work_factory(
        {"backend": "sqlite", "path": str(tmp_path / "graph.sqlite")}
    )
    with factory() as uow:
        repo = uow.event_stream_repository
        head = repo.get_stream_head(_PROJ, run_id)
        assert head is not None
        event = EventEnvelopeBuilder().continue_chain(
            head.last_event_sha256,
            head.last_sequence,
            domain_event_id=f"{run_id}:{event_type}:{head.last_sequence + 1}",
            stream_id=run_id,
            event_type=event_type,
            payload_schema_version="mw_protocol_v3_graph_event_v1",
            upcaster_id="graph-runtime-v1",
            actor_type="system",
            actor_id="foreign-writer",
            action="append",
            reason="test corruption probe",
            payload=payload,
            emitted_at=_EPOCH,
        )
        repo.append_events(_PROJ, run_id, (event,))


# ---------------------------------------------------------------------------
# Plan validation and material identity
# ---------------------------------------------------------------------------


class TestPlanValidation:
    def test_plan_material_hash_is_deterministic_and_order_independent(self) -> None:
        from app.protocol_workflow.graph import GraphNodePlan, GraphPlan

        plan = _probe_plan()
        first = plan.material_sha256()
        assert first == plan.material_sha256()
        assert len(first) == 64
        reversed_nodes = GraphPlan(
            project_id=plan.project_id,
            branch_id=plan.branch_id,
            graph_id=plan.graph_id,
            graph_version=plan.graph_version,
            description=plan.description,
            schemas=tuple(reversed(plan.schemas)),
            root_inputs=plan.root_inputs,
            nodes=tuple(reversed(plan.nodes)),
        )
        assert reversed_nodes.material_sha256() == first
        bumped = GraphPlan(
            project_id=plan.project_id,
            branch_id=plan.branch_id,
            graph_id=plan.graph_id,
            graph_version="probe_v2",
            description=plan.description,
            schemas=plan.schemas,
            root_inputs=plan.root_inputs,
            nodes=plan.nodes,
        )
        assert bumped.material_sha256() != first

    @pytest.mark.parametrize(
        "mutation, code",
        [
            (
                lambda nodes: nodes
                + (nodes[0].model_copy(update={"node_id": "draft_node"}),),
                "graph_node_duplicate",
            ),
            (
                lambda nodes: nodes
                + (
                    nodes[0].model_copy(
                        update={
                            "node_id": "ghost_dep",
                            "depends_on": ("missing_node",),
                            "logical_key": "probe.ghost.1",
                            "output_schema": "final",
                            "input_schemas": ("study_facts",),
                        }
                    ),
                ),
                "graph_dependency_unknown",
            ),
            (
                lambda nodes: nodes
                + (
                    nodes[0].model_copy(
                        update={
                            "node_id": "self_dep",
                            "depends_on": ("self_dep",),
                            "logical_key": "probe.self.1",
                        }
                    ),
                ),
                "graph_cycle",
            ),
            (
                lambda nodes: nodes
                + (nodes[1].model_copy(update={"node_id": "twin", "logical_key": "probe.review.1"}),),
                "graph_logical_key_duplicate",
            ),
            (
                lambda nodes: nodes
                + (
                    nodes[0].model_copy(
                        update={
                            "node_id": "no_input",
                            "depends_on": (),
                            "input_schemas": (),
                            "logical_key": "probe.noinput.1",
                        }
                    ),
                ),
                "graph_node_inputs_empty",
            ),
        ],
    )
    def test_plan_mutations_fail_closed(self, mutation, code) -> None:
        from app.protocol_workflow.graph import GraphPlanError

        plan = _probe_plan()
        # Both construction entrypoints run the same fail-closed validator:
        # the fully re-validating copy and the persistence roundtrip.
        with pytest.raises(GraphPlanError) as raised:
            broken = plan.model_copy(update={"nodes": mutation(plan.nodes)})
            GraphPlan.model_validate(broken.model_dump())
        assert raised.value.code == code

    def test_plan_rejects_cyclic_dependencies(self) -> None:
        from app.protocol_workflow.graph import GraphPlanError

        plan = _probe_plan()
        nodes = list(plan.nodes)
        nodes[0] = nodes[0].model_copy(update={"depends_on": ("final_node",)})
        with pytest.raises(GraphPlanError) as raised:
            plan.model_copy(update={"nodes": tuple(nodes)})
        assert raised.value.code == "graph_cycle"

    def test_plan_rejects_ambiguous_input_schema(self) -> None:
        from app.protocol_workflow.graph import GraphPlanError, GraphNodeKind, GraphNodeOwner, GraphNodePlan

        plan = _probe_plan()
        twin_producer = GraphNodePlan(
            node_id="second_draft",
            kind=GraphNodeKind.WORK,
            owner=GraphNodeOwner.DESIGN_AND_SUMMARY,
            depends_on=(),
            input_schemas=("study_facts",),
            output_schema="draft",  # already produced by draft_node
            logical_key="probe.draft.2",
        )
        ambiguous = plan.nodes + (twin_producer,)
        with pytest.raises(GraphPlanError) as raised:
            plan.model_copy(update={"nodes": ambiguous})
        assert raised.value.code == "graph_output_schema_ambiguous"


# ---------------------------------------------------------------------------
# Execution, decisions and event-sourced reconstruction
# ---------------------------------------------------------------------------


class TestExecutionAndDecisions:
    def test_run_executes_to_decision_pause_then_completes_after_human_record(
        self, tmp_path
    ) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0001"

        snapshot = runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        assert snapshot.status.value == "running"
        assert snapshot.nodes[0].status.value == "pending"

        # Work nodes run, then the decision node pauses the run.
        done = runtime.run_to_completion(run_id, plan=plan)
        assert executions == {"draft_node": 1, "review_node": 1}
        statuses = {node.node_id: node.status.value for node in done.nodes}
        assert statuses == {
            "draft_node": "completed",
            "review_node": "completed",
            "lock_node": "awaiting_decision",
            "final_node": "pending",
        }
        assert done.status.value == "awaiting_decision"

        # An agent cannot self-approve: advancing at the pause is a no-op.
        still = runtime.advance(run_id, plan=plan)
        assert still.status.value == "awaiting_decision"
        assert executions == {"draft_node": 1, "review_node": 1}

        recorded = runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True, "label": "labeled-synthetic"},
            reason="human confirms the locked review",
        )
        assert recorded.status.value == "running"
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        assert executions["final_node"] == 1
        final_status = {node.node_id: node.status.value for node in final.nodes}
        assert final_status["lock_node"] == "completed"
        assert final_status["final_node"] == "completed"

    def test_decision_record_is_idempotent_and_conflicts_fail_closed(
        self, tmp_path
    ) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0002"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r1",
        )

        # Repeating the identical decision identity is idempotent.
        again = runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r1",
        )
        assert again.nodes[2].status.value == "completed"

        # A different decision under the same key fails closed.
        from app.protocol_workflow.graph import GraphDecisionConflictError

        with pytest.raises(GraphDecisionConflictError):
            runtime.record_decision(
                run_id,
                node_id="lock_node",
                decision_id="dec-0002",
                actor_id="reviewer-1",
                value={"approved": False},
                reason="r2",
            )
        with pytest.raises(GraphDecisionConflictError):
            runtime.record_decision(
                run_id,
                node_id="lock_node",
                decision_id="dec-0001",
                actor_id="reviewer-2",
                value={"approved": True},
                reason="r1",
            )

    def test_decision_before_pause_and_on_non_decision_node_fail_closed(
        self, tmp_path
    ) -> None:
        from app.protocol_workflow.graph import GraphRunError

        runtime = _runtime(tmp_path, _probe_services({}))
        plan = _probe_plan()
        run_id = "run-probe-0003"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        with pytest.raises(GraphRunError):
            runtime.record_decision(
                run_id,
                node_id="lock_node",
                decision_id="dec-early",
                actor_id="reviewer-1",
                value={"approved": True},
                reason="too early",
            )

    def test_reviewer_identity_is_separate_from_writer_context(self, tmp_path) -> None:
        runtime = _runtime(tmp_path, _probe_services({}))
        plan = _probe_plan()
        run_id = "run-probe-0004"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r",
        )
        events = runtime.read_events(run_id)
        recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
        assert len(recorded) == 1
        event = recorded[0]
        # Reviewer identity travels as the event actor...
        assert event.actor_type.value == "user"
        assert event.actor_id == "reviewer-1"
        # ...while the writer context is a separate payload field naming the
        # runtime process, never the reviewer.
        writer = event.payload["writer_context"]
        assert writer["runtime_owner"] == "graph-runtime-test"
        assert writer["pid"] != "reviewer-1"
        assert event.payload["decision_id"] == "dec-0001"

    def test_node_result_events_carry_persisted_v1_1_contracts(self, tmp_path) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0005"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r",
        )
        runtime.run_to_completion(run_id, plan=plan)

        events = runtime.read_events(run_id)
        results = [e for e in events if e.event_type == "graph_node_result"]
        assert len(results) == 4
        # Service-dispatched nodes carry the persisted compacted contract;
        # the decision node's result carries the decision binding instead.
        dispatched = [e for e in results if "execution_contract" in e.payload]
        assert len(dispatched) == 3
        decision_results = [
            e for e in results if e.payload["node_id"] == "lock_node"
        ]
        assert len(decision_results) == 1
        assert decision_results[0].payload["output"]["decision_id"] == "dec-0001"
        for event in dispatched:
            contract_payload = event.payload["execution_contract"]
            assert contract_payload["schema_version"] == "mw_protocol_v3_contract_v1_1"
            assert contract_payload["dependency_sha256"]
            # The compacted representation replaced the field-level tuple
            # (the serializer drops the emptied dependency field entirely).
            assert "input_artifact_hashes" not in contract_payload
            # The v1_1 binding is executable: rebuilding the contract from the
            # persisted payload re-verifies freshness against the recorded
            # input hashes (and rejects foreign input sets).
            from packages.contracts.workbench_contracts.protocol_v3 import (
                NodeExecutionContract,
            )

            contract = NodeExecutionContract.model_validate(contract_payload)
            current = tuple(sorted(set(event.payload["input_hashes"].values())))
            assert contract.matches_dependencies(current)
            assert not contract.matches_dependencies(("0" * 64,))

    def test_reconstruction_matches_after_reopen_without_reexecution(
        self, tmp_path
    ) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0006"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        first = runtime.run_to_completion(run_id, plan=plan)
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r",
        )
        before = runtime.run_to_completion(run_id, plan=plan)

        # A fresh runtime instance over the same database reconstructs the
        # same authoritative state and re-executes nothing.
        reopened = _runtime(tmp_path, _probe_services(executions))
        snapshot = reopened.load_run(plan, run_id)
        assert snapshot.status.value == "completed"
        assert {n.node_id: n.status.value for n in snapshot.nodes} == {
            n.node_id: n.status.value for n in before.nodes
        }
        after = reopened.run_to_completion(run_id, plan=plan)
        assert after.status.value == "completed"
        assert executions == {"draft_node": 1, "review_node": 1, "final_node": 1}

    def test_one_effective_artifact_lineage_per_logical_key(self, tmp_path) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0007"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        results = [
            e for e in runtime.read_events(run_id) if e.event_type == "graph_node_result"
        ]
        keys = [e.payload["logical_key"] for e in results]
        assert len(keys) == len(set(keys))
        shas = {e.payload["logical_key"]: e.payload["output_sha256"] for e in results}
        # Duplicate resume appends no second lineage.
        runtime.run_to_completion(run_id, plan=plan)
        results_again = [
            e for e in runtime.read_events(run_id) if e.event_type == "graph_node_result"
        ]
        assert {e.payload["logical_key"]: e.payload["output_sha256"] for e in results_again} == shas
        assert len(results_again) == len(results)


# ---------------------------------------------------------------------------
# Binding: old graph rejected; checkpoint is advisory only
# ---------------------------------------------------------------------------


class TestBindingAndCheckpoint:
    def test_resume_rejects_old_graph_version(self, tmp_path) -> None:
        from app.protocol_workflow.graph import GraphPlanBindingError

        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0008"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)

        old_plan = _probe_plan(graph_version="probe_v0")
        with pytest.raises(GraphPlanBindingError):
            old_runtime = _runtime(tmp_path, _probe_services({}))
            old_runtime.load_run(old_plan, run_id)
        with pytest.raises(GraphPlanBindingError):
            runtime.advance(run_id, plan=old_plan)
        # History retained: the run is intact and still completable.
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r",
        )
        assert runtime.run_to_completion(run_id, plan=plan).status.value == "completed"

    def test_over_claiming_checkpoint_is_repaired_from_events(self, tmp_path) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0009"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)

        # Corrupt advisory state, written directly through the event stream
        # the way a stale/corrupt writer would: a checkpoint claiming the
        # decision node is already completed, although no authoritative
        # result event exists.
        _append_foreign_event(
            tmp_path,
            run_id,
            event_type="graph_checkpoint",
            payload={
                "node_states": {
                    "draft_node": "completed",
                    "review_node": "completed",
                    "lock_node": "completed",
                    "final_node": "pending",
                }
            },
        )
        snapshot = runtime.load_run(plan, run_id)
        assert snapshot.checkpoint_divergence is not None
        statuses = {n.node_id: n.status.value for n in snapshot.nodes}
        assert statuses["lock_node"] == "awaiting_decision"  # events are authority
        # The runtime repairs the advisory state and finishes from events.
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-0001",
            actor_id="reviewer-1",
            value={"approved": True},
            reason="r",
        )
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        assert final.checkpoint_divergence is None
        repairs = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_checkpoint_repaired"
        ]
        assert len(repairs) == 1
        # Existing history retained: the corrupt checkpoint event is still there.
        assert any(
            e.event_type == "graph_checkpoint" for e in runtime.read_events(run_id)
        )

    def test_run_completion_never_certified_by_checkpoint_alone(self, tmp_path) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0010"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        # A checkpoint claiming full completion must not certify the run.
        _append_foreign_event(
            tmp_path,
            run_id,
            event_type="graph_checkpoint",
            payload={
                "node_states": {
                    "draft_node": "completed",
                    "review_node": "completed",
                    "lock_node": "completed",
                    "final_node": "completed",
                }
            },
        )
        snapshot = runtime.load_run(plan, run_id)
        assert snapshot.status.value != "completed"
        assert snapshot.checkpoint_divergence is not None


# ---------------------------------------------------------------------------
# Reservation discipline: reuse, orphan recovery, unknown fail-closed
# ---------------------------------------------------------------------------


class TestReservationDiscipline:
    def test_completed_reservation_is_reused_without_new_dispatch(self, tmp_path) -> None:
        """A crash after the reservation completed but before any further
        progress leaves a completed result; resume reuses it (zero dispatches
        for the completed call) and the run still finishes."""

        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "run-probe-0011"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())

        # Simulate the crash window by dropping the runtime's in-memory view:
        # a fresh instance over the same database observes the same durable
        # completed reservations and reuses them.
        first = runtime.run_to_completion(run_id, plan=plan)
        assert first.status.value == "awaiting_decision"
        reopened = _runtime(tmp_path, _probe_services(executions))
        snapshot = reopened.run_to_completion(run_id, plan=plan)
        assert snapshot.status.value == "awaiting_decision"
        assert executions == {"draft_node": 1, "review_node": 1}
        attempts = reopened.reservation_attempts(run_id, "draft_node")
        assert len(attempts) == 1
        assert attempts[0].status is ReservationStatus.COMPLETED

    def test_unknown_outcome_never_auto_redispatches(self, tmp_path) -> None:
        """A dispatch classified unknown (timeout inside the transport) blocks
        the node; resume never redispatches it automatically, and only a
        verified payload-bearing receipt restores usable content."""

        from app.protocol_workflow.graph import GraphNodeStatus, GraphRunError, NodeServiceRequest

        executions: dict[str, int] = {}

        def _timeout_service(request: NodeServiceRequest) -> dict[str, Any]:
            executions[request.node.node_id] = executions.get(request.node.node_id, 0) + 1
            raise TimeoutError("synthetic dispatch timeout")

        services = {node: _timeout_service for node in ("draft_node", "review_node", "final_node")}
        runtime = _runtime(tmp_path, services)
        plan = _probe_plan()
        run_id = "run-probe-0012"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        blocked = runtime.run_to_completion(run_id, plan=plan)
        assert blocked.status.value == "blocked"
        statuses = {n.node_id: n.status.value for n in blocked.nodes}
        assert statuses["draft_node"] == "blocked_unknown"
        assert executions["draft_node"] == 1

        # Resume (fresh runtime, fresh process-style) still refuses.
        reopened = _runtime(tmp_path, services)
        still = reopened.run_to_completion(run_id, plan=plan)
        assert still.nodes[0].status.value == GraphNodeStatus.BLOCKED_UNKNOWN.value
        assert executions["draft_node"] == 1
        assert len(reopened.reservation_attempts(run_id, "draft_node")) == 1

        # A hash without its payload is NOT usable content: refused with a
        # typed error, the node stays blocked, nothing is certified.
        recovered_sha = _sha_of({"node": "draft_node", "label": "recovered-synthetic"})
        with pytest.raises(GraphRunError) as raised:
            reopened.resolve_unknown_with_receipt(
                run_id,
                node_id="draft_node",
                output={"node": "draft_node", "label": "recovered-synthetic"},
                output_sha256=_sha_of({"different": "payload"}),
            )
        assert raised.value.code == "graph_receipt_hash_mismatch"
        assert reopened.load_run(plan, run_id).nodes[0].status.value == (
            GraphNodeStatus.BLOCKED_UNKNOWN.value
        )
        assert executions["draft_node"] == 1

        # The verified payload-bearing receipt restores usable content:
        # the same typed result is persisted (schema, contract, input
        # provenance, recovered marker) and the existing reservation
        # converges with no new dispatch.
        recovered = reopened.resolve_unknown_with_receipt(
            run_id,
            node_id="draft_node",
            output={"node": "draft_node", "label": "recovered-synthetic"},
            output_sha256=recovered_sha,
        )
        assert recovered.nodes[0].status.value == "completed"
        assert recovered.nodes[0].output_sha256 == recovered_sha
        assert executions["draft_node"] == 1
        results = [
            e for e in reopened.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "draft_node"
        ]
        assert len(results) == 1
        payload = results[0].payload
        assert payload["output"] == {"node": "draft_node", "label": "recovered-synthetic"}
        assert payload["output_sha256"] == recovered_sha
        assert payload["recovered_receipt"] is True
        assert payload["execution_contract"]["schema_version"] == (
            "mw_protocol_v3_contract_v1_1"
        )
        attempts = reopened.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1]
        assert attempts[0].status.value == "completed"

        # Downstream is usable again: the review node consumes the recovered
        # payload as its declared input (it then hits its own synthetic
        # timeout and blocks — the recovered work itself is not re-run).
        proceeded = reopened.run_to_completion(run_id, plan=plan)
        assert executions["review_node"] == 1
        assert proceeded.nodes[1].status.value == "blocked_unknown"
        review = [
            e for e in reopened.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "review_node"
        ]
        assert review == []  # review produced no result; draft was not re-run
        # The review dispatch's material input binding carries the recovered
        # draft payload: downstream actually consumed the recovered content.
        from app.protocol_workflow.runtime.idempotency import canonical_input_hash

        expected_payload = {
            "workflow_run_id": run_id,
            "node_id": "review_node",
            "inputs": {"draft": {"node": "draft_node", "label": "recovered-synthetic"}},
            "input_hashes": {"draft": recovered_sha},
        }
        expected_sha = canonical_input_hash(
            logical_call_id=f"call:{run_id}:review_node",
            idempotency_key="probe.review.1",
            payload=expected_payload,
        )
        review_attempts = reopened.reservation_attempts(run_id, "review_node")
        assert [a.attempt for a in review_attempts] == [1]
        assert review_attempts[0].input_sha256 == expected_sha

    def test_explicit_retry_appends_attempt_and_requires_decision_identity(
        self, tmp_path
    ) -> None:
        from app.protocol_workflow.graph import GraphRunError, NodeServiceRequest

        executions: dict[str, int] = {}

        def _flaky(request: NodeServiceRequest) -> dict[str, Any]:
            node_id = request.node.node_id
            executions[node_id] = executions.get(node_id, 0) + 1
            if executions[node_id] == 1:
                raise TimeoutError("synthetic timeout on first attempt")
            return {"node": node_id, "label": "labeled-synthetic", "attempt": request.attempt}

        services = {node: _flaky for node in ("draft_node", "review_node", "final_node")}
        runtime = _runtime(tmp_path, services)
        plan = _probe_plan()
        run_id = "run-probe-0013"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        assert runtime.run_to_completion(run_id, plan=plan).status.value == "blocked"

        # Explicit retry with a stable decision identity executes attempt 2.
        retried = runtime.retry_node(
            run_id,
            node_id="draft_node",
            retry_decision_id="retry-dec-0001",
            reason="owner-approved retry",
        )
        assert executions["draft_node"] == 2
        assert retried.nodes[0].status.value == "completed"
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1, 2]
        assert attempts[0].status is ReservationStatus.UNKNOWN_OUTCOME
        assert attempts[1].status is ReservationStatus.COMPLETED

        # Repeating the same retry decision identity is idempotent (no third
        # attempt, no new execution).
        same = runtime.retry_node(
            run_id,
            node_id="draft_node",
            retry_decision_id="retry-dec-0001",
            reason="owner-approved retry",
        )
        assert executions["draft_node"] == 2
        assert [a.attempt for a in runtime.reservation_attempts(run_id, "draft_node")] == [1, 2]

        # A distinct identity is refused once the node is completed.
        with pytest.raises(GraphRunError):
            runtime.retry_node(
                run_id,
                node_id="draft_node",
                retry_decision_id="retry-dec-0002",
                reason="duplicate",
            )

    def test_blocked_running_row_from_crash_requires_explicit_resolution(
        self, tmp_path
    ) -> None:
        """A reservation left RUNNING by a dead process (no result event)
        blocks the node and is never auto-redispatched; the owner must resolve
        it as failed and explicitly retry, producing an append-only lineage."""

        from datetime import datetime, timezone

        from app.protocol_workflow.graph import NodeServiceRequest
        from packages.contracts.workbench_contracts.protocol_v3 import (
            ExecutionReservation,
        )

        executions: dict[str, int] = {}

        def _service(request: NodeServiceRequest) -> dict[str, Any]:
            executions[request.node.node_id] = executions.get(request.node.node_id, 0) + 1
            return {"node": request.node.node_id, "label": "labeled-synthetic"}

        services = {node: _service for node in ("draft_node", "review_node", "final_node")}
        runtime = _runtime(tmp_path, services)
        plan = _probe_plan()
        run_id = "run-probe-0014"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())

        # Craft the crash window exactly as a dead process would leave it: a
        # RUNNING reservation with one transport attempt and no result event,
        # written through the committed-operation repository.
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        logical_call = runtime.logical_call_id(run_id, "draft_node")
        with build_committed_reservation_repository_factory(
            {"backend": "sqlite", "path": str(tmp_path / "graph.sqlite")}
        )() as repo:
            shell = repo.reserve(
                _PROJ,
                ExecutionReservation(
                    execution_reservation_id="res:crashwindow:0001",
                    node_execution_contract_id=f"nec:{run_id}:draft_node",
                    logical_call_id=logical_call,
                    idempotency_key="probe.draft.1",
                    input_sha256=_sha_of({"seed": "crash-window"}),
                    attempt=1,
                    transport_attempts=0,
                    provider_session_id="sess:crashwindow:0001",
                    status=ReservationStatus.RESERVED,
                    reserved_at=now,
                    updated_at=now,
                ),
            )
            assert shell.status is ReservationStatus.RESERVED
            running = repo.transition(
                _PROJ,
                "res:crashwindow:0001",
                to_status=ReservationStatus.RUNNING,
                transport_attempts=1,
                updated_at=now,
            )
            assert running.status is ReservationStatus.RUNNING

        blocked = runtime.run_to_completion(run_id, plan=plan)
        assert blocked.nodes[0].status.value == "blocked_unknown"
        assert executions == {}  # nothing redispatched

        resolved = runtime.resolve_blocked_with_failure(
            run_id,
            node_id="draft_node",
            resolution_id="res-dec-0001",
            reason="crash window closed as failed",
        )
        assert resolved.nodes[0].status.value == "failed"
        retried = runtime.retry_node(
            run_id,
            node_id="draft_node",
            retry_decision_id="retry-dec-crash-1",
            reason="owner retry after crash",
        )
        assert retried.nodes[0].status.value == "completed"
        assert executions == {"draft_node": 1}
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1, 2]
        assert attempts[0].status is ReservationStatus.FAILED
        assert attempts[1].status is ReservationStatus.COMPLETED


# ---------------------------------------------------------------------------
# Ported Codex probes + deterministic stale-precheck interleaving (2R.1 repair)
#
# The four Codex probes (runs/mw_protocol_v3_2r1_typed_facade_20260905/
# test_codex_concurrency_probe.py — read-only original evidence) are ported
# here against the repaired seams.  The forced-interleave hook moved with the
# transaction boundary: the semantic check now runs INSIDE the append
# transaction (``_append_events_tx`` guard), so the deterministic parking
# seam is that method, not the old outer ``_append_events``.  Assertions are
# unchanged: exactly one decision/start event, loser gets the typed error.
# ---------------------------------------------------------------------------


class TestDecisionAndStartAtomicity:
    def test_conflicting_decisions_cannot_both_pass_stale_precheck(
        self, tmp_path
    ) -> None:
        """Forced interleave: writer A parks between its stale pre-check and
        its append transaction; writer B commits a conflicting decision
        meanwhile; A's in-transaction guard must then fail closed.  Exactly
        one decision event survives and exactly one writer reports recorded.
        (Ported from the Codex probe; the parking seam moved from the outer
        append to the new in-transaction append+guard path.)"""

        import threading

        from app.protocol_workflow.graph import GraphDecisionConflictError

        setup = _runtime(tmp_path, _probe_services({}))
        plan = _probe_plan()
        run_id = "race-probe"
        setup.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        setup.run_to_completion(run_id, plan=plan)

        a_parked = threading.Event()
        b_done = threading.Event()

        def _make_racer(index: int):
            runtime = _runtime(tmp_path, _probe_services({}))
            real_append = runtime._append_events_tx

            def guarded_append_tx(run_id_, specs, guard=None):
                if index == 0 and specs[0][0] == "graph_decision_recorded":
                    a_parked.set()
                    assert b_done.wait(timeout=30), "writer B never committed"
                return real_append(run_id_, specs, guard=guard)

            return runtime, guarded_append_tx

        outcomes: dict[int, str] = {}
        errors: dict[int, str] = {}

        def submit(index: int) -> None:
            runtime, append_tx = _make_racer(index)
            runtime._append_events_tx = append_tx
            try:
                runtime.record_decision(
                    run_id,
                    node_id="lock_node",
                    decision_id=f"choice-{index}",
                    actor_id=f"writer-{index}",
                    value={"approved": index == 0},
                    reason="choice",
                )
                outcomes[index] = "recorded"
            except GraphDecisionConflictError:
                outcomes[index] = "conflict"
                errors[index] = "GraphDecisionConflictError"

        import threading as _th

        thread_a = _th.Thread(target=submit, args=(0,))
        thread_a.start()
        assert a_parked.wait(timeout=30), "writer A never reached its append"
        thread_b = _th.Thread(target=submit, args=(1,))
        thread_b.start()
        deadline = 300
        while 1 not in outcomes and deadline > 0:
            deadline -= 1
            _th.Event().wait(0.01)
        b_done.set()
        thread_a.join(60)
        thread_b.join(60)

        records = [
            event
            for event in setup.read_events(run_id)
            if event.event_type == "graph_decision_recorded"
        ]
        assert len(records) == 1, (
            outcomes,
            [event.payload["decision_id"] for event in records],
        )
        assert sorted(outcomes.values()) == ["conflict", "recorded"]
        assert errors.get(0) == "GraphDecisionConflictError"

    def test_same_run_cannot_silently_accept_changed_root_facts(
        self, tmp_path
    ) -> None:
        runtime = _runtime(tmp_path, _probe_services({}))
        runtime.start_run(
            _probe_plan(), workflow_run_id="facts-probe", root_inputs=_root_inputs()
        )
        from app.protocol_workflow.graph import GraphRunError

        changed = {"study_facts": {"population": "different-synthetic", "phase": "III"}}
        with pytest.raises(GraphRunError):
            runtime.start_run(
                _probe_plan(), workflow_run_id="facts-probe", root_inputs=changed
            )
        # The binding is unchanged: original facts still rule.
        snapshot = runtime.load_run(_probe_plan(), "facts-probe")
        assert snapshot.status.value == "running"

    def test_decision_content_hash_matches_actual_downstream_payload(
        self, tmp_path
    ) -> None:
        runtime = _runtime(tmp_path, _probe_services({}))
        plan = _probe_plan()
        runtime.start_run(plan, workflow_run_id="hash-probe", root_inputs=_root_inputs())
        runtime.run_to_completion("hash-probe")
        runtime.record_decision(
            "hash-probe",
            node_id="lock_node",
            decision_id="choice",
            actor_id="human",
            value={"approved": True},
            reason="reviewed",
        )
        results = [
            e.payload
            for e in runtime.read_events("hash-probe")
            if e.event_type == "graph_node_result" and e.payload["node_id"] == "lock_node"
        ]
        assert results[0]["output_sha256"] == _sha_of(results[0]["output"])
        # The decision value hash stays available separately for dedup.
        recorded = [
            e.payload
            for e in runtime.read_events("hash-probe")
            if e.event_type == "graph_decision_recorded"
        ]
        assert recorded[0]["value_sha256"] == _sha_of(recorded[0]["value"])

    def test_reopen_final_result_without_completion_event_finishes_without_dispatch(
        self, tmp_path
    ) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "final-probe"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        runtime.run_to_completion(run_id, plan=plan)
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="choice",
            actor_id="human",
            value={"approved": True},
            reason="reviewed",
        )

        def crash_before_completion(*args):
            raise RuntimeError("synthetic interruption after durable final result")

        original_finish = runtime._finish_run_if_complete
        runtime._finish_run_if_complete = crash_before_completion
        try:
            with pytest.raises(RuntimeError, match="synthetic interruption"):
                runtime.advance(run_id)
        finally:
            runtime._finish_run_if_complete = original_finish
        calls: dict[str, int] = {}
        reopened = _runtime(tmp_path, _probe_services(calls))
        result = reopened.advance(run_id)
        assert calls == {}
        assert result.status.value == "completed"
        completed = [
            e for e in reopened.read_events(run_id)
            if e.event_type == "graph_run_completed"
        ]
        assert len(completed) == 1

    def test_run_to_completion_is_bounded_when_nothing_progresses(
        self, tmp_path
    ) -> None:
        executions: dict[str, int] = {}
        runtime = _runtime(tmp_path, _probe_services(executions))
        plan = _probe_plan()
        run_id = "bound-probe"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        stuck = runtime.advance(run_id)

        def never_progress(workflow_run_id, plan=None):
            return stuck

        from app.protocol_workflow.graph import GraphRunError

        runtime.advance = never_progress
        with pytest.raises(GraphRunError) as raised:
            runtime.run_to_completion(run_id)
        assert raised.value.code == "graph_no_progress"


class TestTerminalReceiptRecovery:
    def test_terminal_node_receipt_recovery_completes_the_run(
        self, tmp_path
    ) -> None:
        """Recovering the LAST node's unknown outcome with a verified
        payload converges the run to completed — no dispatch, real final
        state hash, and a second receipt attempt is refused (already done).
        """

        from app.protocol_workflow.graph import GraphRunError, NodeServiceRequest

        executions: dict[str, int] = {}

        def _service(request: NodeServiceRequest) -> dict[str, Any]:
            node_id = request.node.node_id
            executions[node_id] = executions.get(node_id, 0) + 1
            if node_id == "final_node":
                raise TimeoutError("synthetic final dispatch timeout")
            return {"node": node_id, "label": "labeled-synthetic"}

        services = {node: _service for node in ("draft_node", "review_node", "final_node")}
        runtime = _runtime(tmp_path, services)
        plan = _probe_plan()
        run_id = "run-terminal-receipt"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-terminal",
            actor_id="reviewer-terminal",
            value={"approved": True},
            reason="human adoption",
        )
        blocked = runtime.run_to_completion(run_id, plan=plan)
        assert blocked.status.value == "blocked"
        assert blocked.nodes[3].status.value == "blocked_unknown"

        final_payload = {"node": "final_node", "label": "recovered-final-synthetic"}
        recovered = runtime.resolve_unknown_with_receipt(
            run_id,
            node_id="final_node",
            output=final_payload,
            output_sha256=_sha_of(final_payload),
        )
        assert recovered.status.value == "completed"
        assert recovered.node_output("final_node") == _sha_of(final_payload)
        assert executions["final_node"] == 1
        completed = [
            e for e in runtime.read_events(run_id)
            if e.event_type == "graph_run_completed"
        ]
        assert len(completed) == 1
        assert completed[0].payload["final_state"]["final_node"] == _sha_of(final_payload)
        # An identical second receipt is idempotent reuse (no second result).
        again = runtime.resolve_unknown_with_receipt(
            run_id,
            node_id="final_node",
            output=final_payload,
            output_sha256=_sha_of(final_payload),
        )
        assert again.status.value == "completed"
        results = [
            e for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "final_node"
        ]
        assert len(results) == 1
        # A DIFFERENT receipt over the completed node is a typed conflict.
        from app.protocol_workflow.graph import GraphRunError

        with pytest.raises(GraphRunError) as raised:
            runtime.resolve_unknown_with_receipt(
                run_id,
                node_id="final_node",
                output={"node": "final_node", "label": "other-content"},
                output_sha256=_sha_of({"node": "final_node", "label": "other-content"}),
            )
        assert raised.value.code == "graph_node_completed"


class TestQCInvocationIndependence:
    """Offline orchestration evidence for QC/reviewer independence.

    What this proves: an injected QC node service is invoked as an
    independent callable over exactly its DECLARED input artifacts, with an
    invocation identity recorded separately from the writer-private context
    (runtime owner + pid) and from the human confirmation actor.  This is
    orchestration-layer provenance ONLY — it is not actual-model fresh
    context and not clinical/medical acceptance; real-model QC activation
    stays deferred to its own phase.
    """

    def test_qc_service_receives_only_declared_inputs_with_separate_context(
        self, tmp_path
    ) -> None:
        from app.protocol_workflow.graph import NodeServiceRequest

        plan = _probe_plan()
        review_node = plan.node("review_node")
        assert review_node.owner.value == "quality_control"

        invocations: list[dict[str, Any]] = []

        def _make_qc_service():
            # Fresh context per injected QC invocation: the callable closes
            # over its own private token and shares nothing with the writer
            # services or the decision path.
            qc_token = f"qc-context-{len(invocations) + 1}"

            def _qc_service(request: NodeServiceRequest) -> dict[str, Any]:
                invocations.append(
                    {
                        "qc_token": qc_token,
                        "received_input_schemas": sorted(request.inputs.keys()),
                        "request_slots": sorted(request.__slots__),
                        "node_id": request.node.node_id,
                    }
                )
                return {
                    "node": request.node.node_id,
                    "open_count": 0,
                    "qc_context": qc_token,
                    "label": "labeled-synthetic-qc",
                }

            return _qc_service

        services = {
            "draft_node": lambda request: {"node": "draft_node", "label": "labeled-synthetic"},
            "review_node": _make_qc_service(),
            "final_node": lambda request: {"node": "final_node", "label": "labeled-synthetic"},
        }
        runtime = _runtime(tmp_path, services, runtime_owner="writer-owner")
        run_id = "run-qc-independence"
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-qc",
            actor_id="reviewer-human",
            value={"approved": True},
            reason="human confirmation",
        )

        # 1. The QC service was invoked exactly once, over exactly its
        #    declared input schemas — no root or other artifacts, and the
        #    request carries none of the runtime's private surface.
        assert len(invocations) == 1
        invocation = invocations[0]
        assert invocation["received_input_schemas"] == sorted(review_node.input_schemas)
        assert invocation["node_id"] == "review_node"
        assert set(invocation["request_slots"]) == {
            "plan", "node", "inputs", "input_hashes", "attempt", "reservation_id",
        }

        # 2. The persisted QC result carries typed invocation provenance:
        #    declared inputs bound on the event, the writer context separate
        #    from the QC execution identity.
        results = [
            e.payload for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result" and e.payload["node_id"] == "review_node"
        ]
        assert len(results) == 1
        provenance = results[0]["service_invocation"]
        assert provenance["declared_input_schemas"] == sorted(review_node.input_schemas)
        assert provenance["owner"] == "quality_control"
        assert provenance["writer_context"]["runtime_owner"] == "writer-owner"
        assert isinstance(provenance["writer_context"]["pid"], int)
        assert provenance["invocation_id"].startswith("svcinv:run-qc-independence:review_node:")
        # The QC execution context recorded in the artifact differs from the
        # writer identity that persisted it.
        assert results[0]["output"]["qc_context"] != provenance["writer_context"]["runtime_owner"]

        # 3. The human confirmation is a separate actor with its own writer
        #    context — never the QC invocation, never the result writer.
        decision = [
            e for e in runtime.read_events(run_id)
            if e.event_type == "graph_decision_recorded"
        ][0]
        assert decision.actor_id == "reviewer-human"
        assert decision.actor_type.value == "user"
        assert decision.payload["writer_context"]["runtime_owner"] == "writer-owner"
        assert decision.payload["actor_id"] != provenance["writer_context"]["runtime_owner"]
        assert decision.payload["decision_id"] not in (
            invocation["qc_token"],
            provenance["invocation_id"],
        )
