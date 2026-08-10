#!/usr/bin/env python3
"""Build and verify the permanent Protocol v3 functional failure corpus.

The corpus freezes product failures that must remain rejected by later E0, E3,
W1, and P1-G1 implementations.  It contains only compact, controlled fixtures and
durable evidence locators.  The deleted r17 runtime is never treated as
recovered; its two content failures are explicitly evidence-reconstructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


CORPUS_SCHEMA_VERSION = "protocol_v3_failure_corpus_v1"
FIXTURE_SCHEMA_VERSION = "protocol_v3_failure_fixture_v1"
MANIFEST_ID = "mw_protocol_v3_permanent_failure_corpus_v1"

REQUIRED_FILES = (
    "r17_thin_eligibility.json",
    "heading_only.json",
    "generic_long_body.json",
    "empty_protocol_d017.json",
    "zero_registry_result.json",
    "batch_reject_resurrection.json",
    "unknown_outcome.json",
    "checkpoint_event_split_brain.json",
)

EXPECTED_META = {
    "r17_thin_eligibility.json": (
        "mwp3fail_e3_evidence_thin_eligibility_v1",
        "protocol_v3:failure:E3:evidence:thin_eligibility:v1",
        "MW-PRO-E3-EVIDENCE-THIN_ELIGIBILITY",
        "E3",
        "agent_1_medical_admission",
        "evidence_reconstructed",
    ),
    "heading_only.json": (
        "mwp3fail_e3_evidence_heading_only_v1",
        "protocol_v3:failure:E3:evidence:heading_only:v1",
        "MW-PRO-E3-EVIDENCE-HEADING_ONLY",
        "E3",
        "agent_1_medical_admission",
        "evidence_reconstructed",
    ),
    "generic_long_body.json": (
        "mwp3fail_e3_evidence_generic_body_v1",
        "protocol_v3:failure:E3:evidence:generic_body:v1",
        "MW-PRO-E3-EVIDENCE-GENERIC_BODY",
        "E3",
        "agent_1_medical_admission",
        "controlled_synthetic",
    ),
    "empty_protocol_d017.json": (
        "mwp3fail_w1_document_skeleton_only_v1",
        "protocol_v3:failure:W1:document:skeleton_only:v1",
        "MW-PRO-W1-DOCUMENT-SKELETON_ONLY",
        "W1",
        "agent_3_protocol_writer",
        "observed_artifact",
    ),
    "zero_registry_result.json": (
        "mwp3fail_e0_source_zero_result_unexplained_v1",
        "protocol_v3:failure:E0:source:zero_result_unexplained:v1",
        "MW-PRO-E0-SOURCE-ZERO_RESULT_UNEXPLAINED",
        "E0",
        "agent_1_source_acquisition",
        "controlled_synthetic",
    ),
    "batch_reject_resurrection.json": (
        "mwp3fail_e3_decision_reject_resurrected_v1",
        "protocol_v3:failure:E3:decision:reject_resurrected:v1",
        "MW-PRO-E3-DECISION-REJECT_RESURRECTED",
        "E3",
        "agent_1_medical_admission",
        "evidence_reconstructed",
    ),
    "unknown_outcome.json": (
        "mwp3fail_p1g1_execution_unknown_outcome_redispatch_v1",
        "protocol_v3:failure:P1-G1:execution:unknown_outcome_redispatch:v1",
        "MW-PRO-P1G1-EXECUTION-UNKNOWN_OUTCOME_REDISPATCH",
        "P1-G1",
        "agent_5_workflow_control",
        "controlled_synthetic",
    ),
    "checkpoint_event_split_brain.json": (
        "mwp3fail_p1g1_state_checkpoint_event_mismatch_v1",
        "protocol_v3:failure:P1-G1:state:checkpoint_event_mismatch:v1",
        "MW-PRO-P1G1-STATE-CHECKPOINT_EVENT_MISMATCH",
        "P1-G1",
        "agent_5_workflow_control",
        "controlled_synthetic",
    ),
}

FIXTURE_KEYS = {
    "schema_version",
    "fixture_id",
    "failure_identity",
    "failure_code",
    "title",
    "source_locator",
    "expected_gate",
    "owner",
    "provenance",
    "original_runtime_available",
    "expected_result",
    "must_remain_negative",
    "xfail",
    "skip",
    "failure_reason",
    "payload",
}

SOURCE_LOCATOR_KEYS = {"kind", "path", "lines", "evidence"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FailureCorpusError(RuntimeError):
    """Raised when the permanent functional regression identity drifts."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_file_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source(path: str, lines: str, evidence: str, *, kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "path": path,
        "lines": lines,
        "evidence": evidence,
    }


