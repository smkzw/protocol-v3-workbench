"""Task 1.10 — read-only v2→v3 migration inventory & quarantine primitives.

Worker 01 focused test: proves the legacy inventory (migration_inventory.py)
and quarantine (quarantine.py) typed primitives with *synthetic immutable
inputs only*.  No database, no runtime singleton, no source file is read or
written; every input is constructed in memory and proven unchanged after the
inventory pass.

Covered contracts:

* deep source immutability — caller payloads untouched, stored payloads and
  every container reject mutation, hashes are of the original content;
* cross-project separation — identical identity in two projects never
  conflicts and hashes never bleed;
* permutation determinism — ordering/hash independent of input order,
  including conflict outcomes;
* duplicate semantics — identical duplicates are deduplicated explicitly,
  divergent payloads under one identity fail closed into quarantine (every
  occurrence), payload-internal revision contradictions fail closed;
* complete seven-family denominator — the closed family set is exactly the
  seven declared families and unsupported families quarantine explicitly;
* quarantine contract — original source hash + immutable locator + stable
  Chinese-safe reason metadata, no fabricated hashes for payload-less rows;
* synthetic 3,878-row corpus — unmappable rows remain explicit (never
  dropped, never fabricated) with full accounting.
"""

from __future__ import annotations

import copy
from datetime import datetime
from enum import Enum
import json
import random

import pytest
from pydantic import ValidationError

from services.api.app.protocol_workflow.canonical.hashing import (
    canonical_json,
    exact_payload_sha256,
)
from services.api.app.protocol_workflow.legacy import (
    FAMILY_PUBLIC_LABEL_ZH,
    INVENTORY_SCHEMA_VERSION,
    LEGACY_SOURCE_FAMILIES,
    ImmutableLocator,
    InventorySnapshot,
    LegacySourceFamily,
    LegacySourceRecord,
    QuarantineReasonKind,
    QuarantineRecord,
    SourceRevisionToken,
    build_inventory,
    quarantine_reason,
)

SEVEN_FAMILIES = {
    "study_definition",
    "journey_stage_draft",
    "working_copy_snapshot",
    "corpus_evidence",
    "decision_approval",
    "protocol_document",
    "artifact_lineage",
}

FAMILY_VALUES = {member.value for member in LegacySourceFamily}

Sha256_HEX_RE = "0123456789abcdef"


def _row(
    project_id: str,
    family: str,
    source_type: str,
    source_id: str,
    revision_token: str,
    payload: object,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "source_family": family,
        "source_type": source_type,
        "source_id": source_id,
        "revision_token": revision_token,
        "payload": payload,
    }


def _valid_row(index: int, project: str = "PRJ-1") -> dict[str, object]:
    return _row(
        project_id=project,
        family="corpus_evidence",
        source_type="corpus",
        source_id=f"row:{index:04d}",
        revision_token=f"v{index % 7 + 1}",
        payload={"index": index, "text": "公司语料示例", "revision": f"v{index % 7 + 1}"},
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in Sha256_HEX_RE for char in value)
    )


def _assert_accounting(snapshot: InventorySnapshot) -> None:
    assert (
        snapshot.source_count
        == snapshot.record_count
        + snapshot.quarantined_count
        + snapshot.deduplicated_count
    ), "accounting invariant broken"
    assert len(snapshot.records) == snapshot.record_count
    assert len(snapshot.quarantine_records) == snapshot.quarantined_count


# ---------------------------------------------------------------------------
# Deep source immutability
# ---------------------------------------------------------------------------


