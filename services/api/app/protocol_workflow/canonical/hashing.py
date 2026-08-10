"""Canonical hashing primitives for the Protocol v3 authority kernel.

These helpers compute deterministic, content-addressed identities for
StudyDefinition lineage, decision CAS replay, revisioned-aggregate binding and
fact-set comparison.  They are pure functions — no repository, filesystem,
network, clock or model access — so that the same logical input always produces
the same hash regardless of where or when the reducer runs.

Two distinct hash disciplines coexist here, and they must not be conflated:

* **Material hash** (:func:`material_sha256`) excludes *all* runtime metadata
  (revision counters, timestamps, lifecycle state, journey counters, display
  progress) so that unchanged authority content never appears stale.  Two
  StudyDefinitions with identical facts but different revisions share a material
  hash.  This is the :class:`ProtocolV3Model` discipline.

* **Revision hash** (:func:`canonical_revision_hash`) binds the *full*
  revisioned identity: stable aggregate id, numeric revision, predecessor
  revision hash, canonical lifecycle state and the material hash.  Same material
  at a different revision, or a different lifecycle state, or a different
  predecessor chain, yields a *different* revision hash.  This is the snapshot
  a decision CAS triple is captured against, so the triple is inherently
  revision-aware.

* **CAS identity** (:func:`decision_cas_identity`) hashes the raw
  ``(decision_record_id, snapshot_sha256, expected_state_revision)`` triple
  directly via :func:`canonical_json` + SHA-256.  It is *not* routed through the
  metadata-stripping material hash, so changing any single component — including
  the expected revision — produces a different identity.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Mapping, Optional, Sequence

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    JsonValue,
    ProtocolV3Model,
)

__all__ = [
    "canonical_json",
    "exact_payload_sha256",
    "material_sha256",
    "decision_cas_identity",
    "canonical_revision_hash",
    "study_definition_lineage_hash",
    "fact_set_sha256",
]


def canonical_json(value: Any) -> str:
    """Return a stable JSON encoding suitable for hashing.

    Keys are sorted recursively, ASCII is not escaped, and separators are
    compact.  Tuples and lists are treated identically.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, frozenset):
        return sorted(obj)
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, ProtocolV3Model):
        return obj.material_payload()
    raise TypeError(f"object of type {type(obj).__name__} is not JSON serialisable")


def exact_payload_sha256(value: Any) -> str:
    """SHA-256 over the exact canonical JSON payload.

    Unlike :func:`material_sha256`, this helper never strips keys that happen
    to share names with model metadata.  It is therefore the required hash for
    command payloads and domain fact maps, where ``revision`` or ``updated_at``
    may be legitimate fact keys rather than model metadata.
    """

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def material_sha256(value: Any) -> str:
    """SHA-256 over the canonical encoding of *value* after stripping
    material-metadata fields.

    Accepts raw JSON values, mappings, sequences, tuples of tuples, and
    :class:`ProtocolV3Model` instances.

    This is the *content* hash: it is deliberately invariant to revision number,
    predecessor hash, lifecycle state, timestamps and display progress so that
    unchanged authority content is never considered stale.
    """

    if isinstance(value, ProtocolV3Model):
        return value.material_sha256()
    stripped = _strip_metadata(value)
    payload = canonical_json(stripped).encode("utf-8")
    return sha256(payload).hexdigest()


def _strip_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_metadata(item)
            for key, item in value.items()
            if key not in ProtocolV3Model.material_metadata_fields
        }
    if isinstance(value, (Sequence,)) and not isinstance(value, (str, bytes)):
        return [_strip_metadata(item) for item in value]
    return value


def decision_cas_identity(
    decision_record_id: str,
    snapshot_sha256: str,
    expected_state_revision: int,
) -> str:
    """Deterministic CAS identity for decision replay.

    Two operations share the same CAS identity when and only when they replay
    the same decision against the same snapshot and the same expected revision.
    The triple is hashed **directly** via :func:`canonical_json` + SHA-256; it
    is never routed through the metadata-stripping :func:`material_sha256`,
    because ``expected_state_revision`` is a material-metadata field on the
    model and would be stripped, making the identity invariant to the revision.

    The returned value is a 64-character hex SHA-256.  It changes when any of
    the three components changes.
    """

    payload = canonical_json(
        {
            "decision_record_id": decision_record_id,
            "snapshot_sha256": snapshot_sha256,
            "expected_state_revision": expected_state_revision,
        }
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def canonical_revision_hash(
    aggregate_id: str,
    revision: int,
    previous_revision_sha256: Optional[str],
    canonical_state: CanonicalState,
    material_sha256_value: str,
) -> str:
    """Revision-aware identity hash for an immutable revisioned aggregate.

    Binds the *full* revisioned identity so that the same material content at a
    different revision, lifecycle state, or predecessor chain yields a different
    hash.  Fields:

    * ``aggregate_id`` — stable aggregate identity (e.g. ``study_definition_id``);
    * ``revision`` — monotonically increasing revision number;
    * ``previous_revision_sha256`` — predecessor revision hash (``None`` for
      revision 1);
    * ``canonical_state`` — lifecycle state (proposed/confirmed/frozen/...);
    * ``material_sha256_value`` — the material (content) hash of the aggregate.

    Only non-authoritative display/time metadata is excluded (there is none
    here by construction — every field is authoritative revision identity).

    This is the snapshot value a :class:`DecisionRecord` captures in its
    ``snapshot_sha256`` and that a fresh apply must match against the current
    aggregate.
    """

    payload = canonical_json(
        {
            "aggregate_id": aggregate_id,
            "revision": revision,
            "previous_revision_sha256": previous_revision_sha256,
            "canonical_state": _canonical_state_value(canonical_state),
            "material_sha256": material_sha256_value,
        }
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _canonical_state_value(state: CanonicalState) -> str:
    """Normalise a canonical state to its stable string value for hashing."""

    if isinstance(state, CanonicalState):
        return state.value
    return str(state)


def study_definition_lineage_hash(
    study_definition_id: str,
    normalized_seed_id: str,
    normalized_seed_sha256: str,
    facts: Mapping[str, JsonValue],
) -> str:
    """Material lineage hash for a StudyDefinition.

    The hash captures the authoritative *content* identity: the definition's
    stable ID, the normalised seed it derives from, and the full fact set.
    Revision number, previous-revision hash, timestamps and lifecycle state are
    deliberately excluded so that the same logical definition always yields the
    same lineage hash regardless of which revision it sits at.

    This complements :func:`canonical_revision_hash`: the lineage hash answers
    "is this the same logical study?" while the revision hash answers "is this
    the exact revision the decision was captured against?".
    """

    return exact_payload_sha256(
        {
            "study_definition_id": study_definition_id,
            "normalized_seed_id": normalized_seed_id,
            "normalized_seed_sha256": normalized_seed_sha256,
            "facts": dict(facts),
        }
    )


def fact_set_sha256(facts: Mapping[str, JsonValue]) -> str:
    """SHA-256 over a fact set, independent of dict insertion order."""

    return exact_payload_sha256({"facts": dict(facts)})
