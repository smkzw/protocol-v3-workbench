"""Typed graph runtime over product SQLite (Task 2R.1).

One coherent typed facade runtime behind the product :class:`OrchestratorPort`
(``app.protocol_workflow.graph.ports``).  One runtime instance is bound to
one project (mirroring the project-keyed storage ports); it executes a
validated :class:`~app.protocol_workflow.graph.plan.GraphPlan` with these
disciplines:

* **Event-sourced state** — every run appends to its own authoritative
  ``DomainEvent`` stream through the product SQLite unit of work.  Node
  state is reconstructed by replaying events plus the committed reservation
  ledger.  The ``graph_checkpoint`` event is *advisory*: it never certifies
  node or run completion, divergence from the authoritative replay is
  detected and repaired by appending a corrected checkpoint (existing
  history is never rewritten).

* **Persist-first dispatch** — every executable node dispatches through the
  product :class:`ReservationCoordinator` wired to the committed-operation
  reservation repository (``build_committed_reservation_repository_factory``),
  so the RESERVED claim and the RUNNING transition are durable *before* the
  physical service call.  The typed service's result is
  committed as a ``graph_node_result`` event *before* the coordinator
  records ``COMPLETED``, so a crash in between leaves truthful evidence on
  both sides and the authoritative event/result data repairs the
  reservation.

* **v1_1 contracts in the executed path** — every dispatch builds a
  ``NodeExecutionContract`` and immediately compacts it through
  ``compact_dependencies()``; the compacted (``mw_protocol_v3_contract_v1_1``)
  contract is persisted on the node result event and its compact dependency
  digest is re-verified against the recorded input hashes on every
  reconstruction.  Input freshness binding is therefore executed, not a
  wrapper.

* **Humans decide** — a DECISION node pauses the run into an
  ``awaiting_decision`` product state.  The runtime never self-approves:
  only :meth:`GraphRuntime.record_decision` applies a human decision, with
  idempotent/CAS semantics per decision key, the reviewer identity as the
  event actor, and the writer context as a separate payload field.

* **Unknown is never auto-redispatched** — a dead process's RUNNING shell or
  an ``UNKNOWN_OUTCOME`` reservation blocks the node (``blocked_unknown``).
  Recovery requires explicit owner action: close the crash window as failed
  and append an explicit retry attempt, or adopt a verified recovered
  receipt.  A zero-transport-attempt orphan shell (dispatch never started)
  is disposed by the coordinator and retried through an explicit, derived,
  idempotent recovery decision identity.

No product module imports ``pocs``: plans built from the accepted PoC case
graphs enter through the PoC-side adapter.  Nodes default to deterministic
offline contracts. Application-configured nodes may supply a model contract;
the runtime passes that same compacted contract to their executor and stores
it with their result. The runtime itself has no provider client.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    DomainEvent,
    ExecutionTerminalState,
    ExecutionReservation,
    NodeExecutionContract,
    ReasoningEffort,
    ReservationStatus,
    SensitivityTier,
)

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.events.models import EventEnvelopeBuilder
from app.protocol_workflow.graph.plan import GraphNodeKind, GraphNodePlan, GraphPlan
from app.protocol_workflow.graph.state import (
    EVENT_CHECKPOINT,
    EVENT_CHECKPOINT_REPAIRED,
    EVENT_DECISION_PENDING,
    EVENT_DECISION_RECORDED,
    EVENT_NODE_RESULT,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_STARTED,
    GRAPH_EVENT_SCHEMA_VERSION,
    GRAPH_EVENT_UPCASTER_ID,
    ORPHAN_DISPATCH_NOT_STARTED,
    RUNTIME_ACTOR_ID,
    GraphDecisionConflictError,
    GraphNodeStateRecord,
    GraphNodeStatus,
    GraphPlanBindingError,
    GraphRunError,
    GraphRunSnapshot,
    GraphRunStatus,
)
from app.protocol_workflow.graph.ports import (
    ConfiguredNodeServiceRequest, ConfiguredNodeServiceResult, NodeServiceRequest,
)
from app.protocol_workflow.ports.repositories import (
    IdempotencyConflictError,
    RepositoryStateTransitionError,
    UnknownOutcomeConflictError,
)
from app.protocol_workflow.runtime.reservations import (
    ReservationCoordinator,
    ReservationOutcome,
)
from app.protocol_workflow.storage.sqlite import (
    SqliteCommittedOperationReservationRepository,
)

__all__ = ["GraphRuntime"]

#: Hard step bound for ``run_to_completion``; a healthy run finishes in a few
#: steps per node, so exceeding this means no progress is possible.
_MAX_RUN_TO_COMPLETION_STEPS = 256
_EVENT_NODE_DISPATCH = 'graph_node_dispatch'


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    """Normalize a payload to plain JSON-able Python (deterministic)."""

    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        canonical_json(_jsonable(payload)).encode("utf-8")
    ).hexdigest()


class _ServiceTransport:
    """Reservation transport wrapping one configured or deterministic service.

    ``dispatch`` commits the node result event (the durable result) *before*
    returning the receipt, so the coordinator's COMPLETED transition can
    never precede the result evidence.
    """

    def __init__(
        self,
        runtime: "GraphRuntime",
        workflow_run_id: str,
        plan: GraphPlan,
        node: GraphNodePlan,
        contract_payload: Dict[str, Any],
        inputs: Mapping[str, Any],
        input_hashes: Mapping[str, str],
        attempt: int,
    ) -> None:
        self._runtime = runtime
        self._workflow_run_id = workflow_run_id
        self._plan = plan
        self._node = node
        self._contract_payload = contract_payload
        self._inputs = inputs
        self._input_hashes = input_hashes
        self._attempt = attempt

    def preflight(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        if self._node.node_id not in self._runtime._services:
            return "graph_service_missing"
        if self._node.node_id in self._runtime._execution_contract_factories:
            self._runtime._append_events_tx(
                self._workflow_run_id,
                [(_EVENT_NODE_DISPATCH, {
                    'node_id': self._node.node_id,
                    'reservation_id': reservation.execution_reservation_id,
                    'attempt': self._attempt,
                    'execution_contract': self._contract_payload,
                    'input_hashes': dict(self._input_hashes),
                }, ActorType.SYSTEM, RUNTIME_ACTOR_ID, 'node_dispatch',
                  'persist configured execution contract before provider dispatch')],
                guard=lambda events: not any(
                    e.event_type == _EVENT_NODE_DISPATCH
                    and e.payload.get('reservation_id') == reservation.execution_reservation_id
                    for e in events
                ),
            )
        return None

    def dispatch(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        request_kwargs = dict(
            plan=self._plan,
            node=self._node,
            inputs=self._inputs,
            input_hashes=self._input_hashes,
            attempt=self._attempt,
            reservation_id=reservation.execution_reservation_id,
        )
        if self._node.node_id in self._runtime._execution_contract_factories:
            request = ConfiguredNodeServiceRequest(
                **request_kwargs,
                execution_contract=NodeExecutionContract.model_validate(self._contract_payload),
            )
        else:
            request = NodeServiceRequest(**request_kwargs)
        result = self._runtime._services[self._node.node_id](request)
        provider_session_id = reservation.provider_session_id
        if isinstance(result, ConfiguredNodeServiceResult):
            if not isinstance(result.provider_session_id, str) or not result.provider_session_id.strip():
                raise ValueError('configured service returned no provider receipt identity')
            provider_session_id = result.provider_session_id
            result = result.payload
        if not isinstance(result, Mapping) or not result:
            raise ValueError("node service must return a non-empty mapping")
        output_payload = _jsonable(dict(result))
        output_sha = _payload_sha256(output_payload)
        # Durable result BEFORE the receipt: the event stream is the
        # authoritative result record the repair path trusts.
        self._runtime._append_node_result(
            workflow_run_id=self._workflow_run_id,
            node=self._node,
            contract_payload=self._contract_payload,
            input_hashes=self._input_hashes,
            output_payload=output_payload,
            output_sha=output_sha,
            reservation_id=reservation.execution_reservation_id,
            attempt=self._attempt,
            provider_session_id=provider_session_id,
            service_invocation=self._runtime._service_invocation(
                self._workflow_run_id, self._plan, self._node, self._attempt
            ),
        )
        return {
            "output_sha256": output_sha,
            "provider_session_id": provider_session_id,
        }


class _RunView:
    """Reconstructed authoritative view of one run."""

    def __init__(self) -> None:
        self.workflow_run_id: str = ""
        self.plan: Optional[GraphPlan] = None
        self.root_payloads: Dict[str, Any] = {}
        self.root_hashes: Dict[str, str] = {}
        self.results: Dict[str, Dict[str, Any]] = {}
        self.pending_decisions: Dict[str, str] = {}
        self.recorded_decisions: Dict[str, Dict[str, Any]] = {}
        self.completed_event = False
        #: Advisory checkpoint payload of the latest checkpoint/repair event.
        self.advisory: Optional[Dict[str, str]] = None
        #: Latest reservation status per node (empty when never dispatched).
        self.reservation_status: Dict[str, ReservationStatus] = {}
        #: (node_id, reservation_id, output_sha) triples whose result event
        #: is committed but whose reservation never reached a terminal state.
        self.reservation_repairs: Tuple[Tuple[str, str, str], ...] = ()


class GraphRuntime:
    """Typed orchestrator runtime over the product storage adapter."""

    def __init__(
        self,
        *,
        project_id: str,
        uow_factory: Callable[[], Any],
        reservation_repository_factory: Callable[
            [], SqliteCommittedOperationReservationRepository
        ],
        services: Mapping[str, Callable[[NodeServiceRequest], Mapping[str, Any]]],
        clock: Optional[Callable[[], datetime]] = None,
        runtime_owner: str = RUNTIME_ACTOR_ID,
        execution_contract_factories: Optional[Mapping[
            str, Callable[[NodeExecutionContract], NodeExecutionContract]
        ]] = None,
    ) -> None:
        self._project_id = project_id
        self._uow_factory = uow_factory
        self._reservation_repository_factory = reservation_repository_factory
        self._services = dict(services)
        self._clock = clock or _default_clock
        self._runtime_owner = runtime_owner
        self._execution_contract_factories = dict(execution_contract_factories or {})

    # ------------------------------------------------------------------
    # Public surface (OrchestratorPort + recovery operations)
    # ------------------------------------------------------------------

    @staticmethod
    def logical_call_id(workflow_run_id: str, node_id: str) -> str:
        """Deterministic reservation logical call id of one run node."""

        return f"call:{workflow_run_id}:{node_id}"

    def start_run(
        self,
        plan: GraphPlan,
        *,
        workflow_run_id: str,
        root_inputs: Mapping[str, Any],
    ) -> GraphRunSnapshot:
        """Bind a run to the plan identity and seed the root inputs.

        Idempotent for the identical plan identity *and* identical root
        input identities.  A different graph identity OR different root
        facts under the same run id fails closed with a typed binding error
        — checked both in the fast pre-check and, atomically, inside the
        append transaction, so a concurrent or stale-precheck start can
        never double-create a run or silently rebind its identity/roots.
        """

        if plan.project_id != self._project_id:
            raise GraphPlanBindingError(
                "graph_plan_binding_mismatch",
                f"runtime is bound to project {self._project_id!r}, plan "
                f"declares {plan.project_id!r}",
            )
        missing = [s for s in plan.root_inputs if s not in root_inputs]
        extra = [s for s in root_inputs if s not in plan.root_inputs]
        if missing or extra:
            raise GraphRunError(
                "graph_root_inputs_invalid",
                f"root inputs must declare exactly {sorted(plan.root_inputs)}; "
                f"missing={missing} extra={extra}",
            )
        root_payloads = {
            schema: _jsonable(payload) for schema, payload in root_inputs.items()
        }
        root_hashes = {
            schema: _payload_sha256(payload)
            for schema, payload in root_payloads.items()
        }
        try:
            view = self._load(workflow_run_id, caller_plan=None)
        except GraphRunError as exc:
            if exc.code != "graph_run_unknown":
                raise
        else:
            # Fast sequential path: identical identity *and* identical root
            # facts reuse the existing run; anything else fails closed.
            self._assert_binding(view.plan, plan, workflow_run_id)
            if view.root_hashes != root_hashes:
                raise GraphPlanBindingError(
                    "graph_root_inputs_conflict",
                    f"run {workflow_run_id!r} is already bound to root input "
                    f"identities {sorted(view.root_hashes.items())}; the new "
                    f"start declares {sorted(root_hashes.items())} — changed "
                    "root facts require a new run, never a silent rebind",
                )
            return self._snapshot(view, executed=set())
        specs = [
            (
                EVENT_RUN_STARTED,
                {
                    "plan": plan.model_dump(mode="json"),
                    "graph_sha256": plan.material_sha256(),
                    "root_payloads": root_payloads,
                    "root_hashes": root_hashes,
                },
                ActorType.SYSTEM,
                RUNTIME_ACTOR_ID,
                "start",
                "typed graph run started",
            )
        ]
        # The guard re-checks existence inside the append transaction, so
        # two concurrent starts produce exactly one start event and the
        # conflicting one fails closed instead of rebinding.
        appended = self._append_events_tx(
            workflow_run_id, specs, guard=self._start_guard(plan, root_hashes)
        )
        del appended  # False → identical start already applied; reuse below
        self._append_checkpoint(workflow_run_id, plan)
        view = self._load(workflow_run_id, caller_plan=plan)
        return self._snapshot(view, executed=set())

    def load_run(self, plan: GraphPlan, workflow_run_id: str) -> GraphRunSnapshot:
        """Reconstruct the authoritative run state (read-only)."""

        view = self._load(workflow_run_id, caller_plan=plan)
        return self._snapshot(view, executed=set())

    def advance(
        self, workflow_run_id: str, plan: Optional[GraphPlan] = None
    ) -> GraphRunSnapshot:
        """Execute at most one node step and return the run snapshot."""

        view = self._load(workflow_run_id, caller_plan=plan)
        executed: Set[str] = set()
        self._resolve_divergence(workflow_run_id, view)
        self._apply_reservation_repairs(view)
        if self._run_status(view) is GraphRunStatus.COMPLETED:
            return self._snapshot(view, executed=executed)
        for node_id in view.plan.topological_order():
            node = view.plan.node(node_id)
            status = self._node_status(view, node_id)
            if status is GraphNodeStatus.COMPLETED:
                continue
            if status is GraphNodeStatus.AWAITING_DECISION:
                return self._snapshot(view, executed=executed).model_copy(
                    update={"stop_reason": "awaiting_human_decision"}
                )
            if status in (GraphNodeStatus.FAILED, GraphNodeStatus.BLOCKED_UNKNOWN):
                return self._snapshot(view, executed=executed).model_copy(
                    update={"stop_reason": "blocked_requires_explicit_resolution"}
                )
            if node.kind is GraphNodeKind.DECISION:
                self._open_decision_pause(workflow_run_id, view, node)
                view = self._load(workflow_run_id, caller_plan=None)
                return self._snapshot(view, executed=executed).model_copy(
                    update={"stop_reason": "awaiting_human_decision"}
                )
            self._execute_node(workflow_run_id, view, node)
            executed.add(node_id)
            view = self._load(workflow_run_id, caller_plan=None)
            break
        # Crash-window convergence: every node result is durable but the
        # completion event was lost (killed between the last result and the
        # completion append).  Reopen must finish from the authoritative
        # results without dispatching any node.
        self._finish_run_if_complete(workflow_run_id, view)
        view = self._load(workflow_run_id, caller_plan=None)
        return self._snapshot(view, executed=executed)

    def run_to_completion(
        self, workflow_run_id: str, plan: Optional[GraphPlan] = None
    ) -> GraphRunSnapshot:
        """Advance until the run completes, pauses at a decision, or blocks.

        Bounded: if consecutive advances make no progress (no new events)
        the loop fails closed with a typed no-progress error instead of
        spinning forever.
        """

        snapshot = self.advance(workflow_run_id, plan=plan)
        last_event_count = -1
        for _ in range(_MAX_RUN_TO_COMPLETION_STEPS):
            if snapshot.status.value != "running":
                return snapshot
            event_count = len(self.read_events(workflow_run_id))
            if event_count == last_event_count:
                raise GraphRunError(
                    "graph_no_progress",
                    f"run {workflow_run_id!r} made no progress after "
                    f"{event_count} events; refusing to spin",
                )
            last_event_count = event_count
            snapshot = self.advance(workflow_run_id, plan=None)
        raise GraphRunError(
            "graph_no_progress",
            f"run {workflow_run_id!r} exceeded the "
            f"{_MAX_RUN_TO_COMPLETION_STEPS}-step bound",
        )

    def record_decision(
        self,
        workflow_run_id: str,
        *,
        node_id: str,
        decision_id: str,
        actor_id: str,
        value: Mapping[str, Any],
        reason: str,
    ) -> GraphRunSnapshot:
        """Apply one human decision to a paused decision node.

        Idempotent for the identical decision identity (same ``decision_id``,
        actor and value); any other decision under the same key fails closed.
        The reviewer identity travels as the event actor; the writer context
        is a separate payload field.
        """

        view = self._load(workflow_run_id, caller_plan=None)
        self._resolve_divergence(workflow_run_id, view)
        node = view.plan.node(node_id)
        if node.kind is not GraphNodeKind.DECISION:
            raise GraphRunError(
                "graph_decision_not_decision_node",
                f"node {node_id!r} is not a decision node",
            )
        existing = view.recorded_decisions.get(node_id)
        value_payload = _jsonable(dict(value))
        # The value hash identifies the decision for idempotent reuse/dedup;
        # the persisted node result hash (below) hashes the exact output
        # object downstream nodes consume.
        value_sha = _payload_sha256(value_payload)
        if existing is not None:
            if (
                existing["decision_id"] == decision_id
                and existing["actor_id"] == actor_id
                and existing["value_sha256"] == value_sha
            ):
                return self._snapshot(view, executed=set())
            raise GraphDecisionConflictError(
                "graph_decision_conflict",
                f"decision key {node.logical_key!r} already holds decision "
                f"{existing['decision_id']!r} by {existing['actor_id']!r}",
            )
        if node_id not in view.pending_decisions:
            raise GraphRunError(
                "graph_decision_not_pending",
                f"node {node_id!r} is not awaiting a human decision",
            )
        if not decision_id.strip() or not actor_id.strip() or not reason.strip():
            raise GraphRunError(
                "graph_decision_identity_invalid",
                "decision_id, actor_id and reason must be non-empty",
            )
        input_hashes = self._current_input_hashes(view, node)
        recorded_at = self._clock()
        decision_output = {
            "decision_id": decision_id,
            "actor_id": actor_id,
            "value": value_payload,
            "reason": reason,
        }
        # The result hash must identify the exact persisted output consumed
        # downstream — not the bare decision value.
        output_sha = _payload_sha256(decision_output)
        specs = [
            (
                EVENT_DECISION_RECORDED,
                {
                    "node_id": node_id,
                    "decision_key": node.logical_key,
                    "decision_id": decision_id,
                    "actor_id": actor_id,
                    "value": value_payload,
                    "value_sha256": value_sha,
                    "reason": reason,
                    "input_hashes": input_hashes,
                    "writer_context": {
                        "runtime_owner": self._runtime_owner,
                        "pid": os.getpid(),
                    },
                    "decided_at": recorded_at.isoformat(),
                },
                ActorType.USER,
                actor_id,
                "record_decision",
                reason,
            ),
            (
                EVENT_NODE_RESULT,
                self._decision_result_payload(
                    view, node, decision_output, output_sha, input_hashes,
                    recorded_at,
                ),
                ActorType.USER,
                actor_id,
                "apply_decision",
                reason,
            ),
        ]
        # Atomic CAS: the guard re-reads the stream inside the append
        # transaction, so a concurrent conflicting decision that committed
        # first fails this writer closed, and an identical decision is
        # reused exactly once (no second event).
        appended = self._append_events_tx(
            workflow_run_id,
            specs,
            guard=self._decision_guard(node_id, decision_id, actor_id, value_sha),
        )
        if not appended:
            view = self._load(workflow_run_id, caller_plan=None)
            return self._snapshot(view, executed=set())
        self._append_checkpoint(workflow_run_id, view.plan)
        view = self._load(workflow_run_id, caller_plan=None)
        if self._run_status(view) is GraphRunStatus.RUNNING:
            self._finish_run_if_complete(workflow_run_id, view)
            view = self._load(workflow_run_id, caller_plan=None)
        return self._snapshot(view, executed=set())

    def read_events(self, workflow_run_id: str) -> Tuple[DomainEvent, ...]:
        """Return the run's authoritative event stream."""

        with self._uow_factory() as uow:
            repo = uow.event_stream_repository
            head = repo.get_stream_head(self._project_id, workflow_run_id)
            if head is None:
                return ()
            return repo.read_events(self._project_id, workflow_run_id)

    def reservation_attempts(self, workflow_run_id: str, node_id: str):
        """Append-only reservation attempt lineage of one run node."""

        logical_call = self.logical_call_id(workflow_run_id, node_id)
        with self._reservation_repository_factory() as repo:
            return repo.list_attempts(self._project_id, logical_call)

    def node_has_live_dispatch(self, workflow_run_id: str, node_id: str) -> bool:
        """Read existing committed-repository OS ownership for UI progress.

        This does not change graph recovery semantics or revive an unknown
        outcome. Repositories without a liveness probe cannot prove an owner.
        """
        with self._reservation_repository_factory() as repo:
            attempts = repo.list_attempts(self._project_id, self.logical_call_id(workflow_run_id, node_id))
            if not attempts or attempts[-1].status not in (ReservationStatus.RUNNING, ReservationStatus.RESERVED):
                return False
            probe = getattr(repo, 'has_live_dispatch', None)
            return bool(callable(probe) and probe(self._project_id, attempts[-1].execution_reservation_id))

    def resolve_blocked_with_failure(
        self,
        workflow_run_id: str,
        *,
        node_id: str,
        resolution_id: str,
        reason: str,
    ) -> GraphRunSnapshot:
        """Explicitly close a dead-process crash window as failed.

        Both a RESERVED shell (dispatch never crossed) and a RUNNING shell
        (dispatch began but the owner died) require this explicit resolution
        before a new attempt.  A live lease is never closed by this method.
        """

        view = self._load(workflow_run_id, caller_plan=None)
        view.plan.node(node_id)
        status = self._node_status(view, node_id)
        if status is GraphNodeStatus.COMPLETED:
            return self._snapshot(view, executed=set())
        if status is GraphNodeStatus.FAILED:
            return self._snapshot(view, executed=set())  # already resolved
        if status is not GraphNodeStatus.BLOCKED_UNKNOWN:
            raise GraphRunError(
                "graph_node_not_blocked",
                f"node {node_id!r} is not blocked on an unresolved dispatch",
            )
        if not resolution_id.strip() or not reason.strip():
            raise GraphRunError(
                "graph_resolution_identity_invalid",
                "resolution_id and reason must be non-empty",
            )
        latest = self._latest_reservation(view, node_id)
        if latest is not None and latest.status in (
                ReservationStatus.RESERVED, ReservationStatus.RUNNING):
            if self.node_has_live_dispatch(workflow_run_id, node_id):
                raise GraphRunError(
                    "graph_reservation_contended_retryable",
                    f"node {node_id!r} still has a live dispatch lease; "
                    "reconcile it after the owner resolves",
                )
            with self._reservation_repository_factory() as repo:
                repo.transition(
                    self._project_id,
                    latest.execution_reservation_id,
                    to_status=ReservationStatus.FAILED,
                    terminal_state=ExecutionTerminalState.FAILED,
                    output_sha256=None,
                    error_code="crash_resolved_failed",
                    transport_attempts=latest.transport_attempts,
                    updated_at=self._clock(),
                )
        view = self._load(workflow_run_id, caller_plan=None)
        return self._snapshot(view, executed=set())

    def resolve_unknown_with_receipt(
        self,
        workflow_run_id: str,
        *,
        node_id: str,
        output: Optional[Mapping[str, Any]] = None,
        output_sha256: str,
        provider_session_id: Optional[str] = None,
    ) -> GraphRunSnapshot:
        """Adopt a verified recovered result for an unknown-outcome node.

        Receipt recovery restores USABLE content: the caller supplies the
        genuine output payload plus its declared hash; the runtime verifies
        the hash against the payload, persists the same typed
        ``graph_node_result`` event the original dispatch would have written
        (same schema, contract, and input provenance, marked as a recovered
        receipt), and converges the existing reservation to COMPLETED in
        place — no new dispatch, no new attempt.

        A hash without its payload is NOT completed usable content: the call
        is refused with a typed error and the node stays blocked (explicit
        reason), never certified, never wedged in an untyped exception.
        Unknown work is never auto-retried here.

        An actual recovered provider receipt identity is stored on the new
        result event. The historical UNKNOWN reservation identity is retained;
        a completion response id does not imply a native resumable session.
        """

        recovered_payload = _jsonable(dict(output)) if output is not None else None
        computed_sha = _payload_sha256(recovered_payload) if output is not None else None
        if output is not None and computed_sha != output_sha256:
            raise GraphRunError(
                "graph_receipt_hash_mismatch",
                "declared receipt hash does not match the supplied payload",
            )
        view = self._load(workflow_run_id, caller_plan=None)
        self._resolve_divergence(workflow_run_id, view)
        self._apply_reservation_repairs(view)
        node = view.plan.node(node_id)
        status = self._node_status(view, node_id)
        if status is GraphNodeStatus.COMPLETED:
            # Idempotent only for the identical already-adopted content; a
            # different receipt over a completed node is a typed conflict.
            existing = view.results.get(node_id)
            if (
                existing is not None
                and existing.get("output_sha256") == output_sha256
                and existing.get("recovered_receipt") is True
            ):
                return self._snapshot(view, executed=set())
            raise GraphRunError(
                "graph_node_completed",
                f"node {node_id!r} is already completed; a receipt can only "
                "recover an unknown outcome",
            )
        if status is not GraphNodeStatus.BLOCKED_UNKNOWN:
            raise GraphRunError(
                "graph_node_not_blocked",
                f"node {node_id!r} is not blocked on an unknown outcome",
            )
        if output is None:
            # Hash-only receipt: no usable content to restore.  The node
            # remains blocked with an explicit reason; it can later be
            # recovered with a payload-bearing receipt or an explicit retry.
            return self._snapshot(view, executed=set()).model_copy(
                update={
                    "stop_reason": (
                        "unknown_outcome_requires_payload_bearing_receipt"
                    )
                }
            )
        latest = self._latest_reservation(view, node_id)
        if latest is None or latest.status is not ReservationStatus.UNKNOWN_OUTCOME:
            raise GraphRunError(
                "graph_receipt_requires_unknown_outcome",
                f"node {node_id!r} has no UNKNOWN_OUTCOME reservation to "
                "converge; use the explicit failure/resolution path",
            )
        # Deterministic provenance: rebuild the same contract and input
        # binding the original dispatch used (inputs are reconstructible
        # from the authoritative events).
        input_hashes = self._current_input_hashes(view, node)
        contract = self._build_contract(workflow_run_id, view.plan, node, input_hashes)
        self._append_node_result(
            workflow_run_id=workflow_run_id,
            node=node,
            contract_payload=contract.model_dump(mode="json"),
            input_hashes=input_hashes,
            output_payload=recovered_payload,
            output_sha=computed_sha,
            reservation_id=latest.execution_reservation_id,
            attempt=latest.attempt,
            service_invocation=self._service_invocation(
                workflow_run_id, view.plan, node, latest.attempt
            ),
            recovered_receipt=True,
            provider_session_id=provider_session_id,
        )
        # Converge the existing reservation in place (UNKNOWN → COMPLETED),
        # never dispatching new work.
        with self._reservation_repository_factory() as repo:
            coordinator = ReservationCoordinator(repo)
            try:
                coordinator.recover_unknown(
                    project_id=self._project_id,
                    reservation_id=latest.execution_reservation_id,
                    recovered_output_receipt={
                        "output_sha256": computed_sha,
                        "provider_session_id": latest.provider_session_id,
                    },
                    now=self._clock(),
                )
            except RepositoryStateTransitionError as exc:
                current = repo.get(self._project_id, latest.execution_reservation_id)
                if not (current is not None
                        and current.status is ReservationStatus.COMPLETED
                        and current.output_sha256 == computed_sha):
                    raise GraphRunError(
                        "graph_reservation_contended_retryable",
                        "receipt reservation changed during recovery",
                    ) from exc
        self._append_checkpoint(workflow_run_id, view.plan)
        view = self._load(workflow_run_id, caller_plan=None)
        if self._run_status(view) is GraphRunStatus.RUNNING:
            self._finish_run_if_complete(workflow_run_id, view)
            view = self._load(workflow_run_id, caller_plan=None)
        return self._snapshot(view, executed=set())

    def retry_node(
        self,
        workflow_run_id: str,
        *,
        node_id: str,
        retry_decision_id: str,
        reason: str,
        plan: Optional[GraphPlan] = None,
    ) -> GraphRunSnapshot:
        """Append one explicit, auditable retry attempt for a node.

        Repeating the same ``retry_decision_id`` is idempotent; a distinct
        identity allocates the next append-only attempt (bounded by the
        node's ``allowed_attempts``).
        """

        view = self._load(workflow_run_id, caller_plan=plan)
        self._resolve_divergence(workflow_run_id, view)
        self._apply_reservation_repairs(view)
        node = view.plan.node(node_id)
        retry_limit = (
            plan.node(node_id).allowed_attempts
            if plan is not None
            else node.allowed_attempts
        )
        if not retry_decision_id.strip() or not reason.strip():
            raise GraphRunError(
                "graph_retry_identity_invalid",
                "retry_decision_id and reason must be non-empty",
            )
        # Repeating an already-executed retry decision identity is idempotent:
        # its derived decision-key reservation exists and is returned as-is.
        derived_retry_key = (
            f"{node.logical_key}::retry-decision:{retry_decision_id}"
        )
        with self._reservation_repository_factory() as repo:
            existing_decision = repo.find_by_logical_call(
                self._project_id,
                self.logical_call_id(workflow_run_id, node_id),
                derived_retry_key,
            )
        status = self._node_status(view, node_id)
        if existing_decision is not None:
            return self._snapshot(view, executed=set())
        if (status is GraphNodeStatus.BLOCKED_UNKNOWN
                and self.node_has_live_dispatch(workflow_run_id, node_id)):
            raise GraphRunError(
                "graph_reservation_contended_retryable",
                f"node {node_id!r} still has a live dispatch lease; "
                "reconcile it before retrying",
            )
        if status is GraphNodeStatus.COMPLETED:
            raise GraphRunError(
                "graph_node_completed",
                f"node {node_id!r} is already completed; no retry is needed",
            )
        if status not in (GraphNodeStatus.FAILED, GraphNodeStatus.BLOCKED_UNKNOWN):
            raise GraphRunError(
                "graph_node_not_retryable",
                f"node {node_id!r} is {status.value}; only failed or blocked "
                "nodes accept explicit retries",
            )
        attempts = self.reservation_attempts(workflow_run_id, node_id)
        if len(attempts) >= retry_limit:
            raise GraphRunError(
                "graph_retry_exhausted",
                f"node {node_id!r} already used {len(attempts)} of "
                f"{retry_limit} allowed attempts",
            )
        inputs, input_hashes = self._gather_inputs(view, node)
        contract = self._build_contract(workflow_run_id, view.plan, node, input_hashes)
        input_payload = self._input_payload(workflow_run_id, node, inputs, input_hashes)
        with self._reservation_repository_factory() as repo:
            coordinator = ReservationCoordinator(repo)
            try:
                outcome = coordinator.retry_explicit(
                    project_id=self._project_id,
                    logical_call_id=self.logical_call_id(workflow_run_id, node_id),
                    idempotency_key=node.logical_key,
                    node_contract=contract,
                    input_payload=input_payload,
                    now=self._clock(),
                    transport=self._transport_for(
                        workflow_run_id, view.plan, node, contract, inputs,
                        input_hashes, attempts[-1].attempt + 1,
                    ),
                    retry_reason=reason,
                    retry_decision_id=retry_decision_id,
                )
            except UnknownOutcomeConflictError as exc:
                raise GraphRunError(
                    "graph_reservation_contended_retryable",
                    f"node {node_id!r} is being dispatched by another "
                    "execution; retry after the winner resolves",
                ) from exc
            except IdempotencyConflictError as exc:
                raise GraphRunError(
                    "graph_input_binding_conflict",
                    f"node {node_id!r} logical call already holds a "
                    "different input binding",
                ) from exc
        del outcome
        view = self._load(workflow_run_id, caller_plan=None)
        executed: Set[str] = set()
        if self._node_status(view, node_id) is GraphNodeStatus.COMPLETED:
            executed.add(node_id)
            self._finish_run_if_complete(workflow_run_id, view)
            view = self._load(workflow_run_id, caller_plan=None)
        return self._snapshot(view, executed=executed)

    # ------------------------------------------------------------------
    # Reconstruction
    # ------------------------------------------------------------------

    def _load(
        self, workflow_run_id: str, *, caller_plan: Optional[GraphPlan]
    ) -> _RunView:
        with self._uow_factory() as uow:
            repo = uow.event_stream_repository
            head = repo.get_stream_head(self._project_id, workflow_run_id)
            if head is None:
                raise GraphRunError(
                    "graph_run_unknown",
                    f"no run exists for {workflow_run_id!r}",
                )
            events = repo.read_events(self._project_id, workflow_run_id)
        view = _RunView()
        view.workflow_run_id = workflow_run_id
        for event in events:
            payload = event.payload
            if event.event_type == EVENT_RUN_STARTED:
                view.plan = GraphPlan.model_validate(payload["plan"])
                view.root_payloads = dict(payload["root_payloads"])
                view.root_hashes = dict(payload["root_hashes"])
            elif event.event_type == EVENT_NODE_RESULT:
                view.results[payload["node_id"]] = dict(payload)
            elif event.event_type == EVENT_DECISION_PENDING:
                view.pending_decisions[payload["node_id"]] = payload["decision_key"]
            elif event.event_type == EVENT_DECISION_RECORDED:
                view.recorded_decisions[payload["node_id"]] = dict(payload)
            elif event.event_type == EVENT_RUN_COMPLETED:
                view.completed_event = True
            elif event.event_type in (EVENT_CHECKPOINT, EVENT_CHECKPOINT_REPAIRED):
                view.advisory = dict(payload.get("node_states") or {})
        if view.plan is None:  # pragma: no cover - run_started is first by construction
            raise GraphRunError(
                "graph_run_corrupt", f"run {workflow_run_id!r} has no start event"
            )
        if caller_plan is not None:
            self._assert_binding(view.plan, caller_plan, workflow_run_id)
        self._verify_contract_digests(view)
        self._load_reservation_states(view)
        return view

    @staticmethod
    def _retry_budget_compatible(stored: GraphPlan, caller: GraphPlan) -> bool:
        """Allow only a monotonic retry-budget expansion on an old run."""
        stored_payload = stored.material_payload()
        caller_payload = caller.material_payload()
        stored_limits = {
            item["node_id"]: item["allowed_attempts"]
            for item in stored_payload["nodes"]
        }
        caller_limits = {
            item["node_id"]: item["allowed_attempts"]
            for item in caller_payload["nodes"]
        }
        stored_nodes = {
            item["node_id"]: item for item in stored_payload["nodes"]
        }
        caller_nodes = {
            item["node_id"]: item for item in caller_payload["nodes"]
        }
        for payload in (stored_payload, caller_payload):
            for item in payload["nodes"]:
                item.pop("allowed_attempts", None)
        if stored_payload != caller_payload or stored_nodes.keys() != caller_nodes.keys():
            return False
        return all(
            caller_limits[node_id] >= stored_limits[node_id]
            for node_id in stored_limits
        )

    def _assert_binding(
        self, stored: GraphPlan, caller: GraphPlan, workflow_run_id: str
    ) -> None:
        exact = (
            stored.project_id == caller.project_id
            and stored.branch_id == caller.branch_id
            and stored.graph_id == caller.graph_id
            and stored.graph_version == caller.graph_version
            and stored.material_sha256() == caller.material_sha256()
        )
        if exact or self._retry_budget_compatible(stored, caller):
            return
        raise GraphPlanBindingError(
            "graph_plan_binding_mismatch",
            f"run {workflow_run_id!r} is bound to graph "
            f"{stored.graph_id!r} version {stored.graph_version!r} "
            f"(material {stored.material_sha256()[:12]}…), not "
            f"{caller.graph_id!r} version {caller.graph_version!r} "
            f"(material {caller.material_sha256()[:12]}…); old graphs are "
            "rejected",
        )

    def _verify_contract_digests(self, view: _RunView) -> None:
        """Re-verify every persisted v1_1 contract digest on reconstruction."""

        for node_id, result in view.results.items():
            contract_payload = result.get("execution_contract")
            if not contract_payload:
                continue
            contract = NodeExecutionContract.model_validate(contract_payload)
            hashes = tuple(sorted(set((result.get("input_hashes") or {}).values())))
            if not contract.matches_dependencies(hashes):
                raise GraphRunError(
                    "graph_contract_digest_mismatch",
                    f"persisted contract for node {node_id!r} does not match "
                    "its recorded input hashes",
                )

    def _load_reservation_states(self, view: _RunView) -> None:
        """Read the reservation ledger once per reconstruction.

        Populates per-node latest reservation status/output plus the repair
        list (result events whose reservation never reached a terminal
        state).
        """

        repairs: list[Tuple[str, str, str]] = []
        pending_nodes = [
            node
            for node in view.plan.nodes
            if node.node_id not in view.results
            and node.kind is not GraphNodeKind.DECISION
        ]
        with self._reservation_repository_factory() as repo:
            for node in pending_nodes:
                attempts = repo.list_attempts(
                    self._project_id,
                    self.logical_call_id(view.workflow_run_id, node.node_id),
                )
                if not attempts:
                    continue
                latest = attempts[-1]
                view.reservation_status[node.node_id] = latest.status
            for node_id, result in view.results.items():
                reservation_id = result.get("reservation_id")
                if not reservation_id:
                    continue
                persisted = repo.get(self._project_id, reservation_id)
                if persisted is not None and persisted.status in (
                    ReservationStatus.RUNNING,
                    ReservationStatus.UNKNOWN_OUTCOME,
                    ReservationStatus.RESERVED,
                ):
                    repairs.append(
                        (node_id, reservation_id, result["output_sha256"])
                    )
        view.reservation_repairs = tuple(repairs)

    def _latest_reservation(self, view: _RunView, node_id: str):
        attempts = self.reservation_attempts(view.workflow_run_id, node_id)
        return attempts[-1] if attempts else None

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def _node_status(self, view: _RunView, node_id: str) -> GraphNodeStatus:
        node = view.plan.node(node_id)
        if node_id in view.results:
            return GraphNodeStatus.COMPLETED
        if node.kind is GraphNodeKind.DECISION:
            if node_id in view.recorded_decisions:
                return GraphNodeStatus.COMPLETED
            if node_id in view.pending_decisions:
                return GraphNodeStatus.AWAITING_DECISION
            return GraphNodeStatus.PENDING
        latest = view.reservation_status.get(node_id)
        if latest in (ReservationStatus.RUNNING, ReservationStatus.UNKNOWN_OUTCOME):
            return GraphNodeStatus.BLOCKED_UNKNOWN
        if latest is ReservationStatus.FAILED:
            return GraphNodeStatus.FAILED
        if latest is ReservationStatus.COMPLETED:
            # Terminal reservation WITHOUT a result event: a hash-only
            # completion is not usable content.  The node stays blocked —
            # it must be recovered with a payload-bearing receipt or an
            # explicit retry — and never certifies run completion.
            return GraphNodeStatus.BLOCKED_UNKNOWN
        return GraphNodeStatus.PENDING

    def _run_status(self, view: _RunView) -> GraphRunStatus:
        statuses = {
            node.node_id: self._node_status(view, node.node_id)
            for node in view.plan.nodes
        }
        if view.completed_event and all(
            status is GraphNodeStatus.COMPLETED for status in statuses.values()
        ):
            return GraphRunStatus.COMPLETED
        if any(
            status is GraphNodeStatus.AWAITING_DECISION
            for status in statuses.values()
        ):
            return GraphRunStatus.AWAITING_DECISION
        if any(
            status in (GraphNodeStatus.FAILED, GraphNodeStatus.BLOCKED_UNKNOWN)
            for status in statuses.values()
        ):
            return GraphRunStatus.BLOCKED
        return GraphRunStatus.RUNNING

    def _checkpoint_divergence(self, view: _RunView) -> Optional[str]:
        if view.advisory is None:
            return None
        derived = {
            node.node_id: self._node_status(view, node.node_id).value
            for node in view.plan.nodes
        }
        if view.advisory == derived:
            return None
        differing = sorted(
            node_id
            for node_id, status in derived.items()
            if view.advisory.get(node_id) != status
        )
        return f"checkpoint diverges at: {differing}"

    def _snapshot(self, view: _RunView, *, executed: Set[str]) -> GraphRunSnapshot:
        records = []
        for node_id in view.plan.topological_order():
            node = view.plan.node(node_id)
            status = self._node_status(view, node_id)
            result = view.results.get(node_id)
            output_sha = None
            attempt = None
            if result is not None:
                output_sha = result["output_sha256"]
                attempt = result.get("attempt")
            records.append(
                GraphNodeStateRecord(
                    node_id=node_id,
                    status=status,
                    logical_key=node.logical_key,
                    output_sha256=output_sha,
                    attempt=attempt,
                    executed_in_last_call=node_id in executed,
                )
            )
        return GraphRunSnapshot(
            workflow_run_id=view.workflow_run_id,
            project_id=view.plan.project_id,
            branch_id=view.plan.branch_id,
            graph_id=view.plan.graph_id,
            graph_version=view.plan.graph_version,
            graph_sha256=view.plan.material_sha256(),
            status=self._run_status(view),
            nodes=tuple(records),
            checkpoint_divergence=self._checkpoint_divergence(view),
        )

    # ------------------------------------------------------------------
    # Execution internals
    # ------------------------------------------------------------------

    def _execute_node(
        self, workflow_run_id: str, view: _RunView, node: GraphNodePlan
    ) -> None:
        inputs, input_hashes = self._gather_inputs(view, node)
        contract = self._build_contract(workflow_run_id, view.plan, node, input_hashes)
        input_payload = self._input_payload(workflow_run_id, node, inputs, input_hashes)
        with self._reservation_repository_factory() as repo:
            coordinator = ReservationCoordinator(repo)
            try:
                outcome = coordinator.reserve_or_reuse(
                    project_id=self._project_id,
                    node_contract=contract,
                    input_payload=input_payload,
                    now=self._clock(),
                    transport=self._transport_for(
                        workflow_run_id, view.plan, node, contract, inputs,
                        input_hashes, self._next_attempt(workflow_run_id, node.node_id),
                    ),
                )
            except UnknownOutcomeConflictError as exc:
                # A concurrent dispatch of the same logical call holds the
                # live shell.  Fail closed as a typed WAIT/RETRY-LATER
                # signal — never permission to dispatch — and converge on a
                # later advance once the winner resolves.
                raise GraphRunError(
                    "graph_reservation_contended_retryable",
                    f"node {node.node_id!r} is being dispatched by another "
                    "execution; retry after the winner resolves",
                ) from exc
            except IdempotencyConflictError as exc:
                # Same logical call, different material input: a hard
                # conflict, not a retry.
                raise GraphRunError(
                    "graph_input_binding_conflict",
                    f"node {node.node_id!r} logical call already holds a "
                    "different input binding",
                ) from exc
            outcome = self._recover_zero_attempt_orphan(
                workflow_run_id,
                view.plan,
                node,
                coordinator,
                outcome,
                contract,
                input_payload,
            )
        if outcome.terminal_state is ExecutionTerminalState.COMPLETED:
            # The result event was already committed by the transport (this
            # call) or by the original dispatching process (reuse).
            self._append_checkpoint(workflow_run_id, view.plan)
        # FAILED (deterministic preflight rejection) and UNKNOWN_OUTCOME
        # (ambiguous dispatch) are never auto-retried: the node stays failed
        # or blocked for explicit owner action.

    def _recover_zero_attempt_orphan(
        self,
        workflow_run_id: str,
        plan: GraphPlan,
        node: GraphNodePlan,
        coordinator: ReservationCoordinator,
        outcome: ReservationOutcome,
        contract: NodeExecutionContract,
        input_payload: Mapping[str, Any],
    ) -> ReservationOutcome:
        """Retry a disposed zero-transport-attempt orphan shell exactly once.

        The coordinator classifies a dangling RESERVED shell with no live
        owner as ``FAILED`` with zero transport attempts — proof that no
        physical dispatch ever started.  Re-running it is not a redispatch of
        ambiguous work: the runtime retries through the coordinator's
        explicit, append-only path under a deterministic, idempotent recovery
        decision identity.
        """

        reservation = outcome.reservation
        if (
            outcome.terminal_state is not ExecutionTerminalState.FAILED
            or reservation.error_code != ORPHAN_DISPATCH_NOT_STARTED
            or reservation.transport_attempts != 0
        ):
            return outcome
        inputs, input_hashes = self._inputs_from_payload(input_payload)
        try:
            return coordinator.retry_explicit(
                project_id=self._project_id,
                logical_call_id=self.logical_call_id(workflow_run_id, node.node_id),
                idempotency_key=node.logical_key,
                node_contract=contract,
                input_payload=dict(input_payload),
                now=self._clock(),
                transport=self._transport_for(
                    workflow_run_id, plan, node, contract, inputs, input_hashes,
                    reservation.attempt + 1,
                ),
                retry_reason="orphan shell recovery: dispatch never started",
                retry_decision_id=f"orphan-recovery:{reservation.execution_reservation_id}",
            )
        except UnknownOutcomeConflictError as exc:
            raise GraphRunError(
                "graph_reservation_contended_retryable",
                f"node {node.node_id!r} orphan recovery lost a concurrent "
                "claim; retry after the winner resolves",
            ) from exc

    @staticmethod
    def _inputs_from_payload(
        input_payload: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        return (
            dict(input_payload["inputs"]),
            dict(input_payload["input_hashes"]),
        )

    def _open_decision_pause(
        self, workflow_run_id: str, view: _RunView, node: GraphNodePlan
    ) -> None:
        if node.node_id in view.pending_decisions:
            return
        input_hashes = self._current_input_hashes(view, node)
        self._append_events(
            workflow_run_id,
            [
                (
                    EVENT_DECISION_PENDING,
                    {
                        "node_id": node.node_id,
                        "decision_key": node.logical_key,
                        "input_hashes": input_hashes,
                    },
                    ActorType.SYSTEM,
                    RUNTIME_ACTOR_ID,
                    "pause",
                    "human decision required before the locked chain continues",
                )
            ],
        )
        self._append_checkpoint(workflow_run_id, view.plan)

    def _gather_inputs(
        self, view: _RunView, node: GraphNodePlan
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        inputs: Dict[str, Any] = {}
        hashes: Dict[str, str] = {}
        for schema in node.input_schemas:
            if schema in view.root_payloads:
                inputs[schema] = view.root_payloads[schema]
                hashes[schema] = view.root_hashes[schema]
                continue
            producer = None
            for candidate in view.plan.nodes:
                if candidate.output_schema == schema:
                    producer = candidate
                    break
            result = view.results.get(producer.node_id) if producer else None
            if result is None or result.get("output") is None:
                raise GraphRunError(
                    "graph_result_payload_missing",
                    f"input schema {schema!r} of node {node.node_id!r} has no "
                    "committed result payload",
                )
            inputs[schema] = result["output"]
            hashes[schema] = result["output_sha256"]
        return inputs, hashes

    def _current_input_hashes(self, view: _RunView, node: GraphNodePlan) -> Dict[str, str]:
        _, hashes = self._gather_inputs(view, node)
        return hashes

    def _input_payload(
        self,
        workflow_run_id: str,
        node: GraphNodePlan,
        inputs: Mapping[str, Any],
        input_hashes: Mapping[str, str],
    ) -> Dict[str, Any]:
        return {
            "workflow_run_id": workflow_run_id,
            "node_id": node.node_id,
            "inputs": dict(inputs),
            "input_hashes": dict(input_hashes),
        }

    def _build_contract(
        self,
        workflow_run_id: str,
        plan: GraphPlan,
        node: GraphNodePlan,
        input_hashes: Mapping[str, str],
    ) -> NodeExecutionContract:
        """Build the dispatch contract and compact it to v1_1 immediately."""

        # A resumed call uses the contract recorded before its physical
        # dispatch, even when current registry or factory configuration changed.
        for event in self.read_events(workflow_run_id):
            if event.event_type == _EVENT_NODE_DISPATCH and event.payload.get('node_id') == node.node_id:
                pinned = NodeExecutionContract.model_validate(event.payload['execution_contract'])
                if not pinned.matches_dependencies(tuple(sorted(set(input_hashes.values())))):
                    raise GraphRunError('graph_execution_contract_binding_mismatch',
                                        'recorded dispatch contract has different inputs')
                return pinned

        node_spec = canonical_json(
            {
                "graph_id": plan.graph_id,
                "graph_version": plan.graph_version,
                "node_id": node.node_id,
                "kind": node.kind.value,
                "output_schema": node.output_schema,
                "input_schemas": sorted(node.input_schemas),
            }
        )
        contract = NodeExecutionContract(
            node_execution_contract_id=f"nec:{workflow_run_id}:{node.node_id}",
            skill_definition_id=f"skill:{plan.graph_id}:{node.node_id}",
            role=node.owner.value,
            harness="graph_runtime",
            provider="deterministic-offline",
            model="deterministic-offline",
            reasoning_effort=ReasoningEffort.LOW,
            same_session_recovery=True,
            timeout_seconds=300,
            fallback_policy_id="fbp:graph-runtime",
            prompt_sha256=hashlib.sha256(node_spec.encode("utf-8")).hexdigest(),
            input_schema_ref=f"schema:{plan.graph_id}:{node.node_id}:input",
            output_schema_ref=f"schema:{plan.graph_id}:{node.output_schema}",
            allowed_tools=(),
            allowed_paths=(),
            permission_policy_id="perm:graph-runtime",
            input_artifact_hashes=tuple(sorted(set(input_hashes.values()))),
            sensitivity_tier=SensitivityTier.INTERNAL,
            allowed_providers=("deterministic-offline",),
            allowed_regions=("offline",),
            redaction_policy_id="redact:graph-runtime",
            retention_policy_id="retain:graph-runtime",
            logical_call_id=self.logical_call_id(workflow_run_id, node.node_id),
            idempotency_key=node.logical_key,
        )
        factory = self._execution_contract_factories.get(node.node_id)
        if factory is not None:
            configured = factory(contract)
            if not isinstance(configured, NodeExecutionContract):
                raise GraphRunError('graph_execution_contract_invalid', 'node contract factory must return a typed contract')
            # The application supplies model/skill configuration; the graph
            # continues to own call identity and dependency binding.
            if any(getattr(configured, field) != getattr(contract, field) for field in (
                'node_execution_contract_id', 'logical_call_id', 'idempotency_key',
            )) or not configured.matches_dependencies(tuple(sorted(set(input_hashes.values())))):
                raise GraphRunError('graph_execution_contract_binding_mismatch',
                                    'configured node contract changed graph call or input identity')
            contract = configured
        # Executed minor-version compaction: the persisted dispatch contract
        # is the v1_1 dependency-compacted representation.
        return contract.compact_dependencies()

    def _next_attempt(self, workflow_run_id: str, node_id: str) -> int:
        """Attempt number the next dispatch of this node would carry."""

        attempts = self.reservation_attempts(workflow_run_id, node_id)
        return (attempts[-1].attempt + 1) if attempts else 1

    def _transport_for(
        self,
        workflow_run_id: str,
        plan: GraphPlan,
        node: GraphNodePlan,
        contract: NodeExecutionContract,
        inputs: Mapping[str, Any],
        input_hashes: Mapping[str, str],
        attempt: int,
    ) -> _ServiceTransport:
        return _ServiceTransport(
            runtime=self,
            workflow_run_id=workflow_run_id,
            plan=plan,
            node=node,
            contract_payload=contract.model_dump(mode="json"),
            inputs=inputs,
            input_hashes=input_hashes,
            attempt=attempt,
        )

    def _service_invocation(
        self,
        workflow_run_id: str,
        plan: GraphPlan,
        node: GraphNodePlan,
        attempt: int,
    ) -> Dict[str, Any]:
        """Typed provenance of one injected service invocation.

        Records WHICH declared inputs the service was invoked over and the
        writer context that persisted the result — the offline-orchestration
        evidence that an injected QC/review invocation is bound to its
        declared inputs and separate from the writer-private context and
        from any user confirmation.  This is orchestration provenance, not
        actual-model context or clinical acceptance.
        """

        return {
            "service_id": f"svc:{plan.graph_id}:{node.node_id}",
            "invocation_id": (
                f"svcinv:{workflow_run_id}:{node.node_id}:{attempt}"
            ),
            "owner": node.owner.value,
            "declared_input_schemas": sorted(node.input_schemas),
            "writer_context": {
                "runtime_owner": self._runtime_owner,
                "pid": os.getpid(),
            },
        }

    def _append_node_result(
        self,
        workflow_run_id: str,
        node: GraphNodePlan,
        contract_payload: Dict[str, Any],
        input_hashes: Mapping[str, str],
        output_payload: Dict[str, Any],
        output_sha: str,
        reservation_id: str,
        attempt: int,
        service_invocation: Optional[Dict[str, Any]] = None,
        recovered_receipt: bool = False,
        provider_session_id: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "node_id": node.node_id,
            "logical_key": node.logical_key,
            "output_schema": node.output_schema,
            "output": output_payload,
            "output_sha256": output_sha,
            "input_hashes": dict(input_hashes),
            "execution_contract": contract_payload,
            "reservation_id": reservation_id,
            "attempt": attempt,
        }
        if service_invocation is not None:
            payload["service_invocation"] = service_invocation
        if provider_session_id is not None:
            payload['provider_session_id'] = provider_session_id
        if recovered_receipt:
            payload["recovered_receipt"] = True
        def receipt_guard(events):
            for event in events:
                if (event.event_type == EVENT_NODE_RESULT
                        and event.payload.get("node_id") == node.node_id):
                    if (event.payload.get("output_sha256") == output_sha
                            and event.payload.get("reservation_id") == reservation_id
                            and event.payload.get("recovered_receipt") is True):
                        return False
                    raise GraphRunError(
                        "graph_node_completed", "node already has a different result"
                    )
            return True

        append = self._append_events_tx if recovered_receipt else self._append_events
        append(
            workflow_run_id,
            [
                (
                    EVENT_NODE_RESULT,
                    payload,
                    ActorType.SYSTEM,
                    RUNTIME_ACTOR_ID,
                    "node_result",
                    f"committed result of node {node.node_id}",
                )
            ],
            **({"guard": receipt_guard} if recovered_receipt else {}),
        )

    def _decision_result_payload(
        self,
        view: _RunView,
        node: GraphNodePlan,
        decision_output: Mapping[str, Any],
        output_sha: str,
        input_hashes: Mapping[str, str],
        recorded_at: datetime,
    ) -> Dict[str, Any]:
        return {
            "node_id": node.node_id,
            "logical_key": node.logical_key,
            "output_schema": node.output_schema,
            "output": dict(decision_output),
            # Hash of the exact persisted output consumed downstream.
            "output_sha256": output_sha,
            "input_hashes": dict(input_hashes),
            "decided_at": recorded_at.isoformat(),
        }

    def _finish_run_if_complete(self, workflow_run_id: str, view: _RunView) -> None:
        if view.completed_event:
            return
        statuses = {
            node.node_id: self._node_status(view, node.node_id)
            for node in view.plan.nodes
        }
        if not all(
            status is GraphNodeStatus.COMPLETED for status in statuses.values()
        ):
            return
        # Run completion is certified only by durable result payloads: a
        # hash-only reservation completion never carries a usable artifact
        # and is classified blocked, so it can never reach here.
        missing = [
            node_id for node_id in statuses if node_id not in view.results
        ]
        if missing:  # pragma: no cover - defensive against corrupt state
            raise GraphRunError(
                "graph_completion_missing_results",
                f"run completion refused: nodes {missing} have no durable "
                "result payload",
            )
        final_state = {
            node_id: view.results[node_id]["output_sha256"]
            for node_id in statuses
        }
        def completion_guard(events):
            for event in events:
                if event.event_type != EVENT_RUN_COMPLETED:
                    continue
                if (event.payload.get("graph_sha256") != view.plan.material_sha256()
                        or event.payload.get("final_state") != final_state):
                    raise GraphRunError("graph_completion_conflict", "stored completion differs from durable results")
                return False
            return True
        appended = self._append_events_tx(
            workflow_run_id,
            [
                (
                    EVENT_RUN_COMPLETED,
                    {
                        "graph_sha256": view.plan.material_sha256(),
                        "final_state": final_state,
                    },
                    ActorType.SYSTEM,
                    RUNTIME_ACTOR_ID,
                    "complete",
                    "all nodes completed; run certified by the event chain",
                )
            ],
            guard=completion_guard,
        )
        if appended:
            self._append_checkpoint(workflow_run_id, view.plan)

    # ------------------------------------------------------------------
    # Event append helpers
    # ------------------------------------------------------------------

    def _append_events(self, workflow_run_id: str, specs) -> None:
        with self._uow_factory() as uow:
            repo = uow.event_stream_repository
            head = repo.get_stream_head(self._project_id, workflow_run_id)
            builder = EventEnvelopeBuilder()
            domain_events = []
            sequence = head.last_sequence if head is not None else 0
            previous = head.last_event_sha256 if head is not None else None
            for (
                event_type, payload, actor_type, actor_id, action, reason
            ) in specs:
                sequence += 1
                event = builder.build(
                    domain_event_id=f"{workflow_run_id}:{event_type}:{sequence}",
                    stream_id=workflow_run_id,
                    sequence=sequence,
                    event_type=event_type,
                    payload_schema_version=GRAPH_EVENT_SCHEMA_VERSION,
                    upcaster_id=GRAPH_EVENT_UPCASTER_ID,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    reason=reason,
                    payload=_jsonable(payload),
                    emitted_at=self._clock(),
                    previous_event_sha256=previous,
                )
                previous = event.event_sha256
                domain_events.append(event)
            repo.append_events(self._project_id, workflow_run_id, domain_events)

    def _append_events_tx(
        self,
        workflow_run_id: str,
        specs,
        guard=None,
    ) -> bool:
        """Append *specs* atomically with an in-transaction semantic check.

        The caller's stale pre-check (its own earlier ``_load``) is advisory
        only; the authoritative semantic decision is the ``guard`` callback,
        which runs INSIDE the same unit-of-work transaction as the append,
        after a fresh authoritative read of the whole stream and before any
        row is written.  Under SQLite's single-writer ``BEGIN IMMEDIATE``
        this makes check-then-append one atomic step: a concurrent writer
        that committed first is always visible to the loser's guard, so
        conflicting decisions/starts fail closed with their typed errors and
        identical work is reused exactly once.

        ``guard(events)`` returns ``True`` to proceed with the append,
        ``False`` to skip it (idempotent reuse — the work is already fully
        applied), or raises a typed error (``GraphDecisionConflictError`` /
        ``GraphPlanBindingError``) to fail closed and roll back.
        """

        with self._uow_factory() as uow:
            repo = uow.event_stream_repository
            events = repo.read_events(self._project_id, workflow_run_id)
            if guard is not None and guard(events) is False:
                return False
            head = repo.get_stream_head(self._project_id, workflow_run_id)
            builder = EventEnvelopeBuilder()
            domain_events = []
            sequence = head.last_sequence if head is not None else 0
            previous = head.last_event_sha256 if head is not None else None
            for (
                event_type, payload, actor_type, actor_id, action, reason
            ) in specs:
                sequence += 1
                event = builder.build(
                    domain_event_id=f"{workflow_run_id}:{event_type}:{sequence}",
                    stream_id=workflow_run_id,
                    sequence=sequence,
                    event_type=event_type,
                    payload_schema_version=GRAPH_EVENT_SCHEMA_VERSION,
                    upcaster_id=GRAPH_EVENT_UPCASTER_ID,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    reason=reason,
                    payload=_jsonable(payload),
                    emitted_at=self._clock(),
                    previous_event_sha256=previous,
                )
                previous = event.event_sha256
                domain_events.append(event)
            repo.append_events(self._project_id, workflow_run_id, domain_events)
        return True

    @staticmethod
    def _decision_guard(
        node_id: str,
        decision_id: str,
        actor_id: str,
        value_sha256: str,
    ):
        """In-transaction decision CAS.

        No recorded decision → proceed.  Identical identity (same decision
        id, actor and value hash) → idempotent reuse (``False``).  Any other
        decision under the same key → typed conflict.
        """

        def guard(events) -> bool:
            for event in events:
                if (
                    event.event_type == EVENT_DECISION_RECORDED
                    and event.payload.get("node_id") == node_id
                ):
                    payload = event.payload
                    if (
                        payload.get("decision_id") == decision_id
                        and payload.get("actor_id") == actor_id
                        and payload.get("value_sha256") == value_sha256
                    ):
                        return False
                    raise GraphDecisionConflictError(
                        "graph_decision_conflict",
                        f"decision key already holds decision "
                        f"{payload.get('decision_id')!r} by "
                        f"{payload.get('actor_id')!r}",
                    )
            return True

        return guard

    @staticmethod
    def _start_guard(plan: GraphPlan, root_hashes: Mapping[str, str]):
        """In-transaction run-creation CAS.

        No start event → proceed.  Identical plan identity *and* identical
        root input identities → idempotent reuse (``False``).  Anything else
        (old graph version, different material, different root facts) →
        typed binding conflict; a concurrent start never double-creates a
        run and never silently rebinds its identity or roots.
        """

        def guard(events) -> bool:
            for event in events:
                if event.event_type == EVENT_RUN_STARTED:
                    stored = GraphPlan.model_validate(event.payload["plan"])
                    stored_roots = dict(event.payload.get("root_hashes") or {})
                    if (
                        stored.project_id == plan.project_id
                        and stored.branch_id == plan.branch_id
                        and stored.graph_id == plan.graph_id
                        and stored.graph_version == plan.graph_version
                        and (
                            stored.material_sha256() == plan.material_sha256()
                            or GraphRuntime._retry_budget_compatible(stored, plan)
                        )
                        and stored_roots == dict(root_hashes)
                    ):
                        return False
                    raise GraphPlanBindingError(
                        "graph_run_binding_conflict",
                        f"run already started with graph "
                        f"{stored.graph_id!r} version {stored.graph_version!r} "
                        f"(material {stored.material_sha256()[:12]}…) and root "
                        f"identities {sorted(stored_roots.items())}; refusing "
                        "to double-create or silently rebind",
                    )
            return True

        return guard

    def _append_checkpoint(self, workflow_run_id: str, plan: GraphPlan) -> None:
        """Write the advisory checkpoint in its own transaction.

        Deliberately separate from the authoritative event batch so the
        crash window between the two is real and the repair path is
        exercised by genuine process death.
        """

        view = self._load(workflow_run_id, caller_plan=None)
        node_states = {
            node.node_id: self._node_status(view, node.node_id).value
            for node in plan.nodes
        }
        self._append_events(
            workflow_run_id,
            [
                (
                    EVENT_CHECKPOINT,
                    {"node_states": node_states},
                    ActorType.SYSTEM,
                    RUNTIME_ACTOR_ID,
                    "checkpoint",
                    "advisory progress snapshot (never authoritative)",
                )
            ],
        )

    def _resolve_divergence(self, workflow_run_id: str, view: _RunView) -> None:
        divergence = self._checkpoint_divergence(view)
        if divergence is None:
            return
        node_states = {
            node.node_id: self._node_status(view, node.node_id).value
            for node in view.plan.nodes
        }
        self._append_events(
            workflow_run_id,
            [
                (
                    EVENT_CHECKPOINT_REPAIRED,
                    {"detected": divergence, "node_states": node_states},
                    ActorType.SYSTEM,
                    RUNTIME_ACTOR_ID,
                    "repair_checkpoint",
                    "advisory checkpoint rebuilt from authoritative events",
                )
            ],
        )
        view.advisory = node_states

    def _apply_reservation_repairs(self, view: _RunView) -> None:
        """Complete non-terminal reservations from committed result events.

        The result event is the authoritative outcome; a reservation left
        running/unknown after its result was committed is transitioned in
        place with the recorded output hash.  History is never rewritten.
        """

        if not view.reservation_repairs:
            return
        with self._reservation_repository_factory() as repo:
            for _node_id, reservation_id, output_sha in view.reservation_repairs:
                persisted = repo.get(self._project_id, reservation_id)
                if persisted is not None and persisted.status in (
                    ReservationStatus.RUNNING,
                    ReservationStatus.UNKNOWN_OUTCOME,
                ):
                    repo.transition(
                        self._project_id,
                        reservation_id,
                        to_status=ReservationStatus.COMPLETED,
                        terminal_state=ExecutionTerminalState.COMPLETED,
                        output_sha256=output_sha,
                        provider_session_id=(
                            view.results[_node_id].get('provider_session_id')
                            if persisted.status is ReservationStatus.RUNNING else None
                        ),
                        error_code=None,
                        updated_at=self._clock(),
                    )
        view.reservation_repairs = ()