class TestDeepSourceImmutability:
    def test_inventory_never_mutates_caller_payloads(self) -> None:
        rows = [_valid_row(1), _valid_row(2), _row("PRJ-1", "billing", "x", "b:1", "v1", {"a": [1, {"b": 2}]})]
        original = copy.deepcopy(rows)

        snapshot = build_inventory(rows)

        assert rows == original, "caller-supplied input was mutated"
        assert snapshot.record_count == 2
        assert snapshot.quarantined_count == 1

        # Stored payloads deep-equal the originals (byte/value stable).
        stored = {json.dumps(record.payload, ensure_ascii=False, sort_keys=True) for record in snapshot.records}
        expected = {
            json.dumps(row["payload"], ensure_ascii=False, sort_keys=True) for row in original[:2]
        }
        assert stored == expected

    def test_stored_payload_rejects_deep_mutation(self) -> None:
        rows = [
            _row(
                "PRJ-1",
                "study_definition",
                "definition",
                "def:1",
                "r1",
                {"title": "P1", "meta": [1, {"k": "v"}], "revision": "r1"},
            )
        ]
        snapshot = build_inventory(rows)
        record = snapshot.records[0]
        assert isinstance(record.payload, dict)

        with pytest.raises(TypeError):
            record.payload["title"] = "X"
        with pytest.raises(TypeError):
            record.payload["meta"].append(9)
        with pytest.raises(TypeError):
            record.payload["meta"][1]["k"] = "y"
        with pytest.raises(TypeError):
            record.payload.update({"extra": 1})
        with pytest.raises(TypeError):
            del record.payload["title"]
        # Contents survived every attempt.
        assert record.payload["title"] == "P1"
        assert record.payload["meta"] == [1, {"k": "v"}]

    def test_payload_sha256_covers_original_content(self) -> None:
        rows = [_valid_row(7)]
        original_payload = copy.deepcopy(rows[0]["payload"])

        snapshot = build_inventory(rows)
        record = snapshot.records[0]

        assert record.payload_sha256 == exact_payload_sha256(original_payload)
        # And the stored (frozen) payload hashes identically.
        assert record.payload_sha256 == exact_payload_sha256(record.payload)

    def test_model_attributes_and_containers_are_frozen(self) -> None:
        rows = [_valid_row(3), _valid_row(4)]
        snapshot = build_inventory(rows)
        record = snapshot.records[0]

        with pytest.raises((TypeError, ValidationError)):
            setattr(record, "project_id", "OTHER")
        with pytest.raises((TypeError, ValidationError)):
            setattr(record, "payload", {"hijack": True})
        with pytest.raises((TypeError, ValidationError)):
            setattr(snapshot, "source_count", 99)
        with pytest.raises((TypeError, ValidationError)):
            snapshot.records[0] = record
        with pytest.raises((TypeError, ValidationError)):
            setattr(snapshot.records[0].locator, "source_id", "other")

        assert isinstance(snapshot.records, tuple)
        assert isinstance(snapshot.quarantine_records, tuple)
        assert snapshot.source_count == 2

    def test_locator_binds_identity_and_payload_deterministically(self) -> None:
        rows_a = [_row("PRJ-1", "protocol_document", "document", "doc:1", "r2", {"title": "T", "revision": "r2"})]
        snapshot_a = build_inventory(rows_a)
        locator_a = snapshot_a.records[0].locator
        assert isinstance(locator_a, ImmutableLocator)
        assert _is_sha256(locator_a.locator_sha256)
        assert locator_a.payload_sha256 == snapshot_a.records[0].payload_sha256

        # Same identity + payload => same locator hash.
        snapshot_b = build_inventory([_row("PRJ-1", "protocol_document", "document", "doc:1", "r2", {"revision": "r2", "title": "T"})])
        assert snapshot_b.records[0].locator.locator_sha256 == locator_a.locator_sha256

        # Different payload => different locator hash.
        snapshot_c = build_inventory([_row("PRJ-1", "protocol_document", "document", "doc:1", "r2", {"title": "U", "revision": "r2"})])
        assert snapshot_c.records[0].locator.locator_sha256 != locator_a.locator_sha256

        # Locator hash is exactly the canonical hash of its own payload.
        expected = exact_payload_sha256(
            {
                "project_id": locator_a.project_id,
                "source_family": locator_a.source_family.value,
                "source_type": locator_a.source_type,
                "source_id": locator_a.source_id,
                "revision_token": locator_a.revision_token,
                "payload_sha256": locator_a.payload_sha256,
            }
        )
        assert locator_a.locator_sha256 == expected

    def test_revision_token_normalizes_and_is_immutable(self) -> None:
        token = SourceRevisionToken(value="  r17 ")
        assert token.value == "r17"
        with pytest.raises((TypeError, ValidationError)):
            token.value = "r18"
        with pytest.raises(ValidationError):
            SourceRevisionToken(value="   ")


# ---------------------------------------------------------------------------
# Permutation determinism and ordering
# ---------------------------------------------------------------------------


