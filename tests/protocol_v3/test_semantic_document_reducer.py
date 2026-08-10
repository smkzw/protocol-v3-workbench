"""Tests for the SemanticDocument pure reducer, fact-revision binding and typed
fact proposal.

Covers Protocol v3 Task 1.4 (worker_03) micro-steps after manager-directed
repairs:

- **Ledger-first CAS replay** — the same ``(decision_record_id,
  snapshot_sha256, expected_state_revision)`` triple and identical payload
  replay the exact prior revision via :class:`DocumentEffectLedger`.  A
  different decision ID can never be mistaken for the original operation.
- **Full payload binding** — semantic blocks (including content/bindings),
  chapter contract hashes, applicability identity/hash, and the exact
  StudyDefinition revision hash all participate in the payload hash.  Same CAS
  triple with any changed payload raises :class:`DocumentPayloadConflictError`.
- **Shared canonical revision hash** — StudyDefinition authority binding uses
  :func:`canonical_revision_hash`; same material at a new numeric revision
  makes the prior document stale.
- **Deep-immutable FactProposal** — caller mutation after construction and
  attempted mutation at every nested dict/list level cannot alter the
  proposal.
- **Projection coverage** — paragraph (Summary/body), schedule_of_activities,
  table and figure blocks each bind only real fact paths; the document has no
  fact-value authority field.
- **``fact_or_uncertain`` is proposal-only** — no document revision, no silent
  fact mutation.  Safe edit classes still require full CAS/payload checks.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DecisionRecord,
    SemanticBlock,
    SemanticDocumentRevision,
    StudyDefinitionV3,
)
from services.api.app.protocol_workflow.canonical import (
    DocumentCasError,
    DocumentEffectLedger,
    DocumentPayloadConflictError,
    DocumentRevisionStaleError,
    EditClass,
    FactProposal,
    FactProposalError,
    FactRevisionMismatchError,
    SemanticDocumentReducer,
    UnboundFactPathError,
    document_revision_hash,
    study_revision_hash,
)


NOW = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 10, 10, 30, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _study_definition(**overrides) -> StudyDefinitionV3:
    payload = {
        "study_definition_id": "study:def:uc301",
        "project_id": "project:uc301",
        "revision": 1,
        "normalized_seed_id": "seed:uc301:normalized",
        "normalized_seed_sha256": SHA_A,
        "facts": {
            "picos.population.indication": "中重度活动性溃疡性结肠炎",
            "picos.intervention.dose": "10 mg 每日一次",
            "picos.sample_size.total": "120",
            "picos.endpoints.primary": "临床缓解率（Mayo 评分）",
            "soa.visits.screening": "筛选期：-28 至 -1 天",
        },
        "decision_record_ids": (),
        "updated_at": NOW,
        "canonical_state": "proposed",
    }
    payload.update(overrides)
    if payload["revision"] > 1 and "previous_revision_sha256" not in payload:
        payload["previous_revision_sha256"] = SHA_B
    return StudyDefinitionV3(**payload)


def _semantic_block(
    *,
    semantic_block_id: str = "block:summary:001",
    semantic_node_id: str = "node:summary",
    chapter_contract_id: str = "chapter:summary",
    substantive_content_contract_id: str = "substantive:summary",
    block_kind: str = "paragraph",
    content: str = "本研究评估药物 X 在中重度活动性溃疡性结肠炎患者中的疗效。",
    fact_paths: tuple[str, ...] = ("picos.population.indication",),
    claim_evidence_link_ids: tuple[str, ...] = ("claim:001",),
    medical_admission_unit_ids: tuple[str, ...] = ("mau:001",),
    content_sha256: str = SHA_A,
    **overrides,
) -> SemanticBlock:
    payload = {
        "semantic_block_id": semantic_block_id,
        "semantic_node_id": semantic_node_id,
        "chapter_contract_id": chapter_contract_id,
        "substantive_content_contract_id": substantive_content_contract_id,
        "block_kind": block_kind,
        "content": content,
        "fact_paths": fact_paths,
        "claim_evidence_link_ids": claim_evidence_link_ids,
        "medical_admission_unit_ids": medical_admission_unit_ids,
        "content_sha256": content_sha256,
    }
    payload.update(overrides)
    return SemanticBlock(**payload)


def _document_revision(
    study_definition: StudyDefinitionV3,
    *,
    semantic_document_revision_id: str = "doc:protocol:001",
    revision: int = 1,
    blocks: tuple[SemanticBlock, ...] | None = None,
    canonical_state: str = "proposed",
    **overrides,
) -> SemanticDocumentRevision:
    payload = {
        "semantic_document_revision_id": semantic_document_revision_id,
        "project_id": study_definition.project_id,
        "revision": revision,
        "study_definition_id": study_definition.study_definition_id,
        "study_definition_sha256": study_revision_hash(study_definition),
        "applicability_snapshot_id": "snap:app:001",
        "applicability_snapshot_sha256": SHA_B,
        "semantic_blocks": blocks or (_semantic_block(),),
        "chapter_contract_hashes": (SHA_A,),
        "updated_at": NOW,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    if payload["revision"] > 1 and "previous_revision_sha256" not in payload:
        payload["previous_revision_sha256"] = SHA_C
    return SemanticDocumentRevision(**payload)


def _decision(
    *,
    decision_record_id: str = "decision:write:001",
    decision_key: str = "decision:write",
    snapshot_sha256: str = SHA_A,
    expected_state_revision: int = 1,
    canonical_state: str = "confirmed",
    **overrides,
) -> DecisionRecord:
    payload = {
        "decision_record_id": decision_record_id,
        "decision_key": decision_key,
        "snapshot_sha256": snapshot_sha256,
        "expected_state_revision": expected_state_revision,
        "state_revision": expected_state_revision + 1,
        "option_ids": ("option:write:001", "option:write:002"),
        "selected_option_id": "option:write:001",
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 生成的方案摘要正文。",
        "decided_at": NOW,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    return DecisionRecord(**payload)


def _snapshot_for(doc: SemanticDocumentRevision) -> str:
    """Return the canonical revision hash — the snapshot a decision must carry
    to bind the exact current document revision."""
    return document_revision_hash(doc)


def _apply_kwargs(
    blocks: tuple[SemanticBlock, ...] | None = None,
    *,
    chapter_contract_hashes: tuple[str, ...] = (SHA_A,),
    applicability_snapshot_id: str = "snap:app:001",
    applicability_snapshot_sha256: str = SHA_B,
) -> dict:
    return {
        "semantic_blocks": blocks or (_semantic_block(),),
        "chapter_contract_hashes": chapter_contract_hashes,
        "applicability_snapshot_id": applicability_snapshot_id,
        "applicability_snapshot_sha256": applicability_snapshot_sha256,
    }


# ---------------------------------------------------------------------------
# Ledger-first CAS replay
# ---------------------------------------------------------------------------


class TestLedgerFirstCasReplay:
    """Exact replay must prove the original unchanged full CAS triple via the
    DocumentEffectLedger, not merely state-revision + predecessor."""

    def test_fresh_apply_advances_revision_and_returns_advanced_ledger(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block(content="修订后的方案摘要正文。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        new_doc, eff_decision, new_ledger, replayed = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert replayed is False
        assert new_doc.revision == 2
        assert new_doc.previous_revision_sha256 == _snapshot_for(doc)
        assert eff_decision is decision
        assert not new_ledger.is_empty()

    def test_exact_replay_returns_prior_revision_and_prior_decision(self):
        """Replaying the exact same CAS triple returns *current* unchanged and
        the *previously recorded* DecisionRecord, not the incoming one."""
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block(content="方案摘要正文。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        # First apply.
        doc2, _, ledger2, replayed1 = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert replayed1 is False
        prior_sha = doc2.material_sha256()
        # Replay the exact same decision (same CAS triple, same payload).
        doc2_replay, eff_decision, ledger2_replay, replayed2 = reducer.replay_or_apply(
            doc2,
            sd,
            decision,
            ledger2,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert replayed2 is True
        assert doc2_replay.material_sha256() == prior_sha
        assert doc2_replay.revision == doc2.revision
        # The ledger is returned unchanged.
        assert ledger2_replay is ledger2
        # The effective decision is the previously recorded one.
        assert eff_decision is decision

    def test_document_effect_and_ledger_are_immutable(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        _, _, ledger, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs(),
        )
        effect = next(iter(ledger.effects.values()))
        with pytest.raises(AttributeError, match="immutable"):
            effect.result_revision = 99
        with pytest.raises(TypeError):
            ledger.effects["forged"] = effect
        with pytest.raises(AttributeError, match="immutable"):
            ledger._effects = {}

    def test_different_decision_id_never_mistaken_for_original(self):
        """A different decision_record_id produces a different CAS identity;
        the ledger cannot confuse it with the original operation."""
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision_a = _decision(
            decision_record_id="decision:write:001",
            snapshot_sha256=_snapshot_for(doc),
        )
        reducer.replay_or_apply(
            doc,
            sd,
            decision_a,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        # A second, different decision targeting the same revision slot.
        decision_b = _decision(
            decision_record_id="decision:write:002",
            snapshot_sha256=_snapshot_for(doc),
        )
        # This is a fresh decision against the original doc — it should NOT be
        # treated as a replay of decision_a.
        _, _, _, replayed = reducer.replay_or_apply(
            doc,
            sd,
            decision_b,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert replayed is False

    def test_replay_against_descendant_revision_is_still_exact(self):
        """After the document has advanced past the recorded result, replaying
        the original CAS triple returns *current* unchanged (commit/restart
        scenario)."""
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block_a = _semantic_block(content="版本 A。")
        decision_a = _decision(snapshot_sha256=_snapshot_for(doc))
        doc2, _, ledger2, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision_a,
            ledger,
            now=LATER,
            **_apply_kwargs((block_a,)),
        )
        # Advance again with a second decision.
        block_b = _semantic_block(content="版本 B。")
        decision_b = _decision(
            decision_record_id="decision:write:002",
            snapshot_sha256=_snapshot_for(doc2),
            expected_state_revision=doc2.revision,
        )
        doc3, _, ledger3, _ = reducer.replay_or_apply(
            doc2,
            sd,
            decision_b,
            ledger2,
            now=LATER,
            **_apply_kwargs((block_b,)),
        )
        # Now replay decision_a against doc3 (descendant).
        doc3_replay, _, _, replayed = reducer.replay_or_apply(
            doc3,
            sd,
            decision_a,
            ledger3,
            now=LATER,
            **_apply_kwargs((block_a,)),
        )
        assert replayed is True
        assert doc3_replay is doc3

    def test_replay_against_forged_same_result_revision_fails_closed(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        block = _semantic_block(content="原始正文。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        doc2, _, ledger, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        forged = _document_revision(
            sd,
            revision=doc2.revision,
            previous_revision_sha256=doc2.previous_revision_sha256,
            blocks=(_semantic_block(content="伪造的不同正文。"),),
            canonical_state=doc2.canonical_state,
        )

        with pytest.raises(DocumentRevisionStaleError):
            reducer.replay_or_apply(
                forged,
                sd,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )

    def test_replay_against_unrecorded_later_revision_fails_closed(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        block = _semantic_block(content="原始正文。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        doc2, _, ledger, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        forged_later = _document_revision(
            sd,
            revision=doc2.revision + 1,
            previous_revision_sha256=document_revision_hash(doc2),
            blocks=(_semantic_block(content="未记录的后续正文。"),),
            canonical_state=doc2.canonical_state,
        )

        with pytest.raises(DocumentRevisionStaleError):
            reducer.replay_or_apply(
                forged_later,
                sd,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )


# ---------------------------------------------------------------------------
# Full payload binding
# ---------------------------------------------------------------------------


class TestFullPayloadBinding:
    """Same CAS triple with any changed payload must raise
    DocumentPayloadConflictError."""

    def test_same_triple_changed_blocks_raises_conflict(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block_a = _semantic_block(content="原始正文。")
        block_b = _semantic_block(content="修改后的正文，内容不同。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        _, _, ledger2, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block_a,)),
        )
        with pytest.raises(DocumentPayloadConflictError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger2,
                now=LATER,
                **_apply_kwargs((block_b,)),
            )
        assert exc_info.value.conflict_kind == "document_payload"

    def test_same_triple_changed_applicability_raises_conflict(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        kw = _apply_kwargs((block,))
        _, _, ledger2, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **kw,
        )
        # Change applicability snapshot identity.
        kw_changed = dict(kw)
        kw_changed["applicability_snapshot_id"] = "snap:app:002"
        with pytest.raises(DocumentPayloadConflictError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger2,
                now=LATER,
                **kw_changed,
            )
        assert exc_info.value.conflict_kind == "document_payload"

    def test_same_triple_changed_chapter_contracts_raises_conflict(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        kw = _apply_kwargs((block,), chapter_contract_hashes=(SHA_A,))
        _, _, ledger2, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **kw,
        )
        kw_changed = dict(kw)
        kw_changed["chapter_contract_hashes"] = (SHA_C,)
        with pytest.raises(DocumentPayloadConflictError):
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger2,
                now=LATER,
                **kw_changed,
            )

    def test_same_triple_changed_decision_payload_raises_conflict(self):
        """Same CAS identity but the DecisionRecord material differs."""
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        _, _, ledger2, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        # Same CAS triple but mutate the decision's material (reason).
        decision_mutated = _decision(
            snapshot_sha256=_snapshot_for(doc),
            reason="不同的决策理由。",
        )
        with pytest.raises(DocumentPayloadConflictError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd,
                decision_mutated,
                ledger2,
                now=LATER,
                **_apply_kwargs((block,)),
            )
        assert exc_info.value.conflict_kind == "decision_record"


# ---------------------------------------------------------------------------
# Stale revision and snapshot binding
# ---------------------------------------------------------------------------


class TestStaleRevisionAndSnapshot:
    def test_stale_expected_revision_raises_typed_error(self):
        sd = _study_definition()
        doc = _document_revision(sd, revision=3, previous_revision_sha256=SHA_C)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(expected_state_revision=1)
        assert decision.state_revision < doc.revision
        with pytest.raises(DocumentRevisionStaleError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )
        assert exc_info.value.expected_revision == 1
        assert exc_info.value.actual_revision == 3

    def test_snapshot_must_bind_canonical_revision_not_material_hash(self):
        """A snapshot that is only the material hash (not the canonical
        revision hash) must be rejected — same content at a different revision
        is stale."""
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        # Material hash is NOT the canonical revision hash.
        bad_snapshot = doc.material_sha256()
        assert bad_snapshot != _snapshot_for(doc)
        decision = _decision(snapshot_sha256=bad_snapshot)
        with pytest.raises(DocumentRevisionStaleError):
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )


# ---------------------------------------------------------------------------
# Fact-revision binding
# ---------------------------------------------------------------------------


class TestFactRevisionBinding:
    def test_document_header_carries_study_definition_hash(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        assert doc.study_definition_id == sd.study_definition_id
        assert doc.study_definition_sha256 == study_revision_hash(sd)

    def test_apply_rejects_study_definition_hash_mismatch(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        sd2 = _study_definition(
            facts={
                "picos.population.indication": "中度活动性溃疡性结肠炎",
                "picos.intervention.dose": "10 mg 每日一次",
                "picos.sample_size.total": "120",
                "picos.endpoints.primary": "临床缓解率（Mayo 评分）",
                "soa.visits.screening": "筛选期：-28 至 -1 天",
            }
        )
        assert sd2.material_sha256() != sd.material_sha256()
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        with pytest.raises(FactRevisionMismatchError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd2,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )
        assert exc_info.value.expected_sha256 == doc.study_definition_sha256
        assert exc_info.value.actual_sha256 == study_revision_hash(sd2)

    def test_apply_rejects_wrong_study_definition_identity(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        sd_other = _study_definition(study_definition_id="study:def:other")
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        with pytest.raises(FactRevisionMismatchError):
            reducer.replay_or_apply(
                doc,
                sd_other,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )

    def test_apply_rejects_block_with_unbound_fact_path(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        phantom_block = _semantic_block(
            fact_paths=("picos.population.indication", "picos.endpoint.secondary"),
        )
        assert "picos.endpoint.secondary" not in sd.facts
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        with pytest.raises(UnboundFactPathError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((phantom_block,)),
            )
        assert "picos.endpoint.secondary" in exc_info.value.unbound_fact_paths

    def test_document_has_no_fact_value_authority_field(self):
        """The document model must not carry fact values — only fact-path
        references."""
        assert "facts" not in SemanticDocumentRevision.model_fields


# ---------------------------------------------------------------------------
# Canonical revision hash for StudyDefinition authority binding
# ---------------------------------------------------------------------------


class TestStudyDefinitionRevisionBinding:
    """Same StudyDefinition material at a new numeric revision must make the
    prior document stale."""

    def test_same_material_new_revision_makes_document_stale(self):
        sd = _study_definition(revision=1)
        doc = _document_revision(sd)
        # Create a study definition with the same facts but at revision 2.
        # The material hash is the same, but the revision identity differs.
        sd_r2 = _study_definition(
            revision=2,
            previous_revision_sha256=SHA_B,
        )
        assert sd_r2.material_sha256() == sd.material_sha256()
        assert doc.study_definition_sha256 == study_revision_hash(sd)
        assert doc.study_definition_sha256 != study_revision_hash(sd_r2)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        with pytest.raises(FactRevisionMismatchError) as exc_info:
            reducer.replay_or_apply(
                doc,
                sd_r2,
                decision,
                ledger,
                now=LATER,
                **_apply_kwargs((block,)),
            )
        assert exc_info.value.expected_sha256 == study_revision_hash(sd)
        assert exc_info.value.actual_sha256 == study_revision_hash(sd_r2)


# ---------------------------------------------------------------------------
# Typed fact proposal — deep immutability
# ---------------------------------------------------------------------------


class TestFactProposalDeepImmutability:
    """FactProposal must be deeply immutable and non-aliasing."""

    def test_caller_dict_mutation_does_not_alter_proposal(self):
        updates = {"picos.intervention.dose": "20 mg 每日一次"}
        proposal = FactProposal(
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates=updates,
        )
        # Mutate the caller's dict after construction.
        updates["picos.intervention.dose"] = "HACKED"
        updates["extra"] = "injected"
        assert dict(proposal.proposed_fact_updates) == {
            "picos.intervention.dose": "20 mg 每日一次"
        }

    def test_nested_dict_is_read_only(self):
        nested = {"key": {"inner": "value"}}
        proposal = FactProposal(
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates=nested,
        )
        result = proposal.proposed_fact_updates
        # The top-level mapping is a MappingProxyType (read-only).
        with pytest.raises(TypeError):
            result["new_key"] = "x"  # type: ignore[index]
        # The nested dict is also frozen.
        inner = result["key"]
        with pytest.raises(TypeError):
            inner["inner"] = "HACKED"  # type: ignore[index]

    def test_nested_list_is_converted_to_tuple(self):
        nested = {"key": [1, 2, 3]}
        proposal = FactProposal(
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates=nested,
        )
        val = proposal.proposed_fact_updates["key"]
        assert isinstance(val, tuple)
        assert val == (1, 2, 3)

    def test_attribute_assignment_raises(self):
        proposal = FactProposal(
            affected_fact_paths=("picos.intervention.dose",),
        )
        with pytest.raises(AttributeError):
            proposal.reason = "HACKED"  # type: ignore[misc]

    def test_attribute_deletion_raises(self):
        proposal = FactProposal(
            affected_fact_paths=("picos.intervention.dose",),
        )
        with pytest.raises(AttributeError):
            del proposal.reason  # type: ignore[misc]

    def test_proposal_via_reducer_is_deeply_immutable(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        updates = {"picos.intervention.dose": "20 mg 每日一次"}
        proposal = reducer.propose_fact_update(
            doc,
            sd,
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates=updates,
        )
        updates["picos.intervention.dose"] = "HACKED"
        assert dict(proposal.proposed_fact_updates) == {
            "picos.intervention.dose": "20 mg 每日一次"
        }

    def test_non_json_mutable_value_is_rejected_instead_of_aliased(self):
        mutable_set = {"A"}
        with pytest.raises(TypeError, match="JSON-compatible"):
            FactProposal(
                affected_fact_paths=("picos.intervention.dose",),
                proposed_fact_updates={"nested": mutable_set},
            )


# ---------------------------------------------------------------------------
# Typed fact proposal — proposal-only semantics
# ---------------------------------------------------------------------------


class TestTypedFactProposalSemantics:
    """A fact-touching edit must return a FactProposal, not a revision."""

    def test_fact_or_uncertain_edit_returns_proposal_not_revision(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        outcome = reducer.classify_and_apply_edit(
            doc,
            sd,
            decision,
            ledger,
            edit_class=EditClass.FACT_OR_UNCERTAIN,
            **_apply_kwargs((block,)),
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates={"picos.intervention.dose": "20 mg 每日一次"},
            originating_block_id="block:summary:001",
            reason="用户在画布上将剂量改为 20 mg。",
            now=LATER,
        )
        assert outcome.applied is False
        assert outcome.revision is None
        assert isinstance(outcome.proposal, FactProposal)
        assert outcome.proposal.affected_fact_paths == ("picos.intervention.dose",)

    def test_wording_only_edit_advances_revision_directly(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block(content="仅措辞调整，不触及任何事实。")
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        outcome = reducer.classify_and_apply_edit(
            doc,
            sd,
            decision,
            ledger,
            edit_class=EditClass.WORDING_ONLY,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert outcome.applied is True
        assert outcome.revision is not None
        assert outcome.revision.revision == 2
        assert outcome.proposal is None

    def test_safe_edit_still_requires_full_cas_checks(self):
        """A WORDING_ONLY edit with a stale expected revision must still fail."""
        sd = _study_definition()
        doc = _document_revision(sd, revision=3, previous_revision_sha256=SHA_C)
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(expected_state_revision=1)
        with pytest.raises(DocumentRevisionStaleError):
            reducer.classify_and_apply_edit(
                doc,
                sd,
                decision,
                ledger,
                edit_class=EditClass.WORDING_ONLY,
                now=LATER,
                **_apply_kwargs((block,)),
            )

    def test_proposal_does_not_change_document_revision(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        original_sha = doc.material_sha256()
        reducer = SemanticDocumentReducer()
        reducer.propose_fact_update(
            doc,
            sd,
            affected_fact_paths=("picos.intervention.dose",),
            proposed_fact_updates={"picos.intervention.dose": "20 mg 每日一次"},
        )
        assert doc.material_sha256() == original_sha
        assert doc.revision == 1

    def test_propose_rejects_phantom_fact_path(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        with pytest.raises(UnboundFactPathError) as exc_info:
            reducer.propose_fact_update(
                doc,
                sd,
                affected_fact_paths=("picos.endpoint.secondary",),
            )
        assert "picos.endpoint.secondary" in exc_info.value.unbound_fact_paths


# ---------------------------------------------------------------------------
# Projection tests: paragraph, schedule_of_activities, table, figure
# ---------------------------------------------------------------------------


class TestProjectionBlockKinds:
    """Each block kind must bind only real fact paths, and the document must
    contain no fact-value authority field."""

    def test_paragraph_block_binds_real_facts(self):
        sd = _study_definition()
        doc = _document_revision(
            sd,
            blocks=(
                _semantic_block(
                    semantic_block_id="block:summary:001",
                    block_kind="paragraph",
                    content="本研究评估药物 X 在中重度活动性溃疡性结肠炎患者中的疗效和安全性。",
                    fact_paths=("picos.population.indication",),
                ),
            ),
        )
        for block in doc.semantic_blocks:
            for path in block.fact_paths:
                assert path in sd.facts

    def test_schedule_of_activities_block_binds_real_facts(self):
        sd = _study_definition()
        soa_block = _semantic_block(
            semantic_block_id="block:soa:001",
            semantic_node_id="node:soa",
            chapter_contract_id="chapter:soa",
            substantive_content_contract_id="substantive:soa",
            block_kind="schedule_of_activities",
            content="访视计划：筛选期 -28 至 -1 天；基线 Day 1；治疗期每 4 周。",
            fact_paths=("soa.visits.screening",),
            content_sha256=SHA_B,
        )
        assert "soa.visits.screening" in sd.facts
        doc = _document_revision(sd, blocks=(soa_block,))
        # Apply should succeed with a valid block.
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        new_doc, _, _, replayed = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((soa_block,)),
        )
        assert replayed is False
        assert new_doc.revision == 2

    def test_table_block_binds_real_facts(self):
        sd = _study_definition()
        table_block = _semantic_block(
            semantic_block_id="block:endpoints:table:001",
            semantic_node_id="node:endpoints",
            chapter_contract_id="chapter:endpoints",
            substantive_content_contract_id="substantive:endpoints",
            block_kind="table",
            content="主要终点：临床缓解率（Mayo 评分）",
            fact_paths=("picos.endpoints.primary",),
            content_sha256=SHA_C,
        )
        assert "picos.endpoints.primary" in sd.facts
        doc = _document_revision(sd, blocks=(table_block,))
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        new_doc, _, _, replayed = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((table_block,)),
        )
        assert replayed is False
        assert new_doc.revision == 2

    def test_figure_block_binds_real_facts(self):
        sd = _study_definition()
        figure_block = _semantic_block(
            semantic_block_id="block:design:figure:001",
            semantic_node_id="node:design",
            chapter_contract_id="chapter:design",
            substantive_content_contract_id="substantive:design",
            block_kind="figure",
            content="研究设计流程图：筛选 → 随机 → 治疗 → 随访",
            fact_paths=("picos.sample_size.total",),
            content_sha256=SHA_A,
        )
        assert "picos.sample_size.total" in sd.facts
        doc = _document_revision(sd, blocks=(figure_block,))
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        new_doc, _, _, replayed = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((figure_block,)),
        )
        assert replayed is False
        assert new_doc.revision == 2

    def test_mixed_block_kinds_in_single_revision(self):
        sd = _study_definition()
        blocks = (
            _semantic_block(
                semantic_block_id="block:summary:001",
                block_kind="paragraph",
                content="方案摘要正文。",
                fact_paths=("picos.population.indication",),
            ),
            _semantic_block(
                semantic_block_id="block:soa:001",
                semantic_node_id="node:soa",
                chapter_contract_id="chapter:soa",
                substantive_content_contract_id="substantive:soa",
                block_kind="schedule_of_activities",
                content="SoA 表格内容。",
                fact_paths=("soa.visits.screening",),
                content_sha256=SHA_B,
            ),
            _semantic_block(
                semantic_block_id="block:endpoints:001",
                semantic_node_id="node:endpoints",
                chapter_contract_id="chapter:endpoints",
                substantive_content_contract_id="substantive:endpoints",
                block_kind="table",
                content="终点表格。",
                fact_paths=("picos.endpoints.primary",),
                content_sha256=SHA_C,
            ),
        )
        doc = _document_revision(sd, blocks=blocks)
        for block in doc.semantic_blocks:
            for path in block.fact_paths:
                assert path in sd.facts


# ---------------------------------------------------------------------------
# Canonical state transitions
# ---------------------------------------------------------------------------


class TestCanonicalStateTransitions:
    def test_confirmed_decision_advances_proposed_to_confirmed(self):
        sd = _study_definition()
        doc = _document_revision(sd, canonical_state="proposed")
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(
            snapshot_sha256=_snapshot_for(doc),
            canonical_state="confirmed",
        )
        new_doc, _, _, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert new_doc.canonical_state is CanonicalState.CONFIRMED

    def test_confirmed_document_stays_confirmed(self):
        sd = _study_definition()
        doc = _document_revision(sd, canonical_state="confirmed")
        reducer = SemanticDocumentReducer()
        ledger = DocumentEffectLedger()
        block = _semantic_block()
        decision = _decision(
            snapshot_sha256=_snapshot_for(doc),
            canonical_state="confirmed",
        )
        new_doc, _, _, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            ledger,
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert new_doc.canonical_state is CanonicalState.CONFIRMED


# ---------------------------------------------------------------------------
# Purity and determinism
# ---------------------------------------------------------------------------


class TestPurityAndDeterminism:
    def test_reducer_produces_deterministic_lineage(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        reducer = SemanticDocumentReducer()
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        d1, _, _, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        d2, _, _, _ = reducer.replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert d1.material_sha256() == d2.material_sha256()

    def test_reducer_is_stateless_across_instances(self):
        sd = _study_definition()
        doc = _document_revision(sd)
        block = _semantic_block()
        decision = _decision(snapshot_sha256=_snapshot_for(doc))
        d1, _, _, _ = SemanticDocumentReducer().replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        d2, _, _, _ = SemanticDocumentReducer().replay_or_apply(
            doc,
            sd,
            decision,
            DocumentEffectLedger(),
            now=LATER,
            **_apply_kwargs((block,)),
        )
        assert d1.material_sha256() == d2.material_sha256()


# ---------------------------------------------------------------------------
# Error hierarchy and EditClass contract
# ---------------------------------------------------------------------------


class TestErrorHierarchyAndEditClass:
    def test_all_document_errors_are_document_cas_error_subclasses(self):
        for exc_cls in (
            DocumentRevisionStaleError,
            DocumentPayloadConflictError,
            FactRevisionMismatchError,
            UnboundFactPathError,
            FactProposalError,
        ):
            assert issubclass(exc_cls, DocumentCasError)

    def test_edit_class_values_match_design_section_14(self):
        assert set(e.value for e in EditClass) == {
            "format_only",
            "wording_only",
            "structure_or_word_object",
            "fact_or_uncertain",
        }

    def test_fact_or_uncertain_is_distinct_from_safe_classes(self):
        assert EditClass.FACT_OR_UNCERTAIN != EditClass.WORDING_ONLY
        assert EditClass.FACT_OR_UNCERTAIN != EditClass.FORMAT_ONLY
        assert EditClass.FACT_OR_UNCERTAIN != EditClass.STRUCTURE_OR_WORD_OBJECT
