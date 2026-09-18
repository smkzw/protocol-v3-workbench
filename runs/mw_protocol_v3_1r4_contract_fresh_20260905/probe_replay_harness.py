"""Reducer + harness level probes for the 1R.4 compact-dependency review."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, "tests/protocol_v3")

from pydantic import ValidationError

from packages.contracts.workbench_contracts.protocol_v3 import NodeExecutionContract
from app.protocol_workflow.canonical.document import (
    DocumentEffectLedger,
    DocumentPayloadConflictError,
    SemanticDocumentReducer,
    document_revision_hash,
)
from app.protocol_workflow.runtime.harness import (
    ArtifactRef,
    HarnessDispatcher,
    HarnessPolicyError,
    _request_matches_binding_evidence,
    build_request,
)
from test_harness_policy import _artifact, _llm_role, _node_contract, _skill
from test_semantic_document_reducer import (
    LATER,
    NOW,
    SHA_A,
    SHA_B,
    _apply_kwargs,
    _decision,
    _document_revision,
    _semantic_block,
    _snapshot_for,
    _study_definition,
)

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, "PASS" if ok else "FAIL", detail))


reducer = SemanticDocumentReducer()

# --- R1. Version propagation over a two-step chain ---------------------------
study = _study_definition()
v1_doc = _document_revision(study)
decision = _decision(snapshot_sha256=_snapshot_for(v1_doc))
rev2_v1, _, ledger1, replayed = reducer.replay_or_apply(
    v1_doc, study, decision, DocumentEffectLedger(), now=LATER, **_apply_kwargs())
check("R1: v1 chain stays v1", rev2_v1.schema_version == "mw_protocol_v3_contract_v1" and not replayed)

v11_doc = _document_revision(study).compact_dependencies()
d2 = _decision(snapshot_sha256=_snapshot_for(v11_doc))
rev2_v11, _, ledger2, _ = reducer.replay_or_apply(
    v11_doc, study, d2, DocumentEffectLedger(), now=LATER, **_apply_kwargs())
check("R2: v1_1 chain stays v1_1", rev2_v11.schema_version == "mw_protocol_v3_contract_v1_1")
check("R3: v1_1 new revision rebinds digest",
      rev2_v11.dependency_sha256 == rev2_v11._dependency_hash(SHA_A and _apply_kwargs()["chapter_contract_hashes"]))
check("R4: v1_1 new revision tuple emptied in memory",
      rev2_v11.chapter_contract_hashes == ())
check("R5: source v1_1 revision not mutated by apply",
      v11_doc.revision == 1 and v11_doc.dependency_sha256 is not None and v11_doc.updated_at == NOW)

# --- R2. Replay under v1_1: exact tuple replays; changed tuple conflicts -----
again, _, _, replayed = reducer.replay_or_apply(
    rev2_v11, study, d2, ledger2, now=LATER, **_apply_kwargs())
check("R6: v1_1 exact replay returns same object", replayed and again is rev2_v11)
try:
    reducer.replay_or_apply(
        rev2_v11, study, d2, ledger2, now=LATER,
        **_apply_kwargs(chapter_contract_hashes=("d" * 64,)))
    check("R7: changed raw tuple under same CAS conflicts", False, "accepted silently")
except DocumentPayloadConflictError:
    check("R7: changed raw tuple under same CAS conflicts", True)

# --- R3. Snapshot binding covers the compact digest --------------------------
forged_payload = rev2_v11.model_dump(mode="json")
forged_payload["dependency_sha256"] = "e" * 64
try:
    forged = type(rev2_v11).model_validate(forged_payload)
    check("R8: forged digest on empty tuple accepted at model level (residual)",
          document_revision_hash(forged) != document_revision_hash(rev2_v11),
          "digest is inside material hash so snapshot chain still binds exact bytes")
except ValidationError as exc:
    check("R8: forged digest on empty tuple accepted at model level (residual)", True,
          "rejected: " + str(exc).splitlines()[1].strip())

# --- H1. Harness: compact contract end-to-end dispatch + revalidation --------
compact = _node_contract().compact_dependencies()
request = build_request(node_contract=compact, skill=_skill(), role_entry=_llm_role(),
                        artifacts=(_artifact(),), selected_region="cn")
check("H1: compact build_request succeeds", request.node_execution_contract_id == compact.node_execution_contract_id)
check("H2: dispatcher revalidation accepts compact request",
      _request_matches_binding_evidence(request))


class _FakeAdapter:
    identity = "deepseek/deepseek-v4-flash/direct-api"
    provider = "deepseek"
    model = "deepseek-v4-flash"
    harness = "direct-api"

    def preflight(self, request):
        from app.protocol_workflow.runtime.harness import AdapterOutcome
        return AdapterOutcome()

    def probe(self):
        return True

    def dispatch(self, request, *, session_id=None, lease=None):
        from app.protocol_workflow.runtime.harness import DispatchReceipt
        return DispatchReceipt(
            provider_session_id="sess-1",
            output_sha256="a" * 64,
            observed_provider="deepseek",
            observed_model="deepseek-v4-flash",
            output_artifact_ref="chapter-1-draft",
            output_schema_ref=request.output_schema_ref,
        )


result = HarnessDispatcher().dispatch(request=request, adapter=_FakeAdapter())
check("H3: compact contract physically dispatches", result.success and result.dispatched)

# Tampered artifact between build and dispatch → revalidation fails closed.
from app.protocol_workflow.runtime.harness import ArtifactRef as AR
tampered = build_request(node_contract=compact, skill=_skill(), role_entry=_llm_role(),
                         artifacts=(_artifact(),), selected_region="cn")
object.__setattr__(tampered, "input_artifacts", (AR(ref="seed", sha256="f" * 64),))
check("H4: post-build artifact tampering fails revalidation",
      not _request_matches_binding_evidence(tampered))

# --- H2. Duplicate artifact refs still rejected under compact ----------------
try:
    build_request(node_contract=compact, skill=_skill(), role_entry=_llm_role(),
                  artifacts=(_artifact(), _artifact()), selected_region="cn")
    check("H5: duplicate artifact refs rejected under compact", False, "accepted")
except HarnessPolicyError:
    check("H5: duplicate artifact refs rejected under compact", True)

# --- H3. v1 contract still works through the same path -----------------------
legacy_req = build_request(node_contract=_node_contract(), skill=_skill(),
                           role_entry=_llm_role(), artifacts=(_artifact(),), selected_region="cn")
check("H6: legacy v1 contract unchanged path works", legacy_req.provider_session_id is None)

# --- H4. Two revisions with same content but different versions differ -------
base = _document_revision(study)
compact_base = base.compact_dependencies()
res = reducer.replay_or_apply(
    compact_base,
    study,
    _decision(snapshot_sha256=_snapshot_for(compact_base)),
    DocumentEffectLedger(),
    now=LATER,
    **_apply_kwargs(),
)
check("R9: v1 vs v1_1 same content -> different revision hashes",
      document_revision_hash(rev2_v1) != document_revision_hash(res[0]))

print()
for name, status, detail in results:
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
failed = [r for r in results if r[1] == "FAIL"]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