class TestPermutationDeterminism:
    def _mixed_corpus(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for index in range(40):
            rows.append(_valid_row(index))
        # duplicates, conflicts, incomplete, unsupported, ambiguous
        rows.append(_row("PRJ-1", "corpus_evidence", "corpus", "row:1000", "v1", {"n": 1, "revision": "v1"}))
        rows.append(_row("PRJ-1", "corpus_evidence", "corpus", "row:1000", "v1", {"n": 1, "revision": "v1"}))  # exact dup
        rows.append(_row("PRJ-1", "corpus_evidence", "corpus", "row:1001", "v1", {"n": 2, "revision": "v1"}))
        rows.append(_row("PRJ-1", "corpus_evidence", "corpus", "row:1001", "v1", {"n": 3, "revision": "v1"}))  # conflict
        rows.append(_row("PRJ-2", "billing_ledger", "invoice", "b:1", "v1", {"amount": 5}))  # unsupported family
        rows.append(_row("PRJ-2", "corpus_evidence", "corpus", "row:2000", "", {"n": 6}))  # empty revision
        rows.append(_row("PRJ-2", "corpus_evidence", "corpus", "row:2001", "v2", {"n": 7, "revision": "v9"}))  # internal mismatch
        return rows

    def test_permuted_inputs_yield_identical_snapshot(self) -> None:
        corpus = self._mixed_corpus()
        rng = random.Random(20260812)
        results = []
        for seed in (1, 2, 3):
            permuted = list(corpus)
            rng.shuffle(permuted)
            snapshot = build_inventory(permuted)
            results.append(snapshot)

        for other in results[1:]:
            assert results[0].records == other.records
            assert results[0].quarantine_records == other.quarantine_records
            assert results[0].source_count == other.source_count
            assert results[0].record_count == other.record_count
            assert results[0].quarantined_count == other.quarantined_count
            assert results[0].deduplicated_count == other.deduplicated_count
            assert dict(results[0].family_counts) == dict(other.family_counts)
            assert dict(results[0].counts_by_reason) == dict(other.counts_by_reason)
            assert results[0].inventory_sha256 == other.inventory_sha256

        _assert_accounting(results[0])
        # Exact duplicate: 1 dedup; conflict pair: both quarantined; plus the
        # unsupported family, empty revision and internal-revision rows.
        assert results[0].deduplicated_count == 1
        assert results[0].quarantined_count == 5

    def test_repeated_build_is_stable(self) -> None:
        corpus = self._mixed_corpus()
        first = build_inventory(corpus)
        second = build_inventory(corpus)
        assert first.inventory_sha256 == second.inventory_sha256
        assert first == second

    def test_payload_key_order_does_not_change_hash(self) -> None:
        payload_a = {"z": 1, "a": [1, 2], "m": {"y": 2, "x": 1}}
        payload_b = {"m": {"x": 1, "y": 2}, "a": [1, 2], "z": 1}
        assert payload_a == payload_b
        snap_a = build_inventory([_row("P", "corpus_evidence", "corpus", "id:1", "v1", payload_a)])
        snap_b = build_inventory([_row("P", "corpus_evidence", "corpus", "id:1", "v1", payload_b)])
        assert snap_a.records[0].payload_sha256 == snap_b.records[0].payload_sha256
        assert snap_a.inventory_sha256 == snap_b.inventory_sha256

    def test_identity_whitespace_is_normalized_not_hashed(self) -> None:
        plain = _row("PRJ-1", "corpus_evidence", "corpus", "id:1", "v1", {"n": 1})
        spaced = _row("  PRJ-1 ", " corpus_evidence ", " corpus ", " id:1 ", " v1 ", {"n": 1})
        snap_plain = build_inventory([plain])
        snap_spaced = build_inventory([spaced])
        assert snap_plain.records[0].identity_key == snap_spaced.records[0].identity_key
        assert snap_plain.inventory_sha256 == snap_spaced.inventory_sha256

    def test_records_sorted_by_canonical_identity(self) -> None:
        rows = [
            _row("PRJ-2", "corpus_evidence", "corpus", "row:2", "v1", {"n": 2}),
            _row("PRJ-1", "study_definition", "definition", "def:1", "r1", {"t": 1, "revision": "r1"}),
            _row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1}),
        ]
        snapshot = build_inventory(rows)
        keys = [record.identity_key for record in snapshot.records]
        assert keys == sorted(keys)
        assert keys[0] == ("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1")

    def test_conflict_outcome_is_order_independent(self) -> None:
        a = _row("PRJ-1", "corpus_evidence", "corpus", "row:9", "v1", {"n": 1, "revision": "v1"})
        b = _row("PRJ-1", "corpus_evidence", "corpus", "row:9", "v1", {"n": 2, "revision": "v1"})
        forward = build_inventory([a, b])
        backward = build_inventory([b, a])
        assert forward.records == backward.records == ()
        assert forward.quarantine_records == backward.quarantine_records
        assert forward.quarantined_count == 2
        assert forward.inventory_sha256 == backward.inventory_sha256
        hashes = {q.payload_sha256 for q in forward.quarantine_records}
        assert hashes == {exact_payload_sha256(a["payload"]), exact_payload_sha256(b["payload"])}

    def test_empty_input_yields_empty_snapshot(self) -> None:
        snapshot = build_inventory([])
        assert snapshot.source_count == 0
        assert snapshot.records == ()
        assert snapshot.quarantine_records == ()
        assert _is_sha256(snapshot.inventory_sha256)
        _assert_accounting(snapshot)


# ---------------------------------------------------------------------------
# Complete seven-family denominator
# ---------------------------------------------------------------------------


class TestSevenFamilyDenominator:
    def test_exactly_seven_families_declared(self) -> None:
        assert FAMILY_VALUES == SEVEN_FAMILIES
        assert len(list(LegacySourceFamily)) == 7
        assert LEGACY_SOURCE_FAMILIES == SEVEN_FAMILIES
        # Every family has a stable Chinese public label.
        for value in SEVEN_FAMILIES:
            assert FAMILY_PUBLIC_LABEL_ZH[value]

    def test_all_seven_families_inventoried(self) -> None:
        rows = [
            _row("PRJ-1", "study_definition", "definition", f"def:{i}", "r1", {"i": i, "revision": "r1"})
            for i, family in enumerate(sorted(SEVEN_FAMILIES))
        ]
        for index, family in enumerate(sorted(SEVEN_FAMILIES)):
            rows[index]["source_family"] = family
        snapshot = build_inventory(rows)
        assert snapshot.record_count == 7
        assert snapshot.quarantined_count == 0
        assert set(snapshot.family_counts) == SEVEN_FAMILIES
        assert all(count == 1 for count in snapshot.family_counts.values())
        _assert_accounting(snapshot)

    def test_unsupported_family_quarantines_explicitly(self) -> None:
        snapshot = build_inventory(
            [_row("PRJ-1", "billing_ledger", "invoice", "b:1", "v1", {"amount": 1})]
        )
        assert snapshot.record_count == 0
        assert snapshot.quarantined_count == 1
        quarantined = snapshot.quarantine_records[0]
        assert quarantined.reason_kinds == (QuarantineReasonKind.UNSUPPORTED_FAMILY,)
        assert snapshot.counts_by_reason == {"unsupported_family": 1}
        assert "billing_ledger" in quarantined.detail_zh
        # Original payload hash is still preserved for the unsupported row.
        assert quarantined.payload_sha256 == exact_payload_sha256({"amount": 1})

    def test_casefold_family_value_is_normalized(self) -> None:
        snapshot = build_inventory(
            [_row("PRJ-1", "Study_Definition", "definition", "def:1", "r1", {"t": 1, "revision": "r1"})]
        )
        assert snapshot.record_count == 1
        assert snapshot.records[0].source_family is LegacySourceFamily.STUDY_DEFINITION
        assert snapshot.records[0].identity_key[1] == "study_definition"

    def test_plausible_but_undeclared_family_is_never_guessed(self) -> None:
        # "study" is not one of the seven canonical values and must not be
        # silently mapped onto study_definition.
        snapshot = build_inventory(
            [_row("PRJ-1", "study", "definition", "def:1", "r1", {"t": 1})]
        )
        assert snapshot.record_count == 0
        assert snapshot.quarantine_records[0].reason_kinds == (QuarantineReasonKind.UNSUPPORTED_FAMILY,)


