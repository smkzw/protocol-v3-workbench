"""Functional v2→v3 mutation guard: route + service layers, fail closed.

Worker 03 guard.  The guard is the *runtime* counterpart of the curated
inventory (:mod:`app.protocol_workflow.legacy.mutation_route_inventory`) and
the per-project cutover state (:mod:`app.protocol_workflow.legacy.cutover_state`):

* a legacy mutation (any inventoried ``legacy_write`` operation) is permitted
  only while the project is in ``LEGACY_ACTIVE``;
* in ``SHADOW_READ_ONLY`` and ``NEW_CANONICAL`` every legacy mutation raises
  the **one typed, stable fail-closed error** — :class:`LegacyMutationBlocked`
  with code ``legacy_mutation_blocked`` — identically at the route layer and
  the service layer (route/service symmetry is enforced by the same code path
  and proven by tests);
* reads stay available in every state and preserve the exact supplied legacy
  payload/hash/project identity (:meth:`MutationGuard.legacy_read`), with the
  payload deep-frozen so callers can never mutate the supplied source or the
  returned copy;
* unknown cutover state (no record) fails closed: it is never treated as
  writable; an operation absent from the inventory also fails closed with a
  configuration error (the drift check guarantees the shipped inventory is
  complete, so a missing entry means the inventory is stale and must not
  silently pass).

A rollback helper (:class:`RollbackHelper`) may disable the *new* command
attachment while retaining v3 events, but it holds no cutover-write
capability: it can never reactivate legacy fact writes and can never reverse
cutover automatically.
"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from hashlib import sha256
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..canonical.hashing import exact_payload_sha256

from .cutover_state import CutoverStateRegistry, ProjectCutoverState
from .mutation_route_inventory import (
    MutatorClassification,
    MutationInventory,
    build_inventory,
)

__all__ = [
    "LegacyMutationBlocked",
    "LegacyReadResult",
    "MutationGuard",
    "MutationGuardConfigurationError",
    "RollbackHelper",
]

LEGACY_MUTATION_BLOCKED_CODE = "legacy_mutation_blocked"


class LegacyMutationBlocked(Exception):
    """The ONE typed, stable fail-closed error for blocked legacy mutations.

    Raised identically by the route-layer and service-layer guards whenever a
    ``legacy_write`` operation is attempted outside ``LEGACY_ACTIVE``.
    """

    code = LEGACY_MUTATION_BLOCKED_CODE

    def __init__(
        self,
        *,
        project_id: str,
        operation_id: str,
        state: Optional[ProjectCutoverState],
        layer: str,
    ) -> None:
        super().__init__(
            f"legacy mutation blocked for project {project_id!r} in state "
            f"{state.value if state is not None else 'unknown'} "
            f"(operation {operation_id!r}, layer {layer})"
        )
        self.project_id = project_id
        self.operation_id = operation_id
        self.state = state
        self.layer = layer

    def to_payload(self) -> dict[str, object]:
        """Stable, typed public payload (both layers share this shape)."""

        return {
            "code": self.code,
            "project_id": self.project_id,
            "operation_id": self.operation_id,
            "state": self.state.value if self.state is not None else "unknown",
            "layer": self.layer,
        }


class MutationGuardConfigurationError(RuntimeError):
    """Fail-closed drift: an operation is not inventoried.

    The AST drift check keeps the shipped inventory complete, so this error
    means the inventory is stale relative to the running source; the guard
    never silently permits an unclassified mutation.
    """


class LegacyReadResult(BaseModel):
    """Typed read-parity result: exact supplied payload + hash + project id.

    ``payload`` is a deep-frozen copy of the caller-supplied legacy payload;
    ``payload_sha256`` is the canonical hash of that exact payload; the
    project identity is preserved verbatim.  Identical in every cutover state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    payload: Any
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "payload": self.payload,
            "payload_sha256": self.payload_sha256,
        }


