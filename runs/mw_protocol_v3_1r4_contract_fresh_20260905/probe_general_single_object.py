"""Synthetic probes for the 1R.4 compact-dependency review (general_single_object).

Readonly on product code. Evidence only; not acceptance.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterLockSnapshot,
    NodeExecutionContract,
    SemanticDocumentRevision,
    SemanticBlock,
    SubmissionEvidencePackage,
)

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
V1 = "mw_protocol_v3_contract_v1"
V1_1 = "mw_protocol_v3_contract_v1_1"

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, "PASS" if ok else "FAIL", detail))


# --- HEAD module import (read-only historical source) -----------------------
spec = importlib.util.spec_from_file_location("head_protocol_v3", "/tmp/head_protocol_v3.py")
head = importlib.util.module_from_spec(spec)
sys.modules["head_protocol_v3"] = head
spec.loader.exec_module(head)


def semantic_block(module):
    return module.SemanticBlock(
        semantic_block_id="block:summary:001",
        semantic_node_id="node:summary",
        chapter_contract_id="chapter:summary",
        substantive_content_contract_id="substantive:summary",
        block_kind="paragraph",
        content="正文",
        fact_paths=("picos.population.indication",),
        claim_evidence_link_ids=("claim:001",),
        medical_admission_unit_ids=("mau:001",),
        content_sha256=SHA_A,
    )


def doc_payload(module=None, **ov):
    p = {
        "semantic_document_revision_id": "doc:protocol:001",
        "project_id": "project:uc301",
        "revision": 1,
        "study_definition_id": "study:def:uc301",
        "study_definition_sha256": SHA_A,
        "applicability_snapshot_id": "snap:app:001",
        "applicability_snapshot_sha256": SHA_B,
        "semantic_blocks": (semantic_block(module or sys.modules["packages.contracts.workbench_contracts.protocol_v3"]),),
        "chapter_contract_hashes": (SHA_A, SHA_B),
        "updated_at": NOW,
    }
    p.update(ov)
    return p


def lock_payload(module=None, **ov):
    p = {
        "chapter_lock_snapshot_id": "lock:test",
        "semantic_node_id": "node:test",
        "semantic_document_revision_id": "doc:test",
        "semantic_document_sha256": SHA_A,
        "upstream_artifact_hashes": (SHA_A, SHA_B),
        "accepted_semantic_block_hashes": (SHA_C,),
        "locked_by_actor_id": "user:test",
        "locked_at": NOW,
    }
    p.update(ov)
    return p


def node_payload(module=None, **ov):
    p = {
        "node_execution_contract_id": "nec:test:1",
        "skill_definition_id": "skill.chapter-draft",
        "role": "product-llm",
        "harness": "direct-api",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reasoning_effort": "max",
        "same_session_recovery": True,
        "timeout_seconds": 300,
        "fallback_policy_id": "fbp:default",
        "prompt_sha256": SHA_B,
        "input_schema_ref": "in",
        "output_schema_ref": "out",
        "allowed_tools": ("deepseek-chat",),
        "allowed_paths": ("artifacts/chapter-draft/",),
        "permission_policy_id": "perm:default",
        "input_artifact_hashes": (SHA_A, SHA_B),
        "sensitivity_tier": "confidential",
        "allowed_providers": ("deepseek",),
        "allowed_regions": ("cn",),
        "redaction_policy_id": "red:default",
        "retention_policy_id": "ret:default",
        "logical_call_id": "lc:1",
        "idempotency_key": "idem-1",
    }
    p.update(ov)
    return p


def submission_payload(module=None, **ov):
    p = {
        "submission_evidence_package_id": "package:test",
        "project_id": "project:test",
        "workflow_run_id": "run:test",
        "workflow_run_sha256": SHA_A,
        "study_definition_id": "study:test",
        "study_definition_sha256": SHA_A,
        "semantic_document_revision_id": "doc:test",
        "semantic_document_sha256": SHA_B,
        "source_manifest_hashes": (SHA_A,),
        "medical_admission_unit_ids": ("unit:test",),
        "applicability_snapshot_id": "snapshot:test",
        "applicability_snapshot_sha256": SHA_B,
        "chapter_contract_hashes": (SHA_A, SHA_B),
        "skill_definition_hashes": (SHA_C,),
        "decision_record_ids": ("decision:test",),
        "qc_clean_verdict_sha256": SHA_A,
        "word_receipt_id": "receipt:test",
        "word_receipt_sha256": SHA_B,
        "projection_artifact_ids": ("artifact:test",),
        "model_versions": {"test": "1"},
        "tool_versions": {"test": "1"},
        "frozen_at": NOW,
    }
    p.update(ov)
    return p


PAIRS = [
    ("SemanticDocumentRevision", head.SemanticDocumentRevision, SemanticDocumentRevision, doc_payload),
    ("ChapterLockSnapshot", head.ChapterLockSnapshot, ChapterLockSnapshot, lock_payload),
    ("NodeExecutionContract", head.NodeExecutionContract, NodeExecutionContract, node_payload),
    ("SubmissionEvidencePackage", head.SubmissionEvidencePackage, SubmissionEvidencePackage, submission_payload),
]

# --- 1. Legacy byte/hash identity vs HEAD -----------------------------------
for name, hcls, ccls, payload in PAIRS:
    h = hcls(**payload(head))
    c = ccls(**payload())
    check(f"{name}: v1 model_dump_json bytes == HEAD", h.model_dump_json() == c.model_dump_json())
    check(f"{name}: v1 model_dump() == HEAD", h.model_dump() == c.model_dump())
    check(f"{name}: v1 material_sha256 == HEAD", h.material_sha256() == c.material_sha256())
    # Duplicate hashes rejected in v1 (moved _unique).
    if name in ("SemanticDocumentRevision", "NodeExecutionContract", "SubmissionEvidencePackage"):
        field = {"SemanticDocumentRevision": "chapter_contract_hashes",
                 "NodeExecutionContract": "input_artifact_hashes",
                 "SubmissionEvidencePackage": "chapter_contract_hashes"}[name]
        dup = payload(**{field: (SHA_A, SHA_A)})
        try:
            ccls(**dup)
            check(f"{name}: duplicate v1 hashes rejected", False, "accepted")
        except ValidationError:
            check(f"{name}: duplicate v1 hashes rejected", True)
    # Missing field rejected in v1.
    import json as _json
    missing = _json.loads(ccls(**payload()).model_dump_json())
    field = {"SemanticDocumentRevision": "chapter_contract_hashes",
             "ChapterLockSnapshot": "upstream_artifact_hashes",
             "NodeExecutionContract": "input_artifact_hashes",
             "SubmissionEvidencePackage": "chapter_contract_hashes"}[name]
    missing.pop(field)
    try:
        ccls.model_validate(missing)
        check(f"{name}: v1 missing dependency field rejected", False, "accepted")
    except ValidationError:
        check(f"{name}: v1 missing dependency field rejected", True)

# --- 2. Compaction semantics on all four types ------------------------------
for name, hcls, ccls, payload in PAIRS:
    v1 = ccls(**payload())
    before_dump = v1.model_dump_json()
    before_tuple = getattr(v1, {"SemanticDocumentRevision": "chapter_contract_hashes",
                                "ChapterLockSnapshot": "upstream_artifact_hashes",
                                "NodeExecutionContract": "input_artifact_hashes",
                                "SubmissionEvidencePackage": "chapter_contract_hashes"}[name])
    compact = v1.compact_dependencies()
    check(f"{name}: compaction leaves source v1 object unchanged",
          v1.model_dump_json() == before_dump and getattr(v1, v1.dependency_field) == before_tuple)
    check(f"{name}: compact schema_version", compact.schema_version == V1_1)
    check(f"{name}: compact dumps drop raw tuple", v1.dependency_field not in compact.model_dump(mode="json"))
    check(f"{name}: compact keeps digest", compact.dependency_sha256 == v1._dependency_hash(before_tuple))
    check(f"{name}: compact material differs from v1", compact.material_sha256() != v1.material_sha256())
    check(f"{name}: matches_dependencies accepts original order", compact.matches_dependencies(before_tuple))
    check(f"{name}: matches_dependencies rejects reordered",
          not compact.matches_dependencies(tuple(reversed(before_tuple))))
    check(f"{name}: matches_dependencies rejects missing",
          not compact.matches_dependencies(before_tuple[:-1]))
    check(f"{name}: matches_dependencies rejects substituted",
          not compact.matches_dependencies((SHA_C,) + before_tuple[1:]))
    check(f"{name}: matches_dependencies rejects duplicated actuals",
          not compact.matches_dependencies(before_tuple + before_tuple))
    rt = type(compact).model_validate_json(compact.model_dump_json())
    check(f"{name}: compact json round-trip equal", rt == compact)
    check(f"{name}: compaction idempotent", compact.compact_dependencies() == compact)
    # Conflicting raw tuple + digest rejected for every type.
    conflicting = compact.model_dump(mode="json")
    conflicting[v1.dependency_field] = [SHA_C] * len(before_tuple)
    try:
        type(compact).model_validate(conflicting)
        check(f"{name}: conflicting tuple+digest rejected", False, "accepted")
    except ValidationError as exc:
        check(f"{name}: conflicting tuple+digest rejected", True, str(exc).splitlines()[1].strip())
    # Empty tuple + arbitrary digest accepted? (expected: accepted — opaque digest)
    empty = compact.model_dump(mode="json")
    empty.pop(v1.dependency_field, None)
    empty["dependency_sha256"] = "f" * 64
    try:
        accepted = type(compact).model_validate(empty)
        check(f"{name}: v1_1 empty-tuple + foreign digest accepted (design gap?)", True,
              f"accepted, matches_dependencies(original)={accepted.matches_dependencies(before_tuple)}")
    except ValidationError as exc:
        check(f"{name}: v1_1 empty-tuple + foreign digest accepted (design gap?)", True,
              "rejected: " + str(exc).splitlines()[1].strip())
    # Immutability of compact instance.
    try:
        setattr(compact, "dependency_sha256", SHA_A)
        check(f"{name}: compact frozen", False, "mutable")
    except ValidationError:
        check(f"{name}: compact frozen", True)

# --- 3. Cross-version equality / equality of identical compactions ----------
a = SemanticDocumentRevision(**doc_payload()).compact_dependencies()
b = SemanticDocumentRevision(**doc_payload()).compact_dependencies()
check("doc: two independent compactions equal material hash", a.material_sha256() == b.material_sha256())
changed = SemanticDocumentRevision(**doc_payload(chapter_contract_hashes=(SHA_A, SHA_C))).compact_dependencies()
check("doc: chapter change changes compact material hash", changed.material_sha256() != a.material_sha256())

# --- 4. matches_dependencies list-vs-tuple asymmetry (cosmetic) --------------
nc = NodeExecutionContract(**node_payload())
compact_nc = nc.compact_dependencies()
check("node: list arg accepted by compact digest (asymmetry)", compact_nc.matches_dependencies([SHA_A, SHA_B]))
check("node: list arg rejected by legacy tuple compare", not nc.matches_dependencies([SHA_A, SHA_B]))

# --- 5. v1_1 payload omitting digest entirely --------------------------------
no_digest = compact_nc.model_dump(mode="json")
no_digest.pop("dependency_sha256")
try:
    NodeExecutionContract.model_validate(no_digest)
    check("node: v1_1 without digest rejected", False, "accepted")
except ValidationError:
    check("node: v1_1 without digest rejected", True)

# --- 6. JSON schema surface ---------------------------------------------------
schema = NodeExecutionContract.model_json_schema()
check("schema: dependency_sha256 exposed in JSON schema (surface change, note only)",
      "dependency_sha256" in schema.get("properties", {}))

# --- 7. Domain separation between fields -------------------------------------
digest_doc = SemanticDocumentRevision(**doc_payload()).compact_dependencies().dependency_sha256
digest_sub = SubmissionEvidencePackage(**submission_payload(chapter_contract_hashes=(SHA_A, SHA_B))).compact_dependencies().dependency_sha256
check("domain: same hashes different fields -> different digests", digest_doc != digest_sub)

print()
for name, status, detail in results:
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
failed = [r for r in results if r[1] == "FAIL"]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