# ---------------------------------------------------------------------------
# Duplicate identity semantics (fail closed)
# ---------------------------------------------------------------------------


class TestDuplicateAndConflictSemantics:
    def test_exact_duplicate_is_deduplicated_not_dropped(self) -> None:
        row = _row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1, "revision": "v1"})
        snapshot = build_inventory([row, copy.deepcopy(row)])
        assert snapshot.record_count == 1
        assert snapshot.deduplicated_count == 1
        assert snapshot.quarantined_count == 0
        assert snapshot.source_count == 2
        _assert_accounting(snapshot)
        # The single inventoried record is content-identical to the input.
        assert snapshot.records[0].payload_sha256 == exact_payload_sha256(row["payload"])

    def test_divergent_payload_conflict_quarantines_every_occurrence(self) -> None:
        a = _row("PRJ-1", "corpus_evidence", "corpus", "row:2", "v1", {"n": 1, "revision": "v1"})
        b = _row("PRJ-1", "corpus_evidence", "corpus", "row:2", "v1", {"n": 2, "revision": "v1"})
        snapshot = build_inventory([a, b])
        assert snapshot.record_count == 0
        assert snapshot.deduplicated_count == 0
        assert snapshot.quarantined_count == 2
        assert all(
            q.reason_kinds == (QuarantineReasonKind.DUPLICATE_CONFLICT,)
            for q in snapshot.quarantine_records
        )
        assert snapshot.counts_by_reason == {"duplicate_conflict": 2}
        hashes = {q.payload_sha256 for q in snapshot.quarantine_records}
        assert hashes == {exact_payload_sha256(a["payload"]), exact_payload_sha256(b["payload"])}
        _assert_accounting(snapshot)

    def test_conflict_plus_duplicate_mix_fails_closed_on_all(self) -> None:
        # Two identical + one divergent: content-based resolution quarantines
        # every occurrence, regardless of which rows were repeated.
        same = _row("PRJ-1", "corpus_evidence", "corpus", "row:3", "v1", {"n": 1, "revision": "v1"})
        other = _row("PRJ-1", "corpus_evidence", "corpus", "row:3", "v1", {"n": 2, "revision": "v1"})
        snapshot = build_inventory([same, copy.deepcopy(same), other])
        assert snapshot.record_count == 0
        assert snapshot.deduplicated_count == 0
        assert snapshot.quarantined_count == 3
        _assert_accounting(snapshot)

    def test_payload_internal_revision_contradiction_quarantines(self) -> None:
        snapshot = build_inventory(
            [_row("PRJ-1", "corpus_evidence", "corpus", "row:4", "v1", {"n": 1, "revision": "v9"})]
        )
        assert snapshot.record_count == 0
        quarantined = snapshot.quarantine_records[0]
        assert quarantined.reason_kinds == (QuarantineReasonKind.AMBIGUOUS_IDENTITY,)
        assert "v9" in quarantined.detail_zh and "v1" in quarantined.detail_zh
        assert quarantined.payload_sha256 == exact_payload_sha256({"n": 1, "revision": "v9"})

    def test_matching_internal_revision_is_inventoried(self) -> None:
        snapshot = build_inventory(
            [_row("PRJ-1", "corpus_evidence", "corpus", "row:5", "v1", {"n": 1, "revision": "v1"})]
        )
        assert snapshot.record_count == 1
        assert snapshot.quarantined_count == 0

    def test_revision_change_is_separate_lineage_not_conflict(self) -> None:
        rows = [
            _row("PRJ-1", "protocol_document", "document", "doc:1", "v1", {"title": "A", "revision": "v1"}),
            _row("PRJ-1", "protocol_document", "document", "doc:1", "v2", {"title": "B", "revision": "v2"}),
        ]
        snapshot = build_inventory(rows)
        assert snapshot.record_count == 2
        assert snapshot.quarantined_count == 0
        revisions = [record.revision_token.value for record in snapshot.records]
        assert revisions == ["v1", "v2"]


# ---------------------------------------------------------------------------
# Quarantine record contract
# ---------------------------------------------------------------------------


