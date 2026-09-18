"""Task 1.10 (Worker 03) — legacy read parity across cutover states.

Focused test for the read side of the mutation guard: reads must remain
available in *every* cutover state and preserve the exact supplied legacy
payload, its canonical hash, and the project identity.  All inputs are
synthetic in-memory payloads; no database, no source file, no runtime
singleton is touched.

Covered contracts:

* read availability — ``check_legacy_read`` and ``legacy_read`` succeed in
  LEGACY_ACTIVE, SHADOW_READ_ONLY, NEW_CANONICAL and with no cutover record;
* exact preservation — payload deep-equals the supplied object, the hash is
  the canonical SHA-256 of that exact content, project identity is preserved;
* immutability both ways — the caller's payload is untouched by the read, and
  the returned payload rejects every mutation API;
* hash determinism — same payload+project yields the same hash; content
  change yields a different hash;
* project isolation — two projects read independently, identical payloads
  hash identically, and one project's cutover transitions never affect the
  other's reads;
* fail-closed validation — an empty project id is rejected in every state.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from services.api.app.protocol_workflow.canonical.hashing import exact_payload_sha256
from services.api.app.protocol_workflow.legacy.cutover_state import (
    CutoverStateRegistry,
    ProjectCutoverState,
)
from services.api.app.protocol_workflow.legacy.mutation_guard import (
    LegacyReadResult,
    MutationGuard,
)


def _payload(index: int, project: str) -> dict[str, object]:
    return {
        "project_id": project,
        "index": index,
        "text": "公司语料示例载荷",
        "nested": {"a": [1, 2, {"b": "c"}]},
    }


def _registry_in_all_states(projects: list[str]) -> CutoverStateRegistry:
    registry = CutoverStateRegistry()
    for index, project in enumerate(projects):
        registry.apply(
            project,
            expected_state=None,
            new_state=ProjectCutoverState.LEGACY_ACTIVE,
            revision=f"init-{index}",
        )
    return registry


def _guard_with_state(state: ProjectCutoverState) -> MutationGuard:
    registry = _registry_in_all_states(["PRJ-1"])
    if state != ProjectCutoverState.LEGACY_ACTIVE:
        registry.apply(
            "PRJ-1",
            expected_state=ProjectCutoverState.LEGACY_ACTIVE,
            new_state=ProjectCutoverState.SHADOW_READ_ONLY,
            revision="to-shadow",
        )
        if state == ProjectCutoverState.NEW_CANONICAL:
            registry.apply(
                "PRJ-1",
                expected_state=ProjectCutoverState.SHADOW_READ_ONLY,
                new_state=ProjectCutoverState.NEW_CANONICAL,
                revision="to-canonical",
            )
    return MutationGuard(states=registry)


ALL_STATES = [
    ProjectCutoverState.LEGACY_ACTIVE,
    ProjectCutoverState.SHADOW_READ_ONLY,
    ProjectCutoverState.NEW_CANONICAL,
]


# ---------------------------------------------------------------------------
# Read availability in every state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ALL_STATES)
def test_reads_available_in_every_state(state: ProjectCutoverState) -> None:
    guard = _guard_with_state(state)
    guard.check_legacy_read("PRJ-1")
    result = guard.legacy_read("PRJ-1", _payload(1, "PRJ-1"))
    assert isinstance(result, LegacyReadResult)
    assert result.payload_sha256 == exact_payload_sha256(_payload(1, "PRJ-1"))


def test_reads_available_with_no_cutover_record() -> None:
    guard = MutationGuard(states=CutoverStateRegistry())
    guard.check_legacy_read("PRJ-UNKNOWN")
    result = guard.legacy_read("PRJ-UNKNOWN", _payload(2, "PRJ-UNKNOWN"))
    assert result.project_id == "PRJ-UNKNOWN"


def test_legacy_read_is_identical_across_all_states() -> None:
    payload = _payload(7, "PRJ-1")
    expected_hash = exact_payload_sha256(payload)
    results = [
        _guard_with_state(state).legacy_read("PRJ-1", payload)
        for state in ALL_STATES
    ]
    for result in results:
        assert result.project_id == "PRJ-1"
        assert result.payload_sha256 == expected_hash
        assert result.payload == payload
    # all five serialised forms identical (read parity is byte-stable)
    serialized = {result.model_dump(mode="json")["payload_sha256"] for result in results}
    assert serialized == {expected_hash}


# ---------------------------------------------------------------------------
# Exact preservation
# ---------------------------------------------------------------------------


def test_read_preserves_exact_payload_hash_and_identity() -> None:
    payload = _payload(11, "PRJ-1")
    guard = _guard_with_state(ProjectCutoverState.NEW_CANONICAL)
    result = guard.legacy_read("PRJ-1", payload)
    assert result.payload == payload
    assert result.payload_sha256 == exact_payload_sha256(payload)
    assert result.project_id == "PRJ-1"
    # hash is over the exact content, not a normalised projection
    assert result.payload_sha256 == exact_payload_sha256(result.payload)


def test_caller_payload_untouched_by_read() -> None:
    payload = _payload(3, "PRJ-1")
    snapshot = copy.deepcopy(payload)
    guard = _guard_with_state(ProjectCutoverState.SHADOW_READ_ONLY)
    result = guard.legacy_read("PRJ-1", payload)
    assert payload == snapshot
    assert result.payload == snapshot


def test_returned_payload_rejects_mutation() -> None:
    guard = _guard_with_state(ProjectCutoverState.LEGACY_ACTIVE)
    result = guard.legacy_read("PRJ-1", _payload(4, "PRJ-1"))
    with pytest.raises(TypeError):
        result.payload["index"] = 999  # type: ignore[index]
    with pytest.raises(TypeError):
        result.payload["nested"]["a"].append(42)  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        result.payload.update({"extra": True})  # type: ignore[attr-defined]


def test_hash_determinism_and_content_sensitivity() -> None:
    guard = _guard_with_state(ProjectCutoverState.NEW_CANONICAL)
    first = guard.legacy_read("PRJ-1", _payload(5, "PRJ-1"))
    again = guard.legacy_read("PRJ-1", _payload(5, "PRJ-1"))
    assert first.payload_sha256 == again.payload_sha256
    changed = _payload(5, "PRJ-1")
    changed["index"] = 6
    other = guard.legacy_read("PRJ-1", changed)
    assert other.payload_sha256 != first.payload_sha256


# ---------------------------------------------------------------------------
# Project isolation
# ---------------------------------------------------------------------------


def test_project_isolation_for_reads() -> None:
    registry = _registry_in_all_states(["PRJ-A", "PRJ-B"])
    guard = MutationGuard(states=registry)
    # identical *content* in two projects (payload carries no project field)
    content = {"index": 1, "text": "公司语料示例载荷"}
    a = guard.legacy_read("PRJ-A", content)
    b = guard.legacy_read("PRJ-B", content)
    # content-based hash is equal; identity is preserved per project
    assert a.payload_sha256 == b.payload_sha256
    assert a.project_id == "PRJ-A"
    assert b.project_id == "PRJ-B"
    assert a.payload == b.payload == content


def test_transitions_in_one_project_never_affect_another() -> None:
    registry = _registry_in_all_states(["PRJ-A", "PRJ-B"])
    registry.apply(
        "PRJ-A",
        expected_state=ProjectCutoverState.LEGACY_ACTIVE,
        new_state=ProjectCutoverState.SHADOW_READ_ONLY,
        revision="a-shadow",
    )
    # B is still fully writable (LEGACY_ACTIVE) while A is shadow read-only
    assert registry.state_of("PRJ-A") == ProjectCutoverState.SHADOW_READ_ONLY
    assert registry.state_of("PRJ-B") == ProjectCutoverState.LEGACY_ACTIVE
    guard = MutationGuard(states=registry)
    assert guard.is_legacy_write_allowed("PRJ-B") is True
    assert guard.is_legacy_write_allowed("PRJ-A") is False
    # reads identical in both projects regardless
    content = {"index": 9, "text": "公司语料示例载荷"}
    a = guard.legacy_read("PRJ-A", content)
    b = guard.legacy_read("PRJ-B", content)
    assert a.payload_sha256 == b.payload_sha256
    assert a.project_id == "PRJ-A"
    assert b.project_id == "PRJ-B"


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ALL_STATES)
def test_empty_project_id_rejected_in_every_state(state: ProjectCutoverState) -> None:
    guard = _guard_with_state(state)
    with pytest.raises(ValueError):
        guard.check_legacy_read("")
    with pytest.raises(ValueError):
        guard.check_legacy_read("   ")
    with pytest.raises(ValueError):
        guard.legacy_read("", _payload(1, "PRJ-1"))


def test_read_result_model_is_strict() -> None:
    with pytest.raises(ValidationError):
        LegacyReadResult(project_id="", payload={}, payload_sha256="not-a-hash")
    with pytest.raises(ValidationError):
        LegacyReadResult(  # unknown extra field
            project_id="PRJ-1",
            payload={},
            payload_sha256="0" * 64,
            extra="forbidden",
        )
