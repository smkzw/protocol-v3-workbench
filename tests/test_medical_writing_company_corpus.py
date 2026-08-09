from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.medical_writing_company_corpus import (
    MANIFEST_PATH,
    SNAPSHOT_PATH,
    MedicalWritingCompanyCorpusService,
)
from services.api.app.medical_writing import MedicalWritingRevisionService
from packages.contracts.workbench_contracts import ProtocolDocument, ProtocolSection


def test_company_corpus_snapshot_is_self_contained_and_highest_source_is_first():
    service = MedicalWritingCompanyCorpusService()
    definition = service.definition()

    assert SNAPSHOT_PATH.is_file()
    assert MANIFEST_PATH.is_file()
    assert definition.entry_count == 3878
    assert definition.snapshot_sha256 == (
        "ae13656aca40b5fda099528bd1e8d449ad0ebb235013639495a628a1b0d23c1c"
    )
    assert definition.supplemental_sources[0]["file_name"] == (
        "CMS-D017-PNH-方案摘要_v0.2.docx"
    )
    assert definition.supplemental_sources[0]["authority_priority"] == 0


def test_company_corpus_search_prefers_relevant_prose_and_preserves_provenance():
    service = MedicalWritingCompanyCorpusService()
    items = service.search("妊娠检查 hCG FSH", section_heading="安全性评估", limit=5)

    assert len(items) == 5
    assert all(item["block_type"] not in {"table", "table_row"} for item in items)
    assert any("FSH" in item["text"] for item in items[:3])
    assert all(item["snapshot_sha256"] == service.definition().snapshot_sha256 for item in items)
    assert all(item["entry_id"] and item["text"] and item["source_file"] for item in items)
    assert all(item["selection"]["score_components"] for item in items)


def test_company_corpus_can_return_table_rows_only_when_requested():
    service = MedicalWritingCompanyCorpusService()
    default_items = service.search("妊娠检查 hCG FSH", limit=5)
    table_items = service.search(
        "妊娠检查 hCG FSH",
        limit=5,
        include_table_rows=True,
    )

    assert all(item["block_type"] not in {"table", "table_row"} for item in default_items)
    assert any(item["block_type"] in {"table", "table_row"} for item in table_items)


def test_company_corpus_manifest_tampering_fails_closed(tmp_path: Path):
    snapshot = tmp_path / "snapshot.jsonl"
    manifest = tmp_path / "snapshot.manifest.json"
    snapshot.write_text('{"entry_id":"x"}\n', encoding="utf-8")
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["snapshot_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        MedicalWritingCompanyCorpusService(snapshot, manifest).definition()


def test_company_corpus_applies_p0_only_inside_synopsis_scope():
    service = MedicalWritingCompanyCorpusService()

    synopsis = service.search(
        "PNH 活动性溶血 血红蛋白 主要终点",
        section_heading="方案概要",
        section_number="1.1",
        project_indication="阵发性睡眠性血红蛋白尿症",
        limit=3,
    )
    safety = service.search(
        "严重不良事件 报告 随访",
        section_heading="不良事件定义与报告",
        section_number="9.2",
        limit=5,
    )

    assert synopsis[0]["source_file"] == "CMS-D017-PNH-方案摘要_v0.2.docx"
    assert synopsis[0]["selection"]["corpus_function"] == "synopsis"
    assert safety[0]["source_role"] == "full_protocol_style_and_clause_reference"
    assert safety[0]["selection"]["corpus_function"] == "reusable_clause"


def test_company_corpus_does_not_invent_unresolved_project_dosing_from_weak_matches():
    service = MedicalWritingCompanyCorpusService()

    items = service.search(
        "具体服药剂量及频率",
        section_heading="方案概要",
        section_number="1.1",
        project_indication="阵发性睡眠性血红蛋白尿症",
        limit=5,
    )

    assert items == []


def test_company_corpus_lower_priority_ra_source_wins_when_project_and_soa_match():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "访视 研究阶段 研究日",
        section_heading="研究流程表",
        section_number="1.3",
        project_indication="类风湿关节炎",
        limit=5,
    )

    assert any(item["source_file"].startswith("MY004-RA-2b") for item in items[:3])
    assert any(item["block_type"] == "table_row" for item in items[:3])
    assert all(item["selection"]["corpus_function"] == "table_soa" for item in items)