class TestQuarantineContract:
    def test_quarantine_carries_original_hash_locator_and_identity(self) -> None:
        payload = {"text": "无法映射的旧数据", "meta": [1, 2]}
        snapshot = build_inventory(
            [_row("PRJ-9", "billing_ledger", "invoice", "b:1", "v3", payload)]
        )
        quarantined = snapshot.quarantine_records[0]
        assert isinstance(quarantined, QuarantineRecord)
        assert quarantined.payload_sha256 == exact_payload_sha256(payload)
        assert _is_sha256(quarantined.locator_sha256)
        assert _is_sha256(quarantined.quarantine_id)
        assert quarantined.project_id == "PRJ-9"
        assert quarantined.source_family == "unknown"
        assert quarantined.source_type == "invoice"
        assert quarantined.source_id == "b:1"
        assert quarantined.revision_token == "v3"
        assert quarantined.detail_zh
        # Locator hash mirrors ImmutableLocator semantics.
        assert quarantined.locator_sha256 == exact_payload_sha256(
            {
                "project_id": "PRJ-9",
                "source_family": "unknown",
                "source_type": "invoice",
                "source_id": "b:1",
                "revision_token": "v3",
                "payload_sha256": quarantined.payload_sha256,
            }
        )

    def test_missing_required_field_quarantines_incomplete(self) -> None:
        row = _row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1})
        del row["revision_token"]
        snapshot = build_inventory([row])
        quarantined = snapshot.quarantine_records[0]
        assert quarantined.reason_kinds == (QuarantineReasonKind.INCOMPLETE_RECORD,)
        assert "revision_token" in quarantined.detail_zh
        # The payload hash of the incomplete row is still recorded.
        assert quarantined.payload_sha256 == exact_payload_sha256({"n": 1})

    def test_payload_less_row_has_no_fabricated_hash(self) -> None:
        row = _row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1})
        del row["payload"]
        snapshot = build_inventory([row])
        quarantined = snapshot.quarantine_records[0]
        assert quarantined.reason_kinds == (QuarantineReasonKind.INCOMPLETE_RECORD,)
        assert quarantined.payload_sha256 is None
        assert quarantined.locator_sha256 is None

    def test_non_json_payload_quarantines_without_fake_hash(self) -> None:
        snapshot = build_inventory(
            [_row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"d": datetime(2026, 1, 1)})]
        )
        quarantined = snapshot.quarantine_records[0]
        assert quarantined.reason_kinds == (QuarantineReasonKind.INCOMPLETE_RECORD,)
        assert quarantined.payload_sha256 is None
        assert "载荷" in quarantined.detail_zh

    def test_non_mapping_item_quarantines(self) -> None:
        snapshot = build_inventory([42, "nonsense"])  # type: ignore[list-item]
        assert snapshot.record_count == 0
        assert snapshot.quarantined_count == 2
        assert all(
            q.reason_kinds == (QuarantineReasonKind.INCOMPLETE_RECORD,)
            for q in snapshot.quarantine_records
        )
        assert all(q.payload_sha256 is None for q in snapshot.quarantine_records)

    def test_reason_metadata_is_stable_and_chinese_safe(self) -> None:
        for kind in QuarantineReasonKind:
            reason = quarantine_reason(kind)
            assert reason is quarantine_reason(kind)  # canonical object identity
            assert reason.kind is kind
            assert reason.label_zh
            assert reason.label_en
            assert reason.code.startswith("MW-LEGACY-Q-")
            assert all(char.isascii() for char in reason.code)

        # Chinese text round-trips unescaped in canonical JSON (Chinese-safe).
        snapshot = build_inventory(
            [_row("PRJ-1", "billing_ledger", "x", "b:1", "v1", {"a": 1})]
        )
        encoded = canonical_json(snapshot.quarantine_records[0].canonical_payload())
        reason_zh = snapshot.quarantine_records[0].reasons[0].label_zh
        assert reason_zh in encoded  # not \\u-escaped
        assert "\\u" not in encoded

    def test_unknown_reason_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown quarantine reason kind"):
            quarantine_reason("not_a_kind")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cross-project separation
# ---------------------------------------------------------------------------


class TestCrossProjectSeparation:
    def test_identical_identity_across_projects_never_conflicts(self) -> None:
        payload_a = {"title": "方案A", "revision": "r1"}
        payload_b = {"title": "方案B", "revision": "r1"}
        rows = [
            _row("PRJ-A", "protocol_document", "document", "doc:1", "r1", payload_a),
            _row("PRJ-B", "protocol_document", "document", "doc:1", "r1", payload_b),
        ]
        snapshot = build_inventory(rows)
        assert snapshot.record_count == 2
        assert snapshot.quarantined_count == 0
        assert snapshot.deduplicated_count == 0
        projects = {record.project_id for record in snapshot.records}
        assert projects == {"PRJ-A", "PRJ-B"}
        hashes = {record.payload_sha256 for record in snapshot.records}
        assert hashes == {exact_payload_sha256(payload_a), exact_payload_sha256(payload_b)}
        _assert_accounting(snapshot)

    def test_project_payload_hashes_never_bleed(self) -> None:
        payload = {"title": "共享标题", "revision": "r1"}
        rows = [
            _row("PRJ-A", "corpus_evidence", "corpus", "row:1", "r1", payload),
            _row("PRJ-B", "corpus_evidence", "corpus", "row:1", "r1", payload),
        ]
        snapshot = build_inventory(rows)
        record_a = next(r for r in snapshot.records if r.project_id == "PRJ-A")
        record_b = next(r for r in snapshot.records if r.project_id == "PRJ-B")
        assert record_a.locator.locator_sha256 != record_b.locator.locator_sha256
        assert record_a.payload_sha256 == record_b.payload_sha256  # content identical


# ---------------------------------------------------------------------------
# Synthetic 3,878-row corpus denominator
# ---------------------------------------------------------------------------


