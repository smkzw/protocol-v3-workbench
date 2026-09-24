# Contiguous method excerpt, de-indented from GitHub commit
# 455b37ee4530628736bd6b37b622796f13e9498f
# services/api/app/medical_writing_authoring_journey.py
# Read window 5580-5860; only dependencies below are supplied by the test harness.
from __future__ import annotations

def _acquire_generation_reservation(
    self,
    *,
    project_id: str,
    expected_revision: int,
    operation: str,
    force: bool,
    enricher_timeout_seconds: float,
) -> _GenerationReservationAcquisition:
    """Acquire the durable fail-closed generation reservation.

    Runs BEFORE any enrichment call.  A second logical call with the
    same key (concurrent duplicate worker or retried request) waits for
    the winner and replays its outcome; it never dispatches another
    model call.  A timed-out or interrupted call is preserved as an
    unknown outcome and is never redispatched automatically: the key
    fails closed until an explicit ``force`` request starts a new
    logical call (recorded via a fresh logical call id).
    """
    wait_bound = (
        max(30.0, enricher_timeout_seconds + 15.0) + 5.0
        if self._generation_reservation_wait_seconds is None
        else self._generation_reservation_wait_seconds
    )
    deadline = time.monotonic() + wait_bound
    while True:
        row = self._read_generation_reservation(
            project_id, expected_revision, operation
        )
        if row is None:
            logical_call_id = self._try_insert_generation_reservation(
                project_id, expected_revision, operation
            )
            if logical_call_id is not None:
                return _GenerationReservationAcquisition(
                    logical_call_id=logical_call_id
                )
            continue  # lost the insert race; re-read the winner's row
        status = str(row["status"])
        if status == "failed" and int(row["transport_attempt_count"] or 0) > 0:
            # Defense-in-depth: a reservation that ever reached the
            # transport layer can never be retryable as a known failure
            # (the upstream model may have completed and only the local
            # result was lost).  Treat it exactly like unknown_outcome
            # so a non-force caller fails closed.
            status = "unknown_outcome"
        if status == "completed":
            # The generation for this key already happened: replay the
            # winner's outcome instead of dispatching again.  Verify the
            # completion event revision so the caller can explain a
            # refresh (the current journey may be a later revision).
            return self._replay_completed_reservation(
                project_id, expected_revision, operation, row
            )
        if status == "failed":
            # Known failure (no event persisted): a fresh logical call
            # may take over the key.
            logical_call_id = self._supersede_generation_reservation(
                project_id,
                expected_revision,
                operation,
                previous_call_id=str(row["logical_call_id"]),
                note=f"supersedes failed call {row['logical_call_id']}",
            )
            if logical_call_id is not None:
                return _GenerationReservationAcquisition(
                    logical_call_id=logical_call_id
                )
            continue
        if status == "unknown_outcome":
            if not force:
                raise MedicalWritingAuthoringJourneyConflictError(
                    "prefill generation for this revision is in an "
                    "unknown-outcome state from a prior call "
                    f"({row['logical_call_id']}); the state is preserved "
                    "and will not be redispatched automatically; retry "
                    "with force=True to start a new logical call"
                )
            logical_call_id = self._supersede_generation_reservation(
                project_id,
                expected_revision,
                operation,
                previous_call_id=str(row["logical_call_id"]),
                note=(
                    "supersedes unknown-outcome call "
                    f"{row['logical_call_id']}"
                ),
            )
            if logical_call_id is not None:
                return _GenerationReservationAcquisition(
                    logical_call_id=logical_call_id
                )
            continue
        # status == "in_flight": wait for a terminal state within the
        # bounded window (the winner may still be enriching).
        if force:
            # Worker_03 corrective: force must never interrupt a live
            # call.  Fail fast with an accurate message naming the
            # in-flight owner instead of waiting out the bound and then
            # raising a misleading "retry with force=True" error.
            raise MedicalWritingAuthoringJourneyConflictError(
                "prefill generation is already in flight for this "
                f"revision (logical call {row['logical_call_id']}); "
                "force cannot interrupt the live call; wait for the "
                "owner to complete or, after the wait bound marks the "
                "call unknown-outcome, retry with force=True"
            )
        if time.monotonic() >= deadline:
            # Worker_03 corrective: the deadline flip is bound to the
            # OBSERVED logical call id with a rowcount check so a stale
            # waiter can never flip a reservation that a newer owner
            # (or a completed event) superseded between read and
            # update.  The owner's own completion UPDATE is bound to
            # its logical call id and may still complete the same row.
            observed_call_id = str(row["logical_call_id"])
            now_iso = datetime.now(timezone.utc).isoformat()
            history = json.loads(str(row["attempt_history"] or "[]"))
            history.append(
                {
                    "logical_call_id": observed_call_id,
                    "transport_attempt_count": int(
                        row["transport_attempt_count"] or 0
                    ),
                    "status": "in_flight",
                    "failure_note": row["failure_note"],
                    "updated_at": row["updated_at"],
                }
            )
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE "
                    "medical_writing_authoring_journey_generation_reservations "
                    "SET status = 'unknown_outcome', failure_note = ?, "
                    "attempt_history = ?, updated_at = ? "
                    "WHERE project_id = ? AND expected_revision = ? "
                    "AND operation = ? AND logical_call_id = ? "
                    "AND status = 'in_flight'",
                    (
                        _WAITER_DEADLINE_FLIP_NOTE,
                        json.dumps(history, ensure_ascii=False),
                        now_iso,
                        project_id,
                        expected_revision,
                        operation,
                        observed_call_id,
                    ),
                )
                connection.commit()
            row = self._read_generation_reservation(
                project_id, expected_revision, operation
            )
            if row is not None and str(row["status"]) == "completed":
                return self._replay_completed_reservation(
                    project_id, expected_revision, operation, row
                )
            # When the flip was not applied, the observed call was
            # completed or superseded between our read and the update:
            # never flip a reservation we did not observe.  Either way
            # this caller's wait is exhausted and the observed call
            # outcome is unknown to it, so fail closed.
            raise MedicalWritingAuthoringJourneyConflictError(
                "prefill generation reservation is still in flight "
                "beyond the wait bound; the prior call outcome is "
                "unknown and preserved; it will not be redispatched "
                "automatically; retry with force=True to start a new "
                "logical call"
            )
        time.sleep(min(0.1, max(0.02, wait_bound / 20.0)))