def test_company_corpus_excludes_cross_indication_disease_specific_entries():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "特应性皮炎 入选标准 EASI",
        section_heading="入选标准",
        section_number="5.2",
        project_indication="特应性皮炎",
        limit=10,
    )

    assert any("AD" in item["source_file"] for item in items)
    assert not any(
        item["source_file"] == "CMS-D017-PNH-方案摘要_v0.2.docx"
        and item["reuse_level"] == "disease_specific_reference"
        for item in items
    )


def test_company_corpus_query_cannot_inject_a_different_project_indication():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "肥胖 减重 剂量探索 方案概要",
        section_heading="方案概要",
        section_number="1.1",
        project_indication="类风湿关节炎",
        project_phase="IIb期",
        limit=10,
    )

    d005_items = [item for item in items if item["source_file"].startswith("CMS-D005")]
    assert d005_items
    assert all(item["selection"]["project_match"] == 0.0 for item in d005_items)
    assert all(
        item["selection"]["project_match_reason"] == "indication_mismatch"
        for item in d005_items
    )


def test_company_corpus_same_indication_distinguishes_matching_and_mismatched_phase():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "特应性皮炎 入选标准 EASI",
        section_heading="入选标准",
        section_number="5.1",
        project_indication="特应性皮炎",
        project_phase="II期",
        limit=10,
    )

    phase_ii = next(item for item in items if item["source_file"].startswith("CMD-D001"))
    phase_iii = next(item for item in items if item["source_file"].startswith("MG-K10"))
    assert phase_ii["selection"]["project_match"] == 1.0
    assert "matched_phase:2" in phase_ii["selection"]["project_match_reason"]
    assert phase_iii["selection"]["project_match"] == 0.65
    assert "phase_mismatch:2" in phase_iii["selection"]["project_match_reason"]


def test_company_corpus_filters_navigation_and_contact_noise():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "多中心 随机 双盲 安慰剂对照 研究设计",
        section_heading="研究设计",
        section_number="4.1",
        limit=10,
    )

    assert all("电话：" not in item["text"] for item in items)
    assert all(not item["selection"]["quality_flags"] == ["navigation_entry_not_clause"] for item in items)
    assert any("本研究" in item["text"] and "随机" in item["text"] for item in items[:3])


def test_company_corpus_keeps_latin_abbreviations_separate():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "hCG FSH",
        section_heading="妊娠检查",
        section_number="8.4",
        limit=5,
    )

    assert "FSH" in items[0]["text"]
    assert items[0]["selection"]["score_components"]["latin_token_coverage"] == 1.0


def test_company_corpus_maps_poc_and_pd_to_regulatory_chinese_equivalents():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "炎症性皮肤病 PoC 药效学 皮肤活检",
        section_heading="研究设计",
        section_number="4.1",
        project_indication="特应性皮炎",
        limit=5,
    )

    assert items[0]["source_file"] == "MY004567片-炎症性皮肤病-方案摘要-V0.4-clean.docx"
    assert "概念验证" in items[0]["text"]
    assert items[0]["selection"]["score_components"]["anchor_term_coverage"] >= 0.5


def test_company_corpus_prefers_complete_confidentiality_clause_over_partial_term_hits():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "保密声明 伦理委员会 监督管理部门",
        section_heading="首页保密声明",
        section_number="0",
        limit=5,
    )

    assert items[0]["source_file"] == "CMS-D017-PNH-方案摘要_v0.2.docx"
    assert items[0]["text"].startswith("保密声明：")
    assert items[0]["selection"]["score_components"]["anchor_term_coverage"] == 1.0