class TestCorpusDenominator3878:
    def test_3878_row_corpus_keeps_unmappable_rows_explicit(self) -> None:
        valid: list[dict[str, object]] = []
        unmappable: list[tuple[str, object, QuarantineReasonKind]] = []
        rng = random.Random(3878)

        for index in range(3678):
            payload = {"row": index, "text": f"公司语料第{index}条", "revision": f"v{index % 5 + 1}"}
            valid.append(
                _row("CORPUS-2026", "corpus_evidence", "corpus", f"corpus:{index:05d}", f"v{index % 5 + 1}", payload)
            )
        for index in range(50):  # unsupported family
            unmappable.append(("billing_ledger", {"row": index, "amount": index}, QuarantineReasonKind.UNSUPPORTED_FAMILY))
        for index in range(50):  # missing revision
            row = _row("CORPUS-2026", "corpus_evidence", "corpus", f"missing-rev:{index:05d}", "v1", {"row": index})
            del row["revision_token"]
            unmappable.append((row, {"row": index}, QuarantineReasonKind.INCOMPLETE_RECORD))
        for index in range(50):  # empty source id
            row = _row("CORPUS-2026", "corpus_evidence", "corpus", "   ", "v1", {"row": index})
            unmappable.append((row, {"row": index}, QuarantineReasonKind.INCOMPLETE_RECORD))
        for index in range(25):  # internal revision contradiction
            unmappable.append(
                ("corpus_evidence", {"row": index, "revision": "conflicting"}, QuarantineReasonKind.AMBIGUOUS_IDENTITY)
            )
        for index in range(25):  # non-JSON payload
            unmappable.append(
                ("corpus_evidence", {"row": index, "d": datetime(2026, 1, 1)}, QuarantineReasonKind.INCOMPLETE_RECORD)
            )

        rows: list[dict[str, object]] = list(valid)
        for item in unmappable:
            family_or_row, payload, _ = item
            if isinstance(family_or_row, dict):
                rows.append(family_or_row)
            else:
                family: str = family_or_row
                rows.append(
                    _row(
                        "CORPUS-2026",
                        family,
                        "corpus",
                        f"bad:{rng.randrange(1 << 40):012d}",
                        "v1",
                        payload,
                    )
                )

        assert len(rows) == 3878
        snapshot = build_inventory(rows)
        second = build_inventory(list(reversed(rows)))

        # Denominator accounting: every row is exactly one explicit outcome.
        assert snapshot.source_count == 3878
        assert snapshot.record_count == 3678
        assert snapshot.quarantined_count == 200
        assert snapshot.deduplicated_count == 0
        _assert_accounting(snapshot)
        assert snapshot.records[0].source_family.value == "corpus_evidence"

        # Reason breakdown matches the injected unmappable classes exactly.
        assert snapshot.counts_by_reason == {
            "unsupported_family": 50,
            "incomplete_record": 125,
            "ambiguous_identity": 25,
        }

        # Every quarantine record is explicit: real hash when a payload
        # existed, None only for the non-JSON rows, always with a locator
        # identity and a stable reason.
        quarantined = snapshot.quarantine_records
        by_kind: dict[str, list[QuarantineRecord]] = {}
        for q in quarantined:
            by_kind.setdefault(q.reason_kinds[0].value, []).append(q)
        assert len(by_kind["unsupported_family"]) == 50
        assert all(_is_sha256(q.payload_sha256) for q in by_kind["unsupported_family"])
        assert all(_is_sha256(q.locator_sha256) for q in by_kind["unsupported_family"])
        assert len(by_kind["ambiguous_identity"]) == 25
        assert all(_is_sha256(q.payload_sha256) for q in by_kind["ambiguous_identity"])
        incomplete = by_kind["incomplete_record"]
        assert len(incomplete) == 125
        assert all(q.payload_sha256 is None or _is_sha256(q.payload_sha256) for q in incomplete)
        # The 25 non-JSON rows are exactly the payload-hash-less ones.
        assert sum(1 for q in incomplete if q.payload_sha256 is None) == 25

        # No fabrication: every inventoried hash corresponds to a real row
        # payload and no unmappable payload leaked into the inventoried set.
        inventoried_hashes = {record.payload_sha256 for record in snapshot.records}
        assert len(inventoried_hashes) == 3678
        unmappable_hashes = {
            h for h in (q.payload_sha256 for q in quarantined) if h is not None
        }
        assert not (inventoried_hashes & unmappable_hashes)
        expected_valid_hash = exact_payload_sha256(
            {"row": 0, "text": "公司语料第0条", "revision": "v1"}
        )
        assert expected_valid_hash in inventoried_hashes

        # Determinism across input order.
        assert second.inventory_sha256 == snapshot.inventory_sha256
        assert second.records == snapshot.records
        assert second.quarantine_records == snapshot.quarantine_records

    @pytest.mark.parametrize(
        "rows",
        [
            [],
            [_valid_row(0)],
            [_valid_row(0), copy.deepcopy(_valid_row(0))],
            [_valid_row(0), _row("P", "billing", "x", "b:1", "v1", {"a": 1})],
            [_valid_row(0), _row("P", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1}), _row("P", "corpus_evidence", "corpus", "row:1", "v1", {"n": 2})],
        ],
    )
    def test_accounting_invariant_holds_across_corpora(self, rows: list[dict[str, object]]) -> None:
        snapshot = build_inventory(rows)
        _assert_accounting(snapshot)
        assert _is_sha256(snapshot.inventory_sha256)


# ---------------------------------------------------------------------------
# Snapshot accounting enforcement and deep immutability (recovery P1)
# ---------------------------------------------------------------------------


