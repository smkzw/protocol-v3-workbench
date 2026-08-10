"""Stable event envelope, upcaster registry and replay verification primitives.

This module is the *event authority* helper layer for Protocol v3 (design
section 18).  It is deliberately decoupled from storage:

* :func:`compute_payload_sha256` / :func:`compute_event_sha256` are the only
  canonical hash functions for an event envelope.  They route through
  :mod:`app.protocol_workflow.canonical.hashing` so the event layer never
  introduces a second hash convention.

* :class:`EventEnvelopeBuilder` is a pure factory that fills in the computed
  hashes and the predecessor chain for a :class:`DomainEvent`.  It never opens
  a repository or clock; the caller supplies ``emitted_at`` and the prior
  ``event_sha256``.

* :class:`UpcasterRegistry` is a closed registry of deterministic schema
  migrations keyed by ``(payload_schema_version, upcaster_id)``.  An unknown
  schema version or a missing/non-deterministic upcaster fails closed into a
  :class:`QuarantineReplayResult`; replay never guesses.

* :class:`ReplayOutcome` / :class:`SuccessfulReplayResult` /
  :class:`QuarantineReplayResult` are the typed tri-state returned by the
  replay engine in :mod:`app.protocol_workflow.events.store`.

The module imports **only** the frozen contracts and the pure canonical
hashing helpers.  It has no repository, storage, network, clock or model
dependency, mirroring the discipline of :mod:`app.protocol_workflow.canonical`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from copy import deepcopy
from threading import RLock
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    DomainEvent,
    JsonValue,
)

from app.protocol_workflow.canonical.hashing import (
    canonical_json,
    exact_payload_sha256,
)

__all__ = [
    "EventEnvelopeError",
    "EventEnvelopeIntegrityError",
    "EventEnvelopeBuilder",
    "EventTypeRegistry",
    "NondeterministicUpcasterError",
    "PayloadHashMismatchError",
    "RegistryFrozenError",
    "QuarantineReason",
    "QuarantineReplayResult",
    "ReplayOutcome",
    "SuccessfulReplayResult",
    "UnknownEventTypeError",
    "UnknownSchemaVersionError",
    "UnknownUpcasterError",
    "UpcasterRegistry",
    "UpcasterSignature",
    "compute_event_sha256",
    "compute_payload_sha256",
    "verify_event_integrity",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------
#
# These mirror the canonical-reducer discipline: they carry the identity
# context the application service needs for audit and UI translation, but they
# never import the user-facing error registry.  Keeping them local prevents the
# event layer from becoming coupled to UI copy.


class EventEnvelopeError(RuntimeError):
    """Base class for event-envelope construction and verification failures."""


class EventEnvelopeIntegrityError(EventEnvelopeError):
    """Raised when an event envelope fails hash or chain verification."""


class PayloadHashMismatchError(EventEnvelopeIntegrityError):
    """Raised when the stored ``payload_sha256`` does not match the payload."""


class UnknownSchemaVersionError(EventEnvelopeError):
    """Raised when an event carries an unknown ``payload_schema_version``."""


class UnknownUpcasterError(EventEnvelopeError):
    """Raised when an event references an unregistered ``upcaster_id``."""


class NondeterministicUpcasterError(EventEnvelopeError):
    """Raised when a registered upcaster is proven non-deterministic at runtime.

    Registration-time source fingerprinting cannot prove runtime determinism.
    This error is raised when :meth:`UpcasterRegistry.verify_determinism`
    executes the migration against isolated copies and observes divergent
    canonical output, or when :meth:`UpcasterRegistry.migrate` detects the
    same condition at replay time.
    """


class UnknownEventTypeError(EventEnvelopeError):
    """Raised when an event carries an ``event_type`` absent from the closed
    event-type registry.  Replay of unregistered event types is never
    permitted; there is no permissive default."""


class RegistryFrozenError(EventEnvelopeError):
    """Raised when a replay registry is mutated after it was frozen.

    An :class:`EventReplayEngine` freezes both registries at construction so a
    long-running process cannot silently change the event types or migration
    implementations accepted by an already-created engine.
    """


# ---------------------------------------------------------------------------
# Canonical event hashing
# ---------------------------------------------------------------------------

#: Fields excluded from the *material* identity of an event.  These are the
#: envelope-level metadata fields that change between revisions even when the
#: business payload is identical.  The material hash is used only for dedup;
#: the authoritative event identity is :func:`compute_event_sha256`.
_EVENT_MATERIAL_EXCLUDE: FrozenSet[str] = frozenset(
    {
        "schema_version",
        "event_sha256",
        "payload_sha256",
        "previous_event_sha256",
        "emitted_at",
    }
)


def compute_payload_sha256(payload: Mapping[str, JsonValue]) -> str:
    """Return the canonical SHA-256 over the event *payload*.

    This is the hash stored in :attr:`DomainEvent.payload_sha256`.  It uses
    :func:`exact_payload_sha256` so that legitimate payload keys that share
    names with model metadata (e.g. ``revision``) are never stripped.
    """

    return exact_payload_sha256(dict(payload))


def _canonical_event_fields(event: DomainEvent) -> Dict[str, JsonValue]:
    """Return the canonical, hash-stable field dict for *event*.

    Enum values are normalised to their ``.value`` so that an event serialised
    from a stored representation and a freshly built event produce the same
    ``event_sha256``.
    """

    actor_type = event.actor_type
    actor_value = actor_type.value if isinstance(actor_type, Enum) else actor_type

    return {
        "domain_event_id": event.domain_event_id,
        "stream_id": event.stream_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload_schema_version": event.payload_schema_version,
        "upcaster_id": event.upcaster_id,
        "actor_type": actor_value,
        "actor_id": event.actor_id,
        "action": event.action,
        "reason": event.reason,
        "payload": event.payload,
        "payload_sha256": event.payload_sha256,
        "migrated_payload_sha256": event.migrated_payload_sha256,
        "previous_event_sha256": event.previous_event_sha256,
        "emitted_at": _normalise_datetime(event.emitted_at),
    }


def _normalise_datetime(value: datetime) -> str:
    """Return a stable ISO-8601 representation for hashing.

    All Protocol v3 timestamps are timezone-aware.  We emit a fixed-precision
    UTC ISO string so that two equivalent instants produce the same hash even
    if their source ``datetime`` objects differ in timezone offset.
    """

    if value.tzinfo is None:
        raise EventEnvelopeError("event emitted_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def compute_event_sha256(event: DomainEvent) -> str:
    """Return the canonical SHA-256 over the full event envelope.

    The envelope hash binds every authoritative field: identity, chain
    position (``sequence`` + ``previous_event_sha256``), schema/upcaster
    identity, actor/action/reason, payload, payload hash, and emission time.
    It excludes only the envelope's own ``event_sha256`` and the model-level
    ``schema_version`` (which is invariant for the contract).
    """

    fields = _canonical_event_fields(event)
    return sha256(canonical_json(fields).encode("utf-8")).hexdigest()


def verify_event_integrity(event: DomainEvent) -> None:
    """Verify that *event*'s stored hashes match its recomputed canonical hashes.

    Raises :class:`PayloadHashMismatchError` when ``payload_sha256`` does not
    match the recomputed payload hash, and :class:`EventEnvelopeIntegrityError`
    when ``event_sha256`` does not match the recomputed envelope hash.
    """

    expected_payload = compute_payload_sha256(event.payload)
    if event.payload_sha256 != expected_payload:
        raise PayloadHashMismatchError(
            f"payload_sha256 mismatch for event {event.domain_event_id}: "
            f"stored={event.payload_sha256} recomputed={expected_payload}"
        )
    expected_event = compute_event_sha256(event)
    if event.event_sha256 != expected_event:
        raise EventEnvelopeIntegrityError(
            f"event_sha256 mismatch for event {event.domain_event_id}: "
            f"stored={event.event_sha256} recomputed={expected_event}"
        )


# ---------------------------------------------------------------------------
# Event envelope builder
# ---------------------------------------------------------------------------


class EventEnvelopeBuilder:
    """Pure factory that fills computed hashes and chain position.

    The builder is stateless and safe to share.  It never consults a clock;
    the caller supplies ``emitted_at``.  It never consults a repository; the
    caller supplies the prior ``previous_event_sha256`` (``None`` for the
    first event in a stream).
    """

    __slots__ = ()

    def build(
        self,
        *,
        domain_event_id: str,
        stream_id: str,
        sequence: int,
        event_type: str,
        payload_schema_version: str,
        upcaster_id: str,
        actor_type: ActorType,
        actor_id: str,
        action: str,
        reason: str,
        payload: Mapping[str, JsonValue],
        migrated_payload_sha256: Optional[str] = None,
        emitted_at: datetime,
        previous_event_sha256: Optional[str] = None,
    ) -> DomainEvent:
        """Construct a :class:`DomainEvent` with canonical hashes filled in.

        The first event in a stream has ``sequence == 1`` and
        ``previous_event_sha256 is None``; subsequent events require both.
        The model's own ``validate_event_chain_identity`` validator enforces
        this invariant at construction.
        """

        payload_sha = compute_payload_sha256(payload)
        # Build once to compute the envelope hash, then construct the final
        # event.  We reuse _canonical_event_fields so that the hash is
        # identical to what verify_event_integrity will recompute.
        from packages.contracts.workbench_contracts.protocol_v3 import (
            DomainEvent as _DE,
        )

        event = _DE(
            domain_event_id=domain_event_id,
            stream_id=stream_id,
            sequence=sequence,
            event_type=event_type,
            payload_schema_version=payload_schema_version,
            upcaster_id=upcaster_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            reason=reason,
            payload=dict(payload),
            payload_sha256=payload_sha,
            migrated_payload_sha256=migrated_payload_sha256,
            previous_event_sha256=previous_event_sha256,
            event_sha256="0" * 64,  # placeholder, recomputed below
            emitted_at=emitted_at,
        )
        event_sha = compute_event_sha256(event)
        return event.model_copy(update={"event_sha256": event_sha})

    def continue_chain(
        self,
        head_sha256: str,
        head_sequence: int,
        *,
        domain_event_id: str,
        stream_id: str,
        event_type: str,
        payload_schema_version: str,
        upcaster_id: str,
        actor_type: ActorType,
        actor_id: str,
        action: str,
        reason: str,
        payload: Mapping[str, JsonValue],
        migrated_payload_sha256: Optional[str] = None,
        emitted_at: datetime,
    ) -> DomainEvent:
        """Build the next event in a stream given the current head.

        ``head_sha256`` is the ``event_sha256`` of the current last event;
        ``head_sequence`` is its ``sequence``.  The new event receives
        ``sequence = head_sequence + 1`` and the proper predecessor link.
        """

        return self.build(
            domain_event_id=domain_event_id,
            stream_id=stream_id,
            sequence=head_sequence + 1,
            event_type=event_type,
            payload_schema_version=payload_schema_version,
            upcaster_id=upcaster_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            reason=reason,
            payload=payload,
            migrated_payload_sha256=migrated_payload_sha256,
            emitted_at=emitted_at,
            previous_event_sha256=head_sha256,
        )


# ---------------------------------------------------------------------------
# Upcaster registry
# ---------------------------------------------------------------------------

#: A deterministic upcaster callable.  It receives the raw stored payload dict
#: and the source schema version, and returns the migrated payload dict.  It
#: must be pure: no I/O, no clock, no randomness.  The registry fingerprints
#: the function's source to detect non-determinism at registration time.
UpcasterFn = Callable[[Mapping[str, JsonValue]], Dict[str, JsonValue]]


@dataclass(frozen=True)
class UpcasterSignature:
    """Identity fingerprint of a registered upcaster.

    ``source_schema_version`` is the schema the upcaster reads; the target is
    implicitly the current canonical schema.  ``upcaster_id`` is the stable
    human-readable id stored on every :class:`DomainEvent`.
    """

    source_schema_version: str
    upcaster_id: str


def _fingerprint_callable(fn: UpcasterFn) -> str:
    """Return a SHA-256 fingerprint of a callable's source code.

    This is a *registration-time* guard against accidentally registering a
    non-deterministic closure (e.g. one that captures a clock or random
    source).  It is not a runtime check; it merely ensures the upcaster is a
    named, inspectable function.
    """

    import inspect

    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        # Builtins, lambdas from REPL, or dynamically generated code: fall
        # back to the qualified name + module.  These are still deterministic
        # per process, but less inspectable; the guard still catches the
        # common case of an inline lambda over mutable state.
        source = f"{getattr(fn, '__module__', '<unknown>')}:{getattr(fn, '__qualname__', '<unknown>')}"
    return sha256(source.encode("utf-8")).hexdigest()


class UpcasterRegistry:
    """Closed registry of deterministic event-schema upcasters.

    An event is replayable only when its ``(payload_schema_version,
    upcaster_id)`` pair is registered here *and* the upcaster is a pure
    function.  An unknown schema version or upcaster id fails closed; replay
    never guesses.

    The registry is immutable after construction: upcasters are registered at
    module import time (or in a dedicated composition root) and never
    mutated.  This mirrors the frozen-skill/version-lock discipline of design
    section 18.
    """

    __slots__ = (
        "_upcasters",
        "_fingerprints",
        "_current_schema_version",
        "_frozen",
        "_observed_output_hashes",
        "_lock",
    )

    def __init__(
        self,
        *,
        current_schema_version: str = "mw_protocol_v3_event_v1",
    ) -> None:
        self._upcasters: Dict[UpcasterSignature, UpcasterFn] = {}
        self._fingerprints: Dict[UpcasterSignature, str] = {}
        self._current_schema_version = current_schema_version
        self._frozen = False
        self._observed_output_hashes: Dict[Tuple[str, UpcasterSignature], str] = {}
        self._lock = RLock()

    @property
    def current_schema_version(self) -> str:
        """The canonical target schema version all upcasters migrate toward."""

        return self._current_schema_version

    def register(
        self,
        signature: UpcasterSignature,
        fn: UpcasterFn,
    ) -> None:
        """Register *fn* as the upcaster for *signature*.

        Raises :class:`UnknownSchemaVersionError` if the signature's source
        schema equals the current canonical schema (no migration needed) and
        :class:`ValueError` on duplicate registration of the same signature
        with a different function.
        """

        if self._frozen:
            raise RegistryFrozenError("upcaster registry is frozen")
        if signature.source_schema_version == self._current_schema_version:
            # An event already at the current schema uses the implicit
            # identity upcaster; an explicit one is unnecessary and signals a
            # misunderstanding.  We still allow the well-known noop id.
            if signature.upcaster_id != "noop:v1":
                raise UnknownSchemaVersionError(
                    f"schema version {signature.source_schema_version!r} is already "
                    f"the current canonical version; no upcaster needed"
                )
        if signature in self._upcasters:
            existing_fp = self._fingerprints[signature]
            new_fp = _fingerprint_callable(fn)
            if existing_fp != new_fp:
                raise ValueError(
                    f"upcaster {signature!r} is already registered with a "
                    f"different implementation"
                )
            return  # idempotent re-registration of the same function
        self._upcasters[signature] = fn
        self._fingerprints[signature] = _fingerprint_callable(fn)

    def freeze(self) -> None:
        """Freeze the registry against further registration.

        Idempotent.  Replay engines call this during construction so their
        accepted migration universe cannot change after first use.
        """

        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def register_noop(self, schema_version: str) -> None:
        """Register the canonical identity upcaster for *schema_version*.

        The noop upcaster returns its input unchanged.  It is the required
        registration for events that are already at the current canonical
        schema version.
        """

        self.register(
            UpcasterSignature(schema_version, "noop:v1"),
            _noop_upcaster,
        )

    def is_registered(self, signature: UpcasterSignature) -> bool:
        return signature in self._upcasters

    def migrate(
        self,
        event: DomainEvent,
    ) -> Tuple[Dict[str, JsonValue], Optional[UpcasterSignature]]:
        """Migrate *event*'s payload to the current canonical schema.

        Returns ``(migrated_payload, applied_signature)``.  When the event is
        already at the current schema, the payload is returned unchanged and
        ``applied_signature`` is ``None`` (no migration applied).

        Raises :class:`UnknownSchemaVersionError` when the schema version is
        not registered, and :class:`UnknownUpcasterError` when the upcaster
        id is not registered for that schema version.

        Raises :class:`NondeterministicUpcasterError` when the upcaster
        returns a different canonical payload on two isolated invocations
        with the same input.  Registration-time source fingerprinting cannot
        prove runtime determinism; this runtime check is the authoritative
        guard against nondeterministic migrations.
        """

        if event.payload_schema_version == self._current_schema_version:
            # At current schema: the event must carry the canonical noop
            # upcaster id.  Any other id at the current schema is a
            # misconfiguration; quarantine it.
            if event.upcaster_id != "noop:v1":
                raise UnknownUpcasterError(
                    f"event {event.domain_event_id} is at current schema "
                    f"{self._current_schema_version!r} but carries non-noop "
                    f"upcaster {event.upcaster_id!r}"
                )
            return dict(event.payload), None
        signature = UpcasterSignature(
            event.payload_schema_version,
            event.upcaster_id,
        )
        if signature not in self._upcasters:
            # Distinguish unknown schema from unknown upcaster for clearer
            # quarantine diagnostics.
            known_schemas = {s.source_schema_version for s in self._upcasters}
            if event.payload_schema_version not in known_schemas:
                raise UnknownSchemaVersionError(
                    f"event {event.domain_event_id} has unknown "
                    f"payload_schema_version {event.payload_schema_version!r}"
                )
            raise UnknownUpcasterError(
                f"event {event.domain_event_id} has unknown upcaster "
                f"{event.upcaster_id!r} for schema "
                f"{event.payload_schema_version!r}"
            )
        fn = self._upcasters[signature]
        # Runtime determinism guard: compare two isolated invocations and bind
        # the result to immutable evidence carried by the event envelope.
        # Registry-local memory alone cannot survive a fresh composition or
        # process restart, so every legacy event must persist the canonical
        # migrated-payload hash as part of its authoritative event identity.
        with self._lock:
            copy_a = deepcopy(event.payload)
            copy_b = deepcopy(event.payload)
            result_a = fn(copy_a)
            result_b = fn(copy_b)
            hash_a = exact_payload_sha256(result_a)
            hash_b = exact_payload_sha256(result_b)
            if hash_a != hash_b:
                raise NondeterministicUpcasterError(
                    f"upcaster {signature!r} for event "
                    f"{event.domain_event_id} produced divergent canonical "
                    f"output on two isolated invocations with the same input"
                )
            expected_hash = event.migrated_payload_sha256
            if expected_hash is None:
                raise NondeterministicUpcasterError(
                    f"legacy event {event.domain_event_id} has no immutable "
                    "migrated_payload_sha256 evidence"
                )
            if hash_a != expected_hash:
                raise NondeterministicUpcasterError(
                    f"upcaster {signature!r} for immutable event "
                    f"{event.domain_event_id} produced migrated payload "
                    f"sha256={hash_a}, expected={expected_hash}"
                )
            identity = (event.event_sha256, signature)
            prior_hash = self._observed_output_hashes.get(identity)
            if prior_hash is not None and prior_hash != hash_a:
                raise NondeterministicUpcasterError(
                    f"upcaster {signature!r} for immutable event "
                    f"{event.domain_event_id} changed migrated payload identity: "
                    f"first={prior_hash} replay={hash_a}"
                )
            self._observed_output_hashes[identity] = hash_a
            return dict(result_a), signature

    def verify_determinism(
        self,
        signature: UpcasterSignature,
        sample_payload: Mapping[str, JsonValue],
    ) -> None:
        """Prove that the upcaster registered under *signature* is
        deterministic by executing it against isolated deep copies of
        *sample_payload* and comparing exact canonical output.

        This is a *practical* verification, not a formal proof: it runs the
        migration a bounded number of times (currently twice) on independent
        deep copies and asserts the canonical JSON SHA-256 of each result is
        identical.  It also rejects upcasters that mutate their input: after
        each invocation the original sample must be unchanged.

        Raises :class:`UnknownUpcasterError` if *signature* is not
        registered, and :class:`NondeterministicUpcasterError` if the
        upcaster is proven non-deterministic or mutates its input.
        """

        if signature not in self._upcasters:
            raise UnknownUpcasterError(f"upcaster {signature!r} is not registered")
        fn = self._upcasters[signature]
        original_hash = exact_payload_sha256(sample_payload)
        copy_a = deepcopy(sample_payload)
        copy_b = deepcopy(sample_payload)
        result_a = fn(copy_a)
        result_b = fn(copy_b)
        hash_a = exact_payload_sha256(result_a)
        hash_b = exact_payload_sha256(result_b)
        if hash_a != hash_b:
            raise NondeterministicUpcasterError(
                f"upcaster {signature!r} produced divergent canonical "
                f"output: first={hash_a} second={hash_b}"
            )
        # Reject upcasters that mutate their input alias: compare the
        # deep-copied inputs before and after invocation.
        if (
            exact_payload_sha256(copy_a) != original_hash
            or exact_payload_sha256(copy_b) != original_hash
        ):
            raise NondeterministicUpcasterError(
                f"upcaster {signature!r} mutated its input payload; "
                f"upcasters must not accept or return mutable aliases"
            )


def _noop_upcaster(payload: Mapping[str, JsonValue]) -> Dict[str, JsonValue]:
    """Canonical identity upcaster — returns a shallow copy of the payload."""

    return dict(payload)


# ---------------------------------------------------------------------------
# Event-type registry (closed allow-list)
# ---------------------------------------------------------------------------


class EventTypeRegistry:
    """Closed, immutable allow-list of permitted event types.

    Replay of an event whose ``event_type`` is not registered here is never
    permitted; there is no permissive default.  This mirrors the design-section-18
    discipline that DomainEvent identity (``event_type`` /
    ``payload_schema_version`` / ``upcaster_id``) must be explicitly known
    before replay, and unknown event versions quarantine fail-closed.

    The registry is immutable after construction.  Event types are registered
    at module import time or in a dedicated composition root and never
    mutated.
    """

    __slots__ = ("_types", "_frozen")

    def __init__(self, event_types: Optional[Sequence[str]] = None) -> None:
        self._types: FrozenSet[str] = frozenset(event_types or ())
        self._frozen = False

    def register(self, event_type: str) -> None:
        """Register *event_type* as a permitted replay event type.

        Raises :class:`ValueError` on duplicate registration.
        """

        if self._frozen:
            raise RegistryFrozenError("event-type registry is frozen")
        if event_type in self._types:
            raise ValueError(f"event type {event_type!r} is already registered")
        self._types = self._types | frozenset({event_type})

    def freeze(self) -> None:
        """Freeze the allow-list against further registration (idempotent)."""

        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def is_registered(self, event_type: str) -> bool:
        """Return ``True`` iff *event_type* is in the allow-list."""

        return event_type in self._types

    def assert_registered(self, event_type: str) -> None:
        """Raise :class:`UnknownEventTypeError` if *event_type* is not
        registered."""

        if event_type not in self._types:
            raise UnknownEventTypeError(
                f"event type {event_type!r} is not registered; replay "
                f"of unregistered event types is not permitted"
            )

    @property
    def event_types(self) -> FrozenSet[str]:
        """The frozen set of all registered event types."""

        return self._types


# ---------------------------------------------------------------------------
# Replay outcome tri-state
# ---------------------------------------------------------------------------


class QuarantineReason(str, Enum):
    """Why an event stream was quarantined during replay.

    The values are stable strings suitable for embedding in a typed error code
    of the form ``MW-PRO-<GATE>-<OBJECT>-<CAUSE>``.
    """

    UNKNOWN_SCHEMA_VERSION = "unknown_schema_version"
    UNKNOWN_UPCASTER = "unknown_upcaster"
    EVENT_HASH_MISMATCH = "event_hash_mismatch"
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"
    BROKEN_CHAIN = "broken_chain"
    CHECKPOINT_EVENT_MISMATCH = "checkpoint_event_mismatch"
    REPLAYER_ERROR = "replayer_error"
    NONDETERMINISTIC_UPCASTER = "nondeterministic_upcaster"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    STREAM_ID_MISMATCH = "stream_id_mismatch"
    REVISION_HASH_MISMATCH = "revision_hash_mismatch"


@dataclass(frozen=True)
class SuccessfulReplayResult:
    """Outcome of a successful deterministic event replay.

    ``final_state`` is the canonical aggregate reached by replaying the event
    stream through the registered reducer.  ``canonical_revision_sha256`` is
    the revision hash of the final state — it MUST match the hash originally
    projected for the same event sequence, proving deterministic
    reconstructability.  ``events_replayed`` is the count of events applied.
    ``skipped_completed_effects`` lists the logical keys of side effects that
    were already recorded in the inbox and therefore skipped during resume
    (design section 18: resume from event stream, skip completed effects).
    """

    final_state: Any
    canonical_revision_sha256: str
    events_replayed: int
    skipped_completed_effects: Tuple[str, ...] = ()
    migrations_applied: Tuple[Optional[UpcasterSignature], ...] = ()


@dataclass(frozen=True)
class QuarantineReplayResult:
    """Outcome of a failed replay that must be quarantined (fail closed).

    ``reason`` is the stable quarantine cause.  ``failing_event_id`` is the id
    of the event at which replay stopped (``None`` when the failure is not
    attributable to a single event, e.g. a checkpoint/event mismatch).  ``detail``
    is a human-readable diagnostic string for audit.
    """

    reason: QuarantineReason
    failing_event_id: Optional[str]
    detail: str
    events_replayed_before_failure: int = 0
    partial_state: Optional[Any] = None
    expected_logical_keys: Tuple[str, ...] = ()


class ReplayOutcome:
    """Type-erased container for either a successful or quarantined replay.

    The application service inspects :attr:`is_quarantined` and then narrows
    to :attr:`success` or :attr:`quarantine`.  This tri-state pattern mirrors
    the ``_ReplayResult`` discipline of the canonical reducers.
    """

    __slots__ = ("_success", "_quarantine")

    def __init__(
        self,
        *,
        success: Optional[SuccessfulReplayResult] = None,
        quarantine: Optional[QuarantineReplayResult] = None,
    ) -> None:
        if (success is None) == (quarantine is None):
            raise ValueError("exactly one of success/quarantine is required")
        self._success = success
        self._quarantine = quarantine

    @property
    def is_quarantined(self) -> bool:
        return self._quarantine is not None

    @property
    def success(self) -> SuccessfulReplayResult:
        if self._success is None:
            raise RuntimeError("outcome is quarantined, not successful")
        return self._success

    @property
    def quarantine(self) -> QuarantineReplayResult:
        if self._quarantine is None:
            raise RuntimeError("outcome is successful, not quarantined")
        return self._quarantine
