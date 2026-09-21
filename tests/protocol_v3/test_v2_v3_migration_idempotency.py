"""Task 1.10 — versioned mapping spec, deterministic dry-run & idempotent lineage.

Worker 02 focused test: proves the mapping specification validation
(``migration_map.py`` + ``config/medical_writing/protocol_v3/v2_v3_mapping.json``)
and the pure deterministic dry run with *synthetic immutable inputs only*.
No database, no runtime singleton, no source file is read or written; every
input is constructed in memory and proven unchanged after the run.

Covered contracts:

* strict spec validation — unknown keys, unknown families, missing seven-family
  coverage, unknown outcomes/rule kinds/derive ops/bases, duplicate rules,
  bare omissions without a Chinese reason, invented semantic-node defaults and
  generic toy source aliases all fail closed at load time;
* real-contract binding — every shipped production source type is the
  mechanically derived identifier of a declared ``source_contract`` (Pydantic
  model symbol / SQLite table / JSONL snapshot) and the pure read-only drift
  verifier proves every symbol/table/column/field exists in the checked-in
  v2 contracts, without importing or opening any live store;
* real source identity binding — before any mapped outcome the declared
  identity/project/revision fields of the contract location must match the
  record envelope; wrong source id / wrong project / wrong revision / missing
  or unsupported values yield one explicit ``incomplete_record`` quarantine
  and no lineage entry; composite identities use the canonical ordered
  encoding; target identities are project-scoped (lineage keys embed the
  project, so two projects can never collapse);
* exhaustive field disposition — every real model field / DDL column /
  payload-model field of a mapped type is covered by a declared role, a field
  rule, or deep-frozen whole-payload preservation; the verifier fails when a
  contract field is added without a disposition or a declared covered field
  does not exist; ``omitted`` rules carry non-empty Chinese reasons;
* deep immutability — ``MappingSpec.families`` and every nested container that
  affects ``spec_sha256`` reject mutation, and report containers are frozen;
* all seven declared families map through the shipped spec with the declared
  target types, identity prefixes, direct/derived/preserved/omitted field
  rules (physical and payload scopes) and explicit quarantine outcomes;
* exact accounting — ``source == mapped + unmapped``, ``quarantined ==
  unmapped``, exactly one quarantine record per unmapped row, no silent drops,
  no fabricated semantic node;
* determinism — permutation-stable reports and hashes, payload key-order
  invariance, source immutability (caller payloads untouched, report fields
  frozen);
* idempotent lineage — exact replay yields the identical target identity/hash
  with no extra semantic effect; conflicting replay fails closed; a changed
  revision creates a child pointing at the prior result without overwriting it;
* synthetic 3,878-row company-corpus denominator — some rows map, every
  remaining row is quarantined explicitly with full accounting.
"""

from __future__ import annotations

import copy
import json
import random
import sys

import pytest
from pydantic import ValidationError

from services.api.app.protocol_workflow.canonical.hashing import (
    canonical_json,
    exact_payload_sha256,
)
from services.api.app.protocol_workflow.legacy.migration_inventory import (
    LEGACY_SOURCE_FAMILIES,
    LegacySourceRecord,
    SourceRevisionToken,
    build_inventory,
)
from services.api.app.protocol_workflow.legacy import migration_map as migration_map_module
from services.api.app.protocol_workflow.legacy.migration_map import (
    CONTRACT_VERIFICATION_SCHEMA_VERSION,
    DRY_RUN_SCHEMA_VERSION,
    JOIN_SEPARATOR,
    LINEAGE_SCHEMA_VERSION,
    MAPPING_SCHEMA_VERSION,
    DryRunReport,
    MappedOutcome,
    MappingContractVerification,
    MappingLineageEntry,
    MappingLineageError,
    MappingSpec,
    MappingSpecError,
    QuarantinedOutcome,
    load_mapping_spec,
    parse_mapping_spec,
    run_mapping_dry_run,
    verify_mapping_spec_contracts,
)

SPEC_PATH = "config/medical_writing/protocol_v3/v2_v3_mapping.json"

SEVEN_FAMILIES = {
    "study_definition",
    "journey_stage_draft",
    "working_copy_snapshot",
    "corpus_evidence",
    "decision_approval",
    "protocol_document",
    "artifact_lineage",
}

Sha256_HEX_RE = "0123456789abcdef"


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in Sha256_HEX_RE for char in value)
    )


def _raw_spec() -> dict[str, object]:
    with open(SPEC_PATH, encoding="utf-8") as handle:
        return json.load(handle)


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


def _record(
    family: str,
    source_type: str,
    source_id: str,
    revision_token: str,
    payload: object,
    project_id: str = "PRJ-1",
) -> LegacySourceRecord:
    return LegacySourceRecord(
        project_id=project_id,
        source_family=family,
        source_type=source_type,
        source_id=source_id,
        revision_token=SourceRevisionToken(value=revision_token),
        payload=payload,
    )


def _loaded_spec() -> MappingSpec:
    return load_mapping_spec(SPEC_PATH)


def _payload_for_type(
    type_spec, source_id: str, project_id: str, revision: str
) -> dict[str, object]:
    """Build a payload that satisfies the identity binding and every declared
    rule of one type spec (identity/project/revision fields are injected from
    the envelope values, so the row binds exactly)."""

    contract = type_spec.source_contract
    container = (
        contract.payload_container if contract.kind == "sqlite_table" else None
    )
    payload: dict[str, object] = {}
    inner: dict[str, object] | None = None
    if container:
        inner = {}
        payload[container] = inner

    def holder_for(rule) -> dict[str, object]:
        if rule.source_scope == "payload" and inner is not None:
            return inner
        return payload

    for field in contract.identity_fields:
        payload[field] = source_id
    for field in contract.project_scope_fields:
        payload[field] = project_id
    for field in contract.revision_fields:
        payload[field] = revision
    for rule in type_spec.field_rules:
        if rule.kind == "whole_payload":
            continue
        if rule.kind == "derived" and rule.derive != "string_join":
            continue
        holder = holder_for(rule)
        if rule.source_field is not None:
            holder[rule.source_field] = "值"
        for field in rule.source_fields:
            holder[field] = "段"
    # binding fields win over rule-generated values: the row must bind
    # exactly to the envelope identity/project/revision
    for field in contract.identity_fields:
        payload[field] = source_id
    for field in contract.project_scope_fields:
        payload[field] = project_id
    for field in contract.revision_fields:
        payload[field] = revision
    return payload


def _definition_row(
    project_id: str, source_id: str, revision: str, origin: str = "guided_greenfield"
) -> dict[str, object]:
    return _row(
        project_id,
        "study_definition",
        "models.MedicalWritingStudyDefinition",
        source_id,
        revision,
        {
            "definition_id": source_id,
            "project_id": project_id,
            "revision": revision,
            "origin": origin,
            "state_sha256": "1" * 64,
            "synopsis_text": "junk",
        },
    )


# ---------------------------------------------------------------------------
# Shipped spec loads under the strict model
# ---------------------------------------------------------------------------