class TestSnapshotAccountingAndImmutability:
    """InventorySnapshot self-validates and deep-freezes its count maps.

    Regression for the recovery P1: ``family_counts``/``counts_by_reason``
    were mutable plain dicts (hash drift after construction) and the
    constructor accepted forged counts, ordering and duplicate members.  All
    of those must now fail closed.
    """

    @staticmethod
    def _single_record_snapshot() -> InventorySnapshot:
        return build_inventory([_valid_row(0)])

    @staticmethod
    def _quarantining_snapshot() -> InventorySnapshot:
        return build_inventory([_row("PRJ-1", "billing", "x", "b:1", "v1", {"a": 1})])

    def test_count_maps_are_deep_frozen_and_hash_never_drifts(self) -> None:
        snapshot = self._single_record_snapshot()
        before = snapshot.inventory_sha256
        for attempt in (
            lambda: snapshot.family_counts.__setitem__("study_definition", 999),
            lambda: snapshot.family_counts.update({"study_definition": 1}),
            lambda: snapshot.family_counts.__delitem__("corpus_evidence"),
            lambda: snapshot.family_counts.pop("corpus_evidence"),
            lambda: snapshot.family_counts.clear(),
            lambda: snapshot.family_counts.setdefault("study_definition", 1),
        ):
            with pytest.raises(TypeError):
                attempt()
        assert snapshot.family_counts == {"corpus_evidence": 1}
        assert snapshot.inventory_sha256 == before

    def test_reason_counts_are_deep_frozen(self) -> None:
        snapshot = self._quarantining_snapshot()
        assert snapshot.counts_by_reason == {"unsupported_family": 1}
        with pytest.raises(TypeError):
            snapshot.counts_by_reason["incomplete_record"] = 1
        with pytest.raises(TypeError):
            snapshot.counts_by_reason.update({"bogus": 1})
        with pytest.raises(TypeError):
            snapshot.counts_by_reason.clear()
        assert snapshot.counts_by_reason == {"unsupported_family": 1}

    def test_forged_constructor_counts_are_rejected(self) -> None:
        # Exact recovery reproduction: invented aggregate counts must fail
        # closed even when every other field is left at defaults.
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=0,
                record_count=99,
                quarantined_count=0,
                deduplicated_count=0,
            )
        # Accounting identity holds but declared record length is forged.
        record = self._single_record_snapshot().records[0]
        quarantined = self._quarantining_snapshot().quarantine_records[0]
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=3,
                record_count=2,
                quarantined_count=1,
                deduplicated_count=0,
                records=(record,),
                quarantine_records=(quarantined,),
                family_counts={"corpus_evidence": 1},
                counts_by_reason={"unsupported_family": 1},
            )

    def test_declared_counts_must_match_tuple_lengths(self) -> None:
        record = self._single_record_snapshot().records[0]
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=1,
                record_count=1,
                quarantined_count=0,
                deduplicated_count=0,
                records=(),
            )
        quarantined = self._quarantining_snapshot().quarantine_records[0]
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=2,
                record_count=0,
                quarantined_count=2,
                deduplicated_count=0,
                records=(),
                quarantine_records=(quarantined,),
                counts_by_reason={"unsupported_family": 2},
            )

    def test_altered_family_counts_are_rejected(self) -> None:
        snapshot = self._single_record_snapshot()
        base = dict(
            source_count=1,
            record_count=1,
            quarantined_count=0,
            deduplicated_count=0,
            records=(snapshot.records[0],),
            quarantine_records=(),
        )
        for forged in (
            {"corpus_evidence": 2},  # wrong value
            {"study_definition": 1},  # wrong family for the actual record
            {"corpus_evidence": 1, "study_definition": 1},  # extra family
            {"billing": 1},  # unknown family
            {"corpus_evidence": 0},  # non-positive count
            {"corpus_evidence": -1},  # negative count
        ):
            with pytest.raises(ValidationError):
                InventorySnapshot(**base, family_counts=forged)

    def test_altered_reason_counts_are_rejected(self) -> None:
        snapshot = self._quarantining_snapshot()
        base = dict(
            source_count=1,
            record_count=0,
            quarantined_count=1,
            deduplicated_count=0,
            records=(),
            quarantine_records=(snapshot.quarantine_records[0],),
        )
        for forged in (
            {"unsupported_family": 2},  # wrong value
            {"incomplete_record": 1},  # wrong reason for the actual record
            {"unsupported_family": 1, "incomplete_record": 1},  # extra reason
            {"bogus_reason": 1},  # unknown reason
            {"unsupported_family": 0},  # non-positive count
        ):
            with pytest.raises(ValidationError):
                InventorySnapshot(**base, counts_by_reason=forged)

    def test_unsorted_or_duplicate_records_are_rejected(self) -> None:
        rows = [
            _row("PRJ-1", "corpus_evidence", "corpus", "row:1", "v1", {"n": 1, "revision": "v1"}),
            _row("PRJ-0", "protocol_document", "document", "doc:1", "r1", {"revision": "r1"}),
        ]
        snapshot = build_inventory(rows)
        keys = [record.identity_key for record in snapshot.records]
        assert keys == sorted(keys)
        # Reversed order is non-canonical.
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=2,
                record_count=2,
                quarantined_count=0,
                deduplicated_count=0,
                records=tuple(reversed(snapshot.records)),
                quarantine_records=(),
                family_counts=dict(snapshot.family_counts),
            )
        # Duplicate identity (same record twice) is non-canonical.
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=2,
                record_count=2,
                quarantined_count=0,
                deduplicated_count=0,
                records=(snapshot.records[0], snapshot.records[0]),
                quarantine_records=(),
                family_counts={"corpus_evidence": 2},
            )

    def test_unsorted_or_cross_set_quarantine_records_are_rejected(self) -> None:
        rows = [
            _row("PRJ-1", "billing", "x", "b:1", "v1", {"a": 1}),
            _row("PRJ-0", "ledger", "x", "l:1", "v1", {"a": 2}),
        ]
        snapshot = build_inventory(rows)
        assert snapshot.quarantined_count == 2
        # Reversed order is non-canonical.
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=2,
                record_count=0,
                quarantined_count=2,
                deduplicated_count=0,
                records=(),
                quarantine_records=tuple(reversed(snapshot.quarantine_records)),
                counts_by_reason=dict(snapshot.counts_by_reason),
            )
        # A quarantine identity that also appears as an inventoried record is
        # non-canonical: the builder never produces both for one identity.
        inventoried = build_inventory(
            [_row("PRJ-9", "corpus_evidence", "corpus", "row:9", "v1", {"n": 1, "revision": "v1"})]
        ).records[0]
        quarantined_same_identity = build_inventory(
            [_row("PRJ-9", "corpus_evidence", "corpus", "row:9", "v1", {"n": 2, "revision": "v9"})]
        ).quarantine_records[0]
        assert quarantined_same_identity.source_id == "row:9"
        with pytest.raises(ValidationError):
            InventorySnapshot(
                source_count=2,
                record_count=1,
                quarantined_count=1,
                deduplicated_count=0,
                records=(inventoried,),
                quarantine_records=(quarantined_same_identity,),
                family_counts={"corpus_evidence": 1},
                counts_by_reason={"ambiguous_identity": 1},
            )

    def test_identical_quarantine_records_are_legitimate(self) -> None:
        # Two identical payload-less rows produce two identical quarantine
        # records; identical records are valid builder output, so the
        # snapshot stays canonical as long as ordering and counts hold.
        snapshot = build_inventory(["nonsense", "nonsense"])  # type: ignore[list-item]
        assert snapshot.quarantined_count == 2
        assert snapshot.quarantine_records[0] == snapshot.quarantine_records[1]
        assert snapshot.counts_by_reason == {"incomplete_record": 2}
        manual = InventorySnapshot(
            source_count=2,
            record_count=0,
            quarantined_count=2,
            deduplicated_count=0,
            records=(),
            quarantine_records=snapshot.quarantine_records,
            counts_by_reason={"incomplete_record": 2},
        )
        assert manual.inventory_sha256 == snapshot.inventory_sha256

    def test_canonical_manual_construction_preserves_hash(self) -> None:
        snapshot = self._quarantining_snapshot()
        manual = InventorySnapshot(
            source_count=snapshot.source_count,
            record_count=snapshot.record_count,
            quarantined_count=snapshot.quarantined_count,
            deduplicated_count=snapshot.deduplicated_count,
            records=snapshot.records,
            quarantine_records=snapshot.quarantine_records,
            family_counts=dict(snapshot.family_counts),
            counts_by_reason=dict(snapshot.counts_by_reason),
        )
        assert manual.inventory_sha256 == snapshot.inventory_sha256
        assert isinstance(manual.family_counts, dict)
        assert isinstance(manual.counts_by_reason, dict)
        with pytest.raises(TypeError):
            manual.family_counts["corpus_evidence"] = 1

    def test_empty_snapshot_is_valid_and_frozen(self) -> None:
        snapshot = InventorySnapshot(
            source_count=0, record_count=0, quarantined_count=0, deduplicated_count=0
        )
        assert snapshot.records == ()
        assert snapshot.family_counts == {}
        assert _is_sha256(snapshot.inventory_sha256)
        with pytest.raises(TypeError):
            snapshot.family_counts["study_definition"] = 1