def _fixture(
    filename: str,
    *,
    title: str,
    source_locator: Mapping[str, str],
    original_runtime_available: bool,
    failure_reason: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    fixture_id, identity, code, gate, owner, provenance = EXPECTED_META[filename]
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "failure_identity": identity,
        "failure_code": code,
        "title": title,
        "source_locator": dict(source_locator),
        "expected_gate": gate,
        "owner": owner,
        "provenance": provenance,
        "original_runtime_available": original_runtime_available,
        "expected_result": "fail_closed",
        "must_remain_negative": True,
        "xfail": False,
        "skip": False,
        "failure_reason": failure_reason,
        "payload": dict(payload),
    }


def build_fixture_documents() -> dict[str, dict[str, Any]]:
    thin_text = (
        "本节概述研究对象资格要求，但未列出任何可执行的入选或排除标准，也未给出任何具体判定条件。"
    )
    generic_text = (
        "本研究将遵循科学、规范和可操作的原则开展，并根据受试者具体情况进行综合评估。"
        "研究过程中将持续关注疗效与安全性，按照方案要求完成相关观察、记录和分析。"
        "研究团队将依据适用法规和质量管理要求实施研究，确保各项工作有序推进。"
        "如出现需要进一步判断的情况，将结合研究实际进行综合考虑并采取适当措施。"
        "所有研究活动均应保持一致性和完整性，并在必要时根据总体情况进行合理调整。"
        "本段未说明研究药物、目标人群、对照、终点、评估工具、时间点或统计假设。"
    )

    return {
        "r17_thin_eligibility.json": _fixture(
            "r17_thin_eligibility.json",
            title="r17 资格标准引言被误作实质准入证据",
            source_locator=_source(
                "legacy_workbench:runs/mw_protocol_p0_max_clean_rounds_20260805.md",
                "225-240",
                "报告记录 44 字资格标准引言被批量准入，且无 objectives/endpoints 可用证据。",
                kind="durable_report",
            ),
            original_runtime_available=False,
            failure_reason=(
                "文本只有资格标准引言，没有任何逐条入选/排除条件、判定阈值或目标 claim；"
                "字符数或标题存在不能替代 MedicalAdmissionUnit 的正向内容合同。"
            ),
            payload={
                "reconstructed_text": thin_text,
                "observed_character_count": 44,
                "content_status": "incomplete_eligibility_criterion",
                "target_claims": [],
                "criteria_items": [],
                "context_before": "Eligibility Criteria",
                "context_after": "具体标准未出现在候选 span 中",
                "source_role": "competitor_protocol_eligibility",
                "runtime_note": (
                    "该文本为按耐久报告约束构造的最小重建样例，不是已删除 r18 runtime 的逐字恢复。"
                ),
            },
        ),
        "heading_only.json": _fixture(
            "heading_only.json",
            title="只有目标标题、没有 objectives/endpoints 实质证据",
            source_locator=_source(
                "legacy_workbench:runs/role_acceptance/"
                "mw_protocol_p0_20260805_round17_engineer_cursor_full_protocol_semantic_span_selection.md",
                "6-9",
                "r17 报告记录 heading-only objectives span，最终无 objectives/endpoints 准入。",
                kind="durable_report",
            ),
            original_runtime_available=False,
            failure_reason=(
                "标题不能证明目标、终点定义、评估工具或时间点；正文和 target claim 均为空。"
            ),
            payload={
                "heading": "Objectives and Endpoints",
                "body": "",
                "target_claims": [],
                "endpoint_definitions": [],
                "locator": "reconstructed://r17/objectives_endpoints/heading",
                "source_role": "competitor_protocol_objectives_endpoints",
                "runtime_note": (
                    "仅重建耐久报告确认的失败形态，不声称恢复原始 span。"
                ),
            },
        ),
        "generic_long_body.json": _fixture(
            "generic_long_body.json",
            title="长篇通用套话缺少研究特异 claim 和事实绑定",
            source_locator=_source(
                "approved_design:plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
                "416-422,516-527",
                "设计明确长通用段落、短无目标 claim 和真空 Chapter Contract 必须失败。",
                kind="approved_design",
            ),
            original_runtime_available=False,
            failure_reason=(
                "字数充足但不含研究药物、人群、对照、终点、评估时间点或统计假设，"
                "对其他项目仍可原样成立。"
            ),
            payload={
                "text": generic_text,
                "character_count": len(generic_text),
                "study_specific_claim_count": 0,
                "study_definition_bindings": [],
                "required_object_bindings": [],
                "source_role": "generic_generated_body",
            },
        ),
        "empty_protocol_d017.json": _fixture(
            "empty_protocol_d017.json",
            title="D017 结构完整但正文近乎空白的骨架方案",
            source_locator=_source(
                "legacy_workbench:runs/MW_SYSTEM_REARCHITECTURE_AUDIT_CHECKPOINT_20260808.md",
                "9-10",
                "只读审计确认 106 个标题、28 页、正文段落字符 2,627、2 表、0 图。",
                kind="durable_audit",
            ),
            original_runtime_available=True,
            failure_reason=(
                "页面和标题数量不能替代适用章节的实质 claim/object/fact/evidence 覆盖；"
                "该产物不得进入 W1 正向路径。"
            ),
            payload={
                "artifact_locator": (
                    "legacy_workbench:records/active_slices/"
                    "medical_writing_ai_first_docx_release_v2_20260720/"
                    "word_acceptance_final_20260720/"
                    "project_A_D017_PNH_synopsis_import_word.docx"
                ),
                "artifact_sha256": (
                    "bae34f096ef5769a8d025ac03f72d9dfed06278d03faef97dff33beaae9705e9"
                ),
                "rendered_page_count": 28,
                "heading_count": 106,
                "paragraph_text_character_count": 2627,
                "table_count": 2,
                "figure_count": 0,
                "controlled_heading_sample": [
                    "方案概要",
                    "方案摘要",
                    "研究背景和立项依据",
                    "研究目的及终点",
                ],
                "substantive_coverage_complete": False,
                "skeleton_risk": True,
            },
        ),
        "zero_registry_result.json": _fixture(
            "zero_registry_result.json",
            title="零注册库结果未经根因调查即被视为充分检索",
            source_locator=_source(
                "approved_design:plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
                "348-377,899-906",
                "Gate E0 要求区分真实零结果、查询/连通性/术语问题并可复现根因。",
                kind="approved_design",
            ),
            original_runtime_available=False,
            failure_reason=(
                "零结果本身不是完整检索证据；未验证连通性、术语扩展、适应症同义词、"
                "过滤条件和替代查询时必须停在 E0 并给出问题卡。"
            ),
            payload={
                "registry": "ClinicalTrials.gov",
                "query": "非标准适应症简称",
                "result_count": 0,
                "connectivity_verified": False,
                "registry_response_verified": False,
                "synonym_queries_attempted": [],
                "filter_relaxation_attempted": False,
                "root_cause": "not_investigated",
                "incorrect_downstream_state": "source_acquisition_complete",
            },
        ),
        "batch_reject_resurrection.json": _fixture(
            "batch_reject_resurrection.json",
            title="单项拒绝被一键批量操作无证据复活",
            source_locator=_source(
                "legacy_workbench:runs/mw_protocol_p0_max_clean_rounds_20260805.md",
                "232-240",
                "可见单项先拒绝，随后批量确认把同一薄弱 item 纳入。",
                kind="durable_report",
            ),
            original_runtime_available=False,
            failure_reason=(
                "同一 item revision 的最新实质 verdict=REJECT 具有优先级；没有新证据、"
                "新 revision 和重新审阅时，batch action 不得改为 ADMITTED。"
            ),
            payload={
                "item_id": "reconstructed_r17_thin_eligibility_item",
                "item_revision": 1,
                "evidence_hash": "a" * 64,
                "latest_item_verdict": "reject",
                "batch_action": "accept_all_recommendations",
                "resulting_state": "admitted",
                "new_evidence_hash": None,
                "new_item_revision": None,
                "rereview_verdict": None,
            },
        ),
        "unknown_outcome.json": _fixture(
            "unknown_outcome.json",
            title="模型调用结果未知时被重新派发造成重复语义效果",
            source_locator=_source(
                "approved_design:plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
                "666-705,983-986",
                "ExecutionReservation 必须将 unknown_outcome 与显式恢复/重试决定绑定。",
                kind="approved_design",
            ),
            original_runtime_available=False,
            failure_reason=(
                "首次 transport 已可能到达供应商；unknown_outcome 不能自动创建第二次模型调用，"
                "必须恢复同一 reservation/session 或形成可审计 retry decision。"
            ),
            payload={
                "reservation_id": "mwexecres_unknown_outcome_fixture_v1",
                "idempotency_key": "protocol-v3:fixture:unknown-outcome:v1",
                "logical_call_id": "mwlogicalcall_unknown_fixture_v1",
                "state": "unknown_outcome",
                "transport_attempts": 2,
                "same_session_recovery_attempted": False,
                "explicit_retry_decision_id": None,
                "semantic_effect_count": 2,
            },
        ),
        "checkpoint_event_split_brain.json": _fixture(
            "checkpoint_event_split_brain.json",
            title="编排 checkpoint 与领域事件提交状态分裂",
            source_locator=_source(
                "approved_design:plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
                "286-330,883-892",
                "应用事件与调度 checkpoint 分离时，两种提交顺序缺口都必须 fail closed 并恢复。",
                kind="approved_design",
            ),
            original_runtime_available=False,
            failure_reason=(
                "任一侧提交、另一侧缺失都会使投影或重放产生不一致；不得按任一单侧状态宣称节点完成。"
            ),
            payload={
                "run_id": "mwworkflow_split_brain_fixture_v1",
                "cases": [
                    {
                        "case_id": "event_committed_checkpoint_missing",
                        "domain_event_committed": True,
                        "checkpoint_committed": False,
                        "incorrect_state": "node_complete",
                    },
                    {
                        "case_id": "checkpoint_committed_event_missing",
                        "domain_event_committed": False,
                        "checkpoint_committed": True,
                        "incorrect_state": "node_complete",
                    },
                ],
                "reconciliation_decision_id": None,
            },
        ),
    }