def test_company_corpus_reassembles_split_estimand_table_with_traceable_entries():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "估计目标 伴发事件策略 目标人群 变量 群体层面汇总",
        section_heading="估计目标",
        section_number="3.1",
        limit=5,
    )

    assert items
    assert items[0]["source_file"].startswith("CMS-D005-减重II期")
    assert items[0]["source_file"].endswith("(2).docx")
    assert len(items[0]["source_entry_ids"]) == 2
    assert all(
        term in items[0]["text"]
        for term in ("目标人群", "治疗", "终点变量", "伴发事件", "总体效应度量")
    )
    assert items[0]["selection"]["reconstruction"]["source_entry_ids"] == items[0]["source_entry_ids"]


def test_company_corpus_reassembles_complete_contraception_clause():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "育龄女性 避孕 方法 持续时间",
        section_heading="避孕要求",
        section_number="5.4",
        limit=5,
    )

    assert items
    assert items[0]["source_file"].startswith("MG-K10-青少年AD")
    assert len(items[0]["source_entry_ids"]) >= 4
    assert "末次给药后6 个月" in items[0]["text"]
    assert "激素避孕药" in items[0]["text"]
    assert "输精管结扎" in items[0]["text"]


def test_company_corpus_ae_mh_boundary_requires_a_complete_rule():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "首次给药前 病史 首次给药后 不良事件 AE",
        section_heading="不良事件与病史边界",
        section_number="9.2",
        limit=5,
    )

    assert items
    assert "首次给药前" in items[0]["text"]
    assert "作为病史/伴随疾病记录" in items[0]["text"]
    assert "作为 AE 予以记录和报告" in items[0]["text"]


def test_company_corpus_distinguishes_ae_definition_from_teae_definition():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "不良事件 是指 任何不利医学事件 不一定有因果关系",
        section_heading="不良事件定义",
        section_number="9.2",
        limit=5,
    )

    assert items
    assert "不良事件" in items[0]["text"]
    assert "不一定" in items[0]["text"]
    assert "因果关系" in items[0]["text"]
    assert not items[0]["text"].startswith("治疗期出现的不良事件")


def test_company_corpus_consent_before_procedure_returns_the_actual_rule():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "签署知情同意前 不可进行试验相关程序",
        section_heading="知情同意过程",
        section_number="11.2",
        limit=5,
    )

    assert items
    assert "签署知情同意书前" in items[0]["text"]
    assert "不可" in items[0]["text"]
    assert "试验相关程序" in items[0]["text"]


def test_company_corpus_reassembles_drug_accountability_lifecycle():
    service = MedicalWritingCompanyCorpusService()
    items = service.search(
        "试验药物 接收 储存 发放 回收 销毁",
        section_heading="试验药物管理",
        section_number="6.6",
        limit=5,
    )

    assert items
    assert items[0]["source_file"].startswith("CMS-D017Ⅰ期")
    assert len(items[0]["source_entry_ids"]) >= 3
    assert all(
        re.search(pattern, items[0]["text"])
        for pattern in (r"接收|收到", r"储存|贮存|保存", r"发放|分发", r"回收|返还", r"销毁|统一处理")
    )


def test_revision_source_selection_uses_authoring_journey_project_context():
    corpus = MedicalWritingCompanyCorpusService()

    class JourneyStub:
        @staticmethod
        def has_project(project_id: str) -> bool:
            return project_id == "proj_ra"

        @staticmethod
        def get(project_id: str):
            assert project_id == "proj_ra"
            return SimpleNamespace(
                framing=SimpleNamespace(
                    indication="类风湿关节炎",
                    study_phase="IIb期",
                )
            )

    revision = MedicalWritingRevisionService(
        repo=object(),
        ai_task_runner=object(),
        company_corpus_service=corpus,
        authoring_journey_service=JourneyStub(),
    )
    definition = corpus.definition()
    protocol = ProtocolDocument(
        document_id="doc_ra",
        project_id="proj_ra",
        protocol_id="RA-001",
        version="V0.1",
        corpus_snapshot_id=definition.snapshot_id,
        corpus_snapshot_version=definition.snapshot_version,
        corpus_snapshot_sha256=definition.snapshot_sha256,
    )
    section = ProtocolSection(
        section_id="section_soa",
        document_id=protocol.document_id,
        heading="研究流程表",
        section_number="1.3",
        template_node_id="m11_1_3_schedule_of_activities",
        interaction_types=["T"],
    )

    sources = revision._company_corpus_sources(
        protocol,
        section,
        "访视 研究阶段 研究日",
        "medical_writing_revision",
    )

    assert len(sources) == 5
    assert sources[0].title.startswith("MY004-RA-2b")
    assert sources[0].project_id == "proj_ra"
    assert sources[0].source_id.startswith("company_corpus:cms_cn_protocol_corpus_20260715_v1:")