# ---------------------------------------------------------------------------
# Snapshot contract
# ---------------------------------------------------------------------------


class TestSnapshotContract:
    def test_package_exports_and_schema_version(self) -> None:
        from services.api.app.protocol_workflow.legacy import __all__ as legacy_exports

        for name in (
            "LegacySourceFamily",
            "LegacySourceRecord",
            "SourceRevisionToken",
            "ImmutableLocator",
            "InventorySnapshot",
            "QuarantineReason",
            "QuarantineReasonKind",
            "QuarantineRecord",
            "build_inventory",
            "quarantine_reason",
        ):
            assert name in legacy_exports
        assert INVENTORY_SCHEMA_VERSION == "mw_legacy_inventory_v1"

    def test_snapshot_hash_changes_when_any_payload_changes(self) -> None:
        base = [_valid_row(1)]
        changed = [_valid_row(1)]
        changed[0]["payload"] = {"index": 1, "text": "公司语料示例（改动）", "revision": "v2"}
        changed[0]["revision_token"] = "v2"
        snap_a = build_inventory(base)
        snap_b = build_inventory(changed)
        assert snap_a.record_count == snap_b.record_count == 1
        assert snap_a.inventory_sha256 != snap_b.inventory_sha256

    def test_direct_record_construction_keeps_hash_integrity(self) -> None:
        record = LegacySourceRecord(
            project_id="PRJ-1",
            source_family=LegacySourceFamily.STUDY_DEFINITION,
            source_type="definition",
            source_id="def:1",
            revision_token=SourceRevisionToken(value="r1"),
            payload={"title": "T", "revision": "r1"},
        )
        assert _is_sha256(record.payload_sha256)
        assert record.payload_sha256 == exact_payload_sha256({"title": "T", "revision": "r1"})
        assert record.identity_key == ("PRJ-1", "study_definition", "definition", "def:1", "r1")
        snapshot = build_inventory([record])
        assert snapshot.record_count == 1
        assert snapshot.records[0] == record

    def test_family_enum_is_stable_str_enum(self) -> None:
        assert isinstance(LegacySourceFamily.STUDY_DEFINITION, Enum)
        assert LegacySourceFamily.STUDY_DEFINITION.value == "study_definition"
        assert LegacySourceFamily("study_definition") is LegacySourceFamily.STUDY_DEFINITION
