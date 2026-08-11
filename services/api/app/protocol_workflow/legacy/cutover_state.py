"""Per-project v2→v3 cutover state machine (Task 1.10, Worker 03).

The cutover ladder is exactly three forward-only states per project::

    LEGACY_ACTIVE -> SHADOW_READ_ONLY -> NEW_CANONICAL

This module owns *state*, not persistence: it is a pure in-memory registry
with no database, no feature-flag wiring, no runtime singleton and no
automatic transition of any kind.  It exists so the migration guard
(:mod:`app.protocol_workflow.legacy.mutation_guard`) can decide whether a
legacy mutation is permitted for a project, and so the frozen-plan
requirements "state revisions use CAS/idempotency" and "reject skip, reverse,
unknown project reuse and conflicting replay" are enforceable and testable.

Transition semantics (all deterministic, fail closed):

* **Initialisation.** A project with no record may only be created at
  ``LEGACY_ACTIVE`` with ``expected_state=None``.  Any other first transition
  for an unknown project is rejected with ``unknown_project_reuse`` (a
  migration must never start mid-ladder, and a retired/terminal project must
  never be re-created).
* **CAS.** ``expected_state`` must equal the recorded current state (or be
  ``None`` for a fresh project), else ``cas_mismatch``.
* **Forward-only.** ``new_state`` must be exactly the next ladder rank.
  A jump of more than one rank is ``skip``; a move to an earlier rank is
  ``reverse``; re-asserting the current state is ``same_state`` (or
  ``already_terminal`` at ``NEW_CANONICAL``).
* **Revision idempotency / conflicting replay.** Each applied transition is
  recorded under the caller-supplied ``revision``.  Re-applying the exact
  ``(revision, expected_state, new_state)`` triple returns
  ``idempotent_replay`` with the current state and never double-applies.
  Reusing a revision with *different* transition content is
  ``conflicting_replay``.  Stale CAS attempts (state already advanced) are
  ``cas_mismatch``, never silently replayed.
* **Project isolation.** Every project has an independent record; transitions
  in one project can never affect another.

Every rejection is a typed :class:`CutoverRejected` carrying a stable
:class:`CutoverRejectionCode`, the project id and a stable message, so the
guard and tests can assert on the code rather than prose.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CUTOVER_LADDER",
    "CutoverRejected",
    "CutoverRejectionCode",
    "CutoverStateRegistry",
    "CutoverTransitionResult",
    "CutoverTransitionStatus",
    "ProjectCutoverState",
    "state_rank",
]

CUTOVER_LADDER: tuple[str, str, str] = (
    "legacy_active",
    "shadow_read_only",
    "new_canonical",
)


class ProjectCutoverState(str, Enum):
    """Exactly the three per-project cutover states, in ladder order."""

    LEGACY_ACTIVE = "legacy_active"
    SHADOW_READ_ONLY = "shadow_read_only"
    NEW_CANONICAL = "new_canonical"


_STATE_RANK: dict[ProjectCutoverState, int] = {
    ProjectCutoverState.LEGACY_ACTIVE: 0,
    ProjectCutoverState.SHADOW_READ_ONLY: 1,
    ProjectCutoverState.NEW_CANONICAL: 2,
}


def state_rank(state: Optional[ProjectCutoverState]) -> int:
    """Ladder rank; ``None`` (no record) ranks below ``LEGACY_ACTIVE``."""

    if state is None:
        return -1
    return _STATE_RANK[state]


def _coerce_state(value: Any, *, label: str) -> ProjectCutoverState:
    """Accept the enum or its canonical string value; reject anything else."""

    if isinstance(value, ProjectCutoverState):
        return value
    if isinstance(value, str):
        text = value.strip()
        for member in ProjectCutoverState:
            if member.value == text:
                return member
    raise ValueError(f"{label} must be a ProjectCutoverState, got {value!r}")


class CutoverRejectionCode(str, Enum):
    """Closed, stable rejection vocabulary for cutover transitions."""

    UNKNOWN_PROJECT_REUSE = "unknown_project_reuse"
    CAS_MISMATCH = "cas_mismatch"
    SKIP = "skip"
    REVERSE = "reverse"
    SAME_STATE = "same_state"
    ALREADY_TERMINAL = "already_terminal"
    CONFLICTING_REPLAY = "conflicting_replay"


class CutoverRejected(Exception):
    """Typed, stable rejection of one cutover transition attempt."""

    def __init__(
        self,
        *,
        code: CutoverRejectionCode,
        project_id: str,
        expected_state: Optional[ProjectCutoverState],
        new_state: Optional[ProjectCutoverState],
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.project_id = project_id
        self.expected_state = expected_state
        self.new_state = new_state
        self.message = message

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "project_id": self.project_id,
            "expected_state": (
                self.expected_state.value if self.expected_state is not None else None
            ),
            "new_state": self.new_state.value if self.new_state is not None else None,
            "message": self.message,
        }


class CutoverTransitionStatus(str, Enum):
    APPLIED = "applied"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class CutoverTransitionResult(BaseModel):
    """Frozen outcome of one accepted (or idempotently replayed) transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    state: ProjectCutoverState
    status: CutoverTransitionStatus
    revision: str = Field(min_length=1)
    transition_number: int = Field(ge=1)


