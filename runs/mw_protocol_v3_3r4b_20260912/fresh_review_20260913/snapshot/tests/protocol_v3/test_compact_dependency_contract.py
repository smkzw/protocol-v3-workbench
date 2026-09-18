"""Versioned dependency compaction retains actual input freshness (no calls)."""

import pytest
from datetime import datetime, timezone

from pydantic import ValidationError
from packages.contracts.workbench_contracts.protocol_v3 import ChapterLockSnapshot, SubmissionEvidencePackage

from app.protocol_workflow.runtime.harness import HarnessPolicyError, build_request
from test_harness_policy import _artifact, _llm_role, _node_contract, _skill


def test_legacy_node_material_hash_remains_byte_stable():
    legacy = _node_contract()
    assert legacy.material_sha256() == (
        "44678e0c1a80d401e0ccfa067f1b7efa869206df4350f3e67ee122844d91d378"
    )
    assert type(legacy).model_validate_json(legacy.model_dump_json()) == legacy


def test_compaction_is_explicit_versioned_and_roundtrips():
    legacy = _node_contract()
    before = legacy.model_dump_json()
    compact = legacy.compact_dependencies()
    assert legacy.model_dump_json() == before
    assert compact.schema_version != legacy.schema_version
    assert "input_artifact_hashes" not in compact.model_dump(mode="json")
    assert compact.material_sha256() != legacy.material_sha256()
    restored = type(compact).model_validate_json(compact.model_dump_json())
    assert restored == compact
    assert restored.compact_dependencies() == compact


def test_compact_contract_binds_matching_inputs_through_real_harness():
    compact = _node_contract().compact_dependencies()
    request = build_request(
        node_contract=compact, skill=_skill(), role_entry=_llm_role(),
        artifacts=(_artifact(),), selected_region="cn",
    )
    assert request.node_execution_contract_id == compact.node_execution_contract_id
    assert request.input_artifacts == (_artifact(),)


@pytest.mark.parametrize("hashes", [("a" * 64,), ("b" * 64, "a" * 64), ("a" * 64, "c" * 64)])
def test_compact_contract_detects_missing_reordered_or_replaced_input(hashes):
    original = _node_contract(input_hashes=("a" * 64, "b" * 64))
    compact = original.compact_dependencies()
    changed = _node_contract(input_hashes=hashes).compact_dependencies()
    assert changed.material_sha256() != compact.material_sha256()
    with pytest.raises(HarnessPolicyError):
        build_request(
            node_contract=compact, skill=_skill(), role_entry=_llm_role(),
            artifacts=tuple(_artifact(ref=f"input-{i}", sha=value) for i, value in enumerate(hashes)),
            selected_region="cn",
        )


def test_compact_document_revision_stays_versioned_and_replays():
    from app.protocol_workflow.canonical.document import DocumentEffectLedger, SemanticDocumentReducer
    from test_semantic_document_reducer import (
        _study_definition, _document_revision, _decision, _snapshot_for, _apply_kwargs, LATER,
    )
    study = _study_definition()
    original = _document_revision(study).compact_dependencies()
    decision = _decision(snapshot_sha256=_snapshot_for(original))
    reducer = SemanticDocumentReducer()
    revised, _, ledger, replayed = reducer.replay_or_apply(
        original, study, decision, DocumentEffectLedger(), now=LATER, **_apply_kwargs(),
    )
    assert not replayed
    assert revised.schema_version == original.schema_version
    assert "chapter_contract_hashes" not in revised.model_dump(mode="json")
    again, _, _, replayed = reducer.replay_or_apply(
        revised, study, decision, ledger, now=LATER, **_apply_kwargs(),
    )
    assert replayed and again == revised


def _remaining_contracts():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    sha = "a" * 64
    return (
        ChapterLockSnapshot(
            chapter_lock_snapshot_id="lock:test", semantic_node_id="node:test",
            semantic_document_revision_id="doc:test", semantic_document_sha256=sha,
            upstream_artifact_hashes=(sha,), accepted_semantic_block_hashes=(sha,),
            locked_by_actor_id="user:test", locked_at=now,
        ),
        SubmissionEvidencePackage(
            submission_evidence_package_id="package:test", project_id="project:test",
            workflow_run_id="run:test", workflow_run_sha256=sha,
            study_definition_id="study:test", study_definition_sha256=sha,
            semantic_document_revision_id="doc:test", semantic_document_sha256=sha,
            source_manifest_hashes=(sha,), medical_admission_unit_ids=("unit:test",),
            applicability_snapshot_id="snapshot:test", applicability_snapshot_sha256=sha,
            chapter_contract_hashes=(sha,), skill_definition_hashes=(sha,),
            decision_record_ids=("decision:test",), qc_clean_verdict_sha256=sha,
            word_receipt_id="receipt:test", word_receipt_sha256=sha,
            projection_artifact_ids=("artifact:test",), model_versions={"test": "1"},
            tool_versions={"test": "1"}, frozen_at=now,
        ),
    )