def test_revision_source_selection_passes_confirmed_plan_facets_and_exclusions():
    corpus = MedicalWritingCompanyCorpusService()
    captured: dict[str, object] = {}

    class CorpusSpy:
        @staticmethod
        def definition():
            return corpus.definition()

        @staticmethod
        def search(*args, **kwargs):
            captured.update(kwargs)
            return corpus.search(*args, **kwargs)

    class JourneyStub:
        @staticmethod
        def has_project(project_id: str) -> bool:
            return project_id == "proj_plan"

        @staticmethod
        def get(project_id: str):
            assert project_id == "proj_plan"
            return SimpleNamespace(
                framing=SimpleNamespace(
                    indication="类风湿关节炎",
                    study_phase="III期",
                )
            )

    drivers = [
        SimpleNamespace(
            driver_id="route",
            driver_kind="drug_route",
            decision_state="confirmed",
            value_summary="皮下注射",
            projection_targets=["evidence_intent", "ai_candidate_intent"],
        ),
        SimpleNamespace(
            driver_id="interim",
            driver_kind="interim_analysis",
            decision_state="not_applicable",
            value_summary="",
            projection_targets=["evidence_intent"],
        ),
        SimpleNamespace(
            driver_id="ai_only",
            driver_kind="writing_style",
            decision_state="confirmed",
            value_summary="监管中文",
            projection_targets=["ai_candidate_intent"],
        ),
    ]
    manifest = SimpleNamespace(
        projection="evidence_intent",
        not_applicable_module_ids=["interim_analysis"],
    )

    class PlanHelperStub:
        @staticmethod
        def require_confirmed_projection(*, project_id: str, projection_kind: str):
            assert project_id == "proj_plan"
            assert projection_kind == "evidence_intent"
            return SimpleNamespace(
                plan=SimpleNamespace(
                    design_drivers=drivers,
                    projection_manifest=[manifest],
                )
            )

    revision = MedicalWritingRevisionService(
        repo=object(),
        ai_task_runner=object(),
        company_corpus_service=CorpusSpy(),
        authoring_journey_service=JourneyStub(),
        plan_consumption_helper=PlanHelperStub(),
    )
    definition = corpus.definition()
    protocol = ProtocolDocument(
        document_id="doc_plan",
        project_id="proj_plan",
        protocol_id="RA-PLAN-001",
        version="V0.1",
        corpus_snapshot_id=definition.snapshot_id,
        corpus_snapshot_version=definition.snapshot_version,
        corpus_snapshot_sha256=definition.snapshot_sha256,
    )
    section = ProtocolSection(
        section_id="section_soa_plan",
        document_id=protocol.document_id,
        heading="研究流程表",
        section_number="1.3",
        template_node_id="m11_1_3_schedule_of_activities",
        interaction_types=["T"],
    )

    revision._company_corpus_sources(
        protocol,
        section,
        "访视 研究阶段 研究日",
        "medical_writing_revision",
    )

    assert captured["project_indication"] == "类风湿关节炎"
    assert captured["project_phase"] == "III期"
    assert captured["plan_not_applicable_modules"] == ["interim_analysis"]
    assert captured["plan_design_drivers"] == [
        {
            "driver_id": "route",
            "driver_kind": "drug_route",
            "decision_state": "confirmed",
            "value_summary": "皮下注射",
        },
        {
            "driver_id": "interim",
            "driver_kind": "interim_analysis",
            "decision_state": "not_applicable",
            "value_summary": "",
        },
    ]