class _AppliedTransition(BaseModel):
    """One recorded transition inside a project record (immutable)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_number: int = Field(ge=1)
    revision: str = Field(min_length=1)
    expected_state: Optional[ProjectCutoverState]
    new_state: ProjectCutoverState


class _ProjectRecord(BaseModel):
    """Independent per-project cutover record (immutable, ordered history)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    state: ProjectCutoverState
    transition_number: int = Field(ge=1)
    history: tuple[_AppliedTransition, ...] = ()


class CutoverStateRegistry:
    """In-memory per-project cutover state with CAS + revision idempotency.

    No persistence: instances are process-local and must be wired explicitly
    by the caller (this task performs no feature-flag wiring).
    """

    def __init__(self) -> None:
        self._records: dict[str, _ProjectRecord] = {}

    # ------------------------------------------------------------------
    # Read surface
    # ------------------------------------------------------------------

    def state_of(self, project_id: str) -> Optional[ProjectCutoverState]:
        """Current state for a project; ``None`` when no record exists."""

        record = self._records.get(project_id)
        return None if record is None else record.state

    def is_read_only(self, project_id: str) -> bool:
        """Fail-closed read-only test: only ``LEGACY_ACTIVE`` is writable.

        A project with no cutover record is treated as read-only (unknown
        state never silently grants legacy write access).
        """

        return self.state_of(project_id) != ProjectCutoverState.LEGACY_ACTIVE

    def transition_number_of(self, project_id: str) -> int:
        record = self._records.get(project_id)
        return 0 if record is None else record.transition_number

    def revision_of(self, project_id: str) -> Optional[str]:
        """Last applied transition revision for a project (replay key)."""

        record = self._records.get(project_id)
        if record is None or not record.history:
            return None
        return record.history[-1].revision

    def history_of(
        self, project_id: str
    ) -> tuple[tuple[int, str, Optional[ProjectCutoverState], ProjectCutoverState], ...]:
        """Ordered applied-transition snapshot:
        ``(transition_number, revision, expected_state, new_state)``.
        """

        record = self._records.get(project_id)
        if record is None:
            return ()
        return tuple(
            (item.transition_number, item.revision, item.expected_state, item.new_state)
            for item in record.history
        )

    def project_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))

    # ------------------------------------------------------------------
    # Transition surface (the only mutation entry point)
    # ------------------------------------------------------------------

    def apply(
        self,
        project_id: str,
        *,
        expected_state: Optional[ProjectCutoverState],
        new_state: ProjectCutoverState,
        revision: str,
    ) -> CutoverTransitionResult:
        """Apply one forward cutover transition with CAS + revision checks.

        Raises:
            :class:`CutoverRejected` with a stable
            :class:`CutoverRejectionCode` on every violation; ``ValueError``
            for malformed arguments (invalid state value, empty revision).
        """

        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        project_id = project_id.strip()
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("revision must be a non-empty string")
        revision = revision.strip()

        expected = (
            None
            if expected_state is None
            else _coerce_state(expected_state, label="expected_state")
        )
        new = _coerce_state(new_state, label="new_state")

        record = self._records.get(project_id)

        # -- exact replay short-circuit (idempotency before CAS) -------------
        if record is not None:
            for applied in record.history:
                if (
                    applied.revision == revision
                    and applied.expected_state == expected
                    and applied.new_state == new
                ):
                    return CutoverTransitionResult(
                        project_id=project_id,
                        state=record.state,
                        status=CutoverTransitionStatus.IDEMPOTENT_REPLAY,
                        revision=revision,
                        transition_number=record.transition_number,
                    )

        if record is None:
            # -- fresh project: may only be created at the ladder bottom -----
            if new != ProjectCutoverState.LEGACY_ACTIVE:
                raise CutoverRejected(
                    code=CutoverRejectionCode.UNKNOWN_PROJECT_REUSE,
                    project_id=project_id,
                    expected_state=expected,
                    new_state=new,
                    message=(
                        "unknown project may only enter the cutover ladder at "
                        "LEGACY_ACTIVE; starting at "
                        f"{new.value!r} would reuse an unknown project mid-ladder"
                    ),
                )
            if expected is not None:
                raise CutoverRejected(
                    code=CutoverRejectionCode.CAS_MISMATCH,
                    project_id=project_id,
                    expected_state=expected,
                    new_state=new,
                    message=(
                        "project has no cutover record; expected_state must be "
                        "None for initialisation"
                    ),
                )
            self._records[project_id] = _ProjectRecord(
                project_id=project_id,
                state=ProjectCutoverState.LEGACY_ACTIVE,
                transition_number=1,
                history=(
                    _AppliedTransition(
                        transition_number=1,
                        revision=revision,
                        expected_state=None,
                        new_state=ProjectCutoverState.LEGACY_ACTIVE,
                    ),
                ),
            )
            return CutoverTransitionResult(
                project_id=project_id,
                state=ProjectCutoverState.LEGACY_ACTIVE,
                status=CutoverTransitionStatus.APPLIED,
                revision=revision,
                transition_number=1,
            )

        # -- existing record --------------------------------------------------
        assert record is not None

        # revision already used with different content -> conflicting replay
        for applied in record.history:
            if applied.revision == revision:
                raise CutoverRejected(
                    code=CutoverRejectionCode.CONFLICTING_REPLAY,
                    project_id=project_id,
                    expected_state=expected,
                    new_state=new,
                    message=(
                        f"revision {revision!r} was already used for project "
                        f"{project_id!r} with different transition content"
                    ),
                )

        # CAS: expected must equal the current recorded state
        if expected != record.state:
            raise CutoverRejected(
                code=CutoverRejectionCode.CAS_MISMATCH,
                project_id=project_id,
                expected_state=expected,
                new_state=new,
                message=(
                    f"expected_state {expected!r} does not match current state "
                    f"{record.state.value!r} for project {project_id!r}"
                ),
            )

        current_rank = state_rank(record.state)
        new_rank = state_rank(new)
        if new_rank == current_rank:
            if record.state == ProjectCutoverState.NEW_CANONICAL:
                raise CutoverRejected(
                    code=CutoverRejectionCode.ALREADY_TERMINAL,
                    project_id=project_id,
                    expected_state=expected,
                    new_state=new,
                    message=(
                        f"project {project_id!r} already reached NEW_CANONICAL; "
                        "cutover is terminal and never restarts"
                    ),
                )
            raise CutoverRejected(
                code=CutoverRejectionCode.SAME_STATE,
                project_id=project_id,
                expected_state=expected,
                new_state=new,
                message=(
                    f"new_state {new.value!r} equals the current state; a "
                    "cutover transition must move exactly one rank forward"
                ),
            )
        if new_rank == current_rank + 1:
            applied = _AppliedTransition(
                transition_number=record.transition_number + 1,
                revision=revision,
                expected_state=record.state,
                new_state=new,
            )
            self._records[project_id] = _ProjectRecord(
                project_id=project_id,
                state=new,
                transition_number=record.transition_number + 1,
                history=record.history + (applied,),
            )
            return CutoverTransitionResult(
                project_id=project_id,
                state=new,
                status=CutoverTransitionStatus.APPLIED,
                revision=revision,
                transition_number=applied.transition_number,
            )
        if new_rank > current_rank + 1:
            raise CutoverRejected(
                code=CutoverRejectionCode.SKIP,
                project_id=project_id,
                expected_state=expected,
                new_state=new,
                message=(
                    f"transition {record.state.value!r} -> {new.value!r} skips "
                    "a ladder rank; only one forward step per transition"
                ),
            )
        raise CutoverRejected(
            code=CutoverRejectionCode.REVERSE,
            project_id=project_id,
            expected_state=expected,
            new_state=new,
            message=(
                f"transition {record.state.value!r} -> {new.value!r} moves "
                "backward; cutover is strictly forward-only"
            ),
        )

    def __len__(self) -> int:
        return len(self._records)