class _FrozenPayload(dict):
    """JSON mapping that serialises like a dict but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy read payload is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


class _FrozenList(list):
    """JSON list that serialises like a list but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy read payload list is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenPayload({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_json(item) for item in value)
    return value


class MutationGuard:
    """Functional guard binding cutover state + inventory at both layers.

    Pure in-memory; the caller owns the :class:`CutoverStateRegistry`
    instance (this task performs no persistence or feature-flag wiring).
    """

    def __init__(
        self,
        *,
        states: CutoverStateRegistry,
        inventory: Optional[MutationInventory] = None,
    ) -> None:
        self._states = states
        self._inventory = inventory if inventory is not None else build_inventory()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def state_of(self, project_id: str) -> Optional[ProjectCutoverState]:
        return self._states.state_of(project_id)

    def is_legacy_write_allowed(self, project_id: str) -> bool:
        """Only ``LEGACY_ACTIVE`` permits legacy writes; unknown blocks."""

        return self._states.state_of(project_id) == ProjectCutoverState.LEGACY_ACTIVE

    def _check_state(self, project_id: str, operation_id: str, layer: str) -> None:
        if self.is_legacy_write_allowed(project_id):
            return
        raise LegacyMutationBlocked(
            project_id=project_id,
            operation_id=operation_id,
            state=self._states.state_of(project_id),
            layer=layer,
        )

    # ------------------------------------------------------------------
    # Route layer
    # ------------------------------------------------------------------

    def check_route_mutation(self, project_id: str, operation_id: str) -> None:
        """Route-layer guard for one inventoried route operation.

        ``legacy_write`` operations are permitted only in ``LEGACY_ACTIVE``.
        ``read_only`` and ``excluded`` operations pass (they are not legacy
        mutations).  An operation absent from the inventory fails closed.
        """

        entry = self._inventory.route_entry(operation_id)
        if entry is None:
            raise MutationGuardConfigurationError(
                f"route operation {operation_id!r} is not inventoried; "
                "refusing to classify at runtime (inventory drift)"
            )
        if entry.classification == MutatorClassification.LEGACY_WRITE:
            self._check_state(project_id, operation_id, layer="route")

    # ------------------------------------------------------------------
    # Service layer
    # ------------------------------------------------------------------

    def check_service_mutation(self, project_id: str, operation_id: str) -> None:
        """Service-layer guard; same typed fail-closed error as the route layer.

        Both layers raise :class:`LegacyMutationBlocked` with the same stable
        code and state for the same project/operation, so a bypass of the
        route layer can never slip past the service layer.
        """

        entry = self._inventory.service_entry(operation_id)
        if entry is None:
            raise MutationGuardConfigurationError(
                f"service operation {operation_id!r} is not inventoried; "
                "refusing to classify at runtime (inventory drift)"
            )
        if entry.classification == MutatorClassification.LEGACY_WRITE:
            self._check_state(project_id, operation_id, layer="service")

    # ------------------------------------------------------------------
    # Read path (available in every state; exact payload/hash/identity)
    # ------------------------------------------------------------------

    def check_legacy_read(self, project_id: str) -> None:
        """Reads remain available in every cutover state.

        Validates project identity (fail closed on empty input) but never
        blocks on cutover state.
        """

        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

    def legacy_read(self, project_id: str, payload: Any) -> LegacyReadResult:
        """Read one legacy payload with exact preservation in all states.

        The returned result carries the exact supplied payload (deep-frozen
        copy — the caller's object is untouched and the result cannot be
        mutated), its canonical SHA-256 over the exact content, and the
        supplied project identity.  Identical results in every cutover state.
        """

        self.check_legacy_read(project_id)
        return LegacyReadResult(
            project_id=project_id.strip(),
            payload=_freeze_json(deepcopy(payload)),
            payload_sha256=exact_payload_sha256(payload),
        )

    # ------------------------------------------------------------------
    # Read-only inventory surface for tests / callers
    # ------------------------------------------------------------------

    @property
    def inventory(self) -> MutationInventory:
        return self._inventory


class RollbackHelper:
    """Rollback helper: disable the new command attachment, retain v3 events.

    Deliberately *incapable* of reversing cutover or reactivating legacy
    writes: it holds no reference to the registry's transition entry point
    and exposes no state-changing API other than the attachment flag.  Legacy
    fact writes remain governed by the guard (and therefore by the cutover
    state) at all times.
    """

    def __init__(self) -> None:
        self._attachment_enabled = True

    # -- new command attachment (the v3 router/service attachment) ---------

    def disable_new_command_attachment(self) -> None:
        """Disable the new (v3) command attachment for the process.

        Pure in-memory flag; it does NOT touch cutover state, does NOT delete
        or modify v3 events, and never re-enables legacy fact writes.
        """

        self._attachment_enabled = False

    def is_new_command_attachment_enabled(self) -> bool:
        return self._attachment_enabled

    # -- v3 events are retained untouched ----------------------------------

    def retain_v3_events(self, events: Sequence[Any]) -> tuple[Any, ...]:
        """Return an immutable, content-identical copy of the v3 events.

        The supplied sequence is never mutated; the returned copy is
        deep-frozen so downstream rollback logic cannot alter the retained
        v3 event history either.
        """

        return tuple(_freeze_json(deepcopy(event)) for event in events)