@pytest.mark.parametrize("legacy", _remaining_contracts())
def test_lock_and_submission_compaction_preserve_dependency_obligations(legacy):
    # Independently compared with the pre-change HEAD model implementation.
    expected = {
        "ChapterLockSnapshot": "062fff6de985944db6a841f36b068ddce4c84d58073d357a2ac6ab28c6cc660b",
        "SubmissionEvidencePackage": "7e0670d3801c95c9d3f61aacb9722dd023d3afbcbde18ca2304cb1a2d8a349df",
    }
    assert legacy.material_sha256() == expected[type(legacy).__name__]
    before = legacy.model_dump_json()
    compact = legacy.compact_dependencies()
    assert legacy.model_dump_json() == before
    assert compact.dependency_field not in compact.model_dump(mode="json")
    assert compact.matches_dependencies(("a" * 64,))
    assert not compact.matches_dependencies(("b" * 64,))
    assert type(compact).model_validate_json(compact.model_dump_json()) == compact
    inconsistent = compact.model_dump(mode="json")
    inconsistent[compact.dependency_field] = ["b" * 64]
    with pytest.raises(ValidationError, match="do not match"):
        type(compact).model_validate(inconsistent)


def test_legacy_missing_dependencies_and_unversioned_digest_are_rejected():
    legacy = _node_contract()
    missing = legacy.model_dump(mode="json")
    missing.pop("input_artifact_hashes")
    with pytest.raises(ValidationError, match="legacy contracts require"):
        type(legacy).model_validate(missing)
    mixed = legacy.model_dump(mode="json")
    mixed["dependency_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="legacy contracts require"):
        type(legacy).model_validate(mixed)


def test_legacy_document_hash_preserved_and_chapter_changes_invalidate_compact():
    from test_semantic_document_reducer import _study_definition, _document_revision
    study = _study_definition()
    original = _document_revision(study)
    assert original.material_sha256() == "580a1f5b8c4966c3e4783a5f9c4744057dc09272ed6b1ba6885a96696da921a5"
    changed = _document_revision(study, chapter_contract_hashes=("f" * 64,))
    assert original.compact_dependencies().material_sha256() != changed.compact_dependencies().material_sha256()


def test_compact_dependency_and_material_hashes_have_stable_version_baselines():
    from test_semantic_document_reducer import _study_definition, _document_revision
    models = (_node_contract(), _document_revision(_study_definition()), *_remaining_contracts())
    # Dependency digests identify ordered named input sets, not model types.
    # Document and submission intentionally share chapter-set digests; their
    # full material hashes remain distinct and bind their containing contracts.
    expected = (
        ("ecd26848d535fd31b8234d00f3258309afcb2b13ba39b7a250b041b7c08ff22e", "a597971a3b0958aaa62efcaa3498d66017dd30e41ed31aa98cca6c58afe827e5"),
        ("5af26df72c11bb57c902a32283916b09908472c129e7e931ca471ec64be90dc9", "78e2cbacfcc7f68213be522b61910e3c62f93ec272e9bf588fa70f8bd0302cec"),
        ("83d66265c89bf84a6ffab684bd05a7f94108ad0c96f91d446ba3b3e94cce2ae0", "c32feca76d2ba541303d9242947578878c7150d4ac05233934605a28ab6e5df5"),
        ("5af26df72c11bb57c902a32283916b09908472c129e7e931ca471ec64be90dc9", "9c5ac8cdb1596435b171d2fbee0ce8e92e39c07ed7868233c75ddbeb7c15a7f5"),
    )
    for legacy, baseline in zip(models, expected, strict=True):
        compact = legacy.compact_dependencies()
        assert (compact.dependency_sha256, compact.material_sha256()) == baseline