class TestShippedSpecLoads:
    def test_spec_file_loads_and_self_validates(self) -> None:
        spec = _loaded_spec()
        assert spec.schema_version == "mw_v2_v3_mapping_v1"
        assert MAPPING_SCHEMA_VERSION == "mw_v2_v3_mapping_v1"
        assert spec.mapping_version == "mw-v2-v3-mapping.2026.08.12-task110"
        assert spec.generated_for == "mw_protocol_v3_phase1_task110_20260812"
        assert _is_sha256(spec.spec_sha256)

    def test_spec_covers_exactly_the_seven_declared_families(self) -> None:
        spec = _loaded_spec()
        assert set(spec.families) == SEVEN_FAMILIES
        assert set(LEGACY_SOURCE_FAMILIES) == SEVEN_FAMILIES
        for family, family_spec in spec.families.items():
            assert family_spec.family_label_zh
            assert len(family_spec.types) >= 1

    def test_spec_declared_vocabularies_match_usage(self) -> None:
        spec = _loaded_spec()
        assert set(spec.identity_rule_bases) == {"source_id"}
        assert set(spec.derive_ops) == {"string_join", "revision_token", "payload_sha256"}
        for family_spec in spec.families.values():
            for type_spec in family_spec.types:
                if type_spec.identity_rule is not None:
                    assert type_spec.identity_rule.basis in spec.identity_rule_bases
                for rule in type_spec.field_rules:
                    if rule.derive is not None:
                        assert rule.derive in spec.derive_ops

    def test_spec_rejects_unknown_top_level_key(self) -> None:
        raw = _raw_spec()
        raw["sneaky_key"] = True
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_unknown_family_key(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        raw["families"]["billing_ledger"] = {
            "family_label_zh": "账单",
            "types": [copy.deepcopy(definition)],
        }
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_missing_seven_family_coverage(self) -> None:
        raw = _raw_spec()
        del raw["families"]["artifact_lineage"]
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "artifact_lineage" in str(exc.value)

    def test_spec_rejects_family_without_types(self) -> None:
        raw = _raw_spec()
        raw["families"]["protocol_document"] = {"family_label_zh": "方案文档", "types": []}
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_unknown_type_key(self) -> None:
        raw = _raw_spec()
        raw["families"]["protocol_document"]["types"][0]["mystery"] = 1
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_unknown_outcome_value(self) -> None:
        raw = _raw_spec()
        raw["families"]["protocol_document"]["types"][0]["outcome"] = "fabricated"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_quarantine_type_carrying_target_shape(self) -> None:
        raw = _raw_spec()
        corpus = next(
            t
            for t in raw["families"]["corpus_evidence"]["types"]
            if t["source_type"] == "jsonl.cms_cn_protocol_corpus_20260715_v1"
        )
        corpus["target_type"] = "invented_node"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_quarantine_type_without_detail(self) -> None:
        raw = _raw_spec()
        corpus = next(
            t
            for t in raw["families"]["corpus_evidence"]["types"]
            if t["source_type"] == "jsonl.cms_cn_protocol_corpus_20260715_v1"
        )
        corpus["quarantine_detail_zh"] = ""
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_non_quarantine_type_without_identity_rule(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        del definition["identity_rule"]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_empty_identity_prefix(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["identity_rule"]["prefix"] = ""
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_basis_outside_declared_bases(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["identity_rule"]["basis"] = "random_seed"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_unknown_field_rule_kind(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"].append(
            {"kind": "teleport", "source_field": "a", "target_field": "b"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_derive_op_outside_declared_ops(self) -> None:
        raw = _raw_spec()
        lineage = next(
            t
            for t in raw["families"]["artifact_lineage"]["types"]
            if t["source_type"] == "sqlite.medical_writing_artifact_lifecycle_records"
        )
        lineage["field_rules"].append(
            {"kind": "derived", "derive": "llm_magic", "target_field": "ghost"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_string_join_without_source_fields(self) -> None:
        raw = _raw_spec()
        lineage = next(
            t
            for t in raw["families"]["artifact_lineage"]["types"]
            if t["source_type"] == "sqlite.medical_writing_artifact_lifecycle_records"
        )
        lineage["field_rules"].append(
            {"kind": "derived", "derive": "string_join", "target_field": "x"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_revision_token_derive_with_source_fields(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"].append(
            {
                "kind": "derived",
                "derive": "revision_token",
                "source_fields": ["origin"],
                "target_field": "x",
            }
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_omitted_rule_with_target_field(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"].append(
            {"kind": "omitted", "source_field": "a", "target_field": "b"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_bare_omitted_rule_without_reason(self) -> None:
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        working_copies["field_rules"].append(
            {"kind": "omitted", "source_scope": "physical", "source_field": "section_id"}
        )
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "omission_reason_zh" in str(exc.value)

    def test_spec_rejects_duplicate_source_type_within_family(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        raw["families"]["study_definition"]["types"].append(copy.deepcopy(definition))
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_duplicate_target_field_within_type(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"].append(
            {"kind": "direct", "source_field": "state_sha256", "target_field": "state_sha256"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_duplicate_source_field_within_type(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"].append(
            {"kind": "direct", "source_field": "origin", "target_field": "headline"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_duplicate_vocabulary_entries(self) -> None:
        raw = _raw_spec()
        raw["derive_ops"].append("string_join")
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_wrong_schema_version(self) -> None:
        raw = _raw_spec()
        raw["schema_version"] = "mw_v2_v3_mapping_v9"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_spec_rejects_non_object_raw(self) -> None:
        with pytest.raises(MappingSpecError):
            parse_mapping_spec([1, 2, 3])
        with pytest.raises(MappingSpecError):
            parse_mapping_spec("not a spec")

    def test_spec_is_frozen_and_hash_stable(self) -> None:
        spec = _loaded_spec()
        with pytest.raises((TypeError, ValidationError)):
            spec.families["study_definition"].types[0].source_type = "hacked"  # type: ignore[misc]
        again = _loaded_spec()
        assert again.spec_sha256 == spec.spec_sha256


# ---------------------------------------------------------------------------
# All seven families map with the declared semantics
# ---------------------------------------------------------------------------


class TestSevenFamiliesMapping:
    def test_study_definition_direct_with_whole_payload_preservation(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "def:1",
            "1",
            {
                "definition_id": "def:1",
                "project_id": "PRJ-1",
                "revision": 1,
                "origin": "guided_greenfield",
                "state_sha256": "a" * 64,
                "synopsis_text": "草稿内容",
                "framing": {"document_title": "研究"},
                "picos": {},
                "created_at": "2026-08-12",
                "updated_at": "2026-08-12",
                "updated_by": "医学经理",
            },
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 1 and report.unmapped_count == 0
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        assert outcome.target_type == "study_definition_node"
        assert outcome.target_id == "v3::study_definition::def:1"
        assert dict(outcome.fields) == {
            "origin": "guided_greenfield",
            "state_sha256": "a" * 64,
            "source_revision": "1",
            "content_hash": record.payload_sha256,
            "legacy_payload": record.payload,
        }
        # every real field is carried: semantic fields mapped, the rest
        # preserved as a deep-frozen whole payload — nothing silently drops
        preserved = outcome.fields["legacy_payload"]
        assert isinstance(preserved, dict)
        for key in (
            "definition_id",
            "project_id",
            "revision",
            "origin",
            "state_sha256",
            "synopsis_text",
            "framing",
            "picos",
            "created_at",
            "updated_at",
            "updated_by",
        ):
            assert key in preserved
        assert preserved["framing"] == {"document_title": "研究"}

    def test_study_definition_declared_quarantine(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudySchemaSnapshot",
            "ss:1",
            "r1",
            {"project_id": "PRJ-1"},
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "unsupported_type"
        assert "schema 快照" in outcome.quarantine_record.detail_zh
        # original source hash and locator preserved
        assert outcome.quarantine_record.payload_sha256 == record.payload_sha256
        assert _is_sha256(outcome.quarantine_record.locator_sha256 or "")

    def test_journey_stage_draft_family(self) -> None:
        spec = _loaded_spec()
        journey = _record(
            "journey_stage_draft",
            "models.MedicalWritingAuthoringJourney",
            "J-9",
            "1",
            {
                "journey_id": "J-9",
                "project_id": "PRJ-1",
                "revision": 1,
                "status": "stage1_in_progress",
                "current_stage": "framing",
                "entry_mode": "guided_greenfield",
                "framing_complete": False,
                "picos_complete": False,
            },
        )
        stage = _record(
            "journey_stage_draft",
            "models.MedicalWritingAuthoringStageDraft",
            "st:1",
            "v2",
            {"stage": "picos", "saved_from_revision": 3},
        )
        reservation = _record(
            "journey_stage_draft",
            "sqlite.medical_writing_authoring_journey_generation_reservations",
            "res:1",
            "v1",
            {},
        )
        report = run_mapping_dry_run([reservation, stage, journey], spec)
        assert report.mapped_count == 1 and report.unmapped_count == 2
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        assert outcome.target_id == "v3::journey::J-9"
        assert dict(outcome.fields) == {
            "state": "stage1_in_progress",
            "stage": "framing",
            "entry_mode": "guided_greenfield",
            "framing_complete": False,
            "picos_complete": False,
            "source_revision": "1",
            "content_hash": journey.payload_sha256,
            "legacy_payload": journey.payload,
        }
        details = {
            q.quarantine_record.source_type: q.quarantine_record.detail_zh
            for q in report.outcomes
            if isinstance(q, QuarantinedOutcome)
        }
        # the nested stage draft is explicitly quarantined: it cannot
        # independently bind a project/identity and must not pretend
        # `stage` alone is a globally meaningful source identity
        assert "嵌套" in details["models.MedicalWritingAuthoringStageDraft"]
        assert "瞬态" in details[
            "sqlite.medical_writing_authoring_journey_generation_reservations"
        ]

    def test_working_copy_snapshot_family_physical_and_payload_scopes(self) -> None:
        spec = _loaded_spec()
        wc = _record(
            "working_copy_snapshot",
            "sqlite.medical_writing_working_copies",
            "wc:2",
            "4",
            {
                "working_copy_id": "wc:2",
                "project_id": "PRJ-1",
                "revision": 4,
                "document_id": "doc:2",
                "section_id": "S1",
                "approval_state": "in_medical_review",
                "payload_json": {
                    "working_copy_id": "wc:2",
                    "project_id": "PRJ-1",
                    "document_id": "doc:2",
                    "content_authority_state": "historical_quarantined",
                    "freeze_status": "editable",
                },
            },
        )
        snap = _record(
            "working_copy_snapshot",
            "sqlite.medical_writing_working_copy_snapshots",
            "sn:3",
            "4",
            {
                "snapshot_id": "sn:3",
                "project_id": "PRJ-1",
                "revision": 4,
                "snapshot_type": "save",
                "working_copy_id": "wc:2",
                "payload_json": {
                    "working_copy_id": "wc:2",
                    "content_authority_state": "historical_quarantined",
                },
            },
        )
        report = run_mapping_dry_run([wc, snap], spec)
        assert report.mapped_count == 2
        by_type = {o.source_type: o for o in report.outcomes if isinstance(o, MappedOutcome)}
        wc_outcome = by_type["sqlite.medical_writing_working_copies"]
        assert wc_outcome.target_type == "working_copy_snapshot"
        assert wc_outcome.target_id == "legacy::working_copy::wc:2"
        assert dict(wc_outcome.fields) == {
            "document_id": "doc:2",
            "section_id": "S1",
            "approval_state": "in_medical_review",
            "legacy_payload": wc.payload["payload_json"],
        }
        snap_outcome = by_type["sqlite.medical_writing_working_copy_snapshots"]
        assert snap_outcome.target_id == "legacy::snapshot::sn:3"
        assert dict(snap_outcome.fields) == {
            "snapshot_type": "save",
            "working_copy_id": "wc:2",
            "legacy_payload": snap.payload["payload_json"],
        }

    def test_corpus_evidence_family(self) -> None:
        spec = _loaded_spec()
        artifact = _record(
            "corpus_evidence",
            "models.WritingReferenceDocumentArtifact",
            "art:1",
            "1",
            {
                "artifact_id": "art:1",
                "project_id": "PRJ-1",
                "state_revision": 1,
                "nct_id": "NCT1",
                "document_type": "protocol",
                "content_sha256": "c" * 64,
                "source_status": "downloaded",
            },
        )
        snapshot_def = _record(
            "corpus_evidence",
            "models.MedicalWritingCorpusSnapshotDefinition",
            "snap:1",
            "v1",
            {"snapshot_id": "snap:1"},
        )
        candidate = _record(
            "corpus_evidence",
            "models.MedicalWritingSharedCorpusCandidate",
            "seg:1",
            "v1",
            {"segment_id": "seg:1"},
        )
        corpus = _record(
            "corpus_evidence",
            "jsonl.cms_cn_protocol_corpus_20260715_v1",
            "row:1",
            "v1",
            {"index": 1},
        )
        report = run_mapping_dry_run([corpus, candidate, snapshot_def, artifact], spec)
        assert report.mapped_count == 1 and report.unmapped_count == 3
        outcome = next(
            o for o in report.outcomes if isinstance(o, MappedOutcome)
        )
        assert outcome.target_type == "corpus_evidence_node"
        assert outcome.target_id == "v3::corpus_artifact::art:1"
        assert outcome.fields["content_hash"] == artifact.payload_sha256
        assert outcome.fields["nct_id"] == "NCT1"
        assert outcome.fields["legacy_payload"]["source_status"] == "downloaded"
        details = {
            q.quarantine_record.source_type: q.quarantine_record.detail_zh
            for q in report.outcomes
            if isinstance(q, QuarantinedOutcome)
        }
        assert "3,878" in details["jsonl.cms_cn_protocol_corpus_20260715_v1"]
        # tenant-global corpus objects cannot bind a project: quarantined
        assert "项目" in details["models.MedicalWritingCorpusSnapshotDefinition"]
        assert "项目" in details["models.MedicalWritingSharedCorpusCandidate"]

    def test_decision_approval_family_preserved(self) -> None:
        spec = _loaded_spec()
        review = _record(
            "decision_approval",
            "sqlite.writing_reference_extraction_review_records",
            "rv:1",
            "1",
            {
                "review_id": "rv:1",
                "project_id": "PRJ-1",
                "revision": 1,
                "artifact_id": "art:1",
                "extraction_revision": "e1",
                "decision": "approved",
                "payload_json": {
                    "review_id": "rv:1",
                    "project_id": "PRJ-1",
                    "artifact_id": "art:1",
                    "extraction_revision": "e1",
                    "decision": "approved",
                    "actor": "医学经理",
                    "comment": "同意",
                    "revision": 1,
                },
            },
        )
        gate = _record(
            "decision_approval",
            "sqlite.approval_gates",
            "ag:1",
            "2026-08-12T03:00:00Z",
            {
                "tenant_id": "tenant-1",
                "project_id": "PRJ-1",
                "approval_id": "ag:1",
                "updated_at": "2026-08-12T03:00:00Z",
                "payload_json": {
                    "approval_id": "ag:1",
                    "project_id": "PRJ-1",
                    "target_type": "protocol_document",
                    "target_id": "doc:1",
                    "state": "pending",
                    "display_title": "方案定稿审批",
                },
            },
        )
        decision = _record(
            "decision_approval",
            "sqlite.approval_decisions",
            "dec:1",
            "2026-08-12T03:01:00Z",
            {
                "tenant_id": "tenant-1",
                "project_id": "PRJ-1",
                "decision_id": "dec:1",
                "approval_id": "ag:1",
                "created_at": "2026-08-12T03:01:00Z",
                "payload_json": {
                    "decision_id": "dec:1",
                    "approval_id": "ag:1",
                    "project_id": "PRJ-1",
                    "action": "approve",
                    "actor": "医学经理",
                    "previous_state": "pending",
                    "new_state": "approved",
                },
            },
        )
        report = run_mapping_dry_run([decision, gate, review], spec)
        assert report.mapped_count == 3 and report.unmapped_count == 0
        outcomes = {
            o.source_type: o
            for o in report.outcomes
            if isinstance(o, MappedOutcome)
        }
        review_outcome = outcomes[
            "sqlite.writing_reference_extraction_review_records"
        ]
        assert review_outcome.target_id == "legacy::extraction_review::rv:1"
        assert dict(review_outcome.fields) == {
            "artifact_id": "art:1",
            "extraction_revision": "e1",
            "decision": "approved",
            "legacy_payload": review.payload["payload_json"],
        }
        assert outcomes["sqlite.approval_gates"].target_id == (
            "legacy::approval_gate::ag:1"
        )
        assert outcomes["sqlite.approval_gates"].fields["source_revision"] == (
            "2026-08-12T03:00:00Z"
        )
        assert outcomes["sqlite.approval_decisions"].target_id == (
            "legacy::approval_decision::dec:1"
        )
        assert outcomes["sqlite.approval_decisions"].fields["source_revision"] == (
            "2026-08-12T03:01:00Z"
        )

    def test_protocol_document_family(self) -> None:
        spec = _loaded_spec()
        doc = _record(
            "protocol_document",
            "sqlite.medical_writing_greenfield_documents",
            "doc:1",
            "2",
            {
                "document_id": "doc:1",
                "project_id": "PRJ-1",
                "baseline_revision": 2,
                "baseline_sha256": "b" * 64,
                "payload_json": {
                    "document_id": "doc:1",
                    "project_id": "PRJ-1",
                    "protocol_id": "P1",
                    "version": "V2.0",
                    "status": "frozen",
                },
            },
        )
        old = _record(
            "protocol_document",
            "sqlite.medical_writing_greenfield_events",
            "ev:1",
            "v1",
            {},
        )
        report = run_mapping_dry_run([old, doc], spec)
        assert report.mapped_count == 1 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        assert outcome.target_id == "v3::protocol_doc::doc:1"
        assert outcome.fields["content_hash"] == doc.payload_sha256
        assert dict(outcome.fields) == {
            "document_id": "doc:1",
            "baseline_revision": 2,
            "baseline_sha256": "b" * 64,
            "protocol_id": "P1",
            "version": "V2.0",
            "state": "frozen",
            "content_hash": doc.payload_sha256,
            "legacy_payload": doc.payload["payload_json"],
        }

    def test_artifact_lineage_family(self) -> None:
        spec = _loaded_spec()
        entry = _record(
            "artifact_lineage",
            "sqlite.medical_writing_artifact_lifecycle_records",
            "art:1",
            "g1",
            {
                "artifact_id": "art:1",
                "project_id": "PRJ-1",
                "generation_id": "g1",
                "document_id": "doc:1",
                "artifact_relpath": "docs/1.docx",
                "identity_json": "{}",
            },
        )
        event = _record(
            "artifact_lineage",
            "sqlite.medical_writing_artifact_lifecycle_events",
            "ev:1",
            "2026-08-12T03:02:00Z",
            {
                "tenant_id": "tenant-1",
                "project_id": "PRJ-1",
                "event_id": "ev:1",
                "artifact_id": "art:1",
                "action": "activate",
                "state_from": "created",
                "state_to": "active",
                "idempotency_key": "idem-event-1",
                "request_hash": "b" * 64,
                "principal_subject": "medical_manager",
                "created_at": "2026-08-12T03:02:00Z",
                "detail_json": "{}",
                "result_json": "{}",
            },
        )
        state = _record(
            "artifact_lineage",
            "sqlite.medical_writing_artifact_lifecycle_state",
            "st:1",
            "r1",
            {},
        )
        report = run_mapping_dry_run([state, event, entry], spec)
        assert report.mapped_count == 2 and report.unmapped_count == 1
        mapped = {
            o.source_type: o
            for o in report.outcomes
            if isinstance(o, MappedOutcome)
        }
        outcome = mapped["sqlite.medical_writing_artifact_lifecycle_records"]
        assert outcome.target_type == "artifact_lineage_node"
        assert outcome.target_id == "v3::artifact_lineage::art:1"
        assert outcome.fields["lineage_ref"] == "{}::docs/1.docx"
        assert outcome.fields["source_revision"] == "g1"
        event_outcome = mapped["sqlite.medical_writing_artifact_lifecycle_events"]
        assert event_outcome.target_id == "legacy::artifact_event::ev:1"
        assert event_outcome.fields["source_revision"] == "2026-08-12T03:02:00Z"
        details = {
            q.quarantine_record.source_type: q.quarantine_record.detail_zh
            for q in report.outcomes
            if isinstance(q, QuarantinedOutcome)
        }
        assert "状态投影" in details["sqlite.medical_writing_artifact_lifecycle_state"]

    def test_every_family_has_mapped_and_declared_quarantine_paths(self) -> None:
        spec = _loaded_spec()
        mapped_by_family: dict[str, int] = {}
        quarantined_by_family: dict[str, int] = {}
        for family, family_spec in spec.families.items():
            rows = []
            for index, type_spec in enumerate(family_spec.types):
                source_id = f"{type_spec.source_type}:{index}"
                payload = _payload_for_type(type_spec, source_id, "PRJ-F", "值")
                rows.append(
                    _row("PRJ-F", family, type_spec.source_type, source_id, "值", payload)
                )
            snapshot = build_inventory(rows)
            report = run_mapping_dry_run(snapshot, spec)
            mapped_by_family[family] = report.mapped_count
            quarantined_by_family[family] = report.unmapped_count
            assert report.source_count == len(rows)
            # every row has exactly one disposition: mapped or quarantined
            assert len(report.outcomes) == report.source_count
        # every family contributes at least one mapped row; every family that
        # declares a quarantine type contributes at least one quarantined row
        # (working_copy_snapshot declares none)
        assert all(count > 0 for count in mapped_by_family.values())
        families_with_quarantine = {
            family
            for family, family_spec in spec.families.items()
            if any(t.outcome == "quarantine" for t in family_spec.types)
        }
        assert families_with_quarantine == {
            "study_definition",
            "journey_stage_draft",
            "corpus_evidence",
            "decision_approval",
            "protocol_document",
            "artifact_lineage",
        }
        assert all(
            quarantined_by_family[family] > 0 for family in families_with_quarantine
        )
        assert quarantined_by_family["working_copy_snapshot"] == 0


# ---------------------------------------------------------------------------
# Fail-closed runtime: undeclared types, missing fields, no fabrication
# ---------------------------------------------------------------------------


class TestFailClosedRuntime:
    def test_undeclared_type_quarantines_without_fabricating_target(self) -> None:
        spec = _loaded_spec()
        for family in sorted(SEVEN_FAMILIES):
            record = _record(family, "undeclared_type_xyz", f"u:{family}", "v1", {"a": 1})
            report = run_mapping_dry_run([record], spec)
            assert report.mapped_count == 0 and report.unmapped_count == 1
            outcome = report.outcomes[0]
            assert isinstance(outcome, QuarantinedOutcome)
            assert outcome.quarantine_record.reason_kinds[0].value == "unsupported_type"
            assert outcome.quarantine_record.payload_sha256 == record.payload_sha256
            assert _is_sha256(outcome.quarantine_record.locator_sha256 or "")

    def test_missing_binding_field_quarantines_incomplete(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "def:2",
            "1",
            {"project_id": "PRJ-1", "revision": 1, "origin": "guided_greenfield"},
            # definition_id missing
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "definition_id" in outcome.quarantine_record.detail_zh
        assert report.lineage_entries == ()

    def test_missing_declared_field_quarantines_incomplete(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "def:2",
            "1",
            {"definition_id": "def:2", "project_id": "PRJ-1", "revision": 1,
             "origin": "guided_greenfield"},  # state_sha256 missing
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "state_sha256" in outcome.quarantine_record.detail_zh

    def test_missing_payload_container_quarantines_incomplete(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "working_copy_snapshot",
            "sqlite.medical_writing_working_copies",
            "wc:1",
            "1",
            {"working_copy_id": "wc:1", "project_id": "PRJ-1", "revision": 1,
             "document_id": "d", "section_id": "S1", "approval_state": "ai_draft"},
            # payload_json missing
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "payload_json" in outcome.quarantine_record.detail_zh

    def test_missing_join_field_quarantines_incomplete(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "artifact_lineage",
            "sqlite.medical_writing_artifact_lifecycle_records",
            "art:2",
            "g1",
            {"artifact_id": "art:2", "project_id": "PRJ-1", "generation_id": "g1",
             "document_id": "d", "artifact_relpath": "x"},  # identity_json missing
        )
        report = run_mapping_dry_run([record], spec)
        assert report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "identity_json" in outcome.quarantine_record.detail_zh

    def test_non_object_payload_quarantines_incomplete(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "def:3",
            "r1",
            ["not", "object"],
        )
        report = run_mapping_dry_run([record], spec)
        assert report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"

    def test_no_silent_drop_and_one_quarantine_per_unmapped(self) -> None:
        spec = _loaded_spec()
        rows = [
            _row("P", "study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
                 {"definition_id": "d:1", "project_id": "P", "revision": 1,
                  "origin": "guided_greenfield", "state_sha256": "a" * 64}),
            _row("P", "study_definition", "ghost_type", "g:1", "v1", {}),
            _row("P", "corpus_evidence", "jsonl.cms_cn_protocol_corpus_20260715_v1", "row:1", "v1",
                 {"index": 1}),
            _row("P", "working_copy_snapshot", "sqlite.medical_writing_working_copies", "w:1", "1",
                 {"working_copy_id": "w:1", "project_id": "P", "revision": 1,
                  "document_id": "d", "section_id": "S1", "approval_state": "ai_draft",
                  "payload_json": {"working_copy_id": "w:1", "content_authority_state": "x"}}),
        ]
        snapshot = build_inventory(rows)
        report = run_mapping_dry_run(snapshot, spec)
        assert report.source_count == 4
        assert report.source_count == report.mapped_count + report.unmapped_count
        assert report.quarantined_count == report.unmapped_count == 2
        assert len(report.quarantine_records) == 2
        assert report.mapped_count == 2
        # every input row has exactly one disposition
        assert len(report.outcomes) == report.source_count

    def test_target_hash_is_computed_from_content(self) -> None:
        spec = _loaded_spec()
        base = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:9", "1",
                       {"definition_id": "d:9", "project_id": "PRJ-1", "revision": 1,
                        "origin": "guided_greenfield", "state_sha256": "a" * 64})
        changed = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:9", "1",
                          {"definition_id": "d:9", "project_id": "PRJ-1", "revision": 1,
                           "origin": "imported_synopsis", "state_sha256": "a" * 64})
        r1 = run_mapping_dry_run([base], spec)
        r2 = run_mapping_dry_run([changed], spec)
        o1, o2 = r1.outcomes[0], r2.outcomes[0]
        assert isinstance(o1, MappedOutcome) and isinstance(o2, MappedOutcome)
        assert o1.target_id == o2.target_id
        assert o1.target_sha256 != o2.target_sha256


# ---------------------------------------------------------------------------
# Determinism and source immutability
# ---------------------------------------------------------------------------


def _mixed_rows(seed: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        _row("PRJ-1", "study_definition", "models.MedicalWritingStudyDefinition", f"d:{i}",
             str(i % 3 + 1),
             {"definition_id": f"d:{i}", "project_id": "PRJ-1", "revision": i % 3 + 1,
              "origin": "guided_greenfield", "state_sha256": f"{i:064x}",
              "synopsis_text": "junk"})
        for i in range(12)
    ]
    rows += [
        _row("PRJ-1", "corpus_evidence", "models.WritingReferenceDocumentArtifact", f"c:{i}",
             "1",
             {"artifact_id": f"c:{i}", "project_id": "PRJ-1", "state_revision": 1,
              "nct_id": f"NCT{i}", "document_type": "protocol",
              "content_sha256": f"{i:064x}", "source_status": "downloaded"})
        for i in range(8)
    ]
    rows += [
        _row("PRJ-1", "artifact_lineage", "sqlite.medical_writing_artifact_lifecycle_records",
             f"e:{i}", "r1",
             {"artifact_id": f"e:{i}", "project_id": "PRJ-1", "generation_id": "r1",
              "document_id": f"doc:{i}", "artifact_relpath": f"docs/{i}.docx",
              "identity_json": "{}"})
        for i in range(6)
    ]
    rows += [
        _row("PRJ-1", "corpus_evidence", "jsonl.cms_cn_protocol_corpus_20260715_v1", f"row:{i}",
             "v1", {"index": i})
        for i in range(4)
    ]
    rows += [
        _row("PRJ-1", "protocol_document", "sqlite.medical_writing_greenfield_documents", f"doc:{i}",
             "1",
             {"document_id": f"doc:{i}", "project_id": "PRJ-1", "baseline_revision": 1,
              "baseline_sha256": f"{i:064x}",
              "payload_json": {"protocol_id": f"P{i}", "version": "V1.0", "status": "draft"}})
        for i in range(5)
    ]
    rows += [
        _row("PRJ-2", "study_definition", "models.MedicalWritingStudyDefinition", "d:0", "1",
             {"definition_id": "d:0", "project_id": "PRJ-2", "revision": 1,
              "origin": "guided_greenfield", "state_sha256": "0" * 64, "synopsis_text": "s"})
    ]
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows


class TestDeterminismAndImmutability:
    def test_permutation_determinism(self) -> None:
        spec = _loaded_spec()
        reports = []
        for seed in (1, 7, 42):
            snapshot = build_inventory(_mixed_rows(seed))
            reports.append(run_mapping_dry_run(snapshot, spec))
        assert [r.run_sha256 for r in reports] == [reports[0].run_sha256] * 3
        assert [r.mapped_count for r in reports] == [reports[0].mapped_count] * 3
        assert [r.quarantined_count for r in reports] == [reports[0].quarantined_count] * 3
        assert reports[0].canonical_payload() == reports[1].canonical_payload() == reports[2].canonical_payload()

    def test_payload_key_order_invariance(self) -> None:
        spec = _loaded_spec()
        a = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
                    {"origin": "guided_greenfield", "state_sha256": "a" * 64,
                     "definition_id": "d:1", "project_id": "PRJ-1", "revision": 1})
        b = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
                    {"state_sha256": "a" * 64, "revision": 1, "project_id": "PRJ-1",
                     "origin": "guided_greenfield", "definition_id": "d:1"})
        assert a.payload_sha256 == b.payload_sha256
        ra = run_mapping_dry_run([a], spec)
        rb = run_mapping_dry_run([b], spec)
        assert ra.run_sha256 == rb.run_sha256

    def test_source_payloads_remain_byte_stable(self) -> None:
        spec = _loaded_spec()
        rows = _mixed_rows(3)
        before = [copy.deepcopy(row) for row in rows]
        snapshot = build_inventory(rows)
        run_mapping_dry_run(snapshot, spec)
        assert rows == before
        for row in rows:
            assert isinstance(row["payload"], dict)
        # also with direct records
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
            {"origin": "guided_greenfield", "state_sha256": "a" * 64,
             "definition_id": "d:1", "project_id": "PRJ-1", "revision": 1,
             "nested": {"k": [1, 2]}},
        )
        payload_before = copy.deepcopy(record.payload)
        report = run_mapping_dry_run([record], spec)
        assert record.payload == payload_before
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        # undeclared payload fields never leak as top-level target fields
        # (no fabricated fields, no implicit passthrough); they are preserved
        # inside the declared whole-payload preservation instead
        assert "nested" not in outcome.fields
        assert outcome.fields["origin"] == "guided_greenfield"
        assert outcome.fields["legacy_payload"]["nested"] == {"k": [1, 2]}

    def test_report_fields_are_frozen_and_source_isolated(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
            {"origin": "guided_greenfield", "state_sha256": "a" * 64,
             "definition_id": "d:1", "project_id": "PRJ-1", "revision": 1},
        )
        report = run_mapping_dry_run([record], spec)
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        with pytest.raises(TypeError):
            outcome.fields["origin"] = "hacked"
        with pytest.raises(TypeError):
            outcome.fields.pop("origin")
        with pytest.raises(TypeError):
            outcome.fields["legacy_payload"]["origin"] = "hacked"  # type: ignore[index]
        with pytest.raises(TypeError):
            report.counts_by_reason["unsupported_type"] = 99
        with pytest.raises(TypeError):
            report.counts_by_reason.pop("unsupported_type")
        with pytest.raises((TypeError, ValidationError)):
            report.mapping_version = "hacked"  # type: ignore[misc]
        # mutating the report never affects the source record
        assert record.payload["origin"] == "guided_greenfield"

    def test_report_self_validates_accounting(self) -> None:
        spec = _loaded_spec()
        snapshot = build_inventory(_mixed_rows(9))
        report = run_mapping_dry_run(snapshot, spec)
        assert report.schema_version == "mw_v2_v3_dry_run_v1"
        assert DRY_RUN_SCHEMA_VERSION == "mw_v2_v3_dry_run_v1"
        assert report.mapping_version == spec.mapping_version
        assert report.source_count == report.mapped_count + report.unmapped_count
        assert report.quarantined_count == report.unmapped_count
        assert len(report.outcomes) == report.source_count
        assert _is_sha256(report.run_sha256)
        with pytest.raises(ValidationError):
            DryRunReport(
                mapping_version=spec.mapping_version,
                source_count=2,
                mapped_count=1,
                unmapped_count=2,
                quarantined_count=2,
                replayed_count=0,
            )
        with pytest.raises(ValidationError):
            DryRunReport(
                mapping_version=spec.mapping_version,
                source_count=1,
                mapped_count=1,
                unmapped_count=0,
                quarantined_count=0,
                replayed_count=1,
                outcomes=(report.outcomes[0],),
            )

    def test_cross_project_isolation(self) -> None:
        spec = _loaded_spec()
        a = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
                    {"definition_id": "d:1", "project_id": "PRJ-A", "revision": 1,
                     "origin": "guided_greenfield", "state_sha256": "a" * 64},
                    project_id="PRJ-A")
        b = _record("study_definition", "models.MedicalWritingStudyDefinition", "d:1", "1",
                    {"definition_id": "d:1", "project_id": "PRJ-B", "revision": 1,
                     "origin": "guided_greenfield", "state_sha256": "b" * 64},
                    project_id="PRJ-B")
        report = run_mapping_dry_run([a, b], spec)
        assert report.mapped_count == 2
        outcomes = [o for o in report.outcomes if isinstance(o, MappedOutcome)]
        assert outcomes[0].target_id == outcomes[1].target_id  # same source id
        assert outcomes[0].lineage_id != outcomes[1].lineage_id  # project-bound
        assert [o.project_id for o in outcomes] == ["PRJ-A", "PRJ-B"]


# ---------------------------------------------------------------------------
# Real source identity binding: wrong identity/project/revision fail closed
# ---------------------------------------------------------------------------


class TestIdentityBinding:
    def test_codex_counterexample_wrong_id_project_revision_fails_closed(self) -> None:
        # Exact reproduced counterexample: envelope WRONG-ID / WRONG-PROJECT /
        # token 1 against a payload declaring ACTUAL-ID / ACTUAL-PROJECT /
        # revision 999 with real extra fields (framing, picos, timestamps).
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "WRONG-ID",
            "1",
            {
                "definition_id": "ACTUAL-ID",
                "project_id": "ACTUAL-PROJECT",
                "revision": 999,
                "origin": "guided_greenfield",
                "state_sha256": "a" * 64,
                "framing": {"document_title": "真实研究"},
                "picos": {"design_archetype": "randomized_confirmatory"},
                "created_at": "2026-01-01",
                "updated_at": "2026-01-02",
                "updated_by": "医学经理",
            },
            project_id="WRONG-PROJECT",
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0
        assert report.unmapped_count == 1
        assert report.lineage_entries == ()  # no lineage entry under a wrong identity
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        detail = outcome.quarantine_record.detail_zh
        assert "ACTUAL-ID" in detail and "WRONG-ID" in detail
        assert "ACTUAL-PROJECT" in detail and "WRONG-PROJECT" in detail
        assert "999" in detail and "'1'" in detail
        # the real payload hash is preserved on the quarantine record
        assert outcome.quarantine_record.payload_sha256 == record.payload_sha256

    def test_wrong_project_only_fails_closed(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "1",
            {"definition_id": "def:1", "project_id": "OTHER-PROJECT", "revision": 1,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
            project_id="PRJ-1",
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "项目作用域" in outcome.quarantine_record.detail_zh
        assert report.lineage_entries == ()

    def test_wrong_revision_only_fails_closed(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "1",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": 999,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert "来源修订" in outcome.quarantine_record.detail_zh
        assert report.lineage_entries == ()

    def test_valid_exact_binding_maps_with_real_identity(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "1",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": 1,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 1 and report.unmapped_count == 0
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        # target identity derives from the bound real identity
        assert outcome.target_id == "v3::study_definition::def:1"
        assert len(report.lineage_entries) == 1

    def test_int_and_str_revision_normalize_identically(self) -> None:
        spec = _loaded_spec()
        as_int = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "999",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": 999,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        as_str = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "999",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": "999",
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        assert run_mapping_dry_run([as_int], spec).mapped_count == 1
        assert run_mapping_dry_run([as_str], spec).mapped_count == 1

    def test_unsupported_identity_value_fails_closed(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", "def:1", "1",
            {"definition_id": {"nested": "not-a-scalar"}, "project_id": "PRJ-1",
             "revision": 1, "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 0 and report.unmapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "incomplete_record"
        assert "值类型不支持" in outcome.quarantine_record.detail_zh

    def test_composite_identity_uses_canonical_ordered_encoding(self) -> None:
        # A composite identity must use an unambiguous ordered encoding: the
        # canonical JSON array of the normalized scalars.  Swapping the order
        # changes the identity and fails the binding.
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["source_contract"]["identity_fields"] = ["project_id", "definition_id"]
        spec = parse_mapping_spec(raw)
        canonical = canonical_json(["PRJ-1", "def:1"])
        correct = _record(
            "study_definition", "models.MedicalWritingStudyDefinition", canonical, "1",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": 1,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        swapped = _record(
            "study_definition", "models.MedicalWritingStudyDefinition",
            canonical_json(["def:1", "PRJ-1"]), "1",
            {"definition_id": "def:1", "project_id": "PRJ-1", "revision": 1,
             "origin": "guided_greenfield", "state_sha256": "a" * 64},
        )
        ok = run_mapping_dry_run([correct], spec)
        assert ok.mapped_count == 1
        outcome = ok.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        assert outcome.target_id == "v3::study_definition::" + canonical
        bad = run_mapping_dry_run([swapped], spec)
        assert bad.mapped_count == 0 and bad.unmapped_count == 1
        assert bad.lineage_entries == ()

    def test_project_scope_prevents_lineage_collapse(self) -> None:
        # Target identity is project-scoped: lineage keys embed the project,
        # so two projects with the same source id can never collapse into the
        # same migration key or lineage (target storage is project-scoped,
        # which prevents equal target_id values in different projects from
        # colliding).
        spec = _loaded_spec()
        a = run_mapping_dry_run(
            build_inventory([_definition_row("PRJ-A", "d:1", "1")]), spec
        )
        b = run_mapping_dry_run(
            build_inventory([_definition_row("PRJ-B", "d:1", "1")]), spec
        )
        ea, eb = a.lineage_entries[0], b.lineage_entries[0]
        assert ea.target_id == eb.target_id  # same source id, same target id
        assert ea.lineage_key[0] == "PRJ-A" and eb.lineage_key[0] == "PRJ-B"
        assert ea.lineage_key != eb.lineage_key
        assert ea.lineage_id != eb.lineage_id
        assert a.run_sha256 != b.run_sha256


# ---------------------------------------------------------------------------
# Idempotent lineage: replay, conflict, changed-revision child
# ---------------------------------------------------------------------------


class TestIdempotentLineage:
    def test_exact_replay_returns_identical_identity_no_extra_effect(self) -> None:
        spec = _loaded_spec()
        rows = [_definition_row("PRJ-1", "d:1", "r1")]
        snapshot = build_inventory(rows)
        first = run_mapping_dry_run(snapshot, spec)
        assert first.replayed_count == 0
        assert len(first.lineage_entries) == 1
        replay = run_mapping_dry_run(snapshot, spec, prior_lineage=first.lineage_entries)
        assert replay.replayed_count == 1
        assert len(replay.lineage_entries) == 1  # no new lineage node
        o1 = first.outcomes[0]
        o2 = replay.outcomes[0]
        assert isinstance(o1, MappedOutcome) and isinstance(o2, MappedOutcome)
        assert o2.replayed is True
        assert o2.target_type == o1.target_type
        assert o2.target_id == o1.target_id
        assert o2.target_sha256 == o1.target_sha256
        assert o2.lineage_id == o1.lineage_id
        assert o2.parent_lineage_id == o1.parent_lineage_id
        assert replay.lineage_entries[0].lineage_id == first.lineage_entries[0].lineage_id
        # same inputs (records + spec + prior) -> identical run hash
        replay_again = run_mapping_dry_run(snapshot, spec, prior_lineage=first.lineage_entries)
        assert replay_again.run_sha256 == replay.run_sha256

    def test_replay_works_for_whole_mixed_batch(self) -> None:
        spec = _loaded_spec()
        snapshot = build_inventory(_mixed_rows(5))
        first = run_mapping_dry_run(snapshot, spec)
        replay = run_mapping_dry_run(snapshot, spec, prior_lineage=first.lineage_entries)
        assert replay.replayed_count == first.mapped_count
        assert replay.mapped_count == first.mapped_count
        assert replay.quarantined_count == first.quarantined_count
        assert [e.lineage_id for e in replay.lineage_entries] == [
            e.lineage_id for e in first.lineage_entries
        ]
        for o in replay.outcomes:
            if isinstance(o, MappedOutcome):
                assert o.replayed is True

    def test_conflicting_replay_fails_closed(self) -> None:
        spec = _loaded_spec()
        first_rows = [_definition_row("PRJ-1", "d:1", "r1", origin="guided_greenfield")]
        first = run_mapping_dry_run(build_inventory(first_rows), spec)
        prior_entry = first.lineage_entries[0]

        conflict_rows = [_definition_row("PRJ-1", "d:1", "r1", origin="imported_synopsis")]
        conflict = run_mapping_dry_run(build_inventory(conflict_rows), spec,
                                       prior_lineage=first.lineage_entries)
        assert conflict.mapped_count == 0 and conflict.unmapped_count == 1
        outcome = conflict.outcomes[0]
        assert isinstance(outcome, QuarantinedOutcome)
        assert outcome.quarantine_record.reason_kinds[0].value == "duplicate_conflict"
        assert outcome.quarantine_record.payload_sha256 != prior_entry.payload_sha256
        # prior entry untouched, no new lineage node
        assert [e.lineage_id for e in conflict.lineage_entries] == [prior_entry.lineage_id]
        assert conflict.lineage_entries[0].target_sha256 == prior_entry.target_sha256

    def test_changed_revision_creates_child_pointing_at_prior(self) -> None:
        spec = _loaded_spec()
        rev1_rows = [_definition_row("PRJ-1", "d:1", "r1")]
        rev1 = run_mapping_dry_run(build_inventory(rev1_rows), spec)
        e1 = rev1.lineage_entries[0]
        assert e1.parent_lineage_id is None

        rev2_rows = [_definition_row("PRJ-1", "d:1", "r2")]
        rev2 = run_mapping_dry_run(build_inventory(rev2_rows), spec,
                                   prior_lineage=rev1.lineage_entries)
        assert rev2.mapped_count == 1 and rev2.replayed_count == 0
        assert len(rev2.lineage_entries) == 2
        carried, child = rev2.lineage_entries
        # the prior result is never overwritten
        assert carried.lineage_id == e1.lineage_id
        assert carried.target_sha256 == e1.target_sha256
        assert carried.parent_lineage_id is None
        # the child points at the prior result
        assert child.parent_lineage_id == e1.lineage_id
        assert child.revision_token == "r2"
        assert child.lineage_id != e1.lineage_id
        # same logical target identity across revisions
        assert child.target_id == e1.target_id
        assert child.target_sha256 != e1.target_sha256

    def test_revision_only_change_still_new_child_never_overwrite(self) -> None:
        spec = _loaded_spec()

        def payload_for(revision: str) -> dict[str, object]:
            return {
                "definition_id": "d:1",
                "project_id": "P",
                "revision": revision,
                "origin": "guided_greenfield",
                "state_sha256": "a" * 64,
            }

        r1 = run_mapping_dry_run(
            build_inventory([_row("P", "study_definition",
                                  "models.MedicalWritingStudyDefinition",
                                  "d:1", "r1", payload_for("r1"))]),
            spec,
        )
        r2 = run_mapping_dry_run(
            build_inventory([_row("P", "study_definition",
                                  "models.MedicalWritingStudyDefinition",
                                  "d:1", "r2", payload_for("r2"))]),
            spec,
            prior_lineage=r1.lineage_entries,
        )
        e1, e2 = r2.lineage_entries
        # the real revision is part of the payload, so the payload hash
        # changes with the revision — and a changed revision is still a new
        # child, never a replay and never an overwrite
        assert e1.lineage_id != e2.lineage_id
        assert e1.revision_token == "r1" and e2.revision_token == "r2"
        assert e1.payload_sha256 != e2.payload_sha256
        assert e1.target_id == e2.target_id
        assert e2.parent_lineage_id == e1.lineage_id

    def test_three_revision_chain_and_full_replay(self) -> None:
        spec = _loaded_spec()
        rows = [
            _definition_row("PRJ-1", "d:1", "r1"),
            _definition_row("PRJ-1", "d:1", "r2"),
            _definition_row("PRJ-1", "d:1", "r3"),
        ]
        chain = run_mapping_dry_run(build_inventory(rows), spec)
        assert chain.mapped_count == 3 and chain.replayed_count == 0
        entries = chain.lineage_entries
        ids = [e.lineage_id for e in entries]
        assert len(set(ids)) == 3
        assert [e.parent_lineage_id for e in entries] == [None, ids[0], ids[1]]

        # replay the whole chain: identical lineage, no extra semantic effect
        replay = run_mapping_dry_run(build_inventory(rows), spec,
                                     prior_lineage=chain.lineage_entries)
        assert replay.replayed_count == 3
        assert [e.lineage_id for e in replay.lineage_entries] == ids
        for o in replay.outcomes:
            assert isinstance(o, MappedOutcome) and o.replayed

    def test_lineage_version_mismatch_rejected(self) -> None:
        spec = _loaded_spec()
        foreign = MappingLineageEntry(
            mapping_version="different-mapping-version",
            migration_key=("P", "study_definition", "models.MedicalWritingStudyDefinition", "d:1"),
            revision_token="r1",
            payload_sha256="0" * 64,
            target_type="x",
            target_id="y",
            target_sha256="1" * 64,
        )
        with pytest.raises(MappingLineageError):
            run_mapping_dry_run(
                build_inventory([_definition_row("P", "d:1", "r1")]),
                spec,
                prior_lineage=[foreign],
            )

    def test_duplicate_prior_lineage_rejected(self) -> None:
        spec = _loaded_spec()
        entry = MappingLineageEntry(
            mapping_version=spec.mapping_version,
            migration_key=("P", "study_definition", "models.MedicalWritingStudyDefinition", "d:1"),
            revision_token="r1",
            payload_sha256="2" * 64,
            target_type="study_definition_node",
            target_id="v3::study_definition::d:1",
            target_sha256="3" * 64,
        )
        with pytest.raises(MappingLineageError):
            run_mapping_dry_run([], spec, prior_lineage=[entry, entry])

    def test_lineage_ids_are_content_bound(self) -> None:
        spec = _loaded_spec()
        a = run_mapping_dry_run(
            build_inventory([_definition_row("PRJ-A", "d:1", "r1")]), spec
        )
        b = run_mapping_dry_run(
            build_inventory([_definition_row("PRJ-B", "d:1", "r1")]), spec
        )
        assert a.lineage_entries[0].lineage_id != b.lineage_entries[0].lineage_id
        assert LINEAGE_SCHEMA_VERSION == "mw_v2_v3_lineage_v1"
        assert _is_sha256(a.lineage_entries[0].lineage_id)
        assert _is_sha256(a.lineage_entries[0].target_sha256)


# ---------------------------------------------------------------------------
# Synthetic 3,878-row company-corpus denominator
# ---------------------------------------------------------------------------

CORPUS_TOTAL = 3878
CORPUS_EXPECTED_MAPPED = 3418
CORPUS_EXPECTED_UNMAPPED = 460


def _build_3878_corpus() -> list[dict[str, object]]:
    """Synthetic 3,878-row denominator covering all seven families.

    The 460 unmappable rows are exactly the spec-declared quarantine types
    (200 company-corpus rows, tenant-global corpus objects, nested stage
    drafts, schema snapshots, audit-only rows and state projections); nothing
    is dropped or fabricated. Every mapped row carries
    a payload whose identity/project/revision fields bind exactly to the
    record envelope.
    """
    rows: list[dict[str, object]] = []

    def add(
        family: str,
        source_type: str,
        count: int,
        payload_factory,
        revision_factory=None,
    ) -> None:
        for i in range(count):
            source_id = f"{source_type}:{i:05d}"
            revision = (
                revision_factory(i) if revision_factory is not None else f"v{i % 7 + 1}"
            )
            rows.append(
                _row(
                    "CORPUS-PRJ",
                    family,
                    source_type,
                    source_id,
                    revision,
                    payload_factory(i, source_id, revision),
                )
            )

    add("study_definition", "models.MedicalWritingStudyDefinition", 300,
        lambda i, sid, rev: {"definition_id": sid, "project_id": "CORPUS-PRJ",
                             "revision": rev, "origin": "guided_greenfield",
                             "state_sha256": f"{i:064x}", "synopsis_text": "正文"},
        revision_factory=lambda i: str(i % 7 + 1))
    add("study_definition", "models.MedicalWritingStudySchemaSnapshot", 5,
        lambda i, sid, rev: {})
    add("journey_stage_draft", "models.MedicalWritingAuthoringJourney", 120,
        lambda i, sid, rev: {"journey_id": sid, "project_id": "CORPUS-PRJ",
                             "revision": rev, "status": "stage1_in_progress",
                             "current_stage": "framing", "entry_mode": "guided_greenfield",
                             "framing_complete": False, "picos_complete": False},
        revision_factory=lambda i: str(i % 7 + 1))
    add("journey_stage_draft", "models.MedicalWritingAuthoringStageDraft", 100,
        lambda i, sid, rev: {})
    add("journey_stage_draft",
        "sqlite.medical_writing_authoring_journey_generation_reservations", 10,
        lambda i, sid, rev: {})
    add("working_copy_snapshot", "sqlite.medical_writing_working_copies", 300,
        lambda i, sid, rev: {"working_copy_id": sid, "project_id": "CORPUS-PRJ",
                             "revision": rev, "document_id": f"doc:{i}",
                             "section_id": "S1", "approval_state": "ai_draft",
                             "payload_json": {"working_copy_id": sid,
                                              "document_id": f"doc:{i}",
                                              "content_authority_state": "historical_quarantined"}},
        revision_factory=lambda i: str(i % 7 + 1))
    add("working_copy_snapshot", "sqlite.medical_writing_working_copy_snapshots", 100,
        lambda i, sid, rev: {"snapshot_id": sid, "project_id": "CORPUS-PRJ",
                             "revision": rev, "snapshot_type": "save",
                             "working_copy_id": f"wc:{i}",
                             "payload_json": {"working_copy_id": f"wc:{i}",
                                              "content_authority_state": "historical_quarantined"}},
        revision_factory=lambda i: str(i % 7 + 1))
    add("corpus_evidence", "models.WritingReferenceDocumentArtifact", 150,
        lambda i, sid, rev: {"artifact_id": sid, "project_id": "CORPUS-PRJ",
                             "state_revision": rev, "nct_id": f"NCT{i:05d}",
                             "document_type": "protocol",
                             "content_sha256": f"{i:064x}",
                             "source_status": "downloaded"},
        revision_factory=lambda i: str(i % 7 + 1))
    add("corpus_evidence", "models.MedicalWritingCorpusSnapshotDefinition", 30,
        lambda i, sid, rev: {})
    add("corpus_evidence", "models.MedicalWritingSharedCorpusCandidate", 50,
        lambda i, sid, rev: {})
    add("corpus_evidence", "jsonl.cms_cn_protocol_corpus_20260715_v1", 200,
        lambda i, sid, rev: {"index": i})
    add("decision_approval", "sqlite.writing_reference_extraction_review_records", 150,
        lambda i, sid, rev: {"review_id": sid, "project_id": "CORPUS-PRJ",
                             "revision": rev, "artifact_id": f"art:{i}",
                             "extraction_revision": "e1", "decision": "approved",
                             "payload_json": {"review_id": sid,
                                              "project_id": "CORPUS-PRJ",
                                              "artifact_id": f"art:{i}",
                                              "extraction_revision": "e1",
                                              "decision": "approved",
                                              "actor": "医学经理",
                                              "comment": "同意",
                                              "revision": rev}},
        revision_factory=lambda i: str(i % 7 + 1))
    add("decision_approval", "sqlite.approval_gates", 200,
        lambda i, sid, rev: {"tenant_id": "tenant-1", "project_id": "CORPUS-PRJ",
                             "approval_id": sid, "updated_at": rev,
                             "payload_json": {"approval_id": sid,
                                              "project_id": "CORPUS-PRJ",
                                              "target_type": "protocol_document",
                                              "target_id": f"doc:{i:05d}",
                                              "state": "pending",
                                              "display_title": "方案审批"}},
        revision_factory=lambda i: f"2026-08-12T03:{i % 60:02d}:00Z")
    add("decision_approval", "sqlite.approval_decisions", 150,
        lambda i, sid, rev: {"tenant_id": "tenant-1", "project_id": "CORPUS-PRJ",
                             "decision_id": sid, "approval_id": f"ag:{i:05d}",
                             "created_at": rev,
                             "payload_json": {"decision_id": sid,
                                              "approval_id": f"ag:{i:05d}",
                                              "project_id": "CORPUS-PRJ",
                                              "action": "approve",
                                              "actor": "医学经理",
                                              "previous_state": "pending",
                                              "new_state": "approved"}},
        revision_factory=lambda i: f"2026-08-12T04:{i % 60:02d}:00Z")
    add("decision_approval", "sqlite.approval_audit_events", 15, lambda i, sid, rev: {})
    add("protocol_document", "sqlite.medical_writing_greenfield_documents", 400,
        lambda i, sid, rev: {"document_id": sid, "project_id": "CORPUS-PRJ",
                             "baseline_revision": rev, "baseline_sha256": f"{i:064x}",
                             "payload_json": {"protocol_id": f"P{i:05d}",
                                              "version": "V1.0", "status": "draft"}},
        revision_factory=lambda i: str(i % 7 + 1))
    add("protocol_document", "sqlite.medical_writing_greenfield_events", 20,
        lambda i, sid, rev: {})
    add("artifact_lineage", "sqlite.medical_writing_artifact_lifecycle_records", 1248,
        lambda i, sid, rev: {"artifact_id": sid, "project_id": "CORPUS-PRJ",
                             "generation_id": rev, "document_id": f"doc:{i:05d}",
                             "artifact_relpath": f"docs/{i:05d}.docx",
                             "identity_json": "{}"},
        revision_factory=lambda i: f"v{i % 7 + 1}")
    add("artifact_lineage", "sqlite.medical_writing_artifact_lifecycle_events", 300,
        lambda i, sid, rev: {"tenant_id": "tenant-1", "project_id": "CORPUS-PRJ",
                             "event_id": sid, "artifact_id": f"art:{i:05d}",
                             "action": "activate", "state_from": "created",
                             "state_to": "active", "idempotency_key": f"idem:{i:05d}",
                             "request_hash": f"{i:064x}",
                             "principal_subject": "medical_manager",
                             "created_at": rev, "detail_json": "{}", "result_json": "{}"},
        revision_factory=lambda i: f"2026-08-12T05:{i % 60:02d}:00Z")
    add("artifact_lineage", "sqlite.medical_writing_artifact_lifecycle_state", 30,
        lambda i, sid, rev: {})
    assert len(rows) == CORPUS_TOTAL
    return rows


class TestSyntheticCorpusDenominator:
    def test_3878_rows_exact_accounting(self) -> None:
        spec = _loaded_spec()
        rows = _build_3878_corpus()
        snapshot = build_inventory(rows)
        assert snapshot.source_count == CORPUS_TOTAL
        assert snapshot.record_count == CORPUS_TOTAL  # no duplicates in corpus
        assert snapshot.quarantined_count == 0
        report = run_mapping_dry_run(snapshot, spec)
        assert report.source_count == CORPUS_TOTAL
        assert report.mapped_count == CORPUS_EXPECTED_MAPPED
        assert report.unmapped_count == CORPUS_EXPECTED_UNMAPPED
        assert report.quarantined_count == CORPUS_EXPECTED_UNMAPPED
        assert report.source_count == report.mapped_count + report.unmapped_count
        assert len(report.quarantine_records) == CORPUS_EXPECTED_UNMAPPED
        assert len(report.outcomes) == CORPUS_TOTAL

    def test_3878_corpus_rows_quarantined_with_declared_detail(self) -> None:
        spec = _loaded_spec()
        report = run_mapping_dry_run(build_inventory(_build_3878_corpus()), spec)
        corpus_records = [
            q.quarantine_record
            for q in report.outcomes
            if isinstance(q, QuarantinedOutcome)
            and q.quarantine_record.source_type == "jsonl.cms_cn_protocol_corpus_20260715_v1"
        ]
        assert len(corpus_records) == 200
        for record in corpus_records:
            assert record.reason_kinds[0].value == "unsupported_type"
            assert "3,878" in record.detail_zh
            assert _is_sha256(record.payload_sha256 or "")
            assert _is_sha256(record.locator_sha256 or "")
        # every unmapped row carries the spec-declared quarantine detail
        for q in report.outcomes:
            if isinstance(q, QuarantinedOutcome):
                assert q.quarantine_record.detail_zh

    def test_3878_all_seven_families_represented(self) -> None:
        spec = _loaded_spec()
        report = run_mapping_dry_run(build_inventory(_build_3878_corpus()), spec)
        mapped_families = {
            o.source_family for o in report.outcomes if isinstance(o, MappedOutcome)
        }
        assert mapped_families == SEVEN_FAMILIES
        # every family that declares a quarantine type contributes quarantined
        # rows; working_copy_snapshot declares none
        unmapped_families = {
            q.quarantine_record.source_family
            for q in report.outcomes
            if isinstance(q, QuarantinedOutcome)
        }
        assert unmapped_families == {
            "study_definition",
            "journey_stage_draft",
            "corpus_evidence",
            "decision_approval",
            "protocol_document",
            "artifact_lineage",
        }

    def test_3878_deterministic_and_replayable(self) -> None:
        spec = _loaded_spec()
        rows = _build_3878_corpus()
        forward = run_mapping_dry_run(build_inventory(rows), spec)
        reversed_snapshot = build_inventory(list(reversed(rows)))
        backward = run_mapping_dry_run(reversed_snapshot, spec)
        assert backward.run_sha256 == forward.run_sha256
        assert backward.canonical_payload() == forward.canonical_payload()
        # replaying the corpus is an exact replay with zero extra effects
        replay = run_mapping_dry_run(
            reversed_snapshot, spec, prior_lineage=forward.lineage_entries
        )
        assert replay.replayed_count == CORPUS_EXPECTED_MAPPED
        assert len(replay.lineage_entries) == CORPUS_EXPECTED_MAPPED
        assert [e.lineage_id for e in replay.lineage_entries] == [
            e.lineage_id for e in forward.lineage_entries
        ]

    def test_3878_run_hash_changes_when_any_row_changes(self) -> None:
        spec = _loaded_spec()
        rows = _build_3878_corpus()
        base = run_mapping_dry_run(build_inventory(rows), spec)
        rows[0] = _row(
            "CORPUS-PRJ", "study_definition", "models.MedicalWritingStudyDefinition",
            "models.MedicalWritingStudyDefinition:00000",
            "v9", {"definition_id": "models.MedicalWritingStudyDefinition:00000",
                   "project_id": "CORPUS-PRJ", "revision": "v9",
                   "origin": "guided_greenfield", "state_sha256": "9" * 64,
                   "synopsis_text": "改动"},
        )
        changed = run_mapping_dry_run(build_inventory(rows), spec)
        assert changed.run_sha256 != base.run_sha256

    def test_3878_no_fabricated_semantic_node(self) -> None:
        spec = _loaded_spec()
        report = run_mapping_dry_run(build_inventory(_build_3878_corpus()), spec)
        target_types = {
            o.target_type for o in report.outcomes if isinstance(o, MappedOutcome)
        }
        declared_target_types = {
            t.target_type
            for family in spec.families.values()
            for t in family.types
            if t.target_type is not None
        }
        assert target_types <= declared_target_types
        for q in report.outcomes:
            if isinstance(q, QuarantinedOutcome):
                assert q.quarantine_record.reason_kinds[0].value == "unsupported_type"


# ---------------------------------------------------------------------------
# P1: every production source type resolves to a real checked-in contract
# ---------------------------------------------------------------------------


class TestContractBinding:
    def test_all_production_source_types_resolve(self) -> None:
        spec = _loaded_spec()
        verification = verify_mapping_spec_contracts(spec)
        assert isinstance(verification, MappingContractVerification)
        assert verification.verified, [
            (i.family, i.source_type, i.message) for i in verification.issues
        ]
        assert verification.spec_sha256 == spec.spec_sha256
        # pinned checked-in spec hash (config is read-only for this task)
        assert (
            spec.spec_sha256
            == "34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2"
        )
        assert CONTRACT_VERIFICATION_SCHEMA_VERSION == "mw_v2_v3_contract_verification_v1"
        assert verification.schema_version == CONTRACT_VERIFICATION_SCHEMA_VERSION
        assert verification.source_type_count == 20
        assert len(verification.verified_types) == 20
        assert len(set(verification.verified_types)) == 20
        # all three source kinds are exercised
        kinds = {
            t.source_contract.kind
            for family in spec.families.values()
            for t in family.types
        }
        assert kinds == {"pydantic_model", "sqlite_table", "jsonl_snapshot"}
        # every family has at least one mapped type with full binding
        for family_spec in spec.families.values():
            mapped = [t for t in family_spec.types if t.outcome != "quarantine"]
            assert mapped, family_spec.family_label_zh
            for type_spec in mapped:
                contract = type_spec.source_contract
                assert contract.identity_fields
                assert contract.project_scope_fields
                assert contract.revision_fields

    def test_drift_renamed_model_field_fails(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        rule = next(r for r in definition["field_rules"] if r["source_field"] == "origin")
        rule["source_field"] = "originn"
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("originn" in i.message for i in verification.issues)

    def test_drift_renamed_model_symbol_fails(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["source_contract"]["symbol"] = "MedicalWritingStudyDefinitionX"
        definition["source_type"] = "models.MedicalWritingStudyDefinitionX"
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("MedicalWritingStudyDefinitionX" in i.message for i in verification.issues)

    def test_drift_renamed_payload_model_symbol_fails(self) -> None:
        raw = _raw_spec()
        review = next(
            t
            for t in raw["families"]["decision_approval"]["types"]
            if t["source_type"] == "sqlite.writing_reference_extraction_review_records"
        )
        review["source_contract"]["payload_model"] = "WritingReferenceExtractionReviewDecisionX"
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("WritingReferenceExtractionReviewDecisionX" in i.message for i in verification.issues)

    def test_drift_renamed_table_fails(self) -> None:
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        working_copies["source_contract"]["table"] = "medical_writing_working_copyz"
        working_copies["source_type"] = "sqlite.medical_writing_working_copyz"
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("medical_writing_working_copyz" in i.message for i in verification.issues)

    def test_drift_renamed_column_fails(self) -> None:
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        working_copies["source_contract"]["identity_fields"] = ["working_copy_idz"]
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("working_copy_idz" in i.message for i in verification.issues)

    def test_drift_renamed_source_file_fails(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["source_contract"]["source_file"] = (
            "packages/contracts/workbench_contracts/models_missing.py"
        )
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("models_missing.py" in i.message for i in verification.issues)

    def test_no_toy_alias_source_types_in_shipped_spec(self) -> None:
        spec = _loaded_spec()
        for family_spec in spec.families.values():
            for type_spec in family_spec.types:
                # source_type is the mechanically derived identifier of the
                # declared contract — never a generic toy alias
                assert type_spec.source_type == type_spec.source_contract.derived_source_type
                assert type_spec.source_type.startswith(("models.", "sqlite.", "jsonl."))
        with open(SPEC_PATH, encoding="utf-8") as handle:
            text = handle.read()
        for toy in (
            '"definition"',
            '"legacy_draft"',
            '"stage_draft"',
            '"curated_source"',
            '"decision_record"',
            '"approver"',
            '"stage_key"',
            '"document_title"',
            '"internal_notes"',
            '"seed_scratchpad"',
            '"obsolete_definition"',
            '"expired_draft"',
            '"orphan_artifact"',
            '"superseded_document"',
            '"unregistered_evidence"',
            '"lineage_entry"',
            '"title"',
            '"payload_field"',
        ):
            assert toy not in text, f"toy alias {toy} still present in shipped spec"

    def test_seven_family_coverage_at_contract_level(self) -> None:
        spec = _loaded_spec()
        assert set(spec.families) == SEVEN_FAMILIES
        all_source_types = [
            t.source_type
            for family_spec in spec.families.values()
            for t in family_spec.types
        ]
        assert len(all_source_types) == len(set(all_source_types))
        for family_spec in spec.families.values():
            for type_spec in family_spec.types:
                contract = type_spec.source_contract
                assert contract.source_file
                assert contract.identity_fields
                assert type_spec.source_contract.kind in {
                    "pydantic_model",
                    "sqlite_table",
                    "jsonl_snapshot",
                }

    def test_verifier_is_pure_and_imports_no_live_store(self) -> None:
        before = set(sys.modules)
        spec = _loaded_spec()
        verification = verify_mapping_spec_contracts(spec)
        assert verification.verified
        newly_loaded = set(sys.modules) - before
        assert not any(name.startswith("app.") for name in newly_loaded), sorted(
            name for name in newly_loaded if name.startswith("app.")
        )
        assert not any("sqlite_runtime_store" in name for name in newly_loaded)
        assert not any("medical_writing_authoring_journey" in name for name in newly_loaded)
        assert not any("medical_writing_company_corpus" in name for name in newly_loaded)
        assert not any("writing_reference_repository" in name for name in newly_loaded)
        assert not any(name == "sqlite3" or name.startswith("sqlite3.") for name in newly_loaded)
        # pydantic checks run against the pure contracts package only
        assert "packages.contracts.workbench_contracts.models" in sys.modules
        # Purity is an import-delta property. The complete suite legitimately
        # loads unrelated app modules before this test; they cannot be treated
        # as imports performed by this verifier.
        assert not any(
            name.startswith("app.") and "protocol_workflow" not in name
            for name in newly_loaded
        )


# ---------------------------------------------------------------------------
# P1: exhaustive field disposition (no silent field loss)
# ---------------------------------------------------------------------------


class TestExhaustiveDisposition:
    def test_undispositioned_model_field_fails_when_preservation_removed(self) -> None:
        # Removing the whole-payload preservation from a copied spec leaves
        # real model fields (framing, picos, timestamps, …) undispositioned —
        # the read-only verifier must reject that as a silent drop.
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        definition["field_rules"] = [
            rule for rule in definition["field_rules"]
            if rule.get("kind") != "whole_payload"
        ]
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        messages = [i.message for i in verification.issues]
        assert any("未处置" in message for message in messages)
        assert any("framing" in message for message in messages)
        assert any("picos" in message for message in messages)

    def test_extra_ddl_column_not_dispositioned_fails(self, monkeypatch) -> None:
        # An added real DDL column that no rule/role covers must fail the
        # verifier (safe monkeypatch of the read-only DDL source; v2 source
        # files are never edited).
        real_read = migration_map_module._read_source_text

        def fake_read(source_file: str):
            text = real_read(source_file)
            if source_file == "services/api/app/sqlite_runtime_store.py":
                text = text.replace(
                    "updated_at TEXT NOT NULL,\n                payload_json TEXT NOT NULL,\n                PRIMARY KEY (tenant_id, project_id, working_copy_id)",
                    "updated_at TEXT NOT NULL,\n                extra_column TEXT NOT NULL,\n                payload_json TEXT NOT NULL,\n                PRIMARY KEY (tenant_id, project_id, working_copy_id)",
                )
            return text

        monkeypatch.setattr(migration_map_module, "_read_source_text", fake_read)
        spec = _loaded_spec()
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        messages = [i.message for i in verification.issues]
        assert any("extra_column" in message and "未处置" in message for message in messages)

    def test_declared_covered_field_must_exist(self) -> None:
        # A rule that names a field the contract does not have must fail —
        # both directions of the drift contract are enforced.
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        rule = next(
            r for r in working_copies["field_rules"]
            if r.get("source_field") == "document_id"
        )
        rule["source_field"] = "document_idz"
        spec = parse_mapping_spec(raw)
        verification = verify_mapping_spec_contracts(spec)
        assert not verification.verified
        assert any("document_idz" in i.message for i in verification.issues)

    def test_whole_payload_lists_exact_checked_in_model_fields(self) -> None:
        spec = _loaded_spec()
        for family_spec in spec.families.values():
            for type_spec in family_spec.types:
                whole_rules = [
                    rule
                    for rule in type_spec.field_rules
                    if rule.kind == "whole_payload"
                ]
                if not whole_rules:
                    continue
                assert len(whole_rules) == 1
                contract = type_spec.source_contract
                if contract.kind == "pydantic_model":
                    module = migration_map_module._import_contract_module(
                        contract.source_file
                    )
                    model_name = contract.symbol
                else:
                    module = migration_map_module._import_contract_module(
                        contract.payload_model_file
                    )
                    model_name = contract.payload_model
                assert module is not None and model_name is not None
                model = getattr(module, model_name)
                assert set(whole_rules[0].covered_fields) == set(model.model_fields)

    def test_removed_whole_payload_covered_field_fails_drift_check(self) -> None:
        raw = _raw_spec()
        definition = next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )
        whole = next(
            rule
            for rule in definition["field_rules"]
            if rule["kind"] == "whole_payload"
        )
        whole["covered_fields"].remove("framing")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("framing" in issue.message for issue in verification.issues)

    def _whole_payload_rule(
        self, raw: dict[str, object], family: str, source_type: str
    ) -> dict[str, object]:
        type_spec = next(
            t
            for t in raw["families"][family]["types"]  # type: ignore[index]
            if t["source_type"] == source_type
        )
        return next(
            rule
            for rule in type_spec["field_rules"]  # type: ignore[index]
            if rule["kind"] == "whole_payload"
        )

    def test_removed_identity_role_from_whole_payload_fails(self) -> None:
        # Repro drift hole: an identity role field removed from the explicit
        # covered_fields list must fail closed — roles never mask the loss.
        raw = _raw_spec()
        whole = self._whole_payload_rule(
            raw, "study_definition", "models.MedicalWritingStudyDefinition"
        )
        whole["covered_fields"].remove("definition_id")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("definition_id" in issue.message for issue in verification.issues)

    def test_removed_project_role_from_whole_payload_fails(self) -> None:
        raw = _raw_spec()
        whole = self._whole_payload_rule(
            raw, "study_definition", "models.MedicalWritingStudyDefinition"
        )
        whole["covered_fields"].remove("project_id")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("project_id" in issue.message for issue in verification.issues)

    def test_removed_revision_role_from_whole_payload_fails(self) -> None:
        raw = _raw_spec()
        whole = self._whole_payload_rule(
            raw, "study_definition", "models.MedicalWritingStudyDefinition"
        )
        whole["covered_fields"].remove("revision")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("revision" in issue.message for issue in verification.issues)

    def test_removed_sqlite_payload_model_rule_field_fails(self) -> None:
        # A payload-scope rule field removed from the SQLite payload-model
        # whole_payload list must fail closed — other payload-scope rules
        # never mask the loss.
        raw = _raw_spec()
        whole = self._whole_payload_rule(
            raw, "protocol_document", "sqlite.medical_writing_greenfield_documents"
        )
        whole["covered_fields"].remove("status")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("status" in issue.message for issue in verification.issues)

    def test_removed_sqlite_payload_model_real_field_fails(self) -> None:
        raw = _raw_spec()
        whole = self._whole_payload_rule(
            raw, "working_copy_snapshot", "sqlite.medical_writing_working_copies"
        )
        whole["covered_fields"].remove("working_copy_id")
        verification = verify_mapping_spec_contracts(parse_mapping_spec(raw))
        assert not verification.verified
        assert any("working_copy_id" in issue.message for issue in verification.issues)

    def test_new_model_field_not_in_explicit_coverage_fails(
        self, monkeypatch
    ) -> None:
        from packages.contracts.workbench_contracts.models import (
            MedicalWritingStudyDefinition,
        )

        monkeypatch.setattr(
            MedicalWritingStudyDefinition,
            "model_fields",
            {
                **MedicalWritingStudyDefinition.model_fields,
                "future_contract_field": object(),
            },
        )
        verification = verify_mapping_spec_contracts(_loaded_spec())
        assert not verification.verified
        assert any(
            "future_contract_field" in issue.message
            for issue in verification.issues
        )

    def test_whole_payload_preservation_carries_all_real_fields(self) -> None:
        # The StudyDefinition counterexample fields (framing, picos, schema,
        # states, module resolutions, source artifacts, provenance/timestamps)
        # must be carried into the mapped output, not silently dropped.
        spec = _loaded_spec()
        record = _record(
            "study_definition",
            "models.MedicalWritingStudyDefinition",
            "def:1",
            "1",
            {
                "definition_id": "def:1",
                "project_id": "PRJ-1",
                "revision": 1,
                "origin": "imported_synopsis",
                "state_sha256": "a" * 64,
                "framing": {"document_title": "真实研究", "version": "V0.1"},
                "picos": {"design_archetype": "randomized_confirmatory"},
                "study_schema": {"schema_id": "s1", "revision": 1},
                "field_states": {"framing.protocol_id": {"status": "confirmed"}},
                "module_resolutions": {"m1": {"module_id": "m1"}},
                "source_artifact_ids": ["art:1", "art:2"],
                "unresolved_paths": [],
                "synopsis_text": "导入文本",
                "synopsis_origin": "imported_text",
                "schema_version": "medical_writing_study_definition_v2",
                "created_at": "2026-01-01",
                "updated_at": "2026-01-02",
                "updated_by": "医学经理",
            },
        )
        report = run_mapping_dry_run([record], spec)
        assert report.mapped_count == 1
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        preserved = outcome.fields["legacy_payload"]
        assert isinstance(preserved, dict)
        for key in (
            "framing",
            "picos",
            "study_schema",
            "field_states",
            "module_resolutions",
            "source_artifact_ids",
            "unresolved_paths",
            "synopsis_text",
            "synopsis_origin",
            "schema_version",
            "created_at",
            "updated_at",
            "updated_by",
        ):
            assert key in preserved, key
        assert preserved["framing"] == {"document_title": "真实研究", "version": "V0.1"}
        # deep-frozen copy: mutation attempts fail and the source is untouched
        with pytest.raises(TypeError):
            preserved["framing"] = "hacked"  # type: ignore[index]
        assert record.payload["framing"] == {"document_title": "真实研究", "version": "V0.1"}

    def test_mapped_output_uses_static_disposition_contract(self) -> None:
        # For every mapped type the runtime output carries exactly the
        # declared rule targets, including whole-payload preservation where
        # declared — the verifier's disposition contract is the same spec the
        # mapper executes (no verifier-only list).
        spec = _loaded_spec()
        for family, family_spec in spec.families.items():
            for index, type_spec in enumerate(family_spec.types):
                if type_spec.outcome == "quarantine":
                    continue
                source_id = f"{type_spec.source_type}:{index}"
                payload = _payload_for_type(type_spec, source_id, "PRJ-D", "值")
                report = run_mapping_dry_run(
                    build_inventory(
                        [_row("PRJ-D", family, type_spec.source_type, source_id, "值", payload)]
                    ),
                    spec,
                )
                assert report.mapped_count == 1, (family, type_spec.source_type)
                outcome = report.outcomes[0]
                assert isinstance(outcome, MappedOutcome)
                declared_targets = {
                    rule.target_field
                    for rule in type_spec.field_rules
                    if rule.target_field is not None
                }
                assert set(outcome.fields) == declared_targets
                if any(rule.kind == "whole_payload" for rule in type_spec.field_rules):
                    assert "legacy_payload" in outcome.fields


# ---------------------------------------------------------------------------
# P1: strict source-contract schema shape (unknown keys, scope misuse)
# ---------------------------------------------------------------------------


class TestSourceContractSchema:
    def _definition_type(self, raw: dict[str, object]) -> dict[str, object]:
        return next(
            t
            for t in raw["families"]["study_definition"]["types"]
            if t["source_type"] == "models.MedicalWritingStudyDefinition"
        )

    def test_rejects_unknown_contract_key(self) -> None:
        raw = _raw_spec()
        self._definition_type(raw)["source_contract"]["mystery"] = 1
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_pydantic_contract_with_table(self) -> None:
        raw = _raw_spec()
        self._definition_type(raw)["source_contract"]["table"] = "x"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_pydantic_contract_with_payload_container(self) -> None:
        raw = _raw_spec()
        self._definition_type(raw)["source_contract"]["payload_container"] = "payload_json"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_pydantic_contract_without_symbol(self) -> None:
        raw = _raw_spec()
        del self._definition_type(raw)["source_contract"]["symbol"]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_sqlite_contract_without_table(self) -> None:
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        del working_copies["source_contract"]["table"]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_sqlite_container_without_payload_model(self) -> None:
        raw = _raw_spec()
        working_copies = next(
            t
            for t in raw["families"]["working_copy_snapshot"]["types"]
            if t["source_type"] == "sqlite.medical_writing_working_copies"
        )
        del working_copies["source_contract"]["payload_model"]
        del working_copies["source_contract"]["payload_model_file"]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_sqlite_without_container_but_with_payload_model(self) -> None:
        raw = _raw_spec()
        records = next(
            t
            for t in raw["families"]["artifact_lineage"]["types"]
            if t["source_type"] == "sqlite.medical_writing_artifact_lifecycle_records"
        )
        records["source_contract"]["payload_model"] = "MedicalWritingWorkingCopy"
        records["source_contract"]["payload_model_file"] = (
            "packages/contracts/workbench_contracts/models.py"
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_jsonl_contract_without_snapshot_constants(self) -> None:
        raw = _raw_spec()
        corpus = next(
            t
            for t in raw["families"]["corpus_evidence"]["types"]
            if t["source_type"] == "jsonl.cms_cn_protocol_corpus_20260715_v1"
        )
        corpus["source_contract"]["snapshot_constants"] = []
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_physical_rule_on_pydantic_source(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        definition["field_rules"].append(
            {"kind": "direct", "source_scope": "physical",
             "source_field": "origin", "target_field": "x"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_payload_rule_on_containerless_sqlite_source(self) -> None:
        raw = _raw_spec()
        records = next(
            t
            for t in raw["families"]["artifact_lineage"]["types"]
            if t["source_type"] == "sqlite.medical_writing_artifact_lifecycle_records"
        )
        records["field_rules"].append(
            {"kind": "direct", "source_field": "document_id", "target_field": "x"}
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_identity_basis_outside_declared_bases(self) -> None:
        raw = _raw_spec()
        gates = next(
            t
            for t in raw["families"]["decision_approval"]["types"]
            if t["source_type"] == "sqlite.writing_reference_extraction_review_records"
        )
        gates["identity_rule"]["basis"] = "payload_field"
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_toy_source_type_not_matching_derived_identifier(self) -> None:
        raw = _raw_spec()
        self._definition_type(raw)["source_type"] = "definition"
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "mechanically derived" in str(exc.value)

    def test_rejects_duplicate_contract_identity_fields(self) -> None:
        raw = _raw_spec()
        self._definition_type(raw)["source_contract"]["identity_fields"] = [
            "definition_id",
            "definition_id",
        ]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_whole_payload_on_jsonl_source(self) -> None:
        raw = _raw_spec()
        corpus = next(
            t
            for t in raw["families"]["corpus_evidence"]["types"]
            if t["source_type"] == "jsonl.cms_cn_protocol_corpus_20260715_v1"
        )
        corpus["outcome"] = "preserved_legacy_only"
        corpus["target_type"] = "corpus_evidence_node"
        corpus["identity_rule"] = {"basis": "source_id", "prefix": "v3::corpus::"}
        corpus["field_rules"] = [{"kind": "whole_payload", "target_field": "legacy_payload"}]
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_whole_payload_without_target_field(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        definition["field_rules"].append({"kind": "whole_payload"})
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_duplicate_whole_payload_rules(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        existing = next(
            rule
            for rule in definition["field_rules"]
            if rule["kind"] == "whole_payload"
        )
        definition["field_rules"].append(
            {
                "kind": "whole_payload",
                "target_field": "second_copy",
                "covered_fields": list(existing["covered_fields"]),
            }
        )
        with pytest.raises(MappingSpecError):
            parse_mapping_spec(raw)

    def test_rejects_mapped_type_without_project_scope(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        definition["source_contract"]["project_scope_fields"] = []
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "project_scope_fields" in str(exc.value)

    def test_rejects_mapped_type_without_revision_fields(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        definition["source_contract"]["revision_fields"] = []
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "revision_fields" in str(exc.value)

    def test_rejects_mapped_type_without_identity_fields(self) -> None:
        raw = _raw_spec()
        definition = self._definition_type(raw)
        definition["source_contract"]["identity_fields"] = []
        with pytest.raises(MappingSpecError) as exc:
            parse_mapping_spec(raw)
        assert "identity_fields" in str(exc.value)


# ---------------------------------------------------------------------------
# P1: deep immutability of the spec and report containers
# ---------------------------------------------------------------------------


class TestDeepImmutability:
    def test_families_mapping_is_deeply_frozen(self) -> None:
        spec = _loaded_spec()
        assert isinstance(spec.families, dict)
        assert type(spec.families) is not dict  # frozen subclass, not a plain dict
        hash_before = spec.spec_sha256
        with pytest.raises(TypeError):
            spec.families.pop("artifact_lineage")
        with pytest.raises(TypeError):
            spec.families["study_definition"] = None  # type: ignore[index]
        with pytest.raises(TypeError):
            spec.families.update({"study_definition": None})
        with pytest.raises(TypeError):
            spec.families.clear()
        with pytest.raises(TypeError):
            del spec.families["artifact_lineage"]
        assert spec.spec_sha256 == hash_before
        assert set(spec.families) == SEVEN_FAMILIES

    def test_nested_spec_models_reject_mutation_with_stable_hash(self) -> None:
        spec = _loaded_spec()
        hash_before = spec.spec_sha256
        with pytest.raises((TypeError, ValidationError)):
            spec.families["study_definition"].family_label_zh = "改"  # type: ignore[misc]
        with pytest.raises((TypeError, ValidationError)):
            spec.families["study_definition"].types[0].source_type = "改"  # type: ignore[misc]
        with pytest.raises((TypeError, ValidationError)):
            spec.families["study_definition"].types[0].field_rules[0].source_field = "改"  # type: ignore[misc]
        with pytest.raises((TypeError, ValidationError)):
            spec.families["study_definition"].types[0].source_contract.symbol = "改"  # type: ignore[misc]
        assert spec.spec_sha256 == hash_before

    def test_spec_hash_stable_under_caller_alias_mutation(self) -> None:
        raw = _raw_spec()
        spec = parse_mapping_spec(raw)
        hash_before = spec.spec_sha256
        # mutating the caller's raw dict must never change the parsed spec
        raw["families"]["study_definition"]["family_label_zh"] = "改"
        raw["families"]["study_definition"]["types"][0]["field_rules"][0][
            "source_field"
        ] = "改"
        assert spec.spec_sha256 == hash_before
        assert spec.families["study_definition"].family_label_zh == "研究方案定义"
        assert spec.families["study_definition"].types[0].field_rules[0].source_field == "origin"

    def test_report_containers_are_deeply_frozen(self) -> None:
        spec = _loaded_spec()
        record = _record(
            "working_copy_snapshot",
            "sqlite.medical_writing_working_copies",
            "wc:1",
            "1",
            {
                "working_copy_id": "wc:1",
                "project_id": "PRJ-1",
                "revision": 1,
                "document_id": "d:1",
                "section_id": "S1",
                "approval_state": "ai_draft",
                "payload_json": {
                    "working_copy_id": "wc:1",
                    "document_id": "d:1",
                    "content_authority_state": {"nested": {"k": [1, 2]}},
                },
            },
        )
        report = run_mapping_dry_run([record], spec)
        outcome = report.outcomes[0]
        assert isinstance(outcome, MappedOutcome)
        with pytest.raises(TypeError):
            outcome.fields["document_id"] = "hacked"
        with pytest.raises(TypeError):
            outcome.fields.pop("document_id")
        nested = outcome.fields["legacy_payload"]["content_authority_state"]
        assert isinstance(nested, dict)
        with pytest.raises(TypeError):
            nested["nested"] = "hacked"  # type: ignore[index]
        with pytest.raises(TypeError):
            report.counts_by_reason["unsupported_type"] = 1
        with pytest.raises(TypeError):
            report.counts_by_reason.pop("unsupported_type")
        assert report.run_sha256 == run_mapping_dry_run([record], spec).run_sha256