def build_positive_control() -> dict[str, Any]:
    return {
        "control_id": "mwp3control_e3_short_substantive_primary_endpoint_v1",
        "expected_gate": "E3",
        "expected_result": "pass",
        "provenance": "controlled_synthetic",
        "text": "主要终点为第12周平均每日症状评分较基线的变化。",
        "claim_type": "primary_endpoint_definition",
        "source_role": "competitor_protocol_primary_endpoint",
        "source_locator": "synthetic://protocol/objectives_endpoints/primary#p1",
        "context_before": "主要疗效终点",
        "context_after": "在预先规定的时间点进行评估",
        "study_definition_binding": "study.endpoints.primary[0]",
        "evidence_class": "competitor_protocol",
    }


def _manifest_entry(filename: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "file": filename,
        "sha256": sha256_bytes(json_file_bytes(fixture)),
        "fixture_id": fixture["fixture_id"],
        "failure_identity": fixture["failure_identity"],
        "failure_code": fixture["failure_code"],
        "expected_gate": fixture["expected_gate"],
        "owner": fixture["owner"],
        "provenance": fixture["provenance"],
        "expected_result": fixture["expected_result"],
    }


def build_manifest(fixtures: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    entries = [_manifest_entry(name, fixtures[name]) for name in REQUIRED_FILES]
    identity_material = [
        {
            "fixture_id": entry["fixture_id"],
            "failure_identity": entry["failure_identity"],
            "failure_code": entry["failure_code"],
            "expected_gate": entry["expected_gate"],
        }
        for entry in entries
    ]
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "manifest_id": MANIFEST_ID,
        "fixture_count": len(entries),
        "required_files": list(REQUIRED_FILES),
        "fixtures": entries,
        "cross_layer_identity_sha256": sha256_bytes(
            canonical_json_bytes(identity_material)
        ),
        "positive_controls": [build_positive_control()],
        "immutability_contract": {
            "allow_fixture_deletion": False,
            "allow_expected_gate_change": False,
            "allow_xfail": False,
            "allow_skip": False,
            "allow_identity_reuse": False,
            "change_requires_new_schema_version": True,
        },
        "provenance_note": (
            "r17 content fixtures are evidence-reconstructed from durable reports; "
            "the deleted r18 runtime and deleted parent-session rows were not recovered."
        ),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FailureCorpusError(message)


def validate_positive_control(control: Mapping[str, Any]) -> None:
    required = {
        "control_id",
        "expected_gate",
        "expected_result",
        "provenance",
        "text",
        "claim_type",
        "source_role",
        "source_locator",
        "context_before",
        "context_after",
        "study_definition_binding",
        "evidence_class",
    }
    _require(set(control) == required, "positive control schema drift")
    _require(control["expected_gate"] == "E3", "positive control gate drift")
    _require(control["expected_result"] == "pass", "positive control must pass")
    _require(
        0 < len(str(control["text"])) < 44,
        "positive control must remain shorter than the r17 failure",
    )
    for key in (
        "claim_type",
        "source_role",
        "source_locator",
        "context_before",
        "context_after",
        "study_definition_binding",
        "evidence_class",
    ):
        _require(bool(control[key]), f"positive control missing {key}")


def validate_fixture(filename: str, fixture: Mapping[str, Any]) -> None:
    _require(set(fixture) == FIXTURE_KEYS, f"{filename}: fixture schema drift")
    expected = EXPECTED_META[filename]
    actual = (
        fixture["fixture_id"],
        fixture["failure_identity"],
        fixture["failure_code"],
        fixture["expected_gate"],
        fixture["owner"],
        fixture["provenance"],
    )
    _require(actual == expected, f"{filename}: stable identity or owner drift")
    _require(
        fixture["schema_version"] == FIXTURE_SCHEMA_VERSION,
        f"{filename}: schema_version drift",
    )
    _require(
        set(fixture["source_locator"]) == SOURCE_LOCATOR_KEYS,
        f"{filename}: source locator schema drift",
    )
    _require(
        str(fixture["source_locator"]["path"]).startswith(
            ("legacy_workbench:", "approved_design:")
        ),
        f"{filename}: source locator must be durable and relative",
    )
    _require(fixture["expected_result"] == "fail_closed", f"{filename}: must fail")
    _require(fixture["must_remain_negative"] is True, f"{filename}: negative pin lost")
    _require(fixture["xfail"] is False, f"{filename}: xfail is forbidden")
    _require(fixture["skip"] is False, f"{filename}: skip is forbidden")
    _require(bool(fixture["failure_reason"]), f"{filename}: missing failure reason")

    payload = fixture["payload"]
    if filename == "r17_thin_eligibility.json":
        _require(fixture["original_runtime_available"] is False, "r17 runtime claim drift")
        _require(
            len(payload["reconstructed_text"]) == payload["observed_character_count"] == 44,
            "r17 thin eligibility must remain a 44-character reconstruction",
        )
        _require(not payload["target_claims"], "thin eligibility gained target claims")
        _require(not payload["criteria_items"], "thin eligibility gained criteria")
        _require("不是" in payload["runtime_note"], "reconstruction disclaimer missing")
    elif filename == "heading_only.json":
        _require(fixture["original_runtime_available"] is False, "r17 runtime claim drift")
        _require(bool(payload["heading"]) and payload["body"] == "", "heading-only drift")
        _require(not payload["target_claims"], "heading-only fixture gained claims")
        _require(not payload["endpoint_definitions"], "heading-only fixture gained endpoints")
    elif filename == "generic_long_body.json":
        _require(payload["character_count"] == len(payload["text"]), "generic length drift")
        _require(payload["character_count"] >= 200, "generic fixture is no longer long")
        _require(payload["study_specific_claim_count"] == 0, "generic fixture gained claims")
        _require(not payload["study_definition_bindings"], "generic fixture gained facts")
    elif filename == "empty_protocol_d017.json":
        _require(SHA256_RE.fullmatch(payload["artifact_sha256"]) is not None, "bad D017 hash")
        _require(payload["heading_count"] == 106, "D017 heading count drift")
        _require(payload["paragraph_text_character_count"] == 2627, "D017 text count drift")
        _require(payload["rendered_page_count"] == 28, "D017 page count drift")
        _require(payload["table_count"] == 2, "D017 table count drift")
        _require(payload["figure_count"] == 0, "D017 figure count drift")
        _require(payload["skeleton_risk"] is True, "D017 skeleton risk lost")
    elif filename == "zero_registry_result.json":
        _require(payload["result_count"] == 0, "zero-result fixture drift")
        _require(payload["root_cause"] == "not_investigated", "zero-result root cause drift")
        _require(payload["connectivity_verified"] is False, "zero-result was investigated")
        _require(not payload["synonym_queries_attempted"], "zero-result gained alternate query")
    elif filename == "batch_reject_resurrection.json":
        _require(payload["latest_item_verdict"] == "reject", "reject verdict drift")
        _require(payload["resulting_state"] == "admitted", "resurrection failure drift")
        _require(payload["new_evidence_hash"] is None, "resurrection gained evidence")
        _require(payload["new_item_revision"] is None, "resurrection gained revision")
        _require(payload["rereview_verdict"] is None, "resurrection gained rereview")
    elif filename == "unknown_outcome.json":
        _require(payload["state"] == "unknown_outcome", "unknown outcome state drift")
        _require(payload["transport_attempts"] > 1, "duplicate dispatch failure drift")
        _require(
            payload["same_session_recovery_attempted"] is False,
            "unknown outcome gained same-session recovery",
        )
        _require(payload["explicit_retry_decision_id"] is None, "retry decision appeared")
        _require(payload["semantic_effect_count"] > 1, "duplicate semantic effect drift")
    elif filename == "checkpoint_event_split_brain.json":
        cases = payload["cases"]
        _require(len(cases) == 2, "split-brain case coverage drift")
        pairs = {(c["domain_event_committed"], c["checkpoint_committed"]) for c in cases}
        _require(pairs == {(True, False), (False, True)}, "split-brain directions drift")
        _require(payload["reconciliation_decision_id"] is None, "fixture gained reconciliation")


def write_corpus(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixture_documents()
    for filename in REQUIRED_FILES:
        (output_dir / filename).write_bytes(json_file_bytes(fixtures[filename]))
    manifest = build_manifest(fixtures)
    (output_dir / "manifest.json").write_bytes(json_file_bytes(manifest))
    verify_failure_corpus(output_dir)
    return manifest


def verify_failure_corpus(corpus_dir: Path) -> Mapping[str, Any]:
    manifest_path = corpus_dir / "manifest.json"
    _require(manifest_path.is_file(), "manifest.json is missing")
    actual_files = sorted(path.name for path in corpus_dir.glob("*.json"))
    expected_files = sorted(("manifest.json",) + REQUIRED_FILES)
    _require(actual_files == expected_files, "failure corpus file set drift")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_fixtures = build_fixture_documents()
    expected_manifest = build_manifest(expected_fixtures)
    _require(manifest == expected_manifest, "manifest identity or expected gate drift")

    identities: set[str] = set()
    codes: set[str] = set()
    for entry in manifest["fixtures"]:
        filename = entry["file"]
        path = corpus_dir / filename
        _require(path.is_file(), f"{filename}: fixture is missing")
        raw = path.read_bytes()
        _require(sha256_bytes(raw) == entry["sha256"], f"{filename}: sha256 drift")
        fixture = json.loads(raw.decode("utf-8"))
        _require(fixture == expected_fixtures[filename], f"{filename}: fixture content drift")
        validate_fixture(filename, fixture)
        _require(fixture["failure_identity"] not in identities, "duplicate failure identity")
        _require(fixture["failure_code"] not in codes, "duplicate failure code")
        identities.add(fixture["failure_identity"])
        codes.add(fixture["failure_code"])

    _require(len(identities) == len(REQUIRED_FILES), "identity coverage drift")
    controls = manifest["positive_controls"]
    _require(len(controls) == 1, "positive control count drift")
    validate_positive_control(controls[0])
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/protocol_v3/failure_corpus"),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.write:
        manifest = write_corpus(args.output)
    else:
        manifest = verify_failure_corpus(args.output)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "write" if args.write else "check",
                "fixture_count": manifest["fixture_count"],
                "manifest_id": manifest["manifest_id"],
                "cross_layer_identity_sha256": manifest["cross_layer_identity_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
